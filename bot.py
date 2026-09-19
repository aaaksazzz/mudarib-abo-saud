# ============================================================
# مضارب أبو سعود V2 PRO 🤖
# Binance Spot
# WebSocket Market Scanner
# Anti-429
# ============================================================

import os
import time
import json
import hmac
import hashlib
import threading
import urllib.parse
from decimal import Decimal, ROUND_DOWN

import requests
import websocket
from flask import Flask, jsonify

# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
WS_URL = "wss://stream.binance.com:9443/stream"

TIMEFRAME = "15m"
CONFIRM_TIMEFRAME = "1h"

EMA_PERIOD = 200
BREAKOUT_LOOKBACK = 20

VOLUME_MULTIPLIER = 1.5
MIN_MOVE = 0.005
MAX_MOVE = 0.04

TRADE_PERCENT = 0.999

MIN_USDT = 5.0

INITIAL_STOP = -0.02
INITIAL_TARGET = 0.012

LOCK_TRIGGER = 0.012
LOCK_PROFIT = 0.012

PROFIT_STEP = 0.01
TARGET_DISTANCE = 0.012

SCAN_PRINT_SECONDS = 30
ORDER_CHECK_SECONDS = 15

BOOTSTRAP_DELAY = 0.15

# عدد streams في اتصال WebSocket
STREAMS_PER_SOCKET = 150

# ============================================================
# GLOBAL
# ============================================================

app = Flask(__name__)

session = requests.Session()

market = {}
market_lock = threading.Lock()

symbols = []
symbol_info = {}

running = True

ws_connections = []
ws_threads = []

trade = None
trade_lock = threading.Lock()

last_signal_candle = {}

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
}

dashboard = {
    "binance_connected": False,
    "websocket_connected": 0,
    "symbols": 0,
    "last_error": "",
    "last_signal": "",
    "status": "بدء التشغيل",
}

account_cache = {
    "time": 0,
    "data": None,
}

# ============================================================
# LOG
# ============================================================

def log(msg):
    print(msg, flush=True)


# ============================================================
# EMA
# ============================================================

def ema(values, period=200):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:
        value = (price - value) * multiplier + value

    return value


# ============================================================
# BINANCE REST
# فقط للأوامر والحساب والتهيئة
# ============================================================

rest_lock = threading.Lock()
rest_cooldown = 0


def rest_request(method, path, params=None, signed=False, retries=5):

    global rest_cooldown

    params = params or {}

    for attempt in range(retries):

        now = time.time()

        if now < rest_cooldown:
            time.sleep(rest_cooldown - now)

        try:

            headers = {}

            if API_KEY:
                headers["X-MBX-APIKEY"] = API_KEY

            if signed:

                params["timestamp"] = int(time.time() * 1000)
                params["recvWindow"] = 10000

                query = urllib.parse.urlencode(params)

                signature = hmac.new(
                    API_SECRET.encode(),
                    query.encode(),
                    hashlib.sha256
                ).hexdigest()

                query += "&signature=" + signature

                url = BASE_URL + path + "?" + query

                r = session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=20
                )

            else:

                r = session.request(
                    method,
                    BASE_URL + path,
                    params=params,
                    headers=headers,
                    timeout=20
                )

            weight = r.headers.get("X-MBX-USED-WEIGHT-1M")

            if weight:

                try:
                    weight = int(weight)

                    if weight >= 5500:
                        rest_cooldown = time.time() + 10

                except:
                    pass

            if r.status_code == 429:

                retry_after = r.headers.get("Retry-After")

                wait = int(retry_after) if retry_after else min(
                    10 * (attempt + 1),
                    60
                )

                rest_cooldown = time.time() + wait

                log(
                    f"⚠️ Binance 429 - انتظار {wait} ثانية"
                )

                time.sleep(wait)
                continue

            if r.status_code >= 500:

                time.sleep(3 * (attempt + 1))
                continue

            r.raise_for_status()

            dashboard["binance_connected"] = True

            return r.json()

        except Exception as e:

            dashboard["last_error"] = str(e)

            log(f"⚠️ REST: {e}")

            time.sleep(2 * (attempt + 1))

    return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def load_exchange_info():

    global symbols

    data = rest_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    if not data:
        return False

    result = []

    for s in data.get("symbols", []):

        if (
            s.get("status") == "TRADING"
            and s.get("quoteAsset") == "USDT"
            and s.get("isSpotTradingAllowed", False)
        ):

            symbol = s["symbol"]

            symbol_info[symbol] = s

            result.append(symbol)

    symbols = sorted(result)

    dashboard["symbols"] = len(symbols)

    log(
        f"✅ Binance Spot: {len(symbols)} عملة"
    )

    return True


# ============================================================
# BOOTSTRAP 15m
# مرة واحدة فقط
# ============================================================

def bootstrap_15m():

    log("📥 تحميل بيانات 15m الأولية...")

    count = 0

    for symbol in symbols:

        try:

            data = rest_request(
                "GET",
                "/api/v3/klines",
                {
                    "symbol": symbol,
                    "interval": "15m",
                    "limit": 210
                }
            )

            if not data:
                continue

            candles = []

            for k in data:

                candles.append({
                    "t": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "closed": True
                })

            with market_lock:

                market.setdefault(symbol, {})
                market[symbol]["15m"] = candles

            count += 1

            if count % 25 == 0:

                log(
                    f"📥 15m: {count}/{len(symbols)}"
                )

            time.sleep(BOOTSTRAP_DELAY)

        except Exception as e:

            log(
                f"⚠️ bootstrap {symbol}: {e}"
            )

    log(
        f"✅ انتهى تحميل 15m: {count}/{len(symbols)}"
    )


# ============================================================
# WEBSOCKET MESSAGE
# ============================================================

def websocket_message(message):

    try:

        packet = json.loads(message)

        data = packet.get("data", packet)

        if data.get("e") != "kline":
            return

        k = data.get("k")

        if not k:
            return

        symbol = k["s"]
        interval = k["i"]

        candle = {
            "t": int(k["t"]),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "closed": bool(k["x"])
        }

        with market_lock:

            market.setdefault(symbol, {})
            candles = market[symbol].setdefault(
                interval,
                []
            )

            if candles and candles[-1]["t"] == candle["t"]:

                candles[-1] = candle

            else:

                candles.append(candle)

                if len(candles) > 250:

                    del candles[:-250]

        if interval == "15m":

            check_signal(symbol)

    except Exception as e:

        dashboard["last_error"] = str(e)


# ============================================================
# WEBSOCKET WORKER
# ============================================================

def websocket_worker(streams, worker_id):

    while running:

        ws = None

        try:

            stream_url = (
                WS_URL
                + "?streams="
                + "/".join(streams)
            )

            def on_open(wsapp):
                log(
                    f"🟢 WebSocket #{worker_id} متصل "
                    f"({len(streams)} streams)"
                )

            def on_message(wsapp, message):
                websocket_message(message)

            def on_error(wsapp, error):

                dashboard["last_error"] = str(error)

                log(
                    f"⚠️ WebSocket #{worker_id}: {error}"
                )

            def on_close(wsapp, code, msg):

                log(
                    f"🔴 WebSocket #{worker_id} انقطع"
                )

            ws = websocket.WebSocketApp(
                stream_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws_connections.append(ws)

            dashboard["websocket_connected"] += 1

            ws.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as e:

            log(
                f"⚠️ WS #{worker_id}: {e}"
            )

        finally:

            dashboard["websocket_connected"] = max(
                0,
                dashboard["websocket_connected"] - 1
            )

        time.sleep(5)


# ============================================================
# START WEBSOCKETS
# ============================================================

def start_websockets():

    streams = []

    for symbol in symbols:

        streams.append(
            symbol.lower() + "@kline_15m"
        )

    chunks = [
        streams[i:i + STREAMS_PER_SOCKET]
        for i in range(
            0,
            len(streams),
            STREAMS_PER_SOCKET
        )
    ]

    log(
        f"📡 تشغيل {len(chunks)} WebSocket"
    )

    for i, chunk in enumerate(chunks, 1):

        t = threading.Thread(
            target=websocket_worker,
            args=(chunk, i),
            daemon=True
        )

        t.start()

        ws_threads.append(t)

        time.sleep(1)


# ============================================================
# 1H CONFIRMATION
# عند الحاجة فقط
# ============================================================

one_hour_cache = {}


def get_1h_confirmation(symbol):

    now = time.time()

    cached = one_hour_cache.get(symbol)

    if cached:

        if now - cached["time"] < 900:

            return cached["ema"], cached["price"]

    data = rest_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": "1h",
            "limit": 210
        }
    )

    if not data:
        return None, None

    closes = [
        float(x[4])
        for x in data
    ]

    if len(closes) < EMA_PERIOD:
        return None, None

    value = ema(
        closes,
        EMA_PERIOD
    )

    price = closes[-1]

    one_hour_cache[symbol] = {
        "time": now,
        "ema": value,
        "price": price
    }

    return value, price


# ============================================================
# STRATEGY
# ============================================================

def check_signal(symbol):

    global trade

    with trade_lock:

        if trade is not None:
            return

    with market_lock:

        candles = market.get(
            symbol,
            {}
        ).get("15m", []).copy()

    if len(candles) < 205:
        return

    current = candles[-1]

    candle_id = current["t"]

    # لا نفحص نفس شمعة الإشارة أكثر من مرة
    if last_signal_candle.get(symbol) == candle_id:
        return

    closes = [
        x["close"]
        for x in candles
    ]

    ema200 = ema(
        closes,
        EMA_PERIOD
    )

    if ema200 is None:
        return

    price = current["close"]

    # السعر فوق EMA200
    if price <= ema200:
        return

    # آخر 20 شمعة قبل الحالية
    previous20 = candles[-21:-1]

    if len(previous20) != 20:
        return

    resistance = max(
        x["high"]
        for x in previous20
    )

    avg_volume = sum(
        x["volume"]
        for x in previous20
    ) / 20

    volume = current["volume"]

    if volume < avg_volume * VOLUME_MULTIPLIER:
        return

    previous_close = candles[-2]["close"]

    if previous_close <= 0:
        return

    move = (
        price - previous_close
    ) / previous_close

    if move < MIN_MOVE:
        return

    if move > MAX_MOVE:
        return

    # اختراق المقاومة
    if price <= resistance:
        return

    # تم اختبار هذه الشمعة
    last_signal_candle[symbol] = candle_id

    log(
        f"🔥 مرشح 15m: {symbol} "
        f"| السعر {price:.8f} "
        f"| EMA {ema200:.8f} "
        f"| حجم {volume / avg_volume:.2f}x"
    )

    # تأكيد 1H فقط هنا
    ema1h, price1h = get_1h_confirmation(symbol)

    if ema1h is None:
        return

    if price1h <= ema1h:
        log(
            f"❌ {symbol} فشل تأكيد 1H"
        )
        return

    dashboard["last_signal"] = symbol

    log(
        f"🟢 BUY SIGNAL: {symbol}"
    )

    open_trade(symbol)


# ============================================================
# SIGNED ACCOUNT
# ============================================================

def get_account(force=False):

    now = time.time()

    if (
        not force
        and account_cache["data"] is not None
        and now - account_cache["time"] < 60
    ):

        return account_cache["data"]

    data = rest_request(
        "GET",
        "/api/v3/account",
        signed=True
    )

    if data:

        account_cache["data"] = data
        account_cache["time"] = now

    return data


def get_usdt_balance():

    data = get_account()

    if not data:
        return 0.0

    for asset in data.get("balances", []):

        if asset["asset"] == "USDT":

            return (
                float(asset["free"])
                + float(asset["locked"])
            )

    return 0.0


# ============================================================
# SYMBOL FILTERS
# ============================================================

def round_step(value, step):

    if step <= 0:
        return value

    d_value = Decimal(str(value))
    d_step = Decimal(str(step))

    return float(
        (d_value / d_step).quantize(
            Decimal("1"),
            rounding=ROUND_DOWN
        ) * d_step
    )


def get_filters(symbol):

    info = symbol_info.get(symbol)

    if not info:
        return None

    price_step = 0.0
    qty_step = 0.0
    min_qty = 0.0
    min_notional = 0.0

    for f in info.get("filters", []):

        if f["filterType"] == "PRICE_FILTER":

            price_step = float(
                f["tickSize"]
            )

        elif f["filterType"] == "LOT_SIZE":

            qty_step = float(
                f["stepSize"]
            )

            min_qty = float(
                f["minQty"]
            )

        elif f["filterType"] == "MIN_NOTIONAL":

            min_notional = float(
                f["minNotional"]
            )

    return (
        price_step,
        qty_step,
        min_qty,
        min_notional
    )


def normalize_qty(symbol, qty):

    filters = get_filters(symbol)

    if not filters:
        return qty

    _, step, min_qty, _ = filters

    qty = round_step(
        qty,
        step
    )

    if qty < min_qty:
        return 0.0

    return qty


def normalize_price(symbol, price):

    filters = get_filters(symbol)

    if not filters:
        return price

    step = filters[0]

    return round_step(
        price,
        step
    )


# ============================================================
# MARKET BUY
# ============================================================

def market_buy(symbol, usdt_amount):

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": f"{usdt_amount:.8f}",
        "newOrderRespType": "FULL"
    }

    return rest_request(
        "POST",
        "/api/v3/order",
        params,
        signed=True
    )


# ============================================================
# OCO
# ============================================================

def place_oco(
    symbol,
    quantity,
    target_price,
    stop_price
):

    quantity = normalize_qty(
        symbol,
        quantity
    )

    target_price = normalize_price(
        symbol,
        target_price
    )

    stop_price = normalize_price(
        symbol,
        stop_price
    )

    if quantity <= 0:
        return None

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": f"{quantity:.12f}",

        "aboveType": "TAKE_PROFIT",
        "aboveStopPrice": f"{target_price:.12f}",

        "belowType": "STOP_LOSS",
        "belowStopPrice": f"{stop_price:.12f}",

        "newOrderRespType": "RESULT"
    }

    return rest_request(
        "POST",
        "/api/v3/orderList/oco",
        params,
        signed=True
    )


# ============================================================
# OPEN TRADE
# ============================================================

def open_trade(symbol):

    global trade

    with trade_lock:

        if trade is not None:
            return False

    balance = get_usdt_balance()

    if balance < MIN_USDT:
        log(
            f"⚠️ الرصيد أقل من {MIN_USDT} USDT"
        )
        return False

    amount = balance * TRADE_PERCENT

    log(
        f"🛒 شراء {symbol} "
        f"بـ {amount:.2f} USDT"
    )

    order = market_buy(
        symbol,
        amount
    )

    if not order:
        return False

    executed_qty = float(
        order.get(
            "executedQty",
            0
        )
    )

    if executed_qty <= 0:
        log("❌ لم يتم تنفيذ الشراء")
        return False

    fills = order.get("fills", [])

    if fills:

        total_qty = 0
        total_cost = 0

        for f in fills:

            q = float(f["qty"])
            p = float(f["price"])

            total_qty += q
            total_cost += q * p

        entry = (
            total_cost / total_qty
            if total_qty
            else float(order.get("price", 0))
        )

    else:

        entry = 0

    if entry <= 0:

        with market_lock:

            c = market.get(
                symbol,
                {}
            ).get("15m", [])

            entry = (
                c[-1]["close"]
                if c
                else 0
            )

    if entry <= 0:
        return False

    stop = entry * (1 + INITIAL_STOP)

    target = entry * (1 + INITIAL_TARGET)

    stop = normalize_price(
        symbol,
        stop
    )

    target = normalize_price(
        symbol,
        target
    )

    oco = place_oco(
        symbol,
        executed_qty,
        target,
        stop
    )

    if not oco:

        log(
            "⚠️ فشل OCO - لن نعتبر الصفقة محمية"
        )

    new_trade = {
        "symbol": symbol,
        "qty": executed_qty,
        "entry": entry,
        "stop": stop,
        "target": target,
        "locked_profit": None,
        "target_level": 0,
        "oco": bool(oco),
        "time": time.time()
    }

    with trade_lock:
        trade = new_trade

    stats["trades"] += 1

    log(
        f"""
🟢 تم الشراء
━━━━━━━━━━━━━━
العملة: {symbol}
الدخول: {entry}
الكمية: {executed_qty}
وقف: {stop}
الهدف: {target}
OCO: {"🟢" if oco else "🔴"}
━━━━━━━━━━━━━━
"""
    )

    return True


# ============================================================
# OPEN ORDERS
# ============================================================

def get_open_orders(symbol=None):

    params = {}

    if symbol:
        params["symbol"] = symbol

    return rest_request(
        "GET",
        "/api/v3/openOrders",
        params,
        signed=True
    )


# ============================================================
# CANCEL ALL ORDERS
# ============================================================

def cancel_orders(symbol):

    return rest_request(
        "DELETE",
        "/api/v3/openOrders",
        {
            "symbol": symbol
        },
        signed=True
    )


# ============================================================
# CURRENT PRICE FROM WEBSOCKET CACHE
# ============================================================

def get_current_price(symbol):

    with market_lock:

        candles = market.get(
            symbol,
            {}
        ).get("15m", [])

        if candles:
            return candles[-1]["close"]

    return None


# ============================================================
# PROFIT LOCK
# ============================================================

def update_protection():

    global trade

    while running:

        try:

            with trade_lock:

                current_trade = (
                    dict(trade)
                    if trade
                    else None
                )

            if not current_trade:

                time.sleep(2)
                continue

            symbol = current_trade["symbol"]

            price = get_current_price(
                symbol
            )

            if not price:

                time.sleep(2)
                continue

            entry = current_trade["entry"]

            profit = (
                price - entry
            ) / entry

            # =================================================
            # فحص حالة OCO كل 15 ثانية
            # =================================================

            if int(time.time()) % ORDER_CHECK_SECONDS < 2:

                orders = get_open_orders(
                    symbol
                )

                if orders is not None:

                    # إذا ما عاد فيه أوامر حماية
                    # نتحقق هل الصفقة انتهت
                    if len(orders) == 0:

                        with trade_lock:

                            if trade:

                                if profit > 0:
                                    stats["wins"] += 1
                                else:
                                    stats["losses"] += 1

                                stats["profit"] += profit * 100

                                trade = None

                        log(
                            f"🏁 انتهت صفقة {symbol} "
                            f"| النتيجة {profit * 100:.2f}%"
                        )

                        time.sleep(3)
                        continue

            # =================================================
            # بدء تأمين الربح عند +1.2%
            # =================================================

            if profit >= LOCK_TRIGGER:

                target_level = int(
                    max(
                        1,
                        profit / PROFIT_STEP
                    )
                )

                new_lock = (
                    target_level
                    * PROFIT_STEP
                )

                # لا نرجع الوقف للخلف
                old_lock = (
                    current_trade.get(
                        "locked_profit"
                    )
                    or 0
                )

                if new_lock > old_lock:

                    new_stop = entry * (
                        1 + new_lock
                    )

                    new_target = new_stop * (
                        1 + TARGET_DISTANCE
                    )

                    new_stop = normalize_price(
                        symbol,
                        new_stop
                    )

                    new_target = normalize_price(
                        symbol,
                        new_target
                    )

                    # لا نعدل إذا الأسعار غير منطقية
                    if new_stop < price and new_target > price:

                        log(
                            f"🔒 تأمين {symbol} "
                            f"عند +{new_lock * 100:.2f}%"
                        )

                        # إلغاء OCO القديم
                        cancel_orders(symbol)

                        time.sleep(0.5)

                        # إنشاء OCO الجديد
                        new_oco = place_oco(
                            symbol,
                            current_trade["qty"],
                            new_target,
                            new_stop
                        )

                        if new_oco:

                            with trade_lock:

                                if trade:

                                    trade["stop"] = new_stop
                                    trade["target"] = new_target
                                    trade["locked_profit"] = new_lock
                                    trade["target_level"] = target_level
                                    trade["oco"] = True

                            log(
                                f"🔒 وقف جديد: {new_stop}"
                            )

                            log(
                                f"🎯 هدف جديد: {new_target}"
                            )

                        else:

                            log(
                                "⚠️ فشل تحديث الحماية"
                            )

            time.sleep(2)

        except Exception as e:

            dashboard["last_error"] = str(e)

            log(
                f"⚠️ إدارة الصفقة: {e}"
            )

            time.sleep(5)


# ============================================================
# RECOVER TRADE
# ============================================================

def recover_trade():

    global trade

    log("🔄 البحث عن صفقة مفتوحة...")

    try:

        orders = get_open_orders()

        if not orders:
            log("ℹ️ لا توجد أوامر مفتوحة")
            return

        # نحاول العثور على OCO/SELL مفتوح
        sell_orders = [
            o for o in orders
            if o.get("side") == "SELL"
        ]

        if not sell_orders:
            return

        symbol = sell_orders[0]["symbol"]

        account = get_account(
            force=True
        )

        if not account:
            return

        base_asset = symbol.replace(
            "USDT",
            ""
        )

        qty = 0.0

        for b in account.get(
            "balances",
            []
        ):

            if b["asset"] == base_asset:

                qty = float(
                    b["free"]
                )

                break

        if qty <= 0:
            return

        # محاولة معرفة سعر الشراء من آخر صفقة
        trades = rest_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 20
            },
            signed=True
        )

        if not trades:
            return

        buys = [
            x for x in trades
            if x.get("isBuyer")
        ]

        if not buys:
            return

        last = buys[-1]

        entry = float(
            last["price"]
        )

        stop = entry * (
            1 + INITIAL_STOP
        )

        target = entry * (
            1 + INITIAL_TARGET
        )

        with trade_lock:

            trade = {
                "symbol": symbol,
                "qty": qty,
                "entry": entry,
                "stop": normalize_price(
                    symbol,
                    stop
                ),
                "target": normalize_price(
                    symbol,
                    target
                ),
                "locked_profit": None,
                "target_level": 0,
                "oco": True,
                "time": time.time()
            }

        log(
            f"""
♻️ تم استرجاع الصفقة
━━━━━━━━━━━━━━
العملة: {symbol}
الدخول: {entry}
الكمية: {qty}
━━━━━━━━━━━━━━
"""
        )

    except Exception as e:

        log(
            f"⚠️ استرجاع الصفقة: {e}"
        )


# ============================================================
# BACKGROUND BOT
# ============================================================

def bot_main():

    dashboard["status"] = "تهيئة Binance"

    if not API_KEY or not API_SECRET:

        dashboard["status"] = "API غير موجود"
        log(
            "❌ أضف BINANCE_API_KEY و BINANCE_API_SECRET"
        )
        return

    if not load_exchange_info():

        dashboard["status"] = "فشل Binance"
        return

    dashboard["status"] = "تحميل البيانات"

    # مرة واحدة عند التشغيل
    bootstrap_15m()

    dashboard["status"] = "تشغيل WebSocket"

    # نبدأ WS
    start_websockets()

    # استرجاع صفقة
    time.sleep(3)

    recover_trade()

    # إدارة الصفقة
    manager = threading.Thread(
        target=update_protection,
        daemon=True
    )

    manager.start()

    dashboard["status"] = "يعمل"

    log(
        "🚀 مضارب أبو سعود V2 PRO يعمل"
    )

    while running:

        try:

            dashboard["binance_connected"] = (
                get_account() is not None
            )

        except:
            pass

        time.sleep(60)


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
def home():

    return """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width, initial-scale=1">

<title>مضارب أبو سعود V2 PRO</title>

<style>

body {
    font-family: Arial;
    background:#111;
    color:#fff;
    padding:20px;
}

.card {
    background:#1d1d1d;
    padding:18px;
    margin:12px 0;
    border-radius:15px;
}

.green {
    color:#00e676;
}

.red {
    color:#ff5252;
}

.value {
    font-size:24px;
    font-weight:bold;
}

</style>
</head>

<body>

<h2>🤖 مضارب أبو سعود V2 PRO</h2>

<div class="card">
    <div>Binance</div>
    <div id="binance" class="value">...</div>
</div>

<div class="card">
    <div>WebSocket</div>
    <div id="ws" class="value">...</div>
</div>

<div class="card">
    <div>عملات Binance</div>
    <div id="symbols" class="value">...</div>
</div>

<div class="card">
    <div>الرصيد</div>
    <div id="balance" class="value">...</div>
</div>

<div class="card">
    <div>الصفقة الحالية</div>
    <div id="trade">لا توجد صفقة</div>
</div>

<div class="card">
    <div>آخر إشارة</div>
    <div id="signal">---</div>
</div>

<script>

async function update() {

    try {

        const r = await fetch('/api/dashboard');
        const d = await r.json();

        const b = document.getElementById('binance');

        if (d.binance.connected) {

            b.innerHTML =
                '<span class="green">🟢 متصل بـ Binance</span>';

            document.getElementById('balance').innerText =
                Number(d.binance.usdt).toFixed(2) + ' USDT';

        } else {

            b.innerHTML =
                '<span class="red">🔴 غير متصل</span>';

        }

        document.getElementById('ws').innerText =
            d.websocket_connected + ' اتصال';

        document.getElementById('symbols').innerText =
            d.symbols;

        document.getElementById('signal').innerText =
            d.last_signal || '---';

        if (d.trade) {

            const t = d.trade;

            document.getElementById('trade').innerHTML =

                '<b>' + t.symbol + '</b><br>' +

                'الدخول: ' + t.entry + '<br>' +

                'السعر: ' + t.current + '<br>' +

                'الربح: ' + t.profit + '%<br>' +

                'الوقف: ' + t.stop + '<br>' +

                'الهدف: ' + t.target + '<br>' +

                'تأمين: ' +
                (t.locked_profit || 0) + '%';

        } else {

            document.getElementById('trade').innerText =
                'لا توجد صفقة';

        }

    } catch(e) {}

}

update();

setInterval(update, 5000);

</script>

</body>
</html>
"""


# ============================================================
# API DASHBOARD
# ============================================================

@app.route("/api/dashboard")
def api_dashboard():

    account = get_account()

    usdt = 0.0

    connected = False

    if account:

        connected = True

        for b in account.get(
            "balances",
            []
        ):

            if b["asset"] == "USDT":

                usdt = (
                    float(b["free"])
                    + float(b["locked"])
                )

                break

    current_trade = None

    with trade_lock:

        if trade:

            t = dict(trade)

            current = get_current_price(
                t["symbol"]
            )

            if current:

                profit = (
                    (current - t["entry"])
                    / t["entry"]
                ) * 100

                t["current"] = round(
                    current,
                    8
                )

                t["profit"] = round(
                    profit,
                    2
                )

            current_trade = t

    return jsonify({

        "binance": {
            "connected": connected,
            "usdt": usdt
        },

        "websocket_connected":
            dashboard["websocket_connected"],

        "symbols":
            dashboard["symbols"],

        "status":
            dashboard["status"],

        "last_error":
            dashboard["last_error"],

        "last_signal":
            dashboard["last_signal"],

        "trade":
            current_trade,

        "stats":
            stats

    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": dashboard["status"],
        "binance": dashboard["binance_connected"],
        "websocket": dashboard["websocket_connected"]
    })


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    bot_thread = threading.Thread(
        target=bot_main,
        daemon=True
    )

    bot_thread.start()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
