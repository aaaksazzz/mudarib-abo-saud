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

STATE_FILE = os.path.expanduser("~/mybot/state.json")
HISTORY_FILE = os.path.expanduser("~/mybot/trade_history.json")

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
        except Exception as e:
            print(f"\n⚠️ اتصال Binance: {e}")
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

        except Exception as e:
            print(f"\n⚠️ اتصال Binance: {e}")
            time.sleep(15)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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


def save_trade(trade):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)

    history = []

    try:
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    except Exception:
        pass

    history.append(trade)

    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-100:], f, indent=2)


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
    """
    نفس شروط V2 الأصلية بالضبط.
    ترجع:
    signal, reason
    """

    try:
        k15 = get_klines(symbol, "15m")
        k1h = get_klines(symbol, "1h")

        close15 = [float(x[4]) for x in k15]
        high15 = [float(x[2]) for x in k15]
        vol15 = [float(x[5]) for x in k15]

        close1h = [float(x[4]) for x in k1h]

        if len(close15) < 220 or len(close1h) < 220:
            return False, "بيانات غير كافية"

        ema200_15 = ema(close15[-200:], 200)
        ema200_1h = ema(close1h[-200:], 200)

        price = close15[-1]

        resistance = max(high15[-21:-1])

        avg_volume = sum(vol15[-21:-1]) / 20

        volume_ratio = (
            vol15[-1] / avg_volume
            if avg_volume > 0
            else 0
        )

        volume_ok = vol15[-1] >= avg_volume * 1.5
        breakout = price > resistance

        move = (price / close15[-2]) - 1

        if close1h[-1] <= ema200_1h:
            return False, "1H تحت EMA200"

        if close15[-1] <= ema200_15:
            return False, "15M تحت EMA200"

        if not breakout:
            return False, "لم يكسر المقاومة"

        if not volume_ok:
            return False, f"الحجم {volume_ratio:.2f}x فقط"

        if move < 0.005:
            return False, f"الحركة {move * 100:.2f}% أقل من 0.5%"

        if move > 0.04:
            return False, f"الحركة {move * 100:.2f}% أكبر من 4%"

        return True, "🔥 كل الشروط مكتملة"

    except Exception as e:
        return False, f"خطأ: {str(e)[:80]}"


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

    qty_down = (
        q / s
    ).to_integral_value(
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
        total_qty = sum(
            float(x["qty"])
            for x in fills
        )

        if total_qty > 0:
            total_value = sum(
                float(x["price"]) *
                float(x["qty"])
                for x in fills
            )

            return total_value / total_qty

    return get_price(order["symbol"])


def manage_position(state):
    symbol = state["symbol"]
    entry = float(state["entry"])
    highest = float(
        state.get("highest", entry)
    )
    step = state["step"]

    start_time = state.get(
        "start_time",
        time.time()
    )

    print("\n")
    print("====================================")
    print("🟢 الصفقة مفتوحة")
    print(f"🪙 العملة: {symbol}")
    print(f"📍 الدخول: {entry:.8f}")
    print("====================================")

    while True:
        try:
            price = get_price(symbol)

            if price > highest:
                highest = price
                state["highest"] = highest
                save_state(state)

            profit = (price / entry) - 1

            profit_usdt = (
                float(state.get("invested", 0))
                * profit
            )

            if profit >= TRAIL_START:
                trail_price = (
                    highest *
                    (1 - TRAIL_DISTANCE)
                )
            else:
                trail_price = 0

            print(
                f"\r📊 {symbol} | "
                f"السعر {price:.8f} | "
                f"{'🟢' if profit >= 0 else '🔴'} "
                f"{profit * 100:+.2f}% | "
                f"{profit_usdt:+.2f} USDT",
                end="",
                flush=True
            )

            if profit >= TRAIL_START:

                print(
                    f"\n🛡️ تأمين الربح مفعل"
                )

                print(
                    f"📌 أعلى سعر: "
                    f"{highest:.8f}"
                )

                print(
                    f"🛡️ سعر الخروج: "
                    f"{trail_price:.8f}"
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
                            "\n🔴 تفعيل تأمين الربح"
                        )

                        sell_order = market_sell(
                            symbol,
                            qty,
                            step
                        )

                        exit_price = get_price(
                            symbol
                        )

                        final_profit = (
                            exit_price / entry
                        ) - 1

                        final_usdt = (
                            float(
                                state.get(
                                    "invested",
                                    0
                                )
                            )
                            * final_profit
                        )

                        result = (
                            "ربح"
                            if final_profit >= 0
                            else "خسارة"
                        )

                        trade = {
                            "symbol": symbol,
                            "entry": entry,
                            "exit": exit_price,
                            "percent": round(
                                final_profit * 100,
                                4
                            ),
                            "profit_usdt": round(
                                final_usdt,
                                4
                            ),
                            "result": result,
                            "time": time.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                        }

                        save_trade(trade)

                        print("")
                        print(
                            "===================================="
                        )
                        print(
                            f"{'🟢' if final_profit >= 0 else '🔴'} "
                            f"الصفقة انتهت: {result}"
                        )
                        print(
                            f"📊 النتيجة: "
                            f"{final_profit * 100:+.2f}%"
                        )
                        print(
                            f"💰 النتيجة: "
                            f"{final_usdt:+.2f} USDT"
                        )
                        print(
                            "===================================="
                        )

                    clear_state()

                    return

            time.sleep(15)

        except Exception as e:

            print(
                f"\n⚠️ مشكلة أثناء متابعة الصفقة: {e}"
            )

            time.sleep(15)


def main():

    print("=============================================")
    print("مضارب أبو سعود V2 🤖")
    print("BINANCE SPOT — FULL USDT BALANCE")
    print("=============================================")
    print("💰 كامل رصيد USDT")
    print("⏱️ 15m + 1h")
    print("📈 EMA200 + Breakout + Volume")
    print("🛡️ تأمين الربح +1.2%")
    print("📉 المسافة 0.6%")
    print("📊 عرض ربح/خسارة الصفقة")
    print("=============================================")

    if not API_KEY or not API_SECRET:
        print("❌ مفاتيح Binance غير موجودة")
        return

    account = signed(
        "GET",
        "/api/v3/account"
    )

    if not account.get("canTrade"):
        print("❌ التداول غير مفعّل")
        return

    print("✅ Binance متصل")
    print("✅ التداول مفعّل")

    symbols = get_symbols()

    print(
        f"🪙 العملات: {len(symbols)}"
    )

    print("🚀 بدأ الفحص...")

    state = load_state()

    if state and state.get("symbol"):
        print(
            "\n🔄 تم العثور على صفقة محفوظة"
        )

        manage_position(state)

    while True:

        for i, info in enumerate(
            symbols,
            1
        ):

            symbol = info["symbol"]

            print(
                f"\r🔎 فحص: "
                f"{i}/{len(symbols)} | "
                f"{symbol}",
                end="",
                flush=True
            )

            signal, reason = check_signal(
                symbol
            )

            if signal:

                print("")
                print(
                    "===================================="
                )
                print(
                    f"🔥 إشارة V2: {symbol}"
                )
                print(
                    f"✅ {reason}"
                )
                print(
                    "===================================="
                )

                usdt = get_usdt()

                if usdt < 5:

                    print(
                        f"⚠️ رصيد USDT غير كافٍ: "
                        f"{usdt:.2f}"
                    )

                    time.sleep(30)
                    continue

                trade_amount = usdt * 0.999

                print(
                    f"💰 الشراء: "
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
                        "step": info["step"],
                        "invested": trade_amount,
                        "start_time": time.time()
                    }

                    save_state(state)

                    print("")
                    print(
                        "🟢🟢🟢 تم فتح الصفقة 🟢🟢🟢"
                    )

                    print(
                        f"🪙 العملة: {symbol}"
                    )

                    print(
                        f"📍 Entry: "
                        f"{entry:.8f}"
                    )

                    print(
                        f"💰 المبلغ: "
                        f"{trade_amount:.2f} USDT"
                    )

                    manage_position(state)

                except Exception as e:

                    print(
                        f"❌ فشل الشراء: {e}"
                    )

            time.sleep(1)


if __name__ == "__main__":
    main()
