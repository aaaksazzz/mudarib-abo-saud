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
# Binance Spot + Restart Recovery + OCO Protection
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

SCAN_SLEEP = 10
REQUEST_TIMEOUT = 15

app = Flask(__name__)

# ============================================================
# GLOBAL STATE
# ============================================================

state_lock = threading.Lock()

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
}

exchange_info = {}
symbols_info = {}


# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(msg, flush=True)


def now_ms():
    return int(time.time() * 1000)


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
                "status": state["status"],
            }

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        log(f"⚠️ حفظ البيانات: {e}")


def load_state():
    global state

    try:
        if not os.path.exists(DATA_FILE):
            log("ℹ️ لا يوجد ملف بيانات سابق")
            return

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)

        with state_lock:
            state["active_trade"] = old.get("active_trade")
            state["trades"] = old.get("trades", [])
            state["wins"] = old.get("wins", 0)
            state["losses"] = old.get("losses", 0)
            state["total_profit"] = old.get("total_profit", 0.0)
            state["last_scan"] = old.get("last_scan", "")

        log("💾 تم تحميل بيانات البوت")

    except Exception as e:
        log(f"⚠️ تعذر تحميل البيانات: {e}")


# ============================================================
# BINANCE SIGNED REQUEST
# ============================================================

def sign_params(params):
    query = urllib.parse.urlencode(params, doseq=True)
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return query + "&signature=" + signature


def public_get(path, params=None):
    r = requests.get(
        BASE + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    return r.json()


def signed_request(method, path, params=None):
    params = params.copy() if params else {}

    params["timestamp"] = now_ms()
    params["recvWindow"] = 5000

    query = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE + path + "?" + query

    if method == "GET":
        r = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    elif method == "POST":
        r = requests.post(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    elif method == "DELETE":
        r = requests.delete(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    else:
        raise Exception("HTTP method غير مدعوم")

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise Exception(
            f"Binance {r.status_code}: {data}"
        )

    return data


# ============================================================
# BINANCE INFO
# ============================================================

def load_exchange_info():
    global exchange_info, symbols_info

    log("📥 تحميل معلومات Binance...")

    exchange_info = public_get("/api/v3/exchangeInfo")

    symbols_info = {}

    for s in exchange_info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue

        symbol = s["symbol"]

        if not symbol.endswith("USDT"):
            continue

        filters = {}

        for f in s.get("filters", []):
            filters[f["filterType"]] = f

        symbols_info[symbol] = {
            "base": s["baseAsset"],
            "quote": s["quoteAsset"],
            "filters": filters
        }

    state["symbols_count"] = len(symbols_info)

    log(f"✅ تم تحميل {len(symbols_info)} عملة")


def decimals_from_step(step):
    d = Decimal(str(step))

    if d == 0:
        return 8

    return max(0, -d.as_tuple().exponent)


def floor_step(value, step):
    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        return value

    result = (value / step).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return result


def format_decimal(value, step):
    d = floor_step(value, step)
    places = decimals_from_step(step)

    return f"{d:.{places}f}"


def get_symbol_filters(symbol):
    info = symbols_info.get(symbol)

    if not info:
        raise Exception(f"لا توجد معلومات {symbol}")

    filters = info["filters"]

    lot = filters.get("LOT_SIZE")
    price_filter = filters.get("PRICE_FILTER")
    min_notional = filters.get("MIN_NOTIONAL")

    return lot, price_filter, min_notional


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

    balances = {}

    for b in account.get("balances", []):
        free = float(b["free"])
        locked = float(b["locked"])

        total = free + locked

        if total > 0:
            balances[b["asset"]] = {
                "free": free,
                "locked": locked,
                "total": total
            }

    return balances


def get_balance(asset):
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
# ORDERS
# ============================================================

def market_buy(symbol, usdt_amount):
    log(f"🟢 شراء MARKET: {symbol} | {usdt_amount} USDT")

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": f"{usdt_amount:.2f}",
        "newOrderRespType": "FULL"
    }

    return signed_request(
        "POST",
        "/api/v3/order",
        params
    )


def market_sell(symbol, quantity):
    lot, _, _ = get_symbol_filters(symbol)

    step = lot["stepSize"]

    qty = floor_step(
        Decimal(str(quantity)),
        Decimal(str(step))
    )

    if qty <= 0:
        raise Exception("الكمية بعد التقريب = 0")

    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": format_decimal(qty, step),
        "newOrderRespType": "FULL"
    }

    log(
        f"🔴 بيع MARKET: {symbol} | "
        f"qty={format_decimal(qty, step)}"
    )

    return signed_request(
        "POST",
        "/api/v3/order",
        params
    )


# ============================================================
# OCO
# ============================================================

def place_oco(symbol, quantity, tp_price, sl_price):
    """
    حماية الصفقة:
    TP = +2%
    SL = -2%

    نستخدم OCO:
    LIMIT_MAKER للبيع عند TP
    STOP_LOSS_LIMIT للبيع عند SL
    """

    lot, price_filter, _ = get_symbol_filters(symbol)

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

    # سعر تنفيذ الستوب أقل بقليل من stopPrice
    stop_limit = floor_step(
        sl * Decimal("0.999"),
        Decimal(str(tick))
    )

    if qty <= 0:
        raise Exception("OCO quantity = 0")

    if tp <= 0 or sl <= 0:
        raise Exception("سعر TP/SL غير صحيح")

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": format_decimal(qty, step),

        "aboveType": "LIMIT_MAKER",
        "abovePrice": format_decimal(tp, tick),

        "belowType": "STOP_LOSS_LIMIT",
        "belowStopPrice": format_decimal(sl, tick),
        "belowPrice": format_decimal(stop_limit, tick),
        "belowTimeInForce": "GTC",

        "newOrderRespType": "RESULT"
    }

    log(
        f"🛡️ إنشاء حماية OCO | "
        f"{symbol} | TP={format_decimal(tp, tick)} "
        f"| SL={format_decimal(sl, tick)}"
    )

    return signed_request(
        "POST",
        "/api/v3/orderList/oco",
        params
    )


def get_open_order_lists():
    try:
        return signed_request(
            "GET",
            "/api/v3/openOrderList"
        )
    except Exception as e:
        log(f"⚠️ فحص OCO: {e}")
        return []


def get_open_orders(symbol=None):
    params = {}

    if symbol:
        params["symbol"] = symbol

    return signed_request(
        "GET",
        "/api/v3/openOrders",
        params
    )


def get_order(symbol, order_id):
    return signed_request(
        "GET",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


def get_order_list(order_list_id):
    return signed_request(
        "GET",
        "/api/v3/orderList",
        {
            "orderListId": order_list_id
        }
    )


# ============================================================
# TRADE HISTORY
# ============================================================

def get_my_trades(symbol, limit=50):
    return signed_request(
        "GET",
        "/api/v3/myTrades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )


def calculate_buy_from_trades(trades):
    buys = [
        t for t in trades
        if t.get("isBuyer") is True
    ]

    if not buys:
        return None

    buys = sorted(
        buys,
        key=lambda x: int(x.get("time", 0)),
        reverse=True
    )

    # نأخذ آخر عمليات الشراء القريبة
    latest_time = int(buys[0]["time"])

    recent = [
        t for t in buys
        if latest_time - int(t["time"]) <= 6 * 60 * 60 * 1000
    ]

    if not recent:
        recent = [buys[0]]

    total_qty = 0.0
    total_quote = 0.0

    for t in recent:
        qty = float(t.get("qty", 0))
        quote = float(t.get("quoteQty", 0))

        total_qty += qty
        total_quote += quote

    if total_qty <= 0:
        return None

    avg_price = total_quote / total_qty

    return {
        "quantity": total_qty,
        "entry_price": avg_price,
        "time": latest_time
    }


# ============================================================
# RECOVERY
# ============================================================

def restore_from_saved_state():
    trade = state.get("active_trade")

    if not trade:
        return False

    symbol = trade.get("symbol")

    if not symbol:
        return False

    try:
        balance = get_balance(
            symbols_info[symbol]["base"]
        )

        if balance["total"] <= 0:
            log(
                f"ℹ️ الصفقة المحفوظة انتهت: {symbol}"
            )

            state["active_trade"] = None
            save_state()

            return False

        log(
            f"♻️ استعادة الصفقة من البيانات: "
            f"{symbol}"
        )

        return True

    except Exception as e:
        log(f"⚠️ استعادة البيانات: {e}")
        return False


def restore_from_open_oco():
    """
    إذا Render طفى والـ OCO لا يزال موجودًا في Binance،
    نستعيد الصفقة مباشرة.
    """

    try:
        lists = get_open_order_lists()

        if not lists:
            return False

        for item in lists:

            symbol = item.get("symbol")

            if not symbol or symbol not in symbols_info:
                continue

            if item.get("listOrderStatus") != "EXECUTING":
                continue

            base = symbols_info[symbol]["base"]

            balance = get_balance(base)

            if balance["total"] <= 0:
                continue

            orders = item.get("orders", [])

            if not orders:
                continue

            log(
                f"♻️ تم العثور على صفقة OCO مفتوحة: "
                f"{symbol}"
            )

            tp = None
            sl = None
            entry = None

            try:
                order_list_id = item.get("orderListId")

                if order_list_id:
                    full = get_order_list(order_list_id)

                    for o in full.get("orders", []):
                        oid = o.get("orderId")

                        if not oid:
                            continue

                        details = get_order(
                            symbol,
                            oid
                        )

                        if details.get("side") != "SELL":
                            continue

                        order_type = details.get("type")

                        if order_type == "LIMIT_MAKER":
                            tp = float(
                                details.get("price", 0)
                            )

                        elif order_type == "STOP_LOSS_LIMIT":
                            sl = float(
                                details.get("stopPrice", 0)
                            )

            except Exception as e:
                log(
                    f"⚠️ قراءة تفاصيل OCO: {e}"
                )

            # نحاول معرفة سعر الدخول من آخر شراء
            try:
                trades = get_my_trades(
                    symbol,
                    50
                )

                info = calculate_buy_from_trades(
                    trades
                )

                if info:
                    entry = info["entry_price"]

            except Exception as e:
                log(
                    f"⚠️ قراءة سجل شراء {symbol}: {e}"
                )

            if not entry:
                if tp:
                    entry = tp / (1 + TP_PERCENT)
                elif sl:
                    entry = sl / (1 - SL_PERCENT)
                else:
                    entry = public_get(
                        "/api/v3/ticker/price",
                        {"symbol": symbol}
                    )

                    entry = float(entry["price"])

            if not tp:
                tp = entry * (1 + TP_PERCENT)

            if not sl:
                sl = entry * (1 - SL_PERCENT)

            state["active_trade"] = {
                "symbol": symbol,
                "quantity": balance["total"],
                "entry_price": entry,
                "tp": tp,
                "sl": sl,
                "recovered": True,
                "recovered_at": now_ms(),
                "oco_order_list_id": item.get(
                    "orderListId"
                )
            }

            save_state()

            log(
                f"✅ استعادة كاملة: {symbol} "
                f"| Entry={entry:.8f} "
                f"| TP={tp:.8f} "
                f"| SL={sl:.8f}"
            )

            return True

        return False

    except Exception as e:
        log(f"⚠️ استعادة OCO: {e}")
        return False


def restore_from_balances():
    """
    إذا الصفقة موجودة في Binance لكن ملف Render اختفى
    أو OCO غير موجود، نحاول اكتشاف آخر شراء.
    """

    try:
        balances = get_balances()

        candidates = []

        for asset, b in balances.items():

            if asset == "USDT":
                continue

            if asset not in [
                info["base"]
                for info in symbols_info.values()
            ]:
                continue

            if b["total"] <= 0:
                continue

            symbol = asset + "USDT"

            if symbol not in symbols_info:
                continue

            candidates.append(
                (symbol, b["total"])
            )

        if not candidates:
            return False

        log(
            f"🔍 فحص {len(candidates)} رصيد "
            f"لاستعادة الصفقة..."
        )

        # نبدأ بالعملات الأكبر
        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        for symbol, balance_qty in candidates:

            try:
                trades = get_my_trades(
                    symbol,
                    50
                )

                info = calculate_buy_from_trades(
                    trades
                )

                if not info:
                    continue

                # نتأكد أن آخر عملية شراء هي الحديثة
                age = now_ms() - info["time"]

                if age > 24 * 60 * 60 * 1000:
                    continue

                entry = info["entry_price"]

                # لا نستعيد رصيد قديم أكبر من صفقة البوت
                invested = info["quantity"] * entry

                if invested < 5:
                    continue

                if invested > TRADE_USDT * 1.5:
                    continue

                tp = entry * (1 + TP_PERCENT)
                sl = entry * (1 - SL_PERCENT)

                log(
                    f"♻️ اكتشاف صفقة متبقية: "
                    f"{symbol}"
                )

                state["active_trade"] = {
                    "symbol": symbol,
                    "quantity": balance_qty,
                    "entry_price": entry,
                    "tp": tp,
                    "sl": sl,
                    "recovered": True,
                    "recovered_at": now_ms()
                }

                save_state()

                # نتأكد هل توجد أوامر حماية
                open_orders = get_open_orders(
                    symbol
                )

                sell_orders = [
                    o for o in open_orders
                    if o.get("side") == "SELL"
                ]

                if sell_orders:
                    log(
                        f"🛡️ حماية موجودة بالفعل: "
                        f"{symbol}"
                    )
                else:
                    log(
                        f"⚠️ لا توجد حماية "
                        f"لـ {symbol} → إنشاء OCO"
                    )

                    place_oco(
                        symbol,
                        balance_qty,
                        tp,
                        sl
                    )

                    log(
                        f"✅ تمت حماية الصفقة: "
                        f"{symbol}"
                    )

                return True

            except Exception as e:
                log(
                    f"⚠️ استعادة {symbol}: {e}"
                )

        return False

    except Exception as e:
        log(f"⚠️ استعادة من الرصيد: {e}")
        return False


def restore_trade():
    log("")
    log("🔄 فحص الصفقات بعد التشغيل...")

    # 1
    if restore_from_saved_state():
        log("✅ تمت استعادة الصفقة المحفوظة")
        return True

    # 2
    if restore_from_open_oco():
        return True

    # 3
    if restore_from_balances():
        return True

    state["active_trade"] = None
    save_state()

    log("ℹ️ لا توجد صفقة مفتوحة")

    return False


# ============================================================
# ACTIVE TRADE MONITOR
# ============================================================

def get_current_price(symbol):
    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


def monitor_trade():
    while True:

        try:
            trade = state.get("active_trade")

            if not trade:
                time.sleep(5)
                continue

            symbol = trade["symbol"]
            base = symbols_info[symbol]["base"]

            price = get_current_price(symbol)

            entry = float(
                trade["entry_price"]
            )

            tp = float(
                trade["tp"]
            )

            sl = float(
                trade["sl"]
            )

            qty = float(
                trade["quantity"]
            )

            pnl_percent = (
                (price - entry)
                / entry
            ) * 100

            log(
                f"📊 {symbol} | "
                f"السعر: {price:.8f} | "
                f"الدخول: {entry:.8f} | "
                f"P/L: {pnl_percent:+.2f}%"
            )

            # =================================================
            # مهم:
            # إذا كان عند Binance OCO مفتوح، لا نبيع يدويًا.
            # Binance هو الذي يحمي الصفقة.
            # =================================================

            open_orders = get_open_orders(symbol)

            sell_orders = [
                o for o in open_orders
                if o.get("side") == "SELL"
            ]

            if sell_orders:
                time.sleep(10)
                continue

            # =================================================
            # لا يوجد OCO
            # نتحقق هل الصفقة ما زالت موجودة
            # =================================================

            balance = get_balance(base)

            if balance["total"] > 0:

                # إذا لا توجد حماية، نحاول إنشاءها
                log(
                    f"🛡️ الصفقة موجودة بدون حماية "
                    f"→ إعادة إنشاء OCO"
                )

                try:
                    place_oco(
                        symbol,
                        balance["total"],
                        tp,
                        sl
                    )

                    trade["quantity"] = balance["total"]

                    save_state()

                    log(
                        f"✅ تمت إعادة الحماية: "
                        f"{symbol}"
                    )

                    time.sleep(10)
                    continue

                except Exception as e:
                    log(
                        f"❌ فشل إنشاء OCO: {e}"
                    )

                    time.sleep(10)
                    continue

            # =================================================
            # لا توجد كمية = الصفقة انتهت
            # =================================================

            log(
                f"🏁 الصفقة انتهت: {symbol}"
            )

            record_finished_trade(
                trade,
                price
            )

            state["active_trade"] = None
            save_state()

        except Exception as e:
            log(
                f"⚠️ مراقبة الصفقة: {e}"
            )

        time.sleep(10)


# ============================================================
# RECORD FINISHED TRADE
# ============================================================

def record_finished_trade(trade, final_price):

    entry = float(
        trade["entry_price"]
    )

    qty = float(
        trade["quantity"]
    )

    profit = (
        final_price - entry
    ) * qty

    profit_percent = (
        (final_price - entry)
        / entry
    ) * 100

    if profit >= 0:
        state["wins"] += 1
    else:
        state["losses"] += 1

    state["total_profit"] += profit

    state["trades"].append({
        "symbol": trade["symbol"],
        "entry": entry,
        "exit": final_price,
        "quantity": qty,
        "profit": profit,
        "profit_percent": profit_percent,
        "time": now_ms()
    })

    log(
        f"💰 نتيجة الصفقة: "
        f"{profit:+.4f} USDT "
        f"({profit_percent:+.2f}%)"
    )


# ============================================================
# SCANNER
# ============================================================

def get_symbols():

    data = public_get(
        "/api/v3/ticker/24hr"
    )

    symbols = []

    for x in data:

        symbol = x.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if symbol not in symbols_info:
            continue

        try:
            volume = float(
                x.get("quoteVolume", 0)
            )
        except:
            continue

        if volume < MIN_VOLUME:
            continue

        symbols.append(symbol)

    return symbols


def get_klines(symbol):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": 2
        }
    )


def check_signal(symbol):

    candles = get_klines(symbol)

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

    trigger_price = (
        previous_close
        * (1 - DROP_PERCENT)
    )

    return current_low <= trigger_price


def trading_loop():

    log("")
    log("🚀 بدأ محرك التداول")
    log("")

    while True:

        try:

            # لا تدخل صفقة ثانية
            if state.get("active_trade"):
                time.sleep(10)
                continue

            symbols = get_symbols()

            state["last_scan"] = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            log(
                f"🔎 فحص {len(symbols)} عملة..."
            )

            for i, symbol in enumerate(symbols, 1):

                # إذا دخلت صفقة أثناء الفحص
                if state.get("active_trade"):
                    break

                try:

                    signal = check_signal(symbol)

                    if not signal:
                        continue

                    log("")
                    log(
                        f"🚨 إشارة شراء "
                        f"[{i}/{len(symbols)}] "
                        f"{symbol}"
                    )

                    # =========================================
                    # BUY
                    # =========================================

                    result = market_buy(
                        symbol,
                        TRADE_USDT
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
                        continue

                    entry = (
                        quote_qty
                        / executed_qty
                    )

                    tp = entry * (
                        1 + TP_PERCENT
                    )

                    sl = entry * (
                        1 - SL_PERCENT
                    )

                    log(
                        f"✅ تم الشراء: {symbol}"
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

                    # =========================================
                    # حفظ الصفقة فورًا
                    # =========================================

                    state["active_trade"] = {
                        "symbol": symbol,
                        "quantity": executed_qty,
                        "entry_price": entry,
                        "tp": tp,
                        "sl": sl,
                        "buy_order_id": result.get(
                            "orderId"
                        ),
                        "created_at": now_ms()
                    }

                    save_state()

                    # =========================================
                    # OCO
                    # =========================================

                    try:

                        place_oco(
                            symbol,
                            executed_qty,
                            tp,
                            sl
                        )

                        log(
                            f"🛡️ OCO مفعل: "
                            f"{symbol}"
                        )

                    except Exception as e:

                        log(
                            f"❌ فشل OCO: {e}"
                        )

                        # لا نترك الصفقة بدون حماية
                        try:
                            balance = get_balance(
                                symbols_info[symbol]["base"]
                            )

                            if balance["total"] > 0:
                                market_sell(
                                    symbol,
                                    balance["total"]
                                )

                                log(
                                    f"🔴 تم إغلاق الصفقة "
                                    f"لعدم وجود حماية"
                                )

                        except Exception as sell_error:
                            log(
                                f"🚨 فشل الإغلاق الطارئ: "
                                f"{sell_error}"
                            )

                        state["active_trade"] = None
                        save_state()

                        continue

                    log(
                        "⏸️ الصفقة مفتوحة "
                        "→ إيقاف البحث عن صفقة ثانية"
                    )

                    time.sleep(10)

                except Exception as e:

                    log(
                        f"⚠️ {symbol}: {e}"
                    )

            time.sleep(SCAN_SLEEP)

        except Exception as e:

            log(
                f"🚨 خطأ محرك التداول: {e}"
            )

            time.sleep(15)


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
    font-size:25px;
    font-weight:bold;
}

.row{
    display:flex;
    justify-content:space-between;
    padding:8px 0;
    border-bottom:1px solid #292d36;
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
<span>الصفقات</span>
<span id="trades">0</span>
</div>

<div class="row">
<span>فوز</span>
<span class="green" id="wins">0</span>
</div>

<div class="row">
<span>خسارة</span>
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

        let r = await fetch('/api/status');

        let d = await r.json();

        document.getElementById('binance').innerHTML =
            d.binance
            ? '<span class="green">متصل ✅</span>'
            : '<span class="red">غير متصل ❌</span>';

        document.getElementById('status').innerText =
            d.status;

        document.getElementById('symbols').innerText =
            d.symbols_count;

        document.getElementById('balance').innerText =
            d.balance.toFixed(4);

        document.getElementById('trades').innerText =
            d.trades;

        document.getElementById('wins').innerText =
            d.wins;

        document.getElementById('losses').innerText =
            d.losses;

        document.getElementById('winrate').innerText =
            d.winrate.toFixed(2) + '%';

        document.getElementById('profit').innerText =
            d.total_profit.toFixed(4) + ' USDT';

        if(d.active_trade){

            let t = d.active_trade;

            document.getElementById('trade').innerHTML = `

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
                    <span>${Number(d.current_price).toFixed(8)}</span>
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
                    <span>P/L</span>
                    <b>${Number(d.trade_pnl).toFixed(2)}%</b>
                </div>

            `;

        }else{

            document.getElementById('trade').innerHTML =
                '<span class="yellow">لا توجد صفقة مفتوحة</span>';

        }

    }catch(e){

        console.log(e);

    }

}

update();

setInterval(update,5000);

</script>

</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():

    balance = 0.0

    try:
        b = get_balance("USDT")
        balance = b["free"] + b["locked"]

        state["binance"] = True

    except:
        state["binance"] = False

    active = state.get("active_trade")

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
                (current_price - entry)
                / entry
            ) * 100

        except:
            pass

    total_trades = (
        state["wins"]
        + state["losses"]
    )

    winrate = (
        state["wins"]
        / total_trades
        * 100
        if total_trades > 0
        else 0
    )

    return jsonify({

        "binance": state["binance"],

        "status": state["status"],

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
            state["last_scan"]

    })


# ============================================================
# STARTUP
# ============================================================

def start_bot():

    log("")
    log("=" * 60)
    log("🤖 مضارب أبو سعود")
    log("=" * 60)
    log("📉 نزول 2% → شراء")
    log("🎯 TP +2%")
    log("🛑 SL -2%")
    log("⏱️ 15 دقيقة")
    log(f"💰 مبلغ الصفقة: {TRADE_USDT}")
    log("🛡️ حماية Binance OCO")
    log("♻️ استعادة الصفقات بعد إعادة التشغيل")
    log("=" * 60)
    log("")

    if not API_KEY or not API_SECRET:
        log("❌ BINANCE_API_KEY أو BINANCE_API_SECRET ناقص")
        return

    try:

        load_state()

        load_exchange_info()

        account = get_account()

        if account.get("accountType"):
            state["binance"] = True

        log("🔗 Binance متصل ✅")

        # ================================================
        # أهم خطوة:
        # الاستعادة قبل تشغيل البحث
        # ================================================

        restored = restore_trade()

        if restored:
            state["status"] = "♻️ تم استعادة الصفقة"
        else:
            state["status"] = "🔍 يبحث عن فرص"

        save_state()

        # ================================================
        # مراقب الصفقة
        # ================================================

        monitor = threading.Thread(
            target=monitor_trade,
            daemon=True
        )

        monitor.start()

        # ================================================
        # محرك التداول
        # ================================================

        trader = threading.Thread(
            target=trading_loop,
            daemon=True
        )

        trader.start()

    except Exception as e:

        log(
            f"🚨 خطأ تشغيل: {e}"
        )

        state["status"] = "خطأ"


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
