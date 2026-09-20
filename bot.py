import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, render_template_string


# =========================================================
# CONFIG
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

FEE_RATE = Decimal("0.001")

# الاستراتيجية
EMA_PERIOD = 200
MIN_CHANGE_15M = Decimal("1.0")

# حماية الربح
PROTECTION_START = Decimal("1.0")
TRAIL_PERCENT = Decimal("0.50")

# استخدام الرصيد
BALANCE_USAGE = Decimal("0.999")

STATE_FILE = "bot_data.json"

POSITION_CHECK_SECONDS = 10
SCAN_INTERVAL = 30


# =========================================================
# SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mudarib-Abo-Saud/4.0"
})


# =========================================================
# APP STATE
# =========================================================

app = Flask(__name__)

state_lock = threading.Lock()

state = {
    "running": True,

    "binance_connected": False,
    "binance_message": "جاري التحقق...",

    "status": "جاري التشغيل",

    "active_symbol": None,
    "entry_price": None,
    "current_price": None,
    "highest_price": None,

    "position_qty": None,

    "gross_profit": None,
    "net_profit": None,
    "profit_usdt": None,

    "protection": False,
    "protection_price": None,

    "balance_usdt": None,

    "scan_count": 0,
    "usdt_pairs": 0,
    "candidates": 0,

    "best_candidate": None,
    "best_change": None,

    "last_action": "لم يتم تنفيذ أي عملية",
    "last_error": None,

    "position_source": None,

    "trade_start": None,

    "daily_profit": Decimal("0"),
    "weekly_profit": Decimal("0"),
    "monthly_profit": Decimal("0"),

    "daily_trades": 0,
    "weekly_trades": 0,
    "monthly_trades": 0,

    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,

    "last_update": None
}


# =========================================================
# DATA FILE
# =========================================================

def default_history():
    return {
        "trades": []
    }


def load_history():

    if not os.path.exists(STATE_FILE):

        return default_history()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if "trades" not in data:
            data["trades"] = []

        return data

    except Exception as e:

        print(
            f"⚠️ فشل قراءة ملف البيانات: {e}",
            flush=True
        )

        return default_history()


history = load_history()


def save_history():

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                history,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"⚠️ فشل حفظ البيانات: {e}",
            flush=True
        )


# =========================================================
# HELPERS
# =========================================================

def D(value):

    try:
        return Decimal(str(value))
    except:
        return Decimal("0")


def now_riyadh():

    return datetime.now(
        timezone(timedelta(hours=3))
    )


def set_state(**kwargs):

    with state_lock:

        for key, value in kwargs.items():
            state[key] = value


def log(message):

    print(message, flush=True)


def decimal_json(value):

    if isinstance(value, Decimal):
        return str(value)

    return value


# =========================================================
# BINANCE PUBLIC REQUEST
# =========================================================

def public_request(
    method,
    path,
    params=None
):

    url = BASE_URL + path

    for attempt in range(5):

        try:

            response = session.request(
                method,
                url,
                params=params,
                timeout=15
            )

            if response.status_code == 429:

                wait = min(
                    30,
                    2 ** attempt
                )

                log(
                    f"⚠️ Binance 429 - "
                    f"انتظار {wait} ثانية"
                )

                time.sleep(wait)

                continue

            if response.status_code >= 400:

                raise Exception(
                    f"Binance {response.status_code}: "
                    f"{response.text[:500]}"
                )

            return response.json()

        except Exception:

            if attempt == 4:
                raise

            time.sleep(
                1 + attempt
            )


# =========================================================
# BINANCE SIGNED REQUEST
# =========================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise Exception(
            "BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود"
        )

    if params is None:
        params = {}

    params = dict(params)

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
        BASE_URL
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    for attempt in range(5):

        try:

            response = session.request(
                method,
                url,
                headers=headers,
                timeout=15
            )

            if response.status_code == 429:

                wait = min(
                    30,
                    2 ** attempt
                )

                log(
                    f"⚠️ Binance 429 - "
                    f"انتظار {wait} ثانية"
                )

                time.sleep(wait)

                continue

            if response.status_code >= 400:

                raise Exception(
                    f"Binance {response.status_code}: "
                    f"{response.text[:700]}"
                )

            return response.json()

        except Exception:

            if attempt == 4:
                raise

            time.sleep(
                1 + attempt
            )


# =========================================================
# BINANCE CONNECTION
# =========================================================

def check_binance_connection():

    if not API_KEY or not API_SECRET:

        set_state(
            binance_connected=False,
            binance_message="❌ مفاتيح Binance غير موجودة"
        )

        return False

    try:

        account = signed_request(
            "GET",
            "/api/v3/account"
        )

        if account:

            set_state(
                binance_connected=True,
                binance_message="🟢 Binance مربوط"
            )

            return True

    except Exception as e:

        set_state(
            binance_connected=False,
            binance_message="🔴 Binance غير مربوط",
            last_error=str(e)
        )

        log(
            f"🚨 اتصال Binance: {e}"
        )

    return False


# =========================================================
# EXCHANGE INFO
# =========================================================

exchange_cache = {
    "time": 0,
    "symbols": []
}

symbol_rules = {}


def load_symbols():

    current = time.time()

    if (
        exchange_cache["symbols"]
        and
        current - exchange_cache["time"] < 3600
    ):

        return exchange_cache["symbols"]

    data = public_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    symbols = []

    for item in data["symbols"]:

        if item["status"] != "TRADING":
            continue

        if item["quoteAsset"] != "USDT":
            continue

        symbol = item["symbol"]

        symbols.append(symbol)

        filters = {}

        for f in item["filters"]:
            filters[f["filterType"]] = f

        symbol_rules[symbol] = filters

    exchange_cache["symbols"] = symbols
    exchange_cache["time"] = current

    set_state(
        usdt_pairs=len(symbols)
    )

    log(
        f"📚 تم تحميل {len(symbols)} عملة USDT"
    )

    return symbols


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    data = public_request(
        "GET",
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return D(data["price"])


def get_all_prices():

    data = public_request(
        "GET",
        "/api/v3/ticker/price"
    )

    prices = {}

    for item in data:

        prices[item["symbol"]] = D(
            item["price"]
        )

    return prices


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

    for balance in account["balances"]:

        if balance["asset"] == "USDT":

            return D(balance["free"])

    return Decimal("0")


# =========================================================
# KLINES / EMA
# =========================================================

def get_klines(
    symbol,
    interval,
    limit=205
):

    return public_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def calculate_ema(
    closes,
    period=200
):

    if len(closes) < period:
        return None

    ema = (
        sum(closes[:period])
        / Decimal(period)
    )

    multiplier = (
        Decimal("2")
        / Decimal(period + 1)
    )

    for price in closes[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


def get_ema(
    symbol,
    interval
):

    klines = get_klines(
        symbol,
        interval,
        EMA_PERIOD + 5
    )

    closes = [
        D(k[4])
        for k in klines
    ]

    return calculate_ema(
        closes,
        EMA_PERIOD
    )


# =========================================================
# 15M CHANGE
# =========================================================

def get_15m_change(symbol):

    klines = get_klines(
        symbol,
        "15m",
        2
    )

    if len(klines) < 2:
        return None

    candle = klines[-1]

    open_price = D(candle[1])
    close_price = D(candle[4])

    if open_price <= 0:
        return None

    return (
        (close_price - open_price)
        / open_price
    ) * 100


# =========================================================
# FIND OPEN POSITION
# =========================================================

def find_open_position():

    account = get_account()

    balances = []

    for balance in account["balances"]:

        asset = balance["asset"]

        if asset == "USDT":
            continue

        qty = (
            D(balance["free"])
            +
            D(balance["locked"])
        )

        if qty <= 0:
            continue

        symbol = asset + "USDT"

        balances.append(
            (symbol, qty)
        )

    if not balances:
        return None

    prices = get_all_prices()

    positions = []

    for symbol, qty in balances:

        price = prices.get(symbol)

        if not price:
            continue

        value = qty * price

        if value >= Decimal("5"):

            positions.append(
                (
                    symbol,
                    qty,
                    price,
                    value
                )
            )

    if not positions:
        return None

    positions.sort(
        key=lambda x: x[3],
        reverse=True
    )

    symbol, qty, price, value = positions[0]

    # -----------------------------------------------------
    # حساب متوسط الدخول
    # -----------------------------------------------------

    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

        current_qty = Decimal("0")
        cost = Decimal("0")

        for trade in sorted(
            trades,
            key=lambda x: x["time"]
        ):

            trade_qty = D(
                trade["qty"]
            )

            trade_price = D(
                trade["price"]
            )

            commission = D(
                trade["commission"]
            )

            base_asset = symbol.replace(
                "USDT",
                ""
            )

            if trade["isBuyer"]:

                added_qty = trade_qty

                if (
                    trade["commissionAsset"]
                    == base_asset
                ):
                    added_qty -= commission

                current_qty += added_qty

                cost += (
                    trade_qty
                    * trade_price
                )

                if (
                    trade["commissionAsset"]
                    == "USDT"
                ):
                    cost += commission

            else:

                sold_qty = trade_qty

                if (
                    trade["commissionAsset"]
                    == base_asset
                ):
                    sold_qty += commission

                if current_qty > 0:

                    average = (
                        cost
                        / current_qty
                    )

                    current_qty -= sold_qty

                    if current_qty < 0:
                        current_qty = Decimal("0")

                    cost = (
                        average
                        * current_qty
                    )

        if (
            current_qty > 0
            and
            cost > 0
        ):

            entry = (
                cost
                / current_qty
            )

        else:

            entry = price

    except Exception:

        entry = price

    return {
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "entry": entry,
        "value": value,
        "source": "Binance"
    }


# =========================================================
# PROFIT
# =========================================================

def calculate_gross_profit(
    entry,
    current
):

    if not entry or entry <= 0:
        return Decimal("0")

    return (
        (current - entry)
        / entry
    ) * 100


def calculate_net_profit(
    entry,
    current
):

    gross = calculate_gross_profit(
        entry,
        current
    )

    fees = (
        FEE_RATE
        * 2
        * 100
    )

    return gross - fees


def calculate_profit_usdt(
    entry,
    current,
    qty
):

    if not entry or not qty:
        return Decimal("0")

    gross = (
        current - entry
    ) * qty

    fees = (
        (entry * qty)
        * FEE_RATE
    ) + (
        (current * qty)
        * FEE_RATE
    )

    return gross - fees


# =========================================================
# TRADE HISTORY
# =========================================================

def record_trade(
    symbol,
    entry,
    exit_price,
    qty,
    profit
):

    record = {
        "symbol": symbol,
        "entry": str(entry),
        "exit": str(exit_price),
        "qty": str(qty),
        "profit": str(profit),
        "time": now_riyadh().isoformat()
    }

    history["trades"].append(
        record
    )

    # لا نخلي الملف يكبر للأبد
    if len(history["trades"]) > 5000:

        history["trades"] = (
            history["trades"][-5000:]
        )

    save_history()


def update_statistics():

    current = now_riyadh()

    today = current.date()

    week_start = (
        today
        - timedelta(
            days=today.weekday()
        )
    )

    month_start = today.replace(
        day=1
    )

    daily = Decimal("0")
    weekly = Decimal("0")
    monthly = Decimal("0")

    daily_count = 0
    weekly_count = 0
    monthly_count = 0

    total = 0
    winners = 0
    losers = 0

    for trade in history["trades"]:

        try:

            trade_time = datetime.fromisoformat(
                trade["time"]
            )

            profit = D(
                trade["profit"]
            )

            total += 1

            if profit > 0:
                winners += 1

            elif profit < 0:
                losers += 1

            trade_date = trade_time.date()

            if trade_date == today:

                daily += profit
                daily_count += 1

            if trade_date >= week_start:

                weekly += profit
                weekly_count += 1

            if trade_date >= month_start:

                monthly += profit
                monthly_count += 1

        except:
            continue

    set_state(
        daily_profit=daily,
        weekly_profit=weekly,
        monthly_profit=monthly,

        daily_trades=daily_count,
        weekly_trades=weekly_count,
        monthly_trades=monthly_count,

        total_trades=total,
        winning_trades=winners,
        losing_trades=losers
    )


# =========================================================
# BUY
# =========================================================

def market_buy(symbol):

    balance = get_usdt_balance()

    set_state(
        balance_usdt=balance
    )

    if balance <= Decimal("5"):

        raise Exception(
            "رصيد USDT غير كافي"
        )

    amount = (
        balance
        * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    log(
        f"💰 الرصيد {balance} USDT"
    )

    log(
        f"🟢 شراء {symbol} "
        f"بقيمة {amount} USDT"
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": str(amount)
        }
    )

    executed_qty = D(
        order["executedQty"]
    )

    fills = order.get(
        "fills",
        []
    )

    if fills:

        total_qty = Decimal("0")
        total_cost = Decimal("0")

        for fill in fills:

            qty = D(fill["qty"])
            price = D(fill["price"])

            total_qty += qty
            total_cost += (
                qty * price
            )

        entry = (
            total_cost
            / total_qty
        )

    else:

        entry = get_price(symbol)

    set_state(
        active_symbol=symbol,

        entry_price=entry,
        current_price=entry,
        highest_price=entry,

        position_qty=executed_qty,

        gross_profit=Decimal("0"),
        net_profit=Decimal("0"),
        profit_usdt=Decimal("0"),

        protection=False,
        protection_price=None,

        position_source="Bot",

        trade_start=now_riyadh().isoformat(),

        status="🟢 صفقة مفتوحة",

        last_action=(
            f"🟢 شراء {symbol}"
        ),

        last_error=None
    )

    log(
        f"🟢 تم الشراء "
        f"{symbol} | "
        f"Entry {entry}"
    )


# =========================================================
# CANCEL SELL PROTECTION
# =========================================================

def cancel_protection(symbol):

    try:

        orders = signed_request(
            "GET",
            "/api/v3/openOrders",
            {
                "symbol": symbol
            }
        )

        for order in orders:

            if order["side"] != "SELL":
                continue

            try:

                signed_request(
                    "DELETE",
                    "/api/v3/order",
                    {
                        "symbol": symbol,
                        "orderId": order["orderId"]
                    }
                )

            except Exception as e:

                log(
                    f"⚠️ إلغاء أمر: {e}"
                )

    except Exception as e:

        log(
            f"⚠️ فحص الحماية: {e}"
        )


# =========================================================
# CREATE PROTECTION
# =========================================================

def create_protection(
    symbol,
    qty,
    stop_price
):

    rules = symbol_rules.get(
        symbol,
        {}
    )

    # كمية
    lot = rules.get(
        "LOT_SIZE"
    )

    if lot:

        step = D(
            lot["stepSize"]
        )

        qty = (
            qty / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    # السعر
    price_filter = rules.get(
        "PRICE_FILTER"
    )

    if price_filter:

        tick = D(
            price_filter["tickSize"]
        )

        stop_price = (
            stop_price / tick
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * tick

    qty = qty.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    stop_price = stop_price.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_DOWN
    )

    return signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": str(qty),
            "stopPrice": str(stop_price)
        }
    )


# =========================================================
# UPDATE PROTECTION
# =========================================================

def update_protection():

    symbol = state["active_symbol"]
    entry = state["entry_price"]
    qty = state["position_qty"]

    if not symbol or not entry or not qty:
        return

    price = get_price(symbol)

    gross = calculate_gross_profit(
        entry,
        price
    )

    net = calculate_net_profit(
        entry,
        price
    )

    profit_usdt = calculate_profit_usdt(
        entry,
        price,
        qty
    )

    highest = state["highest_price"]

    if (
        highest is None
        or
        price > highest
    ):

        highest = price

        set_state(
            highest_price=highest
        )

    set_state(
        current_price=price,
        gross_profit=gross,
        net_profit=net,
        profit_usdt=profit_usdt
    )

    # -----------------------------------------------------
    # قبل +1% لا توجد حماية
    # -----------------------------------------------------

    if net < PROTECTION_START:

        return

    # -----------------------------------------------------
    # الحماية تتحرك مع أعلى سعر
    # -----------------------------------------------------

    trailing_stop = (
        highest
        * (
            Decimal("1")
            - (
                TRAIL_PERCENT
                / 100
            )
        )
    )

    # ضمان بقاء الحماية فوق الدخول
    minimum_stop = (
        entry
        * Decimal("1.001")
    )

    new_stop = max(
        trailing_stop,
        minimum_stop
    )

    old_stop = state[
        "protection_price"
    ]

    # لا ننزل الحماية
    if (
        old_stop is not None
        and
        new_stop <= old_stop
    ):

        return

    try:

        cancel_protection(
            symbol
        )

        time.sleep(0.3)

        create_protection(
            symbol,
            qty,
            new_stop
        )

        set_state(
            protection=True,
            protection_price=new_stop,

            last_action=(
                f"🛡️ حماية الربح "
                f"{new_stop}"
            )
        )

        log(
            f"🛡️ حماية {symbol} "
            f"عند {new_stop}"
        )

    except Exception as e:

        log(
            f"🚨 فشل الحماية: {e}"
        )

        set_state(
            last_error=str(e)
        )


# =========================================================
# CLEAR POSITION
# =========================================================

def clear_position():

    set_state(
        active_symbol=None,

        entry_price=None,
        current_price=None,
        highest_price=None,

        position_qty=None,

        gross_profit=None,
        net_profit=None,
        profit_usdt=None,

        protection=False,
        protection_price=None,

        position_source=None,
        trade_start=None,

        status="لا توجد صفقة",

        last_action=(
            "✅ انتهت الصفقة"
        )
    )

    update_statistics()


# =========================================================
# MANAGE POSITION
# =========================================================

def manage_position(position):

    symbol = position["symbol"]

    entry = position["entry"]

    qty = position["qty"]

    set_state(
        active_symbol=symbol,
        entry_price=entry,
        position_qty=qty,

        position_source=position["source"],

        status="♻️ إدارة الصفقة"
    )

    log(
        f"♻️ إدارة {symbol} "
        f"| Entry {entry}"
    )

    while True:

        try:

            price = get_price(
                symbol
            )

            gross = calculate_gross_profit(
                entry,
                price
            )

            net = calculate_net_profit(
                entry,
                price
            )

            profit_usdt = calculate_profit_usdt(
                entry,
                price,
                qty
            )

            highest = state[
                "highest_price"
            ]

            if (
                highest is None
                or
                price > highest
            ):

                highest = price

            set_state(
                current_price=price,

                highest_price=highest,

                gross_profit=gross,
                net_profit=net,
                profit_usdt=profit_usdt
            )

            log(
                f"📊 {symbol} | "
                f"{price} | "
                f"صافي {net:.2f}% | "
                f"ربح {profit_usdt:.4f} USDT"
            )

            update_protection()

            time.sleep(
                POSITION_CHECK_SECONDS
            )

            latest = find_open_position()

            if latest is None:

                # نستخدم آخر سعر معروف
                exit_price = (
                    state["current_price"]
                    or price
                )

                final_profit = calculate_profit_usdt(
                    entry,
                    exit_price,
                    qty
                )

                record_trade(
                    symbol,
                    entry,
                    exit_price,
                    qty,
                    final_profit
                )

                update_statistics()

                log(
                    f"✅ أغلقت {symbol} "
                    f"| الربح {final_profit:.4f} USDT"
                )

                clear_position()

                return

            if latest["symbol"] != symbol:

                clear_position()

                return

        except Exception as e:

            log(
                f"🚨 إدارة الصفقة: {e}"
            )

            set_state(
                last_error=str(e)
            )

            time.sleep(10)


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market():

    symbols = load_symbols()

    candidates = []

    set_state(
        status="🔎 فحص السوق",
        last_error=None
    )

    # -----------------------------------------------------
    # أول فلتر:
    # 15m > 1%
    # -----------------------------------------------------

    for symbol in symbols:

        try:

            change = get_15m_change(
                symbol
            )

            if change is None:
                continue

            if change <= MIN_CHANGE_15M:
                continue

            candidates.append(
                (
                    symbol,
                    change
                )
            )

        except Exception:
            continue

    # الأقوى أولاً
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    set_state(
        candidates=len(candidates)
    )

    # -----------------------------------------------------
    # اختبار EMA للأقوى
    # -----------------------------------------------------

    for symbol, change in candidates:

        try:

            ema15 = get_ema(
                symbol,
                "15m"
            )

            if ema15 is None:
                continue

            price15 = get_price(
                symbol
            )

            if price15 <= ema15:
                continue

            ema5 = get_ema(
                symbol,
                "5m"
            )

            if ema5 is None:
                continue

            price5 = get_price(
                symbol
            )

            if price5 <= ema5:
                continue

            ema1 = get_ema(
                symbol,
                "1m"
            )

            if ema1 is None:
                continue

            price1 = get_price(
                symbol
            )

            if price1 <= ema1:
                continue

            set_state(
                best_candidate=symbol,
                best_change=change
            )

            log(
                f"🔥 أقوى فرصة: "
                f"{symbol} "
                f"| +{change:.2f}%"
            )

            return symbol

        except Exception as e:

            log(
                f"⚠️ فحص {symbol}: {e}"
            )

    return None


# =========================================================
# TRADING ENGINE
# =========================================================

def trading_engine():

    log(
        "🚀 بدأ محرك مضارب أبو سعود"
    )

    while True:

        try:

            # =============================================
            # دائماً الصفقة أولاً
            # =============================================

            log(
                "🔍 فحص الصفقات المفتوحة أولاً..."
            )

            position = find_open_position()

            if position:

                log(
                    f"♻️ صفقة موجودة: "
                    f"{position['symbol']}"
                )

                manage_position(
                    position
                )

                continue

            # =============================================
            # لا توجد صفقة
            # =============================================

            set_state(
                status="🔎 لا توجد صفقة - البحث"
            )

            # =============================================
            # تحديث الرصيد
            # =============================================

            try:

                balance = get_usdt_balance()

                set_state(
                    balance_usdt=balance
                )

            except Exception as e:

                set_state(
                    last_error=str(e)
                )

            # =============================================
            # فحص السوق
            # =============================================

            with state_lock:

                state["scan_count"] += 1

                scan_number = state[
                    "scan_count"
                ]

            log(
                f"🔎 فحص السوق رقم {scan_number}"
            )

            symbol = scan_market()

            if symbol is None:

                set_state(
                    status="⏳ لا توجد فرصة",

                    last_action=(
                        "لا توجد صفقة مطابقة"
                    )
                )

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # =============================================
            # شراء
            # =============================================

            market_buy(
                symbol
            )

            # =============================================
            # إدارة الصفقة
            # =============================================

            position = find_open_position()

            if position:

                manage_position(
                    position
                )

            else:

                log(
                    "⚠️ لم تظهر الصفقة بعد الشراء"
                )

        except Exception as e:

            log(
                f"🚨 خطأ المحرك: {e}"
            )

            set_state(
                status="⚠️ خطأ - إعادة المحاولة",
                last_error=str(e)
            )

            time.sleep(15)


# =========================================================
# DASHBOARD
# =========================================================

HTML = """
<!DOCTYPE html>

<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود</title>

<style>

*{
box-sizing:border-box;
}

body{
margin:0;
background:#070b12;
color:#f5f7fa;
font-family:
Arial,
Tahoma,
sans-serif;
}

.container{
width:min(1150px,94%);
margin:auto;
padding:25px 0 40px;
}

.top{
display:flex;
justify-content:space-between;
align-items:center;
gap:15px;
margin-bottom:20px;
}

.brand{
font-size:28px;
font-weight:800;
}

.sub{
color:#7f8a9d;
font-size:13px;
margin-top:5px;
}

.connection{
padding:10px 15px;
border-radius:30px;
background:#111927;
border:1px solid #243044;
font-size:13px;
}

.hero{
background:
linear-gradient(
135deg,
#111827,
#0b111c
);

border:1px solid #202b3c;

border-radius:25px;

padding:25px;

margin-bottom:16px;
}

.hero-top{
display:flex;
justify-content:space-between;
align-items:center;
}

.hero-label{
color:#8792a5;
font-size:13px;
}

.hero-symbol{
font-size:38px;
font-weight:900;
margin-top:8px;
}

.hero-profit{
font-size:34px;
font-weight:900;
}

.cards{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(190px,1fr));

gap:13px;

margin-bottom:16px;
}

.card{
background:#0e141e;
border:1px solid #202b3c;
border-radius:19px;
padding:19px;
}

.label{
font-size:12px;
color:#7f8a9d;
margin-bottom:10px;
}

.value{
font-size:22px;
font-weight:800;
}

.green{
color:#48e39a;
}

.red{
color:#ff6477;
}

.blue{
color:#6ba9ff;
}

.gold{
color:#ffd166;
}

.section{
margin-top:18px;
}

.section-title{
font-size:17px;
font-weight:800;
margin-bottom:11px;
}

.performance{
display:grid;
grid-template-columns:
repeat(3,1fr);

gap:13px;
}

.period{
background:#0e141e;
border:1px solid #202b3c;
border-radius:19px;
padding:20px;
}

.period-name{
color:#8a95a8;
font-size:13px;
}

.period-profit{
font-size:28px;
font-weight:900;
margin-top:8px;
}

.period-trades{
color:#778397;
font-size:12px;
margin-top:7px;
}

.info{
background:#0e141e;
border:1px solid #202b3c;
border-radius:19px;
padding:19px;
}

.row{
display:flex;
justify-content:space-between;
align-items:center;
padding:12px 0;
border-bottom:1px solid #1b2533;
gap:20px;
}

.row:last-child{
border-bottom:0;
}

.row span{
color:#7f8a9d;
font-size:13px;
}

.row b{
font-size:14px;
text-align:left;
word-break:break-word;
}

.footer{
text-align:center;
color:#566173;
font-size:11px;
margin-top:25px;
}

@media(max-width:650px){

.top{
align-items:flex-start;
flex-direction:column;
}

.hero-top{
align-items:flex-start;
flex-direction:column;
gap:15px;
}

.hero-profit{
font-size:30px;
}

.performance{
grid-template-columns:1fr;
}

.cards{
grid-template-columns:
repeat(2,1fr);
}

.value{
font-size:18px;
}

}

</style>

</head>

<body>

<div class="container">

<div class="top">

<div>

<div class="brand">
🤖 مضارب أبو سعود
</div>

<div class="sub">
Binance Spot • لوحة المتابعة
</div>

</div>

<div
class="connection"
id="connection">
جاري التحقق...
</div>

</div>


<!-- الصفقة الحالية -->

<div class="hero">

<div class="hero-top">

<div>

<div class="hero-label">
الصفقة الحالية
</div>

<div
class="hero-symbol"
id="symbol">
لا توجد صفقة
</div>

</div>

<div>

<div class="hero-label">
صافي الربح
</div>

<div
class="hero-profit green"
id="profit">
-
</div>

</div>

</div>

</div>


<!-- تفاصيل الصفقة -->

<div class="cards">

<div class="card">

<div class="label">
سعر الدخول
</div>

<div
class="value"
id="entry">
-
</div>

</div>


<div class="card">

<div class="label">
السعر الحالي
</div>

<div
class="value blue"
id="price">
-
</div>

</div>


<div class="card">

<div class="label">
الربح USDT
</div>

<div
class="value green"
id="profit_usdt">
-
</div>

</div>


<div class="card">

<div class="label">
أعلى سعر
</div>

<div
class="value gold"
id="highest">
-
</div>

</div>


<div class="card">

<div class="label">
حماية الربح
</div>

<div
class="value"
id="protection">
-
</div>

</div>


<div class="card">

<div class="label">
الرصيد USDT
</div>

<div
class="value"
id="balance">
-
</div>

</div>

</div>


<!-- الأداء -->

<div class="section">

<div class="section-title">
📈 الأداء
</div>

<div class="performance">


<div class="period">

<div class="period-name">
اليوم
</div>

<div
class="period-profit green"
id="daily">
0 USDT
</div>

<div
class="period-trades"
id="daily_trades">
0 صفقة
</div>

</div>


<div class="period">

<div class="period-name">
هذا الأسبوع
</div>

<div
class="period-profit green"
id="weekly">
0 USDT
</div>

<div
class="period-trades"
id="weekly_trades">
0 صفقة
</div>

</div>


<div class="period">

<div class="period-name">
هذا الشهر
</div>

<div
class="period-profit green"
id="monthly">
0 USDT
</div>

<div
class="period-trades"
id="monthly_trades">
0 صفقة
</div>

</div>

</div>

</div>


<!-- الإحصائيات -->

<div class="section">

<div class="section-title">
📊 الإحصائيات
</div>

<div class="cards">

<div class="card">

<div class="label">
إجمالي الصفقات
</div>

<div
class="value"
id="total">
0
</div>

</div>

<div class="card">

<div class="label">
صفقات رابحة
</div>

<div
class="value green"
id="wins">
0
</div>

</div>

<div class="card">

<div class="label">
صفقات خاسرة
</div>

<div
class="value red"
id="losses">
0
</div>

</div>

<div class="card">

<div class="label">
نسبة النجاح
</div>

<div
class="value blue"
id="winrate">
0%
</div>

</div>

</div>

</div>


<!-- معلومات البوت -->

<div class="section">

<div class="section-title">
⚙️ حالة النظام
</div>

<div class="info">

<div class="row">

<span>
حالة البوت
</span>

<b id="status">
-
</b>

</div>


<div class="row">

<span>
Binance
</span>

<b id="binance">
-
</b>

</div>


<div class="row">

<span>
مصدر الصفقة
</span>

<b id="source">
-
</b>

</div>


<div class="row">

<span>
عدد عملات USDT
</span>

<b id="pairs">
-
</b>

</div>


<div class="row">

<span>
العملات المرشحة
</span>

<b id="candidates">
-
</b>

</div>


<div class="row">

<span>
أقوى مرشح
</span>

<b id="best">
-
</b>

</div>


<div class="row">

<span>
نسبة المرشح
</span>

<b id="change">
-
</b>

</div>


<div class="row">

<span>
عدد الفحوصات
</span>

<b id="scans">
-
</b>

</div>


<div class="row">

<span>
آخر عملية
</span>

<b id="action">
-
</b>

</div>


<div class="row">

<span>
آخر خطأ
</span>

<b id="error">
لا يوجد
</b>

</div>

</div>

</div>


<div class="footer">
مضارب أبو سعود 🤖
</div>

</div>


<script>

function textValue(v){

if(
v === null ||
v === undefined ||
v === ""
){
return "-";
}

return v;

}


function num(v){

if(
v === null ||
v === undefined ||
v === ""
){
return "-";
}

let n = Number(v);

if(
Number.isNaN(n)
){
return v;
}

return n.toFixed(6);

}


function pct(v){

if(
v === null ||
v === undefined
){
return "-";
}

return Number(v).toFixed(2)+"%";

}


function money(v){

if(
v === null ||
v === undefined
){
return "0.0000 USDT";
}

return Number(v).toFixed(4)+" USDT";

}


async function update(){

try{

const response =
await fetch(
"/api/status",
{
cache:"no-store"
}
);

const d =
await response.json();


document.getElementById(
"connection"
).innerText =
textValue(
d.binance_message
);


document.getElementById(
"binance"
).innerText =
textValue(
d.binance_message
);


document.getElementById(
"status"
).innerText =
textValue(
d.status
);


document.getElementById(
"symbol"
).innerText =
textValue(
d.active_symbol
);


document.getElementById(
"entry"
).innerText =
num(
d.entry_price
);


document.getElementById(
"price"
).innerText =
num(
d.current_price
);


document.getElementById(
"profit"
).innerText =
pct(
d.net_profit
);


document.getElementById(
"profit_usdt"
).innerText =
money(
d.profit_usdt
);


document.getElementById(
"highest"
).innerText =
num(
d.highest_price
);


document.getElementById(
"protection"
).innerText =
d.protection
?
num(d.protection_price)
:
"غير مفعلة";


document.getElementById(
"balance"
).innerText =
money(
d.balance_usdt
);


document.getElementById(
"daily"
).innerText =
money(
d.daily_profit
);


document.getElementById(
"weekly"
).innerText =
money(
d.weekly_profit
);


document.getElementById(
"monthly"
).innerText =
money(
d.monthly_profit
);


document.getElementById(
"daily_trades"
).innerText =
textValue(
d.daily_trades
)+" صفقة";


document.getElementById(
"weekly_trades"
).innerText =
textValue(
d.weekly_trades
)+" صفقة";


document.getElementById(
"monthly_trades"
).innerText =
textValue(
d.monthly_trades
)+" صفقة";


document.getElementById(
"total"
).innerText =
textValue(
d.total_trades
);


document.getElementById(
"wins"
).innerText =
textValue(
d.winning_trades
);


document.getElementById(
"losses"
).innerText =
textValue(
d.losing_trades
);


let total =
Number(d.total_trades || 0);

let wins =
Number(d.winning_trades || 0);

let winrate =
total > 0
?
(wins / total) * 100
:
0;

document.getElementById(
"winrate"
).innerText =
winrate.toFixed(1)+"%";


document.getElementById(
"source"
).innerText =
textValue(
d.position_source
);


document.getElementById(
"pairs"
).innerText =
textValue(
d.usdt_pairs
);


document.getElementById(
"candidates"
).innerText =
textValue(
d.candidates
);


document.getElementById(
"best"
).innerText =
textValue(
d.best_candidate
);


document.getElementById(
"change"
).innerText =
pct(
d.best_change
);


document.getElementById(
"scans"
).innerText =
textValue(
d.scan_count
);


document.getElementById(
"action"
).innerText =
textValue(
d.last_action
);


document.getElementById(
"error"
).innerText =
d.last_error
?
d.last_error
:
"لا يوجد";


}
catch(e){

document.getElementById(
"connection"
).innerText =
"⚠️ الموقع يعمل - تعذر تحديث البيانات";

}

}


update();

setInterval(
update,
3000
);

</script>

</body>

</html>
"""


# =========================================================
# API
# =========================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    with state_lock:

        data = dict(state)

    # تحديث إحصائيات السجل
    update_statistics()

    with state_lock:

        data.update({
            "daily_profit":
                state["daily_profit"],

            "weekly_profit":
                state["weekly_profit"],

            "monthly_profit":
                state["monthly_profit"],

            "daily_trades":
                state["daily_trades"],

            "weekly_trades":
                state["weekly_trades"],

            "monthly_trades":
                state["monthly_trades"],

            "total_trades":
                state["total_trades"],

            "winning_trades":
                state["winning_trades"],

            "losing_trades":
                state["losing_trades"]
        })

    # Binance connection
    try:

        if API_KEY and API_SECRET:

            # لا نضرب API كل 3 ثواني
            # الحالة تحفظ من فحص المحرك

            pass

    except:
        pass

    for key, value in list(data.items()):

        if isinstance(value, Decimal):

            data[key] = str(value)

    return jsonify(data)


# =========================================================
# START
# =========================================================

def start():

    log(
        "================================"
    )

    log(
        "🤖 مضارب أبو سعود V4"
    )

    log(
        "================================"
    )

    # تحميل العملات
    try:

        load_symbols()

    except Exception as e:

        log(
            f"🚨 فشل تحميل العملات: {e}"
        )

    # فحص Binance
    check_binance_connection()

    # الإحصائيات
    update_statistics()

    # تشغيل التداول
    thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    thread.start()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    start()

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
