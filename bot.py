import os
import time
import json
import hmac
import hashlib
import threading
import urllib.parse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify

# =========================================================
# مضارب أبو سعود V2 🤖
# Binance Spot + Dashboard PRO
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

API_BASE = "https://api.binance.com"
MARKET_BASE = "https://data-api.binance.vision"

STATE_FILE = "state.json"
HISTORY_FILE = "trade_history.json"

INITIAL_STOP = -0.02
PROFIT_STEP = 0.01
FEE_RATE = 0.001

MIN_USDT = 5.0
TRADE_USDT_PERCENT = 0.999

SCAN_INTERVAL = 180
POSITION_CHECK_SECONDS = 5

session = requests.Session()
session.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-V2/2.0"
})

state_lock = threading.Lock()
history_lock = threading.Lock()

app = Flask(__name__)

BOT_STARTED_AT = time.time()
LAST_SCAN_AT = 0
LAST_SCAN_COUNT = 0
LAST_SIGNAL = None
LAST_ERROR = None


# =========================================================
# LOG
# =========================================================

def log(msg):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


# =========================================================
# TIME
# =========================================================

def now_local():
    return datetime.now().astimezone()


def now_text():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def parse_trade_time(value):
    if not value:
        return None

    try:
        dt = datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S"
        )
        return dt.astimezone()
    except Exception:
        return None


def duration_text(opened_at):
    dt = parse_trade_time(opened_at)

    if not dt:
        return "-"

    seconds = max(
        0,
        int((now_local() - dt).total_seconds())
    )

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    if days:
        return f"{days} يوم {hours} ساعة"

    if hours:
        return f"{hours} ساعة {minutes} دقيقة"

    return f"{minutes} دقيقة"


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
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, filename)


def load_state():
    return load_json(STATE_FILE, {})


def save_state(data):
    with state_lock:
        save_json(STATE_FILE, data)


def load_history():
    return load_json(HISTORY_FILE, [])


def save_history(data):
    with history_lock:
        save_json(HISTORY_FILE, data)


# =========================================================
# HISTORY HELPERS
# =========================================================

def trade_datetime(trade):
    value = (
        trade.get("closed_at")
        or trade.get("time")
        or trade.get("opened_at")
    )

    return parse_trade_time(value)


def trade_profit(trade):
    try:
        return float(
            trade.get(
                "profit_usdt",
                trade.get("pnl_usdt", 0)
            )
        )
    except Exception:
        return 0.0


def calculate_stats(history):
    now = now_local()

    today_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    week_start = today_start - timedelta(
        days=today_start.weekday()
    )

    month_start = today_start.replace(
        day=1
    )

    periods = {
        "today": today_start,
        "week": week_start,
        "month": month_start
    }

    result = {
        "today_profit": 0.0,
        "week_profit": 0.0,
        "month_profit": 0.0,
        "total_profit": 0.0,

        "today_trades": 0,
        "week_trades": 0,
        "month_trades": 0,
        "total_trades": 0,

        "today_wins": 0,
        "today_losses": 0,
        "week_wins": 0,
        "week_losses": 0,
        "month_wins": 0,
        "month_losses": 0,
        "total_wins": 0,
        "total_losses": 0
    }

    for trade in history:

        profit = trade_profit(trade)
        dt = trade_datetime(trade)

        result["total_profit"] += profit
        result["total_trades"] += 1

        if profit > 0:
            result["total_wins"] += 1

        elif profit < 0:
            result["total_losses"] += 1

        if not dt:
            continue

        for name, start in periods.items():

            if dt >= start:

                result[f"{name}_profit"] += profit
                result[f"{name}_trades"] += 1

                if profit > 0:
                    result[f"{name}_wins"] += 1

                elif profit < 0:
                    result[f"{name}_losses"] += 1

    if result["total_trades"] > 0:
        result["win_rate"] = (
            result["total_wins"]
            / result["total_trades"]
            * 100
        )
    else:
        result["win_rate"] = 0

    if result["today_trades"] > 0:
        result["today_win_rate"] = (
            result["today_wins"]
            / result["today_trades"]
            * 100
        )
    else:
        result["today_win_rate"] = 0

    if result["week_trades"] > 0:
        result["week_win_rate"] = (
            result["week_wins"]
            / result["week_trades"]
            * 100
        )
    else:
        result["week_win_rate"] = 0

    if result["month_trades"] > 0:
        result["month_win_rate"] = (
            result["month_wins"]
            / result["month_trades"]
            * 100
        )
    else:
        result["month_win_rate"] = 0

    return result


# =========================================================
# BINANCE SIGNED REQUEST
# =========================================================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception(
            "BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة"
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

                wait = min(
                    30,
                    2 ** attempt + 1
                )

                log(
                    f"⚠️ Binance Rate Limit "
                    f"{r.status_code} | "
                    f"انتظار {wait} ثانية"
                )

                time.sleep(wait)
                continue

            r.raise_for_status()

            return r.json()

        except Exception:

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

    for b in account.get(
        "balances",
        []
    ):

        if b["asset"] == "USDT":
            return float(b["free"])

    return 0.0


def get_asset_balance(asset):

    account = get_account()

    for b in account.get(
        "balances",
        []
    ):

        if b["asset"] == asset:

            return (
                float(b["free"])
                + float(b["locked"])
            )

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

            log(
                "📥 تحميل معلومات Binance..."
            )

            _exchange_info = public_get(
                "/api/v3/exchangeInfo"
            )

    return _exchange_info


def get_symbol_info(symbol):

    info = get_exchange_info()

    for s in info.get(
        "symbols",
        []
    ):

        if s["symbol"] == symbol:
            return s

    return None


def get_filters(symbol):

    info = get_symbol_info(symbol)

    if not info:
        raise Exception(
            f"العملة غير موجودة: {symbol}"
        )

    result = {
        "stepSize": 0.0,
        "minQty": 0.0,
        "minNotional": 0.0,
        "tickSize": 0.0
    }

    for f in info.get(
        "filters",
        []
    ):

        if f["filterType"] == "LOT_SIZE":

            result["stepSize"] = float(
                f["stepSize"]
            )

            result["minQty"] = float(
                f["minQty"]
            )

        elif f["filterType"] == "MIN_NOTIONAL":

            result["minNotional"] = float(
                f.get(
                    "minNotional",
                    0
                )
            )

        elif f["filterType"] == "NOTIONAL":

            result["minNotional"] = float(
                f.get(
                    "minNotional",
                    0
                )
            )

        elif f["filterType"] == "PRICE_FILTER":

            result["tickSize"] = float(
                f["tickSize"]
            )

    return result


def floor_step(value, step):

    if step <= 0:
        return value

    d_value = Decimal(
        str(value)
    )

    d_step = Decimal(
        str(step)
    )

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

    return float(
        data["price"]
    )


# =========================================================
# MARKET BUY
# =========================================================

def market_buy(
    symbol,
    usdt_amount
):

    try:

        log(
            f"🛒 محاولة شراء {symbol} "
            f"بـ {usdt_amount:.4f} USDT"
        )

        filters = get_filters(
            symbol
        )

        if filters["minNotional"] > 0:

            if usdt_amount < filters[
                "minNotional"
            ]:

                raise Exception(
                    "المبلغ أقل من "
                    f"MIN_NOTIONAL "
                    f"({filters['minNotional']} USDT)"
                )

        params = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": (
                f"{usdt_amount:.8f}"
            ),
            "newOrderRespType": "FULL"
        }

        result = signed_request(
            "POST",
            "/api/v3/order",
            params
        )

        executed_qty = float(
            result.get(
                "executedQty",
                0
            )
        )

        cumm_quote = float(
            result.get(
                "cummulativeQuoteQty",
                0
            )
        )

        if executed_qty <= 0:
            raise Exception(
                f"Binance لم تنفذ كمية | "
                f"{result}"
            )

        if cumm_quote <= 0:
            raise Exception(
                f"قيمة الشراء غير معروفة | "
                f"{result}"
            )

        avg_price = (
            cumm_quote
            / executed_qty
        )

        log(
            f"✅ تم الشراء {symbol} | "
            f"الكمية: {executed_qty} | "
            f"متوسط: {avg_price}"
        )

        return {
            "symbol": symbol,
            "qty": executed_qty,
            "entry": avg_price,
            "orderId": result.get(
                "orderId"
            ),
            "quote": cumm_quote
        }

    except Exception as e:

        log(
            "❌ فشل شراء Binance"
        )

        log(
            f"❌ السبب الحقيقي: {e}"
        )

        return None


# =========================================================
# STOP LOSS
# =========================================================

def place_stop(
    symbol,
    quantity,
    stop_price
):

    try:

        filters = get_filters(
            symbol
        )

        quantity = floor_step(
            quantity,
            filters["stepSize"]
        )

        if quantity <= 0:

            raise Exception(
                "الكمية بعد التقريب أصبحت 0"
            )

        stop_price = floor_step(
            stop_price,
            filters["tickSize"]
        )

        if stop_price <= 0:

            raise Exception(
                f"سعر الوقف غير صحيح: "
                f"{stop_price}"
            )

        params = {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": (
                f"{quantity:.8f}"
            ),
            "stopPrice": (
                f"{stop_price:.8f}"
            ),
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

        log(
            f"❌ فشل وضع وقف Binance: {e}"
        )

        return None


# =========================================================
# CANCEL ORDER
# =========================================================

def cancel_order(
    symbol,
    order_id
):

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

def get_order(
    symbol,
    order_id
):

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

        log(
            f"⚠️ فشل فحص الأمر: {e}"
        )

        return None


# =========================================================
# OPEN POSITION
# =========================================================

def position_exists(symbol):

    if not symbol:
        return False

    asset = symbol.replace(
        "USDT",
        ""
    )

    try:

        qty = get_asset_balance(
            asset
        )

        filters = get_filters(
            symbol
        )

        return qty >= filters[
            "minQty"
        ]

    except Exception as e:

        log(
            f"⚠️ فشل فحص الصفقة: {e}"
        )

        return False


# =========================================================
# INITIAL STOP
# =========================================================

def ensure_initial_stop(state):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    qty = float(
        state["qty"]
    )

    if state.get(
        "stop_order_id"
    ):
        return state

    stop_price = (
        entry
        * (1 + INITIAL_STOP)
    )

    result = place_stop(
        symbol,
        qty,
        stop_price
    )

    if result:

        state["stop_order_id"] = (
            result.get("orderId")
        )

        state["stop_price"] = (
            stop_price
        )

        state["locked_profit"] = (
            INITIAL_STOP
        )

        save_state(state)

    return state


# =========================================================
# RAISE STOP
# =========================================================

def raise_stop(
    state,
    current_profit
):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    qty = float(
        state["qty"]
    )

    level = int(
        current_profit
        / PROFIT_STEP
    )

    if level < 1:
        return state

    lock_profit = (
        level
        * PROFIT_STEP
    )

    old_lock = float(
        state.get(
            "locked_profit",
            INITIAL_STOP
        )
    )

    if lock_profit <= old_lock:
        return state

    new_stop = (
        entry
        * (1 + lock_profit)
    )

    old_order_id = state.get(
        "stop_order_id"
    )

    if old_order_id:

        old_status = get_order(
            symbol,
            old_order_id
        )

        if old_status:

            status = old_status.get(
                "status"
            )

            if status == "NEW":

                cancel_order(
                    symbol,
                    old_order_id
                )

    result = place_stop(
        symbol,
        qty,
        new_stop
    )

    if result:

        state["stop_order_id"] = (
            result.get("orderId")
        )

        state["stop_price"] = (
            new_stop
        )

        state["locked_profit"] = (
            lock_profit
        )

        save_state(state)

        log(
            f"🔒 تأمين ربح "
            f"{lock_profit * 100:.0f}% | "
            f"الوقف الجديد: {new_stop}"
        )

    return state


# =========================================================
# CLOSE HISTORY
# =========================================================

def record_closed_trade(
    state,
    exit_price,
    reason="STOP"
):

    entry = float(
        state.get("entry", 0)
    )

    qty = float(
        state.get("qty", 0)
    )

    if entry <= 0:
        return

    gross = (
        (exit_price - entry)
        * qty
    )

    entry_value = (
        entry * qty
    )

    exit_value = (
        exit_price * qty
    )

    fees = (
        (entry_value + exit_value)
        * FEE_RATE
    )

    net_profit = (
        gross - fees
    )

    profit_percent = (
        (net_profit / entry_value)
        * 100
        if entry_value > 0
        else 0
    )

    trade = {
        "symbol": state.get(
            "symbol"
        ),
        "entry": entry,
        "exit": exit_price,
        "qty": qty,
        "profit_percent": profit_percent,
        "profit_usdt": net_profit,
        "gross_profit_usdt": gross,
        "fees_usdt": fees,
        "reason": reason,
        "opened_at": state.get(
            "opened_at"
        ),
        "closed_at": now_text(),
        "time": now_text()
    }

    history = load_history()

    history.append(trade)

    save_history(
        history[-500:]
    )

    log(
        f"🧾 حفظ الصفقة | "
        f"{trade['symbol']} | "
        f"{profit_percent:.2f}% | "
        f"{net_profit:.4f} USDT"
    )


# =========================================================
# MANAGE POSITION
# =========================================================

def manage_position(state):

    symbol = state["symbol"]

    log(
        f"📌 متابعة الصفقة: {symbol}"
    )

    state = ensure_initial_stop(
        state
    )

    save_state(state)

    while True:

        try:

            if not position_exists(
                symbol
            ):

                current = get_price(
                    symbol
                )

                record_closed_trade(
                    state,
                    current,
                    "CLOSED"
                )

                save_state({})

                log(
                    f"🏁 انتهت الصفقة "
                    f"{symbol}"
                )

                return

            current = get_price(
                symbol
            )

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

            state["current_price"] = (
                current
            )

            state["profit_percent"] = (
                profit * 100
            )

            state["profit_usdt"] = (
                profit_usdt
            )

            state["status"] = (
                "رابحة"
                if profit > 0
                else "خاسرة"
                if profit < 0
                else "متعادل"
            )

            state["status_en"] = (
                "PROFIT"
                if profit > 0
                else "LOSS"
                if profit < 0
                else "EVEN"
            )

            state["duration"] = (
                duration_text(
                    state.get(
                        "opened_at"
                    )
                )
            )

            save_state(state)

            log(
                f"📊 {symbol} | "
                f"السعر {current:.8f} | "
                f"الربح "
                f"{profit * 100:.2f}% | "
                f"{profit_usdt:.4f} USDT"
            )

            if profit >= PROFIT_STEP:

                state = raise_stop(
                    state,
                    profit
                )

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

                    if status == "FILLED":

                        log(
                            f"🛑 تم تنفيذ وقف Binance "
                            f"{symbol}"
                        )

                        time.sleep(2)

                        exit_price = current

                        try:
                            qty_sold = float(
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

                            if (
                                qty_sold > 0
                                and quote > 0
                            ):
                                exit_price = (
                                    quote
                                    / qty_sold
                                )

                        except Exception:
                            pass

                        record_closed_trade(
                            state,
                            exit_price,
                            "STOP"
                        )

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

    symbol = state.get(
        "symbol"
    )

    if not symbol:

        save_state({})

        return False

    try:

        if position_exists(
            symbol
        ):

            log(
                f"🔄 وجدت صفقة مفتوحة "
                f"{symbol} — استئناف المتابعة"
            )

            manage_position(
                state
            )

            return True

        else:

            log(
                f"⚠️ الصفقة المحفوظة "
                f"{symbol} غير موجودة الآن"
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

    for s in info.get(
        "symbols",
        []
    ):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get(
            "isSpotTradingAllowed"
        ) is False:
            continue

        symbol = s["symbol"]

        if symbol.endswith("USDT"):
            symbols.append(symbol)

    return symbols


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval,
    limit=210
):

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
        sum(values[:period])
        / period
    )

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

    global LAST_SIGNAL

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

        avg_volume = (
            sum(
                volumes15[-21:-1]
            )
            / 20
        )

        current_volume = (
            volumes15[-1]
        )

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

        if price <= ema200_15:
            return False

        if price <= resistance:
            return False

        if volume_ratio < 1.5:
            return False

        if move < 0.005 or move > 0.04:
            return False

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

        LAST_SIGNAL = {
            "symbol": symbol,
            "time": now_text(),
            "price": price,
            "volume_ratio": volume_ratio,
            "breakout_percent": (
                breakout * 100
            ),
            "move_percent": (
                move * 100
            )
        }

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

        amount = (
            balance
            * TRADE_USDT_PERCENT
        )

        if amount < MIN_USDT:

            log(
                f"⚠️ الرصيد غير كافي: "
                f"{balance:.4f} USDT"
            )

            return False

        result = market_buy(
            symbol,
            amount
        )

        if not result:

            log(
                "❌ لم تفتح الصفقة"
            )

            return False

        state = {
            "symbol": symbol,
            "entry": result["entry"],
            "current_price": result["entry"],
            "qty": result["qty"],
            "order_id": result["orderId"],

            "opened_at": now_text(),

            "profit_percent": 0,
            "profit_usdt": 0,

            "status": "متعادل",
            "status_en": "EVEN",

            "duration": "0 دقيقة",

            "locked_profit": INITIAL_STOP,

            "stop_price": (
                result["entry"]
                * (1 + INITIAL_STOP)
            ),

            "stop_order_id": None
        }

        save_state(state)

        state = ensure_initial_stop(
            state
        )

        manage_position(
            state
        )

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

    global LAST_SCAN_AT
    global LAST_SCAN_COUNT
    global LAST_ERROR

    time.sleep(3)

    log("================================")
    log("🤖 مضارب أبو سعود V2 PRO")
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

            LAST_ERROR = None

            if restore_trade():
                continue

            balance = get_usdt_balance()

            log(
                f"💰 رصيد USDT: "
                f"{balance:.4f}"
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

            LAST_SCAN_COUNT = len(
                symbols
            )

            LAST_SCAN_AT = time.time()

            log(
                f"🔎 فحص {len(symbols)} عملة..."
            )

            for symbol in symbols:

                current_state = (
                    load_state()
                )

                if current_state.get(
                    "symbol"
                ):
                    break

                try:

                    if scan_symbol(
                        symbol
                    ):

                        log(
                            f"🔥 إشارة شراء: "
                            f"{symbol}"
                        )

                        if open_trade(
                            symbol
                        ):
                            break

                        log(
                            "❌ نكمل البحث "
                            "بعد فشل الشراء"
                        )

                except Exception as e:

                    log(
                        f"⚠️ {symbol}: {e}"
                    )

                time.sleep(
                    0.08
                )

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            LAST_ERROR = str(e)

            log(
                f"❌ خطأ رئيسي: {e}"
            )

            time.sleep(10)


# =========================================================
# DASHBOARD
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود V2 PRO</title>

<style>

* {
    box-sizing:border-box;
}

body {
    margin:0;
    background:#080c12;
    color:#fff;
    font-family:Arial,sans-serif;
}

.container {
    max-width:1200px;
    margin:auto;
    padding:15px;
}

.header {
    background:linear-gradient(
        135deg,
        #111a25,
        #0c121b
    );

    border:1px solid #263241;
    border-radius:20px;
    padding:22px;
    margin-bottom:15px;
}

h1 {
    margin:0 0 8px;
}

.subtitle {
    color:#94a3b8;
}

.status {
    display:inline-block;
    margin-top:12px;
    padding:8px 13px;
    border-radius:20px;
    background:#10251b;
    color:#38d27b;
    font-weight:bold;
}

.grid {
    display:grid;
    grid-template-columns:
        repeat(auto-fit,minmax(180px,1fr));
    gap:12px;
}

.card {
    background:#101722;
    border:1px solid #263241;
    border-radius:18px;
    padding:18px;
    margin-bottom:15px;
}

.box {
    background:#0b1119;
    border-radius:15px;
    padding:16px;
    border:1px solid #202b38;
}

.label {
    color:#8e9bab;
    font-size:13px;
}

.value {
    font-size:23px;
    font-weight:bold;
    margin-top:7px;
    word-break:break-word;
}

.green {
    color:#35d07f;
}

.red {
    color:#ff5c67;
}

.yellow {
    color:#ffc857;
}

.blue {
    color:#61a8ff;
}

.big {
    font-size:30px;
}

.section-title {
    margin:0 0 15px;
}

.info {
    color:#aab5c3;
    font-size:13px;
    line-height:1.8;
}

.badge {
    display:inline-block;
    padding:8px 14px;
    border-radius:12px;
    font-weight:bold;
}

.profit {
    background:#0d2a1b;
    color:#35d07f;
}

.loss {
    background:#2b1115;
    color:#ff5c67;
}

.even {
    background:#29220e;
    color:#ffc857;
}

table {
    width:100%;
    border-collapse:collapse;
}

td {
    padding:10px 5px;
    border-bottom:1px solid #202b38;
}

td:first-child {
    color:#8e9bab;
}

.loading {
    color:#8e9bab;
}

</style>

</head>

<body>

<div class="container">

<div class="header">

<h1>🤖 مضارب أبو سعود V2 PRO</h1>

<div class="subtitle">
Binance Spot • مراقبة تلقائية للصفقات
</div>

<div id="status"
class="status">
جاري الاتصال...
</div>

</div>


<!-- الأرباح -->

<div class="card">

<h2 class="section-title">
💰 الأرباح
</h2>

<div class="grid">

<div class="box">
<div class="label">ربح اليوم</div>
<div id="today"
class="value big">
...
</div>
</div>

<div class="box">
<div class="label">ربح الأسبوع</div>
<div id="week"
class="value big">
...
</div>
</div>

<div class="box">
<div class="label">ربح الشهر</div>
<div id="month"
class="value big">
...
</div>
</div>

<div class="box">
<div class="label">إجمالي الأرباح</div>
<div id="total"
class="value big">
...
</div>
</div>

</div>

</div>


<!-- إحصائيات -->

<div class="card">

<h2 class="section-title">
📊 إحصائيات الصفقات
</h2>

<div class="grid">

<div class="box">
<div class="label">صفقات اليوم</div>
<div id="todayTrades"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">صفقات الأسبوع</div>
<div id="weekTrades"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">صفقات الشهر</div>
<div id="monthTrades"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">إجمالي الصفقات</div>
<div id="totalTrades"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">الرابحة</div>
<div id="wins"
class="value green">
...
</div>
</div>

<div class="box">
<div class="label">الخاسرة</div>
<div id="losses"
class="value red">
...
</div>
</div>

<div class="box">
<div class="label">نسبة النجاح</div>
<div id="winRate"
class="value">
...
</div>
</div>

</div>

</div>


<!-- الصفقة -->

<div class="card">

<h2 class="section-title">
🔥 الصفقة المفتوحة
</h2>

<div id="trade">
<div class="loading">
جاري التحميل...
</div>
</div>

</div>


<!-- معلومات البوت -->

<div class="card">

<h2 class="section-title">
🤖 معلومات البوت
</h2>

<div class="grid">

<div class="box">
<div class="label">رصيد USDT</div>
<div id="balance"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">Binance</div>
<div id="binance"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">الفريم</div>
<div class="value">
15m + 1h
</div>
</div>

<div class="box">
<div class="label">العملات المفحوصة</div>
<div id="scanCount"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">آخر فحص</div>
<div id="lastScan"
class="value">
...
</div>
</div>

<div class="box">
<div class="label">وقف البداية</div>
<div class="value red">
-2%
</div>
</div>

<div class="box">
<div class="label">تأمين الربح</div>
<div class="value green">
كل +1%
</div>
</div>

<div class="box">
<div class="label">مبلغ الصفقة</div>
<div class="value">
99.9% من USDT
</div>
</div>

</div>

</div>


<!-- آخر إشارة -->

<div class="card">

<h2 class="section-title">
👀 آخر إشارة
</h2>

<div id="signal"
class="info">
لا توجد إشارة حتى الآن
</div>

</div>

</div>


<script>

function money(v) {

    const n = Number(v || 0);

    return n.toFixed(4) + " USDT";

}


function percent(v) {

    return Number(v || 0).toFixed(2) + "%";

}


function profitClass(v) {

    if (Number(v) > 0)
        return "green";

    if (Number(v) < 0)
        return "red";

    return "yellow";

}


function renderTrade(t) {

    const box =
        document.getElementById("trade");

    if (!t || !t.symbol) {

        box.innerHTML = `
        <div class="box">
            <div class="label">
                الحالة
            </div>

            <div class="value yellow">
                لا توجد صفقة مفتوحة
            </div>

            <div class="info">
                البوت حالياً يبحث عن فرصة دخول.
            </div>
        </div>
        `;

        return;
    }


    const p =
        Number(t.profit_percent || 0);


    let badgeClass = "even";

    if (p > 0)
        badgeClass = "profit";

    if (p < 0)
        badgeClass = "loss";


    const status =
        p > 0
        ? "🟢 الصفقة رابحة"
        : p < 0
        ? "🔴 الصفقة خاسرة"
        : "🟡 متعادلة";


    box.innerHTML = `

    <div class="box"
    style="margin-bottom:12px">

        <div class="label">
            حالة الصفقة
        </div>

        <div class="value">
            <span class="badge ${badgeClass}">
                ${status}
            </span>
        </div>

    </div>


    <div class="grid">

        <div class="box">
            <div class="label">
                العملة
            </div>
            <div class="value blue">
                ${t.symbol}
            </div>
        </div>


        <div class="box">
            <div class="label">
                سعر الدخول
            </div>
            <div class="value">
                ${Number(t.entry).toFixed(8)}
            </div>
        </div>


        <div class="box">
            <div class="label">
                السعر الحالي
            </div>
            <div class="value">
                ${Number(t.current_price).toFixed(8)}
            </div>
        </div>


        <div class="box">
            <div class="label">
                الربح / الخسارة
            </div>
            <div class="value ${profitClass(p)}">
                ${percent(p)}
            </div>
        </div>


        <div class="box">
            <div class="label">
                الربح / الخسارة USDT
            </div>
            <div class="value ${profitClass(t.profit_usdt)}">
                ${money(t.profit_usdt)}
            </div>
        </div>


        <div class="box">
            <div class="label">
                الكمية
            </div>
            <div class="value">
                ${Number(t.qty).toFixed(8)}
            </div>
        </div>


        <div class="box">
            <div class="label">
                وقف Binance
            </div>
            <div class="value red">
                ${t.stop_price
                    ? Number(t.stop_price).toFixed(8)
                    : "-"}
            </div>
        </div>


        <div class="box">
            <div class="label">
                الربح المؤمّن
            </div>
            <div class="value green">
                ${percent(
                    Number(t.locked_profit || -0.02)
                    * 100
                )}
            </div>
        </div>


        <div class="box">
            <div class="label">
                وقت الدخول
            </div>
            <div class="value">
                ${t.opened_at || "-"}
            </div>
        </div>


        <div class="box">
            <div class="label">
                مدة الصفقة
            </div>
            <div class="value">
                ${t.duration || "-"}
            </div>
        </div>


        <div class="box">
            <div class="label">
                Order ID
            </div>
            <div class="value">
                ${t.order_id || "-"}
            </div>
        </div>

    </div>
    `;
}


async function update() {

    try {

        const r =
            await fetch(
                "/api/dashboard"
            );

        const d =
            await r.json();


        document.getElementById(
            "status"
        ).innerText =
            d.online
            ? "🟢 البوت ONLINE"
            : "🔴 البوت OFFLINE";


        document.getElementById(
            "balance"
        ).innerText =
            money(d.balance);


        document.getElementById(
            "binance"
        ).innerText =
            d.binance_connected
            ? "🟢 متصل"
            : "🔴 غير متصل";


        const s =
            d.stats;


        document.getElementById(
            "today"
        ).innerText =
            money(s.today_profit);


        document.getElementById(
            "week"
        ).innerText =
            money(s.week_profit);


        document.getElementById(
            "month"
        ).innerText =
            money(s.month_profit);


        document.getElementById(
            "total"
        ).innerText =
            money(s.total_profit);


        document.getElementById(
            "todayTrades"
        ).innerText =
            s.today_trades;


        document.getElementById(
            "weekTrades"
        ).innerText =
            s.week_trades;


        document.getElementById(
            "monthTrades"
        ).innerText =
            s.month_trades;


        document.getElementById(
            "totalTrades"
        ).innerText =
            s.total_trades;


        document.getElementById(
            "wins"
        ).innerText =
            s.total_wins;


        document.getElementById(
            "losses"
        ).innerText =
            s.total_losses;


        document.getElementById(
            "winRate"
        ).innerText =
            Number(
                s.win_rate
            ).toFixed(1) + "%";


        renderTrade(
            d.trade
        );


        document.getElementById(
            "scanCount"
        ).innerText =
            d.bot.scan_count || 0;


        document.getElementById(
            "lastScan"
        ).innerText =
            d.bot.last_scan || "-";


        const signal =
            d.bot.last_signal;


        if (signal) {

            document.getElementById(
                "signal"
            ).innerHTML = `

            <div class="grid">

                <div class="box">
                    العملة
                    <div class="value blue">
                        ${signal.symbol}
                    </div>
                </div>

                <div class="box">
                    السعر
                    <div class="value">
                        ${Number(
                            signal.price
                        ).toFixed(8)}
                    </div>
                </div>

                <div class="box">
                    حجم التداول
                    <div class="value">
                        ${Number(
                            signal.volume_ratio
                        ).toFixed(2)}x
                    </div>
                </div>

                <div class="box">
                    الاختراق
                    <div class="value green">
                        ${Number(
                            signal.breakout_percent
                        ).toFixed(2)}%
                    </div>
                </div>

                <div class="box">
                    الحركة
                    <div class="value">
                        ${Number(
                            signal.move_percent
                        ).toFixed(2)}%
                    </div>
                </div>

            </div>

            <br>
            آخر إشارة:
            ${signal.time}
            `;

        }

    }

    catch(e) {

        document.getElementById(
            "status"
        ).innerText =
            "🔴 خطأ اتصال";

    }

}


setInterval(
    update,
    5000
);

window.onload =
    update;

</script>

</body>

</html>
"""


# =========================================================
# DASHBOARD API
# =========================================================

@app.route("/")
def home():
    return HTML


@app.route("/api/dashboard")
def dashboard():

    state = load_state()
    history = load_history()

    try:

        balance = get_usdt_balance()

        connected = True

    except Exception:

        balance = 0
        connected = False


    if state:

        if state.get(
            "opened_at"
        ):

            state["duration"] = (
                duration_text(
                    state["opened_at"]
                )
            )


    stats = calculate_stats(
        history
    )


    bot_info = {

        "running": True,

        "started_at": time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(
                BOT_STARTED_AT
            )
        ),

        "scan_count": LAST_SCAN_COUNT,

        "last_scan": (
            time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(
                    LAST_SCAN_AT
                )
            )
            if LAST_SCAN_AT
            else "-"
        ),

        "last_signal": LAST_SIGNAL,

        "last_error": LAST_ERROR,

        "scan_interval": SCAN_INTERVAL,

        "position_check_seconds":
            POSITION_CHECK_SECONDS
    }


    return jsonify({

        "online": True,

        "binance_connected":
            connected,

        "balance":
            balance,

        "trade":
            state if state else None,

        "stats":
            stats,

        "bot":
            bot_info,

        "server_time":
            now_text()
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({

        "status": "ok",

        "bot":
            "Mudarib Abo Saud V2 PRO",

        "time":
            now_text()
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
# RUN
# =========================================================

if __name__ == "__main__":

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
