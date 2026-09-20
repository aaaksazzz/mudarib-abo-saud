import os
import time
import json
import hmac
import hashlib
import urllib.parse
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN

import requests
from flask import Flask, jsonify, render_template_string

# ============================================================
# مضارب أبو سعود 🤖
# Binance Spot + Auto Trading + Dashboard
# الاستراتيجية:
# نزول 2% من إغلاق الشمعة السابقة -> شراء
# TP +2%
# SL -2%
# ============================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE = "https://api.binance.com"

TIMEFRAME = "15m"

DROP_PERCENT = 0.02
TP_PERCENT = 0.02
SL_PERCENT = 0.02

TRADE_USDT = 10.0

MIN_VOLUME = 1_000_000

DATA_FILE = "bot_data.json"

app = Flask(__name__)

session = requests.Session()

lock = threading.Lock()

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


# ============================================================
# حفظ البيانات
# ============================================================

def load_data():
    global state

    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)

        for key in [
            "today_profit",
            "week_profit",
            "month_profit",
            "total_profit",
            "winning_trades",
            "losing_trades",
            "total_trades",
            "current_trade"
        ]:
            if key in old:
                state[key] = old[key]

    except Exception:
        pass


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
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception:
        pass


# ============================================================
# Binance API
# ============================================================

def signed_request(method, endpoint, params=None):

    if params is None:
        params = {}

    params["timestamp"] = int(time.time() * 1000)

    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    query += "&signature=" + signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE + endpoint + "?" + query

    if method == "GET":
        r = session.get(url, headers=headers, timeout=20)

    elif method == "POST":
        r = session.post(url, headers=headers, timeout=20)

    elif method == "DELETE":
        r = session.delete(url, headers=headers, timeout=20)

    else:
        raise Exception("HTTP method غير معروف")

    if r.status_code != 200:
        raise Exception(r.text)

    return r.json()


def public_get(endpoint, params=None):
    r = session.get(
        BASE + endpoint,
        params=params,
        timeout=20
    )

    if r.status_code != 200:
        raise Exception(r.text)

    return r.json()


# ============================================================
# معلومات العملات
# ============================================================

exchange_info = {}


def load_exchange_info():

    global exchange_info

    data = public_get("/api/v3/exchangeInfo")

    for s in data["symbols"]:

        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s.get("isSpotTradingAllowed", False)
        ):
            exchange_info[s["symbol"]] = s


def get_step_size(symbol):

    info = exchange_info.get(symbol)

    if not info:
        return 0.000001

    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            return float(f["stepSize"])

    return 0.000001


def round_quantity(symbol, quantity):

    step = Decimal(str(get_step_size(symbol)))

    q = Decimal(str(quantity))

    rounded = (
        q / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return float(rounded)


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
            balances[x["asset"]] = total

    return balances


def update_balance():

    try:

        balances = get_balances()

        usdt = balances.get("USDT", 0)

        total = usdt

        for asset, amount in balances.items():

            if asset == "USDT":
                continue

            try:
                price = get_price(asset + "USDT")
                total += amount * price
            except:
                pass

        with lock:
            state["balance"] = round(usdt, 4)
            state["total_asset"] = round(total, 4)
            state["binance_connected"] = True

    except Exception as e:

        with lock:
            state["binance_connected"] = False
            state["error"] = str(e)


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
# العملات ذات الحجم فوق 1M
# ============================================================

def get_symbols():

    tickers = public_get(
        "/api/v3/ticker/24hr"
    )

    symbols = []

    for x in tickers:

        symbol = x["symbol"]

        volume = float(
            x.get("quoteVolume", 0)
        )

        if (
            symbol.endswith("USDT")
            and volume >= MIN_VOLUME
            and symbol in exchange_info
        ):
            symbols.append(symbol)

    return symbols


# ============================================================
# شموع 15 دقيقة
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
# اكتشاف الإشارة
# ============================================================

def check_signal(symbol):

    try:

        candles = get_last_klines(symbol)

        if len(candles) < 2:
            return None

        previous_close = float(
            candles[-2][4]
        )

        current_low = float(
            candles[-1][3]
        )

        entry = previous_close * (
            1 - DROP_PERCENT
        )

        if current_low <= entry:

            return {
                "symbol": symbol,
                "entry": entry,
                "previous_close": previous_close
            }

    except:
        pass

    return None


# ============================================================
# شراء
# ============================================================

def market_buy(symbol):

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{TRADE_USDT:.2f}"
        }
    )

    return order


# ============================================================
# بيع
# ============================================================

def market_sell(symbol, quantity):

    quantity = round_quantity(
        symbol,
        quantity
    )

    if quantity <= 0:
        return None

    order = signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": f"{quantity:.8f}"
        }
    )

    return order


# ============================================================
# تسجيل الصفقة
# ============================================================

def register_trade_result(profit):

    now = datetime.now()

    with lock:

        state["total_profit"] += profit

        state["total_trades"] += 1

        if profit >= 0:
            state["winning_trades"] += 1
        else:
            state["losing_trades"] += 1

        state["today_profit"] += profit
        state["week_profit"] += profit
        state["month_profit"] += profit

        save_data()


# ============================================================
# إدارة الصفقة
# ============================================================

def manage_trade():

    while True:

        try:

            with lock:
                trade = state["current_trade"]

            if not trade:
                time.sleep(2)
                continue

            symbol = trade["symbol"]

            price = get_price(symbol)

            entry = trade["entry"]

            tp = trade["tp"]

            sl = trade["sl"]

            quantity = trade["quantity"]

            profit_pct = (
                (price - entry)
                / entry
            ) * 100

            with lock:

                state["current_trade"]["price"] = price

                state["current_trade"]["profit_pct"] = profit_pct

                state["current_trade"]["profit_usdt"] = (
                    (price - entry)
                    * quantity
                )

            # الهدف
            if price >= tp:

                market_sell(
                    symbol,
                    quantity
                )

                profit = (
                    (tp - entry)
                    * quantity
                )

                register_trade_result(
                    profit
                )

                with lock:
                    state["current_trade"] = None
                    state["last_signal"] = (
                        f"{symbol} 🎯 تحقق الهدف"
                    )

                save_data()

            # الوقف
            elif price <= sl:

                market_sell(
                    symbol,
                    quantity
                )

                profit = (
                    (sl - entry)
                    * quantity
                )

                register_trade_result(
                    profit
                )

                with lock:
                    state["current_trade"] = None
                    state["last_signal"] = (
                        f"{symbol} 🛑 ضرب الوقف"
                    )

                save_data()

        except Exception as e:

            with lock:
                state["error"] = str(e)

        time.sleep(2)


# ============================================================
# البحث عن فرص
# ============================================================

def scanner():

    while True:

        try:

            # إذا فيه صفقة لا يفتح غيرها
            with lock:
                active = state["current_trade"]

            if active:
                time.sleep(5)
                continue

            symbols = get_symbols()

            for symbol in symbols:

                with lock:
                    if state["current_trade"]:
                        break

                signal = check_signal(symbol)

                if not signal:
                    continue

                # تأكد أن الرصيد كافي
                update_balance()

                with lock:
                    balance = state["balance"]

                if balance < TRADE_USDT:
                    continue

                # شراء
                order = market_buy(symbol)

                fills = order.get(
                    "fills",
                    []
                )

                if not fills:
                    continue

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

                if total_qty <= 0:
                    continue

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

                with lock:

                    state["current_trade"] = {
                        "symbol": symbol,
                        "entry": entry,
                        "price": entry,
                        "tp": tp,
                        "sl": sl,
                        "quantity": total_qty,
                        "profit_pct": 0,
                        "profit_usdt": 0,
                        "time": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    }

                    state["last_signal"] = (
                        f"{symbol} 🟢 شراء تلقائي"
                    )

                    state["error"] = ""

                save_data()

                break

        except Exception as e:

            with lock:
                state["error"] = str(e)

        time.sleep(10)


# ============================================================
# لوحة المتابعة
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
padding:18px;
}

.header{
background:linear-gradient(
135deg,
#102d4d,
#0b1728
);
padding:22px;
border-radius:22px;
margin-bottom:15px;
}

h1{
margin:0;
font-size:27px;
}

.status{
margin-top:10px;
color:#9fb5cc;
}

.grid{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:12px;
}

.card{
background:#0d1b2d;
border:1px solid #1c344f;
border-radius:17px;
padding:17px;
}

.label{
color:#8fa6bd;
font-size:13px;
}

.value{
font-size:23px;
font-weight:bold;
margin-top:8px;
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

.panel{
margin-top:15px;
background:#0d1b2d;
border:1px solid #1c344f;
border-radius:18px;
padding:18px;
}

.trade{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:10px;
}

.item{
background:#101f33;
padding:14px;
border-radius:12px;
}

table{
width:100%;
border-collapse:collapse;
}

td,th{
padding:11px;
border-bottom:
1px solid #1d3047;
text-align:right;
}

th{
color:#91a8bf;
}

.badge{
display:inline-block;
padding:7px 12px;
border-radius:20px;
background:#123b2a;
color:#40e49a;
}

.off{
background:#411b22;
color:#ff7180;
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

.container{
padding:10px;
}

.grid{
grid-template-columns:1fr;
}

.trade{
grid-template-columns:1fr;
}

h1{
font-size:22px;
}

}

</style>

</head>

<body>

<div class="container">

<div class="header">

<h1>
🤖 مضارب أبو سعود
</h1>

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
آخر تحديث: —
</div>

</div>


<div class="grid">

<div class="card">

<div class="label">
💰 رصيد USDT
</div>

<div id="balance"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
💼 قيمة الحساب
</div>

<div id="asset"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
📅 ربح اليوم
</div>

<div id="today"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
📆 ربح الأسبوع
</div>

<div id="week"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
🗓️ ربح الشهر
</div>

<div id="month"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
🏆 إجمالي الربح
</div>

<div id="totalprofit"
class="value">
—
</div>

</div>


<div class="card">

<div class="label">
🟢 الصفقات الرابحة
</div>

<div id="wins"
class="value green">
—
</div>

</div>


<div class="card">

<div class="label">
🔴 الصفقات الخاسرة
</div>

<div id="losses"
class="value red">
—
</div>

</div>


<div class="card">

<div class="label">
🎯 نسبة النجاح
</div>

<div id="winrate"
class="value blue">
—
</div>

</div>


<div class="card">

<div class="label">
🔢 إجمالي الصفقات
</div>

<div id="trades"
class="value">
—
</div>

</div>

</div>


<div class="panel">

<h2>
📈 الصفقة الحالية
</h2>

<div id="noTrade">
لا توجد صفقة مفتوحة
</div>

<div id="tradeBox"
style="display:none">

<div class="trade">

<div class="item">

<div class="label">
العملة
</div>

<div id="symbol"
class="value">
—
</div>

</div>


<div class="item">

<div class="label">
سعر الدخول
</div>

<div id="entry"
class="value">
—
</div>

</div>


<div class="item">

<div class="label">
السعر الحالي
</div>

<div id="price"
class="value">
—
</div>

</div>


<div class="item">

<div class="label">
🎯 الهدف
</div>

<div id="tp"
class="value green">
—
</div>

</div>


<div class="item">

<div class="label">
🛑 الوقف
</div>

<div id="sl"
class="value red">
—
</div>

</div>


<div class="item">

<div class="label">
نسبة الربح
</div>

<div id="profitpct"
class="value">
—
</div>

</div>


<div class="item">

<div class="label">
الربح / الخسارة
</div>

<div id="profitusdt"
class="value">
—
</div>

</div>


<div class="item">

<div class="label">
وقت الدخول
</div>

<div id="tradetime"
class="value">
—
</div>

</div>

</div>

</div>

</div>


<div class="panel">

<h2>
🤖 حالة البوت
</h2>

<div id="signal">
—
</div>

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
maximumFractionDigits:4
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


let total =
s.winning_trades +
s.losing_trades;

document.getElementById(
'winrate'
).textContent =
total
? ((s.winning_trades/total)*100)
.toFixed(2)+'%'
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
s.last_signal || 'لا توجد إشارة';


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


let t=s.current_trade;


document.getElementById(
'symbol'
).textContent=t.symbol;


document.getElementById(
'entry'
).textContent=
money(t.entry);


document.getElementById(
'price'
).textContent=
money(t.price);


document.getElementById(
'tp'
).textContent=
money(t.tp);


document.getElementById(
'sl'
).textContent=
money(t.sl);


document.getElementById(
'profitpct'
).textContent=
Number(t.profit_pct || 0)
.toFixed(2)+'%';


document.getElementById(
'profitusdt'
).textContent=
money(t.profit_usdt)+' USDT';


document.getElementById(
'tradetime'
).textContent=
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

document.getElementById(
'connection'
).textContent=
'🔴 تعذر الاتصال باللوحة';

}

}


update();

setInterval(update,3000);

</script>

</body>

</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():

    update_balance()

    with lock:
        return jsonify(state)


# ============================================================
# التشغيل
# ============================================================

def start_threads():

    load_data()

    load_exchange_info()

    threading.Thread(
        target=manage_trade,
        daemon=True
    ).start()

    threading.Thread(
        target=scanner,
        daemon=True
    ).start()


if __name__ == "__main__":

    start_threads()

    port = int(
        os.getenv(
            "PORT",
            "8080"
        )
    )

    print()
    print("=" * 60)
    print("🤖 مضارب أبو سعود")
    print("=" * 60)
    print("📉 نزول 2% -> شراء")
    print("🎯 TP +2%")
    print("🛑 SL -2%")
    print("⏱️ 15 دقيقة")
    print("=" * 60)
    print()
    print(
        f"🌐 لوحة المتابعة: "
        f"http://127.0.0.1:{port}"
    )
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
