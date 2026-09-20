# ============================================================
# مضارب أبو سعود V8 LOCK 🤖
# Binance Spot + Dashboard
#
# الاستراتيجية:
# 15m change > +1%
# السعر فوق EMA200 في:
# 15m + 5m + 1m
# اختيار أعلى تغير من العملات المؤهلة
#
# إدارة:
# صفقة واحدة فقط
# POSITION LOCK أثناء الصفقة
# لا يوجد Market Scan أثناء الصفقة
# استرجاع الصفقة بعد إعادة التشغيل
# حساب ربح الصفقة من سعر الدخول الحقيقي
# حماية عند +1% وترتفع كل +1%
# ============================================================

import os
import time
import hmac
import hashlib
import urllib.parse
import requests
import threading

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify

# ============================================================
# Binance
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

REQUEST_TIMEOUT = 15

session = requests.Session()

session.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-V8"
})

# ============================================================
# الاستراتيجية
# ============================================================

EMA_PERIOD = 200

TIMEFRAME_CHANGE = "15m"

MIN_CHANGE_15M = 1.0

EMA_TIMEFRAMES = [
    "15m",
    "5m",
    "1m"
]

# ============================================================
# حماية الربح
# ============================================================

PROTECTION_START = 1.0

PROTECTION_STEP = 1.0

TRAILING_PERCENT = 0.50

# ============================================================
# التداول
# ============================================================

BUY_PERCENT = 99.9

MIN_POSITION_USDT = 2.0

POSITION_CHECK_SECONDS = 15

SCAN_INTERVAL = 60

# ============================================================
# Exchange cache
# ============================================================

EXCHANGE_CACHE_SECONDS = 1800

exchange_cache = {
    "time": 0,
    "symbols": {},
    "all_symbols": []
}

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

# ============================================================
# State
# ============================================================

state_lock = threading.Lock()

state = {
    "running": True,

    # أهم قفل في البوت
    "position_lock": False,

    "position": None,

    "last_scan": None,

    "scanned": 0,

    "qualified": 0,

    "buys": 0,

    "sells": 0,

    "last_signal": None,

    "message": "جاري التشغيل",

    "error": None
}

# ============================================================
# LOG
# ============================================================

def log(message):

    print(
        f"[{time.strftime('%H:%M:%S')}] {message}",
        flush=True
    )

# ============================================================
# Public request
# ============================================================

def public_request(path, params=None):

    response = session.get(
        BASE + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()

# ============================================================
# Signed request
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if params is None:
        params = {}

    params = dict(params)

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

    url = (
        BASE
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    response = session.request(
        method,
        url,
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()

# ============================================================
# Binance request
# ============================================================

def binance_request(
    method,
    path,
    params=None,
    signed=False
):

    if signed:

        return signed_request(
            method,
            path,
            params
        )

    if method == "GET":

        return public_request(
            path,
            params
        )

    response = session.request(
        method,
        BASE + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()

# ============================================================
# Exchange info
# ============================================================

def load_exchange_info(force=False):

    now = time.time()

    if (
        not force
        and exchange_cache["symbols"]
        and (
            now
            - exchange_cache["time"]
            < EXCHANGE_CACHE_SECONDS
        )
    ):

        return exchange_cache["symbols"]

    log(
        "🔄 تحميل معلومات Binance..."
    )

    data = public_request(
        "/api/v3/exchangeInfo"
    )

    symbols = {}

    all_symbols = []

    for item in data.get(
        "symbols",
        []
    ):

        symbol = item["symbol"]

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get(
            "isSpotTradingAllowed"
        ) is False:
            continue

        filters = {}

        for f in item.get(
            "filters",
            []
        ):

            if f["filterType"] == "LOT_SIZE":

                filters["stepSize"] = (
                    f["stepSize"]
                )

                filters["minQty"] = (
                    f["minQty"]
                )

            elif f["filterType"] == "MIN_NOTIONAL":

                filters["minNotional"] = (
                    f.get(
                        "minNotional",
                        "0"
                    )
                )

            elif f["filterType"] == "NOTIONAL":

                filters["minNotional"] = (
                    f.get(
                        "minNotional",
                        "0"
                    )
                )

        symbols[symbol] = filters

        all_symbols.append(symbol)

    exchange_cache["symbols"] = symbols

    exchange_cache["all_symbols"] = all_symbols

    exchange_cache["time"] = now

    log(
        f"✅ تم تحميل معلومات Binance: "
        f"{len(all_symbols)} زوج USDT"
    )

    return symbols

# ============================================================
# Price
# ============================================================

def get_price(symbol):

    data = public_request(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )

# ============================================================
# Klines
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=210
):

    return public_request(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

# ============================================================
# EMA
# ============================================================

def calculate_ema(
    values,
    period=200
):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    ema = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema

# ============================================================
# تحليل العملة
#
# مهم:
# لا يتم استدعاء هذه الدالة أصلاً إذا كان
# position_lock = True
# ============================================================

def analyze_symbol(symbol):

    try:

        # ====================================================
        # 15 دقيقة
        # ====================================================

        k15 = get_klines(
            symbol,
            "15m",
            210
        )

        if len(k15) < 201:
            return None

        closes15 = [
            float(x[4])
            for x in k15
        ]

        current = closes15[-1]

        previous = closes15[-2]

        # ====================================================
        # تغير 15 دقيقة
        # ====================================================

        change = (
            (current - previous)
            / previous
        ) * 100

        if change <= MIN_CHANGE_15M:
            return None

        # ====================================================
        # EMA200 - 15m
        # ====================================================

        ema15 = calculate_ema(
            closes15,
            EMA_PERIOD
        )

        if ema15 is None:
            return None

        if current <= ema15:
            return None

        # ====================================================
        # EMA200 - 5m
        # ====================================================

        k5 = get_klines(
            symbol,
            "5m",
            210
        )

        if len(k5) < 201:
            return None

        closes5 = [
            float(x[4])
            for x in k5
        ]

        ema5 = calculate_ema(
            closes5,
            EMA_PERIOD
        )

        if ema5 is None:
            return None

        if current <= ema5:
            return None

        # ====================================================
        # EMA200 - 1m
        # ====================================================

        k1 = get_klines(
            symbol,
            "1m",
            210
        )

        if len(k1) < 201:
            return None

        closes1 = [
            float(x[4])
            for x in k1
        ]

        ema1 = calculate_ema(
            closes1,
            EMA_PERIOD
        )

        if ema1 is None:
            return None

        if current <= ema1:
            return None

        # ====================================================
        # مؤهلة
        # ====================================================

        return {
            "symbol": symbol,
            "price": current,
            "change": change,
            "ema15": ema15,
            "ema5": ema5,
            "ema1": ema1
        }

    except Exception as e:

        log(
            f"⚠️ تحليل {symbol}: {e}"
        )

        return None

# ============================================================
# USDT balance
# ============================================================

def get_usdt_balance():

    account = binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )

    for balance in account.get(
        "balances",
        []
    ):

        if balance["asset"] == "USDT":

            return float(
                balance["free"]
            )

    return 0.0

# ============================================================
# Asset balance
# ============================================================

def get_asset_balance(asset):

    account = binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )

    for balance in account.get(
        "balances",
        []
    ):

        if balance["asset"] == asset:

            return (
                Decimal(
                    str(balance["free"])
                )
                +
                Decimal(
                    str(balance["locked"])
                )
            )

    return Decimal("0")

# ============================================================
# حساب سعر الدخول الحقيقي
# ============================================================

def calculate_entry(symbol):

    try:

        trades = []

        from_id = None

        while True:

            params = {
                "symbol": symbol,
                "limit": 1000
            }

            if from_id is not None:

                params["fromId"] = from_id

            batch = binance_request(
                "GET",
                "/api/v3/myTrades",
                params,
                signed=True
            )

            if not batch:
                break

            trades.extend(batch)

            if len(batch) < 1000:
                break

            from_id = (
                int(batch[-1]["id"])
                + 1
            )

            time.sleep(0.1)

        if not trades:
            return None

        trades.sort(
            key=lambda x: (
                int(x.get("time", 0)),
                int(x.get("id", 0))
            )
        )

        quantity = Decimal("0")

        cost = Decimal("0")

        for trade in trades:

            qty = Decimal(
                str(trade["qty"])
            )

            quote_qty = Decimal(
                str(trade["quoteQty"])
            )

            # BUY
            if trade["isBuyer"]:

                quantity += qty

                cost += quote_qty

            # SELL
            else:

                if quantity <= 0:
                    continue

                avg_cost = (
                    cost / quantity
                )

                sell_qty = min(
                    qty,
                    quantity
                )

                cost -= (
                    avg_cost
                    * sell_qty
                )

                quantity -= sell_qty

                if quantity <= Decimal(
                    "0.0000000001"
                ):

                    quantity = Decimal("0")

                    cost = Decimal("0")

        if quantity <= 0:
            return None

        if cost <= 0:
            return None

        return float(
            cost / quantity
        )

    except Exception as e:

        log(
            f"❌ حساب الدخول {symbol}: {e}"
        )

        return None

# ============================================================
# البحث عن صفقة مفتوحة
# ============================================================

def find_open_position():

    try:

        log(
            "🔎 فحص الحساب فقط لمعرفة "
            "هل توجد صفقة..."
        )

        account = binance_request(
            "GET",
            "/api/v3/account",
            signed=True
        )

        prices = public_request(
            "/api/v3/ticker/price"
        )

        price_map = {
            x["symbol"]:
            float(x["price"])
            for x in prices
        }

        symbols_info = load_exchange_info()

        candidates = []

        for balance in account.get(
            "balances",
            []
        ):

            asset = balance["asset"]

            if asset == "USDT":
                continue

            free = Decimal(
                str(balance["free"])
            )

            locked = Decimal(
                str(balance["locked"])
            )

            quantity = (
                free + locked
            )

            if quantity <= 0:
                continue

            symbol = asset + "USDT"

            if symbol not in symbols_info:
                continue

            current = price_map.get(
                symbol
            )

            if not current:
                continue

            value = (
                float(quantity)
                * current
            )

            if value < MIN_POSITION_USDT:
                continue

            candidates.append({
                "symbol": symbol,
                "quantity": float(quantity),
                "value": value,
                "price": current
            })

        if not candidates:

            return None

        # أكبر مركز
        candidates.sort(
            key=lambda x: x["value"],
            reverse=True
        )

        candidate = candidates[0]

        symbol = candidate["symbol"]

        log(
            f"🟢 وجدت صفقة {symbol} "
            f"— حساب الدخول..."
        )

        entry = calculate_entry(
            symbol
        )

        if entry is None:

            log(
                f"⚠️ تعذر حساب دخول {symbol}"
            )

            return None

        current = candidate["price"]

        profit = (
            (current - entry)
            / entry
        ) * 100

        position = {
            "symbol": symbol,

            "quantity":
                candidate["quantity"],

            "entry":
                entry,

            "price":
                current,

            "profit":
                profit,

            "protection":
                None,

            "protection_profit":
                None,

            "opened_at":
                time.time(),

            "recovered":
                True
        }

        log(
            f"♻️ استرجاع {symbol} | "
            f"دخول {entry:.8f} | "
            f"الحالي {current:.8f} | "
            f"الربح {profit:+.2f}%"
        )

        return position

    except Exception as e:

        log(
            f"❌ استرجاع الصفقة: {e}"
        )

        return None

# ============================================================
# Normalize quantity
# ============================================================

def normalize_quantity(
    symbol,
    quantity
):

    info = load_exchange_info()

    filters = info.get(
        symbol,
        {}
    )

    step = Decimal(
        str(
            filters.get(
                "stepSize",
                "0.000001"
            )
        )
    )

    qty = Decimal(
        str(quantity)
    )

    if step > 0:

        qty = (
            qty / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    return qty

# ============================================================
# شراء
# ============================================================

def buy_position(signal):

    # ========================================================
    # قفل أمان قبل الشراء
    # ========================================================

    with state_lock:

        if state["position"] is not None:

            log(
                "⛔ منع شراء جديد: "
                "هناك صفقة مفتوحة"
            )

            return None

        if state["position_lock"]:

            log(
                "⛔ منع شراء: POSITION LOCK"
            )

            return None

        # نقفل فوراً
        state["position_lock"] = True

    try:

        symbol = signal["symbol"]

        # ====================================================
        # فحص الحساب قبل الشراء
        # ====================================================

        existing = find_open_position()

        if existing:

            log(
                f"⛔ توجد صفقة {existing['symbol']} "
                f"قبل الشراء — إلغاء الشراء"
            )

            with state_lock:

                state["position"] = existing

            return existing

        # ====================================================
        # الرصيد
        # ====================================================

        usdt = get_usdt_balance()

        amount = (
            Decimal(str(usdt))
            * Decimal(str(BUY_PERCENT))
            / Decimal("100")
        )

        amount = amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN
        )

        if amount <= 0:

            log(
                "⚠️ لا يوجد رصيد USDT"
            )

            return None

        log(
            f"🟢 شراء {symbol} "
            f"بـ {amount} USDT"
        )

        order = binance_request(
            "POST",
            "/api/v3/order",
            {
                "symbol":
                    symbol,

                "side":
                    "BUY",

                "type":
                    "MARKET",

                "quoteOrderQty":
                    str(amount)
            },
            signed=True
        )

        time.sleep(1)

        quantity = Decimal("0")

        cost = Decimal("0")

        for fill in order.get(
            "fills",
            []
        ):

            qty = Decimal(
                str(fill["qty"])
            )

            price = Decimal(
                str(fill["price"])
            )

            quantity += qty

            cost += (
                qty * price
            )

        if quantity <= 0:

            asset = symbol.replace(
                "USDT",
                ""
            )

            quantity = get_asset_balance(
                asset
            )

        if cost > 0:

            entry = float(
                cost / quantity
            )

        else:

            entry = calculate_entry(
                symbol
            )

        if entry is None:

            entry = signal["price"]

        current = get_price(
            symbol
        )

        profit = (
            (current - entry)
            / entry
        ) * 100

        position = {
            "symbol":
                symbol,

            "quantity":
                float(quantity),

            "entry":
                entry,

            "price":
                current,

            "profit":
                profit,

            "protection":
                None,

            "protection_profit":
                None,

            "opened_at":
                time.time(),

            "recovered":
                False
        }

        # ====================================================
        # الصفقة أصبحت مقفلة
        # ====================================================

        with state_lock:

            state["position"] = position

            state["position_lock"] = True

            state["buys"] += 1

            state["last_signal"] = signal

            state["message"] = (
                f"🔒 صفقة مفتوحة "
                f"{symbol} — البحث متوقف"
            )

        log(
            f"🔒 الصفقة مفتوحة: "
            f"{symbol} | "
            f"الدخول {entry:.8f}"
        )

        return position

    except Exception as e:

        log(
            f"❌ فشل الشراء: {e}"
        )

        with state_lock:

            state["error"] = str(e)

            # فقط إذا لم يتم فتح صفقة
            if state["position"] is None:

                state["position_lock"] = False

        return None

# ============================================================
# البيع
# ============================================================

def sell_position(
    position,
    reason
):

    symbol = position["symbol"]

    try:

        asset = symbol.replace(
            "USDT",
            ""
        )

        quantity = get_asset_balance(
            asset
        )

        quantity = normalize_quantity(
            symbol,
            quantity
        )

        if quantity <= 0:

            log(
                f"⚠️ لا توجد كمية {symbol}"
            )

            with state_lock:

                state["position"] = None

                state["position_lock"] = False

                state["message"] = (
                    "تم إغلاق الصفقة"
                )

            return False

        log(
            f"🔴 بيع {symbol} | "
            f"{reason}"
        )

        binance_request(
            "POST",
            "/api/v3/order",
            {
                "symbol":
                    symbol,

                "side":
                    "SELL",

                "type":
                    "MARKET",

                "quantity":
                    str(quantity)
            },
            signed=True
        )

        # ====================================================
        # تأكيد بعد البيع
        # ====================================================

        time.sleep(1)

        remaining = get_asset_balance(
            asset
        )

        # إذا بقيت كمية بسيطة جداً نعتبر الصفقة مغلقة
        current_price = get_price(
            symbol
        )

        remaining_value = (
            float(remaining)
            * current_price
        )

        with state_lock:

            state["sells"] += 1

            state["position"] = None

            # الآن فقط نفتح قفل البحث
            state["position_lock"] = False

            state["message"] = (
                f"تم إغلاق {symbol} — "
                f"يمكن البحث من جديد"
            )

        log(
            f"🔓 أغلقت الصفقة {symbol}"
        )

        return True

    except Exception as e:

        log(
            f"❌ فشل بيع {symbol}: {e}"
        )

        with state_lock:

            state["error"] = str(e)

        return False

# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position(position):

    symbol = position["symbol"]

    try:

        current = get_price(
            symbol
        )

        entry = float(
            position["entry"]
        )

        # ====================================================
        # ربح الصفقة فقط
        # ====================================================

        profit = (
            (current - entry)
            / entry
        ) * 100

        # ====================================================
        # حماية كل +1%
        # ====================================================

        if profit >= PROTECTION_START:

            level = int(
                profit
                // PROTECTION_STEP
            )

            protection_profit = (
                level
                * PROTECTION_STEP
            ) - TRAILING_PERCENT

            protection_price = (
                entry
                * (
                    1
                    + protection_profit
                    / 100
                )
            )

            old_protection = (
                position.get(
                    "protection"
                )
            )

            # الحماية ترتفع فقط
            if (
                old_protection is None
                or protection_price
                > old_protection
            ):

                position[
                    "protection"
                ] = protection_price

                position[
                    "protection_profit"
                ] = protection_profit

                log(
                    f"🛡️ {symbol} | "
                    f"ربح +{profit:.2f}% | "
                    f"الحماية +"
                    f"{protection_profit:.2f}%"
                )

        position["price"] = current

        position["profit"] = profit

        # ====================================================
        # تحديث الحالة
        # ====================================================

        with state_lock:

            state["position"] = position

            state["position_lock"] = True

            state["message"] = (
                f"🔒 يتابع {symbol} — "
                f"البحث متوقف"
            )

        # ====================================================
        # تنفيذ الحماية
        # ====================================================

        protection = position.get(
            "protection"
        )

        if (
            protection is not None
            and current <= protection
        ):

            protection_profit = (
                position.get(
                    "protection_profit",
                    0
                )
            )

            log(
                f"🛑 حماية الصفقة | "
                f"{symbol} | "
                f"الربح {profit:+.2f}% | "
                f"الحماية +"
                f"{protection_profit:.2f}%"
            )

            sell_position(
                position,
                (
                    "حماية الربح "
                    f"+{protection_profit:.2f}%"
                )
            )

            return

        log(
            f"📊 {symbol} | "
            f"الصفقة {profit:+.2f}%"
        )

    except Exception as e:

        log(
            f"⚠️ إدارة {symbol}: {e}"
        )

# ============================================================
# فحص السوق
#
# فيه قفلين:
# 1) قبل بداية الفحص
# 2) قبل كل عملة
# 3) قبل الشراء
# ============================================================

def scan_market():

    # ========================================================
    # قفل مطلق
    # ========================================================

    with state_lock:

        if state["position"] is not None:

            log(
                "🔒 توجد صفقة — "
                "تم منع Market Scan"
            )

            return

        if state["position_lock"]:

            log(
                "🔒 POSITION LOCK — "
                "تم منع Market Scan"
            )

            return

    symbols_info = load_exchange_info()

    symbols = list(
        symbols_info.keys()
    )

    candidates = []

    scanned = 0

    qualified = 0

    log(
        f"🔎 بدء البحث في "
        f"{len(symbols)} زوج..."
    )

    for index, symbol in enumerate(
        symbols,
        1
    ):

        # ====================================================
        # قفل قبل كل تحليل
        # ====================================================

        with state_lock:

            if (
                state["position"] is not None
                or state["position_lock"]
            ):

                log(
                    "🔒 تم إيقاف البحث فوراً "
                    "لوجود صفقة"
                )

                return

        scanned += 1

        with state_lock:

            state["scanned"] = scanned

        result = analyze_symbol(
            symbol
        )

        if result:

            qualified += 1

            candidates.append(
                result
            )

            log(
                f"⭐ {symbol} | "
                f"+{result['change']:.2f}%"
            )

        if index % 25 == 0:

            log(
                f"🔎 {index}/{len(symbols)} | "
                f"مؤهلة {qualified}"
            )

    with state_lock:

        state["qualified"] = qualified

        state["scanned"] = scanned

        state["last_scan"] = (
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

    if not candidates:

        with state_lock:

            state["message"] = (
                "لا توجد عملة مطابقة"
            )

        log(
            "⚪ لا توجد فرصة"
        )

        return

    # ========================================================
    # اختيار أعلى تغير
    # ========================================================

    candidates.sort(
        key=lambda x: x["change"],
        reverse=True
    )

    best = candidates[0]

    log(
        f"🏆 الأفضل: "
        f"{best['symbol']} | "
        f"+{best['change']:.2f}%"
    )

    # ========================================================
    # قفل نهائي قبل الدخول
    # ========================================================

    with state_lock:

        if (
            state["position"] is not None
            or state["position_lock"]
        ):

            log(
                "🔒 منع الدخول — "
                "صفقة موجودة"
            )

            return

    buy_position(
        best
    )

# ============================================================
# محرك التداول
# ============================================================

def trading_engine():

    log(
        "🤖 محرك التداول بدأ"
    )

    while True:

        try:

            # =================================================
            # أول شيء دائماً:
            # هل توجد صفقة في الذاكرة؟
            # =================================================

            with state_lock:

                position = (
                    state["position"]
                )

                locked = (
                    state["position_lock"]
                )

            # =================================================
            # إذا الصفقة موجودة
            # لا يوجد أي بحث
            # =================================================

            if position is not None:

                manage_position(
                    position
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # إذا POSITION LOCK موجود
            # لا نبحث
            # =================================================

            if locked:

                log(
                    "🔒 POSITION LOCK — "
                    "لا يوجد Market Scan"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # لا توجد صفقة:
            # فحص الحساب لمعرفة إذا Binance
            # فيها صفقة من قبل إعادة التشغيل
            # =================================================

            recovered = (
                find_open_position()
            )

            if recovered:

                with state_lock:

                    state["position"] = (
                        recovered
                    )

                    state["position_lock"] = True

                    state["message"] = (
                        f"🔒 استرجاع "
                        f"{recovered['symbol']} — "
                        f"البحث متوقف"
                    )

                log(
                    f"🔒 تم استرجاع "
                    f"{recovered['symbol']} "
                    f"— لن يتم البحث"
                )

                manage_position(
                    recovered
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # الآن فقط يسمح بالبحث
            # =================================================

            with state_lock:

                if (
                    state["position"] is not None
                    or state["position_lock"]
                ):

                    continue

            scan_market()

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            log(
                f"❌ خطأ المحرك: {e}"
            )

            with state_lock:

                state["error"] = str(e)

            time.sleep(30)

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

<title>مضارب أبو سعود V8</title>

<style>

body{
    margin:0;
    background:#0b1020;
    color:#fff;
    font-family:Arial,sans-serif;
}

.container{
    max-width:900px;
    margin:auto;
    padding:20px;
}

h1{
    text-align:center;
}

.card{
    background:#151c31;
    border:1px solid #293552;
    border-radius:18px;
    padding:18px;
    margin:12px 0;
}

.row{
    display:flex;
    justify-content:space-between;
    padding:10px 0;
    border-bottom:1px solid #252d43;
}

.green{
    color:#35e39a;
}

.red{
    color:#ff5d6c;
}

.yellow{
    color:#ffd166;
}

.lock{
    color:#ffb84d;
    font-size:18px;
    font-weight:bold;
}

.big{
    font-size:28px;
    font-weight:bold;
}

</style>

</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود V8</h1>

<div class="card">

<div class="row">
<span>الحالة</span>
<strong id="message">...</strong>
</div>

<div class="row">
<span>قفل الصفقة</span>
<strong id="lock">...</strong>
</div>

<div class="row">
<span>المفحوص</span>
<strong id="scanned">0</strong>
</div>

<div class="row">
<span>المؤهلة</span>
<strong id="qualified">0</strong>
</div>

<div class="row">
<span>المشتريات</span>
<strong id="buys">0</strong>
</div>

<div class="row">
<span>المبيعات</span>
<strong id="sells">0</strong>
</div>

</div>

<div class="card">

<h2>📊 الصفقة الحالية</h2>

<div id="position">
لا توجد صفقة
</div>

</div>

<div class="card">

<h2>⭐ آخر إشارة</h2>

<div id="signal">
لا توجد إشارة
</div>

</div>

</div>

<script>

async function update(){

    try{

        const response =
            await fetch('/api/status');

        const data =
            await response.json();

        document.getElementById(
            'message'
        ).innerText =
            data.message || '';

        document.getElementById(
            'scanned'
        ).innerText =
            data.scanned || 0;

        document.getElementById(
            'qualified'
        ).innerText =
            data.qualified || 0;

        document.getElementById(
            'buys'
        ).innerText =
            data.buys || 0;

        document.getElementById(
            'sells'
        ).innerText =
            data.sells || 0;

        document.getElementById(
            'lock'
        ).innerHTML =
            data.position_lock
            ? '<span class="lock">🔒 البحث متوقف</span>'
            : '<span class="green">🟢 البحث مسموح</span>';

        const p =
            data.position;

        if(p){

            const profitClass =
                p.profit >= 0
                ? 'green'
                : 'red';

            let protection = '';

            if(
                p.protection_profit !== null
                &&
                p.protection_profit !== undefined
            ){

                protection = `
                <div class="row">
                    <span>🛡️ حماية الربح</span>
                    <strong class="green">
                    +${p.protection_profit.toFixed(2)}%
                    </strong>
                </div>`;
            }

            document.getElementById(
                'position'
            ).innerHTML = `

            <div class="row">
                <span>العملة</span>
                <strong>${p.symbol}</strong>
            </div>

            <div class="row">
                <span>الدخول</span>
                <strong>${p.entry}</strong>
            </div>

            <div class="row">
                <span>السعر الحالي</span>
                <strong>${p.price}</strong>
            </div>

            <div class="row">
                <span>ربح الصفقة</span>
                <strong class="${profitClass} big">
                ${p.profit >= 0 ? '+' : ''}
                ${p.profit.toFixed(2)}%
                </strong>
            </div>

            ${protection}

            <div class="row">
                <span>الوضع</span>
                <strong class="lock">
                🔒 متابعة فقط
                </strong>
            </div>

            `;

        }else{

            document.getElementById(
                'position'
            ).innerHTML =
                'لا توجد صفقة مفتوحة';

        }

        const x =
            data.last_signal;

        if(x){

            document.getElementById(
                'signal'
            ).innerHTML = `

            <div class="row">
                <span>العملة</span>
                <strong>${x.symbol}</strong>
            </div>

            <div class="row">
                <span>تغير 15د</span>
                <strong class="green">
                +${x.change.toFixed(2)}%
                </strong>
            </div>

            <div class="row">
                <span>EMA200 15د</span>
                <strong>${x.ema15}</strong>
            </div>

            <div class="row">
                <span>EMA200 5د</span>
                <strong>${x.ema5}</strong>
            </div>

            <div class="row">
                <span>EMA200 1د</span>
                <strong>${x.ema1}</strong>
            </div>

            `;

        }

    }catch(error){

        console.log(error);

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
# Status API
# ============================================================

@app.route("/api/status")
def status():

    with state_lock:

        return jsonify({
            "running":
                state["running"],

            "position_lock":
                state["position_lock"],

            "position":
                state["position"],

            "last_scan":
                state["last_scan"],

            "scanned":
                state["scanned"],

            "qualified":
                state["qualified"],

            "buys":
                state["buys"],

            "sells":
                state["sells"],

            "last_signal":
                state["last_signal"],

            "message":
                state["message"],

            "error":
                state["error"]
        })

# ============================================================
# Start
# ============================================================

def start_bot():

    log("")
    log("=" * 60)
    log(
        "🚀 تشغيل مضارب أبو سعود V8 LOCK"
    )
    log("=" * 60)
    log("")

    if not API_KEY or not API_SECRET:

        log(
            "❌ مفاتيح Binance غير موجودة"
        )

        return

    log(
        "🔐 مفاتيح Binance موجودة"
    )

    load_exchange_info()

    thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    thread.start()

# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    start_bot()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    log(
        f"🌐 الموقع يعمل على PORT {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
