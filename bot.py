import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string
from threading import Thread


# =========================================================
# إعدادات
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

# عمولة 0.1% لكل جهة
FEE_RATE = Decimal(os.getenv("BINANCE_FEE_RATE", "0.001"))

EMA_PERIOD = 200

# لازم يكون أكبر من 1%
MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند +1% صافي
PROTECTION_START_NET = Decimal("1.0")

# التأمين يبعد 0.50% عن أعلى سعر
TRAIL_PERCENT = Decimal("0.50")

# استخدام 99.9% من الرصيد
BALANCE_USAGE = Decimal("0.999")

POSITION_CHECK_INTERVAL = 5
SCAN_INTERVAL = 60

REQUEST_DELAY = 0.12

STATE_FILE = "bot_data.json"


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

session = requests.Session()

exchange_info_cache = None
exchange_info_time = 0

symbol_rules_cache = {}

account_cache = None
account_cache_time = 0


# =========================================================
# حالة البوت
# =========================================================

state = {
    "status": "بدء التشغيل",

    "active_trade": None,

    "scan_number": 0,

    "last_scan": None,
    "last_action": "",
    "last_error": "",

    "best_candidate": "",
    "candidate_change": "",

    "candidate_count": 0,
    "ema_pass_count": 0,

    "last_update": None
}


# =========================================================
# الوقت
# =========================================================

def now():
    return time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# حفظ الحالة
# =========================================================

def save_state():

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"⚠️ فشل حفظ الحالة: {e}"
        )


def load_state():

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            old = json.load(f)

        state.update(old)

        print(
            "♻️ تم استرجاع بيانات البوت"
        )

    except FileNotFoundError:

        print(
            "ℹ️ لا يوجد ملف بيانات سابق"
        )

    except Exception as e:

        print(
            f"⚠️ فشل قراءة الحالة: {e}"
        )


# =========================================================
# طلب Binance
# =========================================================

def binance_request(
    method,
    endpoint,
    params=None,
    signed=False
):

    if params is None:
        params = {}

    params = dict(params)

    if signed:

        params["timestamp"] = int(
            time.time() * 1000
        )

        query = urllib.parse.urlencode(
            params
        )

        signature = hmac.new(
            API_SECRET.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

        query += (
            "&signature="
            + signature
        )

    else:

        query = urllib.parse.urlencode(
            params
        )

    url = BASE_URL + endpoint

    headers = {}

    if API_KEY:

        headers[
            "X-MBX-APIKEY"
        ] = API_KEY

    for attempt in range(5):

        try:

            if method == "GET":

                response = session.get(
                    url,
                    params=urllib.parse.parse_qs(
                        query
                    ),
                    headers=headers,
                    timeout=20
                )

            elif method == "POST":

                response = session.post(
                    url,
                    params=urllib.parse.parse_qs(
                        query
                    ),
                    headers=headers,
                    timeout=20
                )

            elif method == "DELETE":

                response = session.delete(
                    url,
                    params=urllib.parse.parse_qs(
                        query
                    ),
                    headers=headers,
                    timeout=20
                )

            else:

                raise Exception(
                    "طريقة الطلب غير مدعومة"
                )

            # 429
            if response.status_code == 429:

                wait_time = min(
                    15,
                    2 ** attempt
                )

                print(
                    f"⚠️ Binance 429 "
                    f"→ انتظار {wait_time} ثانية"
                )

                time.sleep(
                    wait_time
                )

                continue

            if response.status_code >= 400:

                raise Exception(
                    f"Binance "
                    f"{response.status_code}: "
                    f"{response.text}"
                )

            time.sleep(
                REQUEST_DELAY
            )

            return response.json()

        except requests.RequestException as e:

            if attempt >= 4:

                raise

            wait_time = min(
                10,
                2 ** attempt
            )

            print(
                f"⚠️ مشكلة اتصال → "
                f"إعادة المحاولة بعد "
                f"{wait_time} ثانية"
            )

            time.sleep(
                wait_time
            )

    raise Exception(
        "فشل الاتصال مع Binance"
    )


# =========================================================
# Exchange Info
# =========================================================

def get_exchange_info():

    global exchange_info_cache
    global exchange_info_time
    global symbol_rules_cache

    current_time = time.time()

    if (
        exchange_info_cache is not None
        and
        current_time - exchange_info_time < 3600
    ):

        return exchange_info_cache

    data = binance_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    exchange_info_cache = data
    exchange_info_time = current_time

    symbol_rules_cache = {}

    for item in data["symbols"]:

        if (
            item["status"] == "TRADING"
            and
            item["quoteAsset"] == "USDT"
            and
            item.get(
                "isSpotTradingAllowed",
                False
            )
        ):

            filters = {}

            for f in item["filters"]:

                filters[
                    f["filterType"]
                ] = f

            symbol_rules_cache[
                item["symbol"]
            ] = filters

    print(
        f"📚 تم تحميل "
        f"{len(symbol_rules_cache)} عملة USDT"
    )

    return data


def get_usdt_symbols():

    get_exchange_info()

    return list(
        symbol_rules_cache.keys()
    )


# =========================================================
# Account
# =========================================================

def get_account(
    force=False
):

    global account_cache
    global account_cache_time

    current_time = time.time()

    if (
        not force
        and
        account_cache is not None
        and
        current_time - account_cache_time < 5
    ):

        return account_cache

    account_cache = binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )

    account_cache_time = current_time

    return account_cache


def get_balance_from_account(
    account,
    asset
):

    for balance in account["balances"]:

        if balance["asset"] == asset:

            free = Decimal(
                balance["free"]
            )

            locked = Decimal(
                balance["locked"]
            )

            return free, locked

    return (
        Decimal("0"),
        Decimal("0")
    )


# =========================================================
# كل الأسعار - طلب واحد فقط
# =========================================================

def get_all_prices():

    data = binance_request(
        "GET",
        "/api/v3/ticker/price"
    )

    prices = {}

    for item in data:

        try:

            prices[
                item["symbol"]
            ] = Decimal(
                item["price"]
            )

        except Exception:

            continue

    return prices


# =========================================================
# تحديد الصفقة المفتوحة
# =========================================================

def find_open_position():

    """
    مهم جدًا:

    لا نفحص myTrades لكل العملات.

    1- طلب account واحد.
    2- نأخذ الأرصدة غير USDT.
    3- نجيب أسعار كل العملات بطلب واحد.
    4- نختار أكبر رصيد فعلي بقيمة USDT.
    5- نطلب myTrades لهذه العملة فقط.
    """

    try:

        account = get_account(
            force=True
        )

        symbols = set(
            symbol_rules_cache.keys()
        )

        balances = account[
            "balances"
        ]

        candidates = []

        # ---------------------------------------------
        # الأرصدة
        # ---------------------------------------------

        for balance in balances:

            asset = balance["asset"]

            if asset == "USDT":
                continue

            free = Decimal(
                balance["free"]
            )

            locked = Decimal(
                balance["locked"]
            )

            total = (
                free + locked
            )

            if total <= 0:
                continue

            symbol = (
                asset + "USDT"
            )

            if symbol not in symbols:
                continue

            candidates.append(
                {
                    "asset": asset,
                    "symbol": symbol,
                    "quantity": total
                }
            )

        if not candidates:

            return None

        # ---------------------------------------------
        # الأسعار كلها بطلب واحد
        # ---------------------------------------------

        prices = get_all_prices()

        valid = []

        for item in candidates:

            symbol = item["symbol"]

            price = prices.get(
                symbol
            )

            if price is None:
                continue

            value = (
                item["quantity"]
                * price
            )

            item["price"] = price
            item["value"] = value

            # تجاهل الغبار الصغير
            if value >= Decimal("5"):

                valid.append(item)

        if not valid:

            return None

        # أكبر مركز فعلي
        valid.sort(
            key=lambda x: x["value"],
            reverse=True
        )

        selected = valid[0]

        symbol = selected[
            "symbol"
        ]

        quantity = selected[
            "quantity"
        ]

        print(
            f"🔎 المركز الموجود: "
            f"{symbol} | "
            f"القيمة تقريبًا "
            f"{selected['value']:.2f} USDT"
        )

        # ---------------------------------------------
        # myTrades لعملة واحدة فقط
        # ---------------------------------------------

        trades = binance_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 50
            },
            signed=True
        )

        buys = [
            trade
            for trade in trades
            if trade.get("isBuyer")
        ]

        if not buys:

            print(
                f"⚠️ يوجد رصيد {symbol} "
                f"لكن لا يوجد شراء معروف"
            )

            return None

        # نحسب متوسط سعر آخر مجموعة شراء
        # بطريقة بسيطة من آخر الصفقات
        latest_buy = buys[-1]

        entry = Decimal(
            latest_buy["price"]
        )

        print(
            f"♻️ صفقة مفتوحة مكتشفة: "
            f"{symbol}"
        )

        return {

            "symbol": symbol,

            "entry": str(entry),

            "qty": str(quantity),

            "highest": str(entry),

            "current_price": str(
                selected["price"]
            ),

            "gross_profit": "0",

            "net_profit": "0",

            "protection_active": False,

            "protection_price": None,

            "protection_order_id": None,

            "opened_at": now()
        }

    except Exception as e:

        print(
            f"⚠️ فشل تحديد الصفقة: "
            f"{e}"
        )

        state[
            "last_error"
        ] = str(e)

        return None


# =========================================================
# Klines
# =========================================================

def get_klines(
    symbol,
    interval,
    limit=210
):

    return binance_request(
        "GET",
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# =========================================================
# EMA200
# =========================================================

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


def price_above_ema200(
    symbol,
    interval
):

    klines = get_klines(
        symbol,
        interval,
        210
    )

    closes = [
        Decimal(k[4])
        for k in klines
    ]

    if len(closes) < EMA_PERIOD:

        return (
            False,
            None,
            None
        )

    price = closes[-1]

    ema = calculate_ema(
        closes,
        EMA_PERIOD
    )

    if ema is None:

        return (
            False,
            price,
            None
        )

    return (
        price > ema,
        price,
        ema
    )


# =========================================================
# تغير 15 دقيقة
# =========================================================

def get_15m_change(symbol):

    klines = get_klines(
        symbol,
        "15m",
        2
    )

    if len(klines) < 2:

        return None

    previous = Decimal(
        klines[-2][4]
    )

    current = Decimal(
        klines[-1][4]
    )

    if previous <= 0:

        return None

    change = (
        (
            current - previous
        )
        / previous
    ) * Decimal("100")

    return change


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    symbols = get_usdt_symbols()

    candidates = []

    state[
        "candidate_count"
    ] = 0

    state[
        "ema_pass_count"
    ] = 0

    state[
        "best_candidate"
    ] = ""

    state[
        "candidate_change"
    ] = ""

    print(
        f"🔎 فحص {len(symbols)} "
        f"عملة USDT..."
    )

    # -----------------------------------------------------
    # أول فلتر:
    # أكبر من 1% فقط
    # -----------------------------------------------------

    for index, symbol in enumerate(
        symbols,
        1
    ):

        try:

            change = get_15m_change(
                symbol
            )

            if change is None:
                continue

            # =============================================
            # شرط المستخدم:
            #
            # 1.00% ❌
            # 1.01% ✅
            # 2.00% ✅
            # =============================================

            if change <= MIN_CHANGE_15M:

                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "change": change
                }
            )

            state[
                "candidate_count"
            ] += 1

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

        if index % 100 == 0:

            print(
                f"📊 تم فحص "
                f"{index}/"
                f"{len(symbols)}"
            )

    # -----------------------------------------------------
    # ترتيب من الأعلى للأقل
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    print(
        f"📈 مرشحون فوق 1%: "
        f"{len(candidates)}"
    )

    # -----------------------------------------------------
    # EMA 15m + 5m + 1m
    # -----------------------------------------------------

    for candidate in candidates:

        symbol = candidate[
            "symbol"
        ]

        change = candidate[
            "change"
        ]

        print(
            f"🔍 {symbol} | "
            f"15m +{change:.2f}%"
        )

        try:

            # 15 دقيقة
            ok_15m, _, _ = (
                price_above_ema200(
                    symbol,
                    "15m"
                )
            )

            if not ok_15m:
                continue

            # 5 دقائق
            ok_5m, _, _ = (
                price_above_ema200(
                    symbol,
                    "5m"
                )
            )

            if not ok_5m:
                continue

            # دقيقة
            ok_1m, _, _ = (
                price_above_ema200(
                    symbol,
                    "1m"
                )
            )

            if not ok_1m:
                continue

            state[
                "ema_pass_count"
            ] += 1

            # لأن القائمة مرتبة من
            # أعلى تغير إلى الأقل
            # فهذا هو الأقوى
            state[
                "best_candidate"
            ] = symbol

            state[
                "candidate_change"
            ] = (
                f"{change:.2f}%"
            )

            state[
                "last_action"
            ] = (
                f"🔥 الأقوى {symbol} "
                f"| +{change:.2f}%"
            )

            print(
                f"🔥🔥 الاختيار النهائي: "
                f"{symbol} | "
                f"+{change:.2f}%"
            )

            return candidate

        except Exception as e:

            print(
                f"⚠️ خطأ EMA "
                f"{symbol}: {e}"
            )

    return None


# =========================================================
# السعر
# =========================================================

def get_price(symbol):

    data = binance_request(
        "GET",
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return Decimal(
        data["price"]
    )


# =========================================================
# قواعد العملة
# =========================================================

def floor_step(
    value,
    step
):

    if step <= 0:

        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def get_symbol_rules(symbol):

    get_exchange_info()

    filters = symbol_rules_cache.get(
        symbol,
        {}
    )

    lot = filters.get(
        "LOT_SIZE"
    )

    price_filter = filters.get(
        "PRICE_FILTER"
    )

    min_notional = filters.get(
        "MIN_NOTIONAL"
    )

    return {

        "step_size":
            Decimal(
                lot["stepSize"]
            )
            if lot
            else Decimal("0.000001"),

        "min_qty":
            Decimal(
                lot["minQty"]
            )
            if lot
            else Decimal("0"),

        "tick_size":
            Decimal(
                price_filter["tickSize"]
            )
            if price_filter
            else Decimal("0.00000001"),

        "min_notional":
            Decimal(
                min_notional["minNotional"]
            )
            if min_notional
            else Decimal("5")
    }


# =========================================================
# شراء
# =========================================================

def market_buy(symbol):

    account = get_account(
        force=True
    )

    free_usdt, _ = (
        get_balance_from_account(
            account,
            "USDT"
        )
    )

    amount = (
        free_usdt
        * BALANCE_USAGE
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    if amount <= 0:

        raise Exception(
            "رصيد USDT غير كافٍ"
        )

    print(
        f"💰 USDT المتاح: "
        f"{free_usdt}"
    )

    print(
        f"🟢 شراء {symbol} "
        f"بقيمة {amount} USDT"
    )

    order = binance_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,

            "side": "BUY",

            "type": "MARKET",

            "quoteOrderQty": str(
                amount
            ),

            "newOrderRespType": "FULL"
        },
        signed=True
    )

    executed_qty = Decimal(
        order["executedQty"]
    )

    quote_qty = Decimal(
        order[
            "cummulativeQuoteQty"
        ]
    )

    if executed_qty <= 0:

        raise Exception(
            "لم يتم تنفيذ الشراء"
        )

    entry = (
        quote_qty
        / executed_qty
    )

    return {

        "symbol": symbol,

        "entry": str(entry),

        "qty": str(
            executed_qty
        ),

        "highest": str(entry),

        "current_price": str(entry),

        "gross_profit": "0",

        "net_profit": "0",

        "protection_active": False,

        "protection_price": None,

        "protection_order_id": None,

        "opened_at": now()
    }


# =========================================================
# إلغاء أمر
# =========================================================

def cancel_order(
    symbol,
    order_id
):

    try:

        return binance_request(
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            },
            signed=True
        )

    except Exception as e:

        print(
            f"⚠️ فشل إلغاء الأمر: "
            f"{e}"
        )

        return None


# =========================================================
# إنشاء حماية
# =========================================================

def create_protection(
    symbol,
    qty,
    stop_price
):

    rules = get_symbol_rules(
        symbol
    )

    qty = floor_step(
        qty,
        rules["step_size"]
    )

    stop_price = floor_step(
        stop_price,
        rules["tick_size"]
    )

    if qty < rules["min_qty"]:

        raise Exception(
            "الكمية أقل من الحد الأدنى"
        )

    order = binance_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,

            "side": "SELL",

            "type": "STOP_LOSS",

            "quantity": str(qty),

            "stopPrice": str(
                stop_price
            ),

            "newOrderRespType":
                "RESULT"
        },
        signed=True
    )

    return order


# =========================================================
# تأمين الربح
# =========================================================

def update_protection(
    trade,
    current_price,
    net_profit
):

    symbol = trade[
        "symbol"
    ]

    entry = Decimal(
        trade["entry"]
    )

    qty = Decimal(
        trade["qty"]
    )

    highest = Decimal(
        trade["highest"]
    )

    # -----------------------------------------------------
    # تحديث أعلى سعر
    # -----------------------------------------------------

    if current_price > highest:

        highest = current_price

        trade[
            "highest"
        ] = str(highest)

    # -----------------------------------------------------
    # قبل +1% صافي
    # لا حماية
    # -----------------------------------------------------

    if net_profit < PROTECTION_START_NET:

        return

    # -----------------------------------------------------
    # تأمين 0.50% خلف الأعلى
    # -----------------------------------------------------

    trailing_stop = (
        highest
        * (
            Decimal("1")
            -
            TRAIL_PERCENT
            / Decimal("100")
        )
    )

    # -----------------------------------------------------
    # التعادل بعد العمولة
    # -----------------------------------------------------

    break_even = (
        entry
        * (
            Decimal("1")
            +
            FEE_RATE
            * Decimal("2")
        )
    )

    minimum_stop = (
        break_even
        * Decimal("1.001")
    )

    new_stop = max(
        trailing_stop,
        minimum_stop
    )

    old_stop = None

    if trade.get(
        "protection_price"
    ):

        old_stop = Decimal(
            trade[
                "protection_price"
            ]
        )

    # لا ننزل الحماية
    if (
        old_stop is not None
        and
        new_stop <= old_stop
    ):

        return

    old_order_id = (
        trade.get(
            "protection_order_id"
        )
    )

    try:

        # ننشئ الجديدة أولًا
        new_order = create_protection(
            symbol,
            qty,
            new_stop
        )

        new_order_id = new_order[
            "orderId"
        ]

        # بعدها نحذف القديمة
        if old_order_id:

            cancel_order(
                symbol,
                old_order_id
            )

        trade[
            "protection_order_id"
        ] = new_order_id

        trade[
            "protection_price"
        ] = str(
            new_stop
        )

        trade[
            "protection_active"
        ] = True

        state[
            "last_action"
        ] = (
            f"🛡️ رفع التأمين "
            f"{symbol} → "
            f"{new_stop}"
        )

        print(
            f"🛡️ تأمين جديد: "
            f"{symbol} → "
            f"{new_stop}"
        )

    except Exception as e:

        state[
            "last_error"
        ] = str(e)

        print(
            f"🚨 فشل الحماية: "
            f"{e}"
        )


# =========================================================
# إدارة الصفقة
# =========================================================

def update_trade():

    trade = state.get(
        "active_trade"
    )

    if not trade:

        return False

    symbol = trade[
        "symbol"
    ]

    entry = Decimal(
        trade["entry"]
    )

    current = get_price(
        symbol
    )

    # -----------------------------------------------------
    # الربح الإجمالي
    # -----------------------------------------------------

    gross = (
        (
            current - entry
        )
        / entry
    ) * Decimal("100")

    # -----------------------------------------------------
    # العمولة
    # -----------------------------------------------------

    total_fee_percent = (
        FEE_RATE
        * Decimal("2")
        * Decimal("100")
    )

    # -----------------------------------------------------
    # صافي الربح
    # -----------------------------------------------------

    net = (
        gross
        - total_fee_percent
    )

    trade[
        "current_price"
    ] = str(current)

    trade[
        "gross_profit"
    ] = str(gross)

    trade[
        "net_profit"
    ] = str(net)

    # -----------------------------------------------------
    # تحديث الحماية
    # -----------------------------------------------------

    update_protection(
        trade,
        current,
        net
    )

    state[
        "last_update"
    ] = now()

    print(
        f"📊 {symbol} | "
        f"السعر {current} | "
        f"الصافي {net:.2f}% | "
        f"الأعلى {trade['highest']}"
    )

    # -----------------------------------------------------
    # فحص هل الصفقة أغلقت
    # -----------------------------------------------------

    try:

        account = get_account(
            force=True
        )

        asset = symbol.replace(
            "USDT",
            ""
        )

        free, locked = (
            get_balance_from_account(
                account,
                asset
            )
        )

        total = (
            free + locked
        )

        if total <= 0:

            print(
                f"✅ الصفقة أغلقت: "
                f"{symbol}"
            )

            state[
                "last_action"
            ] = (
                f"✅ إغلاق {symbol}"
            )

            state[
                "active_trade"
            ] = None

            save_state()

            return False

    except Exception as e:

        print(
            f"⚠️ فشل فحص إغلاق "
            f"{symbol}: {e}"
        )

    save_state()

    return True


# =========================================================
# محرك التداول
# =========================================================

def trading_loop():

    print(
        "🚀 بدأ محرك التداول"
    )

    while True:

        try:

            # =================================================
            # 1️⃣ صفقة محفوظة؟
            # =================================================

            if state.get(
                "active_trade"
            ):

                symbol = state[
                    "active_trade"
                ]["symbol"]

                state[
                    "status"
                ] = "إدارة صفقة"

                print(
                    f"📌 إدارة الصفقة: "
                    f"{symbol}"
                )

                update_trade()

                time.sleep(
                    POSITION_CHECK_INTERVAL
                )

                continue

            # =================================================
            # 2️⃣ فحص الصفقة الموجودة في Binance
            # =================================================

            print(
                "🔍 فحص الصفقة المفتوحة أولًا..."
            )

            recovered = (
                find_open_position()
            )

            if recovered:

                state[
                    "active_trade"
                ] = recovered

                state[
                    "status"
                ] = "إدارة صفقة"

                state[
                    "last_action"
                ] = (
                    f"♻️ استكمال "
                    f"{recovered['symbol']}"
                )

                state[
                    "last_error"
                ] = ""

                save_state()

                continue

            # =================================================
            # 3️⃣ ما فيه صفقة
            # =================================================

            print(
                "🔎 لا توجد صفقة مفتوحة"
            )

            state[
                "status"
            ] = "فحص السوق"

            state[
                "scan_number"
            ] += 1

            state[
                "last_scan"
            ] = now()

            state[
                "last_error"
            ] = ""

            # =================================================
            # 4️⃣ فحص السوق
            # =================================================

            candidate = scan_market()

            # =================================================
            # 5️⃣ الدخول
            # =================================================

            if candidate:

                symbol = candidate[
                    "symbol"
                ]

                change = candidate[
                    "change"
                ]

                print(
                    f"🔥 أفضل عملة: "
                    f"{symbol} | "
                    f"+{change:.2f}%"
                )

                try:

                    trade = market_buy(
                        symbol
                    )

                    state[
                        "active_trade"
                    ] = trade

                    state[
                        "status"
                    ] = "إدارة صفقة"

                    state[
                        "last_action"
                    ] = (
                        f"🟢 دخول {symbol} "
                        f"| 15m +"
                        f"{change:.2f}%"
                    )

                    state[
                        "last_error"
                    ] = ""

                    save_state()

                    print(
                        f"🟢 تم الدخول "
                        f"في {symbol}"
                    )

                    continue

                except Exception as e:

                    state[
                        "last_error"
                    ] = str(e)

                    print(
                        f"🚨 فشل الدخول: "
                        f"{e}"
                    )

            else:

                state[
                    "last_action"
                ] = (
                    "⏳ لا توجد فرصة مطابقة"
                )

                print(
                    "⏳ لا توجد فرصة مطابقة"
                )

            save_state()

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

            print(
                f"🚨 خطأ المحرك: "
                f"{e}"
            )

            save_state()

            time.sleep(10)


# =========================================================
# لوحة المتابعة
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

body {
    margin: 0;
    padding: 18px;
    background: #101010;
    color: white;
    font-family: Arial, sans-serif;
}

.container {
    max-width: 700px;
    margin: auto;
}

h1 {
    font-size: 27px;
    margin-bottom: 20px;
}

.card {
    background: #1c1c1c;
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 15px;
}

.row {
    padding: 10px 0;
    border-bottom: 1px solid #333;
}

.row:last-child {
    border-bottom: none;
}

.label {
    color: #999;
}

.value {
    font-size: 19px;
    margin-top: 5px;
}

</style>

</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود V3</h1>

<div class="card">

<div class="row">
<div class="label">الحالة</div>
<div class="value" id="status">...</div>
</div>

<div class="row">
<div class="label">الصفقة</div>
<div class="value" id="symbol">...</div>
</div>

<div class="row">
<div class="label">سعر الدخول</div>
<div class="value" id="entry">...</div>
</div>

<div class="row">
<div class="label">السعر الحالي</div>
<div class="value" id="price">...</div>
</div>

<div class="row">
<div class="label">صافي الربح</div>
<div class="value" id="profit">...</div>
</div>

<div class="row">
<div class="label">أعلى سعر</div>
<div class="value" id="highest">...</div>
</div>

<div class="row">
<div class="label">تأمين الربح</div>
<div class="value" id="protection">...</div>
</div>

</div>


<div class="card">

<div class="row">
<div class="label">رقم الفحص</div>
<div class="value" id="scan">...</div>
</div>

<div class="row">
<div class="label">المرشحون فوق 1%</div>
<div class="value" id="candidates">...</div>
</div>

<div class="row">
<div class="label">أفضل عملة</div>
<div class="value" id="candidate">...</div>
</div>

<div class="row">
<div class="label">تغير 15 دقيقة</div>
<div class="value" id="change">...</div>
</div>

<div class="row">
<div class="label">اجتازت EMA</div>
<div class="value" id="ema">...</div>
</div>

<div class="row">
<div class="label">آخر إجراء</div>
<div class="value" id="action">...</div>
</div>

<div class="row">
<div class="label">آخر خطأ</div>
<div class="value" id="error">...</div>
</div>

<div class="row">
<div class="label">آخر تحديث</div>
<div class="value" id="update">...</div>
</div>

</div>

</div>


<script>

async function refresh() {

    try {

        const response =
            await fetch("/api/status");

        const data =
            await response.json();

        document.getElementById(
            "status"
        ).innerText =
            data.status || "-";

        document.getElementById(
            "scan"
        ).innerText =
            data.scan_number || "0";

        document.getElementById(
            "candidates"
        ).innerText =
            data.candidate_count || "0";

        document.getElementById(
            "candidate"
        ).innerText =
            data.best_candidate || "-";

        document.getElementById(
            "change"
        ).innerText =
            data.candidate_change || "-";

        document.getElementById(
            "ema"
        ).innerText =
            data.ema_pass_count || "0";

        document.getElementById(
            "action"
        ).innerText =
            data.last_action || "-";

        document.getElementById(
            "error"
        ).innerText =
            data.last_error || "لا يوجد";

        document.getElementById(
            "update"
        ).innerText =
            data.last_update || "-";


        const trade =
            data.active_trade;


        if (trade) {

            document.getElementById(
                "symbol"
            ).innerText =
                trade.symbol || "-";

            document.getElementById(
                "entry"
            ).innerText =
                trade.entry || "-";

            document.getElementById(
                "price"
            ).innerText =
                trade.current_price || "-";

            document.getElementById(
                "profit"
            ).innerText =
                (
                    trade.net_profit || "0"
                ) + "%";

            document.getElementById(
                "highest"
            ).innerText =
                trade.highest || "-";

            document.getElementById(
                "protection"
            ).innerText =
                trade.protection_price
                || "غير مفعّل";

        } else {

            document.getElementById(
                "symbol"
            ).innerText =
                "لا توجد صفقة";

            document.getElementById(
                "entry"
            ).innerText = "-";

            document.getElementById(
                "price"
            ).innerText = "-";

            document.getElementById(
                "profit"
            ).innerText = "-";

            document.getElementById(
                "highest"
            ).innerText = "-";

            document.getElementById(
                "protection"
            ).innerText = "-";
        }

    }

    catch(error) {

        console.log(error);

    }

}

refresh();

setInterval(
    refresh,
    5000
);

</script>

</body>

</html>
"""


# =========================================================
# Routes
# =========================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    return jsonify(state)


# =========================================================
# Web Server
# =========================================================

def start_web():

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    load_state()

    try:

        if (
            not API_KEY
            or not API_SECRET
        ):

            print(
                "🚨 مفاتيح Binance غير موجودة"
            )

        else:

            get_exchange_info()

    except Exception as e:

        print(
            f"🚨 فشل Binance عند البداية: "
            f"{e}"
        )

    Thread(
        target=start_web,
        daemon=True
    ).start()

    trading_loop()
