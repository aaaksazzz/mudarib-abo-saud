import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from threading import Thread, Lock
from http.server import BaseHTTPRequestHandler, HTTPServer

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE = "https://api.binance.com"

STATE_FILE = os.path.expanduser("~/mybot/state.json")

TRAIL_START = 0.012
TRAIL_DISTANCE = 0.006

PORT = int(os.environ.get("PORT", 10000))

session = requests.Session()
session.headers.update({"X-MBX-APIKEY": API_KEY or ""})

status = {
    "bot": "🟢 يعمل",
    "binance": "⏳ جاري الاتصال",
    "trading": "⏳ جاري التحقق",
    "symbols": 0,
    "current_symbol": "-",
    "last_signal": "-",
    "last_trade": "-",
    "usdt": "-",
    "position": "لا توجد صفقة",
    "entry": "-",
    "profit": "-",
    "last_update": "-"
}

status_lock = Lock()


def set_status(**kwargs):
    with status_lock:
        status.update(kwargs)


def get_status():
    with status_lock:
        return dict(status)


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        s = get_status()

        html = f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="10">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مضارب أبو سعود V2</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background:#111;
    color:#fff;
    margin:0;
    padding:20px;
}}
.box {{
    max-width:650px;
    margin:auto;
}}
.card {{
    background:#1d1d1d;
    border-radius:14px;
    padding:18px;
    margin-bottom:12px;
}}
h1 {{
    text-align:center;
}}
.row {{
    display:flex;
    justify-content:space-between;
    border-bottom:1px solid #333;
    padding:10px 0;
}}
.value {{
    font-weight:bold;
}}
.small {{
    color:#aaa;
    text-align:center;
    margin-top:20px;
}}
</style>
</head>

<body>
<div class="box">

<div class="card">
<h1>🤖 مضارب أبو سعود V2</h1>
</div>

<div class="card">

<div class="row">
<span>حالة البوت</span>
<span class="value">{s["bot"]}</span>
</div>

<div class="row">
<span>Binance</span>
<span class="value">{s["binance"]}</span>
</div>

<div class="row">
<span>التداول</span>
<span class="value">{s["trading"]}</span>
</div>

<div class="row">
<span>عدد العملات</span>
<span class="value">{s["symbols"]}</span>
</div>

<div class="row">
<span>آخر عملة يتم فحصها</span>
<span class="value">{s["current_symbol"]}</span>
</div>

<div class="row">
<span>آخر إشارة</span>
<span class="value">{s["last_signal"]}</span>
</div>

</div>

<div class="card">

<div class="row">
<span>الصفقة</span>
<span class="value">{s["position"]}</span>
</div>

<div class="row">
<span>سعر الدخول</span>
<span class="value">{s["entry"]}</span>
</div>

<div class="row">
<span>الربح</span>
<span class="value">{s["profit"]}</span>
</div>

<div class="row">
<span>آخر صفقة</span>
<span class="value">{s["last_trade"]}</span>
</div>

<div class="row">
<span>رصيد USDT</span>
<span class="value">{s["usdt"]}</span>
</div>

</div>

<div class="small">
آخر تحديث: {s["last_update"]}<br>
الصفحة تتحدث تلقائيًا كل 10 ثواني
</div>

</div>
</body>
</html>
"""

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(
            html.encode("utf-8")
        )

    def log_message(self, format, *args):
        pass


def start_web_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


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

        except Exception:

            set_status(
                binance="🔴 انقطع الاتصال"
            )

            print(
                "\n⚠️ انقطع النت — أنتظر رجوع الاتصال..."
            )

            time.sleep(15)


def signed(method, path, params=None):

    params = params or {}

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

        except Exception:

            set_status(
                binance="🔴 انقطع الاتصال"
            )

            print(
                "\n⚠️ انقطع النت — أنتظر رجوع الاتصال..."
            )

            time.sleep(15)


def save_state(state):

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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
        os.remove(STATE_FILE)
    except Exception:
        pass


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

            if lot:

                result.append({
                    "symbol": x["symbol"],
                    "step": lot["stepSize"]
                })

    return result


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


def ema(values, period):

    k = 2 / (period + 1)

    result = values[0]

    for price in values[1:]:

        result = (
            price * k
            + result * (1 - k)
        )

    return result


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
            return False

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

        return (
            close1h[-1] > ema200_1h
            and close15[-1] > ema200_15
            and breakout
            and volume_ok
            and 0.005 <= move <= 0.04
        )

    except Exception:

        return False


def get_usdt():

    data = signed(
        "GET",
        "/api/v3/account"
    )

    for b in data["balances"]:

        if b["asset"] == "USDT":

            return float(b["free"])

    return 0.0


def get_asset_balance(asset):

    data = signed(
        "GET",
        "/api/v3/account"
    )

    for b in data["balances"]:

        if b["asset"] == asset:

            return float(b["free"])

    return 0.0


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


def market_sell(
    symbol,
    qty,
    step
):

    q = Decimal(str(qty))
    s = Decimal(str(step))

    qty_down = (
        q / s
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * s

    qty_str = format(
        qty_down,
        "f"
    )

    return signed(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": qty_str
        }
    )


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

    return get_price(
        order["symbol"]
    )


def manage_position(state):

    symbol = state["symbol"]

    entry = float(
        state["entry"]
    )

    highest = float(
        state.get(
            "highest",
            entry
        )
    )

    step = state["step"]

    set_status(
        position=f"🟢 {symbol}",
        entry=f"{entry:.8f}"
    )

    while True:

        try:

            price = get_price(
                symbol
            )

            if price > highest:

                highest = price

                state["highest"] = highest

                save_state(state)

            profit = (
                price / entry
            ) - 1

            set_status(
                position=f"🟢 {symbol}",
                entry=f"{entry:.8f}",
                profit=f"{profit * 100:.2f}%",
                last_update=time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            if profit >= TRAIL_START:

                trail_price = (
                    highest
                    * (1 - TRAIL_DISTANCE)
                )

                if price <= trail_price:

                    asset = symbol.replace(
                        "USDT",
                        ""
                    )

                    qty = get_asset_balance(
                        asset
                    )

                    if qty > 0:

                        market_sell(
                            symbol,
                            qty,
                            step
                        )

                    set_status(
                        position="لا توجد صفقة",
                        last_trade=f"🔴 بيع {symbol}",
                        profit=f"{profit * 100:.2f}%"
                    )

                    clear_state()

                    return

            time.sleep(15)

        except Exception:

            set_status(
                binance="🔴 انقطع الاتصال"
            )

            time.sleep(15)


def main():

    if not API_KEY or not API_SECRET:

        set_status(
            bot="🔴 مفاتيح Binance غير موجودة",
            binance="🔴 غير متصل",
            trading="🔴 غير متاح"
        )

        return

    try:

        account = signed(
            "GET",
            "/api/v3/account"
        )

        if not account.get(
            "canTrade"
        ):

            set_status(
                binance="🟢 متصل",
                trading="🔴 التداول غير مفعّل"
            )

            return

        set_status(
            bot="🟢 يعمل",
            binance="🟢 Binance متصل",
            trading="🟢 التداول مفعّل"
        )

        symbols = get_symbols()

        set_status(
            symbols=len(symbols)
        )

        state = load_state()

        if state and state.get(
            "symbol"
        ):

            manage_position(state)

        while True:

            for i, info in enumerate(
                symbols,
                1
            ):

                symbol = info["symbol"]

                set_status(
                    current_symbol=symbol,
                    last_update=time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

                if check_signal(symbol):

                    set_status(
                        last_signal=f"🔥 BUY {symbol}"
                    )

                    usdt = get_usdt()

                    set_status(
                        usdt=f"{usdt:.2f} USDT"
                    )

                    if usdt < 5:

                        continue

                    trade_amount = (
                        usdt * 0.999
                    )

                    try:

                        order = market_buy(
                            symbol,
                            trade_amount
                        )

                        order["symbol"] = symbol

                        entry = get_entry_from_order(
                            order
                        )

                        state = {
                            "symbol": symbol,
                            "entry": entry,
                            "highest": entry,
                            "step": info["step"]
                        }

                        save_state(state)

                        set_status(
                            last_trade=f"🟢 شراء {symbol}",
                            position=f"🟢 {symbol}",
                            entry=f"{entry:.8f}"
                        )

                        manage_position(
                            state
                        )

                    except Exception as e:

                        set_status(
                            last_trade=f"❌ فشل شراء {symbol}: {str(e)[:60]}"
                        )

                time.sleep(1)

    except Exception as e:

        set_status(
            bot=f"🔴 خطأ: {str(e)[:100]}"
        )


if __name__ == "__main__":

    Thread(
        target=start_web_server,
        daemon=True
    ).start()

    print(
        f"🌐 Render Port: {PORT}"
    )

    main()
