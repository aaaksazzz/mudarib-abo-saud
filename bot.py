# ============================================================
# مضارب أبو سعود V6 FAST PRO 2 🤖
# Binance Spot + Dashboard
# - استرجاع الصفقة بعد إعادة التشغيل
# - إدارة صفقة واحدة فقط
# - حماية الربح كل +1%
# - لا يفحص السوق أثناء وجود صفقة
# - لوحة متابعة احترافية
# ============================================================

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
# الإعدادات
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

BASE = "https://api.binance.com"

TITLE = "مضارب أبو سعود 🤖"

TIMEFRAME = "15m"
EMA_PERIOD = 200

# الاستراتيجية كما هي
MIN_CHANGE_15M = 1.0

# إدارة الربح
PROTECTION_START = 1.0
PROTECTION_STEP = 1.0
TRAILING_PERCENT = 0.50

# الفواصل
POSITION_CHECK_SECONDS = 30
SCAN_INTERVAL = 60

# أقل قيمة للصفقة
MIN_POSITION_USDT = 2.0

# نسبة استخدام الرصيد
BUY_PERCENT = 99.9

# مهلة الاتصال
REQUEST_TIMEOUT = 10

# ============================================================
# جلسة HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-V6-PRO/2.0"
})

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

# ============================================================
# حالة البوت
# ============================================================

state_lock = threading.Lock()

state = {
    "bot": {
        "running": True,
        "started_at": time.time(),
        "last_check": None,
        "last_scan": None,
        "last_error": None,
        "message": "جاري التشغيل...",
        "mode": "فحص الحساب",
        "last_step": "",
        "last_api": "",
        "last_api_ok": None
    },

    "account": {
        "usdt": 0.0,
        "total": 0.0
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
# أدوات مساعدة
# ============================================================

def log(message):
    now = time.strftime("%H:%M:%S")

    line = f"[{now}] {message}"

    print(line, flush=True)

    with state_lock:
        state["logs"].insert(0, line)
        state["logs"] = state["logs"][:80]
        state["bot"]["message"] = message


def set_step(step):
    with state_lock:
        state["bot"]["last_step"] = step


def api_ok(endpoint):
    with state_lock:
        state["bot"]["last_api"] = endpoint
        state["bot"]["last_api_ok"] = True


def api_fail(endpoint, error):
    with state_lock:
        state["bot"]["last_api"] = endpoint
        state["bot"]["last_api_ok"] = False
        state["bot"]["last_error"] = str(error)


def decimal_str(value):
    return format(Decimal(str(value)), "f")


# ============================================================
# Binance GET عام
# ============================================================

def public_get(path, params=None):

    url = BASE + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 429:
            raise Exception("Binance Rate Limit 429")

        if response.status_code >= 500:
            raise Exception(
                f"Binance Server Error {response.status_code}"
            )

        response.raise_for_status()

        data = response.json()

        api_ok(path)

        return data

    except Exception as e:

        api_fail(path, e)

        log(f"❌ API {path}: {e}")

        raise


# ============================================================
# Binance Signed Request
# ============================================================

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

    url = BASE + path + "?" + query

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    try:

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
            raise Exception("Unsupported HTTP method")

        if response.status_code == 429:
            raise Exception("Binance Rate Limit 429")

        if response.status_code >= 500:
            raise Exception(
                f"Binance Server Error {response.status_code}"
            )

        response.raise_for_status()

        data = response.json()

        api_ok(path)

        return data

    except Exception as e:

        api_fail(path, e)

        log(f"❌ Binance {path}: {e}")

        raise


# ============================================================
# معلومات الحساب
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account",
        {
            "recvWindow": 10000
        }
    )


# ============================================================
# رصيد USDT
# ============================================================

def get_usdt_balance():

    account = get_account()

    for balance in account.get("balances", []):

        if balance["asset"] == "USDT":

            free = float(balance["free"])

            with state_lock:
                state["account"]["usdt"] = free
                state["account"]["total"] = free

            return free

    return 0.0


# ============================================================
# سعر عملة
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
# كل الأسعار
# ============================================================

def get_all_prices():

    data = public_get(
        "/api/v3/ticker/price"
    )

    result = {}

    for item in data:

        try:
            result[item["symbol"]] = float(item["price"])
        except:
            pass

    return result


# ============================================================
# معلومات العملات
# ============================================================

symbols_cache = set()
symbols_cache_time = 0


def load_exchange_info():

    global symbols_cache
    global symbols_cache_time

    now = time.time()

    if symbols_cache and now - symbols_cache_time < 1800:
        return symbols_cache

    log("🔄 تحميل معلومات Binance...")

    data = public_get(
        "/api/v3/exchangeInfo"
    )

    valid = set()

    for item in data.get("symbols", []):

        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
        ):
            valid.add(item["symbol"])

    symbols_cache = valid
    symbols_cache_time = now

    log(f"✅ تم تحميل معلومات Binance: {len(valid)} زوج USDT")

    return symbols_cache


def get_valid_usdt_symbols():

    return load_exchange_info()


# ============================================================
# بيانات الشموع
# ============================================================

def get_klines(symbol, interval="15m", limit=200):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


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
# تحليل العملة
# ============================================================

def analyze_symbol(symbol):

    try:

        klines = get_klines(
            symbol,
            TIMEFRAME,
            200
        )

        if len(klines) < EMA_PERIOD + 5:
            return None

        closes = [
            float(x[4])
            for x in klines
        ]

        volumes = [
            float(x[5])
            for x in klines
        ]

        current = closes[-1]

        previous = closes[-2]

        ema200 = calculate_ema(
            closes,
            EMA_PERIOD
        )

        if ema200 is None:
            return None

        # تغير آخر 15 دقيقة
        change = (
            (current - previous)
            / previous
        ) * 100

        # متوسط الحجم
        avg_volume = sum(
            volumes[-21:-1]
        ) / 20

        current_volume = volumes[-1]

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 0
        )

        # ====================================================
        # شروط الاستراتيجية
        # ====================================================

        if current <= ema200:
            return None

        if change < MIN_CHANGE_15M:
            return None

        if volume_ratio < 1.5:
            return None

        # ====================================================
        # اختراق أعلى 20 شمعة
        # ====================================================

        previous_highs = [
            float(x[2])
            for x in klines[-21:-1]
        ]

        resistance = max(previous_highs)

        if current <= resistance:
            return None

        return {
            "symbol": symbol,
            "price": current,
            "ema": ema200,
            "change": change,
            "volume_ratio": volume_ratio,
            "resistance": resistance
        }

    except Exception:

        return None


# ============================================================
# حساب سعر الدخول من Trades
# ============================================================

def calculate_entry(symbol):

    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 100,
                "recvWindow": 10000
            }
        )

        buys = []

        for trade in trades:

            if trade.get("isBuyer"):

                qty = float(trade["qty"])
                price = float(trade["price"])

                buys.append(
                    (
                        qty,
                        price
                    )
                )

        if buys:

            total_qty = sum(
                x[0]
                for x in buys
            )

            if total_qty > 0:

                total_cost = sum(
                    qty * price
                    for qty, price in buys
                )

                return total_cost / total_qty

    except Exception as e:

        log(
            f"⚠️ تعذر حساب الدخول {symbol}: {e}"
        )

    return get_price(symbol)


# ============================================================
# اكتشاف الصفقة المفتوحة بعد إعادة التشغيل
# ============================================================

def find_open_position():

    log("🔎 جاري التحقق من الصفقة المفتوحة...")

    # --------------------------------------------------------
    # 1
    # --------------------------------------------------------

    set_step("الاتصال بحساب Binance")

    log("🔎 [1/4] الاتصال بحساب Binance...")

    account = get_account()

    log("✅ [1/4] تم استلام بيانات الحساب")

    # تحديث USDT مباشرة من نفس الطلب
    usdt_balance = 0.0

    for balance in account.get("balances", []):

        if balance["asset"] == "USDT":

            usdt_balance = float(balance["free"])
            break

    with state_lock:
        state["account"]["usdt"] = usdt_balance
        state["account"]["total"] = usdt_balance

    # --------------------------------------------------------
    # 2
    # --------------------------------------------------------

    set_step("جلب أسعار العملات")

    log("🔎 [2/4] جلب أسعار Binance...")

    prices = get_all_prices()

    log(
        f"✅ [2/4] تم جلب {len(prices)} سعر"
    )

    # --------------------------------------------------------
    # 3
    # --------------------------------------------------------

    set_step("البحث عن العملات الموجودة بالحساب")

    log("🔎 [3/4] البحث عن رصيد غير USDT...")

    valid_symbols = get_valid_usdt_symbols()

    candidates = []

    for balance in account.get("balances", []):

        asset = balance["asset"]

        if asset == "USDT":
            continue

        try:
            free = float(balance["free"])
            locked = float(balance["locked"])
        except:
            continue

        quantity = free + locked

        if quantity <= 0:
            continue

        symbol = asset + "USDT"

        if symbol not in valid_symbols:
            continue

        price = prices.get(symbol)

        if not price or price <= 0:
            continue

        value = quantity * price

        if value < MIN_POSITION_USDT:
            continue

        candidates.append({
            "symbol": symbol,
            "asset": asset,
            "quantity": quantity,
            "price": price,
            "value": value
        })

    # --------------------------------------------------------
    # لا توجد صفقة
    # --------------------------------------------------------

    if not candidates:

        set_step("لا توجد صفقة مفتوحة")

        log("🟢 [3/4] لا توجد صفقة مفتوحة")

        return None

    # أكبر مركز
    candidates.sort(
        key=lambda x: x["value"],
        reverse=True
    )

    candidate = candidates[0]

    symbol = candidate["symbol"]

    # --------------------------------------------------------
    # 4
    # --------------------------------------------------------

    set_step("حساب سعر الدخول")

    log(
        f"🔎 [4/4] تم العثور على {symbol} — حساب الدخول..."
    )

    entry = calculate_entry(symbol)

    current = candidate["price"]

    profit = (
        (current - entry)
        / entry
    ) * 100

    position = {
        "symbol": symbol,
        "quantity": candidate["quantity"],
        "entry": entry,
        "price": current,
        "profit": profit,
        "protection": None,
        "protection_profit": None,
        "opened_at": time.time(),
        "recovered": True
    }

    log(
        f"🟢 تم استرجاع الصفقة: "
        f"{symbol} | دخول {entry:.8f} | "
        f"الحالي {current:.8f} | "
        f"الربح {profit:+.2f}%"
    )

    return position


# ============================================================
# تحديث الصفقة
# ============================================================

def update_position_state(position):

    with state_lock:
        state["position"] = dict(position)


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position(position):

    symbol = position["symbol"]

    try:

        current = get_price(symbol)

        entry = float(position["entry"])

        quantity = float(position["quantity"])

        profit = (
            (current - entry)
            / entry
        ) * 100

        position["price"] = current
        position["profit"] = profit

        # ====================================================
        # حماية الربح
        # ====================================================

        if profit >= PROTECTION_START:

            level = int(
                profit // PROTECTION_STEP
            )

            protection_profit = (
                level * PROTECTION_STEP
            ) - TRAILING_PERCENT

            protection_price = (
                entry
                * (
                    1
                    + protection_profit / 100
                )
            )

            old_protection = position.get(
                "protection"
            )

            # لا ننزل الحماية أبداً
            if (
                old_protection is None
                or protection_price > old_protection
            ):

                position["protection"] = (
                    protection_price
                )

                position["protection_profit"] = (
                    protection_profit
                )

                log(
                    f"🛡️ حماية جديدة {symbol}: "
                    f"+{protection_profit:.2f}% "
                    f"| سعر {protection_price:.8f}"
                )

        # ====================================================
        # بيع عند الحماية
        # ====================================================

        protection = position.get(
            "protection"
        )

        if (
            protection is not None
            and current <= protection
        ):

            log(
                f"🔴 ضربت الحماية {symbol} "
                f"| الحالي {current:.8f} "
                f"| الحماية {protection:.8f}"
            )

            sell_position(
                symbol,
                quantity
            )

            with state_lock:
                state["stats"]["sells"] += 1
                state["position"] = None

            return False

        update_position_state(position)

        return True

    except Exception as e:

        log(
            f"⚠️ خطأ إدارة الصفقة {symbol}: {e}"
        )

        update_position_state(position)

        return True


# ============================================================
# فلتر الكمية
# ============================================================

def get_symbol_filters(symbol):

    data = public_get(
        "/api/v3/exchangeInfo",
        {
            "symbol": symbol
        }
    )

    info = data["symbols"][0]

    filters = {}

    for f in info.get("filters", []):

        filters[f["filterType"]] = f

    return filters


def normalize_quantity(symbol, quantity):

    try:

        filters = get_symbol_filters(symbol)

        lot = filters.get("LOT_SIZE")

        if not lot:
            return quantity

        step = Decimal(
            lot["stepSize"]
        )

        minimum = Decimal(
            lot["minQty"]
        )

        qty = Decimal(
            str(quantity)
        )

        qty = (
            qty / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

        if qty < minimum:
            return 0.0

        return float(qty)

    except Exception as e:

        log(
            f"⚠️ مشكلة ضبط الكمية {symbol}: {e}"
        )

        return quantity


# ============================================================
# شراء
# ============================================================

def buy_position(signal):

    symbol = signal["symbol"]

    try:

        usdt = get_usdt_balance()

        amount = (
            usdt
            * BUY_PERCENT
            / 100
        )

        if amount < MIN_POSITION_USDT:
            log(
                f"⚠️ رصيد USDT غير كافي: {usdt:.2f}"
            )
            return None

        log(
            f"🟢 إشارة شراء {symbol} "
            f"| السعر {signal['price']:.8f} "
            f"| التغير {signal['change']:+.2f}% "
            f"| الحجم x{signal['volume_ratio']:.2f}"
        )

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": decimal_str(
                    amount
                ),
                "recvWindow": 10000
            }
        )

        fills = order.get(
            "fills",
            []
        )

        total_qty = 0.0
        total_cost = 0.0

        for fill in fills:

            qty = float(
                fill["qty"]
            )

            price = float(
                fill["price"]
            )

            total_qty += qty
            total_cost += (
                qty * price
            )

        if total_qty <= 0:

            log(
                f"⚠️ لم يتم الحصول على كمية شراء {symbol}"
            )

            return None

        entry = (
            total_cost
            / total_qty
        )

        position = {
            "symbol": symbol,
            "quantity": total_qty,
            "entry": entry,
            "price": entry,
            "profit": 0.0,
            "protection": None,
            "protection_profit": None,
            "opened_at": time.time(),
            "recovered": False
        }

        with state_lock:
            state["stats"]["buys"] += 1
            state["position"] = position

        log(
            f"🟢 تم الشراء: {symbol} "
            f"| كمية {total_qty:.8f} "
            f"| دخول {entry:.8f}"
        )

        return position

    except Exception as e:

        log(
            f"❌ فشل شراء {symbol}: {e}"
        )

        return None


# ============================================================
# بيع
# ============================================================

def sell_position(symbol, quantity):

    try:

        qty = normalize_quantity(
            symbol,
            quantity
        )

        if qty <= 0:

            log(
                f"❌ كمية البيع غير صالحة {symbol}"
            )

            return None

        log(
            f"🔴 بيع {symbol} "
            f"| الكمية {qty:.8f}"
        )

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": decimal_str(qty),
                "recvWindow": 10000
            }
        )

        log(
            f"✅ تم البيع {symbol}"
        )

        return order

    except Exception as e:

        log(
            f"❌ فشل بيع {symbol}: {e}"
        )

        raise


# ============================================================
# فحص السوق
# ============================================================

def scan_market():

    # ممنوع الفحص إذا فيه صفقة
    with state_lock:
        if state["position"] is not None:
            return

    symbols = list(
        get_valid_usdt_symbols()
    )

    log(
        f"🔍 بدء فحص السوق: "
        f"{len(symbols)} زوج"
    )

    with state_lock:
        state["stats"]["scanned"] = 0
        state["bot"]["last_scan"] = time.time()
        state["bot"]["mode"] = "فحص السوق"

    for index, symbol in enumerate(symbols, 1):

        # ----------------------------------------------------
        # تحقق كل مرة قبل التحليل
        # ----------------------------------------------------

        with state_lock:

            if state["position"] is not None:
                log(
                    "🛑 تم إيقاف الفحص: "
                    "تم فتح صفقة"
                )
                return

        try:

            signal = analyze_symbol(
                symbol
            )

            with state_lock:
                state["stats"]["scanned"] = index

            if signal:

                with state_lock:
                    state["stats"]["signals"] += 1

                log(
                    f"🎯 إشارة {symbol} "
                    f"| +{signal['change']:.2f}% "
                    f"| Volume x{signal['volume_ratio']:.2f}"
                )

                position = buy_position(
                    signal
                )

                if position:

                    log(
                        f"🛑 تم إيقاف السوق "
                        f"لإدارة {symbol}"
                    )

                    return

        except Exception as e:

            log(
                f"⚠️ خطأ {symbol}: {e}"
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

    first_start = True

    while True:

        try:

            # =================================================
            # إذا عندنا صفقة محفوظة في الذاكرة
            # =================================================

            with state_lock:
                current_position = state["position"]

            if current_position:

                with state_lock:
                    state["bot"]["mode"] = "إدارة الصفقة"

                manage_position(
                    current_position
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # فحص Binance بعد التشغيل
            # =================================================

            with state_lock:
                state["bot"]["mode"] = (
                    "استرجاع الصفقة"
                )

            log(
                "🔎 فحص الحساب لمعرفة هل توجد صفقة..."
            )

            position = find_open_position()

            if position:

                with state_lock:
                    state["position"] = position
                    state["bot"]["mode"] = (
                        "إدارة صفقة مسترجعة"
                    )

                log(
                    f"♻️ تم استرجاع {position['symbol']} "
                    f"بعد إعادة التشغيل"
                )

                manage_position(
                    position
                )

                first_start = False

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # لا توجد صفقة
            # =================================================

            if first_start:

                log(
                    "🟢 الحساب خالي من الصفقات"
                )

                first_start = False

            # =================================================
            # فحص السوق
            # =================================================

            with state_lock:
                state["bot"]["mode"] = (
                    "البحث عن فرصة"
                )

            scan_market()

            # =================================================
            # انتظار
            # =================================================

            log(
                f"⏳ انتظار {SCAN_INTERVAL} ثانية..."
            )

            time.sleep(
                SCAN_INTERVAL
            )

        except KeyboardInterrupt:

            log(
                "🛑 إيقاف البوت"
            )

            break

        except Exception as e:

            with state_lock:
                state["bot"]["last_error"] = str(e)

            log(
                f"⚠️ خطأ محرك التداول: {e}"
            )

            # مهم:
            # إذا حصل خطأ لا نفتح صفقة جديدة مباشرة
            # ننتظر ثم نعيد فحص الحساب
            time.sleep(30)


# ============================================================
# Dashboard HTML
# ============================================================

HTML = """
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
    font-family: Arial, Tahoma, sans-serif;
    background:
        radial-gradient(
            circle at top,
            #172033 0%,
            #090d14 45%,
            #05070b 100%
        );
    color: #fff;
    min-height: 100vh;
}

.container {
    max-width: 1100px;
    margin: auto;
    padding: 20px;
}

.header {
    background: rgba(20, 27, 40, .92);
    border: 1px solid #273247;
    border-radius: 22px;
    padding: 22px;
    margin-bottom: 18px;
    box-shadow: 0 15px 45px rgba(0,0,0,.25);
}

.title {
    font-size: 26px;
    font-weight: 800;
}

.subtitle {
    color: #8d9ab0;
    margin-top: 7px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
}

.card {
    background: rgba(18, 24, 36, .94);
    border: 1px solid #273247;
    border-radius: 20px;
    padding: 20px;
    box-shadow:
        0 10px 35px rgba(0,0,0,.20);
}

.label {
    color: #8d9ab0;
    font-size: 13px;
    margin-bottom: 9px;
}

.value {
    font-size: 25px;
    font-weight: 800;
}

.green {
    color: #35d07f;
}

.red {
    color: #ff5f6d;
}

.yellow {
    color: #ffc857;
}

.blue {
    color: #5da9ff;
}

.position {
    margin-top: 18px;
    background: rgba(15, 31, 27, .95);
    border: 1px solid #1d6b4b;
    border-radius: 22px;
    padding: 22px;
}

.position-title {
    font-size: 20px;
    font-weight: 800;
    margin-bottom: 16px;
}

.position-grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px;
}

.empty {
    margin-top: 18px;
    background: rgba(18, 24, 36, .94);
    border: 1px solid #273247;
    border-radius: 20px;
    padding: 25px;
    text-align: center;
    color: #8d9ab0;
}

.logs {
    margin-top: 18px;
}

.logbox {
    background: #05080d;
    border: 1px solid #202a3b;
    border-radius: 18px;
    padding: 15px;
    max-height: 350px;
    overflow-y: auto;
    direction: ltr;
    text-align: left;
}

.logline {
    font-family: monospace;
    color: #aebbd0;
    padding: 5px 0;
    border-bottom: 1px solid #111823;
}

.status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #103d2a;
    border: 1px solid #1d7650;
    color: #48df91;
    padding: 7px 12px;
    border-radius: 999px;
    font-size: 13px;
    margin-top: 12px;
}

.dot {
    width: 8px;
    height: 8px;
    background: #35d07f;
    border-radius: 50%;
    box-shadow: 0 0 10px #35d07f;
}

.footer {
    color: #59677e;
    text-align: center;
    padding: 22px;
    font-size: 12px;
}

</style>

</head>

<body>

<div class="container">

    <div class="header">

        <div class="title">
            🤖 مضارب أبو سعود V6 FAST PRO 2
        </div>

        <div class="subtitle">
            Binance Spot • إدارة صفقة واحدة • استرجاع تلقائي بعد إعادة التشغيل
        </div>

        <div class="status">
            <span class="dot"></span>
            البوت يعمل
        </div>

    </div>


    <div class="grid">

        <div class="card">
            <div class="label">
                حالة البوت
            </div>

            <div class="value blue"
                 id="mode">
                جاري...
            </div>
        </div>


        <div class="card">
            <div class="label">
                رصيد USDT
            </div>

            <div class="value"
                 id="usdt">
                0.00
            </div>
        </div>


        <div class="card">
            <div class="label">
                العملات المفحوصة
            </div>

            <div class="value"
                 id="scanned">
                0
            </div>
        </div>


        <div class="card">
            <div class="label">
                الإشارات
            </div>

            <div class="value yellow"
                 id="signals">
                0
            </div>
        </div>


        <div class="card">
            <div class="label">
                عمليات الشراء
            </div>

            <div class="value green"
                 id="buys">
                0
            </div>
        </div>


        <div class="card">
            <div class="label">
                عمليات البيع
            </div>

            <div class="value red"
                 id="sells">
                0
            </div>
        </div>

    </div>


    <div id="positionArea"></div>


    <div class="card logs">

        <div class="position-title">
            📋 سجل البوت
        </div>

        <div class="logbox"
             id="logs">
        </div>

    </div>


    <div class="footer">
        مضارب أبو سعود 🤖
    </div>

</div>


<script>

function money(value) {

    return Number(value || 0)
        .toLocaleString(
            'en-US',
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 8
            }
        );
}


function refresh() {

    fetch('/api/status')
        .then(r => r.json())
        .then(data => {

            document.getElementById(
                'mode'
            ).textContent =
                data.bot.mode || '---';


            document.getElementById(
                'usdt'
            ).textContent =
                money(data.account.usdt) +
                ' USDT';


            document.getElementById(
                'scanned'
            ).textContent =
                data.stats.scanned || 0;


            document.getElementById(
                'signals'
            ).textContent =
                data.stats.signals || 0;


            document.getElementById(
                'buys'
            ).textContent =
                data.stats.buys || 0;


            document.getElementById(
                'sells'
            ).textContent =
                data.stats.sells || 0;


            const area =
                document.getElementById(
                    'positionArea'
                );


            if (data.position) {

                const p =
                    data.position;

                const profit =
                    Number(p.profit || 0);

                const profitClass =
                    profit >= 0
                    ? 'green'
                    : 'red';

                let protection =
                    'غير مفعلة';

                if (
                    p.protection !== null &&
                    p.protection !== undefined
                ) {

                    protection =
                        money(
                            p.protection
                        );

                    if (
                        p.protection_profit !==
                        null
                    ) {

                        protection +=
                            ' (+' +
                            Number(
                                p.protection_profit
                            ).toFixed(2) +
                            '%)';
                    }
                }


                const recovered =
                    p.recovered
                    ? '♻️ مسترجعة بعد إعادة التشغيل'
                    : '🟢 صفقة حالية';


                area.innerHTML = `

                <div class="position">

                    <div class="position-title">
                        🟢 صفقة مفتوحة — ${p.symbol}
                    </div>

                    <div style="
                        color:#8d9ab0;
                        margin-bottom:16px;
                    ">
                        ${recovered}
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
                                الربح
                            </div>
                            <div class="value ${profitClass}">
                                ${profit >= 0 ? '+' : ''}
                                ${profit.toFixed(2)}%
                            </div>
                        </div>

                        <div>
                            <div class="label">
                                الحماية
                            </div>
                            <div class="value yellow">
                                ${protection}
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

                    </div>

                </div>

                `;

            } else {

                area.innerHTML = `

                <div class="empty">

                    🟡 لا توجد صفقة مفتوحة حالياً

                    <br><br>

                    البوت يبحث عن فرصة حسب الاستراتيجية

                </div>

                `;
            }


            const logs =
                document.getElementById(
                    'logs'
                );

            logs.innerHTML =
                (data.logs || [])
                .map(
                    x =>
                    `<div class="logline">
                        ${x}
                    </div>`
                )
                .join('');

        })
        .catch(() => {});

}


refresh();

setInterval(
    refresh,
    5000
);

</script>

</body>

</html>
"""


# ============================================================
# Dashboard
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


# ============================================================
# API Status
# ============================================================

@app.route("/api/status")
def api_status():

    # مهم:
    # لا نسوي اتصال Binance هنا.
    # اللوحة تقرأ البيانات المحفوظة فقط.

    with state_lock:

        data = {
            "bot": dict(
                state["bot"]
            ),

            "account": dict(
                state["account"]
            ),

            "position": (
                dict(state["position"])
                if state["position"]
                else None
            ),

            "stats": dict(
                state["stats"]
            ),

            "logs": list(
                state["logs"]
            )
        }

    return jsonify(data)


# ============================================================
# تشغيل البوت
# ============================================================

def main():

    print(
        "\n"
        "==================================================\n"
        "🚀 تشغيل مضارب أبو سعود V6 FAST PRO 2\n"
        "==================================================\n",
        flush=True
    )

    if not API_KEY or not API_SECRET:

        log(
            "❌ API_KEY أو API_SECRET غير موجود"
        )

    else:

        log(
            "🔐 مفاتيح Binance موجودة"
        )

    # تحميل العملات
    try:

        load_exchange_info()

    except Exception as e:

        log(
            f"⚠️ تعذر تحميل معلومات Binance: {e}"
        )

    # تشغيل محرك التداول
    worker = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    worker.start()

    # Render PORT
    port = int(
        os.environ.get(
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
# START
# ============================================================

if __name__ == "__main__":
    main()
