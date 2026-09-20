# ============================================================
# مضارب أبو سعود V6 FAST PRO 🤖
# Binance Spot + Auto Trading + Professional Dashboard
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


# ============================================================
# SETTINGS
# ============================================================

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

TITLE = "مضارب أبو سعود 🤖"

TIMEFRAME = "15m"

EMA_PERIOD = 200

# استراتيجية الدخول
MIN_CHANGE_15M = 1.0

# الحماية
PROTECTION_START = 1.0
PROTECTION_STEP = 1.0
TRAILING_PERCENT = 0.50

# الفحص
POSITION_CHECK_SECONDS = 30
SCAN_INTERVAL = 60

# أقل قيمة نعتبرها صفقة
MIN_POSITION_USDT = 2.0

# نسبة الشراء
BUY_PERCENT = 99.9

# ============================================================
# GLOBAL STATE
# ============================================================

app = Flask(__name__)

state = {
    "bot": {
        "running": True,
        "started_at": time.time(),
        "last_check": None,
        "last_scan": None,
        "last_error": None,
        "message": "جاري التشغيل...",
        "mode": "فحص الحساب",
    },

    "account": {
        "usdt": 0.0,
        "total": 0.0,
    },

    "position": None,

    "stats": {
        "scanned": 0,
        "signals": 0,
        "buys": 0,
        "sells": 0,
    },

    "logs": []
}

state_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def add_log(message, level="info"):
    now = time.strftime("%H:%M:%S")

    item = {
        "time": now,
        "message": message,
        "level": level
    }

    with state_lock:
        state["logs"].insert(0, item)
        state["logs"] = state["logs"][:50]

        state["bot"]["last_check"] = time.time()

    print(f"[{now}] {message}")


# ============================================================
# EXCEPTIONS
# ============================================================

class BinanceRateLimit(Exception):
    pass


class BinanceTemporaryError(Exception):
    pass


# ============================================================
# BINANCE REQUESTS
# ============================================================

session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY or ""
})


def public_get(path, params=None, timeout=15):
    try:
        r = session.get(
            BASE + path,
            params=params or {},
            timeout=timeout
        )

        if r.status_code == 429:
            raise BinanceRateLimit("429 Binance Rate Limit")

        if r.status_code >= 500:
            raise BinanceTemporaryError(
                f"Binance server error {r.status_code}"
            )

        r.raise_for_status()

        return r.json()

    except requests.RequestException as e:
        raise BinanceTemporaryError(str(e))


def signed_request(method, path, params=None, timeout=15):
    if not API_KEY or not API_SECRET:
        raise Exception("BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة")

    params = params.copy() if params else {}

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE + path + "?" + query

    try:

        if method == "GET":
            r = session.get(url, timeout=timeout)

        elif method == "POST":
            r = session.post(url, timeout=timeout)

        elif method == "DELETE":
            r = session.delete(url, timeout=timeout)

        else:
            raise Exception("HTTP method غير مدعوم")

        if r.status_code == 429:
            raise BinanceRateLimit("429 Binance Rate Limit")

        if r.status_code >= 500:
            raise BinanceTemporaryError(
                f"Binance server error {r.status_code}"
            )

        if not r.ok:
            try:
                data = r.json()
                msg = data.get("msg", str(data))
            except Exception:
                msg = r.text

            raise Exception(msg)

        return r.json()

    except requests.RequestException as e:
        raise BinanceTemporaryError(str(e))


# ============================================================
# ACCOUNT
# ============================================================

def get_account():
    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_usdt_balance():
    account = get_account()

    free = 0.0
    locked = 0.0

    for b in account.get("balances", []):
        if b["asset"] == "USDT":
            free = float(b["free"])
            locked = float(b["locked"])
            break

    return free + locked


# ============================================================
# PRICE
# ============================================================

def get_price(symbol):
    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


def get_all_prices():
    data = public_get("/api/v3/ticker/price")

    result = {}

    for item in data:
        try:
            result[item["symbol"]] = float(item["price"])
        except Exception:
            pass

    return result


# ============================================================
# EXCHANGE INFO
# ============================================================

exchange_cache = {
    "symbols": set(),
    "filters": {},
    "time": 0
}


def load_exchange_info(force=False):

    if (
        not force
        and exchange_cache["symbols"]
        and time.time() - exchange_cache["time"] < 1800
    ):
        return

    info = public_get("/api/v3/exchangeInfo")

    symbols = set()
    filters = {}

    for item in info.get("symbols", []):

        symbol = item.get("symbol")
        status = item.get("status")
        quote = item.get("quoteAsset")

        if status == "TRADING" and quote == "USDT":
            symbols.add(symbol)

        fs = {}

        for f in item.get("filters", []):

            if f["filterType"] == "LOT_SIZE":
                fs["stepSize"] = f["stepSize"]
                fs["minQty"] = f["minQty"]

            elif f["filterType"] == "MIN_NOTIONAL":
                fs["minNotional"] = f.get("minNotional", "0")

            elif f["filterType"] == "NOTIONAL":
                fs["minNotional"] = f.get("minNotional", "0")

        filters[symbol] = fs

    exchange_cache["symbols"] = symbols
    exchange_cache["filters"] = filters
    exchange_cache["time"] = time.time()

    add_log(
        f"تم تحميل معلومات Binance: {len(symbols)} زوج USDT",
        "success"
    )


def get_valid_usdt_symbols():

    load_exchange_info()

    return exchange_cache["symbols"]


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol, interval="15m", limit=200):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=20
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
            price - ema
        ) * multiplier + ema

    return ema


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    try:

        candles = get_klines(
            symbol,
            TIMEFRAME,
            200
        )

        if len(candles) < EMA_PERIOD + 5:
            return None

        closes = [
            float(x[4])
            for x in candles
        ]

        volumes = [
            float(x[5])
            for x in candles
        ]

        current = closes[-1]

        previous = closes[-2]

        ema200 = calculate_ema(
            closes,
            EMA_PERIOD
        )

        if ema200 is None:
            return None

        change_15m = (
            (current - previous)
            / previous
        ) * 100

        avg_volume = (
            sum(volumes[-21:-1]) / 20
        )

        current_volume = volumes[-1]

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 0
        )

        # ====================================================
        # V6 FAST ENTRY STRATEGY
        # ====================================================

        signal = False

        if current > ema200:

            if change_15m >= MIN_CHANGE_15M:

                signal = True

        return {
            "symbol": symbol,
            "price": current,
            "ema200": ema200,
            "change": change_15m,
            "volume_ratio": volume_ratio,
            "signal": signal
        }

    except BinanceRateLimit:
        raise

    except BinanceTemporaryError:
        raise

    except Exception:
        return None


# ============================================================
# SYMBOL FILTERS
# ============================================================

def get_symbol_filters(symbol):

    load_exchange_info()

    return exchange_cache["filters"].get(
        symbol,
        {}
    )


def round_step(value, step):

    try:

        value = Decimal(str(value))
        step = Decimal(str(step))

        if step <= 0:
            return float(value)

        result = (
            value / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

        return float(result)

    except Exception:
        return float(value)


# ============================================================
# ENTRY PRICE
# ============================================================

def calculate_entry(symbol):

    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 100
            }
        )

        buy_qty = 0.0
        buy_cost = 0.0

        for trade in trades:

            qty = float(trade["qty"])
            price = float(trade["price"])

            if trade.get("isBuyer"):

                buy_qty += qty
                buy_cost += qty * price

            else:

                sell_qty = qty

                if buy_qty > 0:

                    avg = buy_cost / buy_qty

                    reduce_qty = min(
                        sell_qty,
                        buy_qty
                    )

                    buy_qty -= reduce_qty
                    buy_cost -= (
                        reduce_qty * avg
                    )

        if buy_qty > 0:

            return buy_cost / buy_qty

    except Exception:
        pass

    return get_price(symbol)


# ============================================================
# FIND OPEN POSITION
# ============================================================

def find_open_position():

    add_log(
        "🔎 جاري التحقق من الصفقة المفتوحة...",
        "info"
    )

    # مهم:
    # إذا فشل الاتصال لا نعتبرها "لا توجد صفقة"

    account = get_account()

    # نجيب جميع الأسعار بطلب واحد
    prices = get_all_prices()

    valid_symbols = get_valid_usdt_symbols()

    candidates = []

    for balance in account.get("balances", []):

        asset = balance.get("asset")

        if not asset or asset == "USDT":
            continue

        free = float(balance.get("free", 0))
        locked = float(balance.get("locked", 0))

        quantity = free + locked

        if quantity <= 0:
            continue

        symbol = asset + "USDT"

        # العملة لازم يكون لها زوج USDT متداول
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

    # لا توجد صفقة
    if not candidates:

        add_log(
            "ℹ️ لا توجد صفقة مفتوحة",
            "info"
        )

        return None

    # لو فيه أكثر من رصيد نختار الأكبر قيمة
    candidates.sort(
        key=lambda x: x["value"],
        reverse=True
    )

    found = candidates[0]

    symbol = found["symbol"]

    entry = calculate_entry(symbol)

    current_price = found["price"]

    profit = (
        (current_price - entry)
        / entry
    ) * 100

    position = {
        "symbol": symbol,
        "asset": found["asset"],
        "quantity": found["quantity"],
        "entry": entry,
        "price": current_price,
        "value": found["value"],
        "profit": profit,
        "protection": None,
        "protection_level": 0,
        "opened_at": time.time()
    }

    add_log(
        f"✅ تم العثور على صفقة مفتوحة: {symbol} | "
        f"الدخول {entry:.8f} | "
        f"الربح {profit:+.2f}%",
        "success"
    )

    return position


# ============================================================
# BUY
# ============================================================

def buy_symbol(symbol):

    usdt = get_usdt_balance()

    if usdt <= 0:
        add_log(
            "❌ لا يوجد رصيد USDT للشراء",
            "error"
        )
        return None

    amount = usdt * (BUY_PERCENT / 100)

    if amount < 5:
        add_log(
            f"❌ الرصيد غير كافي: {amount:.2f} USDT",
            "error"
        )
        return None

    add_log(
        f"🟢 محاولة شراء {symbol} بقيمة {amount:.2f} USDT",
        "trade"
    )

    result = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{amount:.2f}"
        }
    )

    with state_lock:
        state["stats"]["buys"] += 1

    add_log(
        f"✅ تم تنفيذ شراء {symbol}",
        "success"
    )

    time.sleep(2)

    return find_open_position()


# ============================================================
# SELL
# ============================================================

def sell_position(position, reason="حماية الربح"):

    symbol = position["symbol"]
    asset = position["asset"]

    account = get_account()

    quantity = 0.0

    for balance in account.get("balances", []):

        if balance["asset"] == asset:

            quantity = float(
                balance["free"]
            )

            break

    if quantity <= 0:

        add_log(
            f"⚠️ لا توجد كمية متاحة للبيع: {symbol}",
            "warning"
        )

        return False

    filters = get_symbol_filters(symbol)

    step = filters.get(
        "stepSize",
        "0.000001"
    )

    quantity = round_step(
        quantity,
        step
    )

    if quantity <= 0:
        return False

    add_log(
        f"🔴 بيع {symbol} | السبب: {reason}",
        "trade"
    )

    signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": f"{quantity:.12f}"
        }
    )

    with state_lock:
        state["stats"]["sells"] += 1

    add_log(
        f"✅ تم بيع {symbol}",
        "success"
    )

    with state_lock:
        state["position"] = None

    return True


# ============================================================
# POSITION MANAGEMENT
# ============================================================

def manage_position(position):

    symbol = position["symbol"]

    try:

        price = get_price(symbol)

    except Exception as e:

        add_log(
            f"⚠️ تعذر تحديث سعر {symbol}: {e}",
            "warning"
        )

        return

    entry = float(position["entry"])

    profit = (
        (price - entry)
        / entry
    ) * 100

    position["price"] = price
    position["profit"] = profit
    position["value"] = (
        position["quantity"] * price
    )

    # ========================================================
    # حماية كل +1%
    #
    # +1%  => حماية +0.50%
    # +2%  => حماية +1.50%
    # +3%  => حماية +2.50%
    # +4%  => حماية +3.50%
    # ========================================================

    if profit >= PROTECTION_START:

        level = int(
            profit // PROTECTION_STEP
        )

        protection_profit = (
            level * PROTECTION_STEP
            - TRAILING_PERCENT
        )

        protection_price = (
            entry
            * (
                1
                + protection_profit / 100
            )
        )

        old_protection = (
            position.get("protection")
        )

        if (
            old_protection is None
            or protection_price > old_protection
        ):

            position["protection"] = protection_price
            position["protection_level"] = level

            add_log(
                f"🛡️ حماية مستوى +{level}% | "
                f"{symbol} | "
                f"الوقف {protection_price:.8f}",
                "protection"
            )

    # ========================================================
    # تنفيذ الحماية
    # ========================================================

    protection = position.get(
        "protection"
    )

    if protection:

        if price <= protection:

            sell_position(
                position,
                f"🛡️ ضرب وقف الحماية +{position.get('protection_level', 0)}%"
            )

            return

    with state_lock:
        state["position"] = position


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market():

    load_exchange_info()

    symbols = list(
        exchange_cache["symbols"]
    )

    add_log(
        f"🔎 بدء فحص السوق | {len(symbols)} زوج",
        "info"
    )

    with state_lock:
        state["bot"]["mode"] = "فحص السوق"
        state["bot"]["last_scan"] = time.time()
        state["stats"]["scanned"] = 0

    for index, symbol in enumerate(symbols, 1):

        # ====================================================
        # مهم:
        # إذا ظهرت صفقة أثناء الفحص نوقف البحث فوراً
        # ====================================================

        with state_lock:
            existing = state["position"]

        if existing:

            add_log(
                f"🛑 تم إيقاف الفحص بسبب وجود صفقة {existing['symbol']}",
                "warning"
            )

            return existing

        try:

            result = analyze_symbol(symbol)

            with state_lock:
                state["stats"]["scanned"] = index

            if not result:
                continue

            if result["signal"]:

                with state_lock:
                    state["stats"]["signals"] += 1

                add_log(
                    f"🚨 إشارة شراء: {symbol} | "
                    f"تغير {result['change']:+.2f}% | "
                    f"EMA200 {result['ema200']:.8f}",
                    "signal"
                )

                position = buy_symbol(symbol)

                if position:

                    with state_lock:
                        state["position"] = position
                        state["bot"]["mode"] = "إدارة صفقة"

                    return position

                # لا نبحث عن عدة صفقات
                return None

        except BinanceRateLimit:

            add_log(
                "⚠️ Binance Rate Limit أثناء الفحص",
                "warning"
            )

            time.sleep(10)

            return None

        except BinanceTemporaryError as e:

            add_log(
                f"⚠️ مشكلة مؤقتة من Binance: {e}",
                "warning"
            )

            return None

        except Exception:
            continue

    add_log(
        "✅ انتهى فحص السوق بدون صفقة",
        "success"
    )

    return None


# ============================================================
# TRADING ENGINE
# ============================================================

def trading_engine():

    print()
    print("==============================")
    print("🤖 مضارب أبو سعود V6 FAST PRO")
    print("==============================")
    print()

    add_log(
        "🤖 محرك التداول بدأ",
        "success"
    )

    while True:

        try:

            # =================================================
            # أول شيء: هل توجد صفقة؟
            # =================================================

            with state_lock:
                position = state["position"]

            if position is None:

                with state_lock:
                    state["bot"]["mode"] = "فحص الحساب"

                add_log(
                    "🔎 فحص الحساب لمعرفة هل توجد صفقة...",
                    "info"
                )

                found = find_open_position()

                if found:

                    with state_lock:
                        state["position"] = found
                        state["bot"]["mode"] = "إدارة صفقة"

                    add_log(
                        f"🎯 استعادة الصفقة: {found['symbol']}",
                        "success"
                    )

                    position = found

                else:

                    # =================================================
                    # لا توجد صفقة -> فحص السوق
                    # =================================================

                    scan_market()

                    time.sleep(
                        POSITION_CHECK_SECONDS
                    )

                    continue

            # =================================================
            # إدارة الصفقة
            # =================================================

            with state_lock:
                position = state["position"]

            if position:

                with state_lock:
                    state["bot"]["mode"] = (
                        f"إدارة {position['symbol']}"
                    )

                manage_position(position)

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except BinanceRateLimit as e:

            add_log(
                f"⚠️ Binance Rate Limit: {e}",
                "warning"
            )

            with state_lock:
                state["bot"]["last_error"] = str(e)
                state["bot"]["message"] = (
                    "تم إيقاف الفحص مؤقتًا بسبب ضغط API"
                )

            time.sleep(30)

        except BinanceTemporaryError as e:

            add_log(
                f"⚠️ Binance مؤقتًا غير متاح: {e}",
                "warning"
            )

            with state_lock:
                state["bot"]["last_error"] = str(e)

            time.sleep(30)

        except requests.RequestException as e:

            add_log(
                f"⚠️ مشكلة اتصال: {e}",
                "warning"
            )

            time.sleep(30)

        except Exception as e:

            add_log(
                f"❌ خطأ في محرك التداول: {e}",
                "error"
            )

            with state_lock:
                state["bot"]["last_error"] = str(e)

            time.sleep(30)


# ============================================================
# PROFESSIONAL DASHBOARD
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
    background:
        radial-gradient(circle at top right,#172554 0,#080b16 35%,#05070d 100%);
    color: #f8fafc;
    font-family:
        Arial,
        Tahoma,
        sans-serif;
}

.container {
    max-width: 1200px;
    margin: auto;
    padding: 18px;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
    margin-bottom: 20px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
}

.logo {
    width: 48px;
    height: 48px;
    border-radius: 15px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg,#2563eb,#7c3aed);
    font-size: 25px;
    box-shadow: 0 10px 30px rgba(37,99,235,.35);
}

h1 {
    margin: 0;
    font-size: 22px;
}

.subtitle {
    color: #94a3b8;
    font-size: 12px;
    margin-top: 5px;
}

.status {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 15px;
    border-radius: 30px;
    background: rgba(15,23,42,.75);
    border: 1px solid #1e293b;
}

.dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 12px #22c55e;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(4,1fr);
    gap: 14px;
}

.card {
    background: rgba(15,23,42,.78);
    border: 1px solid rgba(148,163,184,.12);
    border-radius: 18px;
    padding: 18px;
    box-shadow:
        0 15px 45px rgba(0,0,0,.25);
    backdrop-filter: blur(12px);
}

.label {
    color: #94a3b8;
    font-size: 12px;
    margin-bottom: 9px;
}

.value {
    font-size: 24px;
    font-weight: 800;
}

.small {
    font-size: 12px;
    color: #94a3b8;
    margin-top: 6px;
}

.green {
    color: #22c55e;
}

.red {
    color: #ef4444;
}

.blue {
    color: #60a5fa;
}

.yellow {
    color: #facc15;
}

.section {
    margin-top: 18px;
}

.section-title {
    font-size: 16px;
    font-weight: bold;
    margin-bottom: 12px;
}

.position {
    display: grid;
    grid-template-columns:
        repeat(4,1fr);
    gap: 12px;
}

.position-main {
    grid-column: span 4;
    background:
        linear-gradient(
            135deg,
            rgba(37,99,235,.18),
            rgba(124,58,237,.10)
        );
}

.coin {
    font-size: 30px;
    font-weight: 900;
}

.badge {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 20px;
    font-size: 11px;
    background: rgba(34,197,94,.12);
    color: #4ade80;
    margin-top: 8px;
}

.progress {
    width: 100%;
    height: 8px;
    background: #111827;
    border-radius: 20px;
    overflow: hidden;
    margin-top: 12px;
}

.progress-bar {
    height: 100%;
    width: 0%;
    background:
        linear-gradient(90deg,#2563eb,#22c55e);
    border-radius: 20px;
    transition: width .4s;
}

.logs {
    max-height: 360px;
    overflow-y: auto;
}

.log {
    display: flex;
    gap: 10px;
    padding: 11px 0;
    border-bottom: 1px solid rgba(148,163,184,.08);
    font-size: 12px;
}

.log-time {
    color: #64748b;
    min-width: 55px;
}

.log-success {
    color: #4ade80;
}

.log-error {
    color: #f87171;
}

.log-warning {
    color: #facc15;
}

.log-signal {
    color: #60a5fa;
}

.log-protection {
    color: #c084fc;
}

.empty {
    text-align: center;
    padding: 40px;
    color: #64748b;
}

.footer {
    text-align: center;
    color: #475569;
    font-size: 11px;
    margin-top: 20px;
}

@media(max-width:850px) {

    .grid {
        grid-template-columns:
            repeat(2,1fr);
    }

    .position {
        grid-template-columns:
            repeat(2,1fr);
    }

    .position-main {
        grid-column: span 2;
    }

}

@media(max-width:520px) {

    .container {
        padding: 12px;
    }

    .header {
        align-items: flex-start;
    }

    .grid {
        grid-template-columns: 1fr 1fr;
    }

    .card {
        padding: 14px;
    }

    .value {
        font-size: 19px;
    }

    .coin {
        font-size: 25px;
    }

}

</style>

</head>

<body>

<div class="container">

    <div class="header">

        <div class="brand">

            <div class="logo">🤖</div>

            <div>
                <h1>مضارب أبو سعود</h1>
                <div class="subtitle">
                    Binance Spot • V6 FAST PRO
                </div>
            </div>

        </div>

        <div class="status">
            <span class="dot"></span>
            <span id="status">يعمل</span>
        </div>

    </div>


    <!-- ACCOUNT -->

    <div class="grid">

        <div class="card">

            <div class="label">
                💵 رصيد USDT
            </div>

            <div class="value" id="usdt">
                --
            </div>

        </div>


        <div class="card">

            <div class="label">
                📊 حالة المحرك
            </div>

            <div class="value blue"
                 id="mode">
                --
            </div>

        </div>


        <div class="card">

            <div class="label">
                🔎 العملات المفحوصة
            </div>

            <div class="value"
                 id="scanned">
                0
            </div>

        </div>


        <div class="card">

            <div class="label">
                🚨 الإشارات
            </div>

            <div class="value yellow"
                 id="signals">
                0
            </div>

        </div>

    </div>


    <!-- POSITION -->

    <div class="section">

        <div class="section-title">
            📈 الصفقة الحالية
        </div>

        <div id="positionBox"
             class="card">

            <div class="empty">
                لا توجد صفقة مفتوحة
            </div>

        </div>

    </div>


    <!-- STATS -->

    <div class="section">

        <div class="grid">

            <div class="card">

                <div class="label">
                    🟢 عمليات الشراء
                </div>

                <div class="value green"
                     id="buys">
                    0
                </div>

            </div>

            <div class="card">

                <div class="label">
                    🔴 عمليات البيع
                </div>

                <div class="value red"
                     id="sells">
                    0
                </div>

            </div>

            <div class="card">

                <div class="label">
                    ⏱️ آخر فحص
                </div>

                <div class="value"
                     id="lastCheck">
                    --
                </div>

            </div>

            <div class="card">

                <div class="label">
                    ⚙️ النظام
                </div>

                <div class="value"
                     id="system">
                    V6 PRO
                </div>

            </div>

        </div>

    </div>


    <!-- LOGS -->

    <div class="section">

        <div class="section-title">
            📋 سجل العمليات
        </div>

        <div class="card logs"
             id="logs">

            <div class="empty">
                جاري تحميل السجل...
            </div>

        </div>

    </div>


    <div class="footer">
        مضارب أبو سعود 🤖 • Binance Spot
        <br>
        التحديث تلقائي كل 5 ثواني
    </div>

</div>


<script>

function money(v) {

    if (v === null ||
        v === undefined ||
        isNaN(v)) {
        return "--";
    }

    return Number(v).toLocaleString(
        "en-US",
        {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }
    );
}


function price(v) {

    if (v === null ||
        v === undefined ||
        isNaN(v)) {
        return "--";
    }

    let n = Number(v);

    if (n >= 1) {
        return n.toFixed(4);
    }

    return n.toFixed(8);
}


function timeAgo(ts) {

    if (!ts) {
        return "--";
    }

    let diff =
        Math.floor(
            (Date.now() / 1000 - ts)
        );

    if (diff < 60) {
        return diff + " ث";
    }

    if (diff < 3600) {
        return Math.floor(diff / 60) + " د";
    }

    return Math.floor(diff / 3600) + " س";
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
        ).innerText =
            data.bot.running
            ? "البوت يعمل"
            : "متوقف";


        document.getElementById(
            "mode"
        ).innerText =
            data.bot.mode || "--";


        document.getElementById(
            "usdt"
        ).innerText =
            money(data.account.usdt);


        document.getElementById(
            "scanned"
        ).innerText =
            data.stats.scanned;


        document.getElementById(
            "signals"
        ).innerText =
            data.stats.signals;


        document.getElementById(
            "buys"
        ).innerText =
            data.stats.buys;


        document.getElementById(
            "sells"
        ).innerText =
            data.stats.sells;


        document.getElementById(
            "lastCheck"
        ).innerText =
            timeAgo(data.bot.last_check);


        renderPosition(
            data.position
        );


        renderLogs(
            data.logs
        );

    } catch(e) {

        document.getElementById(
            "status"
        ).innerText =
            "مشكلة اتصال";

    }

}


function renderPosition(p) {

    const box =
        document.getElementById(
            "positionBox"
        );

    if (!p) {

        box.innerHTML = `
            <div class="empty">
                💤 لا توجد صفقة مفتوحة
                <br>
                <span class="small">
                    البوت يبحث عن فرصة حسب الاستراتيجية
                </span>
            </div>
        `;

        return;
    }


    const profit =
        Number(p.profit || 0);

    const profitClass =
        profit >= 0
        ? "green"
        : "red";


    let level =
        Number(
            p.protection_level || 0
        );


    let protection =
        p.protection
        ? price(p.protection)
        : "--";


    let progress =
        Math.max(
            0,
            Math.min(
                100,
                profit * 5
            )
        );


    box.innerHTML = `

        <div class="position">

            <div class="card position-main">

                <div class="label">
                    الصفقة المفتوحة
                </div>

                <div class="coin">
                    ${p.symbol}
                </div>

                <span class="badge">
                    🟢 تتم إدارتها تلقائياً
                </span>

                <div class="progress">
                    <div
                        class="progress-bar"
                        style="width:${progress}%">
                    </div>
                </div>

            </div>


            <div class="card">

                <div class="label">
                    💰 سعر الدخول
                </div>

                <div class="value">
                    ${price(p.entry)}
                </div>

            </div>


            <div class="card">

                <div class="label">
                    📍 السعر الحالي
                </div>

                <div class="value">
                    ${price(p.price)}
                </div>

            </div>


            <div class="card">

                <div class="label">
                    📈 الربح / الخسارة
                </div>

                <div class="value ${profitClass}">
                    ${profit >= 0 ? "+" : ""}
                    ${profit.toFixed(2)}%
                </div>

            </div>


            <div class="card">

                <div class="label">
                    🛡️ وقف الحماية
                </div>

                <div class="value yellow">
                    ${protection}
                </div>

                <div class="small">
                    مستوى +${level}%
                </div>

            </div>


            <div class="card">

                <div class="label">
                    🪙 الكمية
                </div>

                <div class="value">
                    ${Number(
                        p.quantity || 0
                    ).toFixed(6)}
                </div>

            </div>


            <div class="card">

                <div class="label">
                    💵 قيمة الصفقة
                </div>

                <div class="value">
                    ${money(p.value)}
                </div>

            </div>


            <div class="card">

                <div class="label">
                    ⚙️ الحماية
                </div>

                <div class="value blue">
                    +${level}%
                </div>

                <div class="small">
                    ترفع كل 1% ربح
                </div>

            </div>

        </div>

    `;
}


function renderLogs(logs) {

    const box =
        document.getElementById(
            "logs"
        );

    if (!logs ||
        logs.length === 0) {

        box.innerHTML = `
            <div class="empty">
                لا توجد عمليات حتى الآن
            </div>
        `;

        return;
    }


    box.innerHTML =
        logs.map(
            x => `

            <div class="log">

                <div class="log-time">
                    ${x.time}
                </div>

                <div class="log-${x.level}">
                    ${x.message}
                </div>

            </div>

        `
        ).join("");

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
def dashboard():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    try:

        # تحديث الرصيد بدون تعطيل الصفحة
        try:
            usdt = get_usdt_balance()

            with state_lock:
                state["account"]["usdt"] = usdt
                state["account"]["total"] = usdt

        except Exception:
            pass

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

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# START
# ============================================================

def main():

    print()
    print("==============================")
    print("🚀 تشغيل V6 FAST PRO")
    print("==============================")

    if not API_KEY or not API_SECRET:

        print(
            "❌ BINANCE_API_KEY أو BINANCE_API_SECRET غير موجودة"
        )

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    # تحميل معلومات Binance مرة واحدة
    try:

        load_exchange_info()

    except Exception as e:

        print(
            f"⚠️ تعذر تحميل Exchange Info: {e}"
        )


    # تشغيل محرك التداول
    thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    thread.start()


    print(
        f"🌐 الموقع يعمل على PORT {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


if __name__ == "__main__":

    main()
