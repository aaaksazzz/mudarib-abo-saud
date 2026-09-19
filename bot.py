import os
import time
import json
import hmac
import hashlib
import threading
import urllib.parse
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify

# =========================================================
# مضارب أبو سعود V2 🤖
# Binance Spot + Dashboard
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

API_BASE = "https://api.binance.com"
MARKET_BASE = "https://data-api.binance.vision"

STATE_FILE = "state.json"
HISTORY_FILE = "trade_history.json"

INITIAL_STOP = -0.02       # -2%
PROFIT_STEP = 0.01         # كل +1%
FEE_RATE = 0.001

MIN_USDT = 5.0
TRADE_USDT_PERCENT = 0.999

SCAN_INTERVAL = 180
POSITION_CHECK_SECONDS = 5

session = requests.Session()
session.headers.update({"User-Agent": "Mudarib-Abo-Saud-V2/1.0"})

state_lock = threading.Lock()

app = Flask(__name__)


# =========================================================
# LOG
# =========================================================

def log(msg):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


# =========================================================
# FILES
# =========================================================

def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        log(f"⚠️ خطأ قراءة {filename}: {e}")
        return default


def save_json(filename, data):
    temp = filename + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp, filename)


def load_state():
    return load_json(STATE_FILE, {})


def save_state(data):
    with state_lock:
        save_json(STATE_FILE, data)


def load_history():
    return load_json(HISTORY_FILE, [])


def save_history(data):
    save_json(HISTORY_FILE, data)


# =========================================================
# BINANCE SIGNED REQUEST
# =========================================================

def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise Exception("BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة")

    params = params or {}

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(params, doseq=True)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = API_BASE + path + "?" + query

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    response = session.request(
        method,
        url,
        headers=headers,
        timeout=20
    )

    try:
        data = response.json()
    except Exception:
        data = response.text

    if response.status_code >= 400:
        raise Exception(
            f"HTTP {response.status_code} | {data}"
        )

    return data


# =========================================================
# PUBLIC REQUEST
# =========================================================

def public_get(path, params=None):
    url = MARKET_BASE + path

    for attempt in range(4):
        try:
            r = session.get(
                url,
                params=params or {},
                timeout=15
            )

            if r.status_code in (418, 429):
                wait = min(30, 2 ** attempt + 1)
                log(
                    f"⚠️ Binance Rate Limit {r.status_code} "
                    f"انتظار {wait} ثواني"
                )
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            if attempt == 3:
                raise

            time.sleep(2)


# =========================================================
# ACCOUNT
# =========================================================

def get_account():
    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_usdt_balance():
    account = get_account()

    for b in account.get("balances", []):
        if b["asset"] == "USDT":
            return float(b["free"])

    return 0.0


def get_asset_balance(asset):
    account = get_account()

    for b in account.get("balances", []):
        if b["asset"] == asset:
            return float(b["free"]) + float(b["locked"])

    return 0.0


# =========================================================
# EXCHANGE INFO
# =========================================================

_exchange_info = None
_exchange_lock = threading.Lock()


def get_exchange_info():
    global _exchange_info

    if _exchange_info is not None:
        return _exchange_info

    with _exchange_lock:
        if _exchange_info is None:
            log("📥 تحميل معلومات Binance...")
            _exchange_info = public_get(
                "/api/v3/exchangeInfo"
            )

    return _exchange_info


def get_symbol_info(symbol):
    info = get_exchange_info()

    for s in info.get("symbols", []):
        if s["symbol"] == symbol:
            return s

    return None


def get_filters(symbol):
    info = get_symbol_info(symbol)

    if not info:
        raise Exception(f"العملة غير موجودة: {symbol}")

    result = {
        "stepSize": 0.0,
        "minQty": 0.0,
        "minNotional": 0.0,
        "tickSize": 0.0
    }

    for f in info.get("filters", []):

        if f["filterType"] == "LOT_SIZE":
            result["stepSize"] = float(f["stepSize"])
            result["minQty"] = float(f["minQty"])

        elif f["filterType"] == "MIN_NOTIONAL":
            result["minNotional"] = float(
                f.get("minNotional", 0)
            )

        elif f["filterType"] == "NOTIONAL":
            result["minNotional"] = float(
                f.get("minNotional", 0)
            )

        elif f["filterType"] == "PRICE_FILTER":
            result["tickSize"] = float(
                f["tickSize"]
            )

    return result


def floor_step(value, step):
    if step <= 0:
        return value

    d_value = Decimal(str(value))
    d_step = Decimal(str(step))

    result = (
        d_value / d_step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * d_step

    return float(result)


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):
    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


# =========================================================
# MARKET BUY
# =========================================================

def market_buy(symbol, usdt_amount):
    try:
        log(
            f"🛒 محاولة شراء {symbol} "
            f"بـ {usdt_amount:.4f} USDT"
        )

        filters = get_filters(symbol)

        if filters["minNotional"] > 0:
            if usdt_amount < filters["minNotional"]:
                raise Exception(
                    f"المبلغ أقل من MIN_NOTIONAL "
                    f"({filters['minNotional']} USDT)"
                )

        params = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{usdt_amount:.8f}",
            "newOrderRespType": "FULL"
        }

        result = signed_request(
            "POST",
            "/api/v3/order",
            params
        )

        executed_qty = float(
            result.get("executedQty", 0)
        )

        cumm_quote = float(
            result.get("cummulativeQuoteQty", 0)
        )

        if executed_qty <= 0:
            raise Exception(
                f"Binance لم تنفذ كمية | {result}"
            )

        if cumm_quote <= 0:
            raise Exception(
                f"قيمة الشراء غير معروفة | {result}"
            )

        avg_price = cumm_quote / executed_qty

        log(
            f"✅ تم الشراء {symbol} | "
            f"الكمية: {executed_qty} | "
            f"متوسط: {avg_price}"
        )

        return {
            "symbol": symbol,
            "qty": executed_qty,
            "entry": avg_price,
            "orderId": result.get("orderId"),
            "quote": cumm_quote
        }

    except Exception as e:

        log("❌ فشل شراء Binance")
        log(f"❌ السبب الحقيقي: {e}")

        return None


# =========================================================
# STOP LOSS
# =========================================================

def place_stop(symbol, quantity, stop_price):

    try:
        filters = get_filters(symbol)

        quantity = floor_step(
            quantity,
            filters["stepSize"]
        )

        if quantity <= 0:
            raise Exception(
                f"الكمية بعد التقريب أصبحت 0"
            )

        stop_price = floor_step(
            stop_price,
            filters["tickSize"]
        )

        if stop_price <= 0:
            raise Exception(
                f"سعر الوقف غير صحيح: {stop_price}"
            )

        params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": f"{quantity:.8f}",
            "stopPrice": f"{stop_price:.8f}",
            "newOrderRespType": "RESULT"
        }

        result = signed_request(
            "POST",
            "/api/v3/order",
            params
        )

        log(
            f"🛡️ تم وضع وقف Binance "
            f"{symbol} عند {stop_price}"
        )

        return result

    except Exception as e:
        log(f"❌ فشل وضع وقف Binance: {e}")
        return None


# =========================================================
# CANCEL ORDER
# =========================================================

def cancel_order(symbol, order_id):

    try:
        return signed_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            }
        )

    except Exception as e:
        log(
            f"⚠️ فشل إلغاء أمر الوقف "
            f"{order_id}: {e}"
        )

        return None


# =========================================================
# ORDER STATUS
# =========================================================

def get_order(symbol, order_id):

    try:
        return signed_request(
            "GET",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            }
        )

    except Exception as e:
        log(f"⚠️ فشل فحص الأمر: {e}")
        return None


# =========================================================
# OPEN POSITION
# =========================================================

def position_exists(symbol):

    if not symbol:
        return False

    asset = symbol.replace("USDT", "")

    try:
        qty = get_asset_balance(asset)

        filters = get_filters(symbol)

        return qty >= filters["minQty"]

    except Exception as e:
        log(f"⚠️ فشل فحص الصفقة: {e}")
        return False


# =========================================================
# SAVE TRADE
# =========================================================

def add_history(trade):

    history = load_history()

    history.append(trade)

    if len(history) > 500:
        history = history[-500:]

    save_history(
        HISTORY_FILE,
        history
    )


# =========================================================
# INITIAL STOP
# =========================================================

def ensure_initial_stop(state):

    symbol = state["symbol"]
    entry = float(state["entry"])
    qty = float(state["qty"])

    if state.get("stop_order_id"):
        return state

    stop_price = entry * (1 + INITIAL_STOP)

    result = place_stop(
        symbol,
        qty,
        stop_price
    )

    if result:

        state["stop_order_id"] = result.get(
            "orderId"
        )

        state["stop_price"] = stop_price
        state["locked_profit"] = INITIAL_STOP

        save_state(state)

    return state


# =========================================================
# RAISE STOP
# =========================================================

def raise_stop(state, current_profit):

    symbol = state["symbol"]
    entry = float(state["entry"])
    qty = float(state["qty"])

    # مثال:
    # +1% => وقف +1%
    # +2% => وقف +2%
    # +3% => وقف +3%

    level = int(
        current_profit / PROFIT_STEP
    )

    if level < 1:
        return state

    lock_profit = level * PROFIT_STEP

    old_lock = float(
        state.get("locked_profit", INITIAL_STOP)
    )

    if lock_profit <= old_lock:
        return state

    new_stop = entry * (1 + lock_profit)

    old_order_id = state.get(
        "stop_order_id"
    )

    # إلغاء الوقف القديم
    if old_order_id:
        old_status = get_order(
            symbol,
            old_order_id
        )

        if old_status:
            status = old_status.get("status")

            if status == "NEW":
                cancel_order(
                    symbol,
                    old_order_id
                )

    # إنشاء الوقف الجديد
    result = place_stop(
        symbol,
        qty,
        new_stop
    )

    if result:

        state["stop_order_id"] = result.get(
            "orderId"
        )

        state["stop_price"] = new_stop
        state["locked_profit"] = lock_profit

        save_state(state)

        log(
            f"🔒 تأمين ربح {lock_profit * 100:.0f}% "
            f"| الوقف الجديد: {new_stop}"
        )

    return state


# =========================================================
# MANAGE POSITION
# =========================================================

def manage_position(state):

    symbol = state["symbol"]

    log(
        f"📌 متابعة الصفقة: {symbol}"
    )

    state = ensure_initial_stop(state)

    save_state(state)

    while True:

        try:

            if not position_exists(symbol):

                current = get_price(symbol)

                entry = float(
                    state["entry"]
                )

                profit = (
                    (current - entry)
                    / entry
                )

                history = load_history()

                history.append({
                    "symbol": symbol,
                    "entry": entry,
                    "exit": current,
                    "profit_percent": profit * 100,
                    "profit_usdt": (
                        current - entry
                    ) * float(state["qty"]),
                    "time": time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                })

                save_history(
                    HISTORY_FILE,
                    history[-500:]
                )

                save_state({})

                log(
                    f"🏁 انتهت الصفقة {symbol}"
                )

                return

            current = get_price(symbol)

            entry = float(
                state["entry"]
            )

            qty = float(
                state["qty"]
            )

            profit = (
                (current - entry)
                / entry
            )

            profit_usdt = (
                current - entry
            ) * qty

            state["current_price"] = current
            state["profit_percent"] = profit * 100
            state["profit_usdt"] = profit_usdt

            save_state(state)

            log(
                f"📊 {symbol} | "
                f"السعر {current:.8f} | "
                f"الربح {profit * 100:.2f}% | "
                f"{profit_usdt:.4f} USDT"
            )

            if profit >= PROFIT_STEP:

                state = raise_stop(
                    state,
                    profit
                )

            # فحص أمر الوقف
            order_id = state.get(
                "stop_order_id"
            )

            if order_id:

                order = get_order(
                    symbol,
                    order_id
                )

                if order:

                    status = order.get(
                        "status"
                    )

                    if status in (
                        "FILLED",
                        "CANCELED",
                        "EXPIRED",
                        "REJECTED"
                    ):

                        if status == "FILLED":

                            log(
                                f"🛑 تم تنفيذ وقف Binance "
                                f"للصفقة {symbol}"
                            )

                            time.sleep(2)

                            if not position_exists(
                                symbol
                            ):
                                save_state({})

                                return

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            log(
                f"⚠️ خطأ متابعة الصفقة: {e}"
            )

            time.sleep(5)


# =========================================================
# RESTORE
# =========================================================

def restore_trade():

    state = load_state()

    if not state:
        return False

    symbol = state.get("symbol")

    if not symbol:
        save_state({})
        return False

    try:

        if position_exists(symbol):

            log(
                f"🔄 وجدت صفقة مفتوحة "
                f"{symbol} — استئناف المتابعة"
            )

            manage_position(state)

            return True

        else:

            log(
                f"⚠️ الصفقة المحفوظة {symbol} "
                f"غير موجودة الآن"
            )

            save_state({})

    except Exception as e:

        log(
            f"⚠️ فشل استعادة الصفقة: {e}"
        )

    return False


# =========================================================
# SYMBOLS
# =========================================================

def get_usdt_symbols():

    info = get_exchange_info()

    symbols = []

    for s in info.get("symbols", []):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get("isSpotTradingAllowed") is False:
            continue

        symbol = s["symbol"]

        if symbol.endswith("USDT"):
            symbols.append(symbol)

    return symbols


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval, limit=210):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:
        result = (
            (price - result)
            * multiplier
            + result
        )

    return result


# =========================================================
# SCAN
# =========================================================

def scan_symbol(symbol):

    try:

        k15 = get_klines(
            symbol,
            "15m",
            210
        )

        if len(k15) < 205:
            return False

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

        if not ema200_15:
            return False

        resistance = max(
            highs15[-21:-1]
        )

        avg_volume = sum(
            volumes15[-21:-1]
        ) / 20

        current_volume = volumes15[-1]

        volume_ratio = (
            current_volume
            / avg_volume
            if avg_volume > 0
            else 0
        )

        breakout = (
            (price - resistance)
            / resistance
            if resistance > 0
            else 0
        )

        move = (
            (price - closes15[-2])
            / closes15[-2]
            if closes15[-2] > 0
            else 0
        )

        # 15m شروط
        if price <= ema200_15:
            return False

        if price <= resistance:
            return False

        if volume_ratio < 1.5:
            return False

        if move < 0.005 or move > 0.04:
            return False

        # 1H تأكيد
        k1h = get_klines(
            symbol,
            "1h",
            210
        )

        if len(k1h) < 205:
            return False

        closes1h = [
            float(x[4])
            for x in k1h
        ]

        ema200_1h = ema(
            closes1h[-201:],
            200
        )

        if not ema200_1h:
            return False

        if price <= ema200_1h:
            return False

        log(
            f"👀 مرشح 15m: {symbol} | "
            f"حجم {volume_ratio:.2f}x | "
            f"اختراق {breakout * 100:.2f}%"
        )

        return True

    except Exception as e:

        log(
            f"⚠️ فشل فحص {symbol}: {e}"
        )

        return False


# =========================================================
# OPEN TRADE
# =========================================================

def open_trade(symbol):

    try:

        balance = get_usdt_balance()

        amount = balance * TRADE_USDT_PERCENT

        if amount < MIN_USDT:
            log(
                f"⚠️ الرصيد غير كافي للشراء: "
                f"{balance:.4f} USDT"
            )
            return False

        result = market_buy(
            symbol,
            amount
        )

        if not result:

            log("❌ لم تفتح الصفقة")
            return False

        state = {
            "symbol": symbol,
            "entry": result["entry"],
            "current_price": result["entry"],
            "qty": result["qty"],
            "order_id": result["orderId"],
            "opened_at": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "profit_percent": 0,
            "profit_usdt": 0,
            "locked_profit": INITIAL_STOP,
            "stop_price": result["entry"] * (
                1 + INITIAL_STOP
            ),
            "stop_order_id": None
        }

        save_state(state)

        state = ensure_initial_stop(
            state
        )

        manage_position(state)

        return True

    except Exception as e:

        log(
            f"❌ خطأ فتح الصفقة: {e}"
        )

        return False


# =========================================================
# MAIN BOT
# =========================================================

def bot_loop():

    time.sleep(3)

    log("================================")
    log("🤖 مضارب أبو سعود V2")
    log("📊 Binance Spot")
    log("📈 15m + 1h")
    log("🛡️ وقف أولي -2%")
    log("🔒 تأمين كل +1%")
    log("================================")

    if not API_KEY or not API_SECRET:
        log(
            "❌ مفاتيح Binance غير موجودة"
        )
        return

    while True:

        try:

            # أول شيء: هل توجد صفقة محفوظة؟
            if restore_trade():
                continue

            balance = get_usdt_balance()

            log(
                f"💰 رصيد USDT: {balance:.4f}"
            )

            if balance < MIN_USDT:

                log(
                    f"⚠️ الرصيد أقل من "
                    f"{MIN_USDT} USDT"
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            symbols = get_usdt_symbols()

            log(
                f"🔎 فحص {len(symbols)} عملة..."
            )

            for symbol in symbols:

                # لا تفحص إذا فتحت صفقة أثناء الدورة
                current_state = load_state()

                if current_state.get("symbol"):
                    break

                try:

                    if scan_symbol(symbol):

                        log(
                            f"🔥 إشارة شراء: "
                            f"{symbol}"
                        )

                        if open_trade(symbol):
                            break

                        log(
                            "❌ نكمل البحث بعد فشل الشراء"
                        )

                except Exception as e:

                    log(
                        f"⚠️ {symbol}: {e}"
                    )

                time.sleep(0.08)

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            log(
                f"❌ خطأ رئيسي: {e}"
            )

            time.sleep(10)


# =========================================================
# DASHBOARD API
# =========================================================

@app.route("/")
def home():

    state = load_state()
    history = load_history()

    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مضارب أبو سعود V2</title>

<style>
body {{
    margin:0;
    background:#0b0f14;
    color:#fff;
    font-family:Arial,sans-serif;
}}

.container {{
    max-width:1100px;
    margin:auto;
    padding:20px;
}}

.card {{
    background:#121923;
    border:1px solid #263241;
    border-radius:18px;
    padding:20px;
    margin-bottom:15px;
}}

h1 {{
    margin-top:0;
}}

.online {{
    color:#35d07f;
    font-weight:bold;
}}

.grid {{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
    gap:12px;
}}

.box {{
    background:#0d141d;
    padding:15px;
    border-radius:14px;
}}

.value {{
    font-size:22px;
    font-weight:bold;
    margin-top:8px;
}}

.green {{
    color:#35d07f;
}}

.red {{
    color:#ff5c67;
}}

.small {{
    color:#98a5b5;
    font-size:13px;
}}

button {{
    border:0;
    border-radius:10px;
    padding:10px 15px;
    cursor:pointer;
}}
</style>

<script>
async function update() {{
    try {{
        const r = await fetch('/api/dashboard');
        const d = await r.json();

        document.getElementById('status').innerText =
            d.online ? '🟢 ONLINE' : '🔴 OFFLINE';

        document.getElementById('balance').innerText =
            Number(d.balance).toFixed(4) + ' USDT';

        const t = d.trade;

        if (t && t.symbol) {{
            document.getElementById('trade').innerHTML = `
                <div class="grid">
                    <div class="box">
                        العملة
                        <div class="value">${{t.symbol}}</div>
                    </div>

                    <div class="box">
                        الدخول
                        <div class="value">${{t.entry}}</div>
                    </div>

                    <div class="box">
                        السعر الحالي
                        <div class="value">${{t.current_price}}</div>
                    </div>

                    <div class="box">
                        الربح
                        <div class="value ${{t.profit_percent >= 0 ? 'green':'red'}}">
                            ${{Number(t.profit_percent).toFixed(2)}}%
                        </div>
                    </div>

                    <div class="box">
                        الربح USDT
                        <div class="value">
                            ${{Number(t.profit_usdt).toFixed(4)}}
                        </div>
                    </div>

                    <div class="box">
                        وقف Binance
                        <div class="value">
                            ${{t.stop_price || '-'}}
                        </div>
                    </div>

                    <div class="box">
                        تأمين الربح
                        <div class="value">
                            ${{(Number(t.locked_profit || -0.02) * 100).toFixed(0)}}%
                        </div>
                    </div>
                </div>
            `;
        }} else {{
            document.getElementById('trade').innerHTML =
                '<div class="small">لا توجد صفقة مفتوحة حالياً</div>';
        }}

    }} catch(e) {{
        document.getElementById('status').innerText =
            '🔴 خطأ اتصال';
    }}
}}

setInterval(update,5000);
window.onload=update;
</script>
</head>

<body>

<div class="container">

<div class="card">
<h1>🤖 مضارب أبو سعود V2</h1>
<div id="status" class="online">جاري الاتصال...</div>
</div>

<div class="card">
<div class="grid">

<div class="box">
الرصيد
<div id="balance" class="value">...</div>
</div>

<div class="box">
الفريم
<div class="value">15m + 1h</div>
</div>

<div class="box">
وقف البداية
<div class="value">-2%</div>
</div>

<div class="box">
تأمين الربح
<div class="value">كل +1%</div>
</div>

</div>
</div>

<div class="card">
<h2>📊 الصفقة الحالية</h2>
<div id="trade">
جاري التحميل...
</div>
</div>

</div>

</body>
</html>
"""


@app.route("/api/dashboard")
def dashboard():

    state = load_state()

    try:
        balance = get_usdt_balance()
        connected = True
    except Exception:
        balance = 0
        connected = False

    return jsonify({
        "online": True,
        "binance_connected": connected,
        "balance": balance,
        "trade": state if state else None
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "bot": "Mudarib Abo Saud V2"
    })


# =========================================================
# START BOT THREAD
# =========================================================

def start_bot():

    thread = threading.Thread(
        target=bot_loop,
        daemon=True
    )

    thread.start()


start_bot()


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
