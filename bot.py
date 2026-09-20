# ============================================================
# مضارب أبو سعود V6 FAST 🤖
# Binance Spot + Dashboard
# إدارة الصفقة المفتوحة + تحريك وقف الحماية كل 1%
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

TITLE = "مضارب أبو سعود 🤖"

TIMEFRAME = "15m"

# استراتيجية الدخول - لا تغيير
MIN_CHANGE_15M = 1.0
EMA_PERIOD = 200

# إدارة الصفقة
PROTECTION_START = 1.0

# كل 1% ربح نرفع مستوى الحماية
PROTECTION_STEP = 1.0

# المسافة بين السعر الحالي ووقف الحماية
TRAILING_PERCENT = 0.50

# الفحص
POSITION_CHECK_SECONDS = 30
SCAN_INTERVAL = 60

# أقل قيمة صفقة نعتبرها صفقة حقيقية
MIN_POSITION_USDT = 2.0

BUY_PERCENT = 99.9

# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

# ============================================================
# الحالة
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

exchange_info_cache = None
exchange_info_time = 0

symbols_cache = []
symbols_cache_time = 0

# ============================================================
# أخطاء Binance
# ============================================================

class BinanceRateLimit(Exception):
    pass


class BinanceTemporaryError(Exception):
    pass


# ============================================================
# GET عام
# ============================================================

def public_get(path, params=None):

    url = BASE + path

    r = requests.get(
        url,
        params=params,
        timeout=20
    )

    if r.status_code == 429:
        raise BinanceRateLimit("Binance 429")

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
        raise BinanceRateLimit("Binance 429")

    if r.status_code >= 500:
        raise BinanceTemporaryError(
            f"Binance server error {r.status_code}"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# Account
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/api/v3/account"
    )


# ============================================================
# السعر
# ============================================================

def get_price(symbol):

    data = public_get(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


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

    exchange_info_cache = public_get(
        "/api/v3/exchangeInfo"
    )

    exchange_info_time = now

    return exchange_info_cache


# ============================================================
# العملات USDT
# ============================================================

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

        permissions = s.get("permissions", [])

        if permissions and "SPOT" not in permissions:
            continue

        result.append(s["symbol"])

    symbols_cache = result
    symbols_cache_time = now

    print(f"📋 العملات الصالحة: {len(result)}")

    return result


# ============================================================
# التحقق من زوج
# ============================================================

def is_valid_symbol(symbol):

    return symbol in get_valid_usdt_symbols()


# ============================================================
# Klines
# ============================================================

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

def calculate_ema(values, period):

    if len(values) < period:
        return None

    ema = sum(values[:period]) / period

    multiplier = 2 / (period + 1)

    for price in values[period:]:

        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


# ============================================================
# تحليل العملة
# ============================================================

def analyze_symbol(symbol):

    try:

        # ----------------------------
        # 15m
        # ----------------------------

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

        if ema15 is None or price <= ema15:
            return None

        # ----------------------------
        # 5m
        # ----------------------------

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

        if ema5 is None or price5 <= ema5:
            return None

        # ----------------------------
        # 1m
        # ----------------------------

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

        if ema1 is None or price1 <= ema1:
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
            f"⚠️ خطأ تحليل {symbol}: {e}"
        )

        return None


# ============================================================
# معلومات الفلاتر
# ============================================================

def get_symbol_filters(symbol):

    info = load_exchange_info()

    for s in info["symbols"]:

        if s["symbol"] != symbol:
            continue

        filters = {}

        for f in s["filters"]:

            if f["filterType"] == "LOT_SIZE":

                filters["stepSize"] = f["stepSize"]
                filters["minQty"] = f["minQty"]

            elif f["filterType"] == "MIN_NOTIONAL":

                filters["minNotional"] = f.get(
                    "minNotional",
                    "0"
                )

            elif f["filterType"] == "NOTIONAL":

                filters["minNotional"] = f.get(
                    "minNotional",
                    "0"
                )

        return filters

    return {}


# ============================================================
# تقريب الكمية
# ============================================================

def round_step(value, step):

    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        return float(value)

    result = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return float(result)


# ============================================================
# متوسط سعر الدخول من الصفقات
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

        for t in trades:

            qty = float(t["qty"])
            price = float(t["price"])

            if t["isBuyer"]:

                total_qty += qty
                total_cost += qty * price

            else:

                total_qty -= qty
                total_cost -= qty * price

        if total_qty <= 0:
            return None

        return total_cost / total_qty

    except Exception as e:

        print(
            f"⚠️ تعذر حساب الدخول {symbol}: {e}"
        )

        return None


# ============================================================
# اكتشاف الصفقة المفتوحة
# ============================================================

def find_open_position():

    account = get_account()

    balances = account.get("balances", [])

    for balance in balances:

        asset = balance["asset"]

        if asset == "USDT":
            continue

        free = float(balance["free"])
        locked = float(balance["locked"])

        amount = free + locked

        if amount <= 0:
            continue

        symbol = asset + "USDT"

        # تجاهل العملات التي لا يوجد لها زوج USDT
        if not is_valid_symbol(symbol):

            print(
                f"⏭️ تجاهل {symbol} - زوج غير صالح"
            )

            continue

        try:

            price = get_price(symbol)

        except requests.HTTPError as e:

            print(
                f"⚠️ تجاهل {symbol}: {e}"
            )

            continue

        value = amount * price

        if value < MIN_POSITION_USDT:
            continue

        entry = calculate_entry(symbol)

        if entry is None:
            entry = price

        return {
            "symbol": symbol,
            "qty": amount,
            "entry": entry,
            "price": price,
            "value": value,
            "peak": price,
            "protection": None
        }

    return None


# ============================================================
# شراء
# ============================================================

def buy_symbol(symbol):

    try:

        account = get_account()

        usdt = 0.0

        for b in account["balances"]:

            if b["asset"] == "USDT":

                usdt = float(b["free"])
                break

        if usdt < MIN_POSITION_USDT:
            print("⚠️ رصيد USDT غير كافي")
            return None

        amount_usdt = usdt * (
            BUY_PERCENT / 100
        )

        price = get_price(symbol)

        filters = get_symbol_filters(symbol)

        step = filters.get(
            "stepSize",
            "0.000001"
        )

        qty = amount_usdt / price

        qty = round_step(
            qty,
            step
        )

        if qty <= 0:
            print("⚠️ الكمية غير صالحة")
            return None

        print(
            f"🟢 شراء {symbol} | "
            f"السعر {price} | "
            f"الكمية {qty}"
        )

        result = signed_request(
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
                state["position"] = position

            print(
                f"✅ تم فتح الصفقة: "
                f"{position['symbol']}"
            )

            return position

        return None

    except BinanceRateLimit:

        raise

    except Exception as e:

        state["last_error"] = str(e)

        print(
            f"❌ خطأ شراء: {e}"
        )

        return None


# ============================================================
# بيع
# ============================================================

def sell_position(position):

    symbol = position["symbol"]

    try:

        account = get_account()

        qty = 0.0

        for b in account["balances"]:

            if b["asset"] == symbol.replace(
                "USDT",
                ""
            ):

                qty = float(b["free"])
                break

        if qty <= 0:
            return False

        filters = get_symbol_filters(symbol)

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
            f"🔴 بيع {symbol} | الكمية {qty}"
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

def manage_position(position):

    symbol = position["symbol"]

    try:

        price = get_price(symbol)

        entry = float(position["entry"])

        profit = (
            (price - entry)
            / entry
        ) * 100

        # أعلى سعر وصل له
        if price > position.get(
            "peak",
            0
        ):

            position["peak"] = price

        peak = position["peak"]

        # ----------------------------------------------------
        # حماية الربح
        # ----------------------------------------------------

        if profit >= PROTECTION_START:

            # المستوى الحالي للربح
            level = int(
                profit // PROTECTION_STEP
            )

            # أقل مستوى حماية
            if level < 1:
                level = 1

            # مثال:
            # +1%  -> مستوى 1
            # +2%  -> مستوى 2
            # +3%  -> مستوى 3
            # +4%  -> مستوى 4

            # وقف الحماية = قمة السعر ناقص 0.5%
            protection_price = peak * (
                1 - TRAILING_PERCENT / 100
            )

            old_protection = position.get(
                "protection"
            )

            # لا ننزل وقف الحماية أبدًا
            if (
                old_protection is None
                or protection_price > old_protection
            ):

                position["protection"] = (
                    protection_price
                )

                print(
                    f"🛡️ حماية {symbol} | "
                    f"ربح +{profit:.2f}% | "
                    f"المستوى +{level}% | "
                    f"وقف {protection_price:.8f}"
                )

        protection = position.get(
            "protection"
        )

        # ----------------------------------------------------
        # ضرب وقف الحماية
        # ----------------------------------------------------

        if (
            protection is not None
            and price <= protection
        ):

            print(
                f"🚨 ضرب وقف الحماية | "
                f"{symbol} | "
                f"ربح {profit:.2f}%"
            )

            sold = sell_position(
                position
            )

            if sold:

                if profit >= 0:
                    state["wins"] += 1
                else:
                    state["losses"] += 1

                with position_lock:
                    state["position"] = None

                print(
                    f"✅ انتهت الصفقة {symbol}"
                )

                return None

        position["price"] = price
        position["profit"] = profit

        with position_lock:
            state["position"] = position

        print(
            f"📊 {symbol} | "
            f"السعر {price:.8f} | "
            f"الربح {profit:+.2f}% | "
            f"الحماية "
            f"{protection if protection else 'لم تبدأ'}"
        )

        return position

    except BinanceRateLimit:

        raise

    except Exception as e:

        state["last_error"] = str(e)

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

    total = len(symbols)

    print(
        f"🚀 بدء فحص {total} عملة"
    )

    for index, symbol in enumerate(
        symbols,
        1
    ):

        print(
            f"🔍 [{index}/{total}] {symbol}",
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

        state["best_symbol"] = (
            best["symbol"]
        )

        state["best_change"] = (
            best["change"]
        )

        print(
            f"🎯 أفضل فرصة: "
            f"{best['symbol']} | "
            f"+{best['change']:.2f}%"
        )

    else:

        print(
            "❌ لا توجد فرصة مطابقة"
        )

    state["last_scan"] = time.time()

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
            # أول شيء: تحقق من الصفقة الموجودة
            # ==================================================

            try:

                position = find_open_position()

            except (
                BinanceRateLimit,
                BinanceTemporaryError,
                requests.RequestException
            ) as e:

                state["last_error"] = str(e)

                print(
                    f"⚠️ ما قدرنا نتأكد "
                    f"من الصفقة: {e}"
                )

                print(
                    "⏳ ننتظر بدون Scan"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            # ==================================================
            # إذا فيه صفقة → إدارة فقط
            # ==================================================

            if position:

                with position_lock:
                    state["position"] = position

                print(
                    f"💰 صفقة موجودة: "
                    f"{position['symbol']}"
                )

                while True:

                    try:

                        current = find_open_position()

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

                    # الصفقة انتهت
                    if current is None:

                        print(
                            "✅ لا توجد الصفقة "
                            "بعد الآن"
                        )

                        with position_lock:
                            state["position"] = None

                        break

                    # احتفظ بحالة الإدارة
                    current["peak"] = max(
                        position.get(
                            "peak",
                            current["price"]
                        ),
                        current["price"]
                    )

                    current["protection"] = (
                        position.get(
                            "protection"
                        )
                    )

                    position = current

                    position = manage_position(
                        position
                    )

                    if position is None:
                        break

                    time.sleep(
                        POSITION_CHECK_SECONDS
                    )

                # بعد انتهاء الصفقة
                # نبدأ دورة جديدة
                continue

            # ==================================================
            # لا توجد صفقة مؤكدة
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
            # فحص السوق
            # ==================================================

            best = scan_market()

            last_scan_time = time.time()

            if best is None:

                time.sleep(5)

                continue

            # ==================================================
            # تأكيد عدم وجود صفقة قبل الشراء
            # ==================================================

            try:

                check = find_open_position()

            except (
                BinanceRateLimit,
                BinanceTemporaryError,
                requests.RequestException
            ) as e:

                print(
                    f"⚠️ تعذر التأكد قبل الشراء: {e}"
                )

                time.sleep(10)

                continue

            if check:

                print(
                    "⚠️ ظهرت صفقة مفتوحة، "
                    "نلغي الشراء ونبدأ إدارتها"
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

            state["last_error"] = str(e)

            print(
                f"❌ خطأ في محرك التداول: {e}"
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

        time.sleep(120)


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

body{
    margin:0;
    background:#0f1115;
    color:white;
    font-family:Arial;
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

.value{
    font-size:24px;
    font-weight:bold;
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

<h3>💰 الصفقة</h3>

<div id="position">
لا توجد صفقة
</div>

</div>

<div class="card">

<h3>📊 الإحصائيات</h3>

<div id="stats">
</div>

</div>

</div>

<script>

async function update(){

    try{

        const r =
            await fetch("/api/status");

        const d =
            await r.json();

        document.getElementById(
            "status"
        ).innerHTML =
            d.running
            ? '<span class="green">🟢 البوت يعمل</span>'
            : '<span class="red">🔴 متوقف</span>';

        if(d.position){

            let p =
                d.position;

            let profit =
                p.profit || 0;

            document.getElementById(
                "position"
            ).innerHTML =

                "العملة: <b>"
                + p.symbol
                + "</b><br><br>"

                + "الدخول: "
                + Number(p.entry).toFixed(8)
                + "<br>"

                + "السعر: "
                + Number(p.price).toFixed(8)
                + "<br>"

                + "الربح: <span class='"
                + (profit >= 0
                    ? "green"
                    : "red")
                + "'>"
                + profit.toFixed(2)
                + "%</span><br><br>"

                + "وقف الحماية: "
                + (
                    p.protection
                    ? Number(
                        p.protection
                      ).toFixed(8)
                    : "لم يبدأ"
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
            + d.trades
            + "<br>"

            + "الرابحة: "
            + d.wins
            + "<br>"

            + "الخاسرة: "
            + d.losses
            + "<br><br>"

            + "أفضل فرصة: "
            + (
                d.best_symbol || "-"
            )
            + "<br>"

            + "التغير: "
            + (
                d.best_change
                ? d.best_change.toFixed(2)
                + "%"
                : "-"
            );

    }catch(e){

        console.log(e);

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
# API Status
# ============================================================

@app.route("/api/status")
def api_status():

    with position_lock:

        position = state["position"]

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
    print("==============================")
    print("🚀 تشغيل V6 FAST")
    print("==============================")
    print("🌐 الموقع يعمل على PORT")
    print()

    print("==============================")
    print("🤖 مضارب أبو سعود V6 FAST")
    print("==============================")
    print()

    t1 = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    t1.start()

    t2 = threading.Thread(
        target=connection_monitor,
        daemon=True
    )

    t2.start()

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


if __name__ == "__main__":
    main()
