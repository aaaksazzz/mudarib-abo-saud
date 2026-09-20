import os
import time
import hmac
import hashlib
import urllib.parse
import threading
import requests

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# إعدادات Binance
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

BASE = "https://api.binance.com"

TITLE = "مضارب أبو سعود 🤖"

TIMEFRAME = "15m"
EMA_PERIOD = 200

MIN_CHANGE_15M = 1.0
PROTECTION_START = 1.0
PROTECTION_STEP = 1.0
TRAILING_PERCENT = 0.50

POSITION_CHECK_SECONDS = 30
SCAN_INTERVAL = 60

MIN_POSITION_USDT = 2.0
BUY_PERCENT = 99.9

REQUEST_TIMEOUT = 10


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)


# ============================================================
# Session
# ============================================================

session = requests.Session()

if API_KEY:
    session.headers.update({
        "X-MBX-APIKEY": API_KEY
    })


# ============================================================
# حالة البوت
# ============================================================

state = {
    "bot": {
        "running": True,
        "started_at": time.time(),
        "last_check": None,
        "last_scan": None,
        "last_error": None,
        "message": "جاري التشغيل...",
        "mode": "بدء التشغيل",
        "last_step": "",
        "last_api": "",
        "last_api_ok": None
    },

    "account": {
        "usdt": 0.0
    },

    "position": None,

    "stats": {
        "scanned": 0,
        "signals": 0,
        "buys": 0,
        "sells": 0
    },

    "logs": []
}


# ============================================================
# Logs
# ============================================================

def log(message):
    now = time.strftime("%H:%M:%S")

    line = f"[{now}] {message}"

    print(line, flush=True)

    state["logs"].insert(0, line)

    if len(state["logs"]) > 100:
        state["logs"] = state["logs"][:100]


# ============================================================
# Public API
# ============================================================

def public_get(endpoint, params=None):

    state["bot"]["last_api"] = endpoint

    try:

        r = session.get(
            BASE + endpoint,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        r.raise_for_status()

        state["bot"]["last_api_ok"] = True

        return r.json()

    except Exception as e:

        state["bot"]["last_api_ok"] = False

        state["bot"]["last_error"] = str(e)

        log(f"❌ API {endpoint}: {e}")

        raise


# ============================================================
# Signed Binance API
# ============================================================

def signed_request(method, endpoint, params=None):

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE + endpoint + "?" + query

    state["bot"]["last_api"] = endpoint

    try:

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

        else:

            raise Exception("Method غير مدعوم")

        if not r.ok:

            raise Exception(
                f"HTTP {r.status_code}: {r.text[:500]}"
            )

        state["bot"]["last_api_ok"] = True

        return r.json()

    except Exception as e:

        state["bot"]["last_api_ok"] = False

        state["bot"]["last_error"] = str(e)

        log(f"❌ Signed API {endpoint}: {e}")

        raise


# ============================================================
# Binance Account
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


# ============================================================
# USDT Balance
# ============================================================

def get_usdt_balance(account=None):

    if account is None:
        account = get_account()

    for item in account.get("balances", []):

        if item["asset"] == "USDT":

            free = float(item["free"])

            state["account"]["usdt"] = free

            return free

    state["account"]["usdt"] = 0.0

    return 0.0


# ============================================================
# Price
# ============================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(data["price"])


# ============================================================
# All prices
# ============================================================

def get_all_prices():

    data = public_get(
        "/api/v3/ticker/price"
    )

    return {
        x["symbol"]: float(x["price"])
        for x in data
    }


# ============================================================
# Exchange Info
# ============================================================

exchange_cache = {
    "time": 0,
    "symbols": []
}


def load_exchange_info():

    now = time.time()

    if (
        exchange_cache["symbols"]
        and now - exchange_cache["time"] < 1800
    ):

        return exchange_cache["symbols"]

    log("🌐 تحميل معلومات Binance...")

    data = public_get(
        "/api/v3/exchangeInfo"
    )

    symbols = []

    for item in data.get("symbols", []):

        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
        ):

            symbols.append(item["symbol"])

    exchange_cache["symbols"] = symbols
    exchange_cache["time"] = now

    log(
        f"تم تحميل معلومات Binance: {len(symbols)} زوج USDT"
    )

    return symbols


# ============================================================
# Candles
# ============================================================

def get_klines(symbol, limit=220):

    data = public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": limit
        }
    )

    candles = []

    for k in data:

        candles.append({
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })

    return candles


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:

        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


# ============================================================
# آخر صفقة دخول
# ============================================================

def calculate_entry(symbol):

    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

        buy_qty = 0.0
        buy_cost = 0.0

        sell_qty = 0.0

        for trade in trades:

            qty = float(trade["qty"])
            price = float(trade["price"])

            if trade.get("isBuyer"):

                buy_qty += qty
                buy_cost += qty * price

            else:

                sell_qty += qty

        current_account = get_account()

        current_quantity = 0.0

        for balance in current_account.get("balances", []):

            asset = balance["asset"]

            if symbol.endswith(asset):

                pass

        base_asset = symbol.replace("USDT", "")

        for balance in current_account.get("balances", []):

            if balance["asset"] == base_asset:

                current_quantity = float(
                    balance["free"]
                ) + float(
                    balance["locked"]
                )

                break

        if current_quantity <= 0:

            return None

        # نحاول حساب متوسط تكلفة الكمية الموجودة
        if buy_qty > 0:

            average_entry = buy_cost / buy_qty

            return average_entry

        return None

    except Exception as e:

        log(
            f"⚠️ تعذر حساب سعر الدخول {symbol}: {e}"
        )

        return None


# ============================================================
# البحث عن الصفقة المفتوحة
# ============================================================

def find_open_position():

    state["bot"]["last_check"] = time.time()
    state["bot"]["mode"] = "فحص الصفقة المفتوحة"
    state["bot"]["last_step"] = "الاتصال بالحساب"

    log("🔎 جاري التحقق من الصفقة المفتوحة...")

    account = get_account()

    # الرصيد فقط — ليس ربح
    get_usdt_balance(account)

    state["bot"]["last_step"] = "تحميل الأسعار"

    prices = get_all_prices()

    state["bot"]["last_step"] = "فحص العملات"

    valid_symbols = set(
        load_exchange_info()
    )

    candidates = []

    for balance in account.get("balances", []):

        asset = balance["asset"]

        if asset == "USDT":
            continue

        free = float(balance["free"])
        locked = float(balance["locked"])

        quantity = free + locked

        if quantity <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in valid_symbols:
            continue

        current = prices.get(symbol)

        if current is None:
            continue

        value = quantity * current

        if value < MIN_POSITION_USDT:
            continue

        candidates.append({
            "symbol": symbol,
            "quantity": quantity,
            "value": value,
            "price": current
        })

    if not candidates:

        log("✅ لا توجد صفقة مفتوحة")

        state["bot"]["mode"] = "البحث عن فرصة"

        return None

    # إذا أكثر من عملة، نأخذ الأكبر
    candidates.sort(
        key=lambda x: x["value"],
        reverse=True
    )

    candidate = candidates[0]

    symbol = candidate["symbol"]
    quantity = candidate["quantity"]
    current = candidate["price"]

    log(
        f"📌 تم العثور على صفقة: {symbol}"
    )

    state["bot"]["last_step"] = (
        f"حساب دخول {symbol}"
    )

    entry = calculate_entry(symbol)

    if entry is None:

        # كحل احتياطي
        entry = current

        log(
            "⚠️ تعذر معرفة الدخول التاريخي، "
            "استخدمنا السعر الحالي مؤقتاً"
        )

    profit_percent = (
        ((current - entry) / entry) * 100
        if entry > 0
        else 0.0
    )

    profit_usdt = (
        (current - entry) * quantity
    )

    position = {
        "symbol": symbol,
        "quantity": quantity,

        "entry": entry,
        "price": current,

        # ربح الصفقة الحالية فقط
        "profit": profit_percent,
        "profit_usdt": profit_usdt,

        "protection": None,
        "protection_profit": None,

        "opened_at": time.time(),

        "recovered": True
    }

    log(
        f"📊 الصفقة الحالية: "
        f"{symbol} | "
        f"{profit_percent:+.2f}% | "
        f"{profit_usdt:+.4f} USDT"
    )

    return position


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position():

    position = state.get("position")

    if not position:
        return

    symbol = position["symbol"]

    quantity = float(
        position["quantity"]
    )

    entry = float(
        position["entry"]
    )

    try:

        current = get_price(symbol)

        # ====================================================
        # الربح والخسارة للصفقة الحالية فقط
        # ====================================================

        entry_value = entry * quantity

        current_value = current * quantity

        if entry_value > 0:

            profit_percent = (
                (
                    current_value
                    - entry_value
                )
                / entry_value
            ) * 100

        else:

            profit_percent = 0.0

        profit_usdt = (
            current_value
            - entry_value
        )

        position["price"] = current

        # هذا هو ربح الصفقة الحالية فقط
        position["profit"] = profit_percent

        position["profit_usdt"] = profit_usdt

        # ====================================================
        # حماية الربح كل +1%
        # ====================================================

        if profit_percent >= PROTECTION_START:

            level = int(
                profit_percent // PROTECTION_STEP
            )

            new_protection = (
                level - TRAILING_PERCENT
            )

            old_protection = position.get(
                "protection"
            )

            if (
                old_protection is None
                or new_protection > old_protection
            ):

                position["protection"] = (
                    new_protection
                )

                position["protection_profit"] = (
                    new_protection
                )

                log(
                    f"🛡️ حماية {symbol}: "
                    f"+{new_protection:.2f}%"
                )

        protection = position.get(
            "protection"
        )

        # ====================================================
        # وقف الحماية
        # ====================================================

        if (
            protection is not None
            and profit_percent <= protection
        ):

            log(
                f"🔴 حماية الصفقة: "
                f"{symbol} "
                f"{profit_percent:+.2f}%"
            )

            sell_position()

            return

        state["bot"]["mode"] = (
            f"إدارة {symbol}"
        )

        state["bot"]["last_check"] = time.time()

        log(
            f"📊 {symbol} | "
            f"السعر {current:.8f} | "
            f"الصفقة {profit_percent:+.2f}% | "
            f"{profit_usdt:+.4f} USDT"
        )

    except Exception as e:

        state["bot"]["last_error"] = str(e)

        log(
            f"❌ خطأ إدارة {symbol}: {e}"
        )


# ============================================================
# Market Buy
# ============================================================

def buy_position(symbol):

    try:

        account = get_account()

        usdt = get_usdt_balance(account)

        if usdt < 5:

            log(
                f"⚠️ رصيد USDT غير كافي: {usdt:.2f}"
            )

            return False

        amount = usdt * (
            BUY_PERCENT / 100
        )

        log(
            f"🟢 شراء {symbol} "
            f"بقيمة {amount:.2f} USDT"
        )

        result = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": (
                    f"{amount:.2f}"
                )
            }
        )

        executed_qty = float(
            result.get(
                "executedQty",
                0
            )
        )

        fills = result.get(
            "fills",
            []
        )

        total_cost = 0.0

        total_qty = 0.0

        for fill in fills:

            qty = float(fill["qty"])
            price = float(fill["price"])

            total_qty += qty
            total_cost += (
                qty * price
            )

        if total_qty > 0:

            entry = (
                total_cost
                / total_qty
            )

        else:

            entry = get_price(symbol)

        current = get_price(symbol)

        position = {
            "symbol": symbol,
            "quantity": (
                executed_qty
                if executed_qty > 0
                else total_qty
            ),

            "entry": entry,
            "price": current,

            # الصفقة الجديدة تبدأ بصفر
            "profit": 0.0,
            "profit_usdt": 0.0,

            "protection": None,
            "protection_profit": None,

            "opened_at": time.time(),

            "recovered": False
        }

        state["position"] = position

        state["stats"]["buys"] += 1

        log(
            f"✅ تم شراء {symbol} "
            f"| دخول {entry:.8f}"
        )

        return True

    except Exception as e:

        state["bot"]["last_error"] = str(e)

        log(
            f"❌ فشل شراء {symbol}: {e}"
        )

        return False


# ============================================================
# Market Sell
# ============================================================

def sell_position():

    position = state.get("position")

    if not position:
        return False

    symbol = position["symbol"]

    quantity = float(
        position["quantity"]
    )

    try:

        log(
            f"🔴 بيع الصفقة الحالية {symbol}"
        )

        # نحصل على رصيد العملة الحقيقي
        account = get_account()

        asset = symbol.replace(
            "USDT",
            ""
        )

        real_quantity = 0.0

        for balance in account.get(
            "balances",
            []
        ):

            if balance["asset"] == asset:

                real_quantity = (
                    float(balance["free"])
                )

                break

        if real_quantity > 0:

            quantity = min(
                quantity,
                real_quantity
            )

        # السعر الحالي
        current = get_price(symbol)

        # ربح الصفقة قبل البيع
        entry = float(
            position["entry"]
        )

        profit_percent = (
            (
                current - entry
            )
            / entry
        ) * 100

        profit_usdt = (
            current - entry
        ) * quantity

        # فلتر بسيط للكمية
        if quantity <= 0:

            log(
                f"⚠️ كمية البيع غير صالحة {symbol}"
            )

            return False

        # كمية مناسبة للـ Binance
        quantity_decimal = Decimal(
            str(quantity)
        ).quantize(
            Decimal("0.000001"),
            rounding=ROUND_DOWN
        )

        quantity_string = format(
            quantity_decimal,
            "f"
        )

        result = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": quantity_string
            }
        )

        log(
            f"✅ تم بيع {symbol} | "
            f"نتيجة الصفقة: "
            f"{profit_percent:+.2f}% | "
            f"{profit_usdt:+.4f} USDT"
        )

        state["stats"]["sells"] += 1

        # إغلاق الصفقة
        state["position"] = None

        state["bot"]["mode"] = (
            "البحث عن فرصة"
        )

        return True

    except Exception as e:

        state["bot"]["last_error"] = str(e)

        log(
            f"❌ فشل بيع {symbol}: {e}"
        )

        return False


# ============================================================
# فحص السوق
# ============================================================

def scan_market():

    state["bot"]["mode"] = (
        "فحص السوق"
    )

    state["bot"]["last_scan"] = time.time()

    symbols = load_exchange_info()

    total = len(symbols)

    state["stats"]["scanned"] = 0

    log(
        f"🔍 بدء فحص {total} زوج"
    )

    for index, symbol in enumerate(symbols, 1):

        # لا تفحص السوق إذا فتحت صفقة
        if state.get("position"):

            log(
                "⏹️ تم إيقاف الفحص "
                "لوجود صفقة مفتوحة"
            )

            return

        try:

            state["stats"]["scanned"] = index

            candles = get_klines(
                symbol,
                220
            )

            if len(candles) < EMA_PERIOD + 20:

                continue

            closes = [
                x["close"]
                for x in candles
            ]

            current = closes[-1]

            ema200 = calculate_ema(
                closes,
                EMA_PERIOD
            )

            if ema200 is None:
                continue

            # السعر فوق EMA200
            if current <= ema200:
                continue

            # حركة آخر 15 دقيقة
            previous_close = closes[-2]

            change = (
                (
                    current
                    - previous_close
                )
                / previous_close
            ) * 100

            if change < MIN_CHANGE_15M:
                continue

            # =================================================
            # حجم التداول
            # =================================================

            volumes = [
                x["volume"]
                for x in candles
            ]

            recent_volume = volumes[-1]

            average_volume = (
                sum(volumes[-21:-1])
                / 20
            )

            if average_volume <= 0:
                continue

            volume_ratio = (
                recent_volume
                / average_volume
            )

            if volume_ratio < 1.5:
                continue

            # =================================================
            # مقاومة آخر 20 شمعة
            # =================================================

            resistance = max(
                x["high"]
                for x in candles[-21:-1]
            )

            if current <= resistance:
                continue

            # =================================================
            # إشارة شراء
            # =================================================

            state["stats"]["signals"] += 1

            log(
                f"🟢 إشارة شراء: {symbol} | "
                f"تغير {change:.2f}% | "
                f"حجم {volume_ratio:.2f}x"
            )

            # شراء أول إشارة فقط
            if buy_position(symbol):

                return

        except Exception as e:

            state["bot"]["last_error"] = str(e)

            log(
                f"⚠️ {symbol}: {e}"
            )

    log(
        "✅ انتهى فحص السوق"
    )


# ============================================================
# محرك التداول
# ============================================================

def trading_engine():

    log(
        "🤖 محرك التداول بدأ"
    )

    # تحميل الأزواج مرة واحدة
    try:

        load_exchange_info()

    except Exception as e:

        log(
            f"⚠️ تعذر تحميل معلومات Binance: {e}"
        )

    # ========================================================
    # استرجاع الصفقة بعد إعادة التشغيل
    # ========================================================

    try:

        log(
            "🔎 فحص الحساب لمعرفة هل توجد صفقة..."
        )

        recovered = find_open_position()

        if recovered:

            state["position"] = recovered

            log(
                f"♻️ تم استرجاع الصفقة "
                f"{recovered['symbol']}"
            )

    except Exception as e:

        state["bot"]["last_error"] = str(e)

        log(
            f"❌ فشل استرجاع الصفقة: {e}"
        )

    # ========================================================
    # Loop
    # ========================================================

    while True:

        try:

            position = state.get(
                "position"
            )

            # ------------------------------------------------
            # توجد صفقة
            # ------------------------------------------------

            if position:

                manage_position()

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # ------------------------------------------------
            # لا توجد صفقة
            # ------------------------------------------------

            # نتأكد مرة أخرى من الحساب
            # قبل بدء المسح

            recovered = find_open_position()

            if recovered:

                state["position"] = recovered

                log(
                    f"♻️ تم العثور على صفقة "
                    f"{recovered['symbol']}"
                )

                continue

            # ------------------------------------------------
            # فحص السوق
            # ------------------------------------------------

            scan_market()

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            state["bot"]["last_error"] = str(e)

            log(
                f"❌ خطأ بالمحرك: {e}"
            )

            time.sleep(30)


# ============================================================
# Dashboard
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>مضارب أبو سعود</title>

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
        #0b1020;

    color: #fff;

    padding: 15px;
}

.container {

    max-width: 1100px;

    margin: auto;
}

.header {

    background:
        linear-gradient(
            135deg,
            #151c35,
            #10162a
        );

    border:
        1px solid #293354;

    border-radius: 20px;

    padding: 20px;

    margin-bottom: 15px;

    box-shadow:
        0 10px 30px
        rgba(0,0,0,.25);
}

.title {

    font-size: 25px;

    font-weight: bold;

    margin-bottom: 7px;
}

.subtitle {

    color: #9da8c7;

    font-size: 14px;
}

.status {

    margin-top: 15px;

    padding: 12px;

    border-radius: 12px;

    background: #10182d;

    border: 1px solid #273354;

    color: #79e6a7;
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

    background:
        #121a30;

    border:
        1px solid #273354;

    border-radius: 16px;

    padding: 16px;
}

.label {

    color: #8f9ab8;

    font-size: 13px;

    margin-bottom: 8px;
}

.value {

    font-size: 21px;

    font-weight: bold;
}

.position {

    background:
        linear-gradient(
            135deg,
            #10291f,
            #111d2c
        );

    border:
        1px solid #24583e;

    border-radius: 20px;

    padding: 18px;

    margin-bottom: 15px;
}

.position-title {

    font-size: 21px;

    font-weight: bold;

    margin-bottom: 18px;

    color: #78e6a5;
}

.position-grid {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(150px, 1fr)
        );

    gap: 14px;
}

.green {
    color: #55e68d;
}

.red {
    color: #ff6675;
}

.yellow {
    color: #ffd166;
}

.logs {

    background: #080d1b;

    border:
        1px solid #273354;

    border-radius: 16px;

    padding: 15px;

    height: 350px;

    overflow-y: auto;

    direction: rtl;
}

.log {

    border-bottom:
        1px solid #18213a;

    padding: 8px 0;

    font-size: 13px;

    color: #c7cee1;
}

.empty {

    text-align: center;

    padding: 35px;

    color: #8792af;
}

.badge {

    display: inline-block;

    padding: 5px 10px;

    border-radius: 20px;

    background: #163f2a;

    color: #70e6a1;

    font-size: 12px;
}

</style>

</head>

<body>

<div class="container">

    <div class="header">

        <div class="title">
            🤖 مضارب أبو سعود V6 FAST PRO
        </div>

        <div class="subtitle">
            Binance Spot • 15m • حماية متحركة
        </div>

        <div
            id="status"
            class="status"
        >
            جاري الاتصال...
        </div>

    </div>


    <div
        id="position-area"
    ></div>


    <div
        class="grid"
    >

        <div class="card">

            <div class="label">
                💰 رصيد USDT
            </div>

            <div
                id="usdt"
                class="value"
            >
                0.00
            </div>

        </div>


        <div class="card">

            <div class="label">
                🔍 تم فحص
            </div>

            <div
                id="scanned"
                class="value"
            >
                0
            </div>

        </div>


        <div class="card">

            <div class="label">
                🎯 الإشارات
            </div>

            <div
                id="signals"
                class="value"
            >
                0
            </div>

        </div>


        <div class="card">

            <div class="label">
                🟢 عمليات الشراء
            </div>

            <div
                id="buys"
                class="value"
            >
                0
            </div>

        </div>


        <div class="card">

            <div class="label">
                🔴 عمليات البيع
            </div>

            <div
                id="sells"
                class="value"
            >
                0
            </div>

        </div>

    </div>


    <div class="card">

        <div class="label">
            📋 سجل البوت
        </div>

        <div
            id="logs"
            class="logs"
        >
            جاري التحميل...
        </div>

    </div>

</div>


<script>

function money(value) {

    value = Number(value || 0);

    if (
        Math.abs(value) < 0.000001
    ) {

        return "0.00";

    }

    return value.toLocaleString(
        "en-US",
        {
            maximumFractionDigits: 8
        }
    );
}


async function update() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache: "no-store"
                }
            );

        const data =
            await response.json();


        document.getElementById(
            "status"
        ).innerHTML =

            `<span class="badge">
                ${data.bot.mode}
            </span>
            &nbsp; ${data.bot.message || ""}`;


        document.getElementById(
            "usdt"
        ).textContent =
            money(data.account.usdt)
            + " USDT";


        document.getElementById(
            "scanned"
        ).textContent =
            data.stats.scanned;


        document.getElementById(
            "signals"
        ).textContent =
            data.stats.signals;


        document.getElementById(
            "buys"
        ).textContent =
            data.stats.buys;


        document.getElementById(
            "sells"
        ).textContent =
            data.stats.sells;


        const area =
            document.getElementById(
                "position-area"
            );


        // ==============================================
        // لا توجد صفقة = لا يوجد ربح / خسارة
        // ==============================================

        if (!data.position) {

            area.innerHTML = `

                <div class="card empty">

                    ⚪ لا توجد صفقة مفتوحة

                </div>

            `;

        } else {

            const p =
                data.position;

            const profit =
                Number(
                    p.profit || 0
                );

            const profitUsdt =
                Number(
                    p.profit_usdt || 0
                );

            const protection =
                p.protection !== null &&
                p.protection !== undefined

                ? (
                    "+" +
                    Number(
                        p.protection
                    ).toFixed(2) +
                    "%"
                )

                : "لم تبدأ";


            const cls =
                profit >= 0
                ? "green"
                : "red";


            const sign =
                profit >= 0
                ? "+"
                : "";


            const signUsdt =
                profitUsdt >= 0
                ? "+"
                : "";


            area.innerHTML = `

                <div class="position">

                    <div class="position-title">

                        🟢 الصفقة الحالية
                        — ${p.symbol}

                    </div>


                    <div class="position-grid">


                        <div>

                            <div class="label">
                                سعر الدخول
                            </div>

                            <div class="value">
                                ${money(p.entry)}
                            </div>

                        </div>


                        <div>

                            <div class="label">
                                السعر الحالي
                            </div>

                            <div class="value">
                                ${money(p.price)}
                            </div>

                        </div>


                        <div>

                            <div class="label">
                                ربح / خسارة الصفقة
                            </div>

                            <div
                                class="value ${cls}"
                            >

                                ${sign}
                                ${profit.toFixed(2)}%

                            </div>

                        </div>


                        <div>

                            <div class="label">
                                ربح / خسارة USDT
                            </div>

                            <div
                                class="value ${cls}"
                            >

                                ${signUsdt}
                                ${money(profitUsdt)}
                                USDT

                            </div>

                        </div>


                        <div>

                            <div class="label">
                                الكمية
                            </div>

                            <div class="value">
                                ${money(p.quantity)}
                            </div>

                        </div>


                        <div>

                            <div class="label">
                                🛡️ الحماية
                            </div>

                            <div
                                class="value yellow"
                            >

                                ${protection}

                            </div>

                        </div>


                    </div>

                </div>

            `;

        }


        const logs =
            document.getElementById(
                "logs"
            );


        logs.innerHTML =
            data.logs
                .map(
                    x =>
                    `<div class="log">
                        ${x}
                    </div>`
                )
                .join("");


    } catch (error) {

        document.getElementById(
            "status"
        ).textContent =
            "⚠️ تعذر تحديث لوحة المتابعة";

    }

}


update();

setInterval(
    update,
    5000
);

</script>

</body>

</html>
"""


# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    # مهم:
    # لا نستدعي Binance هنا.
    # الموقع يقرأ البيانات المحفوظة من البوت فقط.

    return jsonify({
        "bot": state["bot"],
        "account": state["account"],
        "position": state["position"],
        "stats": state["stats"],
        "logs": state["logs"]
    })


# ============================================================
# تشغيل Flask
# ============================================================

def run_server():

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    log(
        f"🌐 الموقع يعمل على PORT {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    print(
        "\n🚀 تشغيل V6 FAST PRO\n",
        flush=True
    )

    server_thread = threading.Thread(
        target=run_server,
        daemon=True
    )

    server_thread.start()

    trading_thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    trading_thread.start()

    while True:

        time.sleep(60)
