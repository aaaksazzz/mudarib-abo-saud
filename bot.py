import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

STATE_FILE = os.path.expanduser("~/mybot/state.json")
HISTORY_FILE = os.path.expanduser("~/mybot/trade_history.json")

# ==================================================
# الإعدادات
# ==================================================

# الوقف الأول
INITIAL_STOP = -0.02

# رفع الوقف كل 1% صافي
PROFIT_STEP = 0.01

# رسوم تقريبية: 0.1% شراء + 0.1% بيع
FEE_RATE = 0.001

# فحص الصفقة كل كم ثانية
CHECK_SECONDS = 5

# أقل رصيد للدخول
MIN_USDT = 5


session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY or ""
})


# ==================================================
# Binance Public
# ==================================================

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

            time.sleep(5)


# ==================================================
# Binance Signed
# ==================================================

def signed(method, path, params=None):

    params = dict(params or {})

    params["timestamp"] = int(
        time.time() * 1000
    )

    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(
        params
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    try:

        r = session.request(
            method,
            BASE + path,
            params=params,
            timeout=15
        )

        try:
            data = r.json()
        except Exception:
            data = {
                "raw": r.text
            }

        if r.status_code >= 400:

            raise Exception(
                json.dumps(
                    data,
                    ensure_ascii=False
                )
            )

        return data

    except Exception as e:

        raise Exception(
            str(e)
        )


# ==================================================
# حفظ الحالة
# ==================================================

def save_state(state):

    folder = os.path.dirname(
        STATE_FILE
    )

    os.makedirs(
        folder,
        exist_ok=True
    )

    temp = STATE_FILE + ".tmp"

    with open(
        temp,
        "w"
    ) as f:

        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp,
        STATE_FILE
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


# ==================================================
# سجل الصفقات
# ==================================================

def save_trade(trade):

    folder = os.path.dirname(
        HISTORY_FILE
    )

    os.makedirs(
        folder,
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

    history.append(
        trade
    )

    with open(
        HISTORY_FILE,
        "w"
    ) as f:

        json.dump(
            history[-100:],
            f,
            indent=2,
            ensure_ascii=False
        )


# ==================================================
# Exchange Info
# ==================================================

def get_symbols():

    data = public(
        "/api/v3/exchangeInfo"
    )

    result = []

    for item in data["symbols"]:

        if (
            item["status"] != "TRADING"
            or item["quoteAsset"] != "USDT"
            or not item.get(
                "isSpotTradingAllowed",
                False
            )
        ):
            continue

        filters = {
            x["filterType"]: x
            for x in item["filters"]
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

            "symbol": item["symbol"],

            "step": lot["stepSize"],

            "min_qty": lot["minQty"],

            "tick": price_filter["tickSize"]

        })

    return result


# ==================================================
# Klines
# ==================================================

def get_klines(
    symbol,
    interval
):

    return public(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 220
        }
    )


# ==================================================
# EMA
# ==================================================

def ema(
    values,
    period
):

    k = 2 / (period + 1)

    result = values[0]

    for price in values[1:]:

        result = (
            price * k
            + result * (1 - k)
        )

    return result


# ==================================================
# استراتيجية V2
# ==================================================

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

        volume15 = [
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
            sum(volume15[-21:-1])
            / 20
        )

        volume_ratio = (
            volume15[-1]
            / avg_volume
            if avg_volume > 0
            else 0
        )

        move = (
            price / close15[-2]
        ) - 1

        # 1H فوق EMA200
        if close1h[-1] <= ema200_1h:

            return False, "1H تحت EMA200"

        # 15M فوق EMA200
        if close15[-1] <= ema200_15:

            return False, "15M تحت EMA200"

        # اختراق المقاومة
        if price <= resistance:

            return False, "لم يكسر المقاومة"

        # حجم 1.5x
        if volume15[-1] < avg_volume * 1.5:

            return False, (
                f"الحجم {volume_ratio:.2f}x"
            )

        # حركة أقل من 0.5%
        if move < 0.005:

            return False, (
                f"الحركة {move * 100:.2f}%"
            )

        # حركة أكبر من 4%
        if move > 0.04:

            return False, (
                f"الحركة {move * 100:.2f}%"
            )

        return True, "🔥 كل شروط V2 مكتملة"

    except Exception as e:

        return False, (
            f"خطأ: {str(e)[:100]}"
        )


# ==================================================
# الحساب
# ==================================================

def get_account():

    return signed(
        "GET",
        "/api/v3/account"
    )


def get_usdt():

    data = get_account()

    for balance in data["balances"]:

        if balance["asset"] == "USDT":

            return float(
                balance["free"]
            )

    return 0.0


def get_asset_balance(asset):

    data = get_account()

    for balance in data["balances"]:

        if balance["asset"] == asset:

            return float(
                balance["free"]
            )

    return 0.0


# ==================================================
# السعر
# ==================================================

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


# ==================================================
# التقريب
# ==================================================

def floor_decimal(
    value,
    step
):

    value = Decimal(
        str(value)
    )

    step = Decimal(
        str(step)
    )

    return float(
        (
            value / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step
    )


def format_decimal(value):

    return format(
        Decimal(
            str(value)
        ),
        "f"
    )


# ==================================================
# شراء Market
# ==================================================

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
            "quoteOrderQty": f"{amount:.2f}",
            "newOrderRespType": "FULL"
        }
    )


# ==================================================
# سعر الدخول
# ==================================================

def get_entry(order):

    fills = order.get(
        "fills",
        []
    )

    if fills:

        qty = sum(
            float(x["qty"])
            for x in fills
        )

        value = sum(
            float(x["price"])
            * float(x["qty"])
            for x in fills
        )

        if qty > 0:

            return value / qty

    executed = float(
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

    if executed > 0:

        return quote / executed

    return get_price(
        order["symbol"]
    )


# ==================================================
# صافي الربح
# ==================================================

def net_profit(
    entry,
    price
):

    gross = (
        price / entry
    ) - 1

    # شراء + بيع
    net = (
        (1 + gross)
        * (1 - FEE_RATE)
        / (1 + FEE_RATE)
    ) - 1

    return net


# ==================================================
# السعر المطلوب لقفل صافي معين
# ==================================================

def price_for_net(
    entry,
    target_net
):

    ratio = (
        (1 + target_net)
        * (1 + FEE_RATE)
        / (1 - FEE_RATE)
    )

    return entry * ratio


# ==================================================
# وضع STOP_LOSS حقيقي
# ==================================================

def place_stop(
    symbol,
    quantity,
    stop_price,
    tick,
    step
):

    quantity = floor_decimal(
        quantity,
        step
    )

    stop_price = floor_decimal(
        stop_price,
        tick
    )

    if quantity <= 0:

        raise Exception(
            "الكمية بعد التقريب = 0"
        )

    print("")
    print(
        "🛡️ محاولة وضع أمر STOP_LOSS"
    )

    print(
        f"🪙 {symbol}"
    )

    print(
        f"📦 الكمية: {quantity}"
    )

    print(
        f"🛑 السعر: {stop_price}"
    )

    response = signed(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": format_decimal(
                quantity
            ),
            "stopPrice": format_decimal(
                stop_price
            ),
            "newOrderRespType": "RESULT"
        }
    )

    print("")
    print(
        "📡 رد Binance:"
    )

    print(
        json.dumps(
            response,
            indent=2,
            ensure_ascii=False
        )
    )

    order_id = response.get(
        "orderId"
    )

    status = response.get(
        "status"
    )

    if not order_id:

        raise Exception(
            "Binance لم يرجع orderId"
        )

    if status and status != "NEW":

        raise Exception(
            f"أمر الوقف ليس NEW: {status}"
        )

    print("")
    print(
        f"✅ STOP_LOSS موجود في Binance"
    )

    print(
        f"🆔 Order ID: {order_id}"
    )

    return response


# ==================================================
# الاستعلام عن الأمر
# ==================================================

def query_order(
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


# ==================================================
# إلغاء الأمر
# ==================================================

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


# ==================================================
# سعر تنفيذ البيع
# ==================================================

def get_exit_price(order):

    qty = float(
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

    if qty > 0 and quote > 0:

        return quote / qty

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


# ==================================================
# تسجيل الصفقة
# ==================================================

def finish_trade(
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

    net = net_profit(
        entry,
        exit_price
    )

    profit_usdt = (
        invested * net
    )

    result = (
        "ربح"
        if net >= 0
        else "خسارة"
    )

    trade = {

        "symbol": state["symbol"],

        "entry": entry,

        "exit": exit_price,

        "net_percent": round(
            net * 100,
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
        f"{'🟢' if net >= 0 else '🔴'} "
        f"انتهت الصفقة"
    )

    print(
        f"🪙 {state['symbol']}"
    )

    print(
        f"📊 الصافي: "
        f"{net * 100:+.2f}%"
    )

    print(
        f"💰 النتيجة: "
        f"{profit_usdt:+.2f} USDT"
    )

    print(
        f"📌 السبب: {reason}"
    )

    print(
        "===================================="
    )


# ==================================================
# متابعة الصفقة
# ==================================================

def manage_position(state):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    step = state["step"]

    tick = state["tick"]

    invested = float(
        state["invested"]
    )

    # ==============================================
    # نحصل على الكمية الحالية الحقيقية
    # ==============================================

    asset = symbol.replace(
        "USDT",
        ""
    )

    quantity = get_asset_balance(
        asset
    )

    quantity = floor_decimal(
        quantity,
        step
    )

    if quantity <= 0:

        print(
            "❌ لا توجد كمية للبيع"
        )

        clear_state()

        return

    state["quantity"] = quantity

    # ==============================================
    # مستوى الوقف الحالي
    # ==============================================

    stop_level = float(
        state.get(
            "stop_level",
            INITIAL_STOP
        )
    )

    stop_order_id = state.get(
        "stop_order_id"
    )

    # ==============================================
    # إذا فيه أمر محفوظ، نتحقق منه
    # ==============================================

    if stop_order_id:

        try:

            old_order = query_order(
                symbol,
                stop_order_id
            )

            old_status = old_order.get(
                "status"
            )

            if old_status == "FILLED":

                exit_price = (
                    get_exit_price(
                        old_order
                    )
                )

                if exit_price is None:

                    exit_price = get_price(
                        symbol
                    )

                finish_trade(
                    state,
                    exit_price,
                    "STOP_LOSS من Binance"
                )

                clear_state()

                return

            if old_status != "NEW":

                stop_order_id = None

        except Exception as e:

            print(
                f"\n⚠️ فحص الوقف: {e}"
            )

            stop_order_id = None

    # ==============================================
    # إنشاء الوقف الأول
    # ==============================================

    if not stop_order_id:

        stop_price = price_for_net(
            entry,
            stop_level
        )

        # لازم الوقف يكون أقل من السعر الحالي
        current_price = get_price(
            symbol
        )

        if stop_price >= current_price:

            stop_price = current_price * 0.995

        stop_order = place_stop(
            symbol,
            quantity,
            stop_price,
            tick,
            step
        )

        stop_order_id = (
            stop_order["orderId"]
        )

        state["stop_order_id"] = (
            stop_order_id
        )

        state["stop_level"] = (
            stop_level
        )

        state["stop_price"] = (
            stop_price
        )

        save_state(
            state
        )

    print("")
    print(
        "===================================="
    )

    print(
        "🟢 الصفقة تحت الحماية"
    )

    print(
        f"🪙 {symbol}"
    )

    print(
        f"📍 Entry: {entry:.8f}"
    )

    print(
        f"🛡️ الوقف: "
        f"{stop_level * 100:+.0f}% صافي"
    )

    print(
        "🚀 رفع الوقف كل +1% صافي"
    )

    print(
        "===================================="
    )

    # ==============================================
    # المتابعة
    # ==============================================

    while True:

        try:

            # --------------------------------------
            # فحص أمر Binance
            # --------------------------------------

            order = query_order(
                symbol,
                stop_order_id
            )

            status = order.get(
                "status"
            )

            if status == "FILLED":

                exit_price = (
                    get_exit_price(
                        order
                    )
                )

                if exit_price is None:

                    exit_price = get_price(
                        symbol
                    )

                finish_trade(
                    state,
                    exit_price,
                    "وقف تلقائي من Binance"
                )

                clear_state()

                print(
                    "\n🔄 الرجوع لفحص صفقة جديدة..."
                )

                return

            # --------------------------------------
            # السعر
            # --------------------------------------

            price = get_price(
                symbol
            )

            net = net_profit(
                entry,
                price
            )

            profit_usdt = (
                invested * net
            )

            # --------------------------------------
            # حساب مستوى الوقف الجديد
            # --------------------------------------

            if net >= PROFIT_STEP:

                level_number = int(
                    net / PROFIT_STEP
                )

                new_level = (
                    level_number
                    * PROFIT_STEP
                )

                # لا ننزل الوقف
                if new_level > stop_level:

                    new_stop_price = (
                        price_for_net(
                            entry,
                            new_level
                        )
                    )

                    # تأكد أن الوقف تحت السعر الحالي
                    if new_stop_price < price:

                        print("")
                        print(
                            "===================================="
                        )

                        print(
                            f"🚀 وصل صافي "
                            f"{new_level * 100:.0f}%"
                        )

                        print(
                            f"🛡️ رفع الوقف من "
                            f"{stop_level * 100:+.0f}% "
                            f"إلى "
                            f"{new_level * 100:+.0f}%"
                        )

                        # ----------------------------------
                        # أولاً نضع الوقف الجديد
                        # ثم نحذف القديم
                        # ----------------------------------

                        new_order = place_stop(
                            symbol,
                            quantity,
                            new_stop_price,
                            tick,
                            step
                        )

                        new_order_id = (
                            new_order["orderId"]
                        )

                        # تأكد أنه NEW
                        check_new = query_order(
                            symbol,
                            new_order_id
                        )

                        if check_new.get(
                            "status"
                        ) != "NEW":

                            raise Exception(
                                "الوقف الجديد لم يصبح NEW"
                            )

                        # ----------------------------------
                        # الآن نحذف القديم
                        # ----------------------------------

                        try:

                            cancel_order(
                                symbol,
                                stop_order_id
                            )

                        except Exception as e:

                            print(
                                f"\n⚠️ فشل حذف الوقف القديم: {e}"
                            )

                            # نحاول حذف الجديد حتى
                            # لا يكون عندنا وقفين
                            try:

                                cancel_order(
                                    symbol,
                                    new_order_id
                                )

                            except Exception:
                                pass

                            raise

                        # ----------------------------------
                        # حفظ الجديد
                        # ----------------------------------

                        stop_order_id = (
                            new_order_id
                        )

                        stop_level = (
                            new_level
                        )

                        state[
                            "stop_order_id"
                        ] = stop_order_id

                        state[
                            "stop_level"
                        ] = stop_level

                        state[
                            "stop_price"
                        ] = new_stop_price

                        save_state(
                            state
                        )

                        print(
                            f"✅ الوقف الجديد فعّال"
                        )

                        print(
                            f"🆔 Order ID: "
                            f"{new_order_id}"
                        )

                        print(
                            f"🛡️ Stop: "
                            f"{new_stop_price:.8f}"
                        )

                        print(
                            "===================================="
                        )

            # --------------------------------------
            # العرض
            # --------------------------------------

            print(
                f"\r📊 {symbol} | "
                f"السعر {price:.8f} | "
                f"صافي {net * 100:+.2f}% | "
                f"{profit_usdt:+.2f} USDT | "
                f"🛡️ الوقف "
                f"{stop_level * 100:+.0f}%",
                end="",
                flush=True
            )

            time.sleep(
                CHECK_SECONDS
            )

        except Exception as e:

            print(
                f"\n⚠️ متابعة الصفقة: {e}"
            )

            time.sleep(5)


# ==================================================
# Main
# ==================================================

def main():

    print("")
    print(
        "============================================="
    )

    print(
        "        مضارب أبو سعود V2 🤖"
    )

    print(
        "        BINANCE SPOT"
    )

    print(
        "============================================="
    )

    print(
        "📈 استراتيجية V2"
    )

    print(
        "⏱️ 15M + 1H"
    )

    print(
        "📊 EMA200 + Breakout + Volume"
    )

    print(
        "🛑 وقف تلقائي حقيقي على Binance"
    )

    print(
        "🚀 كل +1% صافي يرفع الوقف"
    )

    print(
        "🔄 بعد الخروج يبحث عن صفقة جديدة"
    )

    print(
        "============================================="
    )

    # ----------------------------------------------
    # المفاتيح
    # ----------------------------------------------

    if not API_KEY:

        print(
            "❌ BINANCE_API_KEY غير موجود"
        )

        return

    if not API_SECRET:

        print(
            "❌ BINANCE_API_SECRET غير موجود"
        )

        return

    # ----------------------------------------------
    # اتصال
    # ----------------------------------------------

    try:

        account = get_account()

        print(
            "✅ Binance متصل"
        )

        print(
            f"💰 يمكن التداول: "
            f"{account.get('canTrade')}"
        )

        if not account.get(
            "canTrade"
        ):

            print(
                "❌ API لا يملك صلاحية التداول"
            )

            return

    except Exception as e:

        print(
            f"❌ فشل الاتصال: {e}"
        )

        return

    # ----------------------------------------------
    # العملات
    # ----------------------------------------------

    symbols = get_symbols()

    print(
        f"🪙 عدد العملات: "
        f"{len(symbols)}"
    )

    # ----------------------------------------------
    # استرجاع صفقة
    # ----------------------------------------------

    saved = load_state()

    if saved and saved.get(
        "symbol"
    ):

        print("")
        print(
            "🔄 تم العثور على صفقة محفوظة"
        )

        manage_position(
            saved
        )

    # ----------------------------------------------
    # الفحص المستمر
    # ----------------------------------------------

    while True:

        trade_finished = False

        for index, info in enumerate(
            symbols,
            1
        ):

            symbol = info[
                "symbol"
            ]

            print(
                f"\r🔎 فحص "
                f"{index}/{len(symbols)} "
                f"| {symbol}",
                end="",
                flush=True
            )

            signal, reason = (
                check_signal(
                    symbol
                )
            )

            if not signal:

                time.sleep(0.2)

                continue

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

            # ------------------------------------------
            # الرصيد
            # ------------------------------------------

            usdt = get_usdt()

            if usdt < MIN_USDT:

                print(
                    f"⚠️ الرصيد: "
                    f"{usdt:.2f} USDT"
                )

                time.sleep(30)

                continue

            # ------------------------------------------
            # كامل الرصيد تقريباً
            # ------------------------------------------

            amount = (
                usdt * 0.999
            )

            print(
                f"💰 شراء: "
                f"{amount:.2f} USDT"
            )

            try:

                # --------------------------------------
                # شراء
                # --------------------------------------

                order = market_buy(
                    symbol,
                    amount
                )

                order["symbol"] = (
                    symbol
                )

                entry = get_entry(
                    order
                )

                asset = symbol.replace(
                    "USDT",
                    ""
                )

                quantity = (
                    get_asset_balance(
                        asset
                    )
                )

                quantity = floor_decimal(
                    quantity,
                    info["step"]
                )

                if quantity <= 0:

                    raise Exception(
                        "لم نجد كمية بعد الشراء"
                    )

                print("")
                print(
                    "🟢 تم فتح الصفقة"
                )

                print(
                    f"🪙 {symbol}"
                )

                print(
                    f"📍 الدخول: "
                    f"{entry:.8f}"
                )

                print(
                    f"📦 الكمية: "
                    f"{quantity}"
                )

                # --------------------------------------
                # حفظ الحالة قبل الوقف
                # --------------------------------------

                state = {

                    "symbol": symbol,

                    "entry": entry,

                    "quantity": quantity,

                    "step": info["step"],

                    "tick": info["tick"],

                    "invested": amount,

                    "stop_level": INITIAL_STOP,

                    "stop_order_id": None,

                    "start_time": time.time()

                }

                save_state(
                    state
                )

                # --------------------------------------
                # وضع الوقف الحقيقي
                # --------------------------------------

                manage_position(
                    state
                )

                trade_finished = True

                print("")
                print(
                    "🔄 انتهت الصفقة — إعادة الفحص من البداية"
                )

                break

            except Exception as e:

                print("")
                print(
                    f"❌ فشل تنفيذ الصفقة: {e}"
                )

                # إذا اشترى لكن فشل وضع الوقف
                # نخلي الحالة محفوظة
                # ولا نفتح صفقة ثانية

                saved = load_state()

                if saved and saved.get(
                    "symbol"
                ) == symbol:

                    print(
                        "⚠️ توجد صفقة محفوظة، لن يتم فتح صفقة أخرى."
                    )

                    manage_position(
                        saved
                    )

                    trade_finished = True

                    break

            time.sleep(0.5)

        if trade_finished:

            # تحديث قائمة العملات
            try:

                symbols = get_symbols()

            except Exception:
                pass

            continue

        print(
            "\n🔄 انتهت دورة الفحص — إعادة من البداية..."
        )

        time.sleep(2)


if __name__ == "__main__":

    main()
