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
# إعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"

PORT = int(os.getenv("PORT", "10000"))

# الفريمات
TF_FAST = "1m"
TF_MID = "5m"
TF_MAIN = "15m"

# EMA
EMA_PERIOD = 200

# لازم تغير 15 دقيقة يكون أكبر من هذا
MIN_CHANGE_15M = 1.0

# يبدأ تأمين الربح عند +1%
TRAIL_ACTIVATION_PROFIT = 1.0

# Trailing Delta = 0.5%
# 50 BIPS = 0.50%
TRAILING_DELTA_BIPS = 50

# استخدم تقريباً كامل الرصيد
BALANCE_USAGE = 0.999

# فحص البوت
SCAN_INTERVAL = 20

# تأخير بسيط بين طلبات Binance
REQUEST_DELAY = 0.08

STATE_FILE = "bot_data.json"


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

lock = threading.Lock()

state = {
    "status": "starting",
    "active_trade": None,
    "last_scan": None,
    "last_error": None,
    "symbols_count": 0,
    "candidates_count": 0,
    "best_candidate": None,
    "last_action": "بدء التشغيل",
}


# =========================================================
# HTML
# =========================================================

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مضارب أبو سعود 🤖</title>

<style>
body{
    margin:0;
    background:#0f1115;
    color:#fff;
    font-family:Arial,sans-serif;
}
.container{
    max-width:900px;
    margin:auto;
    padding:20px;
}
h1{
    text-align:center;
    margin-bottom:20px;
}
.card{
    background:#181b22;
    border-radius:15px;
    padding:18px;
    margin-bottom:15px;
    box-shadow:0 4px 15px #0005;
}
.row{
    display:flex;
    justify-content:space-between;
    padding:9px 0;
    border-bottom:1px solid #292d36;
}
.row:last-child{
    border-bottom:0;
}
.green{
    color:#20e080;
}
.red{
    color:#ff5757;
}
.yellow{
    color:#ffd34d;
}
.big{
    font-size:24px;
    font-weight:bold;
}
small{
    color:#999;
}
</style>
</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود</h1>

<div class="card">

<div class="row">
<span>الحالة</span>
<b id="status">...</b>
</div>

<div class="row">
<span>آخر إجراء</span>
<b id="action">...</b>
</div>

<div class="row">
<span>عدد العملات</span>
<b id="symbols">...</b>
</div>

<div class="row">
<span>مرشحين +1%</span>
<b id="candidates">...</b>
</div>

<div class="row">
<span>أفضل عملة</span>
<b id="best">...</b>
</div>

</div>


<div class="card">

<h2>📈 الصفقة الحالية</h2>

<div class="row">
<span>العملة</span>
<b id="symbol">لا توجد</b>
</div>

<div class="row">
<span>سعر الدخول</span>
<b id="entry">-</b>
</div>

<div class="row">
<span>السعر الحالي</span>
<b id="price">-</b>
</div>

<div class="row">
<span>الربح</span>
<b id="profit">-</b>
</div>

<div class="row">
<span>حماية Binance</span>
<b id="protection">-</b>
</div>

<div class="row">
<span>كمية الصفقة</span>
<b id="qty">-</b>
</div>

</div>

<div class="card">
<small>
الشروط: 1د فوق EMA200 + 5د فوق EMA200 + 15د فوق EMA200
<br>
وتغير 15د أكبر من +1%
<br>
يتم اختيار أعلى تغير.
<br>
تأمين الربح يبدأ عند +1%.
</small>
</div>

</div>


<script>

async function update(){

    try{

        const r = await fetch('/api/status');
        const d = await r.json();

        document.getElementById("status").innerText =
            d.status || "-";

        document.getElementById("action").innerText =
            d.last_action || "-";

        document.getElementById("symbols").innerText =
            d.symbols_count || 0;

        document.getElementById("candidates").innerText =
            d.candidates_count || 0;

        if(d.best_candidate){

            document.getElementById("best").innerText =
                d.best_candidate.symbol +
                " | +" +
                d.best_candidate.change.toFixed(2) +
                "%";

        }else{

            document.getElementById("best").innerText =
                "لا يوجد";

        }


        if(d.active_trade){

            let t = d.active_trade;

            document.getElementById("symbol").innerText =
                t.symbol;

            document.getElementById("entry").innerText =
                t.entry_price;

            document.getElementById("price").innerText =
                t.current_price;

            let p = Number(t.profit_percent || 0);

            let pe = document.getElementById("profit");

            pe.innerText =
                (p >= 0 ? "+" : "") +
                p.toFixed(2) +
                "%";

            pe.className =
                p >= 0 ? "green big" : "red big";

            document.getElementById("qty").innerText =
                t.quantity;

            document.getElementById("protection").innerText =
                t.protection || "غير مفعلة";

        }else{

            document.getElementById("symbol").innerText =
                "لا توجد";

            document.getElementById("entry").innerText =
                "-";

            document.getElementById("price").innerText =
                "-";

            document.getElementById("profit").innerText =
                "-";

            document.getElementById("qty").innerText =
                "-";

            document.getElementById("protection").innerText =
                "-";
        }

    }catch(e){

        document.getElementById("status").innerText =
            "الاتصال باللوحة فيه مشكلة";

    }

}

update();
setInterval(update,5000);

</script>

</body>
</html>
"""


# =========================================================
# حفظ واستعادة
# =========================================================

def save_state():

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print("⚠️ خطأ حفظ الحالة:", e)


def load_state():

    global state

    try:

        if os.path.exists(STATE_FILE):

            with open(STATE_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)

            if isinstance(old, dict):
                state.update(old)

            print("📂 تم تحميل ملف البيانات السابق")

        else:

            print("ℹ️ لا يوجد ملف بيانات سابق")

    except Exception as e:

        print("⚠️ خطأ تحميل الحالة:", e)


# =========================================================
# Binance API
# =========================================================

session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY
})


def signed_request(method, path, params=None):

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE_URL + path + "?" + query

    try:

        r = session.request(
            method,
            url,
            timeout=15
        )

        if r.status_code >= 400:

            raise Exception(
                f"Binance {r.status_code}: {r.text}"
            )

        return r.json()

    except Exception as e:

        raise


def public_get(path, params=None):

    try:

        r = session.get(
            BASE_URL + path,
            params=params,
            timeout=15
        )

        if r.status_code >= 400:

            raise Exception(
                f"Binance {r.status_code}: {r.text}"
            )

        return r.json()

    except Exception:

        raise


# =========================================================
# معلومات العملات
# =========================================================

exchange_info_cache = None
exchange_info_time = 0


def get_exchange_info():

    global exchange_info_cache
    global exchange_info_time

    if (
        exchange_info_cache is not None
        and time.time() - exchange_info_time < 3600
    ):
        return exchange_info_cache

    print("📥 تحميل معلومات Binance...")

    data = public_get("/api/v3/exchangeInfo")

    exchange_info_cache = data
    exchange_info_time = time.time()

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

        symbols.append(s)

    return symbols


# =========================================================
# Filters
# =========================================================

def symbol_filters(symbol_info):

    result = {
        "step_size": Decimal("0.000001"),
        "min_qty": Decimal("0"),
        "min_notional": Decimal("0"),
        "tick_size": Decimal("0.00000001"),
    }

    for f in symbol_info.get("filters", []):

        typ = f.get("filterType")

        if typ == "LOT_SIZE":

            result["step_size"] = Decimal(
                f.get("stepSize", "0.000001")
            )

            result["min_qty"] = Decimal(
                f.get("minQty", "0")
            )

        elif typ in ("MIN_NOTIONAL", "NOTIONAL"):

            result["min_notional"] = Decimal(
                f.get("minNotional", "0")
            )

        elif typ == "PRICE_FILTER":

            result["tick_size"] = Decimal(
                f.get("tickSize", "0.00000001")
            )

    return result


def round_step(value, step):

    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# =========================================================
# Account
# =========================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_usdt_balance():

    account = get_account()

    for b in account.get("balances", []):

        if b.get("asset") == "USDT":

            return Decimal(b.get("free", "0"))

    return Decimal("0")


# =========================================================
# الأسعار
# =========================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return Decimal(data["price"])


# =========================================================
# Klines
# =========================================================

def get_klines(symbol, interval, limit=210):

    data = public_get(
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


def timeframe_above_ema(symbol, interval):

    candles = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    closes = [
        Decimal(str(c[4]))
        for c in candles
    ]

    if len(closes) < EMA_PERIOD:
        return False, None, None

    # آخر شمعة
    price = closes[-1]

    ema = calculate_ema(
        closes,
        EMA_PERIOD
    )

    if ema is None:
        return False, price, None

    return price > ema, price, ema


# =========================================================
# تغير 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    candles = get_klines(
        symbol,
        TF_MAIN,
        3
    )

    if len(candles) < 2:
        return None

    previous_close = Decimal(
        str(candles[-2][4])
    )

    current_close = Decimal(
        str(candles[-1][4])
    )

    if previous_close <= 0:
        return None

    change = (
        (current_close - previous_close)
        / previous_close
    ) * Decimal("100")

    return float(change)


# =========================================================
# اكتشاف أفضل عملة
# =========================================================

def scan_market():

    symbols_info = get_usdt_symbols()

    state["symbols_count"] = len(symbols_info)

    print(
        f"🔍 فحص {len(symbols_info)} عملة USDT..."
    )

    candidates = []

    # المرحلة الأولى:
    # نفحص 15 دقيقة فقط أولاً
    # عشان نقلل عدد طلبات Binance

    for info in symbols_info:

        symbol = info["symbol"]

        try:

            change = get_15m_change(symbol)

            if change is None:
                continue

            # لازم أكبر من +1%
            if change <= MIN_CHANGE_15M:
                continue

            candidates.append({
                "symbol": symbol,
                "change": change,
                "info": info
            })

            time.sleep(REQUEST_DELAY)

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

    # ترتيب الأعلى صعوداً
    candidates.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    state["candidates_count"] = len(candidates)

    print(
        f"📊 مرشحين فوق +1%: {len(candidates)}"
    )

    # الآن نفحص 1m + 5m + 15m
    # من الأعلى صعوداً إلى الأقل

    for candidate in candidates:

        symbol = candidate["symbol"]

        try:

            print(
                f"🔎 فحص {symbol} "
                f"+{candidate['change']:.2f}%"
            )

            # 15m EMA200
            ok15, price15, ema15 = \
                timeframe_above_ema(
                    symbol,
                    TF_MAIN
                )

            if not ok15:
                continue

            time.sleep(REQUEST_DELAY)

            # 5m EMA200
            ok5, price5, ema5 = \
                timeframe_above_ema(
                    symbol,
                    TF_MID
                )

            if not ok5:
                continue

            time.sleep(REQUEST_DELAY)

            # 1m EMA200
            ok1, price1, ema1 = \
                timeframe_above_ema(
                    symbol,
                    TF_FAST
                )

            if not ok1:
                continue

            state["best_candidate"] = {
                "symbol": symbol,
                "change": candidate["change"],
                "price": float(price15),
                "ema15": float(ema15),
                "ema5": float(ema5),
                "ema1": float(ema1)
            }

            print(
                f"🔥 الأفضل: {symbol} "
                f"+{candidate['change']:.2f}%"
            )

            return candidate

        except Exception as e:

            print(
                f"⚠️ فشل فحص {symbol}: {e}"
            )

    state["best_candidate"] = None

    return None


# =========================================================
# أوامر Binance
# =========================================================

def market_buy(symbol):

    usdt = get_usdt_balance()

    if usdt <= Decimal("5"):
        raise Exception(
            f"رصيد USDT غير كافي: {usdt}"
        )

    quote_qty = usdt * Decimal(
        str(BALANCE_USAGE)
    )

    print(
        f"💰 شراء {symbol} "
        f"بقيمة {quote_qty} USDT"
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": format(
                quote_qty,
                "f"
            ),
            "newOrderRespType": "FULL"
        }
    )

    return order


def get_symbol_info_map():

    data = get_usdt_symbols()

    return {
        x["symbol"]: x
        for x in data
    }


def get_order_status(symbol, order_id):

    return signed_request(
        "GET",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


# =========================================================
# حساب متوسط الدخول
# =========================================================

def order_average_price(order):

    fills = order.get("fills", [])

    if not fills:
        return Decimal("0")

    total_qty = Decimal("0")
    total_cost = Decimal("0")

    for fill in fills:

        qty = Decimal(
            fill.get("qty", "0")
        )

        price = Decimal(
            fill.get("price", "0")
        )

        total_qty += qty
        total_cost += qty * price

    if total_qty <= 0:
        return Decimal("0")

    return total_cost / total_qty


def order_executed_qty(order):

    qty = Decimal(
        order.get("executedQty", "0")
    )

    if qty > 0:
        return qty

    total = Decimal("0")

    for fill in order.get("fills", []):

        total += Decimal(
            fill.get("qty", "0")
        )

    return total


# =========================================================
# اكتشاف الصفقة بعد إعادة التشغيل
# =========================================================

def find_existing_position():

    print("🔄 فحص الصفقات الموجودة...")

    account = get_account()

    balances = account.get(
        "balances",
        []
    )

    info_map = get_symbol_info_map()

    # نبحث عن أي أصل غير USDT
    # عنده رصيد فعلي

    possible = []

    for b in balances:

        asset = b.get("asset")

        if asset == "USDT":
            continue

        free = Decimal(
            b.get("free", "0")
        )

        locked = Decimal(
            b.get("locked", "0")
        )

        total = free + locked

        if total <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in info_map:
            continue

        possible.append(
            (symbol, total)
        )

    print(
        f"🔍 أرصدة محتملة: {len(possible)}"
    )

    # نبحث عن آخر BUY لكل عملة
    for symbol, balance in possible:

        try:

            trades = signed_request(
                "GET",
                "/api/v3/myTrades",
                {
                    "symbol": symbol,
                    "limit": 20
                }
            )

            buys = [
                t for t in trades
                if t.get("isBuyer") is True
            ]

            if not buys:
                continue

            latest = max(
                buys,
                key=lambda x: x.get(
                    "time",
                    0
                )
            )

            price = Decimal(
                latest["price"]
            )

            qty = balance

            print(
                f"♻️ اكتشاف صفقة: {symbol}"
            )

            return {
                "symbol": symbol,
                "entry_price": float(price),
                "quantity": float(qty),
                "order_id": latest.get(
                    "orderId"
                ),
                "recovered": True
            }

        except Exception as e:

            print(
                f"⚠️ خطأ استعادة {symbol}: {e}"
            )

    return None


# =========================================================
# أوامر الحماية الموجودة
# =========================================================

def get_open_orders(symbol):

    return signed_request(
        "GET",
        "/api/v3/openOrders",
        {
            "symbol": symbol
        }
    )


def find_trailing_order(symbol):

    orders = get_open_orders(symbol)

    for o in orders:

        if o.get("side") != "SELL":
            continue

        if o.get("status") not in (
            "NEW",
            "PARTIALLY_FILLED"
        ):
            continue

        if o.get("trailingDelta") is not None:

            return o

    return None


# =========================================================
# إنشاء حماية Binance
# =========================================================

def create_trailing_protection(
    symbol,
    quantity,
    entry_price
):

    current_price = get_price(symbol)

    activation_price = (
        entry_price
        * (
            Decimal("1")
            + Decimal(
                str(TRAIL_ACTIVATION_PROFIT)
            ) / Decimal("100")
        )
    )

    # لازم التفعيل يكون تحت السعر الحالي
    # إذا السعر وصل +1% بالفعل
    if current_price < activation_price:

        print(
            f"⏳ {symbol} لم يصل +1% بعد"
        )

        return None

    info_map = get_symbol_info_map()

    info = info_map.get(symbol)

    if not info:
        raise Exception(
            "معلومات العملة غير موجودة"
        )

    filters = symbol_filters(info)

    qty = round_step(
        quantity,
        filters["step_size"]
    )

    if qty < filters["min_qty"]:
        raise Exception(
            "الكمية أقل من الحد الأدنى"
        )

    activation_price = round_step(
        activation_price,
        filters["tick_size"]
    )

    # حماية إضافية:
    # إذا activation أصبح أعلى من السعر الحالي
    # ننقصه خطوة بسيطة

    if activation_price >= current_price:

        activation_price = (
            current_price
            * Decimal("0.999")
        )

        activation_price = round_step(
            activation_price,
            filters["tick_size"]
        )

    print(
        f"🛡️ إنشاء حماية Binance: "
        f"{symbol} | "
        f"تفعيل={activation_price} | "
        f"Trailing={TRAILING_DELTA_BIPS} BIPS"
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": format(
                qty,
                "f"
            ),
            "stopPrice": format(
                activation_price,
                "f"
            ),
            "trailingDelta":
                TRAILING_DELTA_BIPS,
            "newOrderRespType": "RESULT"
        }
    )

    return order


# =========================================================
# شراء + إعداد الصفقة
# =========================================================

def enter_trade(candidate):

    symbol = candidate["symbol"]

    print(
        f"🚀 دخول: {symbol} "
        f"+{candidate['change']:.2f}%"
    )

    order = market_buy(symbol)

    qty = order_executed_qty(order)

    entry = order_average_price(order)

    if qty <= 0 or entry <= 0:

        # لو FULL ما رجع fills
        time.sleep(1)

        qty = Decimal("0")

        account = get_account()

        for b in account.get(
            "balances",
            []
        ):

            asset = b["asset"]

            if symbol == asset + "USDT":

                qty = Decimal(
                    b["free"]
                )

                break

        entry = get_price(symbol)

    trade = {
        "symbol": symbol,
        "entry_price": float(entry),
        "quantity": float(qty),
        "current_price": float(entry),
        "profit_percent": 0.0,
        "protection": "بانتظار +1%",
        "protection_order_id": None,
        "highest_price": float(entry),
        "started_at": int(time.time()),
        "recovered": False
    }

    state["active_trade"] = trade

    state["last_action"] = (
        f"شراء {symbol}"
    )

    save_state()

    print(
        f"✅ تم الشراء: {symbol}"
    )

    return trade


# =========================================================
# تحديث الصفقة
# =========================================================

def update_trade():

    trade = state.get(
        "active_trade"
    )

    if not trade:
        return False

    symbol = trade["symbol"]

    try:

        price = get_price(symbol)

        entry = Decimal(
            str(trade["entry_price"])
        )

        qty = Decimal(
            str(trade["quantity"])
        )

        profit = (
            (price - entry)
            / entry
        ) * Decimal("100")

        # أعلى سعر
        old_high = Decimal(
            str(
                trade.get(
                    "highest_price",
                    entry
                )
            )
        )

        if price > old_high:

            trade["highest_price"] = float(
                price
            )

        trade["current_price"] = float(
            price
        )

        trade["profit_percent"] = float(
            profit
        )

        # فحص هل الصفقة ما زالت موجودة
        account = get_account()

        base_asset = symbol[:-4]

        balance = Decimal("0")

        for b in account.get(
            "balances",
            []
        ):

            if b["asset"] == base_asset:

                balance = (
                    Decimal(b["free"])
                    +
                    Decimal(b["locked"])
                )

                break

        # إذا اختفت العملة = الصفقة انباعت
        if balance <= 0:

            print(
                f"💰 الصفقة انتهت: {symbol}"
            )

            state["last_action"] = (
                f"انتهت صفقة {symbol}"
            )

            state["active_trade"] = None

            save_state()

            return False

        # =================================================
        # عند +1% نحط أمر Binance
        # =================================================

        existing = find_trailing_order(
            symbol
        )

        if existing:

            trade["protection"] = (
                "🛡️ مفعلة على Binance"
            )

            trade["protection_order_id"] = (
                existing.get("orderId")
            )

        elif profit >= Decimal(
            str(TRAIL_ACTIVATION_PROFIT)
        ):

            try:

                new_order = (
                    create_trailing_protection(
                        symbol,
                        balance,
                        entry
                    )
                )

                if new_order:

                    trade[
                        "protection"
                    ] = (
                        "🛡️ مفعلة على Binance"
                    )

                    trade[
                        "protection_order_id"
                    ] = new_order.get(
                        "orderId"
                    )

                    state["last_action"] = (
                        f"تم تأمين ربح {symbol}"
                    )

                    print(
                        f"🛡️ حماية Binance "
                        f"مفعلة لـ {symbol}"
                    )

            except Exception as e:

                print(
                    "⚠️ فشل إنشاء الحماية:",
                    e
                )

                state["last_error"] = str(e)

        else:

            trade["protection"] = (
                f"بانتظار +{TRAIL_ACTIVATION_PROFIT}%"
            )

        save_state()

        return True

    except Exception as e:

        print(
            f"⚠️ تحديث الصفقة: {e}"
        )

        state["last_error"] = str(e)

        return True


# =========================================================
# استعادة الصفقة
# =========================================================

def recover_trade():

    # أولاً نحاول الصفقة المحفوظة
    saved = state.get(
        "active_trade"
    )

    if saved:

        symbol = saved.get(
            "symbol"
        )

        if symbol:

            try:

                price = get_price(symbol)

                # نتأكد أن الرصيد موجود
                account = get_account()

                base_asset = symbol[:-4]

                balance = Decimal("0")

                for b in account.get(
                    "balances",
                    []
                ):

                    if b["asset"] == base_asset:

                        balance = (
                            Decimal(b["free"])
                            +
                            Decimal(b["locked"])
                        )

                        break

                if balance > 0:

                    saved["quantity"] = float(
                        balance
                    )

                    saved["current_price"] = float(
                        price
                    )

                    saved["recovered"] = True

                    state["active_trade"] = saved

                    print(
                        f"♻️ استكمال الصفقة: {symbol}"
                    )

                    return True

            except Exception as e:

                print(
                    "⚠️ تعذر استعادة المحفوظة:",
                    e
                )

    # ثانياً نفحص Binance مباشرة
    found = find_existing_position()

    if found:

        symbol = found["symbol"]

        price = get_price(symbol)

        found["current_price"] = float(
            price
        )

        found["profit_percent"] = float(
            (
                (
                    price
                    - Decimal(
                        str(
                            found["entry_price"]
                        )
                    )
                )
                /
                Decimal(
                    str(
                        found["entry_price"]
                    )
                )
            ) * Decimal("100")
        )

        found["highest_price"] = float(
            max(
                price,
                Decimal(
                    str(
                        found["entry_price"]
                    )
                )
            )
        )

        found["protection"] = (
            "فحص الحماية..."
        )

        state["active_trade"] = found

        save_state()

        print(
            f"♻️ تم استرجاع {symbol}"
        )

        return True

    return False


# =========================================================
# محرك التداول
# =========================================================

def trading_loop():

    print("🚀 بدأ محرك التداول")

    # انتظار اتصال
    time.sleep(3)

    # استعادة الصفقة
    try:

        if recover_trade():

            print(
                "♻️ يوجد مركز مفتوح، "
                "سيتم استكماله"
            )

        else:

            print(
                "✅ لا توجد صفقة مفتوحة"
            )

    except Exception as e:

        print(
            "⚠️ خطأ الاستعادة:",
            e
        )

    while True:

        try:

            # =============================================
            # إذا عندنا صفقة
            # =============================================

            if state.get(
                "active_trade"
            ):

                state["status"] = (
                    "🟢 صفقة مفتوحة"
                )

                update_trade()

                time.sleep(5)

                continue

            # =============================================
            # لا توجد صفقة
            # =============================================

            state["status"] = (
                "🔎 يبحث عن أفضل عملة"
            )

            state["last_scan"] = int(
                time.time()
            )

            candidate = scan_market()

            if candidate:

                print(
                    f"🔥 أفضل فرصة: "
                    f"{candidate['symbol']} "
                    f"+{candidate['change']:.2f}%"
                )

                try:

                    enter_trade(
                        candidate
                    )

                except Exception as e:

                    print(
                        "❌ فشل الدخول:",
                        e
                    )

                    state["last_error"] = str(e)

                    time.sleep(10)

            else:

                state["last_action"] = (
                    "ما فيه عملة تحقق الشروط"
                )

                print(
                    "⏳ لا توجد فرصة"
                )

            save_state()

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            print(
                "🚨 خطأ بالمحرك:",
                e
            )

            state["last_error"] = str(e)
            state["status"] = "⚠️ خطأ مؤقت"

            save_state()

            time.sleep(15)


# =========================================================
# Dashboard
# =========================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    with lock:

        return jsonify(
            state
        )


@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": "مضارب أبو سعود"
    })


# =========================================================
# التشغيل
# =========================================================

def start_bot():

    load_state()

    if not API_KEY or not API_SECRET:

        print(
            "❌ ناقص BINANCE_API_KEY "
            "أو BINANCE_API_SECRET"
        )

    else:

        try:

            # اختبار الاتصال
            get_account()

            print(
                "🔗 Binance متصل ✅"
            )

        except Exception as e:

            print(
                "⚠️ فشل اتصال Binance:",
                e
            )

    t = threading.Thread(
        target=trading_loop,
        daemon=True
    )

    t.start()


if __name__ == "__main__":

    start_bot()

    print(
        f"🌐 PORT = {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
