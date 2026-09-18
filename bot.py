import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv

# =============================================
# مضارب أبو سعود V5 🤖
# BINANCE SPOT
# حماية ربح حقيقية على Binance
# =============================================

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE_URL = "https://api.binance.com"

TIMEFRAME_15M = "15m"
TIMEFRAME_1H = "1h"

TRADE_USDT = Decimal("10")

# وقف الخسارة الأولي
STOP_LOSS_PCT = Decimal("0.02")

# تفعيل حماية الربح
PROFIT_ACTIVATE = Decimal("0.012")

# أول وقف ربح بعد التفعيل
PROFIT_LOCK = Decimal("0.002")

# كلما ارتفع السعر، نرفع الوقف تحته
TRAIL_DISTANCE = Decimal("0.006")

# شروط الدخول
VOLUME_MULTIPLIER = Decimal("1.5")
MIN_MOVE = Decimal("0.005")
MAX_MOVE = Decimal("0.04")

# فلاتر الحركة
MIN_CURRENT_RANGE = Decimal("0.003")
MIN_AVG_RANGE = Decimal("0.0025")
MIN_5CANDLE_RANGE = Decimal("0.008")

CHECK_SECONDS = 5
REQUEST_TIMEOUT = 15

STATE_FILE = "state.json"

session = requests.Session()
session.headers.update({
    "X-MBX-APIKEY": API_KEY or ""
})

SERVER_TIME_OFFSET = 0


# =============================================
# أدوات عامة
# =============================================

def D(x):
    return Decimal(str(x))


def dec_str(x):
    return format(D(x), "f")


def floor_step(value, step):
    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    return (value / step).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        required = ["symbol", "entry", "qty", "stop_order_id"]

        for x in required:
            if x not in state:
                return None

        return state

    except Exception:
        return None


def clear_state():
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    except Exception:
        pass


# =============================================
# توقيت Binance
# =============================================

def sync_time():
    global SERVER_TIME_OFFSET

    try:
        local_before = int(time.time() * 1000)

        r = session.get(
            BASE_URL + "/api/v3/time",
            timeout=REQUEST_TIMEOUT
        )

        server_time = int(r.json()["serverTime"])

        local_after = int(time.time() * 1000)

        midpoint = (local_before + local_after) // 2

        SERVER_TIME_OFFSET = server_time - midpoint

        print("🕐 تمت مزامنة وقت Binance")

    except Exception as e:
        print("⚠️ تعذر مزامنة الوقت:", e)


def timestamp():
    return int(time.time() * 1000) + SERVER_TIME_OFFSET


# =============================================
# Binance API
# =============================================

def public_get(path, params=None):
    try:
        r = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        data = r.json()

        if r.status_code != 200:
            print("⚠️ Binance:", data)

        return data

    except Exception as e:
        print("⚠️ اتصال Binance:", e)
        return None


def signed_request(method, path, params=None, retry=True):
    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = timestamp()
    params["recvWindow"] = 60000

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE_URL + path + "?" + query

    try:
        if method == "GET":
            r = session.get(url, timeout=REQUEST_TIMEOUT)

        elif method == "POST":
            r = session.post(url, timeout=REQUEST_TIMEOUT)

        elif method == "DELETE":
            r = session.delete(url, timeout=REQUEST_TIMEOUT)

        else:
            raise ValueError("Invalid method")

        data = r.json()

        if r.status_code != 200:
            print("⚠️ Binance:", data)

            if (
                retry
                and isinstance(data, dict)
                and data.get("code") == -1021
            ):
                sync_time()
                return signed_request(
                    method,
                    path,
                    params,
                    retry=False
                )

        return data

    except Exception as e:
        print("⚠️ Binance API:", e)
        return None


# =============================================
# معلومات العملات
# =============================================

SYMBOL_INFO = {}


def get_symbols():
    global SYMBOL_INFO

    data = public_get("/api/v3/exchangeInfo")

    if not data or "symbols" not in data:
        return False

    SYMBOL_INFO = {}

    for s in data["symbols"]:

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        filters = {}

        for f in s.get("filters", []):
            filters[f["filterType"]] = f

        lot = filters.get("LOT_SIZE", {})
        price_filter = filters.get("PRICE_FILTER", {})

        notional = (
            filters.get("NOTIONAL")
            or filters.get("MIN_NOTIONAL")
            or {}
        )

        trailing = filters.get("TRAILING_DELTA", {})

        SYMBOL_INFO[s["symbol"]] = {
            "base": s["baseAsset"],
            "quote": s["quoteAsset"],

            "min_qty": D(lot.get("minQty", "0")),
            "max_qty": D(lot.get("maxQty", "999999999")),
            "step": D(lot.get("stepSize", "0.00000001")),

            "tick": D(price_filter.get("tickSize", "0.00000001")),

            "min_notional": D(
                notional.get(
                    "minNotional",
                    "0"
                )
            ),

            "trailing": trailing
        }

    print(f"📊 تم تحميل {len(SYMBOL_INFO)} عملة Spot")
    return True


# =============================================
# الرصيد
# =============================================

def get_account():
    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_free_asset(asset):
    account = get_account()

    if not account or "balances" not in account:
        return Decimal("0")

    for b in account["balances"]:
        if b["asset"] == asset:
            return D(b["free"])

    return Decimal("0")


def get_free_usdt():
    return get_free_asset("USDT")


# =============================================
# السعر
# =============================================

def get_price(symbol):
    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    if not data or "price" not in data:
        return None

    return D(data["price"])


# =============================================
# الشموع
# =============================================

def get_klines(symbol, interval, limit=250):
    data = public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data or not isinstance(data, list):
        return None

    return data


# =============================================
# EMA
# =============================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = D("2") / D(period + 1)

    result = sum(values[:period]) / D(period)

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


# =============================================
# إشارة الدخول
# =============================================

def signal(symbol):

    try:
        k15 = get_klines(
            symbol,
            TIMEFRAME_15M,
            250
        )

        k1h = get_klines(
            symbol,
            TIMEFRAME_1H,
            250
        )

        if not k15 or not k1h:
            return False

        if len(k15) < 220 or len(k1h) < 220:
            return False

        close15 = [
            D(x[4]) for x in k15
        ]

        close1h = [
            D(x[4]) for x in k1h
        ]

        highs = [
            D(x[2]) for x in k15
        ]

        lows = [
            D(x[3]) for x in k15
        ]

        volumes = [
            D(x[5]) for x in k15
        ]

        # آخر شمعة مكتملة
        current_close = close15[-2]

        ema15 = ema(
            close15[:-1],
            200
        )

        ema1h = ema(
            close1h[:-1],
            200
        )

        if ema15 is None or ema1h is None:
            return False

        # السعر فوق EMA200
        if current_close <= ema15:
            return False

        if close1h[-2] <= ema1h:
            return False

        # اختراق أعلى 20 شمعة سابقة
        resistance = max(
            highs[-22:-2]
        )

        if current_close <= resistance:
            return False

        # الحجم
        avg_volume = (
            sum(volumes[-22:-2])
            / D(20)
        )

        current_volume = volumes[-2]

        if avg_volume <= 0:
            return False

        if current_volume < (
            avg_volume * VOLUME_MULTIPLIER
        ):
            return False

        # حركة السعر
        previous_close = close15[-3]

        if previous_close <= 0:
            return False

        move = (
            current_close - previous_close
        ) / previous_close

        if move < MIN_MOVE:
            return False

        if move > MAX_MOVE:
            return False

        # =====================================
        # فلتر حركة الشموع
        # =====================================

        current_high = highs[-2]
        current_low = lows[-2]

        if current_low <= 0:
            return False

        current_range = (
            current_high - current_low
        ) / current_low

        if current_range < MIN_CURRENT_RANGE:
            return False

        ranges = []

        for i in range(-22, -2):
            low = lows[i]
            high = highs[i]

            if low > 0:
                ranges.append(
                    (high - low) / low
                )

        if not ranges:
            return False

        avg_range = (
            sum(ranges)
            / D(len(ranges))
        )

        if avg_range < MIN_AVG_RANGE:
            return False

        five_high = max(
            highs[-7:-2]
        )

        five_low = min(
            lows[-7:-2]
        )

        if five_low <= 0:
            return False

        five_range = (
            five_high - five_low
        ) / five_low

        if five_range < MIN_5CANDLE_RANGE:
            return False

        return True

    except Exception as e:
        print(
            f"⚠️ خطأ فحص {symbol}: {e}"
        )
        return False


# =============================================
# شراء
# =============================================

def buy(symbol, info):

    free_usdt = get_free_usdt()

    if free_usdt < TRADE_USDT:
        print(
            f"❌ رصيد USDT غير كافي: "
            f"{free_usdt}"
        )
        return None

    amount = min(
        TRADE_USDT,
        free_usdt * D("0.999")
    )

    if amount <= 0:
        return None

    print(
        f"🟢 شراء {symbol} "
        f"بقيمة {amount} USDT"
    )

    data = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": dec_str(amount)
        }
    )

    if not data or "orderId" not in data:
        print("❌ فشل الشراء")
        return None

    time.sleep(1)

    price = get_price(symbol)

    if not price:
        print("❌ تعذر الحصول على سعر الدخول")
        return None

    qty = get_free_asset(
        info["base"]
    )

    qty = floor_step(
        qty,
        info["step"]
    )

    if qty <= 0:
        print("❌ الكمية بعد العمولة صفر")
        return None

    print(
        f"💰 Entry: {price}"
    )

    return {
        "symbol": symbol,
        "entry": price,
        "qty": qty
    }


# =============================================
# الكمية الفعلية
# =============================================

def real_sell_qty(symbol, info):

    qty = get_free_asset(
        info["base"]
    )

    qty = floor_step(
        qty,
        info["step"]
    )

    if qty < info["min_qty"]:
        return Decimal("0")

    return qty


# =============================================
# وقف الخسارة
# =============================================

def put_stop(symbol, entry, info):

    qty = real_sell_qty(
        symbol,
        info
    )

    if qty <= 0:
        print("❌ كمية البيع غير صالحة")
        return None

    stop_price = entry * (
        D("1") - STOP_LOSS_PCT
    )

    stop_price = floor_step(
        stop_price,
        info["tick"]
    )

    if (
        info["min_notional"] > 0
        and qty * stop_price
        < info["min_notional"]
    ):
        print(
            "❌ قيمة الوقف أقل من MIN_NOTIONAL"
        )
        return None

    print(
        f"🛑 وضع وقف حقيقي Binance: "
        f"{stop_price}"
    )

    data = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": dec_str(qty),
            "stopPrice": dec_str(stop_price)
        }
    )

    if not data or "orderId" not in data:
        print("❌ فشل وضع وقف الخسارة")
        return None

    print(
        f"✅ تم وضع الوقف: "
        f"{stop_price}"
    )

    return {
        "order_id": data["orderId"],
        "stop_price": stop_price
    }


# =============================================
# إلغاء أمر حماية
# =============================================

def cancel_order(symbol, order_id):

    data = signed_request(
        "DELETE",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )

    if data and data.get("orderId"):
        return True

    return False


# =============================================
# التحقق من الأمر
# =============================================

def get_order(symbol, order_id):

    return signed_request(
        "GET",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


# =============================================
# وضع وقف ربح
# =============================================

def put_profit_stop(
    symbol,
    entry,
    current_price,
    info,
    old_order_id
):

    qty = real_sell_qty(
        symbol,
        info
    )

    if qty <= 0:
        print("❌ كمية وقف الربح غير صالحة")
        return None

    # أول حماية:
    # فوق الدخول بنسبة 0.2%
    lock_price = entry * (
        D("1") + PROFIT_LOCK
    )

    # وقف متحرك تحت السعر الحالي
    trailing_price = current_price * (
        D("1") - TRAIL_DISTANCE
    )

    # نستخدم الأعلى حتى لا ننزل الحماية
    new_stop = max(
        lock_price,
        trailing_price
    )

    new_stop = floor_step(
        new_stop,
        info["tick"]
    )

    # لازم الوقف يكون تحت السعر الحالي
    if new_stop >= current_price:
        new_stop = floor_step(
            current_price * D("0.998"),
            info["tick"]
        )

    if new_stop <= entry:
        new_stop = floor_step(
            lock_price,
            info["tick"]
        )

    if (
        info["min_notional"] > 0
        and qty * new_stop
        < info["min_notional"]
    ):
        print(
            "❌ قيمة وقف الربح أقل من MIN_NOTIONAL"
        )
        return None

    print(
        f"🔒 وضع وقف ربح حقيقي: "
        f"{new_stop}"
    )

    # =====================================
    # مهم:
    # نضع الجديد أولًا
    # ثم نحذف القديم
    # حتى لا تكون هناك فجوة حماية
    # =====================================

    data = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": dec_str(qty),
            "stopPrice": dec_str(new_stop)
        }
    )

    if not data or "orderId" not in data:
        print(
            "🚨 فشل وضع وقف الربح"
        )
        print(
            "🛡️ الوقف القديم ما زال موجودًا"
        )
        return None

    new_order_id = data["orderId"]

    print(
        f"✅ تم وضع وقف الربح: "
        f"{new_stop}"
    )

    # الآن فقط نحاول حذف الوقف القديم
    if old_order_id:

        if cancel_order(
            symbol,
            old_order_id
        ):
            print(
                "✅ تم إلغاء الوقف القديم"
            )
        else:
            print(
                "⚠️ تعذر إلغاء الوقف القديم"
            )

    return {
        "order_id": new_order_id,
        "stop_price": new_stop
    }


# =============================================
# بيع طارئ
# =============================================

def emergency_sell(symbol, info):

    print(
        "🚨 حماية طارئة: بيع الصفقة"
    )

    qty = real_sell_qty(
        symbol,
        info
    )

    if qty <= 0:
        print(
            "❌ لا توجد كمية للبيع"
        )
        return False

    data = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": dec_str(qty)
        }
    )

    if data and data.get("orderId"):
        print(
            "✅ تم البيع الطارئ"
        )
        return True

    print(
        "🚨 فشل البيع الطارئ"
    )
    return False


# =============================================
# إدارة الصفقة
# =============================================

def manage_position(state, info):

    symbol = state["symbol"]
    entry = D(state["entry"])

    while True:

        price = get_price(symbol)

        if not price:
            time.sleep(CHECK_SECONDS)
            continue

        # صافي تقريبي بعد رسوم دخول وخروج
        net = (
            (price - entry)
            / entry
        ) - D("0.002")

        print(
            f"📊 {symbol} | السعر: "
            f"{price} | الصافي: "
            f"{net * 100:.2f}%"
        )

        # =====================================
        # هل الصفقة انتهت؟
        # =====================================

        order = get_order(
            symbol,
            state["stop_order_id"]
        )

        if order:

            status = order.get(
                "status"
            )

            if status == "FILLED":

                print(
                    "🛑 تم تنفيذ وقف الحماية على Binance"
                )

                clear_state()

                return True

            if status in (
                "CANCELED",
                "REJECTED",
                "EXPIRED"
            ):

                print(
                    "⚠️ أمر الحماية اختفى!"
                )

                # إذا كان عندنا وقف جديد لا نعرفه
                # نحاول حماية الصفقة من جديد
                new_stop = put_stop(
                    symbol,
                    entry,
                    info
                )

                if not new_stop:

                    if emergency_sell(
                        symbol,
                        info
                    ):
                        clear_state()
                        return True

                    print(
                        "🚨 توقيف البوت لحماية الحساب"
                    )
                    return False

                state["stop_order_id"] = (
                    new_stop["order_id"]
                )

                state["stop_price"] = str(
                    new_stop["stop_price"]
                )

                save_state(state)

        # =====================================
        # تفعيل حماية الربح
        # =====================================

        if not state.get("profit_mode", False):

            if net >= PROFIT_ACTIVATE:

                print(
                    "🎯 وصل هدف +1.2% الصافي تقريباً"
                )

                new_stop = put_profit_stop(
                    symbol,
                    entry,
                    price,
                    info,
                    state["stop_order_id"]
                )

                if new_stop:

                    state["profit_mode"] = True

                    state["stop_order_id"] = (
                        new_stop["order_id"]
                    )

                    state["stop_price"] = str(
                        new_stop["stop_price"]
                    )

                    state["highest_price"] = str(
                        price
                    )

                    save_state(state)

                    print(
                        "🔒 تم تفعيل حماية الربح"
                    )

                else:

                    print(
                        "🛡️ بقي وقف -2% كما هو"
                    )

        # =====================================
        # وضع الربح المتحرك
        # =====================================

        else:

            highest = D(
                state.get(
                    "highest_price",
                    str(price)
                )
            )

            if price > highest:

                state["highest_price"] = str(
                    price
                )

                save_state(state)

                # وقف جديد أعلى من السابق
                current_stop = D(
                    state.get(
                        "stop_price",
                        "0"
                    )
                )

                proposed_stop = price * (
                    D("1") - TRAIL_DISTANCE
                )

                lock_price = entry * (
                    D("1") + PROFIT_LOCK
                )

                proposed_stop = max(
                    proposed_stop,
                    lock_price
                )

                proposed_stop = floor_step(
                    proposed_stop,
                    info["tick"]
                )

                # لا ننزل الوقف أبدًا
                if proposed_stop > current_stop:

                    print(
                        f"📈 رفع وقف الربح: "
                        f"{current_stop} → "
                        f"{proposed_stop}"
                    )

                    qty = real_sell_qty(
                        symbol,
                        info
                    )

                    if qty > 0:

                        # الجديد أولًا
                        data = signed_request(
                            "POST",
                            "/api/v3/order",
                            {
                                "symbol": symbol,
                                "side": "SELL",
                                "type": "STOP_LOSS",
                                "quantity": dec_str(qty),
                                "stopPrice": dec_str(
                                    proposed_stop
                                )
                            }
                        )

                        if data and data.get(
                            "orderId"
                        ):

                            new_id = data[
                                "orderId"
                            ]

                            # بعد نجاح الجديد
                            # نحذف القديم
                            old_id = state[
                                "stop_order_id"
                            ]

                            if cancel_order(
                                symbol,
                                old_id
                            ):

                                print(
                                    "✅ تم رفع وقف الربح"
                                )

                            else:

                                print(
                                    "⚠️ الجديد موجود، "
                                    "تعذر إلغاء القديم"
                                )

                            state[
                                "stop_order_id"
                            ] = new_id

                            state[
                                "stop_price"
                            ] = str(
                                proposed_stop
                            )

                            save_state(state)

                        else:

                            print(
                                "⚠️ فشل رفع وقف الربح"
                            )
                            print(
                                "🛡️ الوقف السابق باقي"
                            )

        time.sleep(CHECK_SECONDS)


# =============================================
# تشغيل البوت
# =============================================

def main():

    print(
        "\n===================================="
    )
    print(
        "🤖 مضارب أبو سعود V5"
    )
    print(
        "🟢 BINANCE SPOT"
    )
    print(
        "🔒 وقف خسارة + حماية ربح حقيقية"
    )
    print(
        "====================================\n"
    )

    if not API_KEY or not API_SECRET:
        print(
            "❌ مفاتيح Binance غير موجودة في المتغيرات"
        )
        return

    sync_time()

    if not get_symbols():
        print(
            "❌ فشل تحميل العملات"
        )
        return

    # =========================================
    # استئناف صفقة سابقة
    # =========================================

    state = load_state()

    if state:

        symbol = state["symbol"]

        if symbol in SYMBOL_INFO:

            print(
                f"🔄 استئناف الصفقة: "
                f"{symbol}"
            )

            manage_position(
                state,
                SYMBOL_INFO[symbol]
            )

        else:

            print(
                "⚠️ العملة غير متاحة"
            )

            clear_state()

    # =========================================
    # الفحص المستمر
    # =========================================

    while True:

        try:

            # إذا توجد صفقة أثناء التشغيل
            current_state = load_state()

            if current_state:

                symbol = current_state[
                    "symbol"
                ]

                if symbol in SYMBOL_INFO:

                    manage_position(
                        current_state,
                        SYMBOL_INFO[symbol]
                    )

                    continue

                else:

                    clear_state()

            print(
                "\n🔎 بدء فحص العملات..."
            )

            for symbol, info in SYMBOL_INFO.items():

                # نتأكد ما فيه صفقة جديدة
                if load_state():
                    break

                if not symbol.endswith(
                    "USDT"
                ):
                    continue

                if symbol in (
                    "USDCUSDT",
                    "FDUSDUSDT",
                    "TUSDUSDT",
                    "USDPUSDT"
                ):
                    continue

                if signal(symbol):

                    print(
                        f"\n🚨 إشارة قوية: "
                        f"{symbol}"
                    )

                    position = buy(
                        symbol,
                        info
                    )

                    if not position:
                        continue

                    # =================================
                    # وضع الوقف مباشرة بعد الشراء
                    # =================================

                    stop = put_stop(
                        symbol,
                        position["entry"],
                        info
                    )

                    if not stop:

                        print(
                            "🚨 لم يتم وضع الوقف!"
                        )

                        if emergency_sell(
                            symbol,
                            info
                        ):

                            print(
                                "✅ تم إغلاق الصفقة "
                                "احتياطيًا"
                            )
                            continue

                        print(
                            "🚨 فشل البيع الطارئ"
                        )
                        print(
                            "🚨 تم إيقاف البوت"
                        )
                        return

                    # =================================
                    # حفظ الصفقة
                    # =================================

                    state = {
                        "symbol": symbol,
                        "entry": str(
                            position["entry"]
                        ),
                        "qty": str(
                            position["qty"]
                        ),
                        "stop_order_id": stop[
                            "order_id"
                        ],
                        "stop_price": str(
                            stop["stop_price"]
                        ),
                        "profit_mode": False,
                        "highest_price": str(
                            position["entry"]
                        )
                    }

                    save_state(state)

                    print(
                        "🛡️ الحماية مفعلة على Binance"
                    )

                    # إدارة الصفقة
                    manage_position(
                        state,
                        info
                    )

                    # بعد إغلاق الصفقة
                    # يرجع للفحص من جديد
                    clear_state()

                    print(
                        "\n🔄 الصفقة انتهت — "
                        "إعادة فحص العملات..."
                    )

                    break

            time.sleep(3)

        except KeyboardInterrupt:

            print(
                "\n🛑 تم إيقاف البوت يدويًا"
            )
            return

        except Exception as e:

            print(
                f"⚠️ خطأ عام: {e}"
            )

            time.sleep(5)


if __name__ == "__main__":
    main()
