import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
import requests

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string


# =========================================================
# 🤖 مضارب أبو سعود V6
# Binance Spot + Dashboard
# =========================================================

BASE_URL = "https://api.binance.com"

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

PORT = int(os.getenv("PORT", "10000"))

FEE_RATE = Decimal("0.001")

# الدخول
MIN_CHANGE_15M = Decimal("1.0")

# حماية الربح تبدأ عند +1%
PROTECTION_START = Decimal("1.0")

# مسافة الحماية خلف أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام كامل الرصيد تقريباً
BALANCE_USAGE = Decimal("0.999")

# الفواصل الزمنية
POSITION_CHECK_SECONDS = 10
SCAN_INTERVAL = 30

REQUEST_TIMEOUT = 8


# =========================================================
# الحالة
# =========================================================

app = Flask(__name__)

state_lock = threading.Lock()

state = {
    "running": True,

    "binance_connected": False,
    "binance_message": "جاري الاتصال...",

    "position": None,

    "balance_usdt": 0.0,

    "symbols_count": 0,
    "scan_count": 0,

    "best_candidate": None,

    "last_action": "بدء التشغيل",
    "last_error": "",

    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,

    "total_profit": 0.0,
    "daily_profit": 0.0,
    "weekly_profit": 0.0,
    "monthly_profit": 0.0,

    "daily_trades": 0,
    "weekly_trades": 0,
    "monthly_trades": 0,

    "highest_price": 0.0,
    "protection_price": 0.0,
    "protection_active": False,

    "symbols_loaded": False,
}

symbols = []

last_trade_day = None
last_trade_week = None
last_trade_month = None


# =========================================================
# أدوات عامة
# =========================================================

def log(message):
    print(message, flush=True)


def d(value):
    try:
        return Decimal(str(value))
    except:
        return Decimal("0")


def now_ms():
    return int(time.time() * 1000)


def set_state(key, value):
    with state_lock:
        state[key] = value


def get_state():
    with state_lock:
        return dict(state)


# =========================================================
# Binance API
# =========================================================

session = requests.Session()

if API_KEY:
    session.headers.update({
        "X-MBX-APIKEY": API_KEY
    })


def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    r.raise_for_status()
    return r.json()


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise Exception("BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود")

    params = params or {}

    params["timestamp"] = now_ms()
    params["recvWindow"] = 5000

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE_URL + path + "?" + query

    if method == "GET":
        r = session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

    elif method == "POST":
        r = session.post(
            url,
            timeout=REQUEST_TIMEOUT
        )

    elif method == "DELETE":
        r = session.delete(
            url,
            timeout=REQUEST_TIMEOUT
        )

    else:
        raise Exception("HTTP method غير مدعوم")

    if r.status_code >= 400:
        try:
            error = r.json()
        except:
            error = r.text

        raise Exception(str(error))

    return r.json()


# =========================================================
# اتصال Binance
# =========================================================

def check_binance_connection():
    try:
        data = signed_request(
            "GET",
            "/api/v3/account"
        )

        if "balances" in data:
            set_state("binance_connected", True)
            set_state(
                "binance_message",
                "🟢 Binance مربوط فعلياً"
            )

            return True

        raise Exception("رد Binance غير صحيح")

    except Exception as e:

        set_state("binance_connected", False)
        set_state(
            "binance_message",
            "🔴 Binance غير متصل"
        )

        set_state("last_error", str(e))

        log("⚠️ Binance: " + str(e))

        return False


# =========================================================
# الحساب والرصيد
# =========================================================

def get_account():
    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_usdt_balance():
    try:
        account = get_account()

        for item in account.get("balances", []):
            if item["asset"] == "USDT":
                free = d(item["free"])

                set_state(
                    "balance_usdt",
                    float(free)
                )

                return free

    except Exception as e:
        set_state("last_error", str(e))

    return Decimal("0")


# =========================================================
# اكتشاف الصفقة المفتوحة
# =========================================================

def find_open_position():
    """
    مهم جداً:
    ما نعتمد على قائمة symbols هنا.

    يعني لو فيه صفقة مفتوحة:
    نكتشفها مباشرة من الرصيد
    بدون تحميل 493 عملة.
    """

    try:

        account = get_account()

        balances = account.get("balances", [])

        candidates = []

        # أسعار السوق الحالية
        prices_data = public_get(
            "/api/v3/ticker/price"
        )

        prices = {}

        for item in prices_data:
            prices[item["symbol"]] = d(item["price"])

        for item in balances:

            asset = item["asset"]

            free = d(item["free"])
            locked = d(item["locked"])

            quantity = free + locked

            if quantity <= 0:
                continue

            if asset == "USDT":
                continue

            symbol = asset + "USDT"

            if symbol not in prices:
                continue

            price = prices[symbol]

            value = quantity * price

            # نتجاهل الأرصدة الصغيرة جداً
            if value < Decimal("2"):
                continue

            candidates.append({
                "symbol": symbol,
                "asset": asset,
                "quantity": quantity,
                "price": price,
                "value": value
            })

        if not candidates:
            return None

        # أكبر أصل من ناحية القيمة
        candidates.sort(
            key=lambda x: x["value"],
            reverse=True
        )

        position = candidates[0]

        return position

    except Exception as e:

        set_state("last_error", str(e))

        log(
            "⚠️ خطأ اكتشاف الصفقة: "
            + str(e)
        )

        return None


# =========================================================
# حساب متوسط الدخول
# =========================================================

def calculate_entry(symbol, current_quantity):
    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

        if not trades:
            return None

        # نحاول حساب الكمية الحالية من آخر عمليات الشراء
        buys = []

        for trade in trades:

            if trade.get("isBuyer"):

                qty = d(trade["qty"])
                price = d(trade["price"])
                commission = d(trade.get("commission", "0"))

                buys.append({
                    "qty": qty,
                    "price": price,
                    "commission_asset":
                        trade.get("commissionAsset")
                })

        if not buys:
            return None

        remaining = current_quantity

        total_cost = Decimal("0")
        total_qty = Decimal("0")

        # نبدأ من أحدث شراء
        for trade in reversed(buys):

            if remaining <= 0:
                break

            qty = min(
                trade["qty"],
                remaining
            )

            total_cost += qty * trade["price"]
            total_qty += qty

            remaining -= qty

        if total_qty <= 0:
            return None

        return total_cost / total_qty

    except Exception as e:

        log(
            "⚠️ تعذر حساب الدخول "
            + symbol
            + ": "
            + str(e)
        )

        return None


# =========================================================
# السعر الحالي
# =========================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return d(data["price"])


# =========================================================
# الشموع
# =========================================================

def get_klines(symbol, interval, limit=220):

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

def calculate_ema(values, period=200):

    if len(values) < period:
        return None

    multiplier = Decimal("2") / (
        Decimal(period) + Decimal("1")
    )

    ema = sum(
        values[:period]
    ) / Decimal(period)

    for price in values[period:]:

        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


def price_above_ema200(symbol, interval):

    try:

        candles = get_klines(
            symbol,
            interval,
            205
        )

        closes = [
            d(x[4])
            for x in candles
        ]

        if len(closes) < 200:
            return False

        ema = calculate_ema(
            closes,
            200
        )

        price = closes[-1]

        return price > ema

    except:

        return False


# =========================================================
# تغير آخر شمعة 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    try:

        candles = get_klines(
            symbol,
            "15m",
            2
        )

        if len(candles) < 2:
            return None

        previous_close = d(
            candles[-2][4]
        )

        current_close = d(
            candles[-1][4]
        )

        if previous_close <= 0:
            return None

        change = (
            (current_close - previous_close)
            / previous_close
        ) * Decimal("100")

        return change

    except:

        return None


# =========================================================
# تحميل العملات
# =========================================================

def load_symbols():

    global symbols

    try:

        info = public_get(
            "/api/v3/exchangeInfo"
        )

        new_symbols = []

        for item in info.get("symbols", []):

            if item.get("status") != "TRADING":
                continue

            if item.get("quoteAsset") != "USDT":
                continue

            if item.get("isSpotTradingAllowed") is False:
                continue

            new_symbols.append(
                item["symbol"]
            )

        symbols = new_symbols

        set_state(
            "symbols_count",
            len(symbols)
        )

        set_state(
            "symbols_loaded",
            True
        )

        log(
            f"📚 تم تحميل {len(symbols)} عملة USDT"
        )

        return True

    except Exception as e:

        set_state(
            "last_error",
            str(e)
        )

        log(
            "⚠️ فشل تحميل العملات: "
            + str(e)
        )

        return False


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    global symbols

    if not symbols:
        return None

    set_state(
        "scan_count",
        get_state()["scan_count"] + 1
    )

    strongest = None

    checked = 0

    passed_change = 0

    passed_ema = 0

    for symbol in symbols:

        try:

            checked += 1

            change = get_15m_change(
                symbol
            )

            if change is None:
                continue

            # لازم أكثر من 1% وليس 1% بالضبط
            if change <= MIN_CHANGE_15M:
                continue

            passed_change += 1

            # 1m
            if not price_above_ema200(
                symbol,
                "1m"
            ):
                continue

            # 5m
            if not price_above_ema200(
                symbol,
                "5m"
            ):
                continue

            # 15m
            if not price_above_ema200(
                symbol,
                "15m"
            ):
                continue

            passed_ema += 1

            price = get_price(
                symbol
            )

            candidate = {
                "symbol": symbol,
                "change_15m": float(change),
                "price": float(price)
            }

            # الأقوى = أعلى تغير 15m
            if (
                strongest is None
                or change
                > d(strongest["change_15m"])
            ):
                strongest = candidate

        except Exception as e:

            set_state(
                "last_error",
                str(e)
            )

            continue

    log(
        f"🔎 Scan: {checked} | "
        f">1%: {passed_change} | "
        f"EMA: {passed_ema}"
    )

    set_state(
        "best_candidate",
        strongest
    )

    return strongest


# =========================================================
# شراء
# =========================================================

def get_symbol_filters(symbol):

    info = public_get(
        "/api/v3/exchangeInfo",
        {
            "symbol": symbol
        }
    )

    symbol_info = info["symbols"][0]

    filters = {}

    for f in symbol_info["filters"]:
        filters[f["filterType"]] = f

    return filters


def round_step(value, step):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def buy_symbol(symbol):

    try:

        usdt = get_usdt_balance()

        amount = (
            usdt
            * BALANCE_USAGE
        )

        if amount < Decimal("5"):
            raise Exception(
                "رصيد USDT غير كافي"
            )

        price = get_price(
            symbol
        )

        filters = get_symbol_filters(
            symbol
        )

        lot = filters.get(
            "LOT_SIZE"
        )

        min_notional = filters.get(
            "MIN_NOTIONAL"
        )

        if not lot:
            raise Exception(
                "LOT_SIZE غير موجود"
            )

        step_size = d(
            lot["stepSize"]
        )

        min_qty = d(
            lot["minQty"]
        )

        quantity = amount / price

        quantity = round_step(
            quantity,
            step_size
        )

        if quantity < min_qty:
            raise Exception(
                "الكمية أقل من الحد الأدنى"
            )

        if min_notional:

            min_value = d(
                min_notional.get(
                    "minNotional",
                    "0"
                )
            )

            if quantity * price < min_value:
                raise Exception(
                    "قيمة الصفقة أقل من الحد الأدنى"
                )

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": str(quantity)
            }
        )

        log(
            f"🟢 شراء {symbol} | "
            f"Qty {quantity}"
        )

        set_state(
            "last_action",
            f"🟢 شراء {symbol}"
        )

        return order

    except Exception as e:

        set_state(
            "last_error",
            str(e)
        )

        set_state(
            "last_action",
            "❌ فشل الشراء"
        )

        log(
            "❌ فشل الشراء: "
            + str(e)
        )

        return None


# =========================================================
# إلغاء أوامر الحماية
# =========================================================

def cancel_open_orders(symbol):

    try:

        orders = signed_request(
            "GET",
            "/api/v3/openOrders",
            {
                "symbol": symbol
            }
        )

        for order in orders:

            try:

                signed_request(
                    "DELETE",
                    "/api/v3/order",
                    {
                        "symbol": symbol,
                        "orderId":
                            order["orderId"]
                    }
                )

                log(
                    f"🗑️ إلغاء أمر {symbol} "
                    f"#{order['orderId']}"
                )

            except Exception as e:

                log(
                    "⚠️ تعذر إلغاء الأمر: "
                    + str(e)
                )

    except Exception as e:

        log(
            "⚠️ فشل قراءة الأوامر: "
            + str(e)
        )


# =========================================================
# حماية الربح
# =========================================================

def create_profit_protection(
    symbol,
    quantity,
    stop_price
):

    try:

        filters = get_symbol_filters(
            symbol
        )

        lot = filters.get(
            "LOT_SIZE"
        )

        price_filter = filters.get(
            "PRICE_FILTER"
        )

        if not lot or not price_filter:
            raise Exception(
                "فلاتر Binance غير موجودة"
            )

        step_size = d(
            lot["stepSize"]
        )

        tick_size = d(
            price_filter["tickSize"]
        )

        quantity = round_step(
            quantity,
            step_size
        )

        stop_price = round_step(
            stop_price,
            tick_size
        )

        if quantity <= 0:
            raise Exception(
                "الكمية غير صالحة"
            )

        if stop_price <= 0:
            raise Exception(
                "سعر الحماية غير صالح"
            )

        # نحذف الحماية القديمة
        cancel_open_orders(
            symbol
        )

        # حماية بيع سوقية
        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "STOP_LOSS",
                "quantity": str(quantity),
                "stopPrice": str(stop_price)
            }
        )

        log(
            f"🛡️ حماية الربح {symbol} "
            f"عند {stop_price}"
        )

        return order

    except Exception as e:

        log(
            "⚠️ فشل إنشاء الحماية: "
            + str(e)
        )

        set_state(
            "last_error",
            str(e)
        )

        return None


# =========================================================
# حساب صافي الربح
# =========================================================

def calculate_net_profit_percent(
    entry,
    current
):

    if entry <= 0:
        return Decimal("0")

    gross = (
        (current - entry)
        / entry
    ) * Decimal("100")

    # تقريباً رسوم شراء + بيع
    fees = FEE_RATE * Decimal("2") * Decimal("100")

    return gross - fees


def calculate_profit_usdt(
    entry,
    current,
    quantity
):

    gross = (
        current - entry
    ) * quantity

    estimated_fees = (
        (entry * quantity)
        + (current * quantity)
    ) * FEE_RATE

    return gross - estimated_fees


# =========================================================
# تسجيل الصفقة
# =========================================================

def register_closed_trade(
    profit
):

    global last_trade_day
    global last_trade_week
    global last_trade_month

    import datetime

    now = datetime.datetime.utcnow()

    day = now.strftime("%Y-%m-%d")
    week = now.strftime("%Y-%W")
    month = now.strftime("%Y-%m")

    with state_lock:

        state["total_trades"] += 1

        if profit > 0:
            state["winning_trades"] += 1
        else:
            state["losing_trades"] += 1

        state["total_profit"] += float(
            profit
        )

        if last_trade_day != day:
            state["daily_profit"] = 0
            state["daily_trades"] = 0
            last_trade_day = day

        if last_trade_week != week:
            state["weekly_profit"] = 0
            state["weekly_trades"] = 0
            last_trade_week = week

        if last_trade_month != month:
            state["monthly_profit"] = 0
            state["monthly_trades"] = 0
            last_trade_month = month

        state["daily_profit"] += float(
            profit
        )

        state["weekly_profit"] += float(
            profit
        )

        state["monthly_profit"] += float(
            profit
        )

        state["daily_trades"] += 1
        state["weekly_trades"] += 1
        state["monthly_trades"] += 1


# =========================================================
# إدارة الصفقة
# =========================================================

def manage_position(position):

    symbol = position["symbol"]
    quantity = position["quantity"]

    entry = calculate_entry(
        symbol,
        quantity
    )

    if entry is None:
        entry = position["price"]

    current = get_price(
        symbol
    )

    net_percent = (
        calculate_net_profit_percent(
            entry,
            current
        )
    )

    profit_usdt = (
        calculate_profit_usdt(
            entry,
            current,
            quantity
        )
    )

    current_state = get_state()

    highest = d(
        str(
            current_state.get(
                "highest_price",
                0
            )
        )
    )

    if current > highest:
        highest = current

    protection_active = (
        net_percent >= PROTECTION_START
    )

    protection_price = d(
        str(
            current_state.get(
                "protection_price",
                0
            )
        )
    )

    # =====================================================
    # أول مرة يصل +1%
    # =====================================================

    if (
        protection_active
        and protection_price <= 0
    ):

        new_protection = (
            highest
            * (
                Decimal("1")
                - (
                    TRAIL_PERCENT
                    / Decimal("100")
                )
            )
        )

        # الحماية لازم تكون فوق سعر الدخول
        if new_protection > entry:

            result = create_profit_protection(
                symbol,
                quantity,
                new_protection
            )

            if result:

                protection_price = (
                    new_protection
                )

                set_state(
                    "protection_active",
                    True
                )

                set_state(
                    "protection_price",
                    float(
                        protection_price
                    )
                )

    # =====================================================
    # رفع الحماية مع ارتفاع السعر
    # =====================================================

    elif (
        protection_active
        and protection_price > 0
    ):

        new_protection = (
            highest
            * (
                Decimal("1")
                - (
                    TRAIL_PERCENT
                    / Decimal("100")
                )
            )
        )

        # لا ننزل الحماية أبداً
        if new_protection > protection_price:

            if new_protection > entry:

                result = (
                    create_profit_protection(
                        symbol,
                        quantity,
                        new_protection
                    )
                )

                if result:

                    protection_price = (
                        new_protection
                    )

                    set_state(
                        "protection_price",
                        float(
                            protection_price
                        )
                    )

                    log(
                        f"⬆️ رفع الحماية "
                        f"{symbol} → "
                        f"{new_protection}"
                    )

    # =====================================================
    # تحديث الحالة
    # =====================================================

    position_data = {
        "symbol": symbol,
        "quantity": float(quantity),
        "entry": float(entry),
        "current_price": float(current),
        "net_profit_percent": float(
            net_percent
        ),
        "profit_usdt": float(
            profit_usdt
        ),
        "highest_price": float(
            highest
        ),
        "protection_active":
            protection_active,
        "protection_price": float(
            protection_price
        )
    }

    set_state(
        "position",
        position_data
    )

    set_state(
        "highest_price",
        float(highest)
    )

    set_state(
        "protection_active",
        protection_active
    )

    log(
        f"📊 {symbol} | "
        f"{current} | "
        f"صافي {net_percent:.2f}% | "
        f"ربح {profit_usdt:.4f} USDT"
    )


# =========================================================
# محرك التداول
# =========================================================

def trading_engine():

    log("")
    log("==============================")
    log("🤖 مضارب أبو سعود V6")
    log("==============================")

    # =====================================================
    # الأولوية المطلقة:
    # اكتشاف الصفقة قبل تحميل العملات
    # =====================================================

    while True:

        try:

            position = find_open_position()

            # =============================================
            # فيه صفقة مفتوحة
            # =============================================

            if position:

                symbol = position["symbol"]

                log(
                    f"♻️ صفقة موجودة: {symbol}"
                )

                log(
                    f"♻️ إدارة {symbol} | "
                    f"Qty {position['quantity']}"
                )

                # مهم:
                # ما فيه load_symbols()
                # وما فيه scan_market()

                manage_position(
                    position
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =============================================
            # ما فيه صفقة
            # =============================================

            if get_state()["position"]:

                log(
                    "🏁 الصفقة السابقة انتهت"
                )

                set_state(
                    "position",
                    None
                )

                set_state(
                    "highest_price",
                    0
                )

                set_state(
                    "protection_price",
                    0
                )

                set_state(
                    "protection_active",
                    False
                )

            # =============================================
            # الآن فقط نحمل العملات
            # =============================================

            if not symbols:

                log(
                    "📭 لا توجد صفقة"
                )

                log(
                    "📚 الآن يتم تحميل العملات..."
                )

                if not load_symbols():

                    time.sleep(30)
                    continue

            # =============================================
            # فحص السوق
            # =============================================

            log(
                "🔍 بدء فحص السوق..."
            )

            candidate = scan_market()

            if candidate:

                symbol = candidate["symbol"]

                log(
                    f"🔥 الأقوى: {symbol} | "
                    f"+{candidate['change_15m']:.2f}%"
                )

                set_state(
                    "last_action",
                    f"🔥 أفضل عملة {symbol}"
                )

                # قبل الشراء نفحص مرة ثانية
                # للتأكد أنه ما دخلت صفقة يدوية
                position_now = (
                    find_open_position()
                )

                if position_now:

                    log(
                        "⚠️ تم اكتشاف صفقة مفتوحة "
                        "قبل الشراء — لن ندخل"
                    )

                    time.sleep(5)
                    continue

                order = buy_symbol(
                    symbol
                )

                if order:

                    # نعطي Binance لحظة لتحديث الرصيد
                    time.sleep(2)

                    new_position = (
                        find_open_position()
                    )

                    if new_position:

                        # إعادة ضبط أعلى سعر
                        set_state(
                            "highest_price",
                            float(
                                new_position["price"]
                            )
                        )

                        set_state(
                            "protection_price",
                            0
                        )

                        set_state(
                            "protection_active",
                            False
                        )

                        log(
                            f"♻️ بدأت إدارة "
                            f"{symbol}"
                        )

            else:

                log(
                    "⚪ لا توجد عملة مطابقة حالياً"
                )

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            set_state(
                "last_error",
                str(e)
            )

            log(
                "❌ خطأ بالمحرك: "
                + str(e)
            )

            time.sleep(15)


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

<title>مضارب أبو سعود V6</title>

<style>

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #0b1020;
    color: white;
}

.container {
    max-width: 1100px;
    margin: auto;
    padding: 20px;
}

.header {
    background: #121a2e;
    padding: 20px;
    border-radius: 18px;
    margin-bottom: 15px;
}

.title {
    font-size: 26px;
    font-weight: bold;
}

.status {
    margin-top: 8px;
    font-size: 15px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(180px, 1fr));

    gap: 12px;
}

.card {
    background: #121a2e;
    border-radius: 16px;
    padding: 18px;
}

.label {
    color: #9aa5bd;
    font-size: 13px;
}

.value {
    font-size: 22px;
    font-weight: bold;
    margin-top: 8px;
}

.trade {
    background: #121a2e;
    border-radius: 18px;
    padding: 22px;
    margin-top: 15px;
}

.coin {
    font-size: 30px;
    font-weight: bold;
}

.profit {
    font-size: 28px;
    font-weight: bold;
    margin-top: 10px;
}

.good {
    color: #28d17c;
}

.bad {
    color: #ff5c5c;
}

.neutral {
    color: #f2c94c;
}

.small {
    color: #9aa5bd;
    margin-top: 8px;
}

</style>

</head>

<body>

<div class="container">

<div class="header">

<div class="title">
🤖 مضارب أبو سعود V6
</div>

<div class="status" id="connection">
جاري الاتصال بـ Binance...
</div>

</div>


<div id="trade"></div>


<div class="grid">

<div class="card">
<div class="label">رصيد USDT</div>
<div class="value" id="balance">-</div>
</div>

<div class="card">
<div class="label">إجمالي الصفقات</div>
<div class="value" id="total">0</div>
</div>

<div class="card">
<div class="label">الصفقات الرابحة</div>
<div class="value good" id="wins">0</div>
</div>

<div class="card">
<div class="label">الصفقات الخاسرة</div>
<div class="value bad" id="losses">0</div>
</div>

<div class="card">
<div class="label">نسبة الفوز</div>
<div class="value" id="winrate">0%</div>
</div>

<div class="card">
<div class="label">إجمالي الربح</div>
<div class="value" id="profit">0</div>
</div>

<div class="card">
<div class="label">ربح اليوم</div>
<div class="value" id="daily">0</div>
</div>

<div class="card">
<div class="label">ربح الأسبوع</div>
<div class="value" id="weekly">0</div>
</div>

<div class="card">
<div class="label">ربح الشهر</div>
<div class="value" id="monthly">0</div>
</div>

</div>


<div class="trade">

<div class="label">
آخر إجراء
</div>

<div class="value"
id="action">
-
</div>

<div class="small">
آخر خطأ:
<span id="error">لا يوجد</span>
</div>

</div>


</div>


<script>

async function update() {

    try {

        const r =
            await fetch('/api/status');

        const s =
            await r.json();

        const connected =
            document.getElementById(
                'connection'
            );

        if (s.binance_connected) {

            connected.innerHTML =
                '🟢 Binance مربوط فعلياً';

            connected.className =
                'status good';

        } else {

            connected.innerHTML =
                '🔴 Binance غير متصل';

            connected.className =
                'status bad';
        }


        document.getElementById(
            'balance'
        ).innerText =
            Number(
                s.balance_usdt || 0
            ).toFixed(2);


        document.getElementById(
            'total'
        ).innerText =
            s.total_trades || 0;


        document.getElementById(
            'wins'
        ).innerText =
            s.winning_trades || 0;


        document.getElementById(
            'losses'
        ).innerText =
            s.losing_trades || 0;


        let total =
            Number(
                s.total_trades || 0
            );

        let wins =
            Number(
                s.winning_trades || 0
            );

        document.getElementById(
            'winrate'
        ).innerText =
            total > 0
            ? ((wins / total) * 100).toFixed(1) + '%'
            : '0%';


        document.getElementById(
            'profit'
        ).innerText =
            Number(
                s.total_profit || 0
            ).toFixed(2) + ' USDT';


        document.getElementById(
            'daily'
        ).innerText =
            Number(
                s.daily_profit || 0
            ).toFixed(2) + ' USDT';


        document.getElementById(
            'weekly'
        ).innerText =
            Number(
                s.weekly_profit || 0
            ).toFixed(2) + ' USDT';


        document.getElementById(
            'monthly'
        ).innerText =
            Number(
                s.monthly_profit || 0
            ).toFixed(2) + ' USDT';


        document.getElementById(
            'action'
        ).innerText =
            s.last_action || '-';


        document.getElementById(
            'error'
        ).innerText =
            s.last_error || 'لا يوجد';


        const trade =
            document.getElementById(
                'trade'
            );


        if (s.position) {

            const p =
                s.position;

            let profitClass =
                p.net_profit_percent >= 0
                ? 'good'
                : 'bad';

            trade.innerHTML = `

            <div class="trade">

                <div class="label">
                    الصفقة الحالية
                </div>

                <div class="coin">
                    ${p.symbol}
                </div>

                <div class="small">
                    الدخول:
                    ${Number(p.entry).toFixed(8)}
                </div>

                <div class="small">
                    السعر الحالي:
                    ${Number(p.current_price).toFixed(8)}
                </div>

                <div class="profit ${profitClass}">
                    ${Number(
                        p.net_profit_percent
                    ).toFixed(2)}%
                </div>

                <div class="small">
                    صافي الربح:
                    ${Number(
                        p.profit_usdt
                    ).toFixed(4)} USDT
                </div>

                <div class="small">
                    أعلى سعر:
                    ${Number(
                        p.highest_price
                    ).toFixed(8)}
                </div>

                <div class="small">
                    الحماية:
                    ${
                        p.protection_active
                        ? '🟢 مفعلة عند ' +
                          Number(
                            p.protection_price
                          ).toFixed(8)
                        : '🟡 لم تبدأ بعد'
                    }
                </div>

            </div>

            `;

        } else {

            trade.innerHTML = `

            <div class="trade">

                <div class="coin">
                    💤 لا توجد صفقة
                </div>

                <div class="small">
                    البوت يفحص الصفقات أولاً،
                    ثم يبدأ Scan فقط إذا ما فيه صفقة.
                </div>

            </div>

            `;
        }

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
# Flask
# =========================================================

@app.route("/")
def home():
    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    return jsonify(
        get_state()
    )


# =========================================================
# تشغيل الموقع
# =========================================================

def start_flask():

    log(
        f"🌐 الموقع يعمل على {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )


# =========================================================
# حفظ بسيط للحالة
# =========================================================

def save_state_loop():

    while True:

        try:

            data = get_state()

            with open(
                "bot_data.json",
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:

            log(
                "⚠️ حفظ الحالة: "
                + str(e)
            )

        time.sleep(30)


# =========================================================
# تشغيل
# =========================================================

if __name__ == "__main__":

    log("")
    log("==============================")
    log("🚀 تشغيل V6")
    log("==============================")

    # الموقع
    threading.Thread(
        target=start_flask,
        daemon=True
    ).start()

    # حفظ الحالة
    threading.Thread(
        target=save_state_loop,
        daemon=True
    ).start()

    # المحرك في Thread مستقل
    threading.Thread(
        target=trading_engine,
        daemon=True
    ).start()

    # اتصال Binance للمراقبة فقط
    # لا نوقف المحرك إذا تأخر الاتصال
    while True:

        try:

            check_binance_connection()

        except Exception as e:

            log(
                "⚠️ مراقبة Binance: "
                + str(e)
            )

        time.sleep(60)
