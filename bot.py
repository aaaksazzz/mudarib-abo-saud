# ============================================================
# مضارب أبو سعود V6 FAST 🤖
# Binance Spot + Dashboard
# اكتشاف وإدارة الصفقة المفتوحة بعد إعادة التشغيل
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

load_dotenv()

# ============================================================
# الإعدادات
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

TIMEFRAME = "15m"

# ============================
# استراتيجية الدخول V6
# ============================

MIN_CHANGE_15M = 1.0
EMA_PERIOD = 200

# ============================
# إدارة الصفقة
# ============================

PROTECTION_START = 1.0

# كل 1% إضافية نرفع وقف الحماية
PROTECTION_STEP = 1.0

# مثال:
# +1%  -> وقف +0.5%
# +2%  -> وقف +1.5%
# +3%  -> وقف +2.5%
# +4%  -> وقف +3.5%

PROTECTION_GAP = 0.50

# كل كم ثانية نراجع الصفقة
POSITION_CHECK_SECONDS = 15

# كل كم ثانية نعيد Scan إذا ما فيه صفقة
SCAN_INTERVAL = 60

# أقل قيمة نعتبرها صفقة
MIN_POSITION_USDT = 2.0

BUY_PERCENT = 99.9

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

# ============================================================
# حالة البوت
# ============================================================

state = {
    "running": True,
    "position": None,
    "last_scan": None,
    "last_error": None,
    "best_symbol": None,
    "best_change": None,
    "trades": 0,
    "wins": 0,
    "losses": 0,
}

position_lock = threading.Lock()

# ============================================================
# Cache
# ============================================================

exchange_info_cache = None
exchange_info_time = 0

symbol_map_cache = {}
symbol_map_time = 0

# ============================================================
# أخطاء
# ============================================================

class BinanceRateLimit(Exception):
    pass


class BinanceTemporaryError(Exception):
    pass


# ============================================================
# طلب عام
# ============================================================

def public_get(path, params=None):

    url = BASE + path

    r = requests.get(
        url,
        params=params,
        timeout=20
    )

    if r.status_code == 429:
        raise BinanceRateLimit(
            "Binance 429"
        )

    if r.status_code >= 500:
        raise BinanceTemporaryError(
            f"Binance server error {r.status_code}"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# طلب Binance موقع
# ============================================================

def signed_request(method, path, params=None):

    if params is None:
        params = {}

    params = dict(params)

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

    query += (
        "&signature="
        + signature
    )

    url = (
        BASE
        + path
        + "?"
        + query
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    r = requests.request(
        method,
        url,
        headers=headers,
        timeout=20
    )

    if r.status_code == 429:
        raise BinanceRateLimit(
            "Binance 429"
        )

    if r.status_code >= 500:
        raise BinanceTemporaryError(
            f"Binance server error {r.status_code}"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# حساب Binance
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


# ============================================================
# Exchange Info
# ============================================================

def load_exchange_info():

    global exchange_info_cache
    global exchange_info_time

    now = time.time()

    if (
        exchange_info_cache is not None
        and now - exchange_info_time < 1800
    ):
        return exchange_info_cache

    print(
        "📥 تحميل معلومات Binance..."
    )

    exchange_info_cache = public_get(
        "/api/v3/exchangeInfo"
    )

    exchange_info_time = now

    return exchange_info_cache


# ============================================================
# بناء خريطة الأزواج
# ============================================================

def load_symbol_map():

    global symbol_map_cache
    global symbol_map_time

    now = time.time()

    if (
        symbol_map_cache
        and now - symbol_map_time < 1800
    ):
        return symbol_map_cache

    info = load_exchange_info()

    result = {}

    for s in info.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol"
        )

        if not symbol:
            continue

        result[symbol] = s

    symbol_map_cache = result
    symbol_map_time = now

    print(
        f"📋 تم تحميل {len(result)} زوج"
    )

    return result


# ============================================================
# هل الزوج Spot USDT صالح؟
# ============================================================

def get_usdt_symbol_for_asset(asset):

    symbol_map = load_symbol_map()

    symbol = asset + "USDT"

    data = symbol_map.get(
        symbol
    )

    if not data:
        return None

    if data.get("status") != "TRADING":
        return None

    if data.get("quoteAsset") != "USDT":
        return None

    permissions = data.get(
        "permissions",
        []
    )

    if (
        permissions
        and "SPOT" not in permissions
    ):
        return None

    return symbol


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
# أسعار جميع العملات
# نستخدمها لاكتشاف الصفقة بسرعة
# ============================================================

def get_all_prices():

    data = public_get(
        "/api/v3/ticker/price"
    )

    result = {}

    for item in data:

        symbol = item.get(
            "symbol"
        )

        price = item.get(
            "price"
        )

        if symbol and price:

            try:
                result[symbol] = float(
                    price
                )
            except:
                pass

    return result


# ============================================================
# اكتشاف الصفقة المفتوحة
# ============================================================

def find_open_position():

    print(
        "🔎 جاري التحقق من الصفقة المفتوحة..."
    )

    account = get_account()

    balances = account.get(
        "balances",
        []
    )

    # نجمع العملات الموجودة فعليًا
    candidates = []

    for balance in balances:

        asset = balance.get(
            "asset"
        )

        if not asset:
            continue

        if asset == "USDT":
            continue

        try:

            free = float(
                balance.get(
                    "free",
                    0
                )
            )

            locked = float(
                balance.get(
                    "locked",
                    0
                )
            )

        except:

            continue

        amount = free + locked

        if amount <= 0:
            continue

        candidates.append(
            (
                asset,
                amount
            )
        )

    if not candidates:

        print(
            "📭 لا توجد عملات مفتوحة"
        )

        return None

    # نحصل على الأسعار دفعة واحدة
    try:

        prices = get_all_prices()

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"⚠️ تعذر تحميل الأسعار: {e}"
        )

        raise

    # نبحث عن صفقة حقيقية
    for asset, amount in candidates:

        symbol = get_usdt_symbol_for_asset(
            asset
        )

        # أصل موجود في المحفظة لكن ليس له زوج USDT
        if not symbol:

            print(
                f"⏭️ {asset} "
                f"لا يوجد له زوج USDT صالح"
            )

            continue

        price = prices.get(
            symbol
        )

        if not price:

            continue

        value = amount * price

        # تجاهل الغبار
        if value < MIN_POSITION_USDT:

            print(
                f"⏭️ {symbol} "
                f"رصيده {value:.4f} USDT "
                f"أقل من الحد"
            )

            continue

        print(
            f"💰 تم العثور على صفقة: "
            f"{symbol} | "
            f"القيمة {value:.2f} USDT"
        )

        # حساب الدخول
        entry = calculate_entry(
            symbol
        )

        if entry is None:

            print(
                f"⚠️ لم نجد سعر دخول "
                f"واضح لـ {symbol}"
            )

            # إذا فشل myTrades نستخدم السعر الحالي
            entry = price

        # إنشاء الصفقة
        position = {
            "symbol": symbol,
            "qty": amount,
            "entry": entry,
            "price": price,
            "value": value,
            "peak": price,
            "protection": None,
            "protection_level": 0,
        }

        # حساب حماية مناسبة حتى بعد إعادة تشغيل البوت
        profit = (
            (price - entry)
            / entry
        ) * 100

        if profit >= PROTECTION_START:

            level = int(
                profit
                // PROTECTION_STEP
            )

            if level < 1:
                level = 1

            protection = calculate_protection(
                entry,
                level
            )

            position[
                "protection"
            ] = protection

            position[
                "protection_level"
            ] = level

            print(
                f"🛡️ استعادة الحماية "
                f"+{level}% | "
                f"وقف {protection:.8f}"
            )

        print(
            f"✅ الصفقة جاهزة للإدارة: "
            f"{symbol} | "
            f"الدخول {entry:.8f}"
        )

        return position

    print(
        "📭 لا توجد صفقة قابلة للإدارة"
    )

    return None


# ============================================================
# حساب سعر الدخول
# ============================================================

def calculate_entry(symbol):

    try:

        trades = signed_request(
            "GET",
            "/api/v3/myTrades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

        if not trades:
            return None

        # حساب متوسط تكلفة صافي الكمية
        total_qty = 0.0
        total_cost = 0.0

        for trade in trades:

            qty = float(
                trade.get(
                    "qty",
                    0
                )
            )

            price = float(
                trade.get(
                    "price",
                    0
                )
            )

            if qty <= 0 or price <= 0:
                continue

            if trade.get(
                "isBuyer",
                False
            ):

                total_qty += qty
                total_cost += (
                    qty * price
                )

            else:

                total_qty -= qty
                total_cost -= (
                    qty * price
                )

        if total_qty <= 0:
            return None

        return (
            total_cost
            / total_qty
        )

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"⚠️ تعذر حساب الدخول "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# Klines
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=200
):

    return public_get(
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
    period
):

    if len(values) < period:
        return None

    ema = sum(
        values[:period]
    ) / period

    multiplier = 2 / (
        period + 1
    )

    for price in values[period:]:

        ema = (
            (
                price - ema
            )
            * multiplier
        ) + ema

    return ema


# ============================================================
# تحليل العملة
# نفس V6
# ============================================================

def analyze_symbol(symbol):

    try:

        # ============================
        # 15m
        # ============================

        candles15 = get_klines(
            symbol,
            "15m",
            200
        )

        closes15 = [
            float(x[4])
            for x in candles15
        ]

        if len(closes15) < EMA_PERIOD:
            return None

        price = closes15[-1]
        previous = closes15[-2]

        change15 = (
            (price - previous)
            / previous
        ) * 100

        if change15 < MIN_CHANGE_15M:
            return None

        ema15 = calculate_ema(
            closes15,
            EMA_PERIOD
        )

        if (
            ema15 is None
            or price <= ema15
        ):
            return None

        # ============================
        # 5m
        # ============================

        candles5 = get_klines(
            symbol,
            "5m",
            200
        )

        closes5 = [
            float(x[4])
            for x in candles5
        ]

        if len(closes5) < EMA_PERIOD:
            return None

        price5 = closes5[-1]

        ema5 = calculate_ema(
            closes5,
            EMA_PERIOD
        )

        if (
            ema5 is None
            or price5 <= ema5
        ):
            return None

        # ============================
        # 1m
        # ============================

        candles1 = get_klines(
            symbol,
            "1m",
            200
        )

        closes1 = [
            float(x[4])
            for x in candles1
        ]

        if len(closes1) < EMA_PERIOD:
            return None

        price1 = closes1[-1]

        ema1 = calculate_ema(
            closes1,
            EMA_PERIOD
        )

        if (
            ema1 is None
            or price1 <= ema1
        ):
            return None

        return {
            "symbol": symbol,
            "price": price,
            "change": change15,
            "ema15": ema15,
            "ema5": ema5,
            "ema1": ema1
        }

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"⚠️ تحليل {symbol}: {e}"
        )

        return None


# ============================================================
# أزواج USDT للفحص
# ============================================================

def get_valid_usdt_symbols():

    symbol_map = load_symbol_map()

    result = []

    for symbol, data in symbol_map.items():

        if data.get(
            "status"
        ) != "TRADING":
            continue

        if data.get(
            "quoteAsset"
        ) != "USDT":
            continue

        permissions = data.get(
            "permissions",
            []
        )

        if (
            permissions
            and "SPOT"
            not in permissions
        ):
            continue

        result.append(
            symbol
        )

    print(
        f"📋 العملات الصالحة: "
        f"{len(result)}"
    )

    return result


# ============================================================
# فلاتر الزوج
# ============================================================

def get_symbol_filters(symbol):

    symbol_map = load_symbol_map()

    data = symbol_map.get(
        symbol
    )

    if not data:
        return {}

    filters = {}

    for f in data.get(
        "filters",
        []
    ):

        if f.get(
            "filterType"
        ) == "LOT_SIZE":

            filters[
                "stepSize"
            ] = f.get(
                "stepSize"
            )

            filters[
                "minQty"
            ] = f.get(
                "minQty"
            )

        elif f.get(
            "filterType"
        ) in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            filters[
                "minNotional"
            ] = f.get(
                "minNotional",
                "0"
            )

    return filters


# ============================================================
# تقريب الكمية
# ============================================================

def round_step(
    value,
    step
):

    value = Decimal(
        str(value)
    )

    step = Decimal(
        str(step)
    )

    if step <= 0:
        return float(value)

    result = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return float(result)


# ============================================================
# حساب وقف الحماية
# ============================================================

def calculate_protection(
    entry,
    level
):

    # +1% -> +0.5%
    # +2% -> +1.5%
    # +3% -> +2.5%

    locked_profit = (
        level
        - PROTECTION_GAP
    )

    if locked_profit < 0:
        locked_profit = 0

    return entry * (
        1
        + locked_profit / 100
    )


# ============================================================
# شراء
# ============================================================

def buy_symbol(symbol):

    try:

        account = get_account()

        usdt = 0.0

        for balance in account.get(
            "balances",
            []
        ):

            if balance.get(
                "asset"
            ) == "USDT":

                usdt = float(
                    balance.get(
                        "free",
                        0
                    )
                )

                break

        if usdt < MIN_POSITION_USDT:

            print(
                "⚠️ رصيد USDT غير كافي"
            )

            return None

        amount_usdt = (
            usdt
            * BUY_PERCENT
            / 100
        )

        price = get_price(
            symbol
        )

        filters = get_symbol_filters(
            symbol
        )

        step = filters.get(
            "stepSize",
            "0.000001"
        )

        qty = (
            amount_usdt
            / price
        )

        qty = round_step(
            qty,
            step
        )

        if qty <= 0:

            print(
                "⚠️ الكمية غير صالحة"
            )

            return None

        print(
            f"🟢 شراء {symbol} | "
            f"السعر {price} | "
            f"الكمية {qty}"
        )

        signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": qty
            }
        )

        time.sleep(2)

        position = find_open_position()

        if position:

            state["trades"] += 1

            with position_lock:

                state[
                    "position"
                ] = position

            print(
                f"✅ تم فتح الصفقة "
                f"{position['symbol']}"
            )

            return position

        print(
            "⚠️ تم الشراء لكن "
            "لم يتم اكتشاف الصفقة"
        )

        return None

    except BinanceRateLimit:

        raise

    except Exception as e:

        state[
            "last_error"
        ] = str(e)

        print(
            f"❌ خطأ شراء: {e}"
        )

        return None


# ============================================================
# بيع
# ============================================================

def sell_position(position):

    symbol = position[
        "symbol"
    ]

    asset = symbol.replace(
        "USDT",
        ""
    )

    try:

        account = get_account()

        qty = 0.0

        for balance in account.get(
            "balances",
            []
        ):

            if balance.get(
                "asset"
            ) == asset:

                qty = float(
                    balance.get(
                        "free",
                        0
                    )
                )

                break

        if qty <= 0:

            print(
                f"⚠️ لا توجد كمية "
                f"متاحة للبيع {symbol}"
            )

            return False

        filters = get_symbol_filters(
            symbol
        )

        step = filters.get(
            "stepSize",
            "0.000001"
        )

        qty = round_step(
            qty,
            step
        )

        if qty <= 0:
            return False

        print(
            f"🔴 بيع {symbol} | "
            f"الكمية {qty}"
        )

        signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": qty
            }
        )

        return True

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"❌ خطأ البيع: {e}"
        )

        return False


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position(
    position
):

    symbol = position[
        "symbol"
    ]

    try:

        price = get_price(
            symbol
        )

        entry = float(
            position["entry"]
        )

        if entry <= 0:

            print(
                "⚠️ سعر الدخول غير صالح"
            )

            return position

        profit = (
            (
                price - entry
            )
            / entry
        ) * 100

        position[
            "price"
        ] = price

        position[
            "profit"
        ] = profit

        # أعلى سعر
        if price > position.get(
            "peak",
            0
        ):

            position[
                "peak"
            ] = price

        # ====================================================
        # رفع الحماية كل 1%
        # ====================================================

        if profit >= PROTECTION_START:

            level = int(
                profit
                // PROTECTION_STEP
            )

            if level < 1:
                level = 1

            old_level = position.get(
                "protection_level",
                0
            )

            # لا نرفع إلا إذا وصل مستوى جديد
            if level > old_level:

                new_protection = (
                    calculate_protection(
                        entry,
                        level
                    )
                )

                old_protection = (
                    position.get(
                        "protection"
                    )
                )

                # لا ننزل الوقف أبدًا
                if (
                    old_protection is None
                    or new_protection
                    > old_protection
                ):

                    position[
                        "protection"
                    ] = new_protection

                    position[
                        "protection_level"
                    ] = level

                    print(
                        f"🛡️ رفع الحماية "
                        f"{symbol} | "
                        f"الربح +{profit:.2f}% | "
                        f"المستوى +{level}% | "
                        f"وقف {new_protection:.8f}"
                    )

        protection = position.get(
            "protection"
        )

        # ====================================================
        # ضرب وقف الحماية
        # ====================================================

        if (
            protection is not None
            and price <= protection
        ):

            print(
                f"🚨 ضرب وقف الحماية | "
                f"{symbol} | "
                f"الربح {profit:+.2f}% | "
                f"السعر {price:.8f} | "
                f"الوقف {protection:.8f}"
            )

            sold = sell_position(
                position
            )

            if sold:

                if profit >= 0:

                    state[
                        "wins"
                    ] += 1

                else:

                    state[
                        "losses"
                    ] += 1

                with position_lock:

                    state[
                        "position"
                    ] = None

                print(
                    f"✅ انتهت الصفقة "
                    f"{symbol}"
                )

                return None

        with position_lock:

            state[
                "position"
            ] = dict(
                position
            )

        print(
            f"📊 إدارة {symbol} | "
            f"الربح {profit:+.2f}% | "
            f"الحماية "
            f"{protection:.8f}"
            if protection
            else
            f"📊 إدارة {symbol} | "
            f"الربح {profit:+.2f}% | "
            f"الحماية لم تبدأ"
        )

        return position

    except BinanceRateLimit:

        raise

    except Exception as e:

        state[
            "last_error"
        ] = str(e)

        print(
            f"⚠️ خطأ إدارة {symbol}: {e}"
        )

        return position


# ============================================================
# فحص السوق
# ============================================================

def scan_market():

    symbols = get_valid_usdt_symbols()

    best = None

    total = len(
        symbols
    )

    print(
        f"🚀 بدء فحص {total} عملة"
    )

    for index, symbol in enumerate(
        symbols,
        1
    ):

        print(
            f"🔍 [{index}/{total}] "
            f"{symbol}",
            end="\r",
            flush=True
        )

        result = analyze_symbol(
            symbol
        )

        if result is None:
            continue

        if (
            best is None
            or result["change"]
            > best["change"]
        ):

            best = result

    print()

    if best:

        state[
            "best_symbol"
        ] = best[
            "symbol"
        ]

        state[
            "best_change"
        ] = best[
            "change"
        ]

        print(
            f"🎯 أفضل فرصة: "
            f"{best['symbol']} | "
            f"+{best['change']:.2f}%"
        )

    else:

        print(
            "❌ لا توجد فرصة مطابقة"
        )

    state[
        "last_scan"
    ] = time.time()

    return best


# ============================================================
# محرك التداول
# ============================================================

def trading_engine():

    print(
        "🤖 محرك التداول بدأ"
    )

    last_scan_time = 0

    while True:

        try:

            # ==================================================
            # اكتشاف الصفقة
            # ==================================================

            print(
                "🔎 فحص الحساب لمعرفة "
                "هل توجد صفقة..."
            )

            try:

                position = (
                    find_open_position()
                )

            except (
                BinanceRateLimit,
                BinanceTemporaryError,
                requests.RequestException
            ) as e:

                state[
                    "last_error"
                ] = str(e)

                print(
                    f"⚠️ تعذر التحقق "
                    f"من الحساب: {e}"
                )

                print(
                    "⏳ لن نعمل Scan "
                    "حتى نتأكد"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # ==================================================
            # صفقة موجودة
            # ==================================================

            if position:

                print(
                    f"💰 الصفقة موجودة: "
                    f"{position['symbol']}"
                )

                with position_lock:

                    state[
                        "position"
                    ] = position

                while True:

                    try:

                        current = (
                            find_open_position()
                        )

                    except (
                        BinanceRateLimit,
                        BinanceTemporaryError,
                        requests.RequestException
                    ) as e:

                        print(
                            f"⚠️ تعذر التحقق "
                            f"من الصفقة: {e}"
                        )

                        time.sleep(
                            POSITION_CHECK_SECONDS
                        )

                        continue

                    # الصفقة اختفت
                    if current is None:

                        print(
                            "📭 الصفقة انتهت "
                            "أو تم بيعها"
                        )

                        with position_lock:

                            state[
                                "position"
                            ] = None

                        break

                    # ==================================================
                    # المحافظة على الحماية السابقة
                    # ==================================================

                    current[
                        "peak"
                    ] = max(
                        position.get(
                            "peak",
                            current["price"]
                        ),
                        current["price"]
                    )

                    old_protection = (
                        position.get(
                            "protection"
                        )
                    )

                    if old_protection is not None:

                        current[
                            "protection"
                        ] = old_protection

                    current[
                        "protection_level"
                    ] = position.get(
                        "protection_level",
                        0
                    )

                    position = current

                    # ==================================================
                    # الإدارة
                    # ==================================================

                    position = (
                        manage_position(
                            position
                        )
                    )

                    if position is None:
                        break

                    time.sleep(
                        POSITION_CHECK_SECONDS
                    )

                continue

            # ==================================================
            # لا توجد صفقة
            # ==================================================

            now = time.time()

            if (
                now - last_scan_time
                < SCAN_INTERVAL
            ):

                time.sleep(5)

                continue

            print(
                "📭 لا توجد صفقة مفتوحة"
            )

            # ==================================================
            # Scan
            # ==================================================

            best = scan_market()

            last_scan_time = time.time()

            if best is None:

                time.sleep(5)

                continue

            # ==================================================
            # تأكيد أخير قبل الشراء
            # ==================================================

            try:

                check = (
                    find_open_position()
                )

            except (
                BinanceRateLimit,
                BinanceTemporaryError,
                requests.RequestException
            ) as e:

                print(
                    f"⚠️ تعذر التأكد "
                    f"قبل الشراء: {e}"
                )

                time.sleep(10)

                continue

            if check:

                print(
                    "⚠️ توجد صفقة فعلًا، "
                    "لن نشتري صفقة ثانية"
                )

                continue

            # ==================================================
            # شراء
            # ==================================================

            print(
                f"🟢 إشارة شراء: "
                f"{best['symbol']} | "
                f"+{best['change']:.2f}%"
            )

            buy_symbol(
                best["symbol"]
            )

            time.sleep(5)

        except BinanceRateLimit:

            print(
                "⛔ Binance 429 | "
                "انتظار 60 ثانية"
            )

            time.sleep(60)

        except Exception as e:

            state[
                "last_error"
            ] = str(e)

            print(
                f"❌ خطأ محرك التداول: {e}"
            )

            time.sleep(15)


# ============================================================
# مراقبة الاتصال
# ============================================================

def connection_monitor():

    while True:

        try:

            get_account()

            print(
                "🟢 اتصال Binance OK"
            )

        except Exception as e:

            print(
                f"⚠️ اتصال Binance: {e}"
            )

        time.sleep(180)


# ============================================================
# Dashboard
# ============================================================

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1.0">

<title>مضارب أبو سعود</title>

<style>

body{
    margin:0;
    background:#0f1115;
    color:#fff;
    font-family:Arial,sans-serif;
}

.container{
    max-width:700px;
    margin:auto;
    padding:20px;
}

.card{
    background:#181b22;
    border-radius:16px;
    padding:18px;
    margin-bottom:15px;
}

h1{
    text-align:center;
}

.green{
    color:#00e676;
}

.red{
    color:#ff5252;
}

.gray{
    color:#aaa;
}

.big{
    font-size:24px;
    font-weight:bold;
}

</style>

</head>

<body>

<div class="container">

<h1>🤖 مضارب أبو سعود</h1>

<div class="card">

<h3>حالة البوت</h3>

<div id="status">
جاري التحميل...
</div>

</div>

<div class="card">

<h3>💰 الصفقة الحالية</h3>

<div id="position">
لا توجد صفقة
</div>

</div>

<div class="card">

<h3>📊 المعلومات</h3>

<div id="stats">
جاري التحميل...
</div>

</div>

</div>

<script>

async function update(){

    try{

        const response =
            await fetch(
                "/api/status"
            );

        const data =
            await response.json();

        document.getElementById(
            "status"
        ).innerHTML =
            data.running
            ?
            '<span class="green">🟢 البوت يعمل</span>'
            :
            '<span class="red">🔴 البوت متوقف</span>';

        if(data.position){

            const p =
                data.position;

            const profit =
                p.profit || 0;

            document.getElementById(
                "position"
            ).innerHTML =

                "العملة: <b>"
                + p.symbol
                + "</b><br><br>"

                + "سعر الدخول: "
                + Number(
                    p.entry
                ).toFixed(8)
                + "<br>"

                + "السعر الحالي: "
                + Number(
                    p.price
                ).toFixed(8)
                + "<br>"

                + "الربح: <span class='"
                + (
                    profit >= 0
                    ? "green"
                    : "red"
                )
                + "'>"
                + profit.toFixed(2)
                + "%</span><br>"

                + "مستوى الحماية: +"
                + (
                    p.protection_level
                    || 0
                )
                + "%<br>"

                + "وقف الحماية: "
                + (
                    p.protection
                    ?
                    Number(
                        p.protection
                    ).toFixed(8)
                    :
                    "لم يبدأ"
                );

        }else{

            document.getElementById(
                "position"
            ).innerHTML =
                "📭 لا توجد صفقة مفتوحة";

        }

        document.getElementById(
            "stats"
        ).innerHTML =

            "الصفقات: "
            + data.trades
            + "<br>"

            + "الرابحة: "
            + data.wins
            + "<br>"

            + "الخاسرة: "
            + data.losses
            + "<br><br>"

            + "أفضل فرصة: "
            + (
                data.best_symbol
                || "-"
            )
            + "<br>"

            + "التغير: "
            + (
                data.best_change !== null
                && data.best_change !== undefined
                ?
                data.best_change.toFixed(2)
                + "%"
                :
                "-"
            );

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
# الصفحة الرئيسية
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HTML
    )


# ============================================================
# API
# ============================================================

@app.route("/api/status")
def api_status():

    with position_lock:

        position = state[
            "position"
        ]

        if position:

            position = dict(
                position
            )

    return jsonify({

        "running":
            state["running"],

        "position":
            position,

        "last_scan":
            state["last_scan"],

        "last_error":
            state["last_error"],

        "best_symbol":
            state["best_symbol"],

        "best_change":
            state["best_change"],

        "trades":
            state["trades"],

        "wins":
            state["wins"],

        "losses":
            state["losses"]

    })


# ============================================================
# Main
# ============================================================

def main():

    print()
    print(
        "=============================="
    )
    print(
        "🚀 تشغيل V6 FAST"
    )
    print(
        "=============================="
    )

    print(
        "🌐 الموقع يعمل على PORT"
    )

    print()

    print(
        "=============================="
    )
    print(
        "🤖 مضارب أبو سعود V6 FAST"
    )
    print(
        "=============================="
    )

    print()

    # محرك التداول
    trading_thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    trading_thread.start()

    # مراقبة الاتصال
    monitor_thread = threading.Thread(
        target=connection_monitor,
        daemon=True
    )

    monitor_thread.start()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )


# ============================================================
# تشغيل
# ============================================================

if __name__ == "__main__":

    main()
