import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

STATE_FILE = os.path.expanduser("~/mybot/state.json")
HISTORY_FILE = os.path.expanduser("~/mybot/trade_history.json")

# ==========================================
# إعدادات
# ==========================================

# وقف البداية
INITIAL_STOP_NET = -0.02

# كل كم نرفع الوقف
STEP_PROFIT = 0.01

# رسوم Binance التقريبية:
# 0.1% شراء + 0.1% بيع
FEE_RATE = 0.001

# وقت الانتظار بين فحوصات الصفقة
POSITION_CHECK_SECONDS = 10

# أقل مبلغ دخول
MIN_USDT = 5

session = requests.Session()

if API_KEY:
    session.headers.update({
        "X-MBX-APIKEY": API_KEY
    })


# ==========================================
# Binance Public
# ==========================================

def public(path, params=None):

    while True:

        try:

            r = session.get(
                BASE + path,
                params=params,
                timeout=15
            )

            r.raise_for_status()

            return r.json()

        except Exception as e:

            print(
                f"\n⚠️ اتصال Binance: {e}"
            )

            time.sleep(10)


# ==========================================
# Binance Signed
# ==========================================

def signed(method, path, params=None):

    params = params.copy() if params else {}

    params["timestamp"] = int(
        time.time() * 1000
    )

    query = urllib.parse.urlencode(
        params
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    while True:

        try:

            r = session.request(
                method,
                BASE + path,
                params=params,
                timeout=15
            )

            data = r.json()

            if r.status_code >= 400:

                raise Exception(data)

            return data

        except Exception as e:

            print(
                f"\n⚠️ Binance: {e}"
            )

            time.sleep(10)


# ==========================================
# State
# ==========================================

def save_state(state):

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    with open(
        STATE_FILE,
        "w"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


def load_state():

    try:

        with open(
            STATE_FILE,
            "r"
        ) as f:

            return json.load(f)

    except Exception:

        return None


def clear_state():

    try:

        os.remove(
            STATE_FILE
        )

    except Exception:

        pass


# ==========================================
# History
# ==========================================

def save_trade(trade):

    os.makedirs(
        os.path.dirname(HISTORY_FILE),
        exist_ok=True
    )

    history = []

    try:

        with open(
            HISTORY_FILE,
            "r"
        ) as f:

            history = json.load(f)

    except Exception:

        pass

    history.append(trade)

    with open(
        HISTORY_FILE,
        "w"
    ) as f:

        json.dump(
            history[-100:],
            f,
            indent=2
        )


# ==========================================
# Exchange Info
# ==========================================

def get_symbols():

    data = public(
        "/api/v3/exchangeInfo"
    )

    result = []

    for x in data["symbols"]:

        if (
            x["status"] == "TRADING"
            and x["quoteAsset"] == "USDT"
            and x.get(
                "isSpotTradingAllowed",
                False
            )
        ):

            filters = {
                f["filterType"]: f
                for f in x["filters"]
            }

            lot = filters.get(
                "LOT_SIZE"
            )

            price_filter = filters.get(
                "PRICE_FILTER"
            )

            if not lot or not price_filter:
                continue

            result.append({

                "symbol": x["symbol"],

                "step": lot["stepSize"],

                "tick": price_filter["tickSize"]

            })

    return result


# ==========================================
# Klines
# ==========================================

def get_klines(symbol, interval):

    return public(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 220
        }
    )


# ==========================================
# EMA
# ==========================================

def ema(values, period):

    k = 2 / (period + 1)

    result = values[0]

    for price in values[1:]:

        result = (
            price * k
            + result * (1 - k)
        )

    return result


# ==========================================
# استراتيجية V2
# ==========================================

def check_signal(symbol):

    try:

        k15 = get_klines(
            symbol,
            "15m"
        )

        k1h = get_klines(
            symbol,
            "1h"
        )

        close15 = [
            float(x[4])
            for x in k15
        ]

        high15 = [
            float(x[2])
            for x in k15
        ]

        vol15 = [
            float(x[5])
            for x in k15
        ]

        close1h = [
            float(x[4])
            for x in k1h
        ]

        if (
            len(close15) < 220
            or len(close1h) < 220
        ):

            return False, "بيانات غير كافية"

        ema200_15 = ema(
            close15[-200:],
            200
        )

        ema200_1h = ema(
            close1h[-200:],
            200
        )

        price = close15[-1]

        resistance = max(
            high15[-21:-1]
        )

        avg_volume = (
            sum(vol15[-21:-1])
            / 20
        )

        volume_ratio = (
            vol15[-1]
            / avg_volume
            if avg_volume > 0
            else 0
        )

        volume_ok = (
            vol15[-1]
            >= avg_volume * 1.5
        )

        breakout = (
            price > resistance
        )

        move = (
            price / close15[-2]
        ) - 1

        if close1h[-1] <= ema200_1h:

            return False, "1H تحت EMA200"

        if close15[-1] <= ema200_15:

            return False, "15M تحت EMA200"

        if not breakout:

            return False, "لم يكسر المقاومة"

        if not volume_ok:

            return False, (
                f"الحجم {volume_ratio:.2f}x فقط"
            )

        if move < 0.005:

            return False, (
                f"الحركة {move * 100:.2f}% "
                f"أقل من 0.5%"
            )

        if move > 0.04:

            return False, (
                f"الحركة {move * 100:.2f}% "
                f"أكبر من 4%"
            )

        return True, "🔥 كل الشروط مكتملة"

    except Exception as e:

        return False, (
            f"خطأ: {str(e)[:80]}"
        )


# ==========================================
# Balance
# ==========================================

def get_account():

    return signed(
        "GET",
        "/api/v3/account"
    )


def get_usdt():

    data = get_account()

    for b in data["balances"]:

        if b["asset"] == "USDT":

            return float(
                b["free"]
            )

    return 0.0


def get_asset_balance(asset):

    data = get_account()

    for b in data["balances"]:

        if b["asset"] == asset:

            return float(
                b["free"]
            )

    return 0.0


# ==========================================
# Price
# ==========================================

def get_price(symbol):

    data = public(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ==========================================
# Price Rounding
# ==========================================

def round_price_down(
    price,
    tick
):

    p = Decimal(str(price))
    t = Decimal(str(tick))

    return float(
        (
            p / t
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * t
    )


def round_price_up(
    price,
    tick
):

    p = Decimal(str(price))
    t = Decimal(str(tick))

    return float(
        (
            p / t
        ).to_integral_value(
            rounding=ROUND_UP
        ) * t
    )


# ==========================================
# Quantity Rounding
# ==========================================

def round_qty_down(
    qty,
    step
):

    q = Decimal(str(qty))
    s = Decimal(str(step))

    return float(
        (
            q / s
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * s
    )


# ==========================================
# Market Buy
# ==========================================

def market_buy(
    symbol,
    amount
):

    return signed(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{amount:.2f}"
        }
    )


# ==========================================
# Entry Price
# ==========================================

def get_entry_from_order(order):

    fills = order.get(
        "fills",
        []
    )

    if fills:

        total_qty = sum(
            float(x["qty"])
            for x in fills
        )

        if total_qty > 0:

            total_value = sum(
                float(x["price"])
                * float(x["qty"])
                for x in fills
            )

            return (
                total_value
                / total_qty
            )

    executed_qty = float(
        order.get(
            "executedQty",
            0
        )
    )

    quote_qty = float(
        order.get(
            "cummulativeQuoteQty",
            0
        )
    )

    if executed_qty > 0:

        return (
            quote_qty
            / executed_qty
        )

    return get_price(
        order["symbol"]
    )


# ==========================================
# Net Profit → Stop Price
# ==========================================
#
# نحسب السعر المطلوب حتى يكون الناتج
# بعد رسوم الشراء والبيع قريب من النسبة
# المطلوبة.
#
# net = (exit / entry)
#       * (1-fee)/(1+fee) - 1
#
# ==========================================

def net_target_price(
    entry,
    net_target
):

    gross_ratio = (
        (1 + net_target)
        * (1 + FEE_RATE)
        / (1 - FEE_RATE)
    )

    return (
        entry
        * gross_ratio
    )


# ==========================================
# Create Real Stop Loss
# ==========================================

def create_stop_order(
    symbol,
    qty,
    stop_price,
    tick,
    step
):

    qty = round_qty_down(
        qty,
        step
    )

    stop_price = round_price_down(
        stop_price,
        tick
    )

    if qty <= 0:
        raise Exception(
            "الكمية بعد التقريب صفر"
        )

    if stop_price <= 0:
        raise Exception(
            "سعر الوقف غير صحيح"
        )

    print("")
    print(
        f"🛡️ وضع وقف حقيقي: "
        f"{stop_price:.8f}"
    )

    order = signed(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": format(
                qty,
                "f"
            ),
            "stopPrice": format(
                stop_price,
                "f"
            ),
            "newOrderRespType": "FULL"
        }
    )

    return order


# ==========================================
# Cancel Order
# ==========================================

def cancel_order(
    symbol,
    order_id
):

    return signed(
        "DELETE",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


# ==========================================
# Get Order
# ==========================================

def get_order(
    symbol,
    order_id
):

    return signed(
        "GET",
        "/api/v3/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


# ==========================================
# Order Exit Price
# ==========================================

def get_order_exit_price(
    order
):

    executed_qty = float(
        order.get(
            "executedQty",
            0
        )
    )

    quote_qty = float(
        order.get(
            "cummulativeQuoteQty",
            0
        )
    )

    if (
        executed_qty > 0
        and quote_qty > 0
    ):

        return (
            quote_qty
            / executed_qty
        )

    fills = order.get(
        "fills",
        []
    )

    if fills:

        total_qty = sum(
            float(x["qty"])
            for x in fills
        )

        if total_qty > 0:

            total_value = sum(
                float(x["price"])
                * float(x["qty"])
                for x in fills
            )

            return (
                total_value
                / total_qty
            )

    return None


# ==========================================
# Close Trade Record
# ==========================================

def record_trade(
    state,
    exit_price,
    reason
):

    entry = float(
        state["entry"]
    )

    invested = float(
        state["invested"]
    )

    gross_profit = (
        exit_price
        / entry
    ) - 1

    # تقريب صافي الربح بعد رسوم الشراء والبيع
    net_profit = (
        (
            (1 + gross_profit)
            * (1 - FEE_RATE)
            / (1 + FEE_RATE)
        )
        - 1
    )

    profit_usdt = (
        invested
        * net_profit
    )

    result = (
        "ربح"
        if net_profit >= 0
        else "خسارة"
    )

    trade = {

        "symbol": state["symbol"],

        "entry": entry,

        "exit": exit_price,

        "percent": round(
            net_profit * 100,
            4
        ),

        "profit_usdt": round(
            profit_usdt,
            4
        ),

        "result": result,

        "reason": reason,

        "time": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    save_trade(
        trade
    )

    print("")
    print(
        "===================================="
    )

    print(
        f"{'🟢' if net_profit >= 0 else '🔴'} "
        f"الصفقة انتهت: {result}"
    )

    print(
        f"📊 الصافي: "
        f"{net_profit * 100:+.2f}%"
    )

    print(
        f"💰 الصافي: "
        f"{profit_usdt:+.2f} USDT"
    )

    print(
        f"📌 السبب: {reason}"
    )

    print(
        "===================================="
    )

    return trade


# ==========================================
# Manage Position
# ==========================================

def manage_position(
    state
):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    qty = float(
        state["qty"]
    )

    step = state["step"]
    tick = state["tick"]

    invested = float(
        state["invested"]
    )

    current_level = float(
        state.get(
            "stop_level",
            INITIAL_STOP_NET
        )
    )

    stop_order_id = state.get(
        "stop_order_id"
    )

    print("")
    print(
        "===================================="
    )

    print(
        "🟢 الصفقة مفتوحة"
    )

    print(
        f"🪙 العملة: {symbol}"
    )

    print(
        f"📍 الدخول: {entry:.8f}"
    )

    print(
        f"💰 المبلغ: {invested:.2f} USDT"
    )

    print(
        f"🛑 وقف البداية: "
        f"{INITIAL_STOP_NET * 100:.0f}% صافي"
    )

    print(
        "📈 رفع الوقف: كل +1% صافي"
    )

    print(
        "===================================="
    )

    # ======================================
    # إذا أعيد تشغيل البوت
    # نتأكد أن أمر الوقف ما زال موجود
    # ======================================

    if stop_order_id:

        try:

            existing = get_order(
                symbol,
                stop_order_id
            )

            status = existing.get(
                "status"
            )

            if status == "FILLED":

                exit_price = (
                    get_order_exit_price(
                        existing
                    )
                )

                if exit_price is None:
                    exit_price = get_price(
                        symbol
                    )

                record_trade(
                    state,
                    exit_price,
                    "وقف الخسارة"
                )

                clear_state()

                return

            if status != "NEW":

                stop_order_id = None

        except Exception:

            stop_order_id = None

    # ======================================
    # إذا ما عندنا وقف، ننشئه
    # ======================================

    if not stop_order_id:

        stop_price = net_target_price(
            entry,
            current_level
        )

        stop_order = create_stop_order(
            symbol,
            qty,
            stop_price,
            tick,
            step
        )

        stop_order_id = stop_order[
            "orderId"
        ]

        state["stop_order_id"] = (
            stop_order_id
        )

        state["stop_level"] = (
            current_level
        )

        state["stop_price"] = (
            stop_price
        )

        save_state(
            state
        )

        print(
            f"🛡️ وقف حقيقي عند "
            f"{current_level * 100:+.2f}% صافي"
        )

    # ======================================
    # المتابعة
    # ======================================

    while True:

        try:

            # --------------------------------
            # تحقق من أمر الوقف
            # --------------------------------

            order = get_order(
                symbol,
                stop_order_id
            )

            status = order.get(
                "status"
            )

            if status == "FILLED":

                exit_price = (
                    get_order_exit_price(
                        order
                    )
                )

                if exit_price is None:

                    exit_price = get_price(
                        symbol
                    )

                record_trade(
                    state,
                    exit_price,
                    "وقف تلقائي من Binance"
                )

                clear_state()

                print(
                    "\n🔄 رجوع لفحص صفقات جديدة..."
                )

                return

            # --------------------------------
            # السعر الحالي
            # --------------------------------

            price = get_price(
                symbol
            )

            gross_profit = (
                price / entry
            ) - 1

            net_profit = (
                (
                    (1 + gross_profit)
                    * (1 - FEE_RATE)
                    / (1 + FEE_RATE)
                )
                - 1
            )

            profit_usdt = (
                invested
                * net_profit
            )

            # --------------------------------
            # مستوى الربح التالي
            # --------------------------------

            next_level = (
                int(
                    net_profit
                    / STEP_PROFIT
                )
                * STEP_PROFIT
            )

            # لا ننزل الوقف أبداً
            if next_level > current_level:

                new_level = next_level

                # --------------------------------
                # إلغاء الوقف القديم
                # --------------------------------

                print("")
                print(
                    "===================================="
                )

                print(
                    f"🚀 صافي الربح وصل "
                    f"{new_level * 100:.0f}%"
                )

                print(
                    f"🗑️ إلغاء الوقف القديم "
                    f"{current_level * 100:+.0f}%"
                )

                try:

                    cancel_order(
                        symbol,
                        stop_order_id
                    )

                except Exception as e:

                    print(
                        f"⚠️ تعذر إلغاء الوقف: {e}"
                    )

                    time.sleep(2)

                    continue

                # --------------------------------
                # وضع الوقف الجديد
                # --------------------------------

                new_stop_price = (
                    net_target_price(
                        entry,
                        new_level
                    )
                )

                print(
                    f"🛡️ رفع الوقف إلى "
                    f"{new_level * 100:+.0f}% صافي"
                )

                new_order = (
                    create_stop_order(
                        symbol,
                        qty,
                        new_stop_price,
                        tick,
                        step
                    )
                )

                stop_order_id = (
                    new_order["orderId"]
                )

                current_level = (
                    new_level
                )

                state["stop_order_id"] = (
                    stop_order_id
                )

                state["stop_level"] = (
                    current_level
                )

                state["stop_price"] = (
                    new_stop_price
                )

                save_state(
                    state
                )

                print(
                    f"✅ الوقف الجديد: "
                    f"{new_stop_price:.8f}"
                )

                print(
                    "===================================="
                )

            # --------------------------------
            # عرض الحالة
            # --------------------------------

            print(
                f"\r📊 {symbol} | "
                f"السعر {price:.8f} | "
                f"{'🟢' if net_profit >= 0 else '🔴'} "
                f"صافي {net_profit * 100:+.2f}% | "
                f"{profit_usdt:+.2f} USDT | "
                f"🛡️ وقف "
                f"{current_level * 100:+.0f}%",
                end="",
                flush=True
            )

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            print(
                f"\n⚠️ متابعة الصفقة: {e}"
            )

            time.sleep(10)


# ==========================================
# Main
# ==========================================

def main():

    print(
        "============================================="
    )

    print(
        "مضارب أبو سعود V2 🤖"
    )

    print(
        "BINANCE SPOT"
    )

    print(
        "============================================="
    )

    print(
        "💰 كامل رصيد USDT"
    )

    print(
        "⏱️ 15m + 1h"
    )

    print(
        "📈 EMA200 + Breakout + Volume"
    )

    print(
        "🛑 وقف حقيقي -2% صافي"
    )

    print(
        "🚀 رفع الوقف كل +1% صافي"
    )

    print(
        "🔄 إعادة الدخول بعد الخروج"
    )

    print(
        "============================================="
    )

    if not API_KEY or not API_SECRET:

        print(
            "❌ مفاتيح Binance غير موجودة"
        )

        return

    try:

        account = get_account()

        if not account.get(
            "canTrade"
        ):

            print(
                "❌ التداول غير مفعّل"
            )

            return

    except Exception as e:

        print(
            f"❌ فشل الاتصال: {e}"
        )

        return

    print(
        "✅ Binance متصل"
    )

    print(
        "✅ التداول مفعّل"
    )

    symbols = get_symbols()

    print(
        f"🪙 العملات: {len(symbols)}"
    )

    # ======================================
    # استرجاع صفقة سابقة
    # ======================================

    state = load_state()

    if state and state.get(
        "symbol"
    ):

        print(
            "\n🔄 استرجاع الصفقة السابقة..."
        )

        manage_position(
            state
        )

    # ======================================
    # الفحص المستمر
    # ======================================

    while True:

        for i, info in enumerate(
            symbols,
            1
        ):

            symbol = info[
                "symbol"
            ]

            print(
                f"\r🔎 فحص "
                f"{i}/{len(symbols)} | "
                f"{symbol}",
                end="",
                flush=True
            )

            signal, reason = (
                check_signal(
                    symbol
                )
            )

            if signal:

                print("")

                print(
                    "===================================="
                )

                print(
                    f"🔥 إشارة V2: {symbol}"
                )

                print(
                    f"✅ {reason}"
                )

                print(
                    "===================================="
                )

                usdt = get_usdt()

                if usdt < MIN_USDT:

                    print(
                        f"⚠️ الرصيد أقل من "
                        f"{MIN_USDT} USDT: "
                        f"{usdt:.2f}"
                    )

                    time.sleep(30)

                    continue

                trade_amount = (
                    usdt * 0.999
                )

                print(
                    f"💰 الشراء: "
                    f"{trade_amount:.2f} USDT"
                )

                try:

                    # -------------------------
                    # شراء
                    # -------------------------

                    order = market_buy(
                        symbol,
                        trade_amount
                    )

                    order["symbol"] = (
                        symbol
                    )

                    entry = (
                        get_entry_from_order(
                            order
                        )
                    )

                    executed_qty = float(
                        order.get(
                            "executedQty",
                            0
                        )
                    )

                    if executed_qty <= 0:

                        raise Exception(
                            "لم يتم تنفيذ كمية الشراء"
                        )

                    # نأخذ الرصيد الحقيقي
                    # بعد الشراء
                    asset = symbol.replace(
                        "USDT",
                        ""
                    )

                    actual_qty = (
                        get_asset_balance(
                            asset
                        )
                    )

                    if actual_qty > 0:

                        executed_qty = (
                            actual_qty
                        )

                    # -------------------------
                    # حفظ الصفقة
                    # -------------------------

                    state = {

                        "symbol": symbol,

                        "entry": entry,

                        "qty": executed_qty,

                        "step": info["step"],

                        "tick": info["tick"],

                        "invested": trade_amount,

                        "stop_level": INITIAL_STOP_NET,

                        "stop_order_id": None,

                        "start_time": time.time()
                    }

                    save_state(
                        state
                    )

                    print("")
                    print(
                        "🟢🟢🟢 تم فتح الصفقة 🟢🟢🟢"
                    )

                    print(
                        f"🪙 {symbol}"
                    )

                    print(
                        f"📍 Entry: "
                        f"{entry:.8f}"
                    )

                    print(
                        f"💰 المبلغ: "
                        f"{trade_amount:.2f} USDT"
                    )

                    print(
                        "🛑 وقف حقيقي: "
                        "-2% صافي"
                    )

                    print(
                        "🚀 كل +1% صافي "
                        "يرفع الوقف"
                    )

                    # -------------------------
                    # متابعة
                    # -------------------------

                    manage_position(
                        state
                    )

                    # بعد الخروج
                    # نبدأ دورة فحص جديدة
                    print(
                        "\n🔄 بدء فحص جديد..."
                    )

                    break

                except Exception as e:

                    print(
                        f"\n❌ فشل الصفقة: {e}"
                    )

            time.sleep(1)


if __name__ == "__main__":

    main()
