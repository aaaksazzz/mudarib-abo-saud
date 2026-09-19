import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from threading import Thread
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
session.headers.update({"X-MBX-APIKEY": API_KEY})


# =========================
# Render Web Server
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Mudarib Abo Saud V2 is running")

    def log_message(self, format, *args):
        pass


def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# =========================
# Binance API
# =========================

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
            print("\n⚠️ انقطع النت — أنتظر رجوع الاتصال...")
            time.sleep(15)


def signed(method, path, params=None):

    params = params or {}
    params["timestamp"] = int(time.time() * 1000)

    query = urllib.parse.urlencode(params)

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
            print("\n⚠️ انقطع النت — أنتظر رجوع الاتصال...")
            time.sleep(15)


# =========================
# State
# =========================

def save_state(state):

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def load_state():

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)

    except Exception:
        return None


def clear_state():

    try:
        os.remove(STATE_FILE)

    except Exception:
        pass


# =========================
# Symbols
# =========================

def get_symbols():

    data = public("/api/v3/exchangeInfo")

    result = []

    for x in data["symbols"]:

        if (
            x["status"] == "TRADING"
            and x["quoteAsset"] == "USDT"
            and x.get("isSpotTradingAllowed", False)
        ):

            filters = {
                f["filterType"]: f
                for f in x["filters"]
            }

            lot = filters.get("LOT_SIZE")

            if lot:

                result.append({
                    "symbol": x["symbol"],
                    "step": lot["stepSize"]
                })

    return result


# =========================
# Market Data
# =========================

def get_klines(symbol, interval):

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


# =========================
# Signal
# =========================

def check_signal(symbol):

    try:

        k15 = get_klines(symbol, "15m")
        k1h = get_klines(symbol, "1h")

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

        breakout = price > resistance

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


# =========================
# Account
# =========================

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

    return float(data["price"])


# =========================
# Orders
# =========================

def market_buy(symbol, amount):

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


def market_sell(symbol, qty, step):

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


# =========================
# Position Management
# =========================

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

    print(
        "\n🟢 استكمال الصفقة:",
        symbol
    )

    print(
        f"💰 Entry: {entry:.8f}"
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

            print(
                f"\r📊 {symbol} | "
                f"السعر: {price:.8f} | "
                f"الربح: {profit * 100:.2f}%",
                end="",
                flush=True
            )

            if profit >= TRAIL_START:

                trail_price = (
                    highest
                    * (1 - TRAIL_DISTANCE)
                )

                print(
                    f"\n🛡️ تأمين الربح | "
                    f"الخروج: {trail_price:.8f}"
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

                        print(
                            "🔴 بيع لحماية الربح:",
                            symbol
                        )

                        market_sell(
                            symbol,
                            qty,
                            step
                        )

                    clear_state()

                    print(
                        "✅ تم إغلاق الصفقة"
                    )

                    return

            time.sleep(15)

        except Exception:

            print(
                "\n⚠️ انقطع النت — "
                "الصفقة محفوظة، "
                "أنتظر رجوع الاتصال..."
            )

            time.sleep(15)


# =========================
# Main
# =========================

def main():

    print(
        "============================================="
    )

    print(
        "مضارب أبو سعود V2 🤖"
    )

    print(
        "BINANCE SPOT — FULL USDT BALANCE"
    )

    print(
        "============================================="
    )

    print(
        "💰 كامل رصيد USDT"
    )

    print(
        "⏱️ 15m + 1h"
    )

    print(
        "📈 EMA200 + Breakout + Volume"
    )

    print(
        "🛡️ تأمين الربح +1.2%"
    )

    print(
        "📉 المسافة 0.6%"
    )

    print(
        "============================================="
    )

    if not API_KEY or not API_SECRET:

        print(
            "❌ مفاتيح Binance غير موجودة"
        )

        return

    account = signed(
        "GET",
        "/api/v3/account"
    )

    if not account.get(
        "canTrade"
    ):

        print(
            "❌ التداول غير مفعّل"
        )

        return

    print(
        "✅ Binance متصل"
    )

    print(
        "✅ التداول مفعّل"
    )

    symbols = get_symbols()

    print(
        "العملات:",
        len(symbols)
    )

    print(
        "بدأ الفحص..."
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

            print(
                f"\rفحص: {i}/{len(symbols)} | {symbol}",
                end="",
                flush=True
            )

            if check_signal(symbol):

                print(
                    f"\n🔥 إشارة V2: {symbol}"
                )

                usdt = get_usdt()

                if usdt < 5:

                    print(
                        f"⚠️ رصيد USDT غير كافٍ: "
                        f"{usdt:.2f}"
                    )

                    time.sleep(30)

                    continue

                trade_amount = (
                    usdt * 0.999
                )

                print(
                    f"💰 شراء بكامل الرصيد: "
                    f"{trade_amount:.2f} USDT"
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

                    print(
                        "✅ تم الشراء"
                    )

                    print(
                        f"📍 Entry: {entry:.8f}"
                    )

                    manage_position(
                        state
                    )

                except Exception as e:

                    print(
                        "❌ فشل الشراء:",
                        e
                    )

            time.sleep(1)


if __name__ == "__main__":

    Thread(
        target=start_web_server,
        daemon=True
    ).start()

    print(
        f"🌐 Render Port: {PORT}"
    )

    main()
