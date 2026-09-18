import os
import time
import hmac
import hashlib
import urllib.parse
import json
import requests
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE = "https://api.binance.com"

# تم تعديل المسار ليعمل على Render مباشرة بدون أخطاء مجلدات
STATE_FILE = "state.json"

TRAIL_START = 0.012       # يبدأ تأمين الربح عند +1.2%
TRAIL_DISTANCE = 0.006    # مسافة التأمين 0.6%

session = requests.Session()
session.headers.update({"X-MBX-APIKEY": API_KEY})


def public(path, params=None):
    while True:
        try:
            r = session.get(BASE + path, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            print("\n⚠️ انقطع النت — أنتظر رجوع الاتصال...", flush=True)
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
            print("\n⚠️ انقطع النت — أنتظر رجوع الاتصال...", flush=True)
            time.sleep(15)


def save_state(state):
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
        result = price * k + result * (1 - k)

    return result


def check_signal(symbol):
    try:
        k15 = get_klines(symbol, "15m")
        k1h = get_klines(symbol, "1h")

        close15 = [float(x[4]) for x in k15]
        high15 = [float(x[2]) for x in k15]
        vol15 = [float(x[5]) for x in k15]

        close1h = [float(x[4]) for x in k1h]

        if len(close15) < 220 or len(close1h) < 220:
            return False

        ema200_15 = ema(close15[-200:], 200)
        ema200_1h = ema(close1h[-200:], 200)

        price = close15[-1]

        resistance = max(high15[-21:-1])
        avg_volume = sum(vol15[-21:-1]) / 20

        volume_ok = vol15[-1] >= avg_volume * 1.5
        breakout = price > resistance

        move = (price / close15[-2]) - 1

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
    data = signed("GET", "/api/v3/account")

    for b in data["balances"]:
        if b["asset"] == "USDT":
            return float(b["free"])

    return 0.0


def get_asset_balance(asset):
    data = signed("GET", "/api/v3/account")

    for b in data["balances"]:
        if b["asset"] == asset:
            return float(b["free"])

    return 0.0


def get_price(symbol):
    data = public(
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )
    return float(data["price"])


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

    qty_down = (q / s).to_integral_value(
        rounding=ROUND_DOWN
    ) * s

    qty_str = format(qty_down, "f")

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
    fills = order.get("fills", [])

    if fills:
        total_qty = sum(float(x["qty"]) for x in fills)

        if total_qty > 0:
            total_value = sum(
                float(x["price"]) * float(x["qty"])
                for x in fills
            )

            return total_value / total_qty

    return get_price(order["symbol"])


def manage_position(state):
    symbol = state["symbol"]
    entry = float(state["entry"])
    highest = float(state.get("highest", entry))
    step = state["step"]

    print("\n🟢 استكمال الصفقة:", symbol, flush=True)
    print(f"💰 Entry: {entry:.8f}", flush=True)

    while True:
        try:
            price = get_price(symbol)

            if price > highest:
                highest = price
                state["highest"] = highest
                save_state(state)

            profit = (price / entry) - 1

            print(
                f"\r📊 {symbol} | "
                f"السعر: {price:.8f} | "
                f"الربح: {profit * 100:.2f}%",
                end="",
                flush=True
            )

            if profit >= TRAIL_START:
                trail_price = highest * (1 - TRAIL_DISTANCE)

                print(
                    f"\n🛡️ تأمين الربح | "
                    f"الخروج: {trail_price:.8f}",
                    flush=True
                )

                if price <= trail_price:
                    asset = symbol.replace("USDT", "")
                    qty = get_asset_balance(asset)

                    if qty > 0:
                        print("🔴 بيع لحماية الربح:", symbol, flush=True)
                        market_sell(symbol, qty, step)

                    clear_state()
                    print("✅ تم إغلاق الصفقة", flush=True)
                    return

            time.sleep(15)

        except Exception:
            print("\n⚠️ انقطع النت — الصفقة محفوظة، أنتظر رجوع الاتصال...", flush=True)
            time.sleep(15)


def main():
    print("=============================================", flush=True)
    print("مضارب أبو سعود V2 🤖", flush=True)
    print("BINANCE SPOT — FULL USDT BALANCE", flush=True)
    print("=============================================", flush=True)
    print("💰 كامل رصيد USDT", flush=True)
    print("⏱️ 15m + 1h", flush=True)
    print("📈 EMA200 + Breakout + Volume", flush=True)
    print("🛡️ تأمين الربح +1.2%", flush=True)
    print("📉 المسافة 0.6%", flush=True)
    print("=============================================", flush=True)

    if not API_KEY or not API_SECRET:
        print("❌ مفاتيح Binance غير موجودة في المتغيرات", flush=True)
        return

    account = signed("GET", "/api/v3/account")

    if not account.get("canTrade"):
        print("❌ التداول غير مفعّل بالحساب", flush=True)
        return

    print("✅ Binance متصل بنجاح", flush=True)
    print("✅ التداول مفعّل", flush=True)

    symbols = get_symbols()

    print("العملات المتاحة:", len(symbols), flush=True)
    print("بدأ الفحص...", flush=True)

    # استكمال الصفقة المحفوظة بعد إعادة التشغيل
    state = load_state()

    if state and state.get("symbol"):
        manage_position(state)

    while True:

        for i, info in enumerate(symbols, 1):

            symbol = info["symbol"]

            print(
                f"\rفحص: {i}/{len(symbols)} | {symbol}",
                end="",
                flush=True
            )

            if check_signal(symbol):

                print(f"\n🔥 إشارة V2 جديدة: {symbol}", flush=True)

                usdt = get_usdt()

                if usdt < 5:
                    print(f"⚠️ رصيد USDT غير كافٍ: {usdt:.2f}", flush=True)
                    time.sleep(30)
                    continue

                trade_amount = usdt * 0.999

                print(
                    f"💰 شراء بكامل الرصيد: "
                    f"{trade_amount:.2f} USDT",
                    flush=True
                )

                try:
                    order = market_buy(
                        symbol,
                        trade_amount
                    )

                    order["symbol"] = symbol

                    entry = get_entry_from_order(order)

                    state = {
                        "symbol": symbol,
                        "entry": entry,
                        "highest": entry,
                        "step": info["step"]
                    }

                    save_state(state)

                    print("✅ تم الشراء بنجاح", flush=True)
                    print(f"📍 Entry: {entry:.8f}", flush=True)

                    manage_position(state)

                except Exception as e:
                    print("❌ فشل الشراء:", e, flush=True)

            time.sleep(1)


if __name__ == "__main__":
    main()
