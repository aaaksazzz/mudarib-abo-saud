# ============================================================
# مضارب أبو سعود V2 PRO 🤖
# Binance Spot + Render
# ============================================================

import os
import time
import hmac
import hashlib
import urllib.parse
import threading
import json
import requests
from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify

# ============================================================
# الإعدادات
# ============================================================

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

# نقاط Binance الرسمية
BINANCE_BASE_URLS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

BASE_INDEX = 0
BASE_URL = BINANCE_BASE_URLS[0]

WS_URLS = [
    "wss://stream.binance.com:9443/stream",
    "wss://stream.binance.com:443/stream",
]

WS_INDEX = 0

# ============================================================
# استراتيجية الدخول
# ============================================================

TIMEFRAME = "15m"
CONFIRM_TIMEFRAME = "1h"

EMA_PERIOD = 200
BREAKOUT_PERIOD = 20

VOLUME_MULTIPLIER = 1.5

MIN_MOVE = 0.005       # 0.5%
MAX_MOVE = 0.04        # 4%

# ============================================================
# إدارة الصفقة
# ============================================================

STOP_LOSS = -0.02      # -2%

INITIAL_TARGET = 0.012 # +1.2%

LOCK_TRIGGER = 0.012   # يبدأ تأمين الربح عند +1.2%
LOCK_PROFIT = 0.012    # أول وقف = +1.2%

PROFIT_STEP = 0.01     # كل +1%
TARGET_DISTANCE = 0.012

MIN_USDT = 5.0

# ============================================================
# البوت
# ============================================================

app = Flask(__name__)

symbols = []
symbol_info = {}

market_data = {}
last_1h_check = {}

trade = None

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
}

bot_status = {
    "running": False,
    "binance_connected": False,
    "websocket_connected": False,
    "last_scan": None,
    "last_error": None,
    "base_url": BASE_URL,
}

lock = threading.Lock()


# ============================================================
# أدوات عامة
# ============================================================

def log(msg):
    print(msg, flush=True)


def round_step(value, step):
    try:
        value = Decimal(str(value))
        step = Decimal(str(step))

        if step == 0:
            return float(value)

        result = (value // step) * step

        return float(
            result.quantize(step, rounding=ROUND_DOWN)
        )
    except Exception:
        return float(value)


def get_symbol_info(symbol):
    return symbol_info.get(symbol, {})


# ============================================================
# Binance REST - تبديل تلقائي
# ============================================================

def rest_request(method, path, params=None, signed=False):
    global BASE_INDEX, BASE_URL

    params = params.copy() if params else {}

    last_error = None

    for attempt in range(len(BINANCE_BASE_URLS)):

        current_index = (
            BASE_INDEX + attempt
        ) % len(BINANCE_BASE_URLS)

        current_base = BINANCE_BASE_URLS[current_index]

        try:

            request_params = params.copy()

            if signed:
                request_params["timestamp"] = int(
                    time.time() * 1000
                )

                request_params["recvWindow"] = 10000

                query = urllib.parse.urlencode(
                    request_params,
                    doseq=True
                )

                signature = hmac.new(
                    BINANCE_API_SECRET.encode(),
                    query.encode(),
                    hashlib.sha256
                ).hexdigest()

                request_params["signature"] = signature

            headers = {}

            if BINANCE_API_KEY:
                headers["X-MBX-APIKEY"] = BINANCE_API_KEY

            url = current_base + path

            r = requests.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=15
            )

            # نجاح
            if r.status_code < 400:

                BASE_INDEX = current_index
                BASE_URL = current_base

                bot_status["base_url"] = BASE_URL
                bot_status["binance_connected"] = True
                bot_status["last_error"] = None

                try:
                    return r.json()
                except Exception:
                    return r.text

            # 451
            if r.status_code == 451:

                body = r.text[:1000]

                log(
                    f"⚠️ Binance 451 على {current_base}"
                )

                log(
                    f"📩 رد Binance:\n{body}"
                )

                last_error = Exception(
                    f"HTTP 451: {body}"
                )

                continue

            # 429
            if r.status_code == 429:

                body = r.text[:1000]

                log(
                    f"⚠️ Binance 429 على {current_base}"
                )

                log(body)

                last_error = Exception(
                    f"HTTP 429: {body}"
                )

                time.sleep(5)

                continue

            # باقي الأخطاء
            body = r.text[:1000]

            log(
                f"⚠️ Binance HTTP {r.status_code}"
            )

            log(body)

            last_error = Exception(
                f"HTTP {r.status_code}: {body}"
            )

            # لو خطأ 5xx نجرب السيرفر التالي
            if r.status_code >= 500:
                continue

            break

        except requests.RequestException as e:

            log(
                f"⚠️ فشل الاتصال بـ {current_base}"
            )

            log(str(e)[:500])

            last_error = e

            continue

    bot_status["binance_connected"] = False
    bot_status["last_error"] = str(last_error)

    raise last_error or Exception(
        "Binance REST connection failed"
    )


# ============================================================
# اختبار Binance
# ============================================================

def test_binance():

    try:

        data = rest_request(
            "GET",
            "/api/v3/time"
        )

        if isinstance(data, dict) and "serverTime" in data:

            bot_status["binance_connected"] = True

            log(
                f"🟢 Binance متصل | {BASE_URL}"
            )

            return True

    except Exception as e:

        log(
            f"🔴 Binance غير متصل: {e}"
        )

    return False


# ============================================================
# معلومات العملات
# ============================================================

def load_exchange_info():

    global symbols

    log("📥 تحميل قائمة Binance Spot...")

    data = rest_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    temp_symbols = []

    for s in data.get("symbols", []):

        try:

            symbol = s["symbol"]

            if (
                s["status"] != "TRADING"
                or s["quoteAsset"] != "USDT"
                or s["isSpotTradingAllowed"] is not True
            ):
                continue

            info = {
                "symbol": symbol,
                "baseAsset": s["baseAsset"],
                "quoteAsset": s["quoteAsset"],
                "minQty": 0.0,
                "stepSize": 0.0,
                "minNotional": 5.0,
            }

            for f in s.get("filters", []):

                if f["filterType"] == "LOT_SIZE":
                    info["minQty"] = float(
                        f["minQty"]
                    )
                    info["stepSize"] = float(
                        f["stepSize"]
                    )

                elif f["filterType"] == "NOTIONAL":
                    info["minNotional"] = float(
                        f.get("minNotional", 5)
                    )

                elif f["filterType"] == "MIN_NOTIONAL":
                    info["minNotional"] = float(
                        f.get("minNotional", 5)
                    )

            symbol_info[symbol] = info
            temp_symbols.append(symbol)

        except Exception:
            continue

    symbols = sorted(temp_symbols)

    log(
        f"✅ تم تحميل {len(symbols)} عملة Binance Spot"
    )


# ============================================================
# الشموع
# ============================================================

def get_klines(symbol, interval, limit=210):

    return rest_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
    )


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result) * multiplier
        ) + result

    return result


# ============================================================
# تحليل 15m
# ============================================================

def analyze_symbol(symbol):

    try:

        data = market_data.get(symbol)

        if not data:
            return None

        candles = data.get("candles", [])

        if len(candles) < 205:
            return None

        # آخر شمعة مكتملة
        closed = candles[:-1]

        if len(closed) < 205:
            return None

        current = closed[-1]

        closes = [
            x["close"]
            for x in closed
        ]

        highs = [
            x["high"]
            for x in closed
        ]

        volumes = [
            x["volume"]
            for x in closed
        ]

        current_price = current["close"]

        # EMA200
        ema200 = ema(
            closes[-210:],
            EMA_PERIOD
        )

        if ema200 is None:
            return None

        # السعر فوق EMA200
        if current_price <= ema200:
            return None

        # مقاومة آخر 20 شمعة
        previous_20 = highs[-21:-1]

        if not previous_20:
            return None

        resistance = max(previous_20)

        # اختراق
        if current_price <= resistance:
            return None

        # حجم
        previous_volumes = volumes[-21:-1]

        avg_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            current["volume"]
            / avg_volume
        )

        if volume_ratio < VOLUME_MULTIPLIER:
            return None

        # حركة الشمعة
        previous_close = closed[-2]["close"]

        move = (
            current_price - previous_close
        ) / previous_close

        if move < MIN_MOVE:
            return None

        if move > MAX_MOVE:
            return None

        # تأكيد 1h
        if not get_1h_confirmation(symbol):
            return None

        return {
            "symbol": symbol,
            "price": current_price,
            "ema200": ema200,
            "resistance": resistance,
            "volume_ratio": volume_ratio,
            "move": move,
        }

    except Exception as e:

        log(
            f"⚠️ تحليل {symbol}: {str(e)[:200]}"
        )

        return None


# ============================================================
# تأكيد الساعة
# ============================================================

def get_1h_confirmation(symbol):

    now = time.time()

    # Cache لمدة 15 دقيقة
    if (
        symbol in last_1h_check
        and now - last_1h_check[symbol]["time"] < 900
    ):
        return last_1h_check[symbol]["ok"]

    try:

        data = get_klines(
            symbol,
            "1h",
            210
        )

        if len(data) < 205:

            last_1h_check[symbol] = {
                "time": now,
                "ok": False,
            }

            return False

        closes = [
            float(x[4])
            for x in data[:-1]
        ]

        price = closes[-1]

        ema200 = ema(
            closes[-210:],
            EMA_PERIOD
        )

        ok = (
            ema200 is not None
            and price > ema200
        )

        last_1h_check[symbol] = {
            "time": now,
            "ok": ok,
        }

        return ok

    except Exception as e:

        log(
            f"⚠️ 1H {symbol}: {str(e)[:200]}"
        )

        return False


# ============================================================
# الحساب
# ============================================================

def get_account():

    return rest_request(
        "GET",
        "/api/v3/account",
        signed=True
    )


def get_usdt_balance():

    try:

        account = get_account()

        for b in account.get("balances", []):

            if b["asset"] == "USDT":

                return float(
                    b["free"]
                )

    except Exception as e:

        log(
            f"⚠️ الرصيد: {str(e)[:300]}"
        )

    return 0.0


# ============================================================
# شراء Market
# ============================================================

def market_buy(symbol, usdt_amount):

    info = get_symbol_info(symbol)

    if not info:
        raise Exception(
            "معلومات العملة غير موجودة"
        )

    if usdt_amount < MIN_USDT:
        raise Exception(
            f"الرصيد أقل من {MIN_USDT} USDT"
        )

    log(
        f"🟢 شراء MARKET: {symbol} | {usdt_amount:.2f} USDT"
    )

    result = rest_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{usdt_amount:.2f}",
        },
        signed=True
    )

    return result


# ============================================================
# جلب سعر
# ============================================================

def get_price(symbol):

    data = rest_request(
        "GET",
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ============================================================
# الكمية المشتراة
# ============================================================

def get_asset_balance(asset):

    try:

        account = get_account()

        for b in account.get("balances", []):

            if b["asset"] == asset:

                return float(
                    b["free"]
                ) + float(
                    b["locked"]
                )

    except Exception:
        pass

    return 0.0


# ============================================================
# حفظ الصفقة
# ============================================================

def save_trade(
    symbol,
    entry,
    qty
):

    global trade

    trade = {
        "symbol": symbol,
        "entry": entry,
        "qty": qty,
        "current": entry,
        "profit": 0.0,
        "stop": entry * (1 + STOP_LOSS),
        "target": entry * (1 + INITIAL_TARGET),
        "locked_profit": 0.0,
        "target_level": 0,
        "opened_at": time.time(),
        "status": "OPEN",
        "oco_status": "MANAGED_BY_BOT",
    }

    log(
        f"📌 الصفقة: {symbol}"
    )

    log(
        f"💰 الدخول: {entry}"
    )

    log(
        f"🛑 الوقف: {trade['stop']}"
    )

    log(
        f"🎯 الهدف: {trade['target']}"
    )


# ============================================================
# شراء الصفقة
# ============================================================

def open_position(signal):

    global trade

    with lock:

        if trade is not None:
            return False

        balance = get_usdt_balance()

        if balance < MIN_USDT:
            log(
                f"⚠️ الرصيد {balance:.2f} USDT"
            )
            return False

        # نستخدم 99.9%
        amount = balance * 0.999

        if amount < MIN_USDT:
            return False

        symbol = signal["symbol"]

        result = market_buy(
            symbol,
            amount
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
                amount
            )
        )

        if executed_qty <= 0:
            log(
                "❌ لم يتم تنفيذ الشراء"
            )
            return False

        entry = (
            quote_qty
            / executed_qty
        )

        save_trade(
            symbol,
            entry,
            executed_qty
        )

        stats["trades"] += 1

        log(
            f"✅ تم الشراء {symbol}"
        )

        log(
            f"📦 الكمية: {executed_qty}"
        )

        return True


# ============================================================
# تحديث حماية الصفقة
# ============================================================

def update_trade():

    global trade

    if trade is None:
        return

    try:

        symbol = trade["symbol"]

        price = get_price(
            symbol
        )

        entry = trade["entry"]

        profit = (
            price - entry
        ) / entry

        trade["current"] = price
        trade["profit"] = profit

        # ====================================================
        # وقف الخسارة الأولي
        # ====================================================

        if profit <= STOP_LOSS:

            log(
                f"🔴 وقف خسارة {symbol} | "
                f"{profit * 100:.2f}%"
            )

            close_position(
                "STOP LOSS"
            )

            return

        # ====================================================
        # بدء تأمين الربح
        # ====================================================

        if profit >= LOCK_TRIGGER:

            levels = int(
                (profit - LOCK_TRIGGER)
                / PROFIT_STEP
            )

            lock_profit = (
                LOCK_PROFIT
                + (
                    levels
                    * PROFIT_STEP
                )
            )

            if lock_profit > trade["locked_profit"]:

                trade["locked_profit"] = (
                    lock_profit
                )

                trade["target_level"] = (
                    levels + 1
                )

                trade["stop"] = (
                    entry
                    * (1 + lock_profit)
                )

                trade["target"] = (
                    entry
                    * (
                        1
                        + lock_profit
                        + TARGET_DISTANCE
                    )
                )

                log(
                    f"🔒 تأمين ربح "
                    f"{lock_profit * 100:.2f}%"
                )

                log(
                    f"🛑 الوقف الجديد: "
                    f"{trade['stop']:.8f}"
                )

                log(
                    f"🎯 الهدف الجديد: "
                    f"{trade['target']:.8f}"
                )

        # ====================================================
        # إذا رجع السعر للوقف المؤمّن
        # ====================================================

        if (
            trade["locked_profit"] > 0
            and price <= trade["stop"]
        ):

            log(
                f"🔒 خرج بتأمين ربح "
                f"{trade['locked_profit'] * 100:.2f}%"
            )

            close_position(
                "LOCK PROFIT"
            )

            return

        # ====================================================
        # الهدف
        # ====================================================

        if price >= trade["target"]:

            log(
                f"🎯 وصل الهدف "
                f"{profit * 100:.2f}%"
            )

            close_position(
                "TARGET"
            )

    except Exception as e:

        log(
            f"⚠️ إدارة الصفقة: {str(e)[:500]}"
        )


# ============================================================
# إغلاق Market Sell
# ============================================================

def close_position(reason):

    global trade

    if trade is None:
        return

    symbol = trade["symbol"]

    try:

        info = get_symbol_info(symbol)

        qty = get_asset_balance(
            info["baseAsset"]
        )

        qty = round_step(
            qty,
            info["stepSize"]
        )

        if qty <= 0:
            log(
                "⚠️ لا توجد كمية للإغلاق"
            )

            trade = None
            return

        log(
            f"🔴 إغلاق {symbol} | {reason}"
        )

        result = rest_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": f"{qty:.12f}",
            },
            signed=True
        )

        price = get_price(
            symbol
        )

        profit = (
            price - trade["entry"]
        ) / trade["entry"]

        stats["profit"] += profit

        if profit >= 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

        log(
            f"✅ أغلقت الصفقة | "
            f"{profit * 100:.2f}%"
        )

        trade = None

        return result

    except Exception as e:

        log(
            f"❌ فشل الإغلاق: {str(e)[:500]}"
        )


# ============================================================
# استعادة صفقة بعد إعادة تشغيل Render
# ============================================================

def recover_trade():

    global trade

    try:

        account = get_account()

        balances = account.get(
            "balances",
            []
        )

        # نبحث عن أصل عليه كمية
        for b in balances:

            asset = b["asset"]

            if asset == "USDT":
                continue

            free = float(
                b["free"]
            )

            locked = float(
                b["locked"]
            )

            qty = free + locked

            if qty <= 0:
                continue

            symbol = asset + "USDT"

            if symbol not in symbol_info:
                continue

            price = get_price(
                symbol
            )

            # قيمة تقريبية
            value = qty * price

            if value < MIN_USDT:
                continue

            log(
                f"🔎 تم العثور على صفقة مفتوحة: "
                f"{symbol}"
            )

            # ما عندنا entry محفوظ في الذاكرة
            # نستخدم سعر السوق كبداية استرداد مؤقتة
            trade = {
                "symbol": symbol,
                "entry": price,
                "qty": qty,
                "current": price,
                "profit": 0.0,
                "stop": price * (
                    1 + STOP_LOSS
                ),
                "target": price * (
                    1 + INITIAL_TARGET
                ),
                "locked_profit": 0.0,
                "target_level": 0,
                "opened_at": time.time(),
                "status": "RECOVERED",
                "oco_status": "RECOVERED",
            }

            log(
                f"♻️ تم استرداد {symbol}"
            )

            return True

    except Exception as e:

        log(
            f"⚠️ استرداد الصفقة: "
            f"{str(e)[:500]}"
        )

    return False


# ============================================================
# تحميل بيانات السوق
# ============================================================

def bootstrap_market():

    log(
        "📥 تجهيز بيانات 15m..."
    )

    count = 0

    for symbol in symbols:

        try:

            data = get_klines(
                symbol,
                "15m",
                210
            )

            candles = []

            for x in data:

                candles.append({
                    "open_time": x[0],
                    "open": float(x[1]),
                    "high": float(x[2]),
                    "low": float(x[3]),
                    "close": float(x[4]),
                    "volume": float(x[5]),
                })

            market_data[symbol] = {
                "candles": candles
            }

            count += 1

            if count % 25 == 0:

                log(
                    f"📊 تم تجهيز "
                    f"{count}/{len(symbols)}"
                )

            # تخفيف الضغط
            time.sleep(0.03)

        except Exception as e:

            log(
                f"⚠️ bootstrap {symbol}: "
                f"{str(e)[:150]}"
            )

    log(
        f"✅ انتهى تجهيز السوق: "
        f"{count} عملة"
    )


# ============================================================
# تحديث شمعة من WebSocket
# ============================================================

def update_candle(event):

    try:

        k = event["k"]

        symbol = k["s"]

        if symbol not in market_data:
            return

        candle = {
            "open_time": k["t"],
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
        }

        data = market_data[symbol]

        candles = data["candles"]

        if candles and candles[-1]["open_time"] == candle["open_time"]:

            candles[-1] = candle

        else:

            candles.append(candle)

            if len(candles) > 220:
                del candles[:-220]

        # عند إغلاق الشمعة
        if k["x"]:

            bot_status["last_scan"] = (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

    except Exception as e:

        log(
            f"⚠️ WS candle: {str(e)[:200]}"
        )


# ============================================================
# WebSocket
# ============================================================

def websocket_loop():

    global WS_INDEX

    try:
        import websocket
    except ImportError:

        log(
            "❌ websocket-client غير مثبت"
        )

        return

    while True:

        try:

            current_ws = WS_URLS[
                WS_INDEX
            ]

            # جميع عملات USDT
            streams = [
                f"{s.lower()}@kline_15m"
                for s in symbols
            ]

            # نقسمها حتى ما يكون الرابط ضخم
            chunks = [
                streams[i:i + 100]
                for i in range(
                    0,
                    len(streams),
                    100
                )
            ]

            log(
                f"🔌 WebSocket "
                f"{current_ws}"
            )

            for chunk in chunks:

                params = {
                    "method": "SUBSCRIBE",
                    "params": chunk,
                    "id": int(time.time())
                }

                ws = websocket.create_connection(
                    current_ws,
                    timeout=30
                )

                ws.send(
                    json.dumps(params)
                )

                bot_status[
                    "websocket_connected"
                ] = True

                log(
                    f"🟢 WebSocket متصل "
                    f"| {len(chunk)} عملة"
                )

                while True:

                    raw = ws.recv()

                    if not raw:
                        break

                    data = json.loads(raw)

                    if "stream" in data:

                        payload = data.get(
                            "data",
                            {}
                        )

                        if payload.get("e") == "kline":

                            update_candle(
                                payload
                            )

                ws.close()

        except Exception as e:

            bot_status[
                "websocket_connected"
            ] = False

            log(
                f"⚠️ WebSocket: "
                f"{str(e)[:500]}"
            )

            # جرب المنفذ الآخر
            WS_INDEX = (
                WS_INDEX + 1
            ) % len(WS_URLS)

            time.sleep(5)


# ============================================================
# فحص العملات
# ============================================================

def scan_market():

    global trade

    while True:

        try:

            if trade is None:

                log(
                    "🔍 بدء فحص العملات..."
                )

                found = []

                for index, symbol in enumerate(symbols):

                    signal = analyze_symbol(
                        symbol
                    )

                    if signal:

                        found.append(
                            signal
                        )

                        log(
                            f"🔥 إشارة 9/9 "
                            f"| {symbol} "
                            f"| السعر {signal['price']}"
                        )

                        # أول إشارة فقط
                        break

                    if index % 50 == 0:

                        log(
                            f"🔍 "
                            f"[{index + 1}/{len(symbols)}] "
                            f"{symbol}"
                        )

                if found:

                    signal = found[0]

                    log(
                        f"🚀 دخول: "
                        f"{signal['symbol']}"
                    )

                    open_position(
                        signal
                    )

                else:

                    log(
                        "⚪ لا توجد إشارة حالياً"
                    )

            else:

                log(
                    f"📌 صفقة مفتوحة: "
                    f"{trade['symbol']}"
                )

            bot_status["last_scan"] = (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

        except Exception as e:

            log(
                f"⚠️ Scanner: "
                f"{str(e)[:500]}"
            )

        # كل 3 دقائق
        time.sleep(180)


# ============================================================
# إدارة الصفقة
# ============================================================

def position_manager():

    while True:

        try:

            if trade is not None:

                update_trade()

        except Exception as e:

            log(
                f"⚠️ Position Manager: "
                f"{str(e)[:300]}"
            )

        time.sleep(5)


# ============================================================
# Dashboard
# ============================================================

@app.route("/")
def home():

    return """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود V2 PRO</title>

<style>

body{
    margin:0;
    background:#101216;
    color:#fff;
    font-family:Arial;
}

.container{
    max-width:900px;
    margin:auto;
    padding:20px;
}

.card{
    background:#191c22;
    border-radius:15px;
    padding:18px;
    margin-bottom:15px;
}

h1{
    margin-top:0;
}

.green{
    color:#35e58b;
}

.red{
    color:#ff5555;
}

.yellow{
    color:#ffd166;
}

.value{
    font-size:25px;
    font-weight:bold;
}

.row{
    display:flex;
    justify-content:space-between;
    padding:9px 0;
    border-bottom:1px solid #292d35;
}

</style>
</head>

<body>

<div class="container">

<div class="card">

<h1>🤖 مضارب أبو سعود V2 PRO</h1>

<div id="status">
جاري الاتصال...
</div>

</div>


<div class="card">

<h2>💰 Binance</h2>

<div class="row">
<span>الاتصال</span>
<span id="binance">...</span>
</div>

<div class="row">
<span>الرصيد USDT</span>
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
<span>عدد الصفقات</span>
<span id="trades">0</span>
</div>

<div class="row">
<span>الناجحة</span>
<span id="wins">0</span>
</div>

<div class="row">
<span>الخاسرة</span>
<span id="losses">0</span>
</div>

<div class="row">
<span>نسبة النجاح</span>
<span id="winrate">0%</span>
</div>

<div class="row">
<span>إجمالي النتيجة</span>
<span id="profit">0%</span>
</div>

</div>


<div class="card">

<h2>⚙️ النظام</h2>

<div class="row">
<span>REST</span>
<span id="base">...</span>
</div>

<div class="row">
<span>WebSocket</span>
<span id="ws">...</span>
</div>

<div class="row">
<span>آخر فحص</span>
<span id="scan">...</span>
</div>

</div>

</div>


<script>

async function update(){

    try{

        const r =
            await fetch("/api/dashboard");

        const d =
            await r.json();

        document.getElementById("binance")
            .innerHTML =
            d.binance_connected
            ? '<span class="green">🟢 متصل</span>'
            : '<span class="red">🔴 غير متصل</span>';

        document.getElementById("balance")
            .innerText =
            d.balance.toFixed(2) + " USDT";

        document.getElementById("ws")
            .innerHTML =
            d.websocket_connected
            ? '<span class="green">🟢 متصل</span>'
            : '<span class="red">🔴 غير متصل</span>';

        document.getElementById("base")
            .innerText =
            d.base_url;

        document.getElementById("scan")
            .innerText =
            d.last_scan || "...";

        document.getElementById("trades")
            .innerText =
            d.stats.trades;

        document.getElementById("wins")
            .innerText =
            d.stats.wins;

        document.getElementById("losses")
            .innerText =
            d.stats.losses;

        document.getElementById("winrate")
            .innerText =
            d.winrate.toFixed(2) + "%";

        document.getElementById("profit")
            .innerText =
            (d.stats.profit * 100).toFixed(2) + "%";

        if(d.trade){

            const t = d.trade;

            document.getElementById("trade")
                .innerHTML =

                "🪙 " + t.symbol +

                "<div class='row'><span>الدخول</span><span>"
                + t.entry + "</span></div>" +

                "<div class='row'><span>السعر</span><span>"
                + t.current + "</span></div>" +

                "<div class='row'><span>الربح</span><span>"
                + (t.profit*100).toFixed(2)
                + "%</span></div>" +

                "<div class='row'><span>الوقف</span><span>"
                + t.stop + "</span></div>" +

                "<div class='row'><span>الهدف</span><span>"
                + t.target + "</span></div>" +

                "<div class='row'><span>تأمين الربح</span><span>"
                + (t.locked_profit*100).toFixed(2)
                + "%</span></div>";

        }else{

            document.getElementById("trade")
                .innerHTML =
                "⚪ لا توجد صفقة مفتوحة";
        }

    }catch(e){

        document.getElementById("status")
            .innerHTML =
            '<span class="red">🔴 خطأ في لوحة التحكم</span>';
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
# API Dashboard
# ============================================================

@app.route("/api/dashboard")
def dashboard():

    balance = 0.0

    try:
        balance = get_usdt_balance()
    except Exception:
        pass

    total = (
        stats["wins"]
        + stats["losses"]
    )

    winrate = (
        stats["wins"] / total * 100
        if total > 0
        else 0
    )

    return jsonify({
        "running":
            bot_status["running"],

        "binance_connected":
            bot_status["binance_connected"],

        "websocket_connected":
            bot_status["websocket_connected"],

        "base_url":
            bot_status["base_url"],

        "balance":
            balance,

        "trade":
            trade,

        "stats":
            stats,

        "winrate":
            winrate,

        "last_scan":
            bot_status["last_scan"],

        "last_error":
            bot_status["last_error"],
    })


# ============================================================
# Health
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "running":
            bot_status["running"],
        "binance":
            bot_status["binance_connected"],
        "websocket":
            bot_status["websocket_connected"],
        "base_url":
            BASE_URL,
    })


# ============================================================
# تشغيل البوت
# ============================================================

def bot_main():

    global symbols

    log("")
    log("=" * 60)
    log("🤖 مضارب أبو سعود V2 PRO")
    log("=" * 60)

    if not BINANCE_API_KEY or not BINANCE_API_SECRET:

        log(
            "❌ أضف BINANCE_API_KEY "
            "و BINANCE_API_SECRET في Render"
        )

        bot_status["last_error"] = (
            "API keys missing"
        )

        return

    # اختبار Binance
    if not test_binance():

        log(
            "🔴 Binance REST غير متاح"
        )

        return

    # معلومات العملات
    try:

        load_exchange_info()

    except Exception as e:

        log(
            f"❌ فشل تحميل Binance Spot: "
            f"{str(e)[:500]}"
        )

        return

    # بيانات السوق
    try:

        bootstrap_market()

    except Exception as e:

        log(
            f"⚠️ فشل bootstrap: "
            f"{str(e)[:500]}"
        )

    # استرداد الصفقة
    recover_trade()

    bot_status["running"] = True

    # WebSocket
    threading.Thread(
        target=websocket_loop,
        daemon=True
    ).start()

    # Scanner
    threading.Thread(
        target=scan_market,
        daemon=True
    ).start()

    # إدارة الصفقة
    threading.Thread(
        target=position_manager,
        daemon=True
    ).start()

    log(
        "🟢 البوت يعمل الآن"
    )


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":

    threading.Thread(
        target=bot_main,
        daemon=True
    ).start()

    # Render
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10000"
            )
        ),
        threaded=True
    )
