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


# ============================================================
# مضارب أبو سعود 🤖
# Binance Spot
# 15m
# نزول 2% = شراء
# TP +2%
# SL -2%
# 10 USDT
# Restart Recovery
# 429 Protection
# OCO Protection
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE = "https://api.binance.com"

TIMEFRAME = "15m"

DROP_PERCENT = 0.02
TP_PERCENT = 0.02
SL_PERCENT = 0.02

TRADE_USDT = 10.0

MIN_VOLUME = 1_000_000

DATA_FILE = "bot_data.json"

# سرعة طلبات Binance
REQUEST_MIN_INTERVAL = 0.35

# إذا جاء 429 ولم يعط Binance مدة واضحة
DEFAULT_429_WAIT = 60

# أقصى عمر لصفقة نحاول استعادتها
RECOVERY_MAX_AGE_HOURS = 48

# أقل وأعلى مبلغ يعتبره البوت صفقة البوت
RECOVERY_MIN_QUOTE = 7.0
RECOVERY_MAX_QUOTE = 13.0

# كل دورة فحص
SCAN_INTERVAL = 90

REQUEST_TIMEOUT = 20


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# GLOBAL
# ============================================================

state_lock = threading.Lock()
request_lock = threading.Lock()

last_request_time = 0.0

state = {
    "active_trade": None,

    "trades": [],

    "wins": 0,

    "losses": 0,

    "total_profit": 0.0,

    "last_scan": "",

    "status": "بدء التشغيل",

    "binance": False,

    "symbols_count": 0,

    "last_error": ""
}


exchange_info = {}

symbols_info = {}


# ============================================================
# LOG
# ============================================================

def log(message):
    print(message, flush=True)


# ============================================================
# TIME
# ============================================================

def now_ms():
    return int(time.time() * 1000)


# ============================================================
# SAVE / LOAD
# ============================================================

def save_state():

    try:

        with state_lock:

            data = {
                "active_trade": state["active_trade"],

                "trades": state["trades"][-200:],

                "wins": state["wins"],

                "losses": state["losses"],

                "total_profit": state["total_profit"],

                "last_scan": state["last_scan"],

                "status": state["status"]
            }

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        log(f"⚠️ حفظ البيانات: {e}")


def load_state():

    try:

        if not os.path.exists(DATA_FILE):

            log("ℹ️ لا يوجد ملف بيانات سابق")

            return

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        with state_lock:

            state["active_trade"] = data.get(
                "active_trade"
            )

            state["trades"] = data.get(
                "trades",
                []
            )

            state["wins"] = data.get(
                "wins",
                0
            )

            state["losses"] = data.get(
                "losses",
                0
            )

            state["total_profit"] = data.get(
                "total_profit",
                0.0
            )

            state["last_scan"] = data.get(
                "last_scan",
                ""
            )

        log("💾 تم تحميل ملف البيانات")

    except Exception as e:

        log(f"⚠️ خطأ تحميل البيانات: {e}")


# ============================================================
# REQUEST RATE LIMITER
# ============================================================

def wait_request_slot():

    global last_request_time

    with request_lock:

        current = time.monotonic()

        wait = (
            REQUEST_MIN_INTERVAL
            - (current - last_request_time)
        )

        if wait > 0:

            time.sleep(wait)

        last_request_time = time.monotonic()


def retry_after_seconds(response):

    value = response.headers.get(
        "Retry-After"
    )

    if value:

        try:
            return max(
                1,
                int(float(value))
            )

        except:
            pass

    return DEFAULT_429_WAIT


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(
    path,
    params=None,
    retries=3
):

    for attempt in range(retries):

        wait_request_slot()

        try:

            response = requests.get(
                BASE + path,
                params=params or {},
                timeout=REQUEST_TIMEOUT
            )

        except requests.RequestException as e:

            if attempt < retries - 1:

                wait_time = 5 * (
                    attempt + 1
                )

                log(
                    f"⚠️ اتصال Binance "
                    f"→ انتظار {wait_time}s"
                )

                time.sleep(wait_time)

                continue

            raise e

        # ====================================================
        # 429
        # ====================================================

        if response.status_code == 429:

            wait_time = retry_after_seconds(
                response
            )

            log(
                f"🛑 Binance 429 "
                f"→ إيقاف الطلبات {wait_time}s"
            )

            time.sleep(wait_time)

            continue

        # ====================================================
        # 418
        # ====================================================

        if response.status_code == 418:

            wait_time = retry_after_seconds(
                response
            )

            log(
                f"🚫 Binance 418 "
                f"→ انتظار {wait_time}s"
            )

            time.sleep(wait_time)

            continue

        response.raise_for_status()

        return response.json()

    raise Exception(
        "Binance: فشل الطلب بعد محاولات متعددة"
    )


# ============================================================
# SIGN
# ============================================================

def build_signature(params):

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return query + "&signature=" + signature


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
    retries=3
):

    params = params.copy() if params else {}

    for attempt in range(retries):

        params["timestamp"] = now_ms()

        params["recvWindow"] = 5000

        query = build_signature(
            params
        )

        url = (
            BASE
            + path
            + "?"
            + query
        )

        headers = {
            "X-MBX-APIKEY": API_KEY
        }

        try:

            wait_request_slot()

            if method == "GET":

                response = requests.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )

            elif method == "POST":

                response = requests.post(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )

            elif method == "DELETE":

                response = requests.delete(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )

            else:

                raise Exception(
                    "HTTP method غير مدعوم"
                )

        except requests.RequestException as e:

            if attempt < retries - 1:

                wait_time = 5 * (
                    attempt + 1
                )

                log(
                    f"⚠️ اتصال Binance "
                    f"→ انتظار {wait_time}s"
                )

                time.sleep(wait_time)

                continue

            raise e

        # ====================================================
        # 429
        # ====================================================

        if response.status_code == 429:

            wait_time = retry_after_seconds(
                response
            )

            log(
                f"🛑 Binance 429 "
                f"→ انتظار {wait_time}s"
            )

            time.sleep(wait_time)

            continue

        # ====================================================
        # 418
        # ====================================================

        if response.status_code == 418:

            wait_time = retry_after_seconds(
                response
            )

            log(
                f"🚫 Binance 418 "
                f"→ انتظار {wait_time}s"
            )

            time.sleep(wait_time)

            continue

        try:

            data = response.json()

        except:

            data = {
                "raw": response.text
            }

        if response.status_code >= 400:

            raise Exception(
                f"Binance {response.status_code}: "
                f"{data}"
            )

        return data

    raise Exception(
        "Binance: فشل الطلب بعد المحاولات"
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def load_exchange_info():

    global exchange_info
    global symbols_info

    log("📥 تحميل معلومات Binance...")

    exchange_info = public_get(
        "/api/v3/exchangeInfo"
    )

    symbols_info = {}

    for symbol_data in exchange_info.get(
        "symbols",
        []
    ):

        if symbol_data.get(
            "status"
        ) != "TRADING":

            continue

        symbol = symbol_data.get(
            "symbol"
        )

        if not symbol.endswith(
            "USDT"
        ):

            continue

        filters = {}

        for f in symbol_data.get(
            "filters",
            []
        ):

            filters[
                f["filterType"]
            ] = f

        symbols_info[symbol] = {

            "base":
                symbol_data["baseAsset"],

            "quote":
                symbol_data["quoteAsset"],

            "filters":
                filters
        }

    state["symbols_count"] = len(
        symbols_info
    )

    log(
        f"✅ تم تحميل "
        f"{len(symbols_info)} عملة"
    )


# ============================================================
# DECIMAL HELPERS
# ============================================================

def decimals_from_step(step):

    d = Decimal(
        str(step)
    )

    if d == 0:
        return 8

    return max(
        0,
        -d.as_tuple().exponent
    )


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
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def format_decimal(
    value,
    step
):

    value = floor_step(
        value,
        step
    )

    places = decimals_from_step(
        step
    )

    return f"{value:.{places}f}"


# ============================================================
# SYMBOL FILTERS
# ============================================================

def get_symbol_filters(
    symbol
):

    info = symbols_info.get(
        symbol
    )

    if not info:

        raise Exception(
            f"لا توجد معلومات {symbol}"
        )

    filters = info["filters"]

    lot = filters.get(
        "LOT_SIZE"
    )

    price_filter = filters.get(
        "PRICE_FILTER"
    )

    min_notional = filters.get(
        "MIN_NOTIONAL"
    )

    return (
        lot,
        price_filter,
        min_notional
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_balances():

    account = get_account()

    result = {}

    for balance in account.get(
        "balances",
        []
    ):

        free = float(
            balance["free"]
        )

        locked = float(
            balance["locked"]
        )

        total = free + locked

        if total > 0:

            result[
                balance["asset"]
            ] = {

                "free": free,

                "locked": locked,

                "total": total
            }

    return result


def get_balance(
    asset
):

    balances = get_balances()

    return balances.get(
        asset,
        {
            "free": 0.0,
            "locked": 0.0,
            "total": 0.0
        }
    )


# ============================================================
# PRICE
# ============================================================

def get_current_price(
    symbol
):

    data = public_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ============================================================
# OPEN ORDERS
# ============================================================

def get_open_orders(
    symbol=None
):

    params = {}

    if symbol:

        params["symbol"] = symbol

    return signed_request(
        "GET",
        "/api/v3/openOrders",
        params
    )


# ============================================================
# OPEN OCO
# ============================================================

def get_open_order_lists():

    return signed_request(
        "GET",
        "/api/v3/openOrderList"
    )


# ============================================================
# USER TRADES
# ============================================================

def get_my_trades(
    symbol,
    limit=100
):

    return signed_request(
        "GET",
        "/api/v3/myTrades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )


# ============================================================
# MARKET BUY
# ============================================================

def market_buy(
    symbol
):

    log(
        f"🟢 شراء MARKET "
        f"{symbol} | "
        f"{TRADE_USDT} USDT"
    )

    params = {

        "symbol":
            symbol,

        "side":
            "BUY",

        "type":
            "MARKET",

        "quoteOrderQty":
            f"{TRADE_USDT:.2f}",

        "newOrderRespType":
            "FULL"
    }

    return signed_request(
        "POST",
        "/api/v3/order",
        params
    )


# ============================================================
# MARKET SELL
# ============================================================

def market_sell(
    symbol,
    quantity
):

    lot, _, _ = get_symbol_filters(
        symbol
    )

    step = lot["stepSize"]

    qty = floor_step(
        Decimal(str(quantity)),
        Decimal(str(step))
    )

    if qty <= 0:

        raise Exception(
            "الكمية بعد التقريب = 0"
        )

    params = {

        "symbol":
            symbol,

        "side":
            "SELL",

        "type":
            "MARKET",

        "quantity":
            format_decimal(
                qty,
                step
            ),

        "newOrderRespType":
            "FULL"
    }

    return signed_request(
        "POST",
        "/api/v3/order",
        params
    )


# ============================================================
# OCO
# ============================================================

def place_oco(
    symbol,
    quantity,
    tp_price,
    sl_price
):

    lot, price_filter, _ = get_symbol_filters(
        symbol
    )

    step = lot["stepSize"]

    tick = price_filter["tickSize"]

    qty = floor_step(
        Decimal(str(quantity)),
        Decimal(str(step))
    )

    tp = floor_step(
        Decimal(str(tp_price)),
        Decimal(str(tick))
    )

    sl = floor_step(
        Decimal(str(sl_price)),
        Decimal(str(tick))
    )

    stop_limit = floor_step(
        sl * Decimal("0.999"),
        Decimal(str(tick))
    )

    if qty <= 0:

        raise Exception(
            "OCO quantity = 0"
        )

    if tp <= 0 or sl <= 0:

        raise Exception(
            "TP/SL غير صحيح"
        )

    params = {

        "symbol":
            symbol,

        "side":
            "SELL",

        "quantity":
            format_decimal(
                qty,
                step
            ),

        "aboveType":
            "LIMIT_MAKER",

        "abovePrice":
            format_decimal(
                tp,
                tick
            ),

        "belowType":
            "STOP_LOSS_LIMIT",

        "belowStopPrice":
            format_decimal(
                sl,
                tick
            ),

        "belowPrice":
            format_decimal(
                stop_limit,
                tick
            ),

        "belowTimeInForce":
            "GTC",

        "newOrderRespType":
            "RESULT"
    }

    log(
        f"🛡️ إنشاء OCO "
        f"{symbol} | "
        f"TP={format_decimal(tp,tick)} | "
        f"SL={format_decimal(sl,tick)}"
    )

    return signed_request(
        "POST",
        "/api/v3/orderList/oco",
        params
    )


# ============================================================
# FIND LATEST BOT-LIKE BUY
# ============================================================

def find_latest_buy_for_recovery(
    symbol,
    balance_qty
):

    try:

        trades = get_my_trades(
            symbol,
            100
        )

        buys = [

            t for t in trades

            if t.get(
                "isBuyer"
            ) is True

        ]

        if not buys:

            return None

        # أحدث BUY أولًا
        buys.sort(
            key=lambda x:
            int(
                x.get(
                    "time",
                    0
                )
            ),
            reverse=True
        )

        checked_orders = set()

        for trade in buys:

            order_id = trade.get(
                "orderId"
            )

            if order_id in checked_orders:

                continue

            checked_orders.add(
                order_id
            )

            order_trades = [

                x for x in buys

                if x.get(
                    "orderId"
                ) == order_id

            ]

            if not order_trades:

                continue

            total_qty = 0.0

            total_quote = 0.0

            latest_time = 0

            for t in order_trades:

                qty = float(
                    t.get(
                        "qty",
                        0
                    )
                )

                quote = float(
                    t.get(
                        "quoteQty",
                        0
                    )
                )

                total_qty += qty

                total_quote += quote

                latest_time = max(
                    latest_time,
                    int(
                        t.get(
                            "time",
                            0
                        )
                    )
                )

            if total_qty <= 0:

                continue

            age_ms = (
                now_ms()
                - latest_time
            )

            if age_ms > (
                RECOVERY_MAX_AGE_HOURS
                * 60
                * 60
                * 1000
            ):

                continue

            if total_quote < RECOVERY_MIN_QUOTE:

                continue

            if total_quote > RECOVERY_MAX_QUOTE:

                continue

            # الرصيد الحالي يجب يكون قريب من كمية الشراء
            # لأننا نبحث عن صفقة ما زالت مفتوحة
            if balance_qty > (
                total_qty * 1.05
            ):

                continue

            if balance_qty < (
                total_qty * 0.50
            ):

                continue

            entry = (
                total_quote
                / total_qty
            )

            return {

                "order_id":
                    order_id,

                "quantity":
                    balance_qty,

                "buy_quantity":
                    total_qty,

                "quote":
                    total_quote,

                "entry_price":
                    entry,

                "time":
                    latest_time
            }

        return None

    except Exception as e:

        log(
            f"⚠️ سجل BUY "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# RECOVERY FROM SAVED STATE
# ============================================================

def recover_saved_trade():

    trade = state.get(
        "active_trade"
    )

    if not trade:

        return False

    symbol = trade.get(
        "symbol"
    )

    if not symbol:

        return False

    try:

        base = symbols_info[
            symbol
        ]["base"]

        balance = get_balance(
            base
        )

        if balance["total"] <= 0:

            log(
                f"ℹ️ الصفقة المحفوظة "
                f"انتهت: {symbol}"
            )

            state[
                "active_trade"
            ] = None

            save_state()

            return False

        trade["quantity"] = (
            balance["total"]
        )

        state[
            "active_trade"
        ] = trade

        save_state()

        log(
            f"♻️ استعادة الصفقة "
            f"من الملف: {symbol}"
        )

        return True

    except Exception as e:

        log(
            f"⚠️ استعادة الملف: {e}"
        )

        return False


# ============================================================
# RECOVERY FROM OPEN OCO
# ============================================================

def recover_open_oco():

    try:

        lists = get_open_order_lists()

        if not lists:

            return False

        for item in lists:

            if item.get(
                "listOrderStatus"
            ) != "EXECUTING":

                continue

            symbol = item.get(
                "symbol"
            )

            if not symbol:

                continue

            if symbol not in symbols_info:

                continue

            base = symbols_info[
                symbol
            ]["base"]

            balance = get_balance(
                base
            )

            if balance["total"] <= 0:

                continue

            # نحاول الحصول على الدخول من سجل BUY
            buy = find_latest_buy_for_recovery(
                symbol,
                balance["total"]
            )

            if not buy:

                continue

            entry = buy[
                "entry_price"
            ]

            tp = (
                entry
                * (1 + TP_PERCENT)
            )

            sl = (
                entry
                * (1 - SL_PERCENT)
            )

            state[
                "active_trade"
            ] = {

                "symbol":
                    symbol,

                "quantity":
                    balance["total"],

                "entry_price":
                    entry,

                "tp":
                    tp,

                "sl":
                    sl,

                "buy_order_id":
                    buy["order_id"],

                "oco_order_list_id":
                    item.get(
                        "orderListId"
                    ),

                "recovered":
                    True,

                "recovered_at":
                    now_ms()
            }

            save_state()

            log("")
            log(
                f"♻️ تم استعادة OCO: "
                f"{symbol}"
            )

            log(
                f"💵 Entry: {entry:.8f}"
            )

            log(
                f"🎯 TP: {tp:.8f}"
            )

            log(
                f"🛑 SL: {sl:.8f}"
            )

            log(
                "🛡️ الحماية موجودة في Binance"
            )

            return True

        return False

    except Exception as e:

        log(
            f"⚠️ استعادة OCO: {e}"
        )

        return False


# ============================================================
# RECOVERY FROM BALANCE + BUY HISTORY
# ============================================================

def recover_from_balances():

    try:

        balances = get_balances()

        candidates = []

        for asset, balance in balances.items():

            if asset == "USDT":

                continue

            if balance["total"] <= 0:

                continue

            symbol = (
                asset
                + "USDT"
            )

            if symbol not in symbols_info:

                continue

            candidates.append(
                (
                    symbol,
                    balance["total"]
                )
            )

        if not candidates:

            return False

        log(
            f"🔍 فحص "
            f"{len(candidates)} رصيد "
            f"لاستعادة الصفقة..."
        )

        # الأكبر أولًا
        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        for symbol, balance_qty in candidates:

            buy = find_latest_buy_for_recovery(
                symbol,
                balance_qty
            )

            if not buy:

                continue

            entry = buy[
                "entry_price"
            ]

            tp = (
                entry
                * (1 + TP_PERCENT)
            )

            sl = (
                entry
                * (1 - SL_PERCENT)
            )

            log("")
            log(
                f"♻️ اكتشاف صفقة البوت: "
                f"{symbol}"
            )

            log(
                f"💵 Entry: {entry:.8f}"
            )

            log(
                f"📦 Qty: {balance_qty}"
            )

            log(
                f"🎯 TP: {tp:.8f}"
            )

            log(
                f"🛑 SL: {sl:.8f}"
            )

            state[
                "active_trade"
            ] = {

                "symbol":
                    symbol,

                "quantity":
                    balance_qty,

                "entry_price":
                    entry,

                "tp":
                    tp,

                "sl":
                    sl,

                "buy_order_id":
                    buy["order_id"],

                "recovered":
                    True,

                "recovered_at":
                    now_ms()
            }

            save_state()

            # =================================================
            # نتأكد من وجود حماية
            # =================================================

            open_orders = get_open_orders(
                symbol
            )

            sell_orders = [

                order

                for order in open_orders

                if order.get(
                    "side"
                ) == "SELL"

            ]

            if sell_orders:

                log(
                    "🛡️ أوامر البيع "
                    "موجودة بالفعل"
                )

            else:

                log(
                    "⚠️ لا توجد حماية "
                    "→ إنشاء OCO"
                )

                try:

                    place_oco(
                        symbol,
                        balance_qty,
                        tp,
                        sl
                    )

                    log(
                        "✅ تمت حماية "
                        "الصفقة المستعادة"
                    )

                except Exception as e:

                    log(
                        f"🚨 فشل إنشاء OCO: "
                        f"{e}"
                    )

                    # لا نفتح صفقة جديدة
                    # ونبقي الحالة نشطة
                    # حتى لا نفقد معرفة الصفقة

                    state[
                        "status"
                    ] = (
                        "⚠️ صفقة مستعادة "
                        "بدون OCO"
                    )

                    save_state()

                    return True

            return True

        return False

    except Exception as e:

        log(
            f"⚠️ استعادة الأرصدة: {e}"
        )

        return False


# ============================================================
# MAIN RECOVERY
# ============================================================

def restore_trade():

    log("")
    log(
        "🔄 فحص الصفقات بعد التشغيل..."
    )

    # 1
    if recover_saved_trade():

        log(
            "✅ تم استرجاع الصفقة "
            "من ملف البيانات"
        )

        return True

    # 2
    if recover_open_oco():

        return True

    # 3
    if recover_from_balances():

        return True

    state[
        "active_trade"
    ] = None

    save_state()

    log(
        "ℹ️ لا توجد صفقة مفتوحة للبوت"
    )

    return False


# ============================================================
# GET 24H SYMBOLS
# ============================================================

def get_symbols():

    data = public_get(
        "/api/v3/ticker/24hr"
    )

    result = []

    for item in data:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith(
            "USDT"
        ):

            continue

        if symbol not in symbols_info:

            continue

        try:

            volume = float(
                item.get(
                    "quoteVolume",
                    0
                )
            )

        except:

            continue

        if volume < MIN_VOLUME:

            continue

        result.append(
            (
                symbol,
                volume
            )
        )

    # الأعلى حجمًا أولًا
    result.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return [
        x[0]
        for x in result
    ]


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol
):

    return public_get(
        "/api/v3/klines",
        {
            "symbol":
                symbol,

            "interval":
                TIMEFRAME,

            "limit":
                2
        }
    )


# ============================================================
# SIGNAL
# ============================================================

def check_signal(
    symbol
):

    candles = get_klines(
        symbol
    )

    if len(candles) < 2:

        return False

    previous = candles[-2]

    current = candles[-1]

    previous_close = float(
        previous[4]
    )

    current_low = float(
        current[3]
    )

    trigger = (
        previous_close
        * (1 - DROP_PERCENT)
    )

    return (
        current_low <= trigger
    )


# ============================================================
# SCAN
# ============================================================

def scan_market():

    symbols = get_symbols()

    log(
        f"🔎 فحص "
        f"{len(symbols)} عملة..."
    )

    for index, symbol in enumerate(
        symbols,
        1
    ):

        # إذا فيه صفقة توقف فورًا
        if state.get(
            "active_trade"
        ):

            return

        try:

            signal = check_signal(
                symbol
            )

            if signal:

                log("")
                log(
                    f"🚨 إشارة شراء "
                    f"[{index}/{len(symbols)}] "
                    f"{symbol}"
                )

                execute_trade(
                    symbol
                )

                return

            # رسالة كل 50 عملة
            if index % 50 == 0:

                log(
                    f"🔍 وصل الفحص "
                    f"{index}/{len(symbols)}"
                )

        except Exception as e:

            message = str(e)

            if (
                "429" in message
                or "418" in message
            ):

                log(
                    "🛑 تم إيقاف دورة الفحص "
                    "بسبب حماية Binance"
                )

                return

            log(
                f"⚠️ {symbol}: {e}"
            )


# ============================================================
# EXECUTE TRADE
# ============================================================

def execute_trade(
    symbol
):

    try:

        # ================================================
        # BUY
        # ================================================

        result = market_buy(
            symbol
        )

        executed_qty = float(
            result.get(
                "executedQty",
                0
            )
        )

        quote_qty = float(
            result.get(
                "cummulativeQuoteQty",
                TRADE_USDT
            )
        )

        if executed_qty <= 0:

            log(
                "❌ الشراء لم ينفذ"
            )

            return

        entry = (
            quote_qty
            / executed_qty
        )

        tp = (
            entry
            * (1 + TP_PERCENT)
        )

        sl = (
            entry
            * (1 - SL_PERCENT)
        )

        trade = {

            "symbol":
                symbol,

            "quantity":
                executed_qty,

            "entry_price":
                entry,

            "tp":
                tp,

            "sl":
                sl,

            "buy_order_id":
                result.get(
                    "orderId"
                ),

            "created_at":
                now_ms()
        }

        # نحفظ فورًا
        state[
            "active_trade"
        ] = trade

        state[
            "status"
        ] = "🟢 صفقة مفتوحة"

        save_state()

        log(
            f"✅ تم الشراء "
            f"{symbol}"
        )

        log(
            f"💵 Entry: {entry:.8f}"
        )

        log(
            f"🎯 TP: {tp:.8f}"
        )

        log(
            f"🛑 SL: {sl:.8f}"
        )

        # ================================================
        # OCO
        # ================================================

        try:

            place_oco(
                symbol,
                executed_qty,
                tp,
                sl
            )

            log(
                "🛡️ OCO مفعل ✅"
            )

            return

        except Exception as e:

            log(
                f"🚨 فشل OCO: {e}"
            )

            # لا نفتح صفقة ثانية
            # ونحاول إعادة الحماية لاحقًا

            state[
                "status"
            ] = (
                "⚠️ صفقة مفتوحة "
                "والحماية تحتاج إعادة"
            )

            save_state()

            return

    except Exception as e:

        log(
            f"❌ خطأ تنفيذ الصفقة: {e}"
        )


# ============================================================
# MONITOR ACTIVE TRADE
# ============================================================

def monitor_trade():

    while True:

        try:

            trade = state.get(
                "active_trade"
            )

            if not trade:

                time.sleep(10)

                continue

            symbol = trade[
                "symbol"
            ]

            base = symbols_info[
                symbol
            ]["base"]

            balance = get_balance(
                base
            )

            # ============================================
            # إذا الكمية موجودة
            # ============================================

            if balance["total"] > 0:

                trade[
                    "quantity"
                ] = balance["total"]

                # فحص حماية Binance
                open_orders = get_open_orders(
                    symbol
                )

                sell_orders = [

                    o

                    for o in open_orders

                    if o.get(
                        "side"
                    ) == "SELL"

                ]

                if not sell_orders:

                    log(
                        f"⚠️ {symbol} "
                        "بدون حماية → محاولة OCO"
                    )

                    try:

                        place_oco(
                            symbol,
                            balance["total"],
                            trade["tp"],
                            trade["sl"]
                        )

                        log(
                            f"🛡️ تمت إعادة "
                            f"الحماية {symbol}"
                        )

                    except Exception as e:

                        log(
                            f"⚠️ OCO: {e}"
                        )

                state[
                    "status"
                ] = (
                    f"🟢 صفقة مفتوحة "
                    f"{symbol}"
                )

                save_state()

                time.sleep(20)

                continue

            # ============================================
            # الرصيد اختفى
            # يعني الصفقة انتهت غالبًا
            # ============================================

            log(
                f"🏁 انتهت الصفقة "
                f"{symbol}"
            )

            final_price = 0.0

            try:

                final_price = get_current_price(
                    symbol
                )

            except:

                pass

            record_trade(
                trade,
                final_price
            )

            state[
                "active_trade"
            ] = None

            state[
                "status"
            ] = "🔍 يبحث عن فرص"

            save_state()

        except Exception as e:

            log(
                f"⚠️ مراقبة الصفقة: {e}"
            )

        time.sleep(20)


# ============================================================
# RECORD TRADE
# ============================================================

def record_trade(
    trade,
    exit_price
):

    entry = float(
        trade["entry_price"]
    )

    qty = float(
        trade["quantity"]
    )

    if exit_price <= 0:

        return

    profit = (
        exit_price
        - entry
    ) * qty

    percent = (
        (exit_price - entry)
        / entry
    ) * 100

    if profit >= 0:

        state[
            "wins"
        ] += 1

    else:

        state[
            "losses"
        ] += 1

    state[
        "total_profit"
    ] += profit

    state[
        "trades"
    ].append({

        "symbol":
            trade["symbol"],

        "entry":
            entry,

        "exit":
            exit_price,

        "quantity":
            qty,

        "profit":
            profit,

        "profit_percent":
            percent,

        "time":
            now_ms()
    })

    log(
        f"💰 النتيجة "
        f"{profit:+.4f} USDT "
        f"({percent:+.2f}%)"
    )


# ============================================================
# TRADING LOOP
# ============================================================

def trading_loop():

    log("")
    log(
        "🚀 بدأ محرك التداول"
    )
    log("")

    while True:

        try:

            # لا يبحث أثناء وجود صفقة
            if state.get(
                "active_trade"
            ):

                time.sleep(20)

                continue

            state[
                "status"
            ] = "🔍 يبحث عن فرص"

            state[
                "last_scan"
            ] = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            save_state()

            scan_market()

            # =========================================
            # بعد الفحص
            # =========================================

            if not state.get(
                "active_trade"
            ):

                log(
                    f"⏳ انتهاء الفحص "
                    f"→ انتظار {SCAN_INTERVAL}s"
                )

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            log(
                f"🚨 محرك التداول: {e}"
            )

            state[
                "last_error"
            ] = str(e)

            save_state()

            time.sleep(30)


# ============================================================
# DASHBOARD
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

body{

    margin:0;

    background:#0f1115;

    color:#fff;

    font-family:Arial;

}

.container{

    max-width:900px;

    margin:auto;

    padding:15px;

}

h1{

    text-align:center;

}

.card{

    background:#181b22;

    border-radius:15px;

    padding:15px;

    margin:10px 0;

}

.row{

    display:flex;

    justify-content:space-between;

    padding:10px 0;

    border-bottom:1px solid #292d36;

}

.green{

    color:#00e676;

}

.red{

    color:#ff5252;

}

.yellow{

    color:#ffd740;

}

.big{

    font-size:24px;

    font-weight:bold;

}

</style>

</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود</h1>

<div class="card">

<div class="row">

<span>Binance</span>

<span id="binance">...</span>

</div>

<div class="row">

<span>الحالة</span>

<span id="status">...</span>

</div>

<div class="row">

<span>العملات</span>

<span id="symbols">...</span>

</div>

<div class="row">

<span>USDT</span>

<span id="balance">...</span>

</div>

</div>


<div class="card">

<h2>📊 الصفقة الحالية</h2>

<div id="trade">

لا توجد صفقة

</div>

</div>


<div class="card">

<h2>📈 الإحصائيات</h2>

<div class="row">

<span>إجمالي الصفقات</span>

<span id="trades">0</span>

</div>

<div class="row">

<span>الفوز</span>

<span class="green" id="wins">0</span>

</div>

<div class="row">

<span>الخسارة</span>

<span class="red" id="losses">0</span>

</div>

<div class="row">

<span>نسبة الفوز</span>

<span id="winrate">0%</span>

</div>

<div class="row">

<span>الربح</span>

<span id="profit">0</span>

</div>

</div>

</div>


<script>

async function update(){

    try{

        const response =
            await fetch('/api/status');

        const data =
            await response.json();

        document.getElementById(
            'binance'
        ).innerHTML =
            data.binance
            ? '<span class="green">متصل ✅</span>'
            : '<span class="red">غير متصل ❌</span>';

        document.getElementById(
            'status'
        ).innerText =
            data.status;

        document.getElementById(
            'symbols'
        ).innerText =
            data.symbols_count;

        document.getElementById(
            'balance'
        ).innerText =
            Number(data.balance).toFixed(4);

        document.getElementById(
            'trades'
        ).innerText =
            data.trades;

        document.getElementById(
            'wins'
        ).innerText =
            data.wins;

        document.getElementById(
            'losses'
        ).innerText =
            data.losses;

        document.getElementById(
            'winrate'
        ).innerText =
            Number(data.winrate).toFixed(2)
            + '%';

        document.getElementById(
            'profit'
        ).innerText =
            Number(data.total_profit).toFixed(4)
            + ' USDT';

        if(data.active_trade){

            const t =
                data.active_trade;

            document.getElementById(
                'trade'
            ).innerHTML = `

                <div class="row">
                    <span>العملة</span>
                    <b>${t.symbol}</b>
                </div>

                <div class="row">
                    <span>الدخول</span>
                    <span>${Number(t.entry_price).toFixed(8)}</span>
                </div>

                <div class="row">
                    <span>السعر الحالي</span>
                    <span>${Number(data.current_price).toFixed(8)}</span>
                </div>

                <div class="row">
                    <span>الهدف</span>
                    <span class="green">${Number(t.tp).toFixed(8)}</span>
                </div>

                <div class="row">
                    <span>الوقف</span>
                    <span class="red">${Number(t.sl).toFixed(8)}</span>
                </div>

                <div class="row">
                    <span>الربح/الخسارة</span>
                    <b>${Number(data.trade_pnl).toFixed(2)}%</b>
                </div>

            `;

        }else{

            document.getElementById(
                'trade'
            ).innerHTML =
                '<span class="yellow">لا توجد صفقة مفتوحة</span>';

        }

    }catch(error){

        console.log(error);

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
# API STATUS
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    balance = 0.0

    try:

        usdt = get_balance(
            "USDT"
        )

        balance = (
            usdt["free"]
            + usdt["locked"]
        )

        state[
            "binance"
        ] = True

    except Exception:

        state[
            "binance"
        ] = False

    active = state.get(
        "active_trade"
    )

    current_price = 0.0

    pnl = 0.0

    if active:

        try:

            current_price = get_current_price(
                active["symbol"]
            )

            entry = float(
                active["entry_price"]
            )

            pnl = (
                (
                    current_price
                    - entry
                )
                / entry
            ) * 100

        except:

            pass

    total_trades = (
        state["wins"]
        + state["losses"]
    )

    winrate = (

        (
            state["wins"]
            / total_trades
        ) * 100

        if total_trades > 0

        else 0
    )

    return jsonify({

        "binance":
            state["binance"],

        "status":
            state["status"],

        "symbols_count":
            state["symbols_count"],

        "balance":
            balance,

        "active_trade":
            active,

        "current_price":
            current_price,

        "trade_pnl":
            pnl,

        "trades":
            total_trades,

        "wins":
            state["wins"],

        "losses":
            state["losses"],

        "winrate":
            winrate,

        "total_profit":
            state["total_profit"],

        "last_scan":
            state["last_scan"],

        "last_error":
            state["last_error"]

    })


# ============================================================
# START BOT
# ============================================================

def start_bot():

    log("")
    log("=" * 60)
    log(
        "🤖 مضارب أبو سعود"
    )
    log("=" * 60)

    log(
        "📉 نزول 2% → شراء"
    )

    log(
        "🎯 TP +2%"
    )

    log(
        "🛑 SL -2%"
    )

    log(
        "⏱️ 15 دقيقة"
    )

    log(
        f"💰 مبلغ الصفقة: "
        f"{TRADE_USDT} USDT"
    )

    log(
        "🛡️ حماية Binance OCO"
    )

    log(
        "♻️ استعادة الصفقات"
    )

    log(
        "🛡️ حماية من 429"
    )

    log("=" * 60)
    log("")

    if not API_KEY or not API_SECRET:

        log(
            "❌ مفاتيح Binance غير موجودة"
        )

        state[
            "status"
        ] = "❌ مفاتيح Binance ناقصة"

        return

    try:

        load_state()

        load_exchange_info()

        get_account()

        state[
            "binance"
        ] = True

        log(
            "🔗 Binance متصل ✅"
        )

        # ====================================================
        # الاستعادة قبل أي شراء
        # ====================================================

        restored = restore_trade()

        if restored:

            state[
                "status"
            ] = "♻️ تم استعادة الصفقة"

        else:

            state[
                "status"
            ] = "🔍 يبحث عن فرص"

        save_state()

        # ====================================================
        # MONITOR
        # ====================================================

        monitor_thread = threading.Thread(
            target=monitor_trade,
            daemon=True
        )

        monitor_thread.start()

        # ====================================================
        # TRADING
        # ====================================================

        trading_thread = threading.Thread(
            target=trading_loop,
            daemon=True
        )

        trading_thread.start()

    except Exception as e:

        log(
            f"🚨 خطأ التشغيل: {e}"
        )

        state[
            "status"
        ] = "❌ خطأ"

        state[
            "last_error"
        ] = str(e)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    start_bot()

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    log(
        f"🌐 PORT = {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
