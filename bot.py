import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string
from threading import Thread


# =========================================================
# إعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"

PORT = int(os.getenv("PORT", "10000"))

# عمولة افتراضية 0.1% لكل عملية
FEE_RATE = Decimal(os.getenv("BINANCE_FEE_RATE", "0.001"))

EMA_PERIOD = 200

# لازم يكون التغير أكبر من 1%
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند صافي +1%
PROTECTION_START_NET = Decimal("1.0")

# مسافة التأمين خلف أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام 99.9% من الرصيد لتجنب مشاكل الرسوم
BALANCE_USAGE = Decimal("0.999")

POSITION_CHECK_INTERVAL = 5
SCAN_INTERVAL = 60

# تأخير بين الطلبات
REQUEST_DELAY = 0.15

STATE_FILE = "bot_data.json"


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

session = requests.Session()

symbol_rules_cache = {}
exchange_info_cache = None
exchange_info_time = 0


# =========================================================
# حالة البوت
# =========================================================

state = {
    "status": "بدء التشغيل",
    "active_trade": None,

    "scan_number": 0,
    "ema_pass_count": 0,

    "last_scan": None,
    "last_action": "",
    "last_error": "",

    "best_candidate": "",
    "candidate_change": "",

    "last_update": None
}


# =========================================================
# الوقت
# =========================================================

def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# حفظ الحالة
# =========================================================

def save_state():

    try:

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    except Exception as e:

        print(f"⚠️ فشل حفظ الحالة: {e}")


def load_state():

    global state

    try:

        with open(STATE_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)

        state.update(old)

        print("♻️ تم استرجاع بيانات البوت")

    except FileNotFoundError:

        print("ℹ️ لا يوجد ملف بيانات سابق")

    except Exception as e:

        print(f"⚠️ فشل قراءة الحالة: {e}")


# =========================================================
# طلبات Binance
# =========================================================

def binance_request(
    method,
    endpoint,
    params=None,
    signed=False
):

    if params is None:
        params = {}

    params = dict(params)

    if signed:

        params["timestamp"] = int(time.time() * 1000)

        query = urllib.parse.urlencode(params)

        signature = hmac.new(
            API_SECRET.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

        query += "&signature=" + signature

    else:

        query = urllib.parse.urlencode(params)

    url = BASE_URL + endpoint

    headers = {}

    if API_KEY:
        headers["X-MBX-APIKEY"] = API_KEY

    for attempt in range(5):

        try:

            if method == "GET":

                r = session.get(
                    url,
                    params=urllib.parse.parse_qs(query),
                    headers=headers,
                    timeout=20
                )

            elif method == "POST":

                r = session.post(
                    url,
                    params=urllib.parse.parse_qs(query),
                    headers=headers,
                    timeout=20
                )

            elif method == "DELETE":

                r = session.delete(
                    url,
                    params=urllib.parse.parse_qs(query),
                    headers=headers,
                    timeout=20
                )

            else:

                raise Exception("طريقة طلب غير مدعومة")

            if r.status_code == 429:

                wait_time = min(
                    15,
                    2 ** attempt
                )

                print(
                    f"⚠️ Binance 429 → انتظار {wait_time} ثواني"
                )

                time.sleep(wait_time)
                continue

            if r.status_code >= 400:

                raise Exception(
                    f"Binance {r.status_code}: {r.text}"
                )

            time.sleep(REQUEST_DELAY)

            return r.json()

        except requests.RequestException as e:

            if attempt >= 4:
                raise

            wait_time = min(
                10,
                2 ** attempt
            )

            print(
                f"⚠️ اتصال Binance → إعادة المحاولة بعد {wait_time}"
            )

            time.sleep(wait_time)

    raise Exception("فشل الاتصال بـ Binance")


# =========================================================
# معلومات العملات
# =========================================================

def get_exchange_info():

    global exchange_info_cache
    global exchange_info_time
    global symbol_rules_cache

    current = time.time()

    if (
        exchange_info_cache is not None
        and current - exchange_info_time < 3600
    ):

        return exchange_info_cache

    data = binance_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    exchange_info_cache = data
    exchange_info_time = current

    symbol_rules_cache = {}

    for s in data["symbols"]:

        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["isSpotTradingAllowed"]
        ):

            filters = {}

            for f in s["filters"]:
                filters[f["filterType"]] = f

            symbol_rules_cache[s["symbol"]] = filters

    print(
        f"📚 تم تحميل {len(symbol_rules_cache)} عملة USDT"
    )

    return data


def get_usdt_symbols():

    get_exchange_info()

    return list(symbol_rules_cache.keys())


# =========================================================
# الشموع
# =========================================================

def get_klines(symbol, interval, limit=220):

    return binance_request(
        "GET",
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

def calculate_ema(closes, period=200):

    if len(closes) < period:
        return None

    ema = sum(closes[:period]) / Decimal(period)

    multiplier = Decimal("2") / (
        Decimal(period) + Decimal("1")
    )

    for price in closes[period:]:

        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


def price_above_ema200(symbol, interval):

    klines = get_klines(
        symbol,
        interval,
        210
    )

    closes = [
        Decimal(k[4])
        for k in klines
    ]

    if len(closes) < EMA_PERIOD:
        return False, None, None

    current_price = closes[-1]

    ema = calculate_ema(
        closes,
        EMA_PERIOD
    )

    if ema is None:
        return False, current_price, None

    return (
        current_price > ema,
        current_price,
        ema
    )


# =========================================================
# تغير 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    klines = get_klines(
        symbol,
        "15m",
        2
    )

    if len(klines) < 2:
        return None

    previous_close = Decimal(
        klines[-2][4]
    )

    current_close = Decimal(
        klines[-1][4]
    )

    if previous_close <= 0:
        return None

    change = (
        (current_close - previous_close)
        / previous_close
    ) * Decimal("100")

    return change


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    state["best_candidate"] = ""
    state["candidate_change"] = ""
    state["ema_pass_count"] = 0

    symbols = get_usdt_symbols()

    candidates = []

    print(
        f"🔎 فحص {len(symbols)} عملة..."
    )

    # -----------------------------------------------------
    # المرحلة الأولى:
    # تغير 15m أكبر من 1%
    # -----------------------------------------------------

    for symbol in symbols:

        try:

            change = get_15m_change(symbol)

            if change is None:
                continue

            # مهم:
            # 1.00% ❌
            # 1.01% ✅
            if change <= MIN_CHANGE_15M:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "change": change
                }
            )

        except Exception as e:

            print(
                f"⚠️ {symbol} 15m: {e}"
            )

    # الأقوى أولًا حسب تغير 15 دقيقة
    candidates.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    print(
        f"📈 مرشحون بعد شرط >1%: {len(candidates)}"
    )

    # -----------------------------------------------------
    # المرحلة الثانية:
    # EMA200
    # -----------------------------------------------------

    for candidate in candidates:

        symbol = candidate["symbol"]
        change = candidate["change"]

        try:

            print(
                f"🔍 {symbol} | 15m: +{change:.2f}%"
            )

            ok_15m, price_15m, ema_15m = (
                price_above_ema200(
                    symbol,
                    "15m"
                )
            )

            if not ok_15m:
                continue

            ok_5m, price_5m, ema_5m = (
                price_above_ema200(
                    symbol,
                    "5m"
                )
            )

            if not ok_5m:
                continue

            ok_1m, price_1m, ema_1m = (
                price_above_ema200(
                    symbol,
                    "1m"
                )
            )

            if not ok_1m:
                continue

            state["ema_pass_count"] += 1

            # بما أن القائمة مرتبة تنازليًا
            # أول عملة تجتاز EMA = الأقوى في 15m
            state["best_candidate"] = symbol
            state["candidate_change"] = (
                f"{change:.2f}%"
            )

            state["last_action"] = (
                f"🔥 أفضل فرصة {symbol} "
                f"| تغير 15m +{change:.2f}%"
            )

            print(
                f"🔥 الأفضل: {symbol} "
                f"| +{change:.2f}%"
            )

            return {
                "symbol": symbol,
                "change": change
            }

        except Exception as e:

            print(
                f"⚠️ فشل فحص EMA لـ {symbol}: {e}"
            )

    return None


# =========================================================
# السعر الحالي
# =========================================================

def get_price(symbol):

    data = binance_request(
        "GET",
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return Decimal(data["price"])


# =========================================================
# الحساب
# =========================================================

def get_account():

    return binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )


def get_free_balance(asset):

    account = get_account()

    for balance in account["balances"]:

        if balance["asset"] == asset:

            return Decimal(
                balance["free"]
            )

    return Decimal("0")


# =========================================================
# قواعد العملة
# =========================================================

def floor_step(value, step):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def get_symbol_rules(symbol):

    get_exchange_info()

    filters = symbol_rules_cache.get(
        symbol,
        {}
    )

    lot = filters.get(
        "LOT_SIZE"
    )

    price_filter = filters.get(
        "PRICE_FILTER"
    )

    min_notional = filters.get(
        "MIN_NOTIONAL"
    )

    return {
        "step_size": Decimal(
            lot["stepSize"]
        ) if lot else Decimal("0.000001"),

        "min_qty": Decimal(
            lot["minQty"]
        ) if lot else Decimal("0"),

        "tick_size": Decimal(
            price_filter["tickSize"]
        ) if price_filter else Decimal("0.00000001"),

        "min_notional": Decimal(
            min_notional["minNotional"]
        ) if min_notional else Decimal("5")
    }


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    usdt = get_free_balance("USDT")

    amount = (
        usdt * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    if amount <= 0:
        raise Exception("رصيد USDT غير كافٍ")

    print(
        f"💰 الرصيد المتاح: {usdt} USDT"
    )

    print(
        f"🟢 شراء {symbol} بقيمة {amount} USDT"
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

    executed_qty = Decimal(
        order["executedQty"]
    )

    quote_qty = Decimal(
        order["cummulativeQuoteQty"]
    )

    if executed_qty <= 0:
        raise Exception("لم يتم تنفيذ الشراء")

    entry = (
        quote_qty / executed_qty
    )

    trade = {
        "symbol": symbol,
        "entry": str(entry),
        "qty": str(executed_qty),

        "highest": str(entry),

        "protection_active": False,
        "protection_price": None,
        "protection_order_id": None,

        "opened_at": now()
    }

    return trade


# =========================================================
# أوامر الحماية
# =========================================================

def cancel_order(symbol, order_id):

    try:

        return binance_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            },
            signed=True
        )

    except Exception as e:

        print(
            f"⚠️ فشل إلغاء أمر الحماية: {e}"
        )

        return None


def create_protection(
    symbol,
    qty,
    stop_price
):

    rules = get_symbol_rules(symbol)

    qty = floor_step(
        qty,
        rules["step_size"]
    )

    stop_price = floor_step(
        stop_price,
        rules["tick_size"]
    )

    if qty < rules["min_qty"]:

        raise Exception(
            "الكمية أقل من الحد الأدنى"
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

    return order


# =========================================================
# تحديث تأمين الربح
# =========================================================

def update_protection(
    trade,
    current_price,
    net_profit
):

    symbol = trade["symbol"]

    entry = Decimal(
        trade["entry"]
    )

    qty = Decimal(
        trade["qty"]
    )

    highest = Decimal(
        trade["highest"]
    )

    # تحديث أعلى سعر
    if current_price > highest:

        highest = current_price

        trade["highest"] = str(
            highest
        )

    # لم يصل +1% صافي
    if net_profit < PROTECTION_START_NET:

        return

    # -----------------------------------------------------
    # حساب سعر التأمين
    # -----------------------------------------------------

    trail = (
        highest
        * (
            Decimal("1")
            - TRAIL_PERCENT / Decimal("100")
        )
    )

    # لازم يكون التأمين فوق سعر التعادل
    break_even = (
        entry
        * (
            Decimal("1")
            + FEE_RATE * Decimal("2")
        )
    )

    minimum_stop = (
        break_even
        * Decimal("1.001")
    )

    new_stop = max(
        trail,
        minimum_stop
    )

    old_stop = None

    if trade["protection_price"]:

        old_stop = Decimal(
            trade["protection_price"]
        )

    # لا ننزل الحماية
    if old_stop is not None:

        if new_stop <= old_stop:

            return

    # إلغاء الحماية القديمة
    if trade["protection_order_id"]:

        cancel_order(
            symbol,
            trade["protection_order_id"]
        )

    try:

        order = create_protection(
            symbol,
            qty,
            new_stop
        )

        trade["protection_order_id"] = (
            order["orderId"]
        )

        trade["protection_price"] = str(
            new_stop
        )

        trade["protection_active"] = True

        state["last_action"] = (
            f"🛡️ رفع تأمين {symbol} "
            f"إلى {new_stop}"
        )

        print(
            f"🛡️ تأمين جديد: "
            f"{symbol} → {new_stop}"
        )

    except Exception as e:

        print(
            f"🚨 فشل إنشاء التأمين: {e}"
        )

        state["last_error"] = str(e)


# =========================================================
# فحص الصفقة
# =========================================================

def update_trade():

    trade = state.get(
        "active_trade"
    )

    if not trade:
        return False

    symbol = trade["symbol"]

    entry = Decimal(
        trade["entry"]
    )

    current = get_price(symbol)

    gross = (
        (
            current - entry
        )
        / entry
    ) * Decimal("100")

    total_fee = (
        FEE_RATE
        * Decimal("2")
        * Decimal("100")
    )

    net = gross - total_fee

    trade["current_price"] = str(
        current
    )

    trade["gross_profit"] = str(
        gross
    )

    trade["net_profit"] = str(
        net
    )

    # تحديث التأمين
    update_protection(
        trade,
        current,
        net
    )

    state["last_update"] = now()

    print(
        f"📊 {symbol} | "
        f"السعر {current} | "
        f"الصافي {net:.2f}% | "
        f"الأعلى {trade['highest']}"
    )

    # -----------------------------------------------------
    # هل الصفقة أغلقت؟
    # -----------------------------------------------------

    try:

        asset = symbol.replace(
            "USDT",
            ""
        )

        balance = get_free_balance(
            asset
        )

        if balance <= 0:

            print(
                f"✅ الصفقة {symbol} أغلقت"
            )

            state["last_action"] = (
                f"✅ إغلاق {symbol}"
            )

            state["active_trade"] = None

            save_state()

            return False

    except Exception as e:

        print(
            f"⚠️ خطأ فحص الرصيد: {e}"
        )

    save_state()

    return True


# =========================================================
# استرجاع صفقة مفتوحة
# =========================================================

def recover_position():

    try:

        account = get_account()

        balances = account["balances"]

        # لا نلمس USDT
        for balance in balances:

            asset = balance["asset"]

            if asset == "USDT":
                continue

            free = Decimal(
                balance["free"]
            )

            locked = Decimal(
                balance["locked"]
            )

            total = free + locked

            if total <= 0:
                continue

            symbol = asset + "USDT"

            if symbol not in symbol_rules_cache:
                continue

            try:

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
                    if t["isBuyer"]
                ]

                if not buys:
                    continue

                latest = buys[-1]

                entry = Decimal(
                    latest["price"]
                )

                qty = total

                print(
                    f"♻️ صفقة مفتوحة مكتشفة: "
                    f"{symbol}"
                )

                return {
                    "symbol": symbol,
                    "entry": str(entry),
                    "qty": str(qty),

                    "highest": str(entry),

                    "protection_active": False,
                    "protection_price": None,
                    "protection_order_id": None,

                    "opened_at": now()
                }

            except Exception as e:

                print(
                    f"⚠️ خطأ استرجاع {symbol}: {e}"
                )

    except Exception as e:

        print(
            f"⚠️ خطأ استرجاع الصفقة: {e}"
        )

    return None


# =========================================================
# محرك التداول
# =========================================================

def trading_loop():

    print("🚀 بدأ محرك التداول")

    while True:

        try:

            # =================================================
            # 1️⃣ أول شيء: الصفقة المفتوحة
            # =================================================

            if state.get("active_trade"):

                print(
                    f"📌 صفقة موجودة: "
                    f"{state['active_trade']['symbol']}"
                )

                update_trade()

                time.sleep(
                    POSITION_CHECK_INTERVAL
                )

                continue

            # =================================================
            # 2️⃣ البحث عن صفقة موجودة في Binance
            # =================================================

            print(
                "🔍 فحص الصفقات المفتوحة أولًا..."
            )

            recovered = recover_position()

            if recovered:

                state["active_trade"] = recovered

                state["status"] = (
                    "إدارة صفقة"
                )

                state["last_action"] = (
                    f"♻️ استكمال الصفقة "
                    f"{recovered['symbol']}"
                )

                save_state()

                print(
                    f"♻️ تم العثور على صفقة: "
                    f"{recovered['symbol']}"
                )

                continue

            # =================================================
            # 3️⃣ ما فيه صفقة → فحص السوق
            # =================================================

            state["status"] = "فحص السوق"

            state["scan_number"] += 1

            state["ema_pass_count"] = 0

            state["last_scan"] = now()

            print(
                "🔎 لا توجد صفقات مفتوحة"
            )

            print(
                f"🔎 بدء فحص السوق رقم "
                f"{state['scan_number']}"
            )

            candidate = scan_market()

            # =================================================
            # 4️⃣ الدخول في الأقوى
            # =================================================

            if candidate:

                symbol = candidate["symbol"]

                print(
                    f"🔥 أفضل فرصة: {symbol}"
                )

                try:

                    trade = market_buy(
                        symbol
                    )

                    state["active_trade"] = trade

                    state["status"] = (
                        "إدارة صفقة"
                    )

                    state["last_action"] = (
                        f"🟢 دخول {symbol}"
                    )

                    state["last_error"] = ""

                    save_state()

                    print(
                        f"🟢 تم الدخول في {symbol}"
                    )

                    continue

                except Exception as e:

                    state["last_error"] = str(e)

                    state["last_action"] = (
                        "🚨 فشل الدخول"
                    )

                    print(
                        f"🚨 فشل الدخول: {e}"
                    )

            else:

                state["last_action"] = (
                    "⏳ لا توجد فرصة مطابقة"
                )

                print(
                    "⏳ لا توجد فرصة مطابقة"
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
# لوحة المتابعة
# =========================================================

HTML = """
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>مضارب أبو سعود</title>

<style>

body {
    font-family: Arial, sans-serif;
    background: #111;
    color: white;
    padding: 20px;
}

.card {
    background: #1d1d1d;
    padding: 18px;
    margin-bottom: 15px;
    border-radius: 14px;
}

.title {
    font-size: 26px;
    font-weight: bold;
    margin-bottom: 15px;
}

.value {
    font-size: 21px;
    margin: 8px 0;
}

.green {
    color: #00d084;
}

.red {
    color: #ff4d4d;
}

.yellow {
    color: #ffd166;
}

.small {
    color: #aaa;
}

</style>

</head>

<body>

<div class="title">
🤖 مضارب أبو سعود
</div>

<div class="card">

<div class="value">
الحالة:
<span id="status">...</span>
</div>

<div class="value">
الصفقة:
<span id="symbol">...</span>
</div>

<div class="value">
سعر الدخول:
<span id="entry">...</span>
</div>

<div class="value">
السعر الحالي:
<span id="price">...</span>
</div>

<div class="value">
صافي الربح:
<span id="profit">...</span>
</div>

<div class="value">
أعلى سعر:
<span id="highest">...</span>
</div>

<div class="value">
تأمين الربح:
<span id="protection">...</span>
</div>

</div>


<div class="card">

<div class="value">
🔎 رقم الفحص:
<span id="scan">...</span>
</div>

<div class="value">
🔥 أفضل مرشح:
<span id="candidate">...</span>
</div>

<div class="value">
📈 تغير 15 دقيقة:
<span id="change">...</span>
</div>

<div class="value">
📊 العملات التي اجتازت EMA:
<span id="ema">...</span>
</div>

<div class="value">
📝 آخر إجراء:
<span id="action">...</span>
</div>

<div class="value">
⚠️ آخر خطأ:
<span id="error">...</span>
</div>

</div>


<script>

async function update() {

    try {

        const r = await fetch('/api/status');

        const d = await r.json();

        document.getElementById('status').innerText =
            d.status || '-';

        const trade = d.active_trade;

        if (trade) {

            document.getElementById('symbol').innerText =
                trade.symbol || '-';

            document.getElementById('entry').innerText =
                trade.entry || '-';

            document.getElementById('price').innerText =
                trade.current_price || '-';

            document.getElementById('profit').innerText =
                (trade.net_profit || '-') + '%';

            document.getElementById('highest').innerText =
                trade.highest || '-';

            document.getElementById('protection').innerText =
                trade.protection_price || 'غير مفعّل';

        } else {

            document.getElementById('symbol').innerText =
                'لا توجد صفقة';

            document.getElementById('entry').innerText =
                '-';

            document.getElementById('price').innerText =
                '-';

            document.getElementById('profit').innerText =
                '-';

            document.getElementById('highest').innerText =
                '-';

            document.getElementById('protection').innerText =
                '-';
        }

        document.getElementById('scan').innerText =
            d.scan_number || 0;

        document.getElementById('candidate').innerText =
            d.best_candidate || '-';

        document.getElementById('change').innerText =
            d.candidate_change || '-';

        document.getElementById('ema').innerText =
            d.ema_pass_count || 0;

        document.getElementById('action').innerText =
            d.last_action || '-';

        document.getElementById('error').innerText =
            d.last_error || 'لا يوجد';

    }

    catch(e) {

        console.log(e);

    }

}

update();

setInterval(update, 5000);

</script>

</body>

</html>
"""


@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    return jsonify(state)


# =========================================================
# تشغيل Flask
# =========================================================

def start_web():

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    load_state()

    try:

        if not API_KEY or not API_SECRET:

            print(
                "🚨 BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود"
            )

        else:

            get_exchange_info()

    except Exception as e:

        print(
            f"🚨 فشل Binance عند البداية: {e}"
        )

    Thread(
        target=start_web,
        daemon=True
    ).start()

    trading_loop()
