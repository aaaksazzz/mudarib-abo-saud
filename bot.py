import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta

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

# لازم تكون أكبر من 1%
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند صافي +1%
PROTECTION_START = Decimal("1.0")

# نسبة نزول الحماية من أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام الرصيد
BALANCE_USAGE = Decimal("0.999")

STATE_FILE = "bot_data.json"

# إدارة الصفقة
POSITION_CHECK_SECONDS = 10

# فحص السوق بعد عدم وجود صفقة
SCAN_INTERVAL = 30

REQUEST_TIMEOUT = 15


app = Flask(__name__)

session = requests.Session()

symbols = []


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

    "daily_profit": Decimal("0"),
    "weekly_profit": Decimal("0"),
    "monthly_profit": Decimal("0"),

    "daily_trades": 0,
    "weekly_trades": 0,
    "monthly_trades": 0,

    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,

    "trade_history": [],

    "last_update": ""
}


# =========================================================
# Decimal
# =========================================================

def D(value):

    try:
        return Decimal(str(value))
    except:
        return Decimal("0")


def fmt(value, digits=8):

    try:
        return f"{D(value):.{digits}f}"
    except:
        return "0"


def now_str():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# تحويل البيانات للحفظ
# =========================================================

def serialize(obj):

    if isinstance(obj, Decimal):
        return str(obj)

    if isinstance(obj, dict):
        return {
            k: serialize(v)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [
            serialize(v)
            for v in obj
        ]

    return obj


# =========================================================
# تحميل البيانات
# =========================================================

def load_data():

    global state

    if not os.path.exists(STATE_FILE):

        print("ℹ️ لا يوجد ملف بيانات سابق")

        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        for key, value in data.items():

            if key in [
                "balance_usdt",
                "best_change",
                "protection_price",
                "daily_profit",
                "weekly_profit",
                "monthly_profit"
            ]:

                state[key] = D(value)

            else:

                state[key] = value

        print("💾 تم تحميل بيانات البوت")

    except Exception as e:

        print(
            "⚠️ فشل تحميل البيانات:",
            e
        )


# =========================================================
# حفظ البيانات
# =========================================================

def save_data():

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                serialize(state),
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "⚠️ فشل حفظ البيانات:",
            e
        )


# =========================================================
# طلب Binance موقع
# =========================================================

def signed_request(
    method,
    path,
    params=None
):

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(
        time.time() * 1000
    )

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = (
        BASE_URL
        + path
        + "?"
        + query
    )

    if method == "GET":

        response = session.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method == "POST":

        response = session.post(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method == "DELETE":

        response = session.delete(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    else:

        raise Exception(
            "HTTP method غير صحيح"
        )

    if response.status_code >= 400:

        raise Exception(
            f"Binance {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# =========================================================
# Binance عام
# =========================================================

def public_get(
    path,
    params=None
):

    if params is None:
        params = {}

    response = session.get(
        BASE_URL + path,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code >= 400:

        raise Exception(
            f"Binance {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# =========================================================
# فحص اتصال Binance
# =========================================================

def check_binance_connection():

    try:

        result = signed_request(
            "GET",
            "/api/v3/account"
        )

        if "balances" in result:

            state[
                "binance_connected"
            ] = True

            state[
                "binance_message"
            ] = "🟢 Binance مربوط"

            return True

    except Exception as e:

        state[
            "binance_connected"
        ] = False

        state[
            "binance_message"
        ] = "🔴 Binance غير متصل"

        state[
            "last_error"
        ] = str(e)

        print(
            "🚨 Binance:",
            e
        )

    return False


# =========================================================
# تحميل العملات
#
# مهم:
# هذه الدالة لا يتم استدعاؤها أثناء إدارة الصفقة.
# =========================================================

def load_symbols():

    global symbols

    try:

        data = public_get(
            "/api/v3/exchangeInfo"
        )

        new_symbols = []

        for item in data.get(
            "symbols",
            []
        ):

            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get(
                    "isSpotTradingAllowed",
                    False
                )
            ):

                new_symbols.append(
                    item["symbol"]
                )

        symbols = sorted(
            new_symbols
        )

        state[
            "symbols_count"
        ] = len(symbols)

        print(
            f"📚 تم تحميل {len(symbols)} عملة USDT"
        )

    except Exception as e:

        state[
            "last_error"
        ] = str(e)

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

    return D(
        data["price"]
    )


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
# الشموع
# =========================================================

def get_klines(
    symbol,
    interval,
    limit
):

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

def calculate_ema(
    values,
    period
):

    if len(values) < period:
        return None

    multiplier = (
        D("2")
        / D(period + 1)
    )

    ema = (
        sum(values[:period])
        / D(period)
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


def get_ema(
    symbol,
    interval
):

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
# تغير آخر شمعة 15m
# =========================================================

def get_15m_change(symbol):

    candles = get_klines(
        symbol,
        "15m",
        2
    )

    if len(candles) < 2:
        return Decimal("-999")

    previous = D(
        candles[-2][4]
    )

    current = D(
        candles[-1][4]
    )

    if previous <= 0:
        return Decimal("-999")

    return (
        (current - previous)
        / previous
    ) * D("100")


# =========================================================
# فوق EMA200
# =========================================================

def price_above_ema(
    symbol,
    interval
):

    try:

        ema = get_ema(
            symbol,
            interval
        )

        if ema is None:
            return False

        price = get_price(
            symbol
        )

        return price > ema

    except:

        return False


# =========================================================
# فحص السوق
#
# لا يتم تشغيلها إذا فيه صفقة.
# =========================================================

def scan_market():

    state[
        "scan_count"
    ] += 1

    state[
        "last_action"
    ] = "🔍 فحص السوق..."

    candidates = []

    print(
        "\n🔎 بدأ فحص السوق"
    )

    # -----------------------------------------------------
    # أول فلتر:
    # أكثر من 1% فقط
    # -----------------------------------------------------

    for symbol in symbols:

        try:

            change = get_15m_change(
                symbol
            )

            if change <= MIN_CHANGE_15M:
                continue

            candidates.append(
                (
                    symbol,
                    change
                )
            )

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

    state[
        "candidate_count"
    ] = len(candidates)

    if not candidates:

        state[
            "best_candidate"
        ] = ""

        state[
            "best_change"
        ] = Decimal("0")

        state[
            "last_action"
        ] = "⏳ لا توجد عملة فوق +1%"

        print(
            "⏳ لا توجد عملة فوق +1%"
        )

        return None

    # -----------------------------------------------------
    # الأقوى أولاً
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    # -----------------------------------------------------
    # EMA
    # -----------------------------------------------------

    for symbol, change in candidates:

        try:

            print(
                f"🔎 {symbol} | +{change:.2f}%"
            )

            # 15m
            if not price_above_ema(
                symbol,
                "15m"
            ):
                continue

            # 5m
            if not price_above_ema(
                symbol,
                "5m"
            ):
                continue

            # 1m
            if not price_above_ema(
                symbol,
                "1m"
            ):
                continue

            state[
                "best_candidate"
            ] = symbol

            state[
                "best_change"
            ] = change

            state[
                "last_action"
            ] = (
                f"🟢 أفضل فرصة "
                f"{symbol} +{change:.2f}%"
            )

            print(
                f"🟢 أفضل فرصة: "
                f"{symbol} +{change:.2f}%"
            )

            return symbol

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

    state[
        "best_candidate"
    ] = ""

    state[
        "best_change"
    ] = Decimal("0")

    state[
        "last_action"
    ] = (
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

    for item in account.get(
        "balances",
        []
    ):

        if item["asset"] == "USDT":

            return D(
                item["free"]
            )

    return Decimal("0")


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    balance = get_usdt_balance()

    state[
        "balance_usdt"
    ] = balance

    amount = (
        balance
        * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    if amount < Decimal("5"):

        raise Exception(
            f"الرصيد غير كافي: {balance}"
        )

    print(
        f"💰 رصيد USDT: {balance}"
    )

    print(
        f"🟢 شراء {symbol} "
        f"بقيمة {amount} USDT"
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
# تداولاتي
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
# حساب الدخول
# =========================================================

def calculate_entry(symbol):

    trades = get_my_trades(
        symbol
    )

    qty = Decimal("0")
    cost = Decimal("0")

    for trade in trades:

        t_qty = D(
            trade.get(
                "qty",
                "0"
            )
        )

        price = D(
            trade.get(
                "price",
                "0"
            )
        )

        if trade.get(
            "isBuyer",
            False
        ):

            qty += t_qty

            cost += (
                t_qty * price
            )

        else:

            if qty > 0:

                avg = (
                    cost / qty
                )

                qty -= t_qty

                if qty <= 0:

                    qty = Decimal("0")
                    cost = Decimal("0")

                else:

                    cost = (
                        avg * qty
                    )

    if qty <= 0:

        return None, Decimal("0")

    entry = (
        cost / qty
    )

    return entry, qty


# =========================================================
# اكتشاف الصفقة المفتوحة
#
# هذه هي أهم نقطة:
# يتم فحصها قبل أي scan.
# =========================================================

def find_open_position():

    account = signed_request(
        "GET",
        "/api/v3/account"
    )

    candidates = []

    for balance in account.get(
        "balances",
        []
    ):

        asset = balance["asset"]

        if asset == "USDT":
            continue

        free = D(
            balance.get(
                "free",
                "0"
            )
        )

        locked = D(
            balance.get(
                "locked",
                "0"
            )
        )

        qty = free + locked

        if qty <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in symbols:
            continue

        candidates.append(
            (
                symbol,
                qty
            )
        )

    if not candidates:
        return None

    prices = get_all_prices()

    valued = []

    for symbol, qty in candidates:

        price = prices.get(
            symbol
        )

        if not price:
            continue

        value = (
            qty * price
        )

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

    # أكبر مركز
    valued.sort(
        key=lambda x: x[3],
        reverse=True
    )

    symbol, qty, price, value = valued[0]

    entry, trade_qty = calculate_entry(
        symbol
    )

    if entry is None:

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

def calculate_net_profit(
    entry,
    current
):

    if entry <= 0:
        return Decimal("0")

    gross = (
        (current - entry)
        / entry
    ) * D("100")

    # رسوم شراء + بيع
    fees = (
        FEE_RATE
        * D("2")
        * D("100")
    )

    return gross - fees


# =========================================================
# أوامر البيع المفتوحة
# =========================================================

def get_sell_orders(symbol):

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

        state[
            "last_error"
        ] = str(e)

        return []


# =========================================================
# حذف الحماية القديمة
# =========================================================

def cancel_sell_orders(symbol):

    orders = get_sell_orders(
        symbol
    )

    for order in orders:

        try:

            signed_request(
                "DELETE",
                "/api/v3/order",
                {
                    "symbol": symbol,
                    "orderId": order[
                        "orderId"
                    ]
                }
            )

        except Exception as e:

            print(
                "⚠️ فشل حذف الحماية:",
                e
            )


# =========================================================
# إنشاء حماية
# =========================================================

def create_protection(
    symbol,
    qty,
    stop_price
):

    stop_price = stop_price.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    print(
        f"🛡️ إنشاء حماية "
        f"{symbol} عند {stop_price}"
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
                "stopPrice": str(
                    stop_price
                )
            }
        )

        print(
            "✅ تم إنشاء حماية الربح"
        )

        return order

    except Exception as e:

        state[
            "last_error"
        ] = str(e)

        print(
            "🚨 فشل الحماية:",
            e
        )

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

    net = calculate_net_profit(
        entry,
        current
    )

    # قبل +1%
    if net < PROTECTION_START:

        state[
            "protection_active"
        ] = False

        state[
            "protection_price"
        ] = Decimal("0")

        print(
            f"🛡️ الحماية تنتظر "
            f"+1% | الحالي {net:.2f}%"
        )

        return

    # -----------------------------------------------------
    # أعلى سعر × 99.5%
    # -----------------------------------------------------

    trailing = (
        highest
        * (
            D("1")
            - TRAIL_PERCENT / D("100")
        )
    )

    # لازم الحماية تكون فوق الدخول
    minimum = (
        entry
        * (
            D("1.001")
        )
    )

    new_stop = max(
        trailing,
        minimum
    )

    old_stop = D(
        state.get(
            "protection_price",
            "0"
        )
    )

    # لا ننزل الحماية
    if (
        old_stop > 0
        and new_stop <= old_stop
    ):

        state[
            "protection_active"
        ] = True

        print(
            f"🛡️ الحماية ثابتة "
            f"{old_stop}"
        )

        return

    print(
        f"🟢 صافي الربح وصل "
        f"+{net:.2f}%"
    )

    print(
        f"🛡️ رفع الحماية "
        f"إلى {new_stop}"
    )

    # حذف الحماية القديمة
    cancel_sell_orders(
        symbol
    )

    order = create_protection(
        symbol,
        qty,
        new_stop
    )

    if order:

        state[
            "protection_active"
        ] = True

        state[
            "protection_price"
        ] = new_stop

        state[
            "last_action"
        ] = (
            f"🛡️ حماية {symbol} "
            f"{new_stop}"
        )

        save_data()


# =========================================================
# إدارة الصفقة
# =========================================================

def manage_position(position):

    symbol = position[
        "symbol"
    ]

    entry = D(
        position["entry"]
    )

    qty = D(
        position["qty"]
    )

    # استرجاع أعلى سعر السابق
    old_position = state.get(
        "position"
    )

    if old_position:

        highest = max(
            D(
                old_position.get(
                    "highest",
                    position["price"]
                )
            ),
            position["price"]
        )

        opened_at = old_position.get(
            "opened_at",
            now_str()
        )

    else:

        highest = D(
            position["price"]
        )

        opened_at = now_str()

    state[
        "position"
    ] = {
        "symbol": symbol,
        "entry": str(entry),
        "qty": str(qty),
        "current": str(
            position["price"]
        ),
        "highest": str(highest),
        "opened_at": opened_at
    }

    print(
        "\n================================"
    )

    print(
        f"♻️ إدارة الصفقة: {symbol}"
    )

    print(
        f"💵 الدخول: {entry}"
    )

    print(
        "🚫 إيقاف فحص السوق"
    )

    print(
        "================================"
    )

    while True:

        try:

            # ---------------------------------------------
            # السعر الحالي
            # ---------------------------------------------

            current = get_price(
                symbol
            )

            # ---------------------------------------------
            # أعلى سعر
            # ---------------------------------------------

            if current > highest:

                highest = current

                print(
                    f"📈 أعلى سعر جديد: "
                    f"{highest}"
                )

            # ---------------------------------------------
            # الربح
            # ---------------------------------------------

            net = calculate_net_profit(
                entry,
                current
            )

            profit_usdt = (
                current - entry
            ) * qty

            # ---------------------------------------------
            # حماية
            # ---------------------------------------------

            if state[
                "protection_active"
            ]:

                protection = (
                    f"🛡️ "
                    f"{state['protection_price']}"
                )

            else:

                protection = (
                    "⏳ تنتظر +1%"
                )

            # ---------------------------------------------
            # عرض اللوق
            # ---------------------------------------------

            print(
                f"📊 {symbol} | "
                f"السعر {current} | "
                f"صافي {net:.2f}% | "
                f"ربح {profit_usdt:.4f} USDT | "
                f"أعلى {highest} | "
                f"{protection}"
            )

            # ---------------------------------------------
            # تحديث الموقع
            # ---------------------------------------------

            state[
                "position"
            ] = {

                "symbol": symbol,

                "entry": str(entry),

                "qty": str(qty),

                "current": str(current),

                "highest": str(highest),

                "net_profit": str(net),

                "profit_usdt": str(
                    profit_usdt
                ),

                "opened_at": opened_at
            }

            state[
                "last_action"
            ] = (
                f"♻️ يدير {symbol} | "
                f"صافي {net:.2f}%"
            )

            state[
                "last_update"
            ] = now_str()

            # ---------------------------------------------
            # حماية الربح
            # ---------------------------------------------

            update_protection(
                symbol,
                qty,
                entry,
                current,
                highest
            )

            save_data()

            # ---------------------------------------------
            # هل الصفقة ما زالت موجودة؟
            # ---------------------------------------------

            still_open = (
                find_open_position()
            )

            if still_open is None:

                print(
                    f"🏁 انتهت صفقة {symbol}"
                )

                final_profit = (
                    current - entry
                ) * qty

                final_percent = (
                    calculate_net_profit(
                        entry,
                        current
                    )
                )

                record_closed_trade(
                    symbol,
                    entry,
                    current,
                    qty,
                    final_profit,
                    final_percent
                )

                state[
                    "position"
                ] = None

                state[
                    "protection_active"
                ] = False

                state[
                    "protection_price"
                ] = Decimal("0")

                state[
                    "last_action"
                ] = (
                    f"🏁 انتهت {symbol}"
                )

                save_data()

                print(
                    "🔄 الآن فقط يبدأ فحص السوق"
                )

                return

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

            print(
                "🚨 خطأ إدارة الصفقة:",
                e
            )

            time.sleep(10)


# =========================================================
# تسجيل الصفقة
# =========================================================

def record_closed_trade(
    symbol,
    entry,
    exit_price,
    qty,
    profit_usdt,
    profit_percent
):

    history = state.get(
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

    history = history[-1000:]

    state[
        "trade_history"
    ] = history

    state[
        "total_trades"
    ] = len(history)

    state[
        "winning_trades"
    ] = sum(
        1
        for x in history
        if D(
            x["profit_usdt"]
        ) > 0
    )

    state[
        "losing_trades"
    ] = sum(
        1
        for x in history
        if D(
            x["profit_usdt"]
        ) < 0
    )

    update_statistics()

    save_data()


# =========================================================
# الإحصائيات
# =========================================================

def update_statistics():

    today = datetime.now().date()

    week_start = (
        today
        - timedelta(
            days=today.weekday()
        )
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

    for trade in state.get(
        "trade_history",
        []
    ):

        try:

            date = datetime.strptime(
                trade["time"],
                "%Y-%m-%d %H:%M:%S"
            ).date()

        except:

            continue

        profit = D(
            trade.get(
                "profit_usdt",
                "0"
            )
        )

        if date == today:

            daily += profit
            daily_count += 1

        if date >= week_start:

            weekly += profit
            weekly_count += 1

        if date >= month_start:

            monthly += profit
            monthly_count += 1

    state[
        "daily_profit"
    ] = daily

    state[
        "weekly_profit"
    ] = weekly

    state[
        "monthly_profit"
    ] = monthly

    state[
        "daily_trades"
    ] = daily_count

    state[
        "weekly_trades"
    ] = weekly_count

    state[
        "monthly_trades"
    ] = monthly_count


# =========================================================
# مراقبة اتصال Binance
# =========================================================

def connection_monitor():

    while True:

        try:

            check_binance_connection()

        except:

            pass

        time.sleep(60)


# =========================================================
# المحرك
# =========================================================

def trading_engine():

    print(
        "================================"
    )

    print(
        "🤖 مضارب أبو سعود V5"
    )

    print(
        "================================"
    )

    load_data()

    # -----------------------------------------------------
    # تحميل العملات مرة عند التشغيل فقط
    # -----------------------------------------------------

    check_binance_connection()

    load_symbols()

    print(
        "🚀 بدأ محرك التداول"
    )

    while True:

        try:

            # =================================================
            # 1️⃣ الأولوية المطلقة:
            # فحص الصفقة المفتوحة
            # =================================================

            print(
                "\n🔍 فحص الصفقات المفتوحة أولاً..."
            )

            position = (
                find_open_position()
            )

            # =================================================
            # 2️⃣ إذا فيه صفقة:
            # لا Scan
            # =================================================

            if position:

                print(
                    f"♻️ صفقة موجودة: "
                    f"{position['symbol']}"
                )

                print(
                    "🚫 لن يتم فحص العملات"
                )

                manage_position(
                    position
                )

                # بعد انتهاء الصفقة
                # يرجع لأول خطوة
                continue

            # =================================================
            # 3️⃣ لا توجد صفقة
            # =================================================

            print(
                "✅ لا توجد صفقة مفتوحة"
            )

            state[
                "position"
            ] = None

            state[
                "protection_active"
            ] = False

            state[
                "protection_price"
            ] = Decimal("0")

            # =================================================
            # 4️⃣ الآن فقط نحدّث قائمة العملات
            # =================================================

            print(
                "📚 لا توجد صفقة → تحديث العملات"
            )

            load_symbols()

            # =================================================
            # 5️⃣ فحص السوق
            # =================================================

            symbol = scan_market()

            if not symbol:

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # =================================================
            # 6️⃣ تأكيد عدم وجود صفقة
            # =================================================

            position = (
                find_open_position()
            )

            if position:

                print(
                    "⚠️ ظهرت صفقة قبل الدخول"
                )

                continue

            # =================================================
            # 7️⃣ تنفيذ الشراء
            # =================================================

            print(
                f"🎯 الدخول في {symbol}"
            )

            state[
                "last_action"
            ] = (
                f"🟢 شراء {symbol}"
            )

            market_buy(
                symbol
            )

            # =================================================
            # 8️⃣ انتظار ظهور الصفقة
            # =================================================

            time.sleep(2)

            position = (
                find_open_position()
            )

            if not position:

                print(
                    "⚠️ لم يتم اكتشاف الصفقة"
                )

                state[
                    "last_error"
                ] = (
                    "تم تنفيذ الشراء "
                    "لكن لم يتم اكتشاف المركز"
                )

                time.sleep(5)

                continue

            # =================================================
            # 9️⃣ إدارة الصفقة
            # =================================================

            manage_position(
                position
            )

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

            print(
                "🚨 خطأ بالمحرك:",
                e
            )

            time.sleep(10)


# =========================================================
# Dashboard
# =========================================================

HTML = """
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1.0">

<title>مضارب أبو سعود V5</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    background: #0b0f14;

    color: #fff;

    font-family:
        Arial,
        Tahoma,
        sans-serif;
}

.container {

    max-width: 1100px;

    margin: auto;

    padding: 18px;
}

.header {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 18px;

    padding: 22px;

    text-align: center;

    margin-bottom: 15px;
}

.header h1 {

    margin: 0 0 8px;

    font-size: 26px;
}

.header p {

    margin: 0;

    color: #8d9aa8;
}

.grid {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(180px, 1fr)
        );

    gap: 12px;

    margin-bottom: 15px;
}

.card {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 16px;

    padding: 18px;
}

.label {

    color: #8d9aa8;

    font-size: 13px;

    margin-bottom: 9px;
}

.value {

    font-size: 21px;

    font-weight: bold;

    word-break: break-word;
}

.big {

    font-size: 31px;
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

.status {

    background: #111820;

    border: 1px solid #202a35;

    border-radius: 16px;

    padding: 18px;
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

    border-bottom: 0;
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

<p>
Binance Spot — إدارة الصفقة
</p>

</div>


<div class="grid">


<div class="card">

<div class="label">
الصفقة الحالية
</div>

<div
id="symbol"
class="value blue">
لا توجد
</div>

</div>


<div class="card">

<div class="label">
حالة الإدارة
</div>

<div
id="management"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
صافي الربح
</div>

<div
id="profit"
class="value big">
0.00%
</div>

</div>


<div class="card">

<div class="label">
ربح USDT
</div>

<div
id="profit_usdt"
class="value">
0.0000
</div>

</div>


<div class="card">

<div class="label">
الدخول
</div>

<div
id="entry"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
السعر الحالي
</div>

<div
id="current"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
أعلى سعر
</div>

<div
id="highest"
class="value">
-
</div>

</div>


<div class="card">

<div class="label">
حماية الربح
</div>

<div
id="protection"
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

<div
id="daily"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
ربح الأسبوع
</div>

<div
id="weekly"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
ربح الشهر
</div>

<div
id="monthly"
class="value">
0.0000 USDT
</div>

</div>


<div class="card">

<div class="label">
الرصيد
</div>

<div
id="balance"
class="value">
0.0000 USDT
</div>

</div>


</div>


<div class="grid">


<div class="card">

<div class="label">
إجمالي الصفقات
</div>

<div
id="total"
class="value">
0
</div>

</div>


<div class="card">

<div class="label">
الرابحة
</div>

<div
id="wins"
class="value green">
0
</div>

</div>


<div class="card">

<div class="label">
الخاسرة
</div>

<div
id="losses"
class="value red">
0
</div>

</div>


<div class="card">

<div class="label">
نسبة النجاح
</div>

<div
id="winrate"
class="value">
0%
</div>

</div>


</div>


<div class="status">


<div class="row">

<span>Binance</span>

<strong
id="binance">
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

<span>عملات USDT</span>

<strong
id="symbols">
0
</strong>

</div>


<div class="row">

<span>فوق +1%</span>

<strong
id="candidates">
0
</strong>

</div>


<div class="row">

<span>أفضل مرشح</span>

<strong
id="best">
-
</strong>

</div>


<div class="row">

<span>عدد الفحوصات</span>

<strong
id="scans">
0
</strong>

</div>


<div class="row">

<span>آخر إجراء</span>

<strong
id="action">
-
</strong>

</div>


<div class="row">

<span>آخر خطأ</span>

<strong
id="error">
لا يوجد
</strong>

</div>


</div>


<div class="footer">

آخر تحديث:
<span id="updated">
-
</span>

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

        const r =
            await fetch("/api/status");

        const d =
            await r.json();

        const p =
            d.position;


        document.getElementById(
            "symbol"
        ).innerText =
            p
            ? p.symbol
            : "لا توجد";


        document.getElementById(
            "management"
        ).innerText =
            p
            ? "🟢 يدير الصفقة"
            : "⚪ لا توجد صفقة";


        document.getElementById(
            "profit"
        ).innerText =
            p
            ? percent(p.net_profit)
            : "0.00%";


        document.getElementById(
            "profit_usdt"
        ).innerText =
            p
            ? money(p.profit_usdt)
              + " USDT"
            : "0.0000 USDT";


        document.getElementById(
            "entry"
        ).innerText =
            p
            ? p.entry
            : "-";


        document.getElementById(
            "current"
        ).innerText =
            p
            ? p.current
            : "-";


        document.getElementById(
            "highest"
        ).innerText =
            p
            ? p.highest
            : "-";


        document.getElementById(
            "protection"
        ).innerText =
            d.protection_active
            ? "🛡️ "
              + d.protection_price
            : "⏳ تنتظر +1%";


        document.getElementById(
            "daily"
        ).innerText =
            money(d.daily_profit)
            + " USDT";


        document.getElementById(
            "weekly"
        ).innerText =
            money(d.weekly_profit)
            + " USDT";


        document.getElementById(
            "monthly"
        ).innerText =
            money(d.monthly_profit)
            + " USDT";


        document.getElementById(
            "balance"
        ).innerText =
            money(d.balance_usdt)
            + " USDT";


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


        let wr = 0;

        if (d.total_trades > 0) {

            wr =
                (
                    d.winning_trades
                    /
                    d.total_trades
                ) * 100;
        }


        document.getElementById(
            "winrate"
        ).innerText =
            wr.toFixed(2)
            + "%";


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
              + percent(
                    d.best_change
                )
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
            d.last_error
            || "لا يوجد";


        document.getElementById(
            "updated"
        ).innerText =
            d.last_update
            || "-";

    }

    catch (e) {

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
# الصفحة
# =========================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


# =========================================================
# API
# =========================================================

@app.route("/api/status")
def api_status():

    update_statistics()

    data = serialize(
        dict(state)
    )

    return jsonify(data)


# =========================================================
# Flask
# =========================================================

def start_flask():

    print(
        f"🌐 الموقع يعمل على {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )


# =========================================================
# التشغيل
# =========================================================

if __name__ == "__main__":

    # الموقع
    threading.Thread(
        target=start_flask,
        daemon=True
    ).start()

    # مراقبة Binance
    threading.Thread(
        target=connection_monitor,
        daemon=True
    ).start()

    # التداول
    trading_engine()
