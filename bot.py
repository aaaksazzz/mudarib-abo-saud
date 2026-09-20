import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify

# =========================================================
# الإعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

EMA_PERIOD = 200

# أول فلتر: تغير 15 دقيقة
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ وقف الربح فقط بعد +1%
PROTECTION_START = Decimal("1.0")

# مسافة وقف الربح عن أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام كامل الرصيد تقريبًا
BALANCE_USAGE = Decimal("0.999")

# فحص السوق كل 20 ثانية
SCAN_INTERVAL = 20

# متابعة الصفقة كل 3 ثواني
POSITION_CHECK_INTERVAL = 3

REQUEST_DELAY = 0.08

STATE_FILE = "bot_data.json"


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

state = {
    "status": "starting",
    "active_trade": None,
    "symbols_count": 0,
    "candidates_count": 0,
    "ema_pass_count": 0,
    "best_candidate": None,
    "last_scan": None,
    "last_action": "بدء التشغيل",
    "last_error": None,
    "scan_number": 0,
}

state_lock = threading.Lock()

session = requests.Session()

exchange_info_cache = None
exchange_info_time = 0


# =========================================================
# أدوات
# =========================================================

def log(msg):
    print(msg, flush=True)


def D(value):
    return Decimal(str(value))


def save_state():
    try:
        with state_lock:
            data = {
                "active_trade": state.get("active_trade"),
                "last_action": state.get("last_action"),
            }

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        log(f"⚠️ خطأ حفظ الحالة: {e}")


def load_state():
    if not os.path.exists(STATE_FILE):
        log("ℹ️ لا يوجد ملف بيانات سابق")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        with state_lock:
            state["active_trade"] = data.get(
                "active_trade"
            )

            state["last_action"] = data.get(
                "last_action",
                "تم تحميل الحالة"
            )

        log("♻️ تم تحميل الحالة السابقة")

    except Exception as e:
        log(f"⚠️ فشل تحميل الحالة: {e}")


# =========================================================
# Binance
# =========================================================

def public_get(path, params=None):

    r = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=20
    )

    if r.status_code != 200:
        raise Exception(
            f"Binance {r.status_code}: {r.text}"
        )

    return r.json()


def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception(
            "BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة"
        )

    params = params or {}

    params["timestamp"] = int(
        time.time() * 1000
    )

    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(params)

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

    if method == "GET":
        r = session.get(
            url,
            headers=headers,
            timeout=20
        )

    elif method == "POST":
        r = session.post(
            url,
            headers=headers,
            timeout=20
        )

    elif method == "DELETE":
        r = session.delete(
            url,
            headers=headers,
            timeout=20
        )

    else:
        raise Exception(
            "HTTP method غير مدعوم"
        )

    if r.status_code != 200:
        raise Exception(
            f"Binance {r.status_code}: {r.text}"
        )

    return r.json()


# =========================================================
# العملات
# =========================================================

def get_exchange_info():

    global exchange_info_cache
    global exchange_info_time

    now = time.time()

    if (
        exchange_info_cache is None
        or now - exchange_info_time > 3600
    ):

        exchange_info_cache = public_get(
            "/api/v3/exchangeInfo"
        )

        exchange_info_time = now

    return exchange_info_cache


def get_symbol_map():

    info = get_exchange_info()

    result = {}

    for s in info["symbols"]:

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get("isSpotTradingAllowed") is False:
            continue

        result[s["symbol"]] = s

    return result


# =========================================================
# الفلاتر
# =========================================================

def get_filters(symbol):

    info = get_symbol_map().get(symbol)

    if not info:
        raise Exception(
            f"العملة غير موجودة: {symbol}"
        )

    filters = {}

    for f in info.get("filters", []):
        filters[f["filterType"]] = f

    return filters


def floor_step(value, step):

    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def format_decimal(value):

    s = format(
        D(value),
        "f"
    )

    if "." in s:
        s = s.rstrip("0").rstrip(".")

    return s


def normalize_quantity(symbol, quantity):

    filters = get_filters(symbol)

    f = filters.get("LOT_SIZE")

    if not f:
        f = filters.get("MARKET_LOT_SIZE")

    if not f:
        return quantity

    return floor_step(
        quantity,
        D(f["stepSize"])
    )


def normalize_price(symbol, price):

    filters = get_filters(symbol)

    f = filters.get("PRICE_FILTER")

    if not f:
        return price

    return floor_step(
        price,
        D(f["tickSize"])
    )


def check_min_notional(
    symbol,
    quantity,
    price
):

    filters = get_filters(symbol)

    f = filters.get("NOTIONAL")

    if not f:
        f = filters.get("MIN_NOTIONAL")

    if not f:
        return True

    minimum = D(
        f.get(
            "minNotional",
            "0"
        )
    )

    return (
        quantity * price
    ) >= minimum


# =========================================================
# الحساب
# =========================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_usdt_balance():

    account = get_account()

    for b in account["balances"]:

        if b["asset"] == "USDT":

            return D(b["free"])

    return Decimal("0")


def get_asset_balance(asset):

    account = get_account()

    for b in account["balances"]:

        if b["asset"] == asset:

            return (
                D(b["free"])
                + D(b["locked"])
            )

    return Decimal("0")


# =========================================================
# السعر
# =========================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return D(data["price"])


# =========================================================
# الشموع و EMA
# =========================================================

def get_klines(
    symbol,
    interval,
    limit=210
):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def calculate_ema(
    values,
    period=200
):

    if len(values) < period:
        return None

    multiplier = (
        Decimal("2")
        / Decimal(period + 1)
    )

    ema = (
        sum(values[:period])
        / Decimal(period)
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


def check_ema200(
    symbol,
    interval
):

    candles = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    if len(candles) < EMA_PERIOD:
        return False

    closes = [
        D(c[4])
        for c in candles
    ]

    ema = calculate_ema(
        closes,
        EMA_PERIOD
    )

    if ema is None:
        return False

    price = closes[-1]

    return price > ema


# =========================================================
# تغير 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    candles = get_klines(
        symbol,
        "15m",
        3
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
    ) * Decimal("100")


# =========================================================
# الفحص الرئيسي
# =========================================================

def scan_market():

    symbol_map = get_symbol_map()

    symbols = list(
        symbol_map.keys()
    )

    with state_lock:
        state["symbols_count"] = len(
            symbols
        )

    log(
        f"🔎 المرحلة 1: فحص {len(symbols)} عملة"
    )

    # =====================================================
    # المرحلة الأولى
    # فقط العملات فوق +1%
    # =====================================================

    candidates = []

    for symbol in symbols:

        try:

            change = get_15m_change(
                symbol
            )

            # أقل من +1% ينشال مباشرة
            if change >= MIN_CHANGE_15M:

                candidates.append(
                    {
                        "symbol": symbol,
                        "change": change
                    }
                )

        except Exception:
            pass

        time.sleep(
            REQUEST_DELAY
        )

    # الأقوى أولًا
    candidates.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    with state_lock:
        state["candidates_count"] = len(
            candidates
        )

    log(
        f"✅ بعد فلتر +1%: "
        f"{len(candidates)} عملة"
    )

    if not candidates:
        return None

    # =====================================================
    # المرحلة الثانية
    # EMA 15m + 5m + 1m
    # =====================================================

    passed = []

    log(
        "📊 المرحلة 2: تحليل EMA 1m / 5m / 15m"
    )

    for item in candidates:

        symbol = item["symbol"]
        change = item["change"]

        try:

            # 15 دقيقة
            if not check_ema200(
                symbol,
                "15m"
            ):
                continue

            time.sleep(
                REQUEST_DELAY
            )

            # 5 دقائق
            if not check_ema200(
                symbol,
                "5m"
            ):
                continue

            time.sleep(
                REQUEST_DELAY
            )

            # دقيقة
            if not check_ema200(
                symbol,
                "1m"
            ):
                continue

            passed.append(
                item
            )

            log(
                f"✅ {symbol} "
                f"| +{change:.2f}% "
                f"| EMA 1m/5m/15m فوق"
            )

        except Exception:
            continue

    with state_lock:
        state["ema_pass_count"] = len(
            passed
        )

    # =====================================================
    # المرحلة الثالثة
    # اختيار الأعلى تغيرًا
    # =====================================================

    if not passed:

        log(
            "❌ لا توجد عملة اجتازت المتوسطات"
        )

        return None

    passed.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    best = passed[0]

    with state_lock:
        state["best_candidate"] = {
            "symbol": best["symbol"],
            "change_15m": float(
                best["change"]
            )
        }

    log(
        f"🏆 الأفضل: {best['symbol']} "
        f"| تغير 15m: +{best['change']:.2f}%"
    )

    return best


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    usdt = get_usdt_balance()

    if usdt <= Decimal("5"):

        raise Exception(
            f"رصيد USDT غير كافي: {usdt}"
        )

    amount = (
        usdt * BALANCE_USAGE
    )

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    log(
        f"🚀 دخول {symbol} "
        f"| المبلغ {amount} USDT"
    )

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": format_decimal(
                amount
            ),
        }
    )

    executed_qty = D(
        result.get(
            "executedQty",
            "0"
        )
    )

    quote_qty = D(
        result.get(
            "cummulativeQuoteQty",
            "0"
        )
    )

    if executed_qty <= 0:
        raise Exception(
            "لم يتم تنفيذ الشراء"
        )

    if quote_qty > 0:

        entry = (
            quote_qty
            / executed_qty
        )

    else:

        entry = get_price(
            symbol
        )

    return {
        "symbol": symbol,
        "quantity": float(
            executed_qty
        ),
        "entry_price": float(
            entry
        ),
        "highest_price": float(
            entry
        ),
        "protection_price": None,
        "protection_order_id": None,
        "order_id": result.get(
            "orderId"
        ),
    }


# =========================================================
# أوامر Binance
# =========================================================

def get_open_orders(symbol):

    return signed_request(
        "GET",
        "/api/v3/openOrders",
        {
            "symbol": symbol
        }
    )


def cancel_order(
    symbol,
    order_id
):

    try:

        signed_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            }
        )

        log(
            f"🗑️ حذف الوقف القديم "
            f"{order_id}"
        )

    except Exception as e:

        log(
            f"⚠️ تعذر حذف الوقف القديم: {e}"
        )


def create_protection_order(
    symbol,
    quantity,
    stop_price
):

    current = get_price(
        symbol
    )

    stop_price = normalize_price(
        symbol,
        stop_price
    )

    # الوقف لازم يكون تحت السعر الحالي
    if stop_price >= current:

        stop_price = normalize_price(
            symbol,
            current * Decimal("0.999")
        )

    quantity = normalize_quantity(
        symbol,
        quantity
    )

    if quantity <= 0:
        raise Exception(
            "الكمية غير صالحة"
        )

    if not check_min_notional(
        symbol,
        quantity,
        stop_price
    ):
        raise Exception(
            "قيمة أمر الحماية أقل من الحد الأدنى"
        )

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": format_decimal(
                quantity
            ),
            "stopPrice": format_decimal(
                stop_price
            ),
        }
    )

    log(
        f"🔒 وقف جديد {symbol} "
        f"عند {stop_price}"
    )

    return result


# =========================================================
# تحديث وقف الربح
# =========================================================

def update_protection(
    trade,
    current_price
):

    symbol = trade["symbol"]

    entry = D(
        trade["entry_price"]
    )

    current = D(
        current_price
    )

    highest = D(
        trade.get(
            "highest_price",
            entry
        )
    )

    # أعلى سعر جديد
    if current > highest:

        highest = current

        trade["highest_price"] = float(
            highest
        )

    profit = (
        (current - entry)
        / entry
    ) * Decimal("100")

    # =====================================================
    # قبل +1%
    # لا يوجد أي وقف
    # =====================================================

    if profit < PROTECTION_START:

        with state_lock:
            state["last_action"] = (
                f"{symbol} | "
                f"ربح {profit:.2f}% | "
                f"لا يوجد وقف"
            )

        return

    # =====================================================
    # حساب وقف جديد من أعلى سعر
    # =====================================================

    new_stop = (
        highest
        * (
            Decimal("1")
            - TRAIL_PERCENT
            / Decimal("100")
        )
    )

    # لازم الوقف يكون فوق الدخول
    minimum_profit_stop = (
        entry
        * Decimal("1.001")
    )

    if new_stop < minimum_profit_stop:

        new_stop = (
            minimum_profit_stop
        )

    new_stop = normalize_price(
        symbol,
        new_stop
    )

    old_stop = trade.get(
        "protection_price"
    )

    if old_stop is not None:
        old_stop = D(old_stop)

    # =====================================================
    # إذا الوقف الجديد أقل أو مساوي للقديم
    # لا نغيره
    # =====================================================

    if (
        old_stop is not None
        and new_stop <= old_stop
    ):
        return

    # =====================================================
    # حذف القديم
    # =====================================================

    old_order_id = trade.get(
        "protection_order_id"
    )

    if old_order_id:

        cancel_order(
            symbol,
            old_order_id
        )

        trade[
            "protection_order_id"
        ] = None

    # =====================================================
    # إنشاء الجديد
    # =====================================================

    try:

        result = create_protection_order(
            symbol,
            D(trade["quantity"]),
            new_stop
        )

        trade[
            "protection_price"
        ] = float(new_stop)

        trade[
            "protection_order_id"
        ] = result.get(
            "orderId"
        )

        with state_lock:
            state["last_action"] = (
                f"🔒 رفع الوقف "
                f"إلى {new_stop}"
            )
            state["last_error"] = None

        log(
            f"📈 {symbol} "
            f"| أعلى سعر {highest} "
            f"| وقف {new_stop}"
        )

        save_state()

    except Exception as e:

        with state_lock:
            state["last_error"] = str(e)

        log(
            f"🚨 فشل إنشاء وقف الربح: {e}"
        )


# =========================================================
# متابعة الصفقة
# =========================================================

def update_trade():

    with state_lock:
        trade = state.get(
            "active_trade"
        )

    if not trade:
        return

    symbol = trade["symbol"]

    try:

        current = get_price(
            symbol
        )

        entry = D(
            trade["entry_price"]
        )

        profit = (
            (current - entry)
            / entry
        ) * Decimal("100")

        asset = symbol.replace(
            "USDT",
            ""
        )

        balance = get_asset_balance(
            asset
        )

        # الأصل اختفى = الصفقة أغلقت
        if balance <= 0:

            log(
                f"✅ الصفقة {symbol} أغلقت"
            )

            with state_lock:
                state["active_trade"] = None
                state["last_action"] = (
                    f"تم إغلاق {symbol}"
                )

            save_state()

            return

        trade["quantity"] = float(
            balance
        )

        update_protection(
            trade,
            current
        )

        with state_lock:
            state["active_trade"] = trade

        log(
            f"📊 {symbol} | "
            f"السعر {current} | "
            f"الربح {profit:.2f}% | "
            f"الأعلى {trade['highest_price']}"
        )

        save_state()

    except Exception as e:

        log(
            f"⚠️ متابعة {symbol}: {e}"
        )

        with state_lock:
            state["last_error"] = str(e)


# =========================================================
# استرجاع أي صفقة مفتوحة
# =========================================================

def recover_position():

    try:

        # أولًا الحالة المحفوظة
        with state_lock:
            saved = state.get(
                "active_trade"
            )

        if saved:

            symbol = saved.get(
                "symbol"
            )

            if symbol:

                asset = symbol.replace(
                    "USDT",
                    ""
                )

                balance = get_asset_balance(
                    asset
                )

                if balance > 0:

                    saved["quantity"] = float(
                        balance
                    )

                    log(
                        f"♻️ استرجاع "
                        f"{symbol}"
                    )

                    return saved

        # ثانيًا البحث في أرصدة الحساب
        account = get_account()

        for b in account.get(
            "balances",
            []
        ):

            asset = b["asset"]

            if asset == "USDT":
                continue

            total = (
                D(b["free"])
                + D(b["locked"])
            )

            if total <= 0:
                continue

            symbol = asset + "USDT"

            try:

                if symbol not in get_symbol_map():
                    continue

                trades = signed_request(
                    "GET",
                    "/api/v3/myTrades",
                    {
                        "symbol": symbol,
                        "limit": 20
                    }
                )

                buys = [
                    x for x in trades
                    if x.get("isBuyer")
                ]

                if not buys:
                    continue

                last_buy = max(
                    buys,
                    key=lambda x: x["time"]
                )

                entry = D(
                    last_buy["price"]
                )

                trade = {
                    "symbol": symbol,
                    "quantity": float(total),
                    "entry_price": float(entry),
                    "highest_price": float(entry),
                    "protection_price": None,
                    "protection_order_id": None,
                    "order_id": last_buy.get(
                        "orderId"
                    ),
                }

                log(
                    f"♻️ صفقة مفتوحة "
                    f"مكتشفة: {symbol}"
                )

                return trade

            except Exception:
                continue

        return None

    except Exception as e:

        log(
            f"⚠️ خطأ استرجاع الصفقة: {e}"
        )

        return None


# =========================================================
# الدخول
# =========================================================

def enter_trade(candidate):

    symbol = candidate["symbol"]

    try:

        trade = market_buy(
            symbol
        )

        with state_lock:
            state["active_trade"] = trade
            state["last_action"] = (
                f"🚀 دخول {symbol}"
            )
            state["last_error"] = None

        save_state()

        log(
            f"🚀 تم الدخول "
            f"{symbol} "
            f"| Entry {trade['entry_price']}"
        )

    except Exception as e:

        log(
            f"🚨 فشل الدخول {symbol}: {e}"
        )

        with state_lock:
            state["last_error"] = str(e)


# =========================================================
# المحرك
# =========================================================

def trading_loop():

    log("🚀 بدأ محرك التداول")

    while True:

        try:

            # =================================================
            # إذا فيه صفقة مفتوحة
            # لا يبحث عن صفقة ثانية
            # =================================================

            with state_lock:
                active = state.get(
                    "active_trade"
                )

            if active:

                update_trade()

                time.sleep(
                    POSITION_CHECK_INTERVAL
                )

                continue

            # =================================================
            # البحث عن صفقة موجودة أصلًا
            # =================================================

            recovered = recover_position()

            if recovered:

                with state_lock:
                    state["active_trade"] = recovered
                    state["last_action"] = (
                        f"♻️ إدارة "
                        f"{recovered['symbol']}"
                    )

                save_state()

                continue

            # =================================================
            # الفحص
            # =================================================

            with state_lock:
                state["status"] = "scanning"
                state["scan_number"] += 1
                state["last_scan"] = int(
                    time.time()
                )

            best = scan_market()

            if best:

                enter_trade(
                    best
                )

            else:

                with state_lock:
                    state["last_action"] = (
                        "🔎 لا توجد صفقة مطابقة"
                    )

            with state_lock:
                state["status"] = "running"

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            log(
                f"🚨 خطأ المحرك: {e}"
            )

            with state_lock:
                state["status"] = "error"
                state["last_error"] = str(e)

            time.sleep(10)


# =========================================================
# Dashboard
# =========================================================

@app.route("/")
def dashboard():

    with state_lock:
        data = dict(state)

    trade = data.get(
        "active_trade"
    )

    html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود</title>

<style>

body {
    background:#111;
    color:#fff;
    font-family:Arial;
    padding:20px;
}

.box {
    background:#1d1d1d;
    border-radius:15px;
    padding:18px;
    margin-bottom:15px;
}

.big {
    font-size:28px;
    font-weight:bold;
}

.row {
    margin:9px 0;
}

.green {
    color:#00e676;
}

.red {
    color:#ff5252;
}

.gray {
    color:#aaa;
}

</style>

</head>

<body>

<h1>🤖 مضارب أبو سعود</h1>

<div class="box">

<div class="row">
الحالة:
<b>STATUS</b>
</div>

<div class="row">
عدد العملات:
<b>SYMBOLS</b>
</div>

<div class="row">
بعد فلتر +1%:
<b>CANDIDATES</b>
</div>

<div class="row">
اجتازت المتوسطات:
<b>EMA_PASS</b>
</div>

<div class="row">
أفضل عملة:
<b>BEST</b>
</div>

<div class="row">
رقم الفحص:
<b>SCAN</b>
</div>

<div class="row">
آخر عملية:
<b>ACTION</b>
</div>

<div class="row red">
آخر خطأ:
<b>ERROR</b>
</div>

</div>

<div class="box">

<h2>📊 الصفقة</h2>

"""

    html = html.replace(
        "STATUS",
        str(data.get("status"))
    )

    html = html.replace(
        "SYMBOLS",
        str(data.get("symbols_count"))
    )

    html = html.replace(
        "CANDIDATES",
        str(data.get("candidates_count"))
    )

    html = html.replace(
        "EMA_PASS",
        str(data.get("ema_pass_count"))
    )

    html = html.replace(
        "BEST",
        str(data.get("best_candidate"))
    )

    html = html.replace(
        "SCAN",
        str(data.get("scan_number"))
    )

    html = html.replace(
        "ACTION",
        str(data.get("last_action"))
    )

    html = html.replace(
        "ERROR",
        str(data.get("last_error"))
    )

    if trade:

        symbol = trade["symbol"]

        entry = D(
            trade["entry_price"]
        )

        highest = D(
            trade["highest_price"]
        )

        protection = trade.get(
            "protection_price"
        )

        try:

            current = get_price(
                symbol
            )

            profit = (
                (current - entry)
                / entry
            ) * Decimal("100")

            current_text = format_decimal(
                current
            )

            profit_text = (
                f"{profit:.2f}%"
            )

        except Exception:

            current_text = "-"
            profit_text = "-"

        if protection:

            protection_text = format_decimal(
                D(protection)
            )

            protection_status = (
                "🟢 مفعّل"
            )

        else:

            protection_text = (
                "لا يوجد — ينتظر +1%"
            )

            protection_status = (
                "⏳ غير مفعّل"
            )

        html += f"""

<div class="big">
{symbol}
</div>

<div class="row">
سعر الدخول:
<b>{format_decimal(entry)}</b>
</div>

<div class="row">
السعر الحالي:
<b>{current_text}</b>
</div>

<div class="row">
الربح:
<b class="green">{profit_text}</b>
</div>

<div class="row">
أعلى سعر:
<b>{format_decimal(highest)}</b>
</div>

<div class="row">
وقف الحماية:
<b class="green">
{protection_text}
</b>
</div>

<div class="row">
الحماية:
<b>{protection_status}</b>
</div>

"""

    else:

        html += """
<div class="gray">
لا توجد صفقة مفتوحة 🔎
</div>
"""

    html += """

</div>

<script>

setTimeout(function() {
    location.reload();
}, 5000);

</script>

</body>
</html>
"""

    return html


@app.route("/api/status")
def api_status():

    with state_lock:
        return jsonify(state)


@app.route("/health")
def health():

    return "OK", 200


# =========================================================
# التشغيل
# =========================================================

def start():

    load_state()

    if not API_KEY or not API_SECRET:

        log(
            "🚨 مفاتيح Binance غير موجودة"
        )

    else:

        try:

            get_account()

            log(
                "🔗 Binance متصل ✅"
            )

        except Exception as e:

            log(
                f"🚨 فشل Binance: {e}"
            )

    thread = threading.Thread(
        target=trading_loop,
        daemon=True
    )

    thread.start()

    log(
        f"🌐 PORT = {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )


if __name__ == "__main__":
    start()
