import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

import requests
from flask import Flask, jsonify

# =========================================================
# إعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

# عمولة Binance الافتراضية 0.1%
FEE_RATE = Decimal(os.getenv("BINANCE_FEE_RATE", "0.001"))

# شروط الاستراتيجية
EMA_PERIOD = 200
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند +1% صافي
PROTECTION_START_NET = Decimal("1.0")

# مسافة وقف الحماية عن أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام 99.9% من الرصيد المتاح
BALANCE_USAGE = Decimal("0.999")

# فحص الصفقة
POSITION_CHECK_INTERVAL = 5

# بين فحوص السوق
SCAN_INTERVAL = 60

# تأخير بسيط بين طلبات Binance
REQUEST_DELAY = 0.12

STATE_FILE = "bot_data.json"

# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

# =========================================================
# الحالة
# =========================================================

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
    "binance_connected": False,
}

exchange_info_cache = None
exchange_info_time = 0

symbol_rules_cache = {}


# =========================================================
# أدوات
# =========================================================

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def dec(v):
    return Decimal(str(v))


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ فشل حفظ الحالة:", e)


def load_state():
    global state

    if not os.path.exists(STATE_FILE):
        print("ℹ️ لا يوجد ملف بيانات سابق")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)

        if isinstance(old, dict):
            state.update(old)

        print("♻️ تم تحميل البيانات السابقة")

    except Exception as e:
        print("⚠️ فشل تحميل البيانات:", e)


def format_decimal(value, places=8):
    q = Decimal("1").scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_DOWN)


# =========================================================
# Binance REST
# =========================================================

session = requests.Session()
session.headers.update({
    "X-MBX-APIKEY": API_KEY
})


def binance_request(method, path, params=None, signed=False, retries=4):
    if params is None:
        params = {}

    last_error = None

    for attempt in range(retries):

        try:
            request_params = dict(params)

            if signed:
                request_params["timestamp"] = int(time.time() * 1000)
                request_params["recvWindow"] = 10000

                query = urllib.parse.urlencode(request_params)
                signature = hmac.new(
                    API_SECRET.encode(),
                    query.encode(),
                    hashlib.sha256
                ).hexdigest()

                request_params["signature"] = signature

            url = BASE_URL + path

            response = session.request(
                method,
                url,
                params=request_params,
                timeout=15
            )

            if response.status_code == 429:

                wait_time = min(10, 2 ** attempt)

                print(
                    f"⏳ Binance 429 — انتظار {wait_time} ثانية"
                )

                time.sleep(wait_time)
                last_error = Exception(
                    f"Binance 429: {response.text}"
                )
                continue

            if response.status_code >= 400:
                raise Exception(
                    f"Binance {response.status_code}: {response.text}"
                )

            return response.json()

        except Exception as e:
            last_error = e

            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))

    raise last_error


# =========================================================
# Exchange Info
# =========================================================

def get_exchange_info(force=False):

    global exchange_info_cache
    global exchange_info_time
    global symbol_rules_cache

    if (
        exchange_info_cache is not None
        and not force
        and time.time() - exchange_info_time < 3600
    ):
        return exchange_info_cache

    data = binance_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    exchange_info_cache = data
    exchange_info_time = time.time()

    symbol_rules_cache = {}

    for s in data.get("symbols", []):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        symbol_rules_cache[s["symbol"]] = s

    return data


def get_usdt_symbols():

    data = get_exchange_info()

    symbols = []

    for s in data.get("symbols", []):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get("isSpotTradingAllowed") is False:
            continue

        symbols.append(s["symbol"])

    return symbols


# =========================================================
# الرصيد
# =========================================================

def get_account():

    return binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )


def get_balances():

    account = get_account()

    result = {}

    for b in account.get("balances", []):

        free = dec(b["free"])
        locked = dec(b["locked"])

        if free > 0 or locked > 0:
            result[b["asset"]] = {
                "free": free,
                "locked": locked
            }

    return result


def get_free_balance(asset):

    balances = get_balances()

    if asset not in balances:
        return Decimal("0")

    return balances[asset]["free"]


# =========================================================
# السعر
# =========================================================

def get_price(symbol):

    data = binance_request(
        "GET",
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return dec(data["price"])


# =========================================================
# الشموع
# =========================================================

def get_klines(symbol, interval, limit=205):

    data = binance_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    return data


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    values = [dec(x) for x in values]

    sma = sum(values[:period]) / Decimal(period)

    multiplier = Decimal("2") / Decimal(period + 1)

    ema = sma

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def price_above_ema200(symbol, interval):

    candles = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    if len(candles) < EMA_PERIOD:
        return False, None, None

    closes = [
        dec(c[4])
        for c in candles
    ]

    current_price = closes[-1]

    ema = calculate_ema(
        closes,
        EMA_PERIOD
    )

    if ema is None:
        return False, current_price, None

    return current_price > ema, current_price, ema


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
        return None

    old_close = dec(candles[-2][4])
    new_close = dec(candles[-1][4])

    if old_close <= 0:
        return None

    change = (
        (new_close - old_close)
        / old_close
        * Decimal("100")
    )

    return change


# =========================================================
# فلترة السوق
# =========================================================

def scan_market():

    symbols = get_usdt_symbols()

    state["symbols_count"] = len(symbols)

    print(
        f"🔎 فحص {len(symbols)} عملة USDT"
    )

    candidates = []

    # ---------------------------------------------
    # المرحلة 1
    # استبعاد أقل من +1% على 15 دقيقة
    # ---------------------------------------------

    for index, symbol in enumerate(symbols):

        try:

            change = get_15m_change(symbol)

            if change is None:
                continue

            if change < MIN_CHANGE_15M:
                continue

            candidates.append(
                (symbol, change)
            )

        except Exception as e:

            print(
                f"⚠️ {symbol} 15m: {e}"
            )

        time.sleep(REQUEST_DELAY)

    # الأقوى أولاً
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    state["candidates_count"] = len(candidates)

    print(
        f"📈 بعد فلتر 15m: {len(candidates)}"
    )

    # ---------------------------------------------
    # المرحلة 2
    # EMA200
    # 1m + 5m + 15m
    # ---------------------------------------------

    for symbol, change in candidates:

        try:

            ok_15, p15, ema15 = price_above_ema200(
                symbol,
                "15m"
            )

            if not ok_15:
                continue

            time.sleep(REQUEST_DELAY)

            ok_5, p5, ema5 = price_above_ema200(
                symbol,
                "5m"
            )

            if not ok_5:
                continue

            time.sleep(REQUEST_DELAY)

            ok_1, p1, ema1 = price_above_ema200(
                symbol,
                "1m"
            )

            if not ok_1:
                continue

            state["ema_pass_count"] += 1

            candidate = {
                "symbol": symbol,
                "change_15m": str(change),
                "price": str(p15),
                "ema_15m": str(ema15),
                "ema_5m": str(ema5),
                "ema_1m": str(ema1)
            }

            state["best_candidate"] = candidate

            print(
                f"🔥 أفضل فرصة: {symbol} "
                f"| 15m +{change:.2f}%"
            )

            return candidate

        except Exception as e:

            print(
                f"⚠️ تحليل {symbol}: {e}"
            )

        time.sleep(REQUEST_DELAY)

    return None


# =========================================================
# قواعد العملة
# =========================================================

def get_symbol_rules(symbol):

    if symbol in symbol_rules_cache:
        return symbol_rules_cache[symbol]

    get_exchange_info()

    return symbol_rules_cache.get(symbol)


def quantity_step(symbol):

    info = get_symbol_rules(symbol)

    if not info:
        return Decimal("0.000001")

    for f in info.get("filters", []):

        if f["filterType"] == "LOT_SIZE":
            return dec(f["stepSize"])

    return Decimal("0.000001")


def price_tick(symbol):

    info = get_symbol_rules(symbol)

    if not info:
        return Decimal("0.000001")

    for f in info.get("filters", []):

        if f["filterType"] == "PRICE_FILTER":
            return dec(f["tickSize"])

    return Decimal("0.000001")


def min_notional(symbol):

    info = get_symbol_rules(symbol)

    if not info:
        return Decimal("5")

    for f in info.get("filters", []):

        if f["filterType"] in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            if "minNotional" in f:
                return dec(f["minNotional"])

    return Decimal("5")


def floor_to_step(value, step):

    value = dec(value)
    step = dec(step)

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    usdt = get_free_balance("USDT")

    amount = usdt * BALANCE_USAGE

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    if amount <= 0:
        raise Exception("رصيد USDT غير كافي")

    if amount < min_notional(symbol):
        raise Exception(
            f"المبلغ أقل من الحد الأدنى للعملة: {amount}"
        )

    print(
        f"🟢 شراء {symbol} "
        f"بقيمة {amount} USDT"
    )

    order = binance_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": str(amount),
            "newOrderRespType": "FULL"
        },
        signed=True
    )

    executed_qty = dec(
        order.get("executedQty", "0")
    )

    quote_qty = dec(
        order.get("cummulativeQuoteQty", str(amount))
    )

    if executed_qty <= 0:
        raise Exception(
            "لم يتم تنفيذ الشراء"
        )

    entry = quote_qty / executed_qty

    trade = {
        "symbol": symbol,
        "asset": symbol.replace("USDT", ""),
        "entry": str(entry),
        "quantity": str(executed_qty),
        "highest_price": str(entry),
        "protection_price": None,
        "protection_order_id": None,
        "started_protection": False,
        "opened_at": now(),
        "manual": False
    }

    state["active_trade"] = trade
    state["last_action"] = (
        f"🟢 شراء {symbol} بسعر {entry}"
    )

    save_state()

    return trade


# =========================================================
# العمولة / صافي الربح
# =========================================================

def gross_profit_percent(entry, current):

    entry = dec(entry)
    current = dec(current)

    if entry <= 0:
        return Decimal("0")

    return (
        (current - entry)
        / entry
        * Decimal("100")
    )


def net_profit_percent(entry, current):

    gross = gross_profit_percent(
        entry,
        current
    )

    # شراء + بيع = عمولتين
    total_fee_percent = (
        FEE_RATE
        * Decimal("2")
        * Decimal("100")
    )

    return gross - total_fee_percent


# =========================================================
# أوامر الحماية
# =========================================================

def cancel_order(symbol, order_id):

    if not order_id:
        return

    try:

        binance_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            },
            signed=True
        )

        print(
            f"🗑️ تم إلغاء الحماية القديمة {order_id}"
        )

    except Exception as e:

        print(
            f"⚠️ فشل إلغاء الحماية: {e}"
        )


def create_protection(trade, stop_price):

    symbol = trade["symbol"]

    qty = dec(trade["quantity"])

    step = quantity_step(symbol)

    qty = floor_to_step(
        qty,
        step
    )

    tick = price_tick(symbol)

    stop_price = floor_to_step(
        stop_price,
        tick
    )

    if qty <= 0:
        raise Exception(
            "الكمية بعد التقريب أصبحت صفر"
        )

    print(
        f"🛡️ إنشاء حماية {symbol} "
        f"| Stop {stop_price}"
    )

    order = binance_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": str(qty),
            "stopPrice": str(stop_price),
            "newOrderRespType": "RESULT"
        },
        signed=True
    )

    order_id = order.get("orderId")

    trade["protection_price"] = str(stop_price)
    trade["protection_order_id"] = order_id
    trade["started_protection"] = True

    state["last_action"] = (
        f"🛡️ حماية جديدة {symbol} "
        f"عند {stop_price}"
    )

    save_state()

    return order


# =========================================================
# تحديث الحماية
# =========================================================

def update_protection(trade, current_price):

    entry = dec(trade["entry"])
    current_price = dec(current_price)

    # أعلى سعر
    old_high = dec(
        trade.get(
            "highest_price",
            str(entry)
        )
    )

    if current_price > old_high:

        trade["highest_price"] = str(
            current_price
        )

        old_high = current_price

    # صافي الربح
    net_profit = net_profit_percent(
        entry,
        current_price
    )

    # لم يصل +1% صافي
    if net_profit < PROTECTION_START_NET:

        trade["started_protection"] = False

        return

    # ---------------------------------------------
    # الحماية تبدأ عند +1% صافي
    # ---------------------------------------------

    # وقف الحماية خلف أعلى سعر 0.5%
    new_stop = (
        old_high
        * (
            Decimal("1")
            - TRAIL_PERCENT / Decimal("100")
        )
    )

    # نضمن أن الحماية أعلى من نقطة التعادل
    # بعد احتساب العمولة
    break_even_price = (
        entry
        * (
            Decimal("1")
            + (
                FEE_RATE
                * Decimal("2")
            )
        )
    )

    minimum_stop = (
        break_even_price
        * (
            Decimal("1")
            + Decimal("0.001")
        )
    )

    if new_stop < minimum_stop:
        new_stop = minimum_stop

    tick = price_tick(
        trade["symbol"]
    )

    new_stop = floor_to_step(
        new_stop,
        tick
    )

    old_stop_value = trade.get(
        "protection_price"
    )

    # ---------------------------------------------
    # إذا عندنا حماية قديمة
    # ---------------------------------------------

    if old_stop_value:

        old_stop = dec(
            old_stop_value
        )

        # لا ننزل الوقف
        if new_stop <= old_stop:
            return

    # ---------------------------------------------
    # حذف القديم
    # ---------------------------------------------

    old_order_id = trade.get(
        "protection_order_id"
    )

    if old_order_id:

        cancel_order(
            trade["symbol"],
            old_order_id
        )

        trade["protection_order_id"] = None

    # ---------------------------------------------
    # إنشاء الجديد
    # ---------------------------------------------

    try:

        create_protection(
            trade,
            new_stop
        )

        print(
            f"📈 رفع الوقف {trade['symbol']} "
            f"إلى {new_stop} "
            f"| صافي {net_profit:.2f}%"
        )

    except Exception as e:

        state["last_error"] = str(e)

        print(
            f"🚨 فشل رفع الوقف: {e}"
        )

        save_state()


# =========================================================
# فحص الصفقة الحالية
# =========================================================

def update_trade():

    trade = state.get(
        "active_trade"
    )

    if not trade:
        return False

    symbol = trade["symbol"]

    current = get_price(symbol)

    entry = dec(
        trade["entry"]
    )

    gross = gross_profit_percent(
        entry,
        current
    )

    net = net_profit_percent(
        entry,
        current
    )

    trade["current_price"] = str(
        current
    )

    trade["gross_profit"] = str(
        gross
    )

    trade["net_profit"] = str(
        net
    )

    high = dec(
        trade.get(
            "highest_price",
            str(entry)
        )
    )

    if current > high:

        trade["highest_price"] = str(
            current
        )

    print(
        f"📊 {symbol} "
        f"| السعر {current} "
        f"| صافي {net:.2f}% "
        f"| الأعلى {trade['highest_price']}"
    )

    # ---------------------------------------------
    # هل ما زالت الكمية موجودة؟
    # ---------------------------------------------

    asset = trade["asset"]

    try:

        balance = get_free_balance(
            asset
        )

        locked = Decimal("0")

        balances = get_balances()

        if asset in balances:
            locked = balances[asset]["locked"]

        total_asset = balance + locked

        if total_asset <= 0:

            print(
                f"✅ انتهت الصفقة {symbol}"
            )

            state["last_action"] = (
                f"✅ انتهت صفقة {symbol}"
            )

            state["active_trade"] = None

            save_state()

            return False

    except Exception as e:

        print(
            f"⚠️ فشل فحص رصيد {asset}: {e}"
        )

    # تحديث الحماية
    update_protection(
        trade,
        current
    )

    save_state()

    return True


# =========================================================
# استرجاع الصفقة المفتوحة
# =========================================================

def recover_position():

    # أولًا: الحالة المحفوظة
    saved = state.get(
        "active_trade"
    )

    if saved:

        try:

            asset = saved["asset"]

            balances = get_balances()

            if asset in balances:

                total = (
                    balances[asset]["free"]
                    + balances[asset]["locked"]
                )

                if total > 0:

                    print(
                        f"♻️ استكمال الصفقة "
                        f"{saved['symbol']}"
                    )

                    return saved

        except Exception as e:

            print(
                f"⚠️ فشل استرجاع الحالة: {e}"
            )

    # ---------------------------------------------
    # إذا ما فيه حالة محفوظة:
    # ابحث عن أي رصيد عملة USDT
    # ---------------------------------------------

    balances = get_balances()

    symbols = get_usdt_symbols()

    symbol_set = set(symbols)

    for asset, info in balances.items():

        if asset == "USDT":
            continue

        total = (
            info["free"]
            + info["locked"]
        )

        if total <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in symbol_set:
            continue

        try:

            price = get_price(symbol)

            # نحاول الحصول على سعر الدخول من آخر شراء
            trades = binance_request(
                "GET",
                "/api/v3/myTrades",
                {
                    "symbol": symbol,
                    "limit": 20
                },
                signed=True
            )

            buys = [
                t for t in trades
                if t.get("isBuyer") is True
            ]

            if buys:

                latest = buys[-1]

                entry = dec(
                    latest["price"]
                )

            else:

                # إذا ما قدرنا نجيب سعر الشراء
                entry = price

            trade = {
                "symbol": symbol,
                "asset": asset,
                "entry": str(entry),
                "quantity": str(total),
                "highest_price": str(
                    max(entry, price)
                ),
                "current_price": str(price),
                "protection_price": None,
                "protection_order_id": None,
                "started_protection": False,
                "opened_at": now(),
                "manual": True
            }

            print(
                f"♻️ صفقة مفتوحة مكتشفة: {symbol}"
            )

            print(
                f"💵 Entry: {entry}"
            )

            return trade

        except Exception as e:

            print(
                f"⚠️ تجاهل {symbol}: {e}"
            )

        time.sleep(REQUEST_DELAY)

    return None


# =========================================================
# محرك التداول
# =========================================================

def trading_loop():

    print("🚀 بدأ محرك التداول")

    while True:

        try:

            # -----------------------------------------
            # إذا فيه صفقة
            # -----------------------------------------

            if state.get("active_trade"):

                update_trade()

                time.sleep(
                    POSITION_CHECK_INTERVAL
                )

                continue

            # -----------------------------------------
            # استرجاع أي صفقة مفتوحة
            # -----------------------------------------

            recovered = recover_position()

            if recovered:

                state["active_trade"] = recovered
                state["last_action"] = (
                    f"♻️ استكمال {recovered['symbol']}"
                )

                save_state()

                continue

            # -----------------------------------------
            # لا توجد صفقة
            # -----------------------------------------

            state["scan_number"] += 1
            state["ema_pass_count"] = 0

            state["last_scan"] = now()

            print(
                f"\n🔎 بدء فحص رقم "
                f"{state['scan_number']}"
            )

            candidate = scan_market()

            if candidate:

                symbol = candidate["symbol"]

                print(
                    f"🚀 دخول: {symbol}"
                )

                try:

                    market_buy(
                        symbol
                    )

                except Exception as e:

                    state["last_error"] = str(e)

                    print(
                        f"🚨 فشل الدخول: {e}"
                    )

            else:

                state["last_action"] = (
                    "⏳ لا توجد فرصة مطابقة"
                )

                print(
                    "⏳ لا توجد عملة مطابقة"
                )

            save_state()

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            state["last_error"] = str(e)

            print(
                f"🚨 خطأ المحرك: {e}"
            )

            save_state()

            time.sleep(10)


# =========================================================
# Dashboard
# =========================================================

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مضارب أبو سعود</title>

<style>
body{
    margin:0;
    font-family:Arial,sans-serif;
    background:#0f1115;
    color:#fff;
}
.container{
    max-width:900px;
    margin:auto;
    padding:20px;
}
h1{
    margin-bottom:5px;
}
.card{
    background:#191d24;
    border-radius:15px;
    padding:18px;
    margin:12px 0;
}
.row{
    display:flex;
    justify-content:space-between;
    padding:9px 0;
    border-bottom:1px solid #292e38;
}
.green{
    color:#35d07f;
}
.red{
    color:#ff5b6e;
}
.yellow{
    color:#ffc857;
}
.big{
    font-size:28px;
    font-weight:bold;
}
.small{
    color:#aeb5c2;
}
</style>
</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود</h1>
<div class="small">Binance Spot</div>

<div class="card">

<div class="row">
<span>الحالة</span>
<b id="status">...</b>
</div>

<div class="row">
<span>العملة</span>
<b id="symbol">...</b>
</div>

<div class="row">
<span>الدخول</span>
<b id="entry">...</b>
</div>

<div class="row">
<span>السعر</span>
<b id="price">...</b>
</div>

<div class="row">
<span>الربح الصافي</span>
<b id="profit">...</b>
</div>

<div class="row">
<span>أعلى سعر</span>
<b id="high">...</b>
</div>

<div class="row">
<span>حماية الربح</span>
<b id="protection">...</b>
</div>

</div>


<div class="card">

<div class="row">
<span>عدد العملات</span>
<b id="symbols">...</b>
</div>

<div class="row">
<span>المرشحات +1%</span>
<b id="candidates">...</b>
</div>

<div class="row">
<span>اجتازت EMA</span>
<b id="ema">...</b>
</div>

<div class="row">
<span>أفضل مرشح</span>
<b id="best">...</b>
</div>

<div class="row">
<span>رقم الفحص</span>
<b id="scan">...</b>
</div>

<div class="row">
<span>آخر إجراء</span>
<b id="action">...</b>
</div>

<div class="row">
<span>آخر خطأ</span>
<b id="error">لا يوجد</b>
</div>

</div>

</div>


<script>

async function update(){

    try{

        const r = await fetch('/api/status');
        const d = await r.json();

        document.getElementById('status').innerText =
            d.status || '-';

        const t = d.active_trade;

        if(t){

            document.getElementById('symbol').innerText =
                t.symbol || '-';

            document.getElementById('entry').innerText =
                t.entry || '-';

            document.getElementById('price').innerText =
                t.current_price || '-';

            const p =
                parseFloat(t.net_profit || 0);

            const pe =
                document.getElementById('profit');

            pe.innerText =
                p.toFixed(2) + '%';

            pe.className =
                p >= 0 ? 'green' : 'red';

            document.getElementById('high').innerText =
                t.highest_price || '-';

            document.getElementById('protection').innerText =
                t.protection_price
                ? t.protection_price
                : 'لم تبدأ';

        }else{

            document.getElementById('symbol').innerText =
                'لا توجد صفقة';

            document.getElementById('entry').innerText =
                '-';

            document.getElementById('price').innerText =
                '-';

            document.getElementById('profit').innerText =
                '-';

            document.getElementById('high').innerText =
                '-';

            document.getElementById('protection').innerText =
                '-';
        }

        document.getElementById('symbols').innerText =
            d.symbols_count || 0;

        document.getElementById('candidates').innerText =
            d.candidates_count || 0;

        document.getElementById('ema').innerText =
            d.ema_pass_count || 0;

        if(d.best_candidate){

            document.getElementById('best').innerText =
                d.best_candidate.symbol +
                ' +' +
                parseFloat(
                    d.best_candidate.change_15m
                ).toFixed(2) +
                '%';

        }else{

            document.getElementById('best').innerText =
                '-';
        }

        document.getElementById('scan').innerText =
            d.scan_number || 0;

        document.getElementById('action').innerText =
            d.last_action || '-';

        document.getElementById('error').innerText =
            d.last_error || 'لا يوجد';

    }catch(e){

        document.getElementById('error').innerText =
            'تعذر الاتصال بالبوت';

    }
}

update();
setInterval(update,5000);

</script>

</body>
</html>
"""


@app.route("/")
def home():
    return HTML


@app.route("/api/status")
def api_status():
    return jsonify(state)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "time": now()
    })


# =========================================================
# التشغيل
# =========================================================

def start_bot():

    load_state()

    if not API_KEY or not API_SECRET:

        state["last_error"] = (
            "BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود"
        )

        print(
            "🚨 مفاتيح Binance غير موجودة"
        )

    else:

        try:

            get_exchange_info()

            state["binance_connected"] = True

            print(
                "🔗 Binance متصل ✅"
            )

        except Exception as e:

            state["binance_connected"] = False
            state["last_error"] = str(e)

            print(
                f"🚨 فشل Binance: {e}"
            )

    thread = threading.Thread(
        target=trading_loop,
        daemon=True
    )

    thread.start()


if __name__ == "__main__":

    start_bot()

    print(
        f"🌐 PORT = {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        threaded=True
    )
