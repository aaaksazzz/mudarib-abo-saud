# ============================================================
# مضارب أبو سعود 🤖
# Binance Spot - V6 FAST
# ============================================================

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
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# الإعدادات
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"

TITLE = "مضارب أبو سعود 🤖"

# استراتيجية V6
TIMEFRAME = "15m"
MIN_CHANGE_15M = 1.0

EMA_PERIOD = 200

# حماية الربح
PROTECTION_START = 1.0
TRAILING_PERCENT = 0.50

# الفحص
POSITION_CHECK_SECONDS = 30
SCAN_INTERVAL = 60

# أقل قيمة نعتبرها صفقة
MIN_POSITION_USDT = 2.0

# شراء
BUY_PERCENT = 99.9

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

# ============================================================
# حالة البوت
# ============================================================

bot_status = {
    "running": True,
    "position": None,
    "entry_price": 0,
    "current_price": 0,
    "profit_percent": 0,
    "profit_usdt": 0,
    "protection": False,
    "trailing_price": 0,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_profit": 0,
    "last_scan": "",
    "last_error": "",
    "message": "بدء التشغيل"
}

current_position = None
symbols_cache = []
symbols_cache_time = 0

exchange_info_cache = None
exchange_info_cache_time = 0

position_check_ok = False

# ============================================================
# Exceptions
# ============================================================

class BinanceRateLimit(Exception):
    pass


class BinanceTemporaryError(Exception):
    pass


# ============================================================
# HTTP helpers
# ============================================================

session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY or "",
    "User-Agent": "Mudarib-Abo-Saud-V6"
})


def public_get(path, params=None, timeout=15):
    url = BASE + path

    r = session.get(
        url,
        params=params or {},
        timeout=timeout
    )

    if r.status_code == 429:
        raise BinanceRateLimit("429 Too Many Requests")

    if r.status_code >= 500:
        raise BinanceTemporaryError(
            f"{r.status_code} Binance Server Error"
        )

    r.raise_for_status()

    return r.json()


def signed_request(method, path, params=None, timeout=15):
    if not API_KEY or not API_SECRET:
        raise Exception("BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة")

    params = dict(params or {})

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE + path + "?" + query

    if method.upper() == "GET":
        r = session.get(url, timeout=timeout)
    elif method.upper() == "POST":
        r = session.post(url, timeout=timeout)
    elif method.upper() == "DELETE":
        r = session.delete(url, timeout=timeout)
    else:
        raise Exception("HTTP method غير مدعوم")

    if r.status_code == 429:
        raise BinanceRateLimit("429 Too Many Requests")

    if r.status_code >= 500:
        raise BinanceTemporaryError(
            f"{r.status_code} Binance Server Error"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# Binance
# ============================================================

def get_account():
    return signed_request(
        "GET",
        "/api/v3/account"
    )


def get_price(symbol):
    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


def get_klines(symbol, interval, limit=200):
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

def calculate_ema(values, period=200):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


# ============================================================
# Exchange Info
# ============================================================

def load_exchange_info(force=False):

    global exchange_info_cache
    global exchange_info_cache_time

    now = time.time()

    if (
        exchange_info_cache is not None
        and not force
        and now - exchange_info_cache_time < 1800
    ):
        return exchange_info_cache

    exchange_info_cache = public_get(
        "/api/v3/exchangeInfo"
    )

    exchange_info_cache_time = now

    return exchange_info_cache


def get_valid_usdt_symbols():

    global symbols_cache
    global symbols_cache_time

    now = time.time()

    if (
        symbols_cache
        and now - symbols_cache_time < 1800
    ):
        return symbols_cache

    info = load_exchange_info()

    result = []

    for s in info.get("symbols", []):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get("isSpotTradingAllowed") is False:
            continue

        symbol = s.get("symbol")

        if symbol:
            result.append(symbol)

    symbols_cache = result
    symbols_cache_time = now

    print(f"📚 العملات المتاحة: {len(result)}")

    return result


def is_valid_symbol(symbol):

    try:
        symbols = get_valid_usdt_symbols()

        return symbol in symbols

    except Exception:
        return False


# ============================================================
# Filters
# ============================================================

def get_symbol_filters(symbol):

    info = load_exchange_info()

    for s in info.get("symbols", []):

        if s.get("symbol") != symbol:
            continue

        result = {
            "stepSize": 0.000001,
            "minQty": 0,
            "minNotional": 5
        }

        for f in s.get("filters", []):

            if f["filterType"] == "LOT_SIZE":
                result["stepSize"] = float(
                    f["stepSize"]
                )

                result["minQty"] = float(
                    f["minQty"]
                )

            elif f["filterType"] == "MIN_NOTIONAL":
                result["minNotional"] = float(
                    f.get("minNotional", 5)
                )

            elif f["filterType"] == "NOTIONAL":
                result["minNotional"] = float(
                    f.get("minNotional", 5)
                )

        return result

    return {
        "stepSize": 0.000001,
        "minQty": 0,
        "minNotional": 5
    }


def round_step(value, step):

    if step <= 0:
        return value

    value_dec = Decimal(str(value))
    step_dec = Decimal(str(step))

    result = (
        value_dec // step_dec
    ) * step_dec

    return float(
        result.quantize(
            step_dec,
            rounding=ROUND_DOWN
        )
    )


# ============================================================
# اكتشاف الصفقة
# ============================================================

def find_open_position():

    global position_check_ok

    try:

        account = get_account()

        balances = account.get("balances", [])

        candidates = []

        # ----------------------------------------------------
        # نبحث فقط عن الأصول التي عند المستخدم
        # ----------------------------------------------------

        for b in balances:

            asset = b.get("asset")

            if not asset:
                continue

            if asset == "USDT":
                continue

            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))

            total = free + locked

            if total <= 0:
                continue

            # تجاهل أرصدة صغيرة جداً
            candidates.append(
                (asset, total)
            )

        # ----------------------------------------------------
        # نفحص كل أصل بهدوء
        # ----------------------------------------------------

        for asset, quantity in candidates:

            symbol = asset + "USDT"

            # مهم:
            # لو الزوج غير موجود مثل ETHWUSDT
            # نتجاهله ونكمل
            if not is_valid_symbol(symbol):
                print(
                    f"⏭️ تجاهل {symbol} - زوج غير صالح"
                )
                continue

            try:

                price = get_price(symbol)

            except requests.exceptions.HTTPError as e:

                # 400 = الزوج غير صالح
                response = getattr(e, "response", None)

                if response is not None:
                    if response.status_code == 400:
                        print(
                            f"⏭️ تجاهل {symbol} - Binance رفض الزوج"
                        )
                        continue

                raise

            except BinanceRateLimit:
                raise

            except Exception as e:

                print(
                    f"⏭️ تعذر سعر {symbol}: {e}"
                )

                continue

            value = quantity * price

            # تجاهل الغبار
            if value < MIN_POSITION_USDT:
                continue

            entry = calculate_entry(symbol)

            if entry is None or entry <= 0:
                entry = price

            profit_percent = (
                (price - entry)
                / entry
            ) * 100

            profit_usdt = (
                price - entry
            ) * quantity

            position = {
                "symbol": symbol,
                "quantity": quantity,
                "entry": entry,
                "price": price,
                "profit_percent": profit_percent,
                "profit_usdt": profit_usdt
            }

            position_check_ok = True

            return position

        # ----------------------------------------------------
        # تم التحقق فعلياً ولا توجد صفقة
        # ----------------------------------------------------

        position_check_ok = True

        return None

    except BinanceRateLimit:

        position_check_ok = False

        raise

    except Exception:

        position_check_ok = False

        raise


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
                "limit": 100
            }
        )

        total_qty = 0.0
        total_cost = 0.0

        for trade in trades:

            if not trade.get("isBuyer"):
                continue

            qty = float(
                trade.get("qty", 0)
            )

            price = float(
                trade.get("price", 0)
            )

            total_qty += qty
            total_cost += qty * price

        if total_qty <= 0:
            return None

        return total_cost / total_qty

    except BinanceRateLimit:
        raise

    except Exception as e:

        print(
            f"⚠️ تعذر حساب دخول {symbol}: {e}"
        )

        return None


# ============================================================
# فحص العملة - استراتيجية V6
# ============================================================

def analyze_symbol(symbol):

    try:

        # ----------------------------------------------------
        # 15 دقيقة
        # ----------------------------------------------------

        candles15 = get_klines(
            symbol,
            "15m",
            200
        )

        if len(candles15) < EMA_PERIOD:
            return None

        closes15 = [
            float(x[4])
            for x in candles15
        ]

        current_price = closes15[-1]

        previous_price = closes15[-2]

        if previous_price <= 0:
            return None

        change15 = (
            (current_price - previous_price)
            / previous_price
        ) * 100

        # لازم الحركة تكون فوق 1%
        if change15 < MIN_CHANGE_15M:
            return None

        # EMA 200 - 15m
        ema15 = calculate_ema(
            closes15,
            EMA_PERIOD
        )

        if ema15 is None:
            return None

        if current_price <= ema15:
            return None

        # ----------------------------------------------------
        # 5 دقائق EMA 200
        # ----------------------------------------------------

        candles5 = get_klines(
            symbol,
            "5m",
            200
        )

        if len(candles5) < EMA_PERIOD:
            return None

        closes5 = [
            float(x[4])
            for x in candles5
        ]

        ema5 = calculate_ema(
            closes5,
            EMA_PERIOD
        )

        if ema5 is None:
            return None

        if current_price <= ema5:
            return None

        # ----------------------------------------------------
        # 1 دقيقة EMA 200
        # ----------------------------------------------------

        candles1 = get_klines(
            symbol,
            "1m",
            200
        )

        if len(candles1) < EMA_PERIOD:
            return None

        closes1 = [
            float(x[4])
            for x in candles1
        ]

        ema1 = calculate_ema(
            closes1,
            EMA_PERIOD
        )

        if ema1 is None:
            return None

        if current_price <= ema1:
            return None

        # ----------------------------------------------------
        # النتيجة
        # ----------------------------------------------------

        return {
            "symbol": symbol,
            "price": current_price,
            "change": change15,
            "ema1": ema1,
            "ema5": ema5,
            "ema15": ema15
        }

    except BinanceRateLimit:
        raise

    except Exception as e:

        print(
            f"⚠️ {symbol}: {e}"
        )

        return None


# ============================================================
# فحص السوق
# ============================================================

def scan_market():

    symbols = get_valid_usdt_symbols()

    best = None

    total = len(symbols)

    print(
        f"🔎 بدء فحص {total} عملة..."
    )

    for index, symbol in enumerate(symbols, 1):

        print(
            f"\r[{index}/{total}] 🔍 {symbol}",
            end="",
            flush=True
        )

        result = analyze_symbol(symbol)

        if result is None:
            continue

        if best is None:

            best = result

        elif result["change"] > best["change"]:

            best = result

    print()

    if best:

        print(
            f"🏆 الأفضل: {best['symbol']} "
            f"| حركة 15m: {best['change']:.2f}% "
            f"| السعر: {best['price']}"
        )

    else:

        print(
            "📭 ما فيه عملة مطابقة للشروط"
        )

    bot_status["last_scan"] = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return best


# ============================================================
# شراء
# ============================================================

def buy_symbol(signal):

    symbol = signal["symbol"]

    try:

        account = get_account()

        usdt = 0.0

        for b in account.get("balances", []):

            if b.get("asset") == "USDT":

                usdt = float(
                    b.get("free", 0)
                )

                break

        if usdt <= 5:

            print(
                "❌ رصيد USDT غير كافي"
            )

            return None

        spend = (
            usdt * BUY_PERCENT / 100
        )

        filters = get_symbol_filters(
            symbol
        )

        price = get_price(symbol)

        quantity = spend / price

        quantity = round_step(
            quantity,
            filters["stepSize"]
        )

        if quantity <= 0:

            print(
                "❌ الكمية غير صالحة"
            )

            return None

        if quantity < filters["minQty"]:

            print(
                "❌ الكمية أقل من الحد الأدنى"
            )

            return None

        if quantity * price < filters["minNotional"]:

            print(
                "❌ قيمة الصفقة أقل من الحد الأدنى"
            )

            return None

        print(
            f"\n🟢 شراء {symbol}"
        )

        print(
            f"💰 المبلغ: {quantity * price:.2f} USDT"
        )

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": quantity
            }
        )

        time.sleep(2)

        actual_position = find_open_position()

        if actual_position:

            return actual_position

        executed_qty = float(
            order.get(
                "executedQty",
                quantity
            )
        )

        fills = order.get("fills", [])

        if fills:

            cost = sum(
                float(f["price"])
                * float(f["qty"])
                for f in fills
            )

            qty = sum(
                float(f["qty"])
                for f in fills
            )

            if qty > 0:

                entry = cost / qty

            else:

                entry = price

        else:

            entry = price

        return {
            "symbol": symbol,
            "quantity": executed_qty,
            "entry": entry,
            "price": price,
            "profit_percent": 0,
            "profit_usdt": 0
        }

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"❌ فشل الشراء: {e}"
        )

        bot_status["last_error"] = str(e)

        return None


# ============================================================
# بيع
# ============================================================

def sell_position(position):

    symbol = position["symbol"]

    try:

        quantity = position["quantity"]

        filters = get_symbol_filters(
            symbol
        )

        quantity = round_step(
            quantity,
            filters["stepSize"]
        )

        if quantity <= 0:

            print(
                "❌ كمية البيع غير صالحة"
            )

            return False

        print(
            f"\n🔴 بيع {symbol}"
        )

        order = signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": quantity
            }
        )

        profit = position.get(
            "profit_usdt",
            0
        )

        bot_status["total_trades"] += 1

        bot_status["total_profit"] += profit

        if profit >= 0:
            bot_status["wins"] += 1
        else:
            bot_status["losses"] += 1

        print(
            f"✅ تمت عملية البيع "
            f"| الربح: {profit:.4f} USDT"
        )

        return True

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"❌ فشل البيع: {e}"
        )

        bot_status["last_error"] = str(e)

        return False


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_position(position):

    global current_position

    symbol = position["symbol"]

    try:

        price = get_price(symbol)

        entry = position["entry"]

        quantity = position["quantity"]

        profit_percent = (
            (price - entry)
            / entry
        ) * 100

        profit_usdt = (
            price - entry
        ) * quantity

        position["price"] = price
        position["profit_percent"] = profit_percent
        position["profit_usdt"] = profit_usdt

        # ----------------------------------------------------
        # بدء حماية الربح
        # ----------------------------------------------------

        if profit_percent >= PROTECTION_START:

            if not position.get(
                "protection",
                False
            ):

                position["protection"] = True

                position["trailing_price"] = (
                    price
                    * (
                        1
                        - TRAILING_PERCENT / 100
                    )
                )

                print(
                    f"\n🛡️ بدأت حماية الربح "
                    f"{symbol}"
                    f" | ربح {profit_percent:.2f}%"
                )

            else:

                new_trailing = (
                    price
                    * (
                        1
                        - TRAILING_PERCENT / 100
                    )
                )

                old_trailing = position.get(
                    "trailing_price",
                    0
                )

                if new_trailing > old_trailing:

                    position["trailing_price"] = (
                        new_trailing
                    )

        # ----------------------------------------------------
        # تحقق من وقف الحماية
        # ----------------------------------------------------

        trailing_price = position.get(
            "trailing_price",
            0
        )

        if (
            position.get("protection")
            and trailing_price > 0
            and price <= trailing_price
        ):

            print(
                f"\n🛑 ضرب وقف حماية الربح "
                f"{symbol}"
                f" | السعر {price}"
                f" | الربح {profit_percent:.2f}%"
            )

            if sell_position(position):

                current_position = None

                bot_status["position"] = None
                bot_status["protection"] = False
                bot_status["trailing_price"] = 0

                return False

        # ----------------------------------------------------
        # تحديث الواجهة
        # ----------------------------------------------------

        bot_status["position"] = symbol
        bot_status["entry_price"] = entry
        bot_status["current_price"] = price
        bot_status["profit_percent"] = profit_percent
        bot_status["profit_usdt"] = profit_usdt
        bot_status["protection"] = position.get(
            "protection",
            False
        )
        bot_status["trailing_price"] = position.get(
            "trailing_price",
            0
        )

        print(
            f"📊 {symbol} | "
            f"{price:.8f} | "
            f"صافي {profit_percent:.2f}% | "
            f"ربح {profit_usdt:.4f} USDT"
        )

        return True

    except BinanceRateLimit:

        raise

    except Exception as e:

        print(
            f"⚠️ خطأ إدارة {symbol}: {e}"
        )

        bot_status["last_error"] = str(e)

        return True


# ============================================================
# Trading Engine
# ============================================================

def trading_engine():

    global current_position

    last_scan_time = 0

    print(
        "\n🤖 محرك التداول بدأ"
    )

    while True:

        try:

            # =================================================
            # أولاً: التحقق من وجود صفقة
            # =================================================

            try:

                detected = find_open_position()

            except BinanceRateLimit:

                print(
                    "⚠️ Binance 429 أثناء التحقق "
                    "— ننتظر بدون فحص"
                )

                bot_status["message"] = (
                    "انتظار بسبب Binance 429"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            except Exception as e:

                print(
                    f"⚠️ تعذر التأكد من الصفقة: {e}"
                )

                print(
                    "⚠️ ما قدرنا نتأكد من الصفقة — ننتظر"
                )

                bot_status["message"] = (
                    "تعذر التحقق من الصفقة"
                )

                # مهم جداً:
                # لا نفترض أنه لا توجد صفقة
                # ولا نبدأ Scan
                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # إذا فيه صفقة
            # =================================================

            if detected:

                current_position = detected

                bot_status["message"] = (
                    f"إدارة {detected['symbol']}"
                )

                print(
                    f"♻️ صفقة موجودة: "
                    f"{detected['symbol']}"
                )

                manage_position(
                    current_position
                )

                # لا تحميل عملات
                # لا Scan
                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # =================================================
            # لا توجد صفقة مؤكدة
            # =================================================

            if current_position:

                print(
                    "🏁 الصفقة السابقة انتهت"
                )

                current_position = None

                bot_status["position"] = None
                bot_status["entry_price"] = 0
                bot_status["current_price"] = 0
                bot_status["profit_percent"] = 0
                bot_status["profit_usdt"] = 0
                bot_status["protection"] = False
                bot_status["trailing_price"] = 0

            # =================================================
            # وقت الفحص
            # =================================================

            now = time.time()

            if (
                now - last_scan_time
                < SCAN_INTERVAL
            ):

                time.sleep(5)

                continue

            last_scan_time = now

            bot_status["message"] = (
                "فحص السوق"
            )

            # =================================================
            # تحميل العملات فقط إذا لا توجد صفقة
            # =================================================

            try:

                symbols = get_valid_usdt_symbols()

                print(
                    f"📚 الآن يتم تحميل العملات..."
                )

                print(
                    f"📚 عدد العملات: {len(symbols)}"
                )

            except BinanceRateLimit:

                print(
                    "⚠️ 429 أثناء تحميل العملات "
                    "— ننتظر"
                )

                time.sleep(60)

                continue

            except Exception as e:

                print(
                    f"⚠️ فشل تحميل العملات: {e}"
                )

                time.sleep(30)

                continue

            # =================================================
            # فحص السوق
            # =================================================

            try:

                signal = scan_market()

            except BinanceRateLimit:

                print(
                    "\n⚠️ Binance 429 أثناء الفحص "
                    "— ننتظر 60 ثانية"
                )

                time.sleep(60)

                continue

            except Exception as e:

                print(
                    f"\n⚠️ خطأ الفحص: {e}"
                )

                time.sleep(30)

                continue

            if not signal:

                time.sleep(10)

                continue

            # =================================================
            # تأكيد أخير قبل الشراء
            # =================================================

            try:

                confirmed = find_open_position()

            except Exception as e:

                print(
                    f"⚠️ تعذر التأكد قبل الشراء: {e}"
                )

                time.sleep(30)

                continue

            # إذا ظهر مركز أثناء الفحص
            if confirmed:

                print(
                    f"♻️ ظهرت صفقة "
                    f"{confirmed['symbol']} "
                    f"— إلغاء الشراء"
                )

                current_position = confirmed

                continue

            # =================================================
            # شراء
            # =================================================

            print(
                f"\n🎯 إشارة شراء: "
                f"{signal['symbol']}"
            )

            print(
                f"📈 حركة 15m: "
                f"{signal['change']:.2f}%"
            )

            try:

                new_position = buy_symbol(
                    signal
                )

            except BinanceRateLimit:

                print(
                    "⚠️ 429 أثناء الشراء "
                    "— ننتظر"
                )

                time.sleep(60)

                continue

            if new_position:

                current_position = new_position

                bot_status["position"] = (
                    new_position["symbol"]
                )

                print(
                    f"✅ تم الدخول "
                    f"{new_position['symbol']}"
                )

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            print(
                f"🔥 خطأ رئيسي في البوت: {e}"
            )

            bot_status["last_error"] = str(e)

            time.sleep(30)


# ============================================================
# Dashboard
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

body {
    background:#111;
    color:#fff;
    font-family:Arial;
    margin:0;
    padding:20px;
}

.card {
    background:#1d1d1d;
    border-radius:15px;
    padding:18px;
    margin-bottom:15px;
}

.title {
    font-size:26px;
    font-weight:bold;
}

.green {
    color:#00d26a;
}

.red {
    color:#ff4d4d;
}

.gray {
    color:#aaa;
}

.value {
    font-size:22px;
    margin-top:6px;
}

</style>

</head>

<body>

<div class="card">

<div class="title">
🤖 مضارب أبو سعود V6 FAST
</div>

<div class="gray">
Binance Spot
</div>

</div>


<div class="card">

<div>
الحالة
</div>

<div id="message"
class="value">
جاري التشغيل...
</div>

</div>


<div class="card">

<div>
الصفقة الحالية
</div>

<div id="position"
class="value">
لا توجد صفقة
</div>

</div>


<div class="card">

<div>
سعر الدخول
</div>

<div id="entry"
class="value">
-
</div>

</div>


<div class="card">

<div>
السعر الحالي
</div>

<div id="price"
class="value">
-
</div>

</div>


<div class="card">

<div>
الربح / الخسارة
</div>

<div id="profit"
class="value">
0%
</div>

</div>


<div class="card">

<div>
حماية الربح
</div>

<div id="protection"
class="value">
غير مفعلة
</div>

</div>


<div class="card">

<div>
إجمالي الصفقات
</div>

<div id="trades"
class="value">
0
</div>

</div>


<div class="card">

<div>
فوز / خسارة
</div>

<div id="wl"
class="value">
0 / 0
</div>

</div>


<div class="card">

<div>
إجمالي الربح
</div>

<div id="totalprofit"
class="value">
0 USDT
</div>

</div>


<script>

async function update() {

    try {

        const r = await fetch("/api/status");

        const d = await r.json();

        document.getElementById("message").innerText =
            d.message || "-";

        document.getElementById("position").innerText =
            d.position || "لا توجد صفقة";

        document.getElementById("entry").innerText =
            d.entry_price
            ? Number(d.entry_price).toFixed(8)
            : "-";

        document.getElementById("price").innerText =
            d.current_price
            ? Number(d.current_price).toFixed(8)
            : "-";

        const profit =
            Number(d.profit_percent || 0);

        const profitElement =
            document.getElementById("profit");

        profitElement.innerText =
            profit.toFixed(2) + "%";

        profitElement.className =
            "value " +
            (profit >= 0 ? "green" : "red");

        document.getElementById("protection").innerText =
            d.protection
            ? "🛡️ مفعلة عند " +
              Number(d.trailing_price || 0).toFixed(8)
            : "غير مفعلة";

        document.getElementById("trades").innerText =
            d.total_trades || 0;

        document.getElementById("wl").innerText =
            (d.wins || 0) +
            " / " +
            (d.losses || 0);

        document.getElementById("totalprofit").innerText =
            Number(d.total_profit || 0).toFixed(4)
            + " USDT";

    }

    catch(e) {

        console.log(e);

    }

}

update();

setInterval(update, 5000);

</script>

</body>

</html>
"""


@app.route("/")
def home():

    return render_template_string(
        HTML
    )


@app.route("/api/status")
def api_status():

    return jsonify(
        bot_status
    )


# ============================================================
# Binance connection monitor
# ============================================================

def connection_monitor():

    while True:

        try:

            get_account()

            bot_status["running"] = True

        except BinanceRateLimit:

            print(
                "⚠️ مراقب الاتصال: 429"
            )

        except Exception as e:

            bot_status["last_error"] = str(e)

        # لا نكثر طلبات account
        time.sleep(120)


# ============================================================
# Main
# ============================================================

def main():

    print()
    print("==============================")
    print("🚀 تشغيل V6 FAST")
    print("==============================")
    print("🌐 الموقع يعمل على 10000")
    print()
    print("==============================")
    print("🤖 مضارب أبو سعود V6 FAST")
    print("==============================")

    # محرك التداول
    threading.Thread(
        target=trading_engine,
        daemon=True
    ).start()

    # مراقب Binance
    threading.Thread(
        target=connection_monitor,
        daemon=True
    ).start()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )


if __name__ == "__main__":
    main()
