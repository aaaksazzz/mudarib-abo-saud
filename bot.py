import os
import time
import json
import hmac
import hashlib
import urllib.parse
import threading
import math
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify

# ============================================================
# مضارب أبو سعود V2 PRO 🤖
# Binance Spot
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

API_BASE = "https://api.binance.com"
MARKET_BASE = "https://data-api.binance.vision"

STATE_FILE = "state.json"
HISTORY_FILE = "trade_history.json"

MIN_USDT = 5.0
TRADE_USDT_PERCENT = 0.999

SCAN_INTERVAL = 180
POSITION_CHECK_SECONDS = 5

# ============================================================
# الخروج
# ============================================================

INITIAL_STOP = -0.02
INITIAL_TARGET = 0.02

PROFIT_STEP = 0.01
TARGET_DISTANCE = 0.02

FEE_RATE = 0.001

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

exchange_cache = {}

last_scan = ""
last_signal = ""
last_error = ""

scan_count = 0


# ============================================================
# أدوات
# ============================================================

def log(msg):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        log(f"خطأ قراءة {filename}: {e}")
        return default


def save_json(filename, data):
    tmp = filename + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(tmp, filename)


def load_state():
    return load_json(STATE_FILE, {})


def save_state(data):
    save_json(STATE_FILE, data)


def load_history():
    return load_json(HISTORY_FILE, [])


def save_history(data):
    save_json(HISTORY_FILE, data)


def floor_step(value, step):
    try:
        v = Decimal(str(value))
        s = Decimal(str(step))

        return float(
            (v / s).to_integral_value(
                rounding=ROUND_DOWN
            ) * s
        )

    except Exception:
        return float(value)


# ============================================================
# Binance Signed API
# ============================================================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception(
            "BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود"
        )

    params = dict(params or {})

    params["timestamp"] = int(
        time.time() * 1000
    )

    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    url = (
        f"{API_BASE}{path}"
        f"?{query}"
        f"&signature={signature}"
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=20
    )

    if response.status_code >= 400:

        raise Exception(
            f"Binance {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# ============================================================
# Binance Public API
# ============================================================

def public_get(path, params=None):

    url = f"{MARKET_BASE}{path}"

    response = requests.get(
        url,
        params=params or {},
        timeout=20
    )

    if response.status_code >= 400:

        raise Exception(
            f"Market {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# ============================================================
# Account
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_asset_free(asset):

    account = get_account()

    for balance in account.get(
        "balances",
        []
    ):

        if balance["asset"] == asset:

            return float(
                balance["free"]
            )

    return 0.0


def get_usdt_balance():

    return get_asset_free("USDT")


# ============================================================
# Exchange Info
# مهم: Public وليس Signed
# ============================================================

def get_exchange_info():

    global exchange_cache

    if exchange_cache:
        return exchange_cache

    url = f"{API_BASE}/api/v3/exchangeInfo"

    response = requests.get(
        url,
        timeout=20
    )

    if response.status_code >= 400:

        raise Exception(
            f"ExchangeInfo "
            f"{response.status_code}: "
            f"{response.text}"
        )

    exchange_cache = response.json()

    return exchange_cache


def get_symbol_info(symbol):

    info = get_exchange_info()

    for item in info.get(
        "symbols",
        []
    ):

        if item["symbol"] == symbol:
            return item

    raise Exception(
        f"لا توجد معلومات للعملة {symbol}"
    )


def get_filters(symbol):

    info = get_symbol_info(symbol)

    tick_size = 0.00000001
    step_size = 0.00000001
    min_qty = 0.0
    min_notional = 0.0

    for f in info.get(
        "filters",
        []
    ):

        if f["filterType"] == "PRICE_FILTER":

            tick_size = float(
                f["tickSize"]
            )

        elif f["filterType"] == "LOT_SIZE":

            step_size = float(
                f["stepSize"]
            )

            min_qty = float(
                f["minQty"]
            )

        elif f["filterType"] in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = float(
                f.get(
                    "minNotional",
                    f.get(
                        "notional",
                        0
                    )
                )
            )

    return (
        tick_size,
        step_size,
        min_qty,
        min_notional
    )


# ============================================================
# السعر
# ============================================================

def get_price(symbol):

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
# شراء Market
# ============================================================

def market_buy(symbol, usdt_amount):

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty":
                f"{usdt_amount:.8f}",
            "newOrderRespType": "FULL"
        }
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
            0
        )
    )

    if executed_qty <= 0:
        raise Exception(
            "عملية الشراء لم تنفذ"
        )

    entry = (
        quote_qty / executed_qty
    )

    return {
        "orderId":
            result["orderId"],

        "qty":
            executed_qty,

        "entry":
            entry,

        "raw":
            result
    }


# ============================================================
# OCO
# ============================================================

def place_oco(
    symbol,
    qty,
    stop_price,
    target_price
):

    tick, step, min_qty, min_notional = \
        get_filters(symbol)

    qty = floor_step(
        qty,
        step
    )

    stop_price = floor_step(
        stop_price,
        tick
    )

    target_price = floor_step(
        target_price,
        tick
    )

    if qty < min_qty:

        raise Exception(
            f"الكمية {qty} أقل من "
            f"الحد الأدنى {min_qty}"
        )

    current = get_price(
        symbol
    )

    if target_price <= current:

        raise Exception(
            f"الهدف {target_price} "
            f"أقل أو يساوي السعر الحالي "
            f"{current}"
        )

    if stop_price >= current:

        raise Exception(
            f"الوقف {stop_price} "
            f"أعلى أو يساوي السعر الحالي "
            f"{current}"
        )

    quantity_text = (
        f"{qty:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    stop_text = (
        f"{stop_price:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    target_text = (
        f"{target_price:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    params = {

        "symbol":
            symbol,

        "side":
            "SELL",

        "quantity":
            quantity_text,

        "aboveType":
            "TAKE_PROFIT",

        "aboveStopPrice":
            target_text,

        "belowType":
            "STOP_LOSS",

        "belowStopPrice":
            stop_text,

        "newOrderRespType":
            "RESULT"
    }

    result = signed_request(
        "POST",
        "/api/v3/orderList/oco",
        params
    )

    reports = result.get(
        "orderReports",
        []
    )

    above_order_id = None
    below_order_id = None

    for order in reports:

        order_type = order.get(
            "type"
        )

        if order_type == "TAKE_PROFIT":

            above_order_id = order.get(
                "orderId"
            )

        elif order_type == "STOP_LOSS":

            below_order_id = order.get(
                "orderId"
            )

    return {

        "orderListId":
            result.get(
                "orderListId"
            ),

        "aboveOrderId":
            above_order_id,

        "belowOrderId":
            below_order_id,

        "stop_price":
            stop_price,

        "target_price":
            target_price,

        "qty":
            qty
    }


def cancel_oco(
    symbol,
    order_list_id
):

    if not order_list_id:
        return

    try:

        signed_request(
            "DELETE",
            "/api/v3/orderList",
            {
                "symbol":
                    symbol,

                "orderListId":
                    int(order_list_id)
            }
        )

        log(
            f"✅ تم إلغاء OCO "
            f"{order_list_id}"
        )

    except Exception as e:

        log(
            f"⚠️ تعذر إلغاء OCO: {e}"
        )


def get_order(
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
                int(order_id)
        }
    )


# ============================================================
# مستويات الوقف والهدف
# ============================================================

def get_levels(
    entry,
    level
):

    if level <= 0:

        stop_profit = INITIAL_STOP
        target_profit = INITIAL_TARGET

    else:

        stop_profit = (
            level * PROFIT_STEP
        )

        target_profit = (
            stop_profit
            + TARGET_DISTANCE
        )

    stop_price = (
        entry *
        (1 + stop_profit)
    )

    target_price = (
        entry *
        (1 + target_profit)
    )

    return (
        stop_profit,
        target_profit,
        stop_price,
        target_price
    )


def current_profit(
    entry,
    price
):

    return (
        (price - entry)
        / entry
    )


def profit_level(profit):

    if profit < PROFIT_STEP:
        return 0

    return int(
        math.floor(
            (
                profit
                + 0.000000001
            )
            / PROFIT_STEP
        )
    )


# ============================================================
# إنشاء OCO للصفقة
# ============================================================

def create_oco_for_state(
    trade,
    level
):

    symbol = trade["symbol"]
    entry = float(
        trade["entry"]
    )

    (
        stop_profit,
        target_profit,
        stop_price,
        target_price
    ) = get_levels(
        entry,
        level
    )

    current = get_price(
        symbol
    )

    if current >= target_price:

        raise Exception(
            f"السعر الحالي {current} "
            f"تجاوز الهدف {target_price}"
        )

    if current <= stop_price:

        raise Exception(
            f"السعر الحالي {current} "
            f"تحت الوقف {stop_price}"
        )

    base_asset = symbol[:-4]

    free_qty = get_asset_free(
        base_asset
    )

    tick, step, min_qty, min_notional = \
        get_filters(symbol)

    qty = floor_step(
        min(
            free_qty,
            float(trade["qty"])
        ),
        step
    )

    if qty <= 0:

        raise Exception(
            "لا توجد كمية متاحة للبيع"
        )

    if min_notional > 0:

        if qty * current < min_notional:

            raise Exception(
                f"قيمة الصفقة أقل من "
                f"الحد الأدنى {min_notional}"
            )

    oco = place_oco(
        symbol,
        qty,
        stop_price,
        target_price
    )

    trade["oco"] = oco

    trade["order_list_id"] = \
        oco["orderListId"]

    trade["above_order_id"] = \
        oco["aboveOrderId"]

    trade["below_order_id"] = \
        oco["belowOrderId"]

    trade["stop_price"] = \
        oco["stop_price"]

    trade["target_price"] = \
        oco["target_price"]

    trade["locked_profit"] = \
        stop_profit

    trade["target_profit"] = \
        target_profit

    trade["level"] = level

    trade["stop_status"] = \
        "ACTIVE"

    trade["oco_status"] = \
        "EXECUTING"

    save_state(trade)

    log(
        f"🛡️ {symbol} | "
        f"وقف {stop_profit * 100:.0f}% | "
        f"هدف {target_profit * 100:.0f}%"
    )


# ============================================================
# فتح صفقة
# ============================================================

def open_trade(signal):

    global last_error

    balance = get_usdt_balance()

    amount = (
        balance *
        TRADE_USDT_PERCENT
    )

    if amount < MIN_USDT:

        raise Exception(
            f"الرصيد {balance:.4f} USDT "
            f"أقل من {MIN_USDT}"
        )

    symbol = signal["symbol"]

    log(
        f"🟢 شراء {symbol} "
        f"بمبلغ {amount:.4f} USDT"
    )

    result = market_buy(
        symbol,
        amount
    )

    trade = {

        "symbol":
            symbol,

        "entry":
            result["entry"],

        "current_price":
            result["entry"],

        "qty":
            result["qty"],

        "order_id":
            result["orderId"],

        "opened_at":
            now_text(),

        "profit_percent":
            0,

        "profit_usdt":
            0,

        "status":
            "متعادل",

        "status_en":
            "EVEN",

        "level":
            0,

        "locked_profit":
            INITIAL_STOP,

        "target_profit":
            INITIAL_TARGET,

        "stop_price":
            result["entry"]
            * (1 + INITIAL_STOP),

        "target_price":
            result["entry"]
            * (1 + INITIAL_TARGET),

        "order_list_id":
            None,

        "above_order_id":
            None,

        "below_order_id":
            None,

        "stop_status":
            "PENDING",

        "oco_status":
            "PENDING"
    }

    save_state(
        trade
    )

    success = False

    for attempt in range(3):

        try:

            create_oco_for_state(
                trade,
                0
            )

            success = True
            break

        except Exception as e:

            last_error = str(e)

            log(
                f"⚠️ OCO محاولة "
                f"{attempt + 1}/3: {e}"
            )

            time.sleep(1)

    if not success:

        raise Exception(
            "فشل إنشاء OCO بعد 3 محاولات"
        )

    return trade


# ============================================================
# تسجيل الصفقة
# ============================================================

def record_closed_trade(
    trade,
    exit_price,
    reason
):

    history = load_history()

    entry = float(
        trade["entry"]
    )

    qty = float(
        trade["qty"]
    )

    gross = (
        exit_price - entry
    ) * qty

    fees = (
        abs(entry * qty)
        * FEE_RATE
        +
        abs(exit_price * qty)
        * FEE_RATE
    )

    net = gross - fees

    invested = (
        entry * qty
    )

    profit_percent = (
        net / invested * 100
        if invested > 0
        else 0
    )

    item = {

        "symbol":
            trade["symbol"],

        "entry":
            entry,

        "exit":
            exit_price,

        "qty":
            qty,

        "profit_usdt":
            net,

        "profit_percent":
            profit_percent,

        "opened_at":
            trade.get(
                "opened_at"
            ),

        "closed_at":
            now_text(),

        "reason":
            reason
    }

    history.append(
        item
    )

    save_history(
        history
    )

    log(
        f"🔴 إغلاق {trade['symbol']} | "
        f"{reason} | "
        f"{net:.4f} USDT"
    )


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position():

    global last_error

    trade = load_state()

    if not trade:
        return

    symbol = trade.get(
        "symbol"
    )

    if not symbol:
        return

    try:

        price = get_price(
            symbol
        )

        entry = float(
            trade["entry"]
        )

        qty = float(
            trade["qty"]
        )

        profit = current_profit(
            entry,
            price
        )

        trade["current_price"] = \
            price

        trade["profit_percent"] = \
            profit * 100

        trade["profit_usdt"] = \
            (price - entry) * qty

        if profit > 0:

            trade["status"] = "ربح"
            trade["status_en"] = "PROFIT"

        elif profit < 0:

            trade["status"] = "خسارة"
            trade["status_en"] = "LOSS"

        else:

            trade["status"] = "متعادل"
            trade["status_en"] = "EVEN"

        # ====================================================
        # فحص الهدف
        # ====================================================

        above_id = trade.get(
            "above_order_id"
        )

        below_id = trade.get(
            "below_order_id"
        )

        if above_id:

            try:

                above = get_order(
                    symbol,
                    above_id
                )

                if above.get(
                    "status"
                ) == "FILLED":

                    executed = float(
                        above.get(
                            "executedQty",
                            0
                        )
                    )

                    quote = float(
                        above.get(
                            "cummulativeQuoteQty",
                            0
                        )
                    )

                    exit_price = (
                        quote / executed
                        if executed > 0
                        else price
                    )

                    record_closed_trade(
                        trade,
                        exit_price,
                        "TAKE_PROFIT"
                    )

                    save_state({})
                    return

            except Exception as e:

                last_error = str(e)

        # ====================================================
        # فحص الوقف
        # ====================================================

        if below_id:

            try:

                below = get_order(
                    symbol,
                    below_id
                )

                if below.get(
                    "status"
                ) == "FILLED":

                    executed = float(
                        below.get(
                            "executedQty",
                            0
                        )
                    )

                    quote = float(
                        below.get(
                            "cummulativeQuoteQty",
                            0
                        )
                    )

                    exit_price = (
                        quote / executed
                        if executed > 0
                        else price
                    )

                    record_closed_trade(
                        trade,
                        exit_price,
                        "STOP_LOSS"
                    )

                    save_state({})
                    return

            except Exception as e:

                last_error = str(e)

        # ====================================================
        # تحريك الوقف والهدف
        # ====================================================

        level = profit_level(
            profit
        )

        old_level = int(
            trade.get(
                "level",
                0
            )
        )

        if level > old_level:

            log(
                f"🚀 {symbol} وصل "
                f"+{level}% "
                f"→ تحريك الحماية"
            )

            old_oco = trade.get(
                "order_list_id"
            )

            if old_oco:

                cancel_oco(
                    symbol,
                    old_oco
                )

            success = False

            for attempt in range(3):

                try:

                    create_oco_for_state(
                        trade,
                        level
                    )

                    success = True
                    break

                except Exception as e:

                    last_error = str(e)

                    log(
                        f"⚠️ تحديث OCO "
                        f"{attempt + 1}/3: {e}"
                    )

                    time.sleep(1)

            if not success:

                log(
                    "🚨 فشل تحديث OCO"
                )

        save_state(
            trade
        )

    except Exception as e:

        last_error = str(e)

        log(
            f"❌ خطأ إدارة الصفقة: {e}"
        )


# ============================================================
# استعادة الصفقة بعد إعادة التشغيل
# ============================================================

def restore_trade():

    trade = load_state()

    if not trade:
        return

    symbol = trade.get(
        "symbol"
    )

    if not symbol:
        return

    try:

        base = symbol[:-4]

        free = get_asset_free(
            base
        )

        if free <= 0:

            log(
                f"لا توجد كمية {base} "
                f"→ تنظيف الصفقة"
            )

            save_state({})
            return

        log(
            f"♻️ تم العثور على صفقة "
            f"{symbol}"
        )

        # إذا كانت الصفقة محفوظة بدون OCO
        if not trade.get(
            "order_list_id"
        ):

            log(
                "🛡️ إنشاء OCO للصفقة المستعادة"
            )

            create_oco_for_state(
                trade,
                int(
                    trade.get(
                        "level",
                        0
                    )
                )
            )

    except Exception as e:

        log(
            f"⚠️ استعادة الصفقة: {e}"
        )


# ============================================================
# الشموع
# ============================================================

def get_klines(
    symbol,
    interval,
    limit
):

    return public_get(
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


def ema(
    values,
    period
):

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    result = (
        sum(
            values[:period]
        )
        / period
    )

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
        ) + result

    return result


# ============================================================
# استراتيجية الدخول
# ============================================================

def scan_symbol(symbol):

    try:

        # ====================================================
        # 15 دقيقة
        # ====================================================

        k15 = get_klines(
            symbol,
            "15m",
            210
        )

        closes15 = [
            float(x[4])
            for x in k15
        ]

        highs15 = [
            float(x[2])
            for x in k15
        ]

        volumes15 = [
            float(x[5])
            for x in k15
        ]

        price = closes15[-1]

        ema200_15 = ema(
            closes15[-201:],
            200
        )

        resistance = max(
            highs15[-21:-1]
        )

        avg_volume = (
            sum(
                volumes15[-21:-1]
            )
            / 20
        )

        current_volume = \
            volumes15[-1]

        volume_ratio = (
            current_volume
            / avg_volume
            if avg_volume > 0
            else 0
        )

        breakout = (
            price - resistance
        ) / resistance

        move = (
            price - closes15[-2]
        ) / closes15[-2]

        # ====================================================
        # استراتيجية الدخول الأصلية
        # ====================================================

        if price <= ema200_15:
            return None

        if price <= resistance:
            return None

        if volume_ratio < 1.5:
            return None

        if move < 0.005:
            return None

        if move > 0.04:
            return None

        # ====================================================
        # 1H
        # ====================================================

        k1h = get_klines(
            symbol,
            "1h",
            210
        )

        closes1h = [
            float(x[4])
            for x in k1h
        ]

        ema200_1h = ema(
            closes1h[-201:],
            200
        )

        if price <= ema200_1h:
            return None

        return {

            "symbol":
                symbol,

            "price":
                price,

            "ema200_15":
                ema200_15,

            "ema200_1h":
                ema200_1h,

            "resistance":
                resistance,

            "volume_ratio":
                volume_ratio,

            "breakout":
                breakout,

            "move":
                move
        }

    except Exception:

        return None


# ============================================================
# العملات
# ============================================================

def get_usdt_symbols():

    info = get_exchange_info()

    symbols = []

    for s in info.get(
        "symbols",
        []
    ):

        if s.get(
            "status"
        ) != "TRADING":
            continue

        if s.get(
            "quoteAsset"
        ) != "USDT":
            continue

        if s.get(
            "isSpotTradingAllowed"
        ) is False:
            continue

        symbol = s["symbol"]

        if symbol.endswith(
            "USDT"
        ):

            symbols.append(
                symbol
            )

    return symbols


# ============================================================
# البوت
# ============================================================

def bot_loop():

    global last_scan
    global last_signal
    global last_error
    global scan_count

    log(
        "🚀 مضارب أبو سعود V2 بدأ"
    )

    restore_trade()

    while True:

        try:

            trade = load_state()

            # =================================================
            # صفقة مفتوحة
            # =================================================

            if trade and trade.get(
                "symbol"
            ):

                manage_position()

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # فحص السوق
            # =================================================

            last_scan = now_text()

            scan_count += 1

            symbols = get_usdt_symbols()

            log(
                f"🔎 فحص "
                f"{len(symbols)} عملة"
            )

            found = None

            for symbol in symbols:

                signal = scan_symbol(
                    symbol
                )

                if signal:

                    found = signal

                    last_signal = (
                        f"{symbol} | BUY | "
                        f"{signal['price']}"
                    )

                    log(
                        f"🔥 إشارة شراء: "
                        f"{symbol} | "
                        f"{signal['price']}"
                    )

                    break

            if found:

                try:

                    open_trade(
                        found
                    )

                except Exception as e:

                    last_error = str(e)

                    log(
                        f"❌ فشل فتح الصفقة: "
                        f"{e}"
                    )

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            last_error = str(e)

            log(
                f"❌ خطأ رئيسي: {e}"
            )

            time.sleep(10)


# ============================================================
# الإحصائيات
# ============================================================

def calculate_stats():

    history = load_history()

    now = datetime.now()

    daily = 0
    weekly = 0
    monthly = 0
    total = 0

    wins = 0
    losses = 0

    for trade in history:

        try:

            p = float(
                trade.get(
                    "profit_usdt",
                    0
                )
            )

            total += p

            if p > 0:
                wins += 1

            elif p < 0:
                losses += 1

            dt = datetime.strptime(
                trade["closed_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            days = (
                now - dt
            ).total_seconds() / 86400

            if days <= 1:
                daily += p

            if days <= 7:
                weekly += p

            if (
                dt.year == now.year
                and
                dt.month == now.month
            ):

                monthly += p

        except Exception:
            continue

    count = wins + losses

    win_rate = (
        wins / count * 100
        if count > 0
        else 0
    )

    return {

        "daily":
            daily,

        "weekly":
            weekly,

        "monthly":
            monthly,

        "total":
            total,

        "trades":
            count,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            win_rate
    }


# ============================================================
# API Dashboard
# ============================================================

@app.route("/api/dashboard")
def dashboard_api():

    return jsonify({

        "bot":
            "مضارب أبو سعود V2 PRO",

        "stats":
            calculate_stats(),

        "trade":
            load_state(),

        "scan_count":
            scan_count,

        "last_scan":
            last_scan,

        "last_signal":
            last_signal,

        "last_error":
            last_error,

        "server_time":
            now_text()
    })


@app.route("/health")
def health():

    return jsonify({

        "status":
            "ok",

        "time":
            now_text()
    })


# ============================================================
# Dashboard
# ============================================================

HTML = """
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1">

<title>
مضارب أبو سعود V2 PRO
</title>

<style>

body{
    margin:0;
    font-family:Arial;
    background:#0b1020;
    color:white;
}

.container{
    max-width:1100px;
    margin:auto;
    padding:20px;
}

h1{
    text-align:center;
}

.grid{
    display:grid;
    grid-template-columns:
    repeat(auto-fit,minmax(180px,1fr));
    gap:12px;
}

.card{
    background:#151c31;
    border-radius:15px;
    padding:18px;
    margin-bottom:15px;
}

.label{
    color:#9ca3af;
    font-size:13px;
}

.value{
    font-size:22px;
    font-weight:bold;
    margin-top:8px;
}

.green{
    color:#22c55e;
}

.red{
    color:#ef4444;
}

.row{
    display:flex;
    justify-content:space-between;
    padding:10px 0;
    border-bottom:1px solid #27304a;
}

.error{
    background:#450a0a;
    color:#f87171;
    padding:10px;
    border-radius:10px;
    margin-top:10px;
}

</style>

</head>

<body>

<div class="container">

<h1>
🤖 مضارب أبو سعود V2 PRO
</h1>

<div class="grid">

<div class="card">
<div class="label">ربح اليوم</div>
<div id="daily"
class="value">
0
</div>
</div>

<div class="card">
<div class="label">ربح الأسبوع</div>
<div id="weekly"
class="value">
0
</div>
</div>

<div class="card">
<div class="label">ربح الشهر</div>
<div id="monthly"
class="value">
0
</div>
</div>

<div class="card">
<div class="label">إجمالي الربح</div>
<div id="total"
class="value">
0
</div>
</div>

</div>

<div class="grid">

<div class="card">
<div class="label">عدد الصفقات</div>
<div id="trades"
class="value">
0
</div>
</div>

<div class="card">
<div class="label">الرابحة</div>
<div id="wins"
class="value green">
0
</div>
</div>

<div class="card">
<div class="label">الخاسرة</div>
<div id="losses"
class="value red">
0
</div>
</div>

<div class="card">
<div class="label">نسبة النجاح</div>
<div id="winrate"
class="value">
0%
</div>
</div>

</div>

<div class="card">

<h2>
📊 الصفقة الحالية
</h2>

<div id="noTrade">
لا توجد صفقة مفتوحة
</div>

<div id="trade"
style="display:none">

<div class="row">
<span>العملة</span>
<b id="symbol"></b>
</div>

<div class="row">
<span>الدخول</span>
<b id="entry"></b>
</div>

<div class="row">
<span>السعر الحالي</span>
<b id="current"></b>
</div>

<div class="row">
<span>الربح</span>
<b id="profit"></b>
</div>

<div class="row">
<span>وقف الخسارة</span>
<b id="stop"></b>
</div>

<div class="row">
<span>الهدف</span>
<b id="target"></b>
</div>

<div class="row">
<span>الربح المؤمّن</span>
<b id="locked"></b>
</div>

<div class="row">
<span>الهدف القادم</span>
<b id="targetProfit"></b>
</div>

<div class="row">
<span>مستوى الحماية</span>
<b id="level"></b>
</div>

<div class="row">
<span>حالة OCO</span>
<b id="oco"></b>
</div>

</div>

</div>

<div class="card">

<h2>
🤖 حالة البوت
</h2>

<div class="row">
<span>الفحوصات</span>
<b id="scans"></b>
</div>

<div class="row">
<span>آخر فحص</span>
<b id="lastScan"></b>
</div>

<div class="row">
<span>آخر إشارة</span>
<b id="lastSignal"></b>
</div>

<div id="error"></div>

</div>

</div>

<script>

function money(x){
    return Number(x || 0).toFixed(4);
}

async function update(){

    try{

        const response =
            await fetch(
                "/api/dashboard"
            );

        const data =
            await response.json();

        const stats =
            data.stats;

        document.getElementById(
            "daily"
        ).textContent =
            money(stats.daily)
            + " USDT";

        document.getElementById(
            "weekly"
        ).textContent =
            money(stats.weekly)
            + " USDT";

        document.getElementById(
            "monthly"
        ).textContent =
            money(stats.monthly)
            + " USDT";

        document.getElementById(
            "total"
        ).textContent =
            money(stats.total)
            + " USDT";

        document.getElementById(
            "trades"
        ).textContent =
            stats.trades;

        document.getElementById(
            "wins"
        ).textContent =
            stats.wins;

        document.getElementById(
            "losses"
        ).textContent =
            stats.losses;

        document.getElementById(
            "winrate"
        ).textContent =
            Number(
                stats.win_rate
            ).toFixed(1)
            + "%";

        document.getElementById(
            "scans"
        ).textContent =
            data.scan_count;

        document.getElementById(
            "lastScan"
        ).textContent =
            data.last_scan || "-";

        document.getElementById(
            "lastSignal"
        ).textContent =
            data.last_signal || "-";

        const trade =
            data.trade;

        if(
            trade &&
            trade.symbol
        ){

            document.getElementById(
                "noTrade"
            ).style.display =
                "none";

            document.getElementById(
                "trade"
            ).style.display =
                "block";

            document.getElementById(
                "symbol"
            ).textContent =
                trade.symbol;

            document.getElementById(
                "entry"
            ).textContent =
                trade.entry;

            document.getElementById(
                "current"
            ).textContent =
                trade.current_price;

            document.getElementById(
                "profit"
            ).textContent =
                Number(
                    trade.profit_percent || 0
                ).toFixed(2)
                + "%";

            document.getElementById(
                "stop"
            ).textContent =
                trade.stop_price;

            document.getElementById(
                "target"
            ).textContent =
                trade.target_price;

            document.getElementById(
                "locked"
            ).textContent =
                Number(
                    (trade.locked_profit || 0)
                    * 100
                ).toFixed(0)
                + "%";

            document.getElementById(
                "targetProfit"
            ).textContent =
                Number(
                    (trade.target_profit || 0)
                    * 100
                ).toFixed(0)
                + "%";

            document.getElementById(
                "level"
            ).textContent =
                "+"
                + (
                    trade.level || 0
                )
                + "%";

            document.getElementById(
                "oco"
            ).textContent =
                trade.oco_status || "-";

        }else{

            document.getElementById(
                "noTrade"
            ).style.display =
                "block";

            document.getElementById(
                "trade"
            ).style.display =
                "none";
        }

        const error =
            data.last_error || "";

        document.getElementById(
            "error"
        ).innerHTML =
            error
            ?
            '<div class="error">⚠️ '
            + error
            + '</div>'
            :
            '';

    }catch(e){

        document.getElementById(
            "error"
        ).innerHTML =
            '<div class="error">'
            + 'تعذر الاتصال بالبوت'
            + '</div>';
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


@app.route("/")
def home():
    return HTML


# ============================================================
# تشغيل
# ============================================================

def start_bot():

    thread = threading.Thread(
        target=bot_loop,
        daemon=True
    )

    thread.start()


if __name__ == "__main__":

    start_bot()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
