import os
import time
import hmac
import hashlib
import urllib.parse
import json
import math
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 🤖 مضارب أبو سعود V2
# Binance Spot
#
# استراتيجية الدخول:
# 15m + 1h
# EMA200
# Breakout آخر 20 شمعة
# Volume >= 1.5x
# الحركة 0.5% إلى 4%
#
# إدارة الصفقة:
# وقف أولي -2%
# كل +1% صافي = رفع الوقف لتأمين الربح
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "❌ ضع BINANCE_API_KEY و BINANCE_API_SECRET داخل ملف .env"
    )

# ============================================================
# مهم:
# MARKET_BASE للبيانات العامة فقط
# API_BASE للحساب والأوامر
# لا تخلط بينهم
# ============================================================

API_BASE = "https://api.binance.com"
MARKET_BASE = "https://data-api.binance.vision"

# ============================================================
# الملفات
# ============================================================

STATE_FILE = os.path.expanduser("~/mybot/state.json")
HISTORY_FILE = os.path.expanduser("~/mybot/trade_history.json")

# ============================================================
# الإعدادات
# ============================================================

INITIAL_STOP = -0.02       # وقف -2%
PROFIT_STEP = 0.01         # كل +1%
FEE_RATE = 0.001           # تقدير رسوم 0.1%

MIN_USDT = 5.0

# عدد شموع التحليل
KLINE_LIMIT = 210

# الفحص الكامل كل 3 دقائق
# بدلاً من كل 5 ثواني
SCAN_INTERVAL = 180

# مراقبة الصفقة كل 5 ثواني
POSITION_CHECK_SECONDS = 5

# فاصل صغير بين طلبات السوق
REQUEST_GAP = 0.10

session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY,
    "User-Agent": "Mudarib-Abo-Saud-V2"
})

symbol_cache = {}


# ============================================================
# الملفات
# ============================================================

def ensure_files():

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    if not os.path.exists(STATE_FILE):
        save_json(
            STATE_FILE,
            {}
        )

    if not os.path.exists(HISTORY_FILE):
        save_json(
            HISTORY_FILE,
            []
        )


def load_json(path, default):

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(path, data):

    tmp = path + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        tmp,
        path
    )


def load_state():

    return load_json(
        STATE_FILE,
        {}
    )


def save_state(state):

    save_json(
        STATE_FILE,
        state
    )


def add_history(item):

    history = load_json(
        HISTORY_FILE,
        []
    )

    history.append(item)

    save_json(
        HISTORY_FILE,
        history
    )


# ============================================================
# بيانات السوق العامة
# ============================================================

def market_get(path, params=None):

    backoff = 10

    while True:

        try:

            response = session.get(
                MARKET_BASE + path,
                params=params,
                timeout=15
            )

            # 429
            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                try:

                    wait = int(
                        float(retry_after)
                    )

                except Exception:

                    wait = backoff

                wait = max(
                    wait,
                    10
                )

                print(
                    f"\n⏳ Binance 429 "
                    f"انتظار {wait} ثانية..."
                )

                time.sleep(
                    wait
                )

                backoff = min(
                    backoff * 2,
                    120
                )

                continue

            # 418
            if response.status_code == 418:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                try:

                    wait = int(
                        float(retry_after)
                    )

                except Exception:

                    wait = 180

                wait = max(
                    wait,
                    60
                )

                print(
                    f"\n🚫 Binance حظر IP مؤقتاً"
                    f" | انتظار {wait} ثانية..."
                )

                time.sleep(
                    wait
                )

                continue

            response.raise_for_status()

            backoff = 10

            return response.json()

        except requests.exceptions.RequestException as e:

            print(
                f"\n⚠️ اتصال بيانات السوق: {e}"
            )

            time.sleep(
                10
            )


# ============================================================
# API الحساب والأوامر
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    params = dict(
        params or {}
    )

    params["timestamp"] = int(
        time.time() * 1000
    )

    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url = (
        API_BASE
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    while True:

        try:

            if method == "GET":

                response = session.get(
                    url,
                    timeout=15
                )

            elif method == "POST":

                response = session.post(
                    url,
                    timeout=15
                )

            elif method == "DELETE":

                response = session.delete(
                    url,
                    timeout=15
                )

            else:

                raise ValueError(
                    "HTTP method غير صحيح"
                )

            # 429
            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                try:

                    wait = int(
                        float(retry_after)
                    )

                except Exception:

                    wait = 30

                wait = max(
                    wait,
                    10
                )

                print(
                    f"\n⏳ Binance API 429 "
                    f"| انتظار {wait} ثانية..."
                )

                time.sleep(
                    wait
                )

                continue

            # 418
            if response.status_code == 418:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                try:

                    wait = int(
                        float(retry_after)
                    )

                except Exception:

                    wait = 180

                wait = max(
                    wait,
                    60
                )

                print(
                    f"\n🚫 Binance حظر IP "
                    f"| انتظار {wait} ثانية..."
                )

                time.sleep(
                    wait
                )

                continue

            if not response.ok:

                try:

                    error = response.json()

                except Exception:

                    error = response.text

                raise RuntimeError(
                    f"Binance {response.status_code}: "
                    f"{error}"
                )

            return response.json()

        except requests.exceptions.RequestException as e:

            print(
                f"\n⚠️ اتصال Binance: {e}"
            )

            time.sleep(
                10
            )


# ============================================================
# معلومات العملات
# ============================================================

def get_exchange_info():

    return market_get(
        "/api/v3/exchangeInfo"
    )


def get_symbols():

    global symbol_cache

    if symbol_cache:

        return symbol_cache

    print(
        "\n📡 تحميل قائمة العملات..."
    )

    info = get_exchange_info()

    for item in info.get(
        "symbols",
        []
    ):

        symbol = item["symbol"]

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if not item.get(
            "isSpotTradingAllowed",
            True
        ):
            continue

        lot = None
        price_filter = None

        for f in item.get(
            "filters",
            []
        ):

            if f["filterType"] == "LOT_SIZE":

                lot = f

            elif f["filterType"] == "PRICE_FILTER":

                price_filter = f

        if not lot or not price_filter:
            continue

        symbol_cache[symbol] = {

            "stepSize": lot["stepSize"],

            "minQty": lot["minQty"],

            "tickSize": price_filter["tickSize"],

            "minPrice": price_filter["minPrice"]
        }

    print(
        f"📊 العملات: {len(symbol_cache)}"
    )

    return symbol_cache


# ============================================================
# التقريب
# ============================================================

def floor_step(
    value,
    step
):

    value = Decimal(
        str(value)
    )

    step = Decimal(
        str(step)
    )

    if step <= 0:

        return float(value)

    result = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return float(
        result
    )


def round_qty(
    symbol,
    qty
):

    return floor_step(
        qty,
        symbol_cache[symbol]["stepSize"]
    )


def round_price(
    symbol,
    price
):

    return floor_step(
        price,
        symbol_cache[symbol]["tickSize"]
    )


# ============================================================
# الشموع
# ============================================================

def get_klines(
    symbol,
    interval
):

    time.sleep(
        REQUEST_GAP
    )

    return market_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": KLINE_LIMIT
        }
    )


# ============================================================
# السعر
# ============================================================

def get_price(symbol):

    data = market_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if len(values) < period:

        return None

    multiplier = (
        2 / (period + 1)
    )

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            price - value
        ) * multiplier + value

    return value


# ============================================================
# فحص الإشارة
# ============================================================

def check_signal(symbol):

    try:

        k15 = get_klines(
            symbol,
            "15m"
        )

        k1h = get_klines(
            symbol,
            "1h"
        )

        if (
            len(k15) < 205
            or len(k1h) < 205
        ):

            return None

        close15 = [
            float(x[4])
            for x in k15
        ]

        high15 = [
            float(x[2])
            for x in k15
        ]

        volume15 = [
            float(x[5])
            for x in k15
        ]

        close1h = [
            float(x[4])
            for x in k1h
        ]

        ema200_15 = ema(
            close15,
            200
        )

        ema200_1h = ema(
            close1h,
            200
        )

        if (
            ema200_15 is None
            or ema200_1h is None
        ):

            return None

        current = close15[-1]

        previous_close = close15[-2]

        # أعلى 20 شمعة قبل الحالية
        resistance = max(
            high15[-21:-1]
        )

        average_volume = (
            sum(
                volume15[-21:-1]
            ) / 20
        )

        current_volume = volume15[-1]

        if previous_close <= 0:

            return None

        move_pct = (
            current
            / previous_close
            - 1
        ) * 100

        # ====================================================
        # شروط V2
        # ====================================================

        condition_1 = (
            current > ema200_15
        )

        condition_2 = (
            close1h[-1] > ema200_1h
        )

        condition_3 = (
            current > resistance
        )

        condition_4 = (
            current_volume
            >= average_volume * 1.5
        )

        condition_5 = (
            0.5
            <= move_pct
            <= 4.0
        )

        if (
            condition_1
            and condition_2
            and condition_3
            and condition_4
            and condition_5
        ):

            return {

                "symbol": symbol,

                "price": current,

                "move_pct": move_pct,

                "resistance": resistance,

                "volume_ratio":
                    current_volume
                    / average_volume,

                "ema200_15":
                    ema200_15,

                "ema200_1h":
                    ema200_1h,

                "score": 5
            }

    except Exception as e:

        # لا نخلي عملة واحدة توقف الفحص
        print(
            f"\n⚠️ {symbol}: {e}"
        )

    return None


# ============================================================
# فحص السوق
# ============================================================

def scan_market():

    symbols = list(
        get_symbols().keys()
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        f"🔎 فحص السوق"
    )

    print(
        f"📊 عدد العملات: {len(symbols)}"
    )

    print(
        "⏱️ 15m + 1h"
    )

    print(
        "=" * 60
    )

    best = None

    checked = 0

    for symbol in symbols:

        checked += 1

        signal = check_signal(
            symbol
        )

        if signal:

            print(
                "\n🔥🔥 إشارة V2"
            )

            print(
                f"💰 {symbol}"
            )

            print(
                f"السعر: "
                f"{signal['price']:.8f}"
            )

            print(
                f"الحركة: "
                f"{signal['move_pct']:+.2f}%"
            )

            print(
                f"الحجم: "
                f"x{signal['volume_ratio']:.2f}"
            )

            if best is None:

                best = signal

        if checked % 25 == 0:

            print(
                f"\r📡 فحص "
                f"{checked}/{len(symbols)}",
                end="",
                flush=True
            )

    print(
        "\n\n✅ انتهى الفحص"
    )

    if best:

        print(
            f"🔥 أفضل إشارة: "
            f"{best['symbol']}"
        )

    else:

        print(
            "😴 لا توجد إشارة مطابقة"
        )

    return best


# ============================================================
# الحساب
# ============================================================

def account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_free_balance(asset):

    data = account()

    for balance in data.get(
        "balances",
        []
    ):

        if balance["asset"] == asset:

            return float(
                balance["free"]
            )

    return 0.0


def get_usdt_balance():

    return get_free_balance(
        "USDT"
    )


# ============================================================
# شراء MARKET
# ============================================================

def market_buy(
    symbol,
    usdt_amount
):

    balance = get_usdt_balance()

    usdt_amount = min(
        usdt_amount,
        balance * 0.999
    )

    if usdt_amount < MIN_USDT:

        raise RuntimeError(
            f"رصيد USDT غير كافي: "
            f"{balance:.4f}"
        )

    print(
        "\n"
        + "=" * 60
    )

    print(
        f"🟢 شراء MARKET"
    )

    print(
        f"💰 العملة: {symbol}"
    )

    print(
        f"💵 المبلغ: "
        f"{usdt_amount:.2f} USDT"
    )

    print(
        "=" * 60
    )

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,

            "side": "BUY",

            "type": "MARKET",

            "quoteOrderQty":
                f"{usdt_amount:.2f}",

            "newOrderRespType":
                "FULL"
        }
    )

    if not result.get(
        "orderId"
    ):

        raise RuntimeError(
            f"فشل أمر الشراء: "
            f"{result}"
        )

    fills = result.get(
        "fills",
        []
    )

    if fills:

        total_qty = sum(
            float(x["qty"])
            for x in fills
        )

        total_quote = sum(
            float(x["qty"])
            * float(x["price"])
            for x in fills
        )

        entry = (
            total_quote
            / total_qty
        )

    else:

        total_qty = float(
            result.get(
                "executedQty",
                0
            )
        )

        total_quote = float(
            result.get(
                "cummulativeQuoteQty",
                0
            )
        )

        if total_qty > 0:

            entry = (
                total_quote
                / total_qty
            )

        else:

            entry = get_price(
                symbol
            )

    print(
        f"✅ تم الشراء"
    )

    print(
        f"Entry: {entry:.8f}"
    )

    print(
        f"Qty: {total_qty}"
    )

    print(
        f"Order ID: "
        f"{result['orderId']}"
    )

    return {

        "orderId":
            result["orderId"],

        "symbol":
            symbol,

        "qty":
            total_qty,

        "entry":
            entry,

        "quote":
            total_quote
    }


# ============================================================
# وضع STOP_LOSS
# ============================================================

def place_stop(
    symbol,
    qty,
    stop_price
):

    qty = round_qty(
        symbol,
        qty
    )

    stop_price = round_price(
        symbol,
        stop_price
    )

    if qty <= 0:

        raise RuntimeError(
            f"الكمية غير صالحة: {qty}"
        )

    if stop_price <= 0:

        raise RuntimeError(
            f"سعر الوقف غير صالح: "
            f"{stop_price}"
        )

    print(
        f"\n🛡️ إرسال STOP_LOSS"
    )

    print(
        f"العملة: {symbol}"
    )

    print(
        f"الكمية: {qty}"
    )

    print(
        f"Stop: {stop_price}"
    )

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol":
                symbol,

            "side":
                "SELL",

            "type":
                "STOP_LOSS",

            "quantity":
                f"{qty:.16f}".rstrip(
                    "0"
                ).rstrip("."),

            "stopPrice":
                f"{stop_price:.16f}".rstrip(
                    "0"
                ).rstrip("."),

            "newOrderRespType":
                "RESULT"
        }
    )

    if not result.get(
        "orderId"
    ):

        raise RuntimeError(
            f"Binance لم يرجع orderId: "
            f"{result}"
        )

    print(
        f"✅ STOP_LOSS فعّال"
    )

    print(
        f"🆔 orderId: "
        f"{result['orderId']}"
    )

    print(
        f"📌 status: "
        f"{result.get('status')}"
    )

    return result


# ============================================================
# إلغاء أمر
# ============================================================

def cancel_order(
    symbol,
    order_id
):

    if not order_id:

        return None

    try:

        result = signed_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol":
                    symbol,

                "orderId":
                    order_id
            }
        )

        print(
            f"🗑️ إلغاء الوقف القديم "
            f"{order_id}"
        )

        return result

    except Exception as e:

        print(
            f"⚠️ تعذر إلغاء الوقف: "
            f"{e}"
        )

        return None


# ============================================================
# فحص الأمر
# ============================================================

def query_order(
    symbol,
    order_id
):

    return signed_request(
        "GET",
        "/api/v3/order",
        {
            "symbol":
                symbol,

            "orderId":
                order_id
        }
    )


# ============================================================
# حساب الربح الصافي
# ============================================================

def net_profit_pct(
    entry,
    current
):

    gross = (
        current
        / entry
    ) - 1

    net = (
        (1 + gross)
        * (1 - FEE_RATE)
        * (1 - FEE_RATE)
    ) - 1

    return net


def gross_price_for_net(
    entry,
    net_pct
):

    return (
        entry
        * (1 + net_pct)
        / (1 - FEE_RATE)
    )


def profit_usdt(
    entry,
    current,
    qty
):

    return (
        qty
        * entry
        * net_profit_pct(
            entry,
            current
        )
    )


# ============================================================
# إغلاق وتسجيل الصفقة
# ============================================================

def close_trade(
    state,
    exit_price,
    reason
):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    qty = float(
        state["qty"]
    )

    net_pct = net_profit_pct(
        entry,
        exit_price
    )

    pnl = profit_usdt(
        entry,
        exit_price,
        qty
    )

    trade = {

        "symbol":
            symbol,

        "entry":
            entry,

        "exit":
            exit_price,

        "qty":
            qty,

        "net_pct":
            net_pct * 100,

        "pnl_usdt":
            pnl,

        "reason":
            reason,

        "time":
            int(time.time())
    }

    add_history(
        trade
    )

    print(
        "\n\n"
        + "=" * 60
    )

    print(
        "🏁 انتهت الصفقة"
    )

    print(
        f"💰 {symbol}"
    )

    print(
        f"Entry: {entry:.8f}"
    )

    print(
        f"Exit: {exit_price:.8f}"
    )

    print(
        f"📈 الصافي: "
        f"{net_pct * 100:+.2f}%"
    )

    print(
        f"💵 P/L: "
        f"{pnl:+.4f} USDT"
    )

    print(
        f"السبب: {reason}"
    )

    print(
        "=" * 60
    )

    save_state({})


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position(state):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    qty = float(
        state["qty"]
    )

    stop_order_id = state.get(
        "stop_order_id"
    )

    locked_level = int(
        state.get(
            "locked_level",
            -2
        )
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        f"📌 إدارة الصفقة: "
        f"{symbol}"
    )

    print(
        f"Entry: {entry:.8f}"
    )

    print(
        "=" * 60
    )

    # التأكد من الكمية الحقيقية
    asset = symbol.replace(
        "USDT",
        ""
    )

    try:

        real_qty = get_free_balance(
            asset
        )

        if real_qty > 0:

            qty = min(
                qty,
                real_qty
            )

    except Exception as e:

        print(
            f"⚠️ تعذر تحديث الكمية: "
            f"{e}"
        )

    while True:

        try:

            # ==================================================
            # فحص الوقف
            # ==================================================

            if stop_order_id:

                try:

                    order = query_order(
                        symbol,
                        stop_order_id
                    )

                    status = order.get(
                        "status"
                    )

                    if status == "FILLED":

                        exit_price = float(
                            order.get(
                                "price",
                                0
                            )
                        )

                        if exit_price <= 0:

                            exit_price = get_price(
                                symbol
                            )

                        close_trade(
                            state,
                            exit_price,
                            "STOP_FILLED"
                        )

                        return

                    if status in (
                        "CANCELED",
                        "EXPIRED",
                        "REJECTED"
                    ):

                        print(
                            f"\n⚠️ الوقف أصبح "
                            f"{status}"
                        )

                        stop_order_id = None

                        state[
                            "stop_order_id"
                        ] = None

                        save_state(
                            state
                        )

                except Exception as e:

                    print(
                        f"\n⚠️ فحص الوقف: "
                        f"{e}"
                    )

            # ==================================================
            # السعر الحالي
            # ==================================================

            current = get_price(
                symbol
            )

            net_pct = net_profit_pct(
                entry,
                current
            )

            pnl = profit_usdt(
                entry,
                current,
                qty
            )

            print(
                f"\r📊 {symbol} | "
                f"السعر {current:.8f} | "
                f"الصافي {net_pct * 100:+.2f}% | "
                f"P/L {pnl:+.4f} USDT | "
                f"تأمين +{max(0, locked_level)}%",
                end="",
                flush=True
            )

            # ==================================================
            # تأمين الربح
            #
            # +1% -> وقف +1%
            # +2% -> وقف +2%
            # +3% -> وقف +3%
            # ...
            # ==================================================

            level = math.floor(
                net_pct * 100
            )

            if (
                level >= 1
                and level > locked_level
            ):

                new_stop_net = (
                    level / 100
                )

                new_stop = gross_price_for_net(
                    entry,
                    new_stop_net
                )

                # لا نضع الوقف فوق السعر الحالي
                if new_stop >= current:

                    new_stop = (
                        current
                        * 0.998
                    )

                new_stop = round_price(
                    symbol,
                    new_stop
                )

                print(
                    f"\n\n🔒 تأمين ربح "
                    f"+{level}%"
                )

                print(
                    f"🛡️ الوقف الجديد: "
                    f"{new_stop}"
                )

                new_order = None

                try:

                    # أولاً نضع الوقف الجديد
                    new_order = place_stop(
                        symbol,
                        qty,
                        new_stop
                    )

                    new_id = new_order[
                        "orderId"
                    ]

                    # التأكد أن الجديد موجود
                    check = query_order(
                        symbol,
                        new_id
                    )

                    if check.get(
                        "status"
                    ) not in (
                        "NEW",
                        "PARTIALLY_FILLED"
                    ):

                        raise RuntimeError(
                            f"الوقف الجديد ليس NEW: "
                            f"{check}"
                        )

                    old_id = stop_order_id

                    # بعدها نحذف القديم
                    if (
                        old_id
                        and old_id != new_id
                    ):

                        cancel_order(
                            symbol,
                            old_id
                        )

                    stop_order_id = new_id

                    locked_level = level

                    state[
                        "stop_order_id"
                    ] = stop_order_id

                    state[
                        "locked_level"
                    ] = locked_level

                    state[
                        "last_stop_price"
                    ] = new_stop

                    save_state(
                        state
                    )

                    print(
                        f"✅ تم تأمين +{level}%"
                    )

                except Exception as e:

                    print(
                        f"\n❌ فشل رفع الوقف: "
                        f"{e}"
                    )

                    # لو الوقف الجديد انحط فعلاً
                    # نخليه محفوظ
                    if (
                        new_order
                        and new_order.get(
                            "orderId"
                        )
                    ):

                        stop_order_id = (
                            new_order[
                                "orderId"
                            ]
                        )

                        state[
                            "stop_order_id"
                        ] = stop_order_id

                        save_state(
                            state
                        )

            # ==================================================
            # إذا ما فيه وقف
            # ==================================================

            if not stop_order_id:

                stop_price = gross_price_for_net(
                    entry,
                    INITIAL_STOP
                )

                # لازم الوقف يكون تحت السعر الحالي
                if stop_price >= current:

                    stop_price = (
                        current
                        * 0.995
                    )

                stop_price = round_price(
                    symbol,
                    stop_price
                )

                try:

                    order = place_stop(
                        symbol,
                        qty,
                        stop_price
                    )

                    stop_order_id = order[
                        "orderId"
                    ]

                    state[
                        "stop_order_id"
                    ] = stop_order_id

                    state[
                        "last_stop_price"
                    ] = stop_price

                    save_state(
                        state
                    )

                    print(
                        f"\n🛡️ تم وضع الوقف الأول "
                        f"{stop_price}"
                    )

                except Exception as e:

                    print(
                        f"\n❌ فشل وضع الوقف: "
                        f"{e}"
                    )

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except KeyboardInterrupt:

            print(
                "\n\n⏸️ تم إيقاف البوت يدوياً"
            )

            return

        except Exception as e:

            print(
                f"\n⚠️ إدارة الصفقة: "
                f"{e}"
            )

            time.sleep(
                10
            )


# ============================================================
# فتح صفقة
# ============================================================

def open_trade(signal):

    symbol = signal[
        "symbol"
    ]

    usdt = get_usdt_balance()

    if usdt < MIN_USDT:

        print(
            f"\n⚠️ الرصيد غير كافي: "
            f"{usdt:.4f} USDT"
        )

        return None

    # يستخدم تقريباً كامل الرصيد
    buy_amount = (
        usdt * 0.999
    )

    result = market_buy(
        symbol,
        buy_amount
    )

    state = {

        "symbol":
            symbol,

        "entry":
            result["entry"],

        "qty":
            result["qty"],

        "buy_order_id":
            result["orderId"],

        "stop_order_id":
            None,

        "locked_level":
            -2,

        "last_stop_price":
            None,

        "opened_at":
            int(time.time()),

        "strategy":
            "V2_15m_1h_EMA200_BREAKOUT20_VOLUME1.5"
    }

    save_state(
        state
    )

    return state


# ============================================================
# البرنامج الرئيسي
# ============================================================

def main():

    ensure_files()

    print(
        "\n"
        + "=" * 60
    )

    print(
        "🤖 مضارب أبو سعود V2"
    )

    print(
        "Binance Spot"
    )

    print(
        "15m + 1h"
    )

    print(
        "EMA200"
    )

    print(
        "Breakout 20"
    )

    print(
        "Volume 1.5x"
    )

    print(
        "STOP -2%"
    )

    print(
        "تأمين كل +1%"
    )

    print(
        "=" * 60
    )

    # تحميل العملات مرة واحدة
    get_symbols()

    # ========================================================
    # لو فيه صفقة محفوظة
    # ========================================================

    state = load_state()

    if (
        state.get("symbol")
        and state.get("entry")
    ):

        print(
            f"\n♻️ استعادة الصفقة:"
            f" {state['symbol']}"
        )

        manage_position(
            state
        )

    # ========================================================
    # الفحص المستمر
    # ========================================================

    last_scan = 0

    while True:

        try:

            state = load_state()

            # لا تفتح صفقة ثانية
            if (
                state.get("symbol")
                and state.get("entry")
            ):

                manage_position(
                    state
                )

                continue

            now = time.time()

            # الانتظار بين الفحوصات
            if (
                now - last_scan
                < SCAN_INTERVAL
            ):

                remaining = int(
                    SCAN_INTERVAL
                    - (
                        now
                        - last_scan
                    )
                )

                print(
                    f"\r⏳ الفحص القادم بعد "
                    f"{remaining} ثانية...",
                    end="",
                    flush=True
                )

                time.sleep(
                    5
                )

                continue

            last_scan = time.time()

            # =================================================
            # فحص السوق
            # =================================================

            signal = scan_market()

            if signal:

                print(
                    "\n🔥 دخول حسب استراتيجية V2"
                )

                print(
                    f"💰 {signal['symbol']}"
                )

                state = open_trade(
                    signal
                )

                if state:

                    manage_position(
                        state
                    )

            else:

                print(
                    "\n😴 لا توجد صفقة حالياً"
                )

        except KeyboardInterrupt:

            print(
                "\n\n🛑 تم إيقاف البوت"
            )

            break

        except Exception as e:

            print(
                f"\n\n⚠️ خطأ رئيسي: "
                f"{e}"
            )

            time.sleep(
                15
            )


# ============================================================
# تشغيل
# ============================================================

if __name__ == "__main__":

    main()
