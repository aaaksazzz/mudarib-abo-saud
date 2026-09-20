import os
import time
import hmac
import hashlib
import urllib.parse
import threading
from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string
import requests

# =========================================================
# الإعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"

PORT = int(os.getenv("PORT", "10000"))

FEE_RATE = Decimal("0.001")

# الاستراتيجية
EMA_PERIOD = 200
MIN_CHANGE_15M = Decimal("1.0")       # لازم > 1%
PROTECTION_START = Decimal("1.0")     # يبدأ التأمين عند صافي +1%
TRAIL_PERCENT = Decimal("0.50")       # حماية 0.50% تحت أعلى سعر

# استخدام كامل الرصيد تقريباً
BALANCE_USAGE = Decimal("0.999")

# أوقات الفحص
POSITION_CHECK_SECONDS = 10
PRICE_CHECK_SECONDS = 5
SCAN_SECONDS = 30

SESSION = requests.Session()

# =========================================================
# حالة البوت
# =========================================================

state = {
    "running": True,
    "status": "جاري التشغيل",
    "active_symbol": None,
    "entry_price": None,
    "current_price": None,
    "highest_price": None,
    "net_profit": None,
    "protection": None,
    "protection_price": None,
    "position_qty": None,
    "balance_usdt": None,

    "scan_count": 0,
    "usdt_pairs": 0,
    "candidates": 0,
    "best_candidate": None,
    "best_change": None,

    "ema_1m": None,
    "ema_5m": None,
    "ema_15m": None,

    "last_action": "لم يتم تنفيذ أي عملية",
    "last_error": None,
    "last_scan": None,

    "open_position_source": None,
}

state_lock = threading.Lock()

# =========================================================
# أدوات
# =========================================================

def log(msg):
    print(msg, flush=True)


def D(value):
    try:
        return Decimal(str(value))
    except:
        return Decimal("0")


def fmt(value, digits=8):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except:
        return "-"


def set_state(**kwargs):
    with state_lock:
        state.update(kwargs)


# =========================================================
# Binance API
# =========================================================

def public_request(method, path, params=None):
    url = BASE_URL + path

    for attempt in range(5):
        try:
            r = SESSION.request(
                method,
                url,
                params=params,
                timeout=15
            )

            if r.status_code == 429:
                wait = min(30, 2 ** attempt)
                log(f"⚠️ Binance 429 - انتظار {wait} ثانية")
                time.sleep(wait)
                continue

            if r.status_code >= 400:
                raise Exception(
                    f"Binance {r.status_code}: {r.text[:500]}"
                )

            return r.json()

        except Exception:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)


def signed_request(method, path, params=None):
    if params is None:
        params = {}

    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(params, doseq=True)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url = BASE_URL + path + "?" + query + "&signature=" + signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    for attempt in range(5):
        try:
            r = SESSION.request(
                method,
                url,
                headers=headers,
                timeout=15
            )

            if r.status_code == 429:
                wait = min(30, 2 ** attempt)
                log(f"⚠️ Binance 429 - انتظار {wait} ثانية")
                time.sleep(wait)
                continue

            if r.status_code >= 400:
                raise Exception(
                    f"Binance {r.status_code}: {r.text[:700]}"
                )

            return r.json()

        except Exception:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)


# =========================================================
# معلومات العملات
# =========================================================

exchange_cache = {
    "time": 0,
    "symbols": []
}

symbol_rules = {}


def load_symbols():
    now = time.time()

    if exchange_cache["symbols"] and now - exchange_cache["time"] < 3600:
        return exchange_cache["symbols"]

    data = public_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    symbols = []

    for s in data["symbols"]:

        if s["status"] != "TRADING":
            continue

        if s["quoteAsset"] != "USDT":
            continue

        symbol = s["symbol"]

        symbols.append(symbol)

        filters = {}

        for f in s["filters"]:
            filters[f["filterType"]] = f

        symbol_rules[symbol] = filters

    exchange_cache["symbols"] = symbols
    exchange_cache["time"] = now

    set_state(usdt_pairs=len(symbols))

    log(f"📚 تم تحميل {len(symbols)} عملة USDT")

    return symbols


# =========================================================
# السعر
# =========================================================

def get_price(symbol):
    data = public_request(
        "GET",
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return D(data["price"])


def get_all_prices():
    data = public_request(
        "GET",
        "/api/v3/ticker/price"
    )

    result = {}

    for item in data:
        result[item["symbol"]] = D(item["price"])

    return result


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


# =========================================================
# الشموع
# =========================================================

def get_klines(symbol, interval, limit=210):

    data = public_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    return data


def calculate_ema(closes, period=200):

    if len(closes) < period:
        return None

    ema = sum(closes[:period]) / Decimal(period)

    multiplier = Decimal("2") / Decimal(period + 1)

    for price in closes[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


def get_ema(symbol, interval):

    klines = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    closes = [
        D(k[4])
        for k in klines
    ]

    return calculate_ema(
        closes,
        EMA_PERIOD
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

    candle = klines[-1]

    open_price = D(candle[1])
    current_price = D(candle[4])

    if open_price <= 0:
        return None

    change = (
        (current_price - open_price)
        / open_price
    ) * 100

    return change


# =========================================================
# البحث عن صفقة مفتوحة
# =========================================================

def find_open_position():

    account = get_account()

    balances = []

    for b in account["balances"]:

        asset = b["asset"]

        free = D(b["free"])
        locked = D(b["locked"])

        total = free + locked

        if total <= 0:
            continue

        if asset == "USDT":
            continue

        symbol = asset + "USDT"

        balances.append(
            (symbol, total)
        )

    if not balances:
        return None

    prices = get_all_prices()

    positions = []

    for symbol, qty in balances:

        price = prices.get(symbol)

        if not price:
            continue

        value = qty * price

        if value >= Decimal("5"):
            positions.append(
                (symbol, qty, price, value)
            )

    if not positions:
        return None

    # إذا أكثر من عملة، نعتبر الأكبر قيمة هي الصفقة المفتوحة
    positions.sort(
        key=lambda x: x[3],
        reverse=True
    )

    symbol, qty, price, value = positions[0]

    # نجيب تداولات العملة فقط
    trades = signed_request(
        "GET",
        "/api/v3/myTrades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    current_qty = Decimal("0")
    cost = Decimal("0")

    for t in sorted(
        trades,
        key=lambda x: x["time"]
    ):

        trade_qty = D(t["qty"])
        trade_price = D(t["price"])
        commission = D(t["commission"])
        commission_asset = t["commissionAsset"]

        if t["isBuyer"]:

            added_qty = trade_qty

            if commission_asset == symbol.replace("USDT", ""):
                added_qty -= commission

            current_qty += added_qty

            cost += trade_qty * trade_price

            if commission_asset == "USDT":
                cost += commission

        else:

            sold_qty = trade_qty

            if commission_asset == symbol.replace("USDT", ""):
                sold_qty += commission

            if current_qty > 0:

                avg = cost / current_qty

                current_qty -= sold_qty

                if current_qty < 0:
                    current_qty = Decimal("0")

                cost = avg * current_qty

    if current_qty <= 0:
        current_qty = qty

    if current_qty > 0 and cost > 0:
        entry = cost / current_qty
    else:
        entry = price

    return {
        "symbol": symbol,
        "qty": qty,
        "entry": entry,
        "price": price,
        "value": value,
        "source": "Binance"
    }


# =========================================================
# فحص الاستراتيجية
# =========================================================

def scan_market():

    symbols = load_symbols()

    set_state(
        status="🔎 البحث عن أقوى عملة",
        last_error=None
    )

    candidates = []

    # -----------------------------------------------------
    # المرحلة الأولى:
    # 15m > 1% فقط
    # -----------------------------------------------------

    for i, symbol in enumerate(symbols):

        try:

            change = get_15m_change(symbol)

            if change is None:
                continue

            # مهم:
            # 1.00% لا يدخل
            # 1.01% يدخل
            if change <= MIN_CHANGE_15M:
                continue

            candidates.append(
                (symbol, change)
            )

            if i % 25 == 0:
                time.sleep(0.1)

        except Exception as e:
            log(f"⚠️ {symbol}: {e}")

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    set_state(
        candidates=len(candidates)
    )

    log(
        f"📈 عملات فوق +1%: {len(candidates)}"
    )

    # -----------------------------------------------------
    # نختبر الأقوى أولاً
    # -----------------------------------------------------

    for symbol, change in candidates:

        try:

            # 15m EMA200
            ema15 = get_ema(
                symbol,
                "15m"
            )

            if ema15 is None:
                continue

            price15 = get_price(symbol)

            if price15 <= ema15:
                continue

            # 5m EMA200
            ema5 = get_ema(
                symbol,
                "5m"
            )

            if ema5 is None:
                continue

            price5 = get_price(symbol)

            if price5 <= ema5:
                continue

            # 1m EMA200
            ema1 = get_ema(
                symbol,
                "1m"
            )

            if ema1 is None:
                continue

            price1 = get_price(symbol)

            if price1 <= ema1:
                continue

            # ------------------------------------------------
            # وجدنا الأقوى
            # ------------------------------------------------

            set_state(
                best_candidate=symbol,
                best_change=change,
                ema_1m=True,
                ema_5m=True,
                ema_15m=True
            )

            log(
                f"🔥 أفضل عملة: {symbol} | "
                f"15m +{change:.2f}% | "
                f"EMA 1m/5m/15m ✅"
            )

            return {
                "symbol": symbol,
                "change": change,
                "price": price1,
                "ema1": ema1,
                "ema5": ema5,
                "ema15": ema15
            }

        except Exception as e:

            log(
                f"⚠️ خطأ فحص {symbol}: {e}"
            )

    return None


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    balance = get_usdt_balance()

    if balance <= Decimal("5"):
        raise Exception(
            "رصيد USDT غير كافي"
        )

    amount = (
        balance * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    log(
        f"💰 الرصيد: {balance} USDT"
    )

    log(
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

    executed_qty = D(
        order["executedQty"]
    )

    fills = order.get("fills", [])

    if fills:

        total_cost = Decimal("0")

        total_qty = Decimal("0")

        for fill in fills:

            qty = D(fill["qty"])
            price = D(fill["price"])

            total_qty += qty
            total_cost += qty * price

        entry = (
            total_cost / total_qty
        )

    else:
        entry = get_price(symbol)

    set_state(
        active_symbol=symbol,
        entry_price=entry,
        current_price=entry,
        highest_price=entry,
        net_profit=Decimal("0"),
        protection=False,
        protection_price=None,
        position_qty=executed_qty,
        open_position_source="Bot",
        status="🟢 صفقة مفتوحة",
        last_action=f"شراء {symbol}"
    )

    log(
        f"🟢 تم الشراء {symbol} "
        f"| Entry {entry}"
    )

    return {
        "symbol": symbol,
        "qty": executed_qty,
        "entry": entry
    }


# =========================================================
# صافي الربح
# =========================================================

def calculate_net_profit(entry, price):

    if entry <= 0:
        return Decimal("0")

    gross = (
        (price - entry)
        / entry
    ) * 100

    # رسوم شراء + بيع
    fees = FEE_RATE * 2 * 100

    return gross - fees


# =========================================================
# إلغاء حماية قديمة
# =========================================================

def cancel_protection(symbol):

    try:

        orders = signed_request(
            "GET",
            "/api/v3/openOrders",
            {
                "symbol": symbol
            }
        )

        for order in orders:

            if order["side"] == "SELL":

                try:

                    signed_request(
                        "DELETE",
                        "/api/v3/order",
                        {
                            "symbol": symbol,
                            "orderId": order["orderId"]
                        }
                    )

                    log(
                        f"🗑️ إلغاء حماية قديمة "
                        f"{symbol}"
                    )

                except Exception as e:
                    log(
                        f"⚠️ فشل إلغاء الأمر: {e}"
                    )

    except Exception as e:
        log(
            f"⚠️ فحص أوامر الحماية: {e}"
        )


# =========================================================
# إنشاء حماية ربح
# =========================================================

def create_profit_protection(
    symbol,
    qty,
    stop_price
):

    rules = symbol_rules.get(
        symbol,
        {}
    )

    lot = rules.get(
        "LOT_SIZE"
    )

    if lot:

        step = D(
            lot["stepSize"]
        )

        qty = (
            qty / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    price_filter = rules.get(
        "PRICE_FILTER"
    )

    if price_filter:

        tick = D(
            price_filter["tickSize"]
        )

        stop_price = (
            stop_price / tick
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * tick

    stop_price = stop_price.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    qty = qty.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": str(qty),
            "stopPrice": str(stop_price)
        }
    )

    log(
        f"🛡️ حماية ربح عند {stop_price}"
    )

    return order


# =========================================================
# تحديث الحماية
# =========================================================

def update_protection():

    symbol = state["active_symbol"]

    entry = state["entry_price"]

    qty = state["position_qty"]

    if not symbol or not entry or not qty:
        return

    price = get_price(symbol)

    net = calculate_net_profit(
        entry,
        price
    )

    highest = state["highest_price"]

    if highest is None or price > highest:
        highest = price

        set_state(
            highest_price=highest
        )

    set_state(
        current_price=price,
        net_profit=net
    )

    # -----------------------------------------------------
    # ما وصل +1%؟
    # لا حماية
    # -----------------------------------------------------

    if net < PROTECTION_START:

        set_state(
            protection=False
        )

        return

    # -----------------------------------------------------
    # حساب الوقف المتحرك
    # -----------------------------------------------------

    trailing_stop = (
        highest
        * (
            Decimal("1")
            - TRAIL_PERCENT / 100
        )
    )

    # لازم يظل فوق نقطة الدخول بعد الرسوم
    minimum_profit_stop = (
        entry
        * Decimal("1.001")
    )

    new_stop = max(
        trailing_stop,
        minimum_profit_stop
    )

    old_stop = state["protection_price"]

    # لا ننزل الحماية
    if old_stop is not None:

        if new_stop <= old_stop:
            return

    # -----------------------------------------------------
    # إلغاء القديمة ثم إنشاء الجديدة
    # -----------------------------------------------------

    cancel_protection(symbol)

    time.sleep(0.2)

    try:

        create_profit_protection(
            symbol,
            qty,
            new_stop
        )

        set_state(
            protection=True,
            protection_price=new_stop,
            last_action=(
                f"🛡️ رفع الحماية إلى "
                f"{new_stop}"
            )
        )

    except Exception as e:

        log(
            f"🚨 فشل إنشاء الحماية: {e}"
        )

        set_state(
            last_error=str(e)
        )


# =========================================================
# تنظيف حالة الصفقة
# =========================================================

def clear_trade():

    set_state(
        active_symbol=None,
        entry_price=None,
        current_price=None,
        highest_price=None,
        net_profit=None,
        protection=False,
        protection_price=None,
        position_qty=None,
        open_position_source=None,
        status="لا توجد صفقة",
        last_action="تم إغلاق الصفقة - العودة للفحص"
    )


# =========================================================
# إدارة الصفقة
# =========================================================

def manage_position(position):

    symbol = position["symbol"]

    entry = position["entry"]

    qty = position["qty"]

    source = position["source"]

    set_state(
        active_symbol=symbol,
        entry_price=entry,
        current_price=position["price"],
        highest_price=max(
            position["price"],
            state["highest_price"] or position["price"]
        ),
        position_qty=qty,
        open_position_source=source,
        status="♻️ إدارة الصفقة المفتوحة"
    )

    log(
        f"♻️ صفقة مفتوحة: {symbol} "
        f"| Entry {entry}"
    )

    while True:

        try:

            # ---------------------------------------------
            # السعر
            # ---------------------------------------------

            price = get_price(symbol)

            net = calculate_net_profit(
                entry,
                price
            )

            highest = state["highest_price"]

            if highest is None or price > highest:
                highest = price

            set_state(
                current_price=price,
                highest_price=highest,
                net_profit=net
            )

            log(
                f"📊 {symbol} | "
                f"السعر {price} | "
                f"صافي {net:.2f}% | "
                f"الأعلى {highest}"
            )

            # ---------------------------------------------
            # حماية الربح
            # ---------------------------------------------

            update_protection()

            # ---------------------------------------------
            # هل الصفقة ما زالت موجودة؟
            # ---------------------------------------------

            time.sleep(POSITION_CHECK_SECONDS)

            latest = find_open_position()

            if not latest:

                log(
                    f"✅ لا توجد صفقة {symbol} "
                    f"- الصفقة أغلقت"
                )

                clear_trade()

                return

            if latest["symbol"] != symbol:

                log(
                    f"🔄 تغيرت الصفقة إلى "
                    f"{latest['symbol']}"
                )

                clear_trade()

                return

        except Exception as e:

            log(
                f"🚨 خطأ إدارة الصفقة: {e}"
            )

            set_state(
                last_error=str(e)
            )

            time.sleep(10)


# =========================================================
# محرك البوت
# =========================================================

def trading_engine():

    log("🚀 بدأ محرك التداول")

    while True:

        try:

            # =================================================
            # 1 — دائماً نفحص الصفقة أولاً
            # =================================================

            log(
                "🔍 فحص الصفقات المفتوحة أولًا..."
            )

            position = find_open_position()

            if position:

                log(
                    f"♻️ صفقة مفتوحة مكتشفة: "
                    f"{position['symbol']}"
                )

                manage_position(
                    position
                )

                continue

            # =================================================
            # لا توجد صفقة
            # =================================================

            log(
                "🔎 لا توجد صفقة مفتوحة"
            )

            set_state(
                status="🔎 لا توجد صفقة - جاري البحث",
                active_symbol=None,
                entry_price=None,
                current_price=None,
                net_profit=None,
                protection=False
            )

            # =================================================
            # 2 — فحص السوق
            # =================================================

            set_state(
                scan_count=state["scan_count"] + 1,
                last_scan=time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            result = scan_market()

            if not result:

                log(
                    "❌ لا توجد عملة تحقق الشروط"
                )

                set_state(
                    status="⏳ لا توجد فرصة",
                    last_action="لم توجد فرصة مطابقة"
                )

                time.sleep(
                    SCAN_SECONDS
                )

                continue

            # =================================================
            # 3 — دخول الأقوى
            # =================================================

            symbol = result["symbol"]

            log(
                f"🚀 دخول: {symbol} "
                f"| 15m +{result['change']:.2f}%"
            )

            market_buy(symbol)

            # =================================================
            # 4 — إدارة الصفقة
            # =================================================

            position = find_open_position()

            if position:

                manage_position(
                    position
                )

            else:

                log(
                    "⚠️ لم يتم العثور على الصفقة بعد الشراء"
                )

            time.sleep(2)

        except Exception as e:

            log(
                f"🚨 خطأ المحرك: {e}"
            )

            set_state(
                last_error=str(e),
                status="⚠️ خطأ - إعادة المحاولة"
            )

            time.sleep(15)


# =========================================================
# لوحة المتابعة
# =========================================================

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود</title>

<style>

*{
box-sizing:border-box;
}

body{
margin:0;
font-family:Arial,Tahoma,sans-serif;
background:#080b12;
color:#fff;
}

.container{
max-width:1100px;
margin:auto;
padding:20px;
}

.header{
background:linear-gradient(
135deg,
#111827,
#0b1220
);
border:1px solid #202938;
border-radius:22px;
padding:25px;
margin-bottom:18px;
}

.logo{
font-size:28px;
font-weight:bold;
}

.subtitle{
color:#8b95a7;
margin-top:8px;
}

.status{
display:inline-block;
margin-top:15px;
padding:8px 14px;
border-radius:20px;
background:#162033;
color:#62e6a5;
font-size:14px;
}

.grid{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(210px,1fr));
gap:14px;
}

.card{
background:#101621;
border:1px solid #202938;
border-radius:18px;
padding:20px;
min-height:120px;
}

.label{
font-size:13px;
color:#8994a6;
margin-bottom:12px;
}

.value{
font-size:24px;
font-weight:bold;
word-break:break-word;
}

.green{
color:#45e19a;
}

.red{
color:#ff6677;
}

.blue{
color:#63a8ff;
}

.yellow{
color:#ffd166;
}

.section{
margin-top:18px;
}

.section-title{
font-size:18px;
font-weight:bold;
margin-bottom:12px;
}

.strategy{
background:#101621;
border:1px solid #202938;
border-radius:18px;
padding:20px;
line-height:2;
color:#b7c0cf;
}

.rule{
display:flex;
justify-content:space-between;
border-bottom:1px solid #1e2735;
padding:7px 0;
}

.rule:last-child{
border-bottom:0;
}

.footer{
text-align:center;
color:#667085;
font-size:12px;
margin-top:25px;
}

</style>
</head>

<body>

<div class="container">

<div class="header">

<div class="logo">
🤖 مضارب أبو سعود
</div>

<div class="subtitle">
Binance Spot — محرك تداول آلي
</div>

<div class="status" id="status">
جاري الاتصال...
</div>

</div>


<div class="grid">

<div class="card">
<div class="label">العملة الحالية</div>
<div class="value blue" id="symbol">-</div>
</div>

<div class="card">
<div class="label">سعر الدخول</div>
<div class="value" id="entry">-</div>
</div>

<div class="card">
<div class="label">السعر الحالي</div>
<div class="value" id="price">-</div>
</div>

<div class="card">
<div class="label">صافي الربح</div>
<div class="value green" id="profit">-</div>
</div>

<div class="card">
<div class="label">أعلى سعر</div>
<div class="value yellow" id="highest">-</div>
</div>

<div class="card">
<div class="label">حماية الربح</div>
<div class="value" id="protection">-</div>
</div>

<div class="card">
<div class="label">الرصيد USDT</div>
<div class="value" id="balance">-</div>
</div>

<div class="card">
<div class="label">عدد العملات</div>
<div class="value" id="pairs">-</div>
</div>

<div class="card">
<div class="label">العملات فوق +1%</div>
<div class="value" id="candidates">-</div>
</div>

<div class="card">
<div class="label">أقوى مرشح</div>
<div class="value blue" id="best">-</div>
</div>

<div class="card">
<div class="label">نسبة المرشح</div>
<div class="value green" id="bestChange">-</div>
</div>

<div class="card">
<div class="label">رقم الفحص</div>
<div class="value" id="scan">-</div>
</div>

</div>


<div class="section">

<div class="section-title">
🎯 شروط الدخول
</div>

<div class="strategy">

<div class="rule">
<span>تغير 15 دقيقة</span>
<b>أكبر من +1%</b>
</div>

<div class="rule">
<span>EMA 200 — 15m</span>
<b>السعر فوقه</b>
</div>

<div class="rule">
<span>EMA 200 — 5m</span>
<b>السعر فوقه</b>
</div>

<div class="rule">
<span>EMA 200 — 1m</span>
<b>السعر فوقه</b>
</div>

<div class="rule">
<span>اختيار العملة</span>
<b>الأقوى</b>
</div>

<div class="rule">
<span>الدخول</span>
<b>99.9% من USDT</b>
</div>

<div class="rule">
<span>بدء الحماية</span>
<b>صافي +1%</b>
</div>

<div class="rule">
<span>التريلنج</span>
<b>0.50%</b>
</div>

<div class="rule">
<span>فحص الصفقة</span>
<b>قبل السوق دائماً</b>
</div>

</div>

</div>


<div class="section">

<div class="section-title">
⚙️ آخر عملية
</div>

<div class="strategy" id="action">
-
</div>

</div>


<div class="section">

<div class="section-title">
⚠️ آخر خطأ
</div>

<div class="strategy" id="error">
لا يوجد
</div>

</div>


<div class="footer">
مضارب أبو سعود 🤖
</div>

</div>


<script>

function val(x){
return x === null ||
x === undefined ||
x === ""
? "-"
: x;
}

function number(x){
if(x === null || x === undefined)
return "-";

let n = Number(x);

if(Number.isNaN(n))
return x;

return n.toFixed(6);
}

async function update(){

try{

let r = await fetch(
"/api/status",
{
cache:"no-store"
}
);

let d = await r.json();

document.getElementById("status")
.innerText = val(d.status);

document.getElementById("symbol")
.innerText =
val(d.active_symbol);

document.getElementById("entry")
.innerText =
number(d.entry_price);

document.getElementById("price")
.innerText =
number(d.current_price);

document.getElementById("profit")
innerText =
d.net_profit === null
? "-"
: Number(d.net_profit).toFixed(2)+"%";

document.getElementById("highest")
.innerText =
number(d.highest_price);

document.getElementById("protection")
.innerText =
d.protection
? number(d.protection_price)
: "غير مفعلة";

document.getElementById("balance")
.innerText =
number(d.balance_usdt);

document.getElementById("pairs")
.innerText =
val(d.usdt_pairs);

document.getElementById("candidates")
.innerText =
val(d.candidates);

document.getElementById("best")
.innerText =
val(d.best_candidate);

document.getElementById("bestChange")
.innerText =
d.best_change === null
? "-"
: Number(d.best_change).toFixed(2)+"%";

document.getElementById("scan")
.innerText =
val(d.scan_count);

document.getElementById("action")
.innerText =
val(d.last_action);

document.getElementById("error")
.innerText =
d.last_error
? d.last_error
: "لا يوجد";

}

catch(e){

document.getElementById("status")
.innerText =
"⚠️ تعذر الاتصال";

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
# API لوحة التحكم
# =========================================================

@app.route("/")
def home():
    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    with state_lock:
        data = dict(state)

    try:
        data["balance_usdt"] = get_usdt_balance()
    except:
        pass

    # Decimal -> string
    for k, v in list(data.items()):

        if isinstance(v, Decimal):
            data[k] = str(v)

    return jsonify(data)


# =========================================================
# تشغيل
# =========================================================

def start_bot():

    if not API_KEY or not API_SECRET:

        log(
            "🚨 لم يتم وضع BINANCE_API_KEY "
            "و BINANCE_API_SECRET"
        )

    load_symbols()

    thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    thread.start()


if __name__ == "__main__":

    start_bot()

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
