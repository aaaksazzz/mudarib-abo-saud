import os
import time
import hmac
import hashlib
import urllib.parse
import requests
import threading
from flask import Flask, jsonify

# ============================================================
# مضارب أبو سعود V2
# Binance Spot - الاتصال القديم
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

BASE_URL = "https://api.binance.com"

# ============================================================
# الاستراتيجية
# ============================================================

TIMEFRAME = "15m"
EMA_PERIOD = 200
BREAKOUT_PERIOD = 20
VOLUME_MULTIPLIER = 1.5

MIN_MOVE = 0.005
MAX_MOVE = 0.04

STOP_LOSS = -0.02
INITIAL_TARGET = 0.012

LOCK_TRIGGER = 0.012
LOCK_PROFIT = 0.012
PROFIT_STEP = 0.01
TARGET_DISTANCE = 0.012

MIN_USDT = 5.0

# ============================================================

app = Flask(__name__)

symbols = []
symbol_info = {}
market_data = {}

trade = None

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0
}

status = {
    "running": False,
    "binance": False,
    "websocket": False,
    "last_scan": None,
    "error": None
}

lock = threading.Lock()


# ============================================================
# REST Binance
# ============================================================

def binance_request(
    method,
    path,
    params=None,
    signed=False
):

    if params is None:
        params = {}

    params = params.copy()

    if signed:

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

        params["signature"] = signature

    headers = {}

    if API_KEY:
        headers["X-MBX-APIKEY"] = API_KEY

    url = BASE_URL + path

    r = requests.request(
        method,
        url,
        params=params,
        headers=headers,
        timeout=20
    )

    if r.status_code >= 400:

        print(
            f"❌ Binance HTTP {r.status_code}: "
            f"{r.text[:1000]}",
            flush=True
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# اختبار Binance
# ============================================================

def test_binance():

    try:

        data = binance_request(
            "GET",
            "/api/v3/time"
        )

        if "serverTime" in data:

            status["binance"] = True

            print(
                "🟢 Binance متصل",
                flush=True
            )

            return True

    except Exception as e:

        status["binance"] = False
        status["error"] = str(e)

        print(
            f"🔴 Binance غير متصل: {e}",
            flush=True
        )

    return False


# ============================================================
# Exchange Info
# ============================================================

def load_symbols():

    global symbols

    data = binance_request(
        "GET",
        "/api/v3/exchangeInfo"
    )

    result = []

    for s in data.get("symbols", []):

        try:

            if s["status"] != "TRADING":
                continue

            if s["quoteAsset"] != "USDT":
                continue

            if not s.get(
                "isSpotTradingAllowed",
                False
            ):
                continue

            info = {
                "baseAsset": s["baseAsset"],
                "stepSize": 0.0,
                "minQty": 0.0,
                "minNotional": 5.0
            }

            for f in s.get("filters", []):

                if f["filterType"] == "LOT_SIZE":

                    info["stepSize"] = float(
                        f["stepSize"]
                    )

                    info["minQty"] = float(
                        f["minQty"]
                    )

                if f["filterType"] in (
                    "MIN_NOTIONAL",
                    "NOTIONAL"
                ):

                    info["minNotional"] = float(
                        f.get(
                            "minNotional",
                            5
                        )
                    )

            symbol_info[s["symbol"]] = info

            result.append(
                s["symbol"]
            )

        except Exception:
            pass

    symbols = sorted(result)

    print(
        f"✅ تم تحميل {len(symbols)} عملة Spot",
        flush=True
    )


# ============================================================
# Klines
# ============================================================

def get_klines(
    symbol,
    interval="15m",
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


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    ema_value = (
        sum(values[:period])
        / period
    )

    multiplier = 2 / (period + 1)

    for price in values[period:]:

        ema_value = (
            (price - ema_value)
            * multiplier
        ) + ema_value

    return ema_value


# ============================================================
# تحليل 1H
# ============================================================

def confirmation_1h(symbol):

    try:

        data = get_klines(
            symbol,
            "1h",
            210
        )

        if len(data) < 205:
            return False

        closes = [
            float(x[4])
            for x in data[:-1]
        ]

        price = closes[-1]

        ema200 = calculate_ema(
            closes[-210:],
            200
        )

        if ema200 is None:
            return False

        return price > ema200

    except Exception as e:

        print(
            f"⚠️ 1H {symbol}: {e}",
            flush=True
        )

        return False


# ============================================================
# تحليل العملة
# ============================================================

def analyze(symbol):

    try:

        data = get_klines(
            symbol,
            "15m",
            210
        )

        if len(data) < 205:
            return None

        candles = data[:-1]

        closes = [
            float(x[4])
            for x in candles
        ]

        highs = [
            float(x[2])
            for x in candles
        ]

        volumes = [
            float(x[5])
            for x in candles
        ]

        price = closes[-1]

        ema200 = calculate_ema(
            closes[-200:],
            200
        )

        if ema200 is None:
            return None

        # السعر فوق EMA200
        if price <= ema200:
            return None

        # مقاومة آخر 20 شمعة
        resistance = max(
            highs[-21:-1]
        )

        # اختراق
        if price <= resistance:
            return None

        # متوسط الحجم
        avg_volume = (
            sum(volumes[-21:-1])
            / 20
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            volumes[-1]
            / avg_volume
        )

        if volume_ratio < VOLUME_MULTIPLIER:
            return None

        # حركة السعر
        previous = closes[-2]

        move = (
            price - previous
        ) / previous

        if move < MIN_MOVE:
            return None

        if move > MAX_MOVE:
            return None

        # تأكيد الساعة
        if not confirmation_1h(symbol):
            return None

        return {
            "symbol": symbol,
            "price": price,
            "ema200": ema200,
            "resistance": resistance,
            "volume_ratio": volume_ratio,
            "move": move
        }

    except Exception as e:

        print(
            f"⚠️ تحليل {symbol}: "
            f"{str(e)[:200]}",
            flush=True
        )

        return None


# ============================================================
# الرصيد
# ============================================================

def get_account():

    return binance_request(
        "GET",
        "/api/v3/account",
        signed=True
    )


def get_usdt():

    account = get_account()

    for b in account.get(
        "balances",
        []
    ):

        if b["asset"] == "USDT":

            return float(
                b["free"]
            )

    return 0.0


# ============================================================
# السعر
# ============================================================

def get_price(symbol):

    data = binance_request(
        "GET",
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ============================================================
# شراء
# ============================================================

def buy(symbol, amount):

    print(
        f"🟢 شراء {symbol} "
        f"| {amount:.2f} USDT",
        flush=True
    )

    return binance_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{amount:.2f}"
        },
        signed=True
    )


# ============================================================
# فتح الصفقة
# ============================================================

def open_trade(signal):

    global trade

    with lock:

        if trade is not None:
            return

        balance = get_usdt()

        if balance < MIN_USDT:

            print(
                f"⚠️ الرصيد {balance:.2f} USDT",
                flush=True
            )

            return

        amount = balance * 0.999

        result = buy(
            signal["symbol"],
            amount
        )

        qty = float(
            result.get(
                "executedQty",
                0
            )
        )

        quote = float(
            result.get(
                "cummulativeQuoteQty",
                amount
            )
        )

        if qty <= 0:
            return

        entry = quote / qty

        trade = {
            "symbol": signal["symbol"],
            "entry": entry,
            "qty": qty,
            "current": entry,
            "profit": 0.0,
            "stop": entry * (
                1 + STOP_LOSS
            ),
            "target": entry * (
                1 + INITIAL_TARGET
            ),
            "locked_profit": 0.0,
            "target_level": 0,
            "status": "OPEN",
            "opened_at": time.time()
        }

        stats["trades"] += 1

        print(
            f"✅ دخول {signal['symbol']}",
            flush=True
        )

        print(
            f"💰 Entry: {entry}",
            flush=True
        )

        print(
            f"🛑 SL: {trade['stop']}",
            flush=True
        )

        print(
            f"🎯 TP: {trade['target']}",
            flush=True
        )


# ============================================================
# الرصيد من الأصل
# ============================================================

def get_asset_balance(asset):

    account = get_account()

    for b in account.get(
        "balances",
        []
    ):

        if b["asset"] == asset:

            return (
                float(b["free"])
                + float(b["locked"])
            )

    return 0.0


# ============================================================
# إغلاق الصفقة
# ============================================================

def close_trade(reason):

    global trade

    if trade is None:
        return

    symbol = trade["symbol"]

    try:

        asset = symbol.replace(
            "USDT",
            ""
        )

        qty = get_asset_balance(
            asset
        )

        info = symbol_info.get(
            symbol,
            {}
        )

        step = info.get(
            "stepSize",
            0
        )

        if step > 0:

            qty = (
                int(qty / step)
                * step
            )

        if qty <= 0:
            return

        print(
            f"🔴 إغلاق {symbol} | {reason}",
            flush=True
        )

        binance_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": f"{qty:.12f}"
            },
            signed=True
        )

        price = get_price(
            symbol
        )

        profit = (
            price - trade["entry"]
        ) / trade["entry"]

        stats["profit"] += profit

        if profit >= 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

        print(
            f"✅ النتيجة: "
            f"{profit * 100:.2f}%",
            flush=True
        )

        trade = None

    except Exception as e:

        print(
            f"❌ فشل الإغلاق: {e}",
            flush=True
        )


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_trade():

    global trade

    if trade is None:
        return

    try:

        symbol = trade["symbol"]

        price = get_price(
            symbol
        )

        entry = trade["entry"]

        profit = (
            price - entry
        ) / entry

        trade["current"] = price
        trade["profit"] = profit

        # وقف -2%
        if profit <= STOP_LOSS:

            close_trade(
                "STOP LOSS -2%"
            )

            return

        # تأمين الربح
        if profit >= LOCK_TRIGGER:

            level = int(
                (
                    profit
                    - LOCK_TRIGGER
                )
                / PROFIT_STEP
            )

            locked = (
                LOCK_PROFIT
                + level
                * PROFIT_STEP
            )

            if locked > trade["locked_profit"]:

                trade["locked_profit"] = locked

                trade["target_level"] = (
                    level + 1
                )

                trade["stop"] = (
                    entry
                    * (1 + locked)
                )

                trade["target"] = (
                    entry
                    * (
                        1
                        + locked
                        + TARGET_DISTANCE
                    )
                )

                print(
                    f"🔒 تأمين "
                    f"{locked * 100:.2f}%",
                    flush=True
                )

        # وقف الربح
        if (
            trade["locked_profit"] > 0
            and price <= trade["stop"]
        ):

            close_trade(
                "LOCK PROFIT"
            )

            return

        # الهدف
        if price >= trade["target"]:

            close_trade(
                "TARGET"
            )

    except Exception as e:

        print(
            f"⚠️ إدارة الصفقة: {e}",
            flush=True
        )


# ============================================================
# فحص السوق
# ============================================================

def scanner():

    while True:

        try:

            if trade is None:

                print(
                    "🔍 بدء الفحص...",
                    flush=True
                )

                for i, symbol in enumerate(
                    symbols
                ):

                    signal = analyze(
                        symbol
                    )

                    if signal:

                        print(
                            f"🔥 إشارة 9/9 "
                            f"{symbol}",
                            flush=True
                        )

                        open_trade(
                            signal
                        )

                        break

                    if i % 50 == 0:

                        print(
                            f"🔍 [{i+1}/{len(symbols)}] "
                            f"{symbol}",
                            flush=True
                        )

            status["last_scan"] = (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

        except Exception as e:

            status["error"] = str(e)

            print(
                f"⚠️ Scanner: {e}",
                flush=True
            )

        time.sleep(180)


# ============================================================
# إدارة الصفقة كل 5 ثواني
# ============================================================

def trade_manager():

    while True:

        try:

            if trade is not None:
                manage_trade()

        except Exception as e:

            print(
                f"⚠️ Manager: {e}",
                flush=True
            )

        time.sleep(5)


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

<title>مضارب أبو سعود V2</title>

<style>

body{
    background:#101216;
    color:white;
    font-family:Arial;
    margin:0;
}

.container{
    max-width:800px;
    margin:auto;
    padding:20px;
}

.card{
    background:#191c22;
    padding:18px;
    margin-bottom:15px;
    border-radius:15px;
}

.row{
    display:flex;
    justify-content:space-between;
    padding:10px 0;
    border-bottom:1px solid #292d35;
}

.green{
    color:#35e58b;
}

.red{
    color:#ff5555;
}

</style>

</head>

<body>

<div class="container">

<div class="card">

<h1>🤖 مضارب أبو سعود V2</h1>

<div id="status">
جاري التحميل...
</div>

</div>

<div class="card">

<h2>💰 Binance</h2>

<div class="row">
<span>الاتصال</span>
<span id="binance">...</span>
</div>

<div class="row">
<span>الرصيد</span>
<span id="balance">...</span>
</div>

</div>

<div class="card">

<h2>📊 الصفقة</h2>

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
<span>الرابحة</span>
<span id="wins">0</span>
</div>

<div class="row">
<span>الخاسرة</span>
<span id="losses">0</span>
</div>

<div class="row">
<span>نسبة النجاح</span>
<span id="winrate">0%</span>
</div>

<div class="row">
<span>النتيجة</span>
<span id="profit">0%</span>
</div>

</div>

</div>

<script>

async function update(){

    try{

        const r =
            await fetch("/api/dashboard");

        const d =
            await r.json();

        document.getElementById(
            "binance"
        ).innerHTML =
            d.binance
            ? '<span class="green">🟢 متصل</span>'
            : '<span class="red">🔴 غير متصل</span>';

        document.getElementById(
            "balance"
        ).innerText =
            d.balance.toFixed(2)
            + " USDT";

        document.getElementById(
            "trades"
        ).innerText =
            d.stats.trades;

        document.getElementById(
            "wins"
        ).innerText =
            d.stats.wins;

        document.getElementById(
            "losses"
        ).innerText =
            d.stats.losses;

        document.getElementById(
            "winrate"
        ).innerText =
            d.winrate.toFixed(2)
            + "%";

        document.getElementById(
            "profit"
        ).innerText =
            (
                d.stats.profit * 100
            ).toFixed(2)
            + "%";

        if(d.trade){

            const t = d.trade;

            document.getElementById(
                "trade"
            ).innerHTML =

                "<b>🪙 "
                + t.symbol
                + "</b>" +

                "<div class='row'><span>الدخول</span><span>"
                + t.entry
                + "</span></div>" +

                "<div class='row'><span>السعر</span><span>"
                + t.current
                + "</span></div>" +

                "<div class='row'><span>الربح</span><span>"
                + (
                    t.profit * 100
                ).toFixed(2)
                + "%</span></div>" +

                "<div class='row'><span>الوقف</span><span>"
                + t.stop
                + "</span></div>" +

                "<div class='row'><span>الهدف</span><span>"
                + t.target
                + "</span></div>" +

                "<div class='row'><span>التأمين</span><span>"
                + (
                    t.locked_profit * 100
                ).toFixed(2)
                + "%</span></div>";

        }else{

            document.getElementById(
                "trade"
            ).innerText =
                "⚪ لا توجد صفقة";

        }

    }catch(e){

        document.getElementById(
            "status"
        ).innerHTML =
            '<span class="red">🔴 خطأ</span>';

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
# API Dashboard
# ============================================================

@app.route("/api/dashboard")
def dashboard():

    balance = 0.0

    try:
        balance = get_usdt()
    except Exception:
        pass

    total = (
        stats["wins"]
        + stats["losses"]
    )

    winrate = (
        stats["wins"]
        / total
        * 100
        if total
        else 0
    )

    return jsonify({

        "running":
            status["running"],

        "binance":
            status["binance"],

        "websocket":
            status["websocket"],

        "balance":
            balance,

        "trade":
            trade,

        "stats":
            stats,

        "winrate":
            winrate,

        "last_scan":
            status["last_scan"],

        "error":
            status["error"]
    })


# ============================================================
# Health
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "running": status["running"],
        "binance": status["binance"]
    })


# ============================================================
# تشغيل
# ============================================================

def start_bot():

    print(
        "=" * 60,
        flush=True
    )

    print(
        "🤖 مضارب أبو سعود V2",
        flush=True
    )

    print(
        "🔗 Binance: api.binance.com",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    if not API_KEY or not API_SECRET:

        print(
            "❌ BINANCE_API_KEY أو "
            "BINANCE_API_SECRET غير موجود",
            flush=True
        )

        return

    if not test_binance():

        print(
            "❌ Binance REST غير متاح",
            flush=True
        )

        return

    try:

        load_symbols()

    except Exception as e:

        print(
            f"❌ فشل تحميل العملات: {e}",
            flush=True
        )

        return

    status["running"] = True

    threading.Thread(
        target=scanner,
        daemon=True
    ).start()

    threading.Thread(
        target=trade_manager,
        daemon=True
    ).start()

    print(
        "🟢 البوت بدأ العمل",
        flush=True
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    threading.Thread(
        target=start_bot,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10000"
            )
        ),
        threaded=True
    )
