import os
import time
import json
import hmac
import hashlib
import urllib.parse
import threading
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify, render_template_string


# ============================================================
# مضارب أبو سعود 🤖
# Binance Spot + Auto Trading + Dashboard
#
# الاستراتيجية:
# 15m
# نزول 2% من إغلاق الشمعة السابقة -> شراء
# TP +2%
# SL -2%
#
# مهم:
# بعد الشراء يتم وضع OCO على Binance نفسها.
# لذلك TP/SL يستمران حتى لو توقف Render.
# ============================================================


API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

BASE = "https://api.binance.com"

TIMEFRAME = "15m"

DROP_PERCENT = 0.02
TP_PERCENT = 0.02
SL_PERCENT = 0.02

TRADE_USDT = 10.0

MIN_VOLUME = 1_000_000

DATA_FILE = "bot_data.json"


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

session = requests.Session()

lock = threading.Lock()


# ============================================================
# الحالة
# ============================================================

state = {
    "bot_running": True,
    "binance_connected": False,

    "balance": 0.0,
    "total_asset": 0.0,

    "current_trade": None,

    "today_profit": 0.0,
    "week_profit": 0.0,
    "month_profit": 0.0,
    "total_profit": 0.0,

    "winning_trades": 0,
    "losing_trades": 0,
    "total_trades": 0,

    "last_update": "",
    "last_signal": "",
    "error": ""
}


exchange_info = {}


# ============================================================
# حفظ البيانات
# ============================================================

def load_data():

    global state

    if not os.path.exists(DATA_FILE):
        print("ℹ️ لا يوجد ملف بيانات سابق")
        return

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)

        keys = [
            "today_profit",
            "week_profit",
            "month_profit",
            "total_profit",
            "winning_trades",
            "losing_trades",
            "total_trades",
            "current_trade"
        ]

        for key in keys:

            if key in old:
                state[key] = old[key]

        print("💾 تم تحميل بيانات البوت")

    except Exception as e:

        print("⚠️ تعذر تحميل البيانات:", e)


def save_data():

    try:

        data = {
            "today_profit": state["today_profit"],
            "week_profit": state["week_profit"],
            "month_profit": state["month_profit"],
            "total_profit": state["total_profit"],
            "winning_trades": state["winning_trades"],
            "losing_trades": state["losing_trades"],
            "total_trades": state["total_trades"],
            "current_trade": state["current_trade"]
        }

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("⚠️ خطأ حفظ البيانات:", e)


# ============================================================
# Binance Public
# ============================================================

def public_get(endpoint, params=None):

    r = session.get(
        BASE + endpoint,
        params=params,
        timeout=20
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text}"
        )

    return r.json()


# ============================================================
# Binance Signed
# ============================================================

def signed_request(method, endpoint, params=None):

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
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE + endpoint + "?" + query

    if method == "GET":

        r = session.get(
            url,
            headers=headers,
            timeout=20
        )

    elif method == "POST":

        r = session.post(
            url,
            headers=headers,
            timeout=20
        )

    elif method == "DELETE":

        r = session.delete(
            url,
            headers=headers,
            timeout=20
        )

    else:

        raise Exception(
            "HTTP method غير معروف"
        )

    if r.status_code != 200:

        raise Exception(
            f"Binance {r.status_code}: {r.text}"
        )

    return r.json()


# ============================================================
# اختبار اتصال Binance
# ============================================================

def test_binance():

    try:

        account = signed_request(
            "GET",
            "/api/v3/account"
        )

        if account:

            with lock:
                state["binance_connected"] = True
                state["error"] = ""

            print("🔗 Binance متصل ✅")

            return True

    except Exception as e:

        with lock:
            state["binance_connected"] = False
            state["error"] = str(e)

        print("❌ Binance غير متصل:")
        print(e)

    return False


# ============================================================
# معلومات العملات
# ============================================================

def load_exchange_info():

    global exchange_info

    print("📥 تحميل معلومات Binance...")

    data = public_get(
        "/api/v3/exchangeInfo"
    )

    exchange_info = {}

    for s in data["symbols"]:

        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s.get(
                "isSpotTradingAllowed",
                False
            )
        ):

            exchange_info[
                s["symbol"]
            ] = s

    print(
        f"✅ تم تحميل {len(exchange_info)} عملة"
    )


def get_symbol_filter(symbol, filter_type):

    info = exchange_info.get(symbol)

    if not info:
        return None

    for f in info["filters"]:

        if f["filterType"] == filter_type:
            return f

    return None


def get_step_size(symbol):

    f = get_symbol_filter(
        symbol,
        "LOT_SIZE"
    )

    if f:
        return float(f["stepSize"])

    return 0.000001


def get_tick_size(symbol):

    f = get_symbol_filter(
        symbol,
        "PRICE_FILTER"
    )

    if f:
        return float(f["tickSize"])

    return 0.000001


def round_quantity(symbol, quantity):

    step = Decimal(
        str(get_step_size(symbol))
    )

    q = Decimal(
        str(quantity)
    )

    rounded = (
        q / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return float(rounded)


def round_price(symbol, price):

    tick = Decimal(
        str(get_tick_size(symbol))
    )

    p = Decimal(
        str(price)
    )

    rounded = (
        p / tick
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * tick

    return float(rounded)


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
# الرصيد
# ============================================================

def get_balances():

    account = signed_request(
        "GET",
        "/api/v3/account"
    )

    balances = {}

    for x in account["balances"]:

        free = float(x["free"])
        locked = float(x["locked"])

        total = free + locked

        if total > 0:

            balances[
                x["asset"]
            ] = total

    return balances


def update_balance():

    try:

        balances = get_balances()

        usdt = balances.get(
            "USDT",
            0
        )

        total = usdt

        for asset, amount in balances.items():

            if asset == "USDT":
                continue

            symbol = asset + "USDT"

            if symbol not in exchange_info:
                continue

            try:

                price = get_price(
                    symbol
                )

                total += amount * price

            except:
                pass

        with lock:

            state["balance"] = round(
                usdt,
                4
            )

            state["total_asset"] = round(
                total,
                4
            )

            state["binance_connected"] = True

            state["last_update"] = (
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

    except Exception as e:

        with lock:

            state["binance_connected"] = False
            state["error"] = str(e)

        print(
            "❌ خطأ تحديث الرصيد:",
            e
        )


# ============================================================
# العملات فوق حجم 1M
# ============================================================

def get_symbols():

    tickers = public_get(
        "/api/v3/ticker/24hr"
    )

    symbols = []

    for x in tickers:

        symbol = x["symbol"]

        volume = float(
            x.get(
                "quoteVolume",
                0
            )
        )

        if (
            symbol.endswith("USDT")
            and volume >= MIN_VOLUME
            and symbol in exchange_info
        ):

            symbols.append(
                symbol
            )

    return symbols


# ============================================================
# الشموع
# ============================================================

def get_last_klines(symbol):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": 3
        }
    )


# ============================================================
# إشارة النزول 2%
# ============================================================

def check_signal(symbol):

    try:

        candles = get_last_klines(
            symbol
        )

        if len(candles) < 2:
            return None

        previous_close = float(
            candles[-2][4]
        )

        current_low = float(
            candles[-1][3]
        )

        entry = (
            previous_close *
            (1 - DROP_PERCENT)
        )

        if current_low <= entry:

            return {
                "symbol": symbol,
                "entry": entry,
                "previous_close":
                    previous_close
            }

    except Exception:
        pass

    return None


# ============================================================
# شراء Market
# ============================================================

def market_buy(symbol):

    print(
        f"🟢 شراء {symbol} "
        f"بمبلغ {TRADE_USDT} USDT"
    )

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty":
                f"{TRADE_USDT:.2f}",
            "newOrderRespType":
                "FULL"
        }
    )

    return order


# ============================================================
# بيع Market احتياطي
# ============================================================

def market_sell(
    symbol,
    quantity
):

    quantity = round_quantity(
        symbol,
        quantity
    )

    if quantity <= 0:
        return None

    print(
        f"🔴 بيع احتياطي {symbol}"
    )

    return signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity":
                f"{quantity:.8f}",
            "newOrderRespType":
                "FULL"
        }
    )


# ============================================================
# إنشاء OCO على Binance
#
# فوق = TP
# تحت = SL
# ============================================================

def place_oco(
    symbol,
    quantity,
    tp,
    sl
):

    quantity = round_quantity(
        symbol,
        quantity
    )

    tp = round_price(
        symbol,
        tp
    )

    sl = round_price(
        symbol,
        sl
    )

    # stop limit يكون أسفل stop
    stop_limit = round_price(
        symbol,
        sl * 0.999
    )

    print(
        f"🛡️ وضع OCO: "
        f"{symbol} | "
        f"TP {tp} | "
        f"SL {sl}"
    )

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity":
            f"{quantity:.8f}",

        "aboveType":
            "LIMIT_MAKER",

        "abovePrice":
            f"{tp:.8f}",

        "belowType":
            "STOP_LOSS_LIMIT",

        "belowPrice":
            f"{stop_limit:.8f}",

        "belowStopPrice":
            f"{sl:.8f}",

        "belowTimeInForce":
            "GTC",

        "newOrderRespType":
            "RESULT"
    }

    result = signed_request(
        "POST",
        "/api/v3/orderList/oco",
        params
    )

    print(
        "✅ OCO تم وضعه على Binance"
    )

    return result


# ============================================================
# الحصول على أوامر OCO المفتوحة
# ============================================================

def get_open_oco():

    return signed_request(
        "GET",
        "/api/v3/openOrderList"
    )


# ============================================================
# استعادة الصفقة
# ============================================================

def restore_trade():

    print()
    print("🔄 فحص الصفقات بعد التشغيل...")

    # --------------------------------------------------------
    # 1. إذا عندنا current_trade محفوظ
    # --------------------------------------------------------

    with lock:
        saved_trade = state[
            "current_trade"
        ]

    if saved_trade:

        symbol = saved_trade.get(
            "symbol"
        )

        try:

            balances = get_balances()

            asset = symbol.replace(
                "USDT",
                ""
            )

            quantity = balances.get(
                asset,
                0
            )

            if quantity > 0:

                saved_trade[
                    "quantity"
                ] = quantity

                with lock:
                    state[
                        "current_trade"
                    ] = saved_trade

                print(
                    f"♻️ استعادة الصفقة: "
                    f"{symbol}"
                )

                return True

        except Exception as e:

            print(
                "⚠️ فشل استعادة الصفقة:",
                e
            )

    # --------------------------------------------------------
    # 2. فحص OCO الموجود على Binance
    # --------------------------------------------------------

    try:

        open_lists = get_open_oco()

        if open_lists:

            for item in open_lists:

                symbol = item.get(
                    "symbol"
                )

                if not symbol:
                    continue

                if not symbol.endswith(
                    "USDT"
                ):
                    continue

                asset = symbol.replace(
                    "USDT",
                    ""
                )

                balances = get_balances()

                quantity = balances.get(
                    asset,
                    0
                )

                if quantity <= 0:
                    continue

                # نحاول استخراج أسعار OCO
                tp = None
                sl = None

                try:

                    orders = item.get(
                        "orders",
                        []
                    )

                    for o in orders:

                        order_id = o.get(
                            "orderId"
                        )

                        if not order_id:
                            continue

                        order = signed_request(
                            "GET",
                            "/api/v3/order",
                            {
                                "symbol":
                                    symbol,
                                "orderId":
                                    order_id
                            }
                        )

                        otype = order.get(
                            "type"
                        )

                        if otype == "LIMIT_MAKER":

                            tp = float(
                                order["price"]
                            )

                        if otype == "STOP_LOSS_LIMIT":

                            sl = float(
                                order["stopPrice"]
                            )

                except:
                    pass

                price = get_price(
                    symbol
                )

                if not tp:
                    tp = price * (
                        1 + TP_PERCENT
                    )

                if not sl:
                    sl = price * (
                        1 - SL_PERCENT
                    )

                # الدخول التقريبي من TP/2%
                entry = price

                if tp > 0:
                    entry = tp / (
                        1 + TP_PERCENT
                    )

                trade = {
                    "symbol": symbol,
                    "entry": entry,
                    "price": price,
                    "tp": tp,
                    "sl": sl,
                    "quantity": quantity,
                    "profit_pct":
                        ((price-entry)/entry)
                        * 100
                        if entry else 0,
                    "profit_usdt":
                        ((price-entry)
                        * quantity),
                    "time":
                        datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                }

                with lock:
                    state[
                        "current_trade"
                    ] = trade

                save_data()

                print(
                    f"♻️ تم استعادة OCO: "
                    f"{symbol}"
                )

                return True

    except Exception as e:

        print(
            "⚠️ فشل فحص OCO:",
            e
        )

    print(
        "ℹ️ لا توجد صفقة مفتوحة"
    )

    with lock:
        state[
            "current_trade"
        ] = None

    save_data()

    return False


# ============================================================
# تسجيل نتيجة الصفقة
# ============================================================

def register_trade_result(
    profit
):

    with lock:

        state[
            "total_profit"
        ] += profit

        state[
            "total_trades"
        ] += 1

        if profit >= 0:

            state[
                "winning_trades"
            ] += 1

        else:

            state[
                "losing_trades"
            ] += 1

        state[
            "today_profit"
        ] += profit

        state[
            "week_profit"
        ] += profit

        state[
            "month_profit"
        ] += profit

    save_data()


# ============================================================
# مراقبة الصفقة
# ============================================================

def manage_trade():

    while True:

        try:

            with lock:
                trade = state[
                    "current_trade"
                ]

            if not trade:

                time.sleep(3)
                continue

            symbol = trade[
                "symbol"
            ]

            price = get_price(
                symbol
            )

            entry = float(
                trade["entry"]
            )

            tp = float(
                trade["tp"]
            )

            sl = float(
                trade["sl"]
            )

            quantity = float(
                trade["quantity"]
            )

            profit_pct = (
                (price-entry)
                / entry
            ) * 100

            profit_usdt = (
                price-entry
            ) * quantity

            with lock:

                if state[
                    "current_trade"
                ]:

                    state[
                        "current_trade"
                    ]["price"] = price

                    state[
                        "current_trade"
                    ]["profit_pct"] = (
                        profit_pct
                    )

                    state[
                        "current_trade"
                    ]["profit_usdt"] = (
                        profit_usdt
                    )

            # ------------------------------------------------
            # لا نبيع يدويًا هنا إذا كان OCO موجود.
            #
            # Binance هي التي تنفذ TP/SL.
            # نحن فقط نراقب.
            # ------------------------------------------------

            if price >= tp:

                print(
                    f"🎯 {symbol} وصل TP"
                )

            elif price <= sl:

                print(
                    f"🛑 {symbol} وصل SL"
                )

        except Exception as e:

            with lock:
                state[
                    "error"
                ] = str(e)

        time.sleep(2)


# ============================================================
# فحص هل ما زالت الصفقة موجودة
# ============================================================

def verify_current_trade():

    while True:

        try:

            with lock:
                trade = state[
                    "current_trade"
                ]

            if not trade:

                time.sleep(10)
                continue

            symbol = trade[
                "symbol"
            ]

            asset = symbol.replace(
                "USDT",
                ""
            )

            balances = get_balances()

            quantity = balances.get(
                asset,
                0
            )

            # إذا لم تعد العملة موجودة
            # فغالبًا OCO نفذ البيع
            if quantity <= 0:

                print(
                    f"✅ انتهت صفقة {symbol}"
                )

                # نحتاج حساب نتيجة تقريبية
                entry = float(
                    trade["entry"]
                )

                price = get_price(
                    symbol
                )

                old_qty = float(
                    trade["quantity"]
                )

                profit = (
                    price-entry
                ) * old_qty

                register_trade_result(
                    profit
                )

                with lock:

                    state[
                        "current_trade"
                    ] = None

                    state[
                        "last_signal"
                    ] = (
                        f"{symbol} "
                        f"✅ انتهت الصفقة"
                    )

                    state[
                        "error"
                    ] = ""

                save_data()

            else:

                with lock:

                    if state[
                        "current_trade"
                    ]:

                        state[
                            "current_trade"
                        ]["quantity"] = (
                            quantity
                        )

        except Exception as e:

            with lock:
                state[
                    "error"
                ] = str(e)

        time.sleep(10)


# ============================================================
# البحث عن فرص
# ============================================================

def scanner():

    while True:

        try:

            with lock:
                active = state[
                    "current_trade"
                ]

            if active:

                time.sleep(10)
                continue

            symbols = get_symbols()

            print(
                f"🔎 فحص {len(symbols)} عملة..."
            )

            for index, symbol in enumerate(
                symbols,
                start=1
            ):

                with lock:

                    if state[
                        "current_trade"
                    ]:
                        break

                signal = check_signal(
                    symbol
                )

                if not signal:
                    continue

                print()
                print(
                    f"🎯 إشارة شراء: "
                    f"{symbol}"
                )

                print(
                    f"📉 السعر السابق: "
                    f"{signal['previous_close']}"
                )

                print(
                    f"🟢 مستوى الدخول: "
                    f"{signal['entry']}"
                )

                update_balance()

                with lock:
                    balance = state[
                        "balance"
                    ]

                if balance < TRADE_USDT:

                    print(
                        "❌ الرصيد غير كافي"
                    )

                    continue

                # ------------------------------------------------
                # شراء كامل مبلغ الصفقة
                # ------------------------------------------------

                try:

                    order = market_buy(
                        symbol
                    )

                    fills = order.get(
                        "fills",
                        []
                    )

                    total_qty = 0
                    total_cost = 0

                    for fill in fills:

                        qty = float(
                            fill["qty"]
                        )

                        price = float(
                            fill["price"]
                        )

                        total_qty += qty

                        total_cost += (
                            qty * price
                        )

                    # أحيانًا FULL response
                    # قد لا يحتوي fills بالطريقة المتوقعة
                    if total_qty <= 0:

                        total_qty = float(
                            order.get(
                                "executedQty",
                                0
                            )
                        )

                        total_cost = float(
                            order.get(
                                "cummulativeQuoteQty",
                                0
                            )
                        )

                    if total_qty <= 0:

                        raise Exception(
                            "شراء تم إرساله لكن الكمية المنفذة = 0"
                        )

                    entry = (
                        total_cost /
                        total_qty
                    )

                    tp = entry * (
                        1 + TP_PERCENT
                    )

                    sl = entry * (
                        1 - SL_PERCENT
                    )

                    # ------------------------------------------------
                    # ضع OCO على Binance
                    # ------------------------------------------------

                    try:

                        place_oco(
                            symbol,
                            total_qty,
                            tp,
                            sl
                        )

                    except Exception as oco_error:

                        print(
                            "❌ فشل وضع OCO:"
                        )

                        print(
                            oco_error
                        )

                        # إذا فشل OCO لا نترك الصفقة بدون حماية
                        print(
                            "🛡️ محاولة بيع احتياطي..."
                        )

                        try:

                            market_sell(
                                symbol,
                                total_qty
                            )

                            print(
                                "✅ تم إغلاق الصفقة "
                                "لأن OCO فشل"
                            )

                        except Exception as sell_error:

                            print(
                                "🚨 خطر: فشل OCO "
                                "وفشل البيع:"
                            )

                            print(
                                sell_error
                            )

                        continue

                    trade = {
                        "symbol": symbol,
                        "entry": entry,
                        "price": entry,
                        "tp": tp,
                        "sl": sl,
                        "quantity": total_qty,
                        "profit_pct": 0,
                        "profit_usdt": 0,
                        "time":
                            datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                    }

                    with lock:

                        state[
                            "current_trade"
                        ] = trade

                        state[
                            "last_signal"
                        ] = (
                            f"{symbol} "
                            f"🟢 شراء تلقائي "
                            f"10 USDT"
                        )

                        state[
                            "error"
                        ] = ""

                    save_data()

                    print(
                        f"✅ الصفقة دخلت: "
                        f"{symbol}"
                    )

                    print(
                        f"💰 المبلغ: "
                        f"{TRADE_USDT} USDT"
                    )

                    print(
                        f"📦 الكمية: "
                        f"{total_qty}"
                    )

                    print(
                        f"🎯 TP: {tp}"
                    )

                    print(
                        f"🛑 SL: {sl}"
                    )

                    break

                except Exception as e:

                    print(
                        "❌ فشل تنفيذ الشراء:"
                    )

                    print(e)

                    with lock:
                        state[
                            "error"
                        ] = str(e)

            time.sleep(10)

        except Exception as e:

            print(
                "❌ خطأ في Scanner:"
            )

            print(e)

            with lock:
                state[
                    "error"
                ] = str(e)

            time.sleep(15)


# ============================================================
# Dashboard
# ============================================================

HTML = r"""
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
font-family:Arial,Tahoma;
background:#07111f;
color:#fff;
}

.container{
max-width:1200px;
margin:auto;
padding:15px;
}

.header{
background:#102d4d;
padding:20px;
border-radius:20px;
margin-bottom:15px;
}

h1{
margin:0;
font-size:26px;
}

.status{
margin-top:10px;
color:#9fb5cc;
}

.badge{
display:inline-block;
padding:7px 12px;
border-radius:20px;
background:#123b2a;
color:#40e49a;
}

.grid{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:10px;
}

.card,
.panel{
background:#0d1b2d;
border:1px solid #1c344f;
border-radius:16px;
padding:16px;
}

.panel{
margin-top:12px;
}

.label{
color:#8fa6bd;
font-size:13px;
}

.value{
font-size:21px;
font-weight:bold;
margin-top:7px;
}

.green{
color:#35df91;
}

.red{
color:#ff6475;
}

.blue{
color:#55b8ff;
}

.trade{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:10px;
}

.item{
background:#101f33;
padding:12px;
border-radius:12px;
}

@media(max-width:800px){

.grid{
grid-template-columns:
repeat(2,1fr);
}

.trade{
grid-template-columns:
repeat(2,1fr);
}

}

@media(max-width:500px){

.grid,
.trade{
grid-template-columns:1fr;
}

}

</style>

</head>

<body>

<div class="container">

<div class="header">

<h1>🤖 مضارب أبو سعود</h1>

<div class="status">

<span id="connection"
class="badge">
جاري الاتصال...
</span>

&nbsp;

<span id="bot"
class="badge">
البوت يعمل
</span>

</div>

<div id="update"
class="status">
—
</div>

</div>


<div class="grid">

<div class="card">
<div class="label">💰 رصيد USDT</div>
<div id="balance" class="value">—</div>
</div>

<div class="card">
<div class="label">💼 قيمة الحساب</div>
<div id="asset" class="value">—</div>
</div>

<div class="card">
<div class="label">📅 ربح اليوم</div>
<div id="today" class="value">—</div>
</div>

<div class="card">
<div class="label">📆 ربح الأسبوع</div>
<div id="week" class="value">—</div>
</div>

<div class="card">
<div class="label">🗓️ ربح الشهر</div>
<div id="month" class="value">—</div>
</div>

<div class="card">
<div class="label">🏆 إجمالي الربح</div>
<div id="totalprofit" class="value">—</div>
</div>

<div class="card">
<div class="label">🟢 الرابحة</div>
<div id="wins" class="value green">—</div>
</div>

<div class="card">
<div class="label">🔴 الخاسرة</div>
<div id="losses" class="value red">—</div>
</div>

<div class="card">
<div class="label">🎯 نسبة النجاح</div>
<div id="winrate" class="value blue">—</div>
</div>

<div class="card">
<div class="label">🔢 إجمالي الصفقات</div>
<div id="trades" class="value">—</div>
</div>

</div>


<div class="panel">

<h2>📈 الصفقة الحالية</h2>

<div id="noTrade">
لا توجد صفقة مفتوحة
</div>

<div id="tradeBox"
style="display:none">

<div class="trade">

<div class="item">
<div class="label">العملة</div>
<div id="symbol" class="value">—</div>
</div>

<div class="item">
<div class="label">الدخول</div>
<div id="entry" class="value">—</div>
</div>

<div class="item">
<div class="label">السعر</div>
<div id="price" class="value">—</div>
</div>

<div class="item">
<div class="label">🎯 الهدف</div>
<div id="tp" class="value green">—</div>
</div>

<div class="item">
<div class="label">🛑 الوقف</div>
<div id="sl" class="value red">—</div>
</div>

<div class="item">
<div class="label">الربح %</div>
<div id="profitpct" class="value">—</div>
</div>

<div class="item">
<div class="label">الربح USDT</div>
<div id="profitusdt" class="value">—</div>
</div>

<div class="item">
<div class="label">وقت الدخول</div>
<div id="tradetime" class="value">—</div>
</div>

</div>

</div>

</div>


<div class="panel">

<h2>🤖 حالة البوت</h2>

<div id="signal">—</div>

<div id="error"
class="red"
style="margin-top:10px">
</div>

</div>

</div>


<script>

function money(x){

return Number(x || 0)
.toLocaleString(
'en-US',
{
minimumFractionDigits:2,
maximumFractionDigits:6
}
);

}


async function update(){

try{

const r =
await fetch('/api/status');

const s =
await r.json();


document.getElementById(
'connection'
).textContent =
s.binance_connected
? '🟢 Binance متصل'
: '🔴 Binance غير متصل';


document.getElementById(
'bot'
).textContent =
s.bot_running
? '🟢 البوت يعمل'
: '🔴 البوت متوقف';


document.getElementById(
'balance'
).textContent =
money(s.balance)+' USDT';


document.getElementById(
'asset'
).textContent =
money(s.total_asset)+' USDT';


document.getElementById(
'today'
).textContent =
money(s.today_profit)+' USDT';


document.getElementById(
'week'
).textContent =
money(s.week_profit)+' USDT';


document.getElementById(
'month'
).textContent =
money(s.month_profit)+' USDT';


document.getElementById(
'totalprofit'
).textContent =
money(s.total_profit)+' USDT';


document.getElementById(
'wins'
).textContent =
s.winning_trades;


document.getElementById(
'losses'
).textContent =
s.losing_trades;


document.getElementById(
'trades'
).textContent =
s.total_trades;


const total =
s.winning_trades +
s.losing_trades;


document.getElementById(
'winrate'
).textContent =
total
? (
s.winning_trades /
total *
100
).toFixed(2)+'%'
: '0%';


document.getElementById(
'update'
).textContent =
'آخر تحديث: '+
new Date()
.toLocaleTimeString();


document.getElementById(
'signal'
).textContent =
s.last_signal ||
'لا توجد إشارة';


document.getElementById(
'error'
).textContent =
s.error || '';


if(s.current_trade){

document.getElementById(
'noTrade'
).style.display='none';

document.getElementById(
'tradeBox'
).style.display='block';

const t =
s.current_trade;


document.getElementById(
'symbol'
).textContent =
t.symbol;


document.getElementById(
'entry'
).textContent =
money(t.entry);


document.getElementById(
'price'
).textContent =
money(t.price);


document.getElementById(
'tp'
).textContent =
money(t.tp);


document.getElementById(
'sl'
).textContent =
money(t.sl);


document.getElementById(
'profitpct'
).textContent =
Number(
t.profit_pct || 0
).toFixed(2)+'%';


document.getElementById(
'profitusdt'
).textContent =
money(
t.profit_usdt
)+' USDT';


document.getElementById(
'tradetime'
).textContent =
t.time;

}else{

document.getElementById(
'noTrade'
).style.display='block';

document.getElementById(
'tradeBox'
).style.display='none';

}

}catch(e){

console.log(e);

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


# ============================================================
# Routes
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    update_balance()

    with lock:

        return jsonify(
            state
        )


# ============================================================
# تشغيل Threads
# ============================================================

def start_threads():

    print()
    print("=" * 60)
    print("🤖 مضارب أبو سعود")
    print("=" * 60)
    print("📉 نزول 2% -> شراء")
    print("🎯 TP +2%")
    print("🛑 SL -2%")
    print("⏱️ 15 دقيقة")
    print("💰 مبلغ الصفقة:", TRADE_USDT)
    print("🛡️ حماية Binance OCO")
    print("=" * 60)
    print()

    load_data()

    # -----------------------------------------------
    # تحميل معلومات العملات
    # -----------------------------------------------

    try:

        load_exchange_info()

    except Exception as e:

        print(
            "❌ فشل تحميل exchangeInfo:"
        )

        print(e)

    # -----------------------------------------------
    # اختبار Binance
    # -----------------------------------------------

    if test_binance():

        update_balance()

        # -------------------------------------------
        # استعادة الصفقة
        # -------------------------------------------

        restore_trade()

    # -----------------------------------------------
    # Threads
    # -----------------------------------------------

    threading.Thread(
        target=manage_trade,
        daemon=True
    ).start()

    threading.Thread(
        target=verify_current_trade,
        daemon=True
    ).start()

    threading.Thread(
        target=scanner,
        daemon=True
    ).start()


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    start_threads()

    port = int(
        os.getenv(
            "PORT",
            "8080"
        )
    )

    print(
        f"🌐 PORT = {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
