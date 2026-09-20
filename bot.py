import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, render_template_string


# =========================================================
# 🤖 مضارب أبو سعود V5
# Binance Spot
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"

PORT = int(os.getenv("PORT", "10000"))

FEE_RATE = Decimal("0.001")

EMA_PERIOD = 200

# لازم تكون الحركة أكبر من 1%
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند صافي +1%
PROTECTION_START = Decimal("1.0")

# مسافة الحماية من أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# يستخدم 99.9% من الرصيد
BALANCE_USAGE = Decimal("0.999")

STATE_FILE = "bot_data.json"

# فحص وإدارة الصفقة
POSITION_CHECK_SECONDS = 10

# فحص السوق
SCAN_INTERVAL = 30

REQUEST_TIMEOUT = 15


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# الحالة
# =========================================================

state = {
    "running": True,

    "binance_connected": False,
    "binance_message": "🔴 Binance غير مربوط",

    "position": None,

    "balance_usdt": Decimal("0"),

    "symbols_count": 0,
    "candidate_count": 0,
    "best_candidate": "",
    "best_change": Decimal("0"),

    "scan_count": 0,

    "last_action": "تشغيل البوت...",
    "last_error": "",

    "protection_active": False,
    "protection_price": Decimal("0"),

    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,

    "daily_profit": Decimal("0"),
    "weekly_profit": Decimal("0"),
    "monthly_profit": Decimal("0"),

    "daily_trades": 0,
    "weekly_trades": 0,
    "monthly_trades": 0,

    "last_update": "",
}


symbols = []

session = requests.Session()


# =========================================================
# أدوات Decimal
# =========================================================

def D(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def fmt(value, digits=8):
    try:
        return f"{D(value):.{digits}f}"
    except Exception:
        return "0"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# حفظ البيانات
# =========================================================

def serialize(obj):
    if isinstance(obj, Decimal):
        return str(obj)

    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [serialize(v) for v in obj]

    return obj


def load_data():
    global state

    if not os.path.exists(STATE_FILE):
        print("ℹ️ لا يوجد ملف بيانات سابق")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in data.items():

            if key in [
                "balance_usdt",
                "best_change",
                "protection_price",
                "daily_profit",
                "weekly_profit",
                "monthly_profit",
            ]:
                state[key] = D(value)

            else:
                state[key] = value

        print("💾 تم تحميل بيانات البوت")

    except Exception as e:
        print("⚠️ خطأ تحميل البيانات:", e)


def save_data():
    try:
        data = serialize(state)

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        print("⚠️ خطأ حفظ البيانات:", e)


# =========================================================
# توقيع Binance
# =========================================================

def signed_request(method, path, params=None):
    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)

    query = urllib.parse.urlencode(params, doseq=True)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path + "?" + query

    try:

        if method == "GET":
            r = session.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

        elif method == "POST":
            r = session.post(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

        elif method == "DELETE":
            r = session.delete(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

        else:
            raise Exception("HTTP method غير معروف")

        if r.status_code >= 400:
            raise Exception(
                f"Binance {r.status_code}: {r.text}"
            )

        return r.json()

    except Exception as e:

        state["binance_connected"] = False
        state["binance_message"] = "🔴 Binance غير متصل"
        state["last_error"] = str(e)

        raise


# =========================================================
# Binance GET عام
# =========================================================

def public_get(path, params=None):

    if params is None:
        params = {}

    r = session.get(
        BASE_URL + path,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code >= 400:
        raise Exception(
            f"Binance {r.status_code}: {r.text}"
        )

    return r.json()


# =========================================================
# اختبار اتصال Binance
# =========================================================

def check_binance_connection():

    try:

        account = signed_request(
            "GET",
            "/api/v3/account"
        )

        if account and "balances" in account:

            state["binance_connected"] = True
            state["binance_message"] = "🟢 Binance مربوط"

            print("🟢 Binance مربوط بالحساب")

            return True

    except Exception as e:

        state["binance_connected"] = False
        state["binance_message"] = "🔴 Binance غير مربوط"

        print("🚨 فشل Binance:", e)

        return False

    return False


# =========================================================
# تحميل كل عملات USDT
# =========================================================

def load_symbols():

    global symbols

    try:

        data = public_get(
            "/api/v3/exchangeInfo"
        )

        result = []

        for s in data.get("symbols", []):

            if (
                s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
                and s.get("isSpotTradingAllowed", False)
            ):
                result.append(s["symbol"])

        symbols = sorted(result)

        state["symbols_count"] = len(symbols)

        print(
            f"📚 تم تحميل {len(symbols)} عملة USDT"
        )

    except Exception as e:

        state["last_error"] = str(e)

        print(
            "🚨 فشل تحميل العملات:",
            e
        )


# =========================================================
# السعر
# =========================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return D(data["price"])


# =========================================================
# كل الأسعار
# =========================================================

def get_all_prices():

    data = public_get(
        "/api/v3/ticker/price"
    )

    return {
        x["symbol"]: D(x["price"])
        for x in data
    }


# =========================================================
# Klines
# =========================================================

def get_klines(symbol, interval, limit=205):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = D("2") / D(period + 1)

    ema = sum(values[:period]) / D(period)

    for price in values[period:]:

        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


def get_ema(symbol, interval):

    candles = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    closes = [
        D(x[4])
        for x in candles
    ]

    return calculate_ema(
        closes,
        EMA_PERIOD
    )


# =========================================================
# تغير 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    candles = get_klines(
        symbol,
        "15m",
        2
    )

    if len(candles) < 2:
        return Decimal("-999")

    previous_close = D(candles[-2][4])
    current_close = D(candles[-1][4])

    if previous_close <= 0:
        return Decimal("-999")

    change = (
        (current_close - previous_close)
        / previous_close
    ) * D("100")

    return change


# =========================================================
# فحص هل السعر فوق EMA200
# =========================================================

def above_ema200(symbol, interval):

    try:

        ema = get_ema(
            symbol,
            interval
        )

        if ema is None:
            return False

        price = get_price(symbol)

        return price > ema

    except Exception:

        return False


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    state["scan_count"] += 1
    state["last_action"] = "🔍 فحص جميع العملات..."

    candidates = []

    print(
        f"\n🔎 فحص السوق رقم {state['scan_count']}"
    )

    # -----------------------------------------------------
    # المرحلة الأولى:
    # الحركة أكبر من 1%
    # -----------------------------------------------------

    for symbol in symbols:

        try:

            change = get_15m_change(symbol)

            # مهم:
            # 1.00% لا تدخل
            # 1.01% تدخل
            if change <= MIN_CHANGE_15M:
                continue

            candidates.append(
                (symbol, change)
            )

        except Exception as e:

            state["last_error"] = str(e)

    state["candidate_count"] = len(candidates)

    if not candidates:

        state["best_candidate"] = ""
        state["best_change"] = Decimal("0")

        state["last_action"] = (
            "⏳ لا توجد عملة أعلى من +1%"
        )

        print(
            "⏳ لا توجد عملة تحقق شرط +1%"
        )

        return None

    # -----------------------------------------------------
    # الأقوى أولاً
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    print(
        f"📊 المرشحين فوق +1%: {len(candidates)}"
    )

    # -----------------------------------------------------
    # فحص EMA
    # -----------------------------------------------------

    for symbol, change in candidates:

        try:

            print(
                f"🔎 {symbol} | 15m +{change:.2f}%"
            )

            # 15m
            if not above_ema200(
                symbol,
                "15m"
            ):
                continue

            # 5m
            if not above_ema200(
                symbol,
                "5m"
            ):
                continue

            # 1m
            if not above_ema200(
                symbol,
                "1m"
            ):
                continue

            state["best_candidate"] = symbol
            state["best_change"] = change

            state["last_action"] = (
                f"🟢 أقوى فرصة: {symbol} +{change:.2f}%"
            )

            print(
                f"🟢 أفضل فرصة: {symbol} +{change:.2f}%"
            )

            return symbol

        except Exception as e:

            state["last_error"] = str(e)

    state["best_candidate"] = ""
    state["best_change"] = Decimal("0")

    state["last_action"] = (
        "⏳ لا توجد عملة اجتازت EMA200"
    )

    return None


# =========================================================
# رصيد USDT
# =========================================================

def get_usdt_balance():

    account = signed_request(
        "GET",
        "/api/v3/account"
    )

    for balance in account.get("balances", []):

        if balance["asset"] == "USDT":

            return D(
                balance["free"]
            )

    return Decimal("0")


# =========================================================
# شراء Market
# =========================================================

def market_buy(symbol):

    balance = get_usdt_balance()

    state["balance_usdt"] = balance

    amount = (
        balance * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    if amount < Decimal("5"):
        raise Exception(
            f"رصيد USDT غير كافي: {balance}"
        )

    print(
        f"💰 الرصيد: {balance} USDT"
    )

    print(
        f"🟢 شراء {symbol} بقيمة {amount} USDT"
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": str(amount)
        }
    )

    print(
        "✅ تم تنفيذ الشراء"
    )

    return order


# =========================================================
# جلب تداولات العملة
# =========================================================

def get_my_trades(symbol):

    return signed_request(
        "GET",
        "/api/v3/myTrades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )


# =========================================================
# حساب متوسط الدخول
# =========================================================

def calculate_entry_from_trades(symbol):

    trades = get_my_trades(symbol)

    total_qty = Decimal("0")
    total_cost = Decimal("0")

    for trade in trades:

        qty = D(
            trade.get("qty", "0")
        )

        price = D(
            trade.get("price", "0")
        )

        is_buyer = trade.get(
            "isBuyer",
            False
        )

        if is_buyer:

            total_qty += qty
            total_cost += (
                qty * price
            )

        else:

            # بيع يخصم من الكمية
            if total_qty > 0:

                avg = (
                    total_cost / total_qty
                )

                total_qty -= qty

                if total_qty <= 0:
                    total_qty = Decimal("0")
                    total_cost = Decimal("0")

                else:
                    total_cost = (
                        avg * total_qty
                    )

    if total_qty <= 0:
        return None, Decimal("0")

    entry = (
        total_cost / total_qty
    )

    return entry, total_qty


# =========================================================
# اكتشاف الصفقة المفتوحة
# =========================================================

def find_open_position():

    account = signed_request(
        "GET",
        "/api/v3/account"
    )

    balances = account.get(
        "balances",
        []
    )

    # -----------------------------------------------------
    # نبحث عن أكبر أصل غير USDT
    # -----------------------------------------------------

    candidates = []

    for balance in balances:

        asset = balance["asset"]

        if asset == "USDT":
            continue

        free = D(
            balance.get("free", "0")
        )

        locked = D(
            balance.get("locked", "0")
        )

        qty = free + locked

        if qty <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in symbols:
            continue

        candidates.append(
            (symbol, qty)
        )

    if not candidates:
        return None

    # -----------------------------------------------------
    # الأسعار مرة واحدة
    # -----------------------------------------------------

    prices = get_all_prices()

    valued = []

    for symbol, qty in candidates:

        price = prices.get(symbol)

        if not price:
            continue

        value = qty * price

        if value >= Decimal("5"):

            valued.append(
                (
                    symbol,
                    qty,
                    price,
                    value
                )
            )

    if not valued:
        return None

    # أكبر صفقة
    valued.sort(
        key=lambda x: x[3],
        reverse=True
    )

    symbol, qty, price, value = valued[0]

    # -----------------------------------------------------
    # حساب الدخول
    # -----------------------------------------------------

    entry, trade_qty = calculate_entry_from_trades(
        symbol
    )

    if entry is None:

        # إذا تعذر حساب الدخول
        # نستخدم السعر الحالي كحل مؤقت
        entry = price
        trade_qty = qty

    return {
        "symbol": symbol,
        "qty": qty,
        "entry": entry,
        "price": price,
        "value": value
    }


# =========================================================
# صافي الربح
# =========================================================

def calculate_profit(entry, current):

    if entry <= 0:
        return Decimal("0")

    gross = (
        (current - entry)
        / entry
    ) * D("100")

    # شراء + بيع
    fees = FEE_RATE * D("2") * D("100")

    net = gross - fees

    return net


# =========================================================
# حماية الربح
# =========================================================

def get_existing_sell_orders(symbol):

    try:

        orders = signed_request(
            "GET",
            "/api/v3/openOrders",
            {
                "symbol": symbol
            }
        )

        return [
            x for x in orders
            if x.get("side") == "SELL"
        ]

    except Exception as e:

        state["last_error"] = str(e)

        return []


# =========================================================
# حذف حماية قديمة
# =========================================================

def cancel_sell_orders(symbol):

    orders = get_existing_sell_orders(
        symbol
    )

    for order in orders:

        try:

            signed_request(
                "DELETE",
                "/api/v3/order",
                {
                    "symbol": symbol,
                    "orderId": order["orderId"]
                }
            )

            print(
                f"🗑️ حذف حماية قديمة: {order['orderId']}"
            )

        except Exception as e:

            print(
                "⚠️ فشل حذف الحماية:",
                e
            )


# =========================================================
# إنشاء حماية الربح
# =========================================================

def create_profit_protection(
    symbol,
    qty,
    stop_price
):

    # نلغي أي حماية بيع قديمة
    cancel_sell_orders(symbol)

    # السعر لازم يكون تحت السعر الحالي
    # وسيكون فوق الدخول إذا تحقق الربح
    stop_price = stop_price.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    print(
        f"🛡️ إنشاء حماية {symbol}"
    )

    print(
        f"🔒 Stop Price: {stop_price}"
    )

    try:

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "STOP_LOSS",
                "quantity": str(
                    qty.quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_DOWN
                    )
                ),
                "stopPrice": str(stop_price)
            }
        )

        print(
            f"✅ تم إنشاء حماية الربح: {stop_price}"
        )

        return order

    except Exception as e:

        print(
            "🚨 فشل إنشاء حماية الربح:",
            e
        )

        state["last_error"] = str(e)

        return None


# =========================================================
# تحديث الحماية
# =========================================================

def update_protection(
    symbol,
    qty,
    entry,
    current,
    highest
):

    net_profit = calculate_profit(
        entry,
        current
    )

    # -----------------------------------------------------
    # لم يصل +1%
    # -----------------------------------------------------

    if net_profit < PROTECTION_START:

        state["protection_active"] = False
        state["protection_price"] = Decimal("0")

        print(
            f"🛡️ الحماية تنتظر | صافي {net_profit:.2f}%"
        )

        return

    # -----------------------------------------------------
    # نحسب وقف متحرك
    # -----------------------------------------------------

    trailing_stop = (
        highest
        * (
            D("1")
            - TRAIL_PERCENT / D("100")
        )
    )

    # لازم الحماية تكون فوق الدخول
    minimum_profit_stop = (
        entry
        * (
            D("1")
            + D("0.10") / D("100")
        )
    )

    new_stop = max(
        trailing_stop,
        minimum_profit_stop
    )

    old_stop = D(
        state.get(
            "protection_price",
            "0"
        )
    )

    # -----------------------------------------------------
    # لا ننزل الحماية
    # -----------------------------------------------------

    if old_stop > 0 and new_stop <= old_stop:

        state["protection_active"] = True

        print(
            f"🛡️ الحماية ثابتة: {old_stop}"
        )

        return

    print(
        f"🟢 وصل صافي الربح +{net_profit:.2f}%"
    )

    print(
        f"🛡️ رفع حماية الربح إلى {new_stop}"
    )

    order = create_profit_protection(
        symbol,
        qty,
        new_stop
    )

    if order:

        state["protection_active"] = True
        state["protection_price"] = new_stop

        state["last_action"] = (
            f"🛡️ حماية {symbol}: {new_stop}"
        )

        save_data()


# =========================================================
# تحديث إحصائيات
# =========================================================

def update_statistics():

    try:

        today = datetime.now().date()

        week_start = (
            today
            - timedelta(days=today.weekday())
        )

        month_start = today.replace(
            day=1
        )

        daily = Decimal("0")
        weekly = Decimal("0")
        monthly = Decimal("0")

        daily_count = 0
        weekly_count = 0
        monthly_count = 0

        if os.path.exists(STATE_FILE):

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            history = data.get(
                "trade_history",
                []
            )

            for trade in history:

                try:

                    date_value = datetime.fromisoformat(
                        trade["time"]
                    ).date()

                except Exception:
                    continue

                profit = D(
                    trade.get(
                        "profit_usdt",
                        "0"
                    )
                )

                if date_value == today:

                    daily += profit
                    daily_count += 1

                if date_value >= week_start:

                    weekly += profit
                    weekly_count += 1

                if date_value >= month_start:

                    monthly += profit
                    monthly_count += 1

        state["daily_profit"] = daily
        state["weekly_profit"] = weekly
        state["monthly_profit"] = monthly

        state["daily_trades"] = daily_count
        state["weekly_trades"] = weekly_count
        state["monthly_trades"] = monthly_count

    except Exception as e:

        state["last_error"] = str(e)


# =========================================================
# تسجيل الصفقة المغلقة
# =========================================================

def record_closed_trade(
    symbol,
    entry,
    exit_price,
    qty,
    profit_usdt,
    profit_percent
):

    try:

        history = []

        if os.path.exists(STATE_FILE):

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

                history = data.get(
                    "trade_history",
                    []
                )

        history.append({

            "time": now_str(),

            "symbol": symbol,

            "entry": str(entry),

            "exit": str(exit_price),

            "qty": str(qty),

            "profit_usdt": str(
                profit_usdt
            ),

            "profit_percent": str(
                profit_percent
            )

        })

        # آخر 1000 صفقة
        history = history[-1000:]

        state["trade_history"] = history

        state["total_trades"] = len(
            history
        )

        state["winning_trades"] = sum(
            1
            for x in history
            if D(x["profit_usdt"]) > 0
        )

        state["losing_trades"] = sum(
            1
            for x in history
            if D(x["profit_usdt"]) < 0
        )

        save_data()

        update_statistics()

    except Exception as e:

        state["last_error"] = str(e)

        print(
            "⚠️ خطأ تسجيل الصفقة:",
            e
        )


# =========================================================
# إدارة الصفقة
# =========================================================

def manage_position(position):

    symbol = position["symbol"]

    entry = D(
        position["entry"]
    )

    qty = D(
        position["qty"]
    )

    highest = D(
        state.get(
            "position",
            {}
        ).get(
            "highest",
            position["price"]
        )
    )

    state["position"] = {
        "symbol": symbol,
        "entry": str(entry),
        "qty": str(qty),
        "current": str(position["price"]),
        "highest": str(highest),
        "opened_at": state.get(
            "position",
            {}
        ).get(
            "opened_at",
            now_str()
        )
    }

    print(
        f"♻️ إدارة {symbol} | Entry {entry}"
    )

    while True:

        try:

            # -------------------------------------------------
            # السعر الحالي
            # -------------------------------------------------

            current = get_price(
                symbol
            )

            # -------------------------------------------------
            # أعلى سعر
            # -------------------------------------------------

            if current > highest:

                highest = current

                print(
                    f"📈 أعلى سعر جديد: {highest}"
                )

            # -------------------------------------------------
            # الربح
            # -------------------------------------------------

            net_profit = calculate_profit(
                entry,
                current
            )

            profit_usdt = (
                (current - entry)
                * qty
            )

            # -------------------------------------------------
            # الحالة
            # -------------------------------------------------

            if net_profit >= PROTECTION_START:

                protection_text = (
                    f"🛡️ {fmt(state.get('protection_price', 0), 8)}"
                )

            else:

                protection_text = (
                    "⏳ تنتظر +1%"
                )

            print(
                f"📊 {symbol} | "
                f"{current} | "
                f"صافي {net_profit:.2f}% | "
                f"ربح {profit_usdt:.4f} USDT | "
                f"حماية {protection_text}"
            )

            state["position"] = {

                "symbol": symbol,

                "entry": str(entry),

                "qty": str(qty),

                "current": str(current),

                "highest": str(highest),

                "net_profit": str(
                    net_profit
                ),

                "profit_usdt": str(
                    profit_usdt
                ),

                "opened_at": state[
                    "position"
                ].get(
                    "opened_at",
                    now_str()
                )
            }

            state["last_action"] = (
                f"♻️ إدارة {symbol} | "
                f"صافي {net_profit:.2f}%"
            )

            state["last_update"] = now_str()

            # -------------------------------------------------
            # حماية الربح
            # -------------------------------------------------

            update_protection(
                symbol,
                qty,
                entry,
                current,
                highest
            )

            save_data()

            # -------------------------------------------------
            # نتحقق هل الصفقة لا تزال موجودة
            # -------------------------------------------------

            still_open = find_open_position()

            if still_open is None:

                print(
                    f"🏁 انتهت صفقة {symbol}"
                )

                exit_price = current

                final_profit = (
                    exit_price - entry
                ) * qty

                final_percent = calculate_profit(
                    entry,
                    exit_price
                )

                record_closed_trade(
                    symbol,
                    entry,
                    exit_price,
                    qty,
                    final_profit,
                    final_percent
                )

                state["position"] = None

                state["protection_active"] = False

                state["protection_price"] = Decimal("0")

                state["last_action"] = (
                    f"🏁 انتهت {symbol} | "
                    f"{final_percent:.2f}%"
                )

                save_data()

                print(
                    "🔄 رجوع لفحص الصفقات المفتوحة أولاً"
                )

                return

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            state["last_error"] = str(e)

            print(
                "🚨 خطأ إدارة الصفقة:",
                e
            )

            time.sleep(
                POSITION_CHECK_SECONDS
            )


# =========================================================
# المحرك الرئيسي
# =========================================================

def trading_engine():

    print(
        "🤖 مضارب أبو سعود V5"
    )

    load_data()

    check_binance_connection()

    load_symbols()

    print(
        "🚀 بدأ محرك مضارب أبو سعود"
    )

    while True:

        try:

            # =================================================
            # 1️⃣ أول شيء دائمًا:
            # فحص الصفقات المفتوحة
            # =================================================

            print(
                "\n🔍 فحص الصفقات المفتوحة أولاً..."
            )

            position = find_open_position()

            # =================================================
            # إذا فيه صفقة:
            # لا نفحص السوق
            # =================================================

            if position:

                print(
                    f"♻️ صفقة موجودة: "
                    f"{position['symbol']}"
                )

                manage_position(
                    position
                )

                # بعد إغلاقها يرجع للبداية
                continue

            # =================================================
            # لا توجد صفقة
            # =================================================

            print(
                "✅ لا توجد صفقة مفتوحة"
            )

            state["position"] = None

            state["protection_active"] = False

            state["protection_price"] = Decimal("0")

            # =================================================
            # 2️⃣ الآن فقط نفحص السوق
            # =================================================

            symbol = scan_market()

            if not symbol:

                print(
                    "⏳ ما فيه دخول مناسب"
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # =================================================
            # 3️⃣ تأكيد أخير قبل الشراء
            # =================================================

            print(
                f"🎯 فرصة مختارة: {symbol}"
            )

            # نتأكد مرة ثانية ما فيه صفقة
            position = find_open_position()

            if position:

                print(
                    "⚠️ ظهرت صفقة قبل الشراء"
                )

                continue

            # =================================================
            # 4️⃣ شراء
            # =================================================

            state["last_action"] = (
                f"🟢 تنفيذ شراء {symbol}"
            )

            order = market_buy(
                symbol
            )

            # =================================================
            # 5️⃣ ننتظر ظهور الصفقة
            # =================================================

            time.sleep(2)

            position = find_open_position()

            if not position:

                print(
                    "⚠️ لم يتم العثور على الصفقة بعد الشراء"
                )

                state["last_error"] = (
                    "تم الشراء لكن لم يتم اكتشاف الصفقة"
                )

                time.sleep(5)

                continue

            print(
                f"♻️ بدأ إدارة {position['symbol']}"
            )

            # =================================================
            # 6️⃣ إدارة الصفقة
            # =================================================

            manage_position(
                position
            )

        except Exception as e:

            state["last_error"] = str(e)

            state["last_action"] = (
                "⚠️ المحرك مستمر بعد خطأ"
            )

            print(
                "🚨 خطأ بالمحرك:",
                e
            )

            time.sleep(10)


# =========================================================
# تحديث اتصال Binance كل دقيقة
# =========================================================

def connection_monitor():

    while True:

        try:

            check_binance_connection()

        except Exception:
            pass

        time.sleep(60)


# =========================================================
# Dashboard
# =========================================================

HTML = """
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>مضارب أبو سعود V5</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    font-family:
    Arial,
    Tahoma,
    sans-serif;

    background:
    #0b0f14;

    color: #ffffff;
}

.container {

    max-width: 1100px;

    margin: auto;

    padding: 20px;
}

.header {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 18px;

    padding: 22px;

    margin-bottom: 15px;

    text-align: center;
}

.header h1 {

    margin: 0 0 8px;

    font-size: 25px;
}

.header p {

    margin: 0;

    color: #9ba8b5;
}

.grid {

    display: grid;

    grid-template-columns:
    repeat(auto-fit, minmax(180px, 1fr));

    gap: 12px;

    margin-bottom: 15px;
}

.card {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 16px;

    padding: 18px;

    min-height: 110px;
}

.label {

    color: #8d9aa8;

    font-size: 13px;

    margin-bottom: 10px;
}

.value {

    font-size: 22px;

    font-weight: bold;

    word-break: break-word;
}

.green {

    color: #35d07f;
}

.red {

    color: #ff5d67;
}

.yellow {

    color: #ffc857;
}

.blue {

    color: #55a7ff;
}

.big {

    font-size: 32px;
}

.status {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 16px;

    padding: 18px;

    margin-bottom: 15px;
}

.row {

    display: flex;

    justify-content: space-between;

    gap: 15px;

    padding: 12px 0;

    border-bottom:
    1px solid #202a35;
}

.row:last-child {

    border-bottom: none;
}

.small {

    color: #8d9aa8;

    font-size: 13px;
}

.footer {

    text-align: center;

    color: #65717d;

    font-size: 12px;

    padding: 20px;
}

</style>

</head>

<body>

<div class="container">

<div class="header">

<h1>🤖 مضارب أبو سعود V5</h1>

<p>Binance Spot — إدارة الصفقة والحماية</p>

</div>


<div class="grid">


<div class="card">

<div class="label">
الصفقة الحالية
</div>

<div id="symbol"
class="value blue">
لا توجد
</div>

</div>


<div class="card">

<div class="label">
صافي الربح
</div>

<div id="profit"
class="value big">
0.00%
</div>

</div>


<div class="card">

<div class="label">
ربح USDT
</div>

<div id="profit_usdt"
class="value">
0.0000
</div>

</div>


<div class="card">

<div class="label">
حالة الإدارة
</div>

<div id="management"
class="value green">
متوقف
</div>

</div>


<div class="card">

<div class="label">
سعر الدخول
</div>

<div id="entry"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
السعر الحالي
</div>

<div id="current"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
أعلى سعر
</div>

<div id="highest"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
حماية الربح
</div>

<div id="protection"
class="value yellow">
تنتظر +1%
</div>

</div>


</div>


<div class="grid">


<div class="card">

<div class="label">
ربح اليوم
</div>

<div id="daily"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
ربح الأسبوع
</div>

<div id="weekly"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
ربح الشهر
</div>

<div id="monthly"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
الرصيد USDT
</div>

<div id="balance"
class="value">
0.0000
</div>

</div>


</div>


<div class="grid">


<div class="card">

<div class="label">
إجمالي الصفقات
</div>

<div id="total"
class="value">
0
</div>

</div>


<div class="card">

<div class="label">
صفقات رابحة
</div>

<div id="wins"
class="value green">
0
</div>

</div>


<div class="card">

<div class="label">
صفقات خاسرة
</div>

<div id="losses"
class="value red">
0
</div>

</div>


<div class="card">

<div class="label">
نسبة النجاح
</div>

<div id="winrate"
class="value">
0%
</div>

</div>


</div>


<div class="status">

<div class="row">

<span>Binance</span>

<strong id="binance">
🔴 غير مربوط
</strong>

</div>


<div class="row">

<span>حالة البوت</span>

<strong class="green">
🟢 يعمل
</strong>

</div>


<div class="row">

<span>عدد عملات USDT</span>

<strong id="symbols">
0
</strong>

</div>


<div class="row">

<span>المرشحين فوق +1%</span>

<strong id="candidates">
0
</strong>

</div>


<div class="row">

<span>أفضل مرشح</span>

<strong id="best">
-
</strong>

</div>


<div class="row">

<span>عدد الفحوصات</span>

<strong id="scans">
0
</strong>

</div>


<div class="row">

<span>آخر إجراء</span>

<strong id="action">
-
</strong>

</div>


<div class="row">

<span>آخر خطأ</span>

<strong id="error">
لا يوجد
</strong>

</div>

</div>


<div class="footer">

آخر تحديث:
<span id="updated">-</span>

</div>

</div>


<script>

function money(v) {

    return Number(v || 0)
        .toFixed(4);
}


function percent(v) {

    return Number(v || 0)
        .toFixed(2) + "%";
}


async function update() {

    try {

        const response =
            await fetch("/api/status");

        const d =
            await response.json();


        const p =
            d.position;


        document.getElementById(
            "symbol"
        ).innerText =
            p ? p.symbol : "لا توجد";


        document.getElementById(
            "profit"
        ).innerText =
            p ? percent(p.net_profit) : "0.00%";


        document.getElementById(
            "profit_usdt"
        ).innerText =
            p ? money(p.profit_usdt) + " USDT" : "0.0000";


        document.getElementById(
            "management"
        ).innerText =
            p ? "🟢 يدير الصفقة" : "⚪ لا توجد صفقة";


        document.getElementById(
            "entry"
        ).innerText =
            p ? p.entry : "-";


        document.getElementById(
            "current"
        ).innerText =
            p ? p.current : "-";


        document.getElementById(
            "highest"
        ).innerText =
            p ? p.highest : "-";


        document.getElementById(
            "protection"
        ).innerText =
            d.protection_active
            ? "🛡️ " + d.protection_price
            : "⏳ تنتظر +1%";


        document.getElementById(
            "daily"
        ).innerText =
            money(d.daily_profit) + " USDT";


        document.getElementById(
            "weekly"
        ).innerText =
            money(d.weekly_profit) + " USDT";


        document.getElementById(
            "monthly"
        ).innerText =
            money(d.monthly_profit) + " USDT";


        document.getElementById(
            "balance"
        ).innerText =
            money(d.balance_usdt);


        document.getElementById(
            "total"
        ).innerText =
            d.total_trades;


        document.getElementById(
            "wins"
        ).innerText =
            d.winning_trades;


        document.getElementById(
            "losses"
        ).innerText =
            d.losing_trades;


        document.getElementById(
            "winrate"
        ).innerText =
            Number(d.win_rate || 0)
            .toFixed(2) + "%";


        document.getElementById(
            "binance"
        ).innerText =
            d.binance_message;


        document.getElementById(
            "symbols"
        ).innerText =
            d.symbols_count;


        document.getElementById(
            "candidates"
        ).innerText =
            d.candidate_count;


        document.getElementById(
            "best"
        ).innerText =
            d.best_candidate
            ? d.best_candidate
              + " "
              + percent(d.best_change)
            : "-";


        document.getElementById(
            "scans"
        ).innerText =
            d.scan_count;


        document.getElementById(
            "action"
        ).innerText =
            d.last_action;


        document.getElementById(
            "error"
        ).innerText =
            d.last_error || "لا يوجد";


        document.getElementById(
            "updated"
        ).innerText =
            d.last_update || "-";


    } catch (e) {

        console.log(e);

    }

}


update();

setInterval(
    update,
    3000
);

</script>

</body>

</html>
"""


# =========================================================
# API status
# =========================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    update_statistics()

    data = serialize(
        dict(state)
    )

    total = int(
        data.get(
            "total_trades",
            0
        )
    )

    wins = int(
        data.get(
            "winning_trades",
            0
        )
    )

    if total > 0:

        data["win_rate"] = (
            wins / total
        ) * 100

    else:

        data["win_rate"] = 0

    return jsonify(data)


# =========================================================
# تشغيل Flask
# =========================================================

def start_flask():

    print(
        f"🌐 Flask app على المنفذ {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":

    # Flask
    threading.Thread(
        target=start_flask,
        daemon=True
    ).start()

    # مراقبة اتصال Binance
    threading.Thread(
        target=connection_monitor,
        daemon=True
    ).start()

    # محرك التداول
    trading_engine()
