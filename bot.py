import os
import time
import hmac
import hashlib
import urllib.parse
import json
import math
import requests

from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from dotenv import load_dotenv


# =========================================================
# مضارب أبو سعود V2 🤖
# Binance Spot
# 15m + 1h
# EMA200
# Breakout 20
# Volume 1.5x
# حركة 0.5% - 4%
# وقف -2%
# تأمين كل +1%
# =========================================================


load_dotenv()


# =========================================================
# API
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

API_BASE = "https://api.binance.com"

# بيانات السوق العامة
MARKET_BASE = "https://data-api.binance.vision"


# =========================================================
# ملفات
# =========================================================

BASE_DIR = os.path.expanduser("~/mybot")

os.makedirs(BASE_DIR, exist_ok=True)

STATE_FILE = os.path.join(
    BASE_DIR,
    "state.json"
)

HISTORY_FILE = os.path.join(
    BASE_DIR,
    "trade_history.json"
)


# =========================================================
# الإعدادات
# =========================================================

INITIAL_STOP = -0.02

PROFIT_STEP = 0.01

# تقدير رسوم الشراء والبيع
FEE_RATE = 0.001

# أقل مبلغ
MIN_USDT = 5.0

# عدد الشموع
KLINE_LIMIT = 210

# كل كم ثانية يبحث عن صفقة جديدة
SCAN_INTERVAL = 180

# كل كم ثانية يدير الصفقة المفتوحة
POSITION_CHECK_SECONDS = 5

# تأخير بسيط بين طلبات السوق
REQUEST_GAP = 0.08

# Retry
MAX_RETRIES = 6


# =========================================================
# Session
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-V2/2.0"
})


# =========================================================
# متغيرات
# =========================================================

SYMBOL_INFO = {}

LAST_MARKET_REQUEST = 0

SERVER_TIME_OFFSET = 0


# =========================================================
# طباعة
# =========================================================

def log(text):

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[{now}] {text}",
        flush=True
    )


# =========================================================
# JSON
# =========================================================

def load_json(path, default):

    try:

        if not os.path.exists(path):
            return default

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        log(
            f"⚠️ قراءة JSON: {e}"
        )

        return default


def save_json(path, data):

    temp = path + ".tmp"

    try:

        with open(
            temp,
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
            temp,
            path
        )

    except Exception as e:

        log(
            f"⚠️ حفظ JSON: {e}"
        )


def load_state():

    data = load_json(
        STATE_FILE,
        {}
    )

    if not isinstance(data, dict):
        return {}

    return data


def save_state(state):

    save_json(
        STATE_FILE,
        state
    )


def clear_state():

    try:

        if os.path.exists(
            STATE_FILE
        ):

            os.remove(
                STATE_FILE
            )

    except Exception as e:

        log(
            f"⚠️ حذف الحالة: {e}"
        )


def load_history():

    data = load_json(
        HISTORY_FILE,
        []
    )

    if isinstance(data, dict):

        data = (
            data.get("trades")
            or
            data.get("history")
            or
            []
        )

    if not isinstance(data, list):
        data = []

    return data


def save_history(history):

    save_json(
        HISTORY_FILE,
        history[-500:]
    )


# =========================================================
# Decimal helpers
# =========================================================

def dec(value):

    return Decimal(
        str(value)
    )


def floor_step(value, step):

    value = dec(value)
    step = dec(step)

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def decimal_string(value):

    text = format(
        dec(value),
        "f"
    )

    text = text.rstrip("0").rstrip(".")

    if text == "":
        return "0"

    return text


# =========================================================
# Binance timestamp
# =========================================================

def sync_server_time():

    global SERVER_TIME_OFFSET

    try:

        response = session.get(
            f"{API_BASE}/api/v3/time",
            timeout=10
        )

        response.raise_for_status()

        server_time = int(
            response.json()["serverTime"]
        )

        local_time = int(
            time.time() * 1000
        )

        SERVER_TIME_OFFSET = (
            server_time -
            local_time
        )

        log(
            f"🕐 فرق وقت Binance: "
            f"{SERVER_TIME_OFFSET} ms"
        )

    except Exception as e:

        log(
            f"⚠️ تعذر مزامنة الوقت: {e}"
        )


def timestamp_ms():

    return int(
        time.time() * 1000
    ) + SERVER_TIME_OFFSET


# =========================================================
# Public Market GET
# =========================================================

def market_get(
    path,
    params=None
):

    global LAST_MARKET_REQUEST

    url = (
        MARKET_BASE +
        path
    )

    for attempt in range(
        MAX_RETRIES
    ):

        try:

            elapsed = (
                time.time()
                -
                LAST_MARKET_REQUEST
            )

            if elapsed < REQUEST_GAP:

                time.sleep(
                    REQUEST_GAP -
                    elapsed
                )

            response = session.get(
                url,
                params=params,
                timeout=15
            )

            LAST_MARKET_REQUEST = (
                time.time()
            )

            if response.status_code == 200:

                return response.json()

            if response.status_code == 429:

                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                if retry_after:

                    wait = float(
                        retry_after
                    )

                else:

                    wait = min(
                        60,
                        2 ** attempt
                    )

                log(
                    f"⚠️ Binance 429 "
                    f"انتظار {wait:.1f}s"
                )

                time.sleep(wait)

                continue

            if response.status_code == 418:

                wait = min(
                    180,
                    30 * (attempt + 1)
                )

                log(
                    f"🚫 Binance 418 "
                    f"انتظار {wait}s"
                )

                time.sleep(wait)

                continue

            log(
                f"⚠️ Market HTTP "
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )

            time.sleep(
                min(
                    10,
                    2 ** attempt
                )
            )

        except Exception as e:

            wait = min(
                20,
                2 ** attempt
            )

            log(
                f"⚠️ اتصال Binance: "
                f"{e}"
            )

            time.sleep(wait)

    return None


# =========================================================
# Signed Binance request
# =========================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "BINANCE_API_KEY / "
            "BINANCE_API_SECRET غير موجودة"
        )

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = timestamp_ms()

    params.setdefault(
        "recvWindow",
        10000
    )

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query.encode(
            "utf-8"
        ),
        hashlib.sha256
    ).hexdigest()

    query += (
        "&signature="
        +
        signature
    )

    headers = {
        "X-MBX-APIKEY":
            API_KEY
    }

    url = (
        API_BASE +
        path +
        "?" +
        query
    )

    for attempt in range(
        MAX_RETRIES
    ):

        try:

            response = session.request(
                method,
                url,
                headers=headers,
                timeout=20
            )

            if response.status_code == 200:

                try:
                    return response.json()
                except:
                    return {}

            if response.status_code == 429:

                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                if retry_after:

                    wait = float(
                        retry_after
                    )

                else:

                    wait = min(
                        60,
                        2 ** attempt
                    )

                log(
                    f"⚠️ Signed 429 "
                    f"انتظار {wait:.1f}s"
                )

                time.sleep(wait)

                continue

            if response.status_code == 418:

                wait = min(
                    180,
                    30 * (attempt + 1)
                )

                log(
                    f"🚫 Signed 418 "
                    f"انتظار {wait}s"
                )

                time.sleep(wait)

                continue

            if response.status_code == 400:

                log(
                    "❌ Binance 400: "
                    +
                    response.text[:1000]
                )

                return None

            if response.status_code in (
                401,
                403
            ):

                log(
                    "❌ Binance API "
                    "صلاحيات/مفتاح: "
                    +
                    response.text[:1000]
                )

                return None

            log(
                f"⚠️ Binance HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )

            time.sleep(
                min(
                    10,
                    2 ** attempt
                )
            )

        except Exception as e:

            wait = min(
                20,
                2 ** attempt
            )

            log(
                f"⚠️ Signed connection: "
                f"{e}"
            )

            time.sleep(wait)

    return None


# =========================================================
# Exchange Info
# =========================================================

def load_exchange_info():

    global SYMBOL_INFO

    log(
        "📥 تحميل معلومات العملات..."
    )

    data = market_get(
        "/api/v3/exchangeInfo"
    )

    if not data:

        return False

    symbols = data.get(
        "symbols",
        []
    )

    info = {}

    for item in symbols:

        symbol = item.get(
            "symbol"
        )

        if not symbol:
            continue

        if item.get(
            "status"
        ) != "TRADING":
            continue

        if item.get(
            "quoteAsset"
        ) != "USDT":
            continue

        filters = {}

        for f in item.get(
            "filters",
            []
        ):

            filters[
                f.get("filterType")
            ] = f

        lot = (
            filters.get(
                "LOT_SIZE"
            )
            or
            filters.get(
                "MARKET_LOT_SIZE"
            )
        )

        price = filters.get(
            "PRICE_FILTER"
        )

        min_notional = (
            filters.get(
                "MIN_NOTIONAL"
            )
            or
            filters.get(
                "NOTIONAL"
            )
        )

        if not lot or not price:
            continue

        info[symbol] = {

            "baseAsset":
                item.get(
                    "baseAsset"
                ),

            "quoteAsset":
                "USDT",

            "stepSize":
                lot.get(
                    "stepSize",
                    "0"
                ),

            "minQty":
                lot.get(
                    "minQty",
                    "0"
                ),

            "maxQty":
                lot.get(
                    "maxQty",
                    "0"
                ),

            "tickSize":
                price.get(
                    "tickSize",
                    "0"
                ),

            "minPrice":
                price.get(
                    "minPrice",
                    "0"
                ),

            "minNotional":
                (
                    min_notional or {}
                ).get(
                    "minNotional",
                    "0"
                )

        }

    SYMBOL_INFO = info

    log(
        f"✅ تم تحميل "
        f"{len(SYMBOL_INFO)} عملة USDT"
    )

    return True


# =========================================================
# Klines
# =========================================================

def get_klines(
    symbol,
    interval,
    limit=KLINE_LIMIT
):

    data = market_get(
        "/api/v3/klines",
        {
            "symbol":
                symbol,

            "interval":
                interval,

            "limit":
                limit
        }
    )

    if not data:
        return []

    return data


# =========================================================
# Current price
# =========================================================

def get_price(symbol):

    data = market_get(
        "/api/v3/ticker/price",
        {
            "symbol":
                symbol
        }
    )

    if not data:
        return None

    try:

        return float(
            data["price"]
        )

    except:

        return None


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = (
        2 /
        (period + 1)
    )

    current = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        current = (
            (
                price -
                current
            )
            *
            multiplier
        ) + current

    return current


# =========================================================
# Signal 15m
# =========================================================

def signal_15m(symbol):

    candles = get_klines(
        symbol,
        "15m"
    )

    if len(candles) < 205:

        return None

    closes = [
        float(x[4])
        for x in candles
    ]

    highs = [
        float(x[2])
        for x in candles
    ]

    volumes = [
        float(x[5])
        for x in candles
    ]

    current_price = closes[-1]

    ema200 = ema(
        closes,
        200
    )

    if ema200 is None:
        return None

    # مقاومة آخر 20 شمعة
    resistance = max(
        highs[-21:-1]
    )

    # متوسط حجم آخر 20 شمعة
    avg_volume = (
        sum(
            volumes[-21:-1]
        )
        /
        20
    )

    current_volume = (
        volumes[-1]
    )

    if resistance <= 0:
        return None

    move = (
        (
            current_price -
            resistance
        )
        /
        resistance
    )

    # الاستراتيجية الأصلية
    if current_price <= ema200:
        return None

    if current_price <= resistance:
        return None

    if avg_volume <= 0:
        return None

    if current_volume < (
        avg_volume * 1.5
    ):
        return None

    if move < 0.005:
        return None

    if move > 0.04:
        return None

    return {

        "symbol":
            symbol,

        "price":
            current_price,

        "ema200":
            ema200,

        "resistance":
            resistance,

        "volume_ratio":
            current_volume /
            avg_volume,

        "move":
            move

    }


# =========================================================
# تأكيد 1h
# =========================================================

def confirm_1h(symbol):

    candles = get_klines(
        symbol,
        "1h"
    )

    if len(candles) < 205:
        return False

    closes = [
        float(x[4])
        for x in candles
    ]

    current_price = (
        closes[-1]
    )

    ema200 = ema(
        closes,
        200
    )

    if ema200 is None:
        return False

    return (
        current_price >
        ema200
    )


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    symbols = list(
        SYMBOL_INFO.keys()
    )

    log(
        f"🔎 فحص {len(symbols)} "
        f"عملة..."
    )

    candidates = []

    checked = 0

    for symbol in symbols:

        checked += 1

        try:

            signal = signal_15m(
                symbol
            )

            if not signal:
                continue

            log(
                f"👀 مرشح 15m: "
                f"{symbol} | "
                f"حجم "
                f"{signal['volume_ratio']:.2f}x | "
                f"اختراق "
                f"{signal['move']*100:.2f}%"
            )

            # تأكيد الساعة فقط للمرشح
            if not confirm_1h(
                symbol
            ):
                continue

            candidates.append(
                signal
            )

        except Exception as e:

            log(
                f"⚠️ {symbol}: {e}"
            )

    if not candidates:

        log(
            "📭 لا توجد إشارة كاملة"
        )

        return None

    # نختار أقوى حجم ثم الاختراق
    candidates.sort(
        key=lambda x: (
            x["volume_ratio"],
            x["move"]
        ),
        reverse=True
    )

    best = candidates[0]

    log(
        f"🔥 أقوى إشارة: "
        f"{best['symbol']} | "
        f"حجم "
        f"{best['volume_ratio']:.2f}x | "
        f"اختراق "
        f"{best['move']*100:.2f}%"
    )

    return best


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

    if not account:
        return 0.0

    for balance in account.get(
        "balances",
        []
    ):

        if balance.get(
            "asset"
        ) == "USDT":

            return float(
                balance.get(
                    "free",
                    0
                )
            )

    return 0.0


def get_asset_balance(asset):

    account = get_account()

    if not account:
        return 0.0

    for balance in account.get(
        "balances",
        []
    ):

        if balance.get(
            "asset"
        ) == asset:

            free = float(
                balance.get(
                    "free",
                    0
                )
            )

            locked = float(
                balance.get(
                    "locked",
                    0
                )
            )

            return (
                free +
                locked
            )

    return 0.0


# =========================================================
# Order helpers
# =========================================================

def normalize_quantity(
    symbol,
    quantity
):

    info = SYMBOL_INFO.get(
        symbol
    )

    if not info:
        return None

    step = dec(
        info["stepSize"]
    )

    min_qty = dec(
        info["minQty"]
    )

    qty = floor_step(
        quantity,
        step
    )

    if qty < min_qty:
        return None

    return qty


def normalize_price(
    symbol,
    price
):

    info = SYMBOL_INFO.get(
        symbol
    )

    if not info:
        return None

    tick = dec(
        info["tickSize"]
    )

    value = floor_step(
        price,
        tick
    )

    min_price = dec(
        info["minPrice"]
    )

    if value < min_price:
        return None

    return value


# =========================================================
# Market Buy
# =========================================================

def market_buy(symbol):

    usdt = get_usdt_balance()

    log(
        f"💰 USDT متاح: "
        f"{usdt:.4f}"
    )

    if usdt < MIN_USDT:

        log(
            f"❌ الرصيد أقل من "
            f"{MIN_USDT} USDT"
        )

        return None

    # نترك هامش بسيط للرسوم
    quote_amount = (
        usdt * 0.999
    )

    if quote_amount < MIN_USDT:

        return None

    log(
        f"🟢 شراء MARKET: "
        f"{symbol} | "
        f"{quote_amount:.4f} USDT"
    )

    response = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol":
                symbol,

            "side":
                "BUY",

            "type":
                "MARKET",

            "quoteOrderQty":
                decimal_string(
                    quote_amount
                ),

            "newOrderRespType":
                "FULL"
        }
    )

    if not response:

        log(
            "❌ فشل شراء Binance"
        )

        return None

    if not response.get(
        "orderId"
    ):

        log(
            "❌ Binance لم يعط "
            "orderId:"
        )

        log(
            json.dumps(
                response,
                ensure_ascii=False
            )
        )

        return None

    order_id = response[
        "orderId"
    ]

    executed_qty = float(
        response.get(
            "executedQty",
            0
        )
    )

    quote_qty = float(
        response.get(
            "cummulativeQuoteQty",
            0
        )
    )

    fills = response.get(
        "fills",
        []
    )

    if fills:

        total_qty = 0.0
        total_cost = 0.0

        for fill in fills:

            q = float(
                fill.get(
                    "qty",
                    0
                )
            )

            p = float(
                fill.get(
                    "price",
                    0
                )
            )

            total_qty += q
            total_cost += (
                q * p
            )

        if total_qty > 0:

            executed_qty = (
                total_qty
            )

            quote_qty = (
                total_cost
            )

    if executed_qty <= 0:

        log(
            "❌ الشراء لم ينفذ كمية"
        )

        return None

    if quote_qty <= 0:

        log(
            "❌ تعذر حساب تكلفة "
            "الشراء"
        )

        return None

    entry_price = (
        quote_qty /
        executed_qty
    )

    log(
        f"✅ تم الشراء "
        f"{symbol}"
    )

    log(
        f"📌 Entry: "
        f"{entry_price}"
    )

    log(
        f"📦 Qty: "
        f"{executed_qty}"
    )

    log(
        f"🧾 Order ID: "
        f"{order_id}"
    )

    return {

        "order_id":
            order_id,

        "qty":
            executed_qty,

        "entry":
            entry_price,

        "quote_qty":
            quote_qty

    }


# =========================================================
# Query order
# =========================================================

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


# =========================================================
# Cancel order
# =========================================================

def cancel_order(
    symbol,
    order_id
):

    if not order_id:
        return None

    log(
        f"🗑️ إلغاء وقف "
        f"{order_id}"
    )

    response = signed_request(
        "DELETE",
        "/api/v3/order",
        {
            "symbol":
                symbol,

            "orderId":
                order_id
        }
    )

    if response:

        log(
            f"✅ تم إلغاء الوقف "
            f"{order_id}"
        )

    return response


# =========================================================
# وضع وقف حقيقي على Binance
# =========================================================

def place_stop(
    symbol,
    quantity,
    stop_price
):

    info = SYMBOL_INFO.get(
        symbol
    )

    if not info:

        log(
            "❌ لا توجد معلومات "
            f"للعملة {symbol}"
        )

        return None

    qty = normalize_quantity(
        symbol,
        quantity
    )

    price = normalize_price(
        symbol,
        stop_price
    )

    if qty is None:

        log(
            "❌ الكمية لا تطابق "
            "LOT_SIZE"
        )

        return None

    if price is None:

        log(
            "❌ سعر الوقف لا يطابق "
            "PRICE_FILTER"
        )

        return None

    log(
        f"🛑 وضع وقف Binance: "
        f"{symbol} | "
        f"Qty={decimal_string(qty)} | "
        f"Stop={decimal_string(price)}"
    )

    response = signed_request(
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
                decimal_string(qty),

            "stopPrice":
                decimal_string(price),

            "newOrderRespType":
                "RESULT"
        }
    )

    if not response:

        log(
            "❌ Binance رفض إنشاء "
            "وقف الخسارة"
        )

        return None

    log(
        "📥 رد Binance للوقف:"
    )

    log(
        json.dumps(
            response,
            ensure_ascii=False
        )
    )

    order_id = (
        response.get(
            "orderId"
        )
    )

    status = (
        response.get(
            "status"
        )
    )

    if not order_id:

        log(
            "❌ لم يتم الحصول "
            "على orderId للوقف"
        )

        return None

    if status not in (
        None,
        "NEW",
        "PARTIALLY_FILLED"
    ):

        log(
            f"⚠️ حالة الوقف: "
            f"{status}"
        )

    log(
        f"✅ وقف Binance فعال "
        f"| ID={order_id}"
    )

    return {

        "order_id":
            order_id,

        "stop_price":
            float(price),

        "quantity":
            float(qty),

        "status":
            status

    }


# =========================================================
# سعر الوقف حسب الربح الصافي
# =========================================================

def price_for_net_profit(
    entry,
    net_profit
):

    # net = gross * (1-fee) * (1-fee) - 1
    fee_multiplier = (
        (1 - FEE_RATE)
        *
        (1 - FEE_RATE)
    )

    gross_multiplier = (
        1 + net_profit
    ) / fee_multiplier

    return (
        entry *
        gross_multiplier
    )


# =========================================================
# حساب الربح الصافي
# =========================================================

def net_profit_pct(
    entry,
    current
):

    if entry <= 0:
        return -1

    gross = (
        current /
        entry
    )

    net = (
        gross *
        (1 - FEE_RATE) *
        (1 - FEE_RATE)
    ) - 1

    return net


# =========================================================
# تسجيل الصفقة المغلقة
# =========================================================

def record_trade(
    state,
    exit_price,
    reason
):

    history = load_history()

    entry = float(
        state.get(
            "entry",
            0
        )
    )

    qty = float(
        state.get(
            "qty",
            0
        )
    )

    if entry <= 0:
        pnl_pct = 0
    else:
        pnl_pct = (
            net_profit_pct(
                entry,
                exit_price
            )
            *
            100
        )

    pnl_usdt = (
        (
            exit_price -
            entry
        )
        *
        qty
    )

    record = {

        "symbol":
            state.get(
                "symbol"
            ),

        "entry":
            entry,

        "exit":
            exit_price,

        "qty":
            qty,

        "pnl_pct":
            pnl_pct,

        "pnl_usdt":
            pnl_usdt,

        "reason":
            reason,

        "opened_at":
            state.get(
                "opened_at"
            ),

        "closed_at":
            datetime.now(
                timezone.utc
            ).isoformat()

    }

    history.append(
        record
    )

    save_history(
        history
    )

    log(
        f"📜 تم تسجيل الصفقة "
        f"{state.get('symbol')} | "
        f"{pnl_pct:+.2f}% | "
        f"{pnl_usdt:+.4f} USDT | "
        f"{reason}"
    )


# =========================================================
# التأكد أن الصفقة ما زالت موجودة
# =========================================================

def position_still_exists(
    state
):

    symbol = state.get(
        "symbol"
    )

    if not symbol:
        return False

    info = SYMBOL_INFO.get(
        symbol
    )

    if not info:
        return False

    asset = info.get(
        "baseAsset"
    )

    if not asset:
        return False

    qty = get_asset_balance(
        asset
    )

    original_qty = float(
        state.get(
            "qty",
            0
        )
    )

    # نعتبر الصفقة موجودة
    # إذا بقي جزء معقول من الكمية
    minimum = max(
        original_qty * 0.02,
        0.00000001
    )

    return qty >= minimum


# =========================================================
# استعادة صفقة من state
# =========================================================

def restore_trade():

    state = load_state()

    if not state:
        return None

    symbol = state.get(
        "symbol"
    )

    if not symbol:

        clear_state()

        return None

    log(
        f"♻️ وجدت صفقة محفوظة: "
        f"{symbol}"
    )

    # إذا الصفقة انتهت في Binance
    if not position_still_exists(
        state
    ):

        log(
            "✅ الصفقة السابقة "
            "انتهت على Binance"
        )

        clear_state()

        return None

    log(
        "🟢 سأكمل إدارة الصفقة "
        "بدون فتح صفقة جديدة"
    )

    return state


# =========================================================
# وضع الوقف الأول
# =========================================================

def ensure_initial_stop(
    state
):

    symbol = state.get(
        "symbol"
    )

    entry = float(
        state.get(
            "entry",
            0
        )
    )

    qty = float(
        state.get(
            "qty",
            0
        )
    )

    if not symbol or entry <= 0:
        return False

    existing_stop = state.get(
        "stop_order_id"
    )

    if existing_stop:

        order = query_order(
            symbol,
            existing_stop
        )

        if order:

            status = order.get(
                "status"
            )

            if status in (
                "NEW",
                "PARTIALLY_FILLED"
            ):

                state[
                    "stop_price"
                ] = float(
                    order.get(
                        "stopPrice",
                        state.get(
                            "stop_price",
                            entry * (
                                1 +
                                INITIAL_STOP
                            )
                        )
                    )
                )

                save_state(
                    state
                )

                return True

            if status == "FILLED":

                log(
                    "🛑 وقف الخسارة "
                    "تم تنفيذه"
                )

                exit_price = float(
                    order.get(
                        "stopPrice",
                        entry * (
                            1 +
                            INITIAL_STOP
                        )
                    )
                )

                record_trade(
                    state,
                    exit_price,
                    "STOP_FILLED"
                )

                clear_state()

                return False

    stop_price = (
        entry *
        (1 + INITIAL_STOP)
    )

    # ننزل للكمية الموجودة فعليًا
    info = SYMBOL_INFO.get(
        symbol
    )

    if info:

        asset = info.get(
            "baseAsset"
        )

        if asset:

            actual_qty = (
                get_asset_balance(
                    asset
                )
            )

            if actual_qty > 0:

                qty = min(
                    qty,
                    actual_qty
                )

    stop = place_stop(
        symbol,
        qty,
        stop_price
    )

    if not stop:

        log(
            "❌ لم يتم وضع وقف "
            "الخسارة"
        )

        return False

    state[
        "stop_order_id"
    ] = stop[
        "order_id"
    ]

    state[
        "stop_price"
    ] = stop[
        "stop_price"
    ]

    state.setdefault(
        "locked_level",
        0.0
    )

    save_state(
        state
    )

    return True


# =========================================================
# رفع الوقف
# =========================================================

def raise_stop(
    state,
    target_level
):

    symbol = state.get(
        "symbol"
    )

    entry = float(
        state.get(
            "entry",
            0
        )
    )

    old_order_id = state.get(
        "stop_order_id"
    )

    old_level = float(
        state.get(
            "locked_level",
            0
        )
    )

    if target_level <= old_level:

        return True

    # السعر الذي يحقق الربح الصافي المطلوب
    new_stop_price = (
        price_for_net_profit(
            entry,
            target_level
        )
    )

    # كمية فعلية موجودة
    info = SYMBOL_INFO.get(
        symbol
    )

    if not info:
        return False

    asset = info.get(
        "baseAsset"
    )

    actual_qty = (
        get_asset_balance(
            asset
        )
    )

    if actual_qty <= 0:

        log(
            "⚠️ لا توجد كمية "
            "متاحة لوقف جديد"
        )

        return False

    qty = actual_qty

    # =====================================================
    # مهم:
    # نلغي الوقف القديم أولًا حتى تصبح الكمية متاحة
    # ثم نضع الوقف الجديد مباشرة.
    # =====================================================

    if old_order_id:

        old_order = query_order(
            symbol,
            old_order_id
        )

        if old_order:

            old_status = old_order.get(
                "status"
            )

            if old_status in (
                "NEW",
                "PARTIALLY_FILLED"
            ):

                cancel_order(
                    symbol,
                    old_order_id
                )

                time.sleep(0.25)

    # تحديث الكمية بعد الإلغاء
    actual_qty = (
        get_asset_balance(
            asset
        )
    )

    if actual_qty <= 0:

        log(
            "❌ الكمية اختفت "
            "بعد إلغاء الوقف"
        )

        return False

    stop = place_stop(
        symbol,
        actual_qty,
        new_stop_price
    )

    if not stop:

        log(
            "🚨 تحذير: فشل وضع "
            "الوقف الجديد"
        )

        return False

    state[
        "stop_order_id"
    ] = stop[
        "order_id"
    ]

    state[
        "stop_price"
    ] = stop[
        "stop_price"
    ]

    state[
        "locked_level"
    ] = target_level

    state[
        "last_raise_time"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    save_state(
        state
    )

    log(
        f"🔒 تم رفع الوقف إلى "
        f"+{target_level*100:.0f}%"
    )

    return True


# =========================================================
# إدارة الصفقة
# =========================================================

def manage_position(
    state
):

    symbol = state.get(
        "symbol"
    )

    entry = float(
        state.get(
            "entry",
            0
        )
    )

    if not symbol or entry <= 0:

        clear_state()

        return False

    log(
        f"📊 إدارة الصفقة: "
        f"{symbol} | "
        f"Entry={entry}"
    )

    # تأكد من وجود وقف
    if not ensure_initial_stop(
        state
    ):

        return False

    # ممكن ensure_initial_stop
    # يعدل state
    state = load_state()

    while True:

        try:

            # =============================================
            # تأكد أن الصفقة ما زالت موجودة
            # =============================================

            if not position_still_exists(
                state
            ):

                log(
                    "✅ الصفقة أغلقت "
                    "على Binance"
                )

                # محاولة معرفة السعر الحالي
                current = get_price(
                    symbol
                )

                if current is None:
                    current = entry

                # إذا كان أمر الوقف Filled
                stop_order_id = state.get(
                    "stop_order_id"
                )

                if stop_order_id:

                    order = query_order(
                        symbol,
                        stop_order_id
                    )

                    if order and order.get(
                        "status"
                    ) == "FILLED":

                        executed = float(
                            order.get(
                                "executedQty",
                                0
                            )
                        )

                        quote = float(
                            order.get(
                                "cummulativeQuoteQty",
                                0
                            )
                        )

                        if executed > 0:

                            current = (
                                quote /
                                executed
                            )

                        reason = (
                            "BINANCE_STOP_FILLED"
                        )

                    else:

                        reason = (
                            "POSITION_CLOSED"
                        )

                else:

                    reason = (
                        "POSITION_CLOSED"
                    )

                record_trade(
                    state,
                    current,
                    reason
                )

                clear_state()

                return False

            # =============================================
            # السعر
            # =============================================

            current = get_price(
                symbol
            )

            if current is None:

                log(
                    "⚠️ تعذر جلب السعر"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =============================================
            # الربح الصافي
            # =============================================

            net = net_profit_pct(
                entry,
                current
            )

            log(
                f"📈 {symbol} | "
                f"السعر {current:.8f} | "
                f"الصافي {net*100:+.2f}% | "
                f"وقف {float(state.get('stop_price', 0)):.8f} | "
                f"تأمين +{float(state.get('locked_level', 0))*100:.0f}%"
            )

            # =============================================
            # مستوى الربح التالي
            # =============================================

            if net >= PROFIT_STEP:

                # مثال:
                # 1.87% => مستوى +1%
                # 2.99% => +2%
                # 5.20% => +5%

                level_number = math.floor(
                    (
                        net + 1e-12
                    )
                    /
                    PROFIT_STEP
                )

                target_level = (
                    level_number *
                    PROFIT_STEP
                )

                current_locked = float(
                    state.get(
                        "locked_level",
                        0
                    )
                )

                if target_level > (
                    current_locked +
                    1e-9
                ):

                    log(
                        f"🚀 ربح {net*100:.2f}% "
                        f"→ رفع الوقف إلى "
                        f"+{target_level*100:.0f}%"
                    )

                    success = raise_stop(
                        state,
                        target_level
                    )

                    if success:

                        state = load_state()

                    else:

                        log(
                            "⚠️ لم يتم رفع الوقف"
                        )

            # =============================================
            # تحقق من حالة أمر الوقف
            # =============================================

            stop_order_id = state.get(
                "stop_order_id"
            )

            if stop_order_id:

                order = query_order(
                    symbol,
                    stop_order_id
                )

                if order:

                    status = order.get(
                        "status"
                    )

                    if status == "FILLED":

                        executed = float(
                            order.get(
                                "executedQty",
                                0
                            )
                        )

                        quote = float(
                            order.get(
                                "cummulativeQuoteQty",
                                0
                            )
                        )

                        exit_price = current

                        if (
                            executed > 0
                            and
                            quote > 0
                        ):

                            exit_price = (
                                quote /
                                executed
                            )

                        log(
                            "🛑 STOP FILLED "
                            "من Binance"
                        )

                        record_trade(
                            state,
                            exit_price,
                            "BINANCE_STOP_FILLED"
                        )

                        clear_state()

                        return False

                    if status in (
                        "CANCELED",
                        "EXPIRED"
                    ):

                        log(
                            f"⚠️ أمر الوقف "
                            f"{status}"
                        )

                        # نعيد إنشاء وقف
                        state[
                            "stop_order_id"
                        ] = None

                        save_state(
                            state
                        )

                        if not ensure_initial_stop(
                            state
                        ):

                            return False

                        state = load_state()

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except KeyboardInterrupt:

            raise

        except Exception as e:

            log(
                f"⚠️ خطأ إدارة الصفقة: "
                f"{e}"
            )

            time.sleep(
                POSITION_CHECK_SECONDS
            )


# =========================================================
# فتح صفقة
# =========================================================

def open_trade(
    signal
):

    symbol = signal[
        "symbol"
    ]

    log(
        f"🔥 دخول صفقة: "
        f"{symbol}"
    )

    result = market_buy(
        symbol
    )

    if not result:

        return False

    state = {

        "symbol":
            symbol,

        "entry":
            result["entry"],

        "qty":
            result["qty"],

        "quote_qty":
            result["quote_qty"],

        "buy_order_id":
            result["order_id"],

        "stop_order_id":
            None,

        "stop_price":
            result["entry"] *
            (1 + INITIAL_STOP),

        "locked_level":
            0.0,

        "opened_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "strategy":
            "V2_15m_1h_EMA200_BREAKOUT20_VOLUME1.5"

    }

    save_state(
        state
    )

    log(
        "💾 تم حفظ الصفقة"
    )

    # وضع وقف حقيقي فورًا
    if not ensure_initial_stop(
        state
    ):

        log(
            "🚨 تحذير خطير: "
            "لم يتم وضع وقف Binance"
        )

        # لا نفتح صفقة ثانية
        # ونبقى ندير الحالية
        return True

    return True


# =========================================================
# تنظيف أوامر وقف قديمة
# =========================================================

def check_existing_state():

    state = load_state()

    if not state:
        return None

    symbol = state.get(
        "symbol"
    )

    if not symbol:

        clear_state()

        return None

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print(
        "=========================================="
    )
    print(
        "   مضارب أبو سعود V2 🤖"
    )
    print(
        "   Binance Spot"
    )
    print(
        "   وقف حقيقي + تأمين ربح"
    )
    print(
        "=========================================="
    )
    print()

    if not API_KEY or not API_SECRET:

        log(
            "❌ ضع BINANCE_API_KEY "
            "و BINANCE_API_SECRET "
            "في .env"
        )

        return

    sync_server_time()

    if not load_exchange_info():

        log(
            "❌ فشل تحميل Exchange Info"
        )

        return

    # =====================================================
    # أهم شيء:
    # إذا فيه صفقة محفوظة نكملها
    # =====================================================

    state = restore_trade()

    if state:

        manage_position(
            state
        )

    # =====================================================
    # البحث المستمر
    # =====================================================

    while True:

        try:

            # إذا فيه صفقة لأي سبب
            # نكملها ولا نفتح ثانية
            state = check_existing_state()

            if state:

                log(
                    f"🟢 صفقة موجودة "
                    f"{state.get('symbol')} "
                    f"→ أكمل إدارتها"
                )

                manage_position(
                    state
                )

                continue

            # =================================================
            # فحص الرصيد
            # =================================================

            balance = get_usdt_balance()

            log(
                f"💰 رصيد USDT: "
                f"{balance:.4f}"
            )

            if balance < MIN_USDT:

                log(
                    f"⏳ الرصيد أقل من "
                    f"{MIN_USDT} USDT"
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # =================================================
            # فحص السوق
            # =================================================

            signal = scan_market()

            if not signal:

                log(
                    f"😴 إعادة الفحص بعد "
                    f"{SCAN_INTERVAL}s"
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # =================================================
            # تأكيد السعر قبل الدخول
            # =================================================

            latest_price = get_price(
                signal["symbol"]
            )

            if latest_price is None:

                log(
                    "⚠️ تعذر تأكيد السعر"
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # نعيد حساب الحركة
            # حتى لا ندخل بعد اندفاعة كبيرة
            resistance = signal[
                "resistance"
            ]

            move = (
                (
                    latest_price -
                    resistance
                )
                /
                resistance
            )

            if move < 0.005:

                log(
                    "❌ الإشارة اختفت"
                )

                time.sleep(10)

                continue

            if move > 0.04:

                log(
                    "❌ الحركة تجاوزت "
                    "4% - تجاهل"
                )

                time.sleep(10)

                continue

            # =================================================
            # فتح الصفقة
            # =================================================

            opened = open_trade(
                signal
            )

            if opened:

                # نقرأ الحالة الجديدة
                state = load_state()

                if state:

                    manage_position(
                        state
                    )

            else:

                log(
                    "❌ لم تفتح الصفقة"
                )

                time.sleep(10)

        except KeyboardInterrupt:

            log(
                "👋 تم إيقاف البوت"
            )

            break

        except Exception as e:

            log(
                f"🚨 خطأ رئيسي: {e}"
            )

            time.sleep(15)


# =========================================================
# تشغيل
# =========================================================

if __name__ == "__main__":

    main()
