import os, time, json, hmac, hashlib, urllib.parse, urllib.request, threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from fastapi import FastAPI

# Technical Binance Futures bot only. No recommendations / web UI.
# Strategy: 15m + 1h EMA200, 15m EMA20, RSI, volume.
# Reverse execution: original BUY -> SHORT, original SELL -> LONG.
# No stop loss. Take profit = 4%.
# LIVE trading is disabled unless BINANCE_LIVE=true.

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
LIVE = os.getenv("BINANCE_LIVE", "false").lower() == "true"
TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
QUOTE = "USDT"
INTERVAL = "15m"
HTF = "1h"
TP_PCT = Decimal("0.04")
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
USD_PER_TRADE = Decimal(os.getenv("USD_PER_TRADE", "10"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
MIN_24H_VOLUME = Decimal(os.getenv("MIN_24H_VOLUME", "1000000"))

BASE = "https://fapi.binancefuture.com" if TESTNET else "https://fapi.binance.com"
STATE_FILE = os.getenv("BOT_STATE_FILE", "bot_state.json")
LOCK = threading.RLock()
STATE = {"running": False, "last_scan": 0, "positions": {}, "trades": []}

app = FastAPI(title="Technical Binance Bot")

def load_state():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            x = json.load(f)
            if isinstance(x, dict):
                STATE.update(x)
    except Exception:
        pass

def save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def public(path, params=None):
    q = urllib.parse.urlencode(params or {})
    url = BASE + path + (("?" + q) if q else "")
    req = urllib.request.Request(url, headers={"User-Agent": "technical-binance-bot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def signed(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET missing")
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 10000
    query = urllib.parse.urlencode(p)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = BASE + path + "?" + query + "&signature=" + sig
    req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": API_KEY, "User-Agent": "technical-binance-bot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def ema(values, period):
    if len(values) < period:
        return None
    e = sum(values[:period]) / Decimal(period)
    k = Decimal(2) / Decimal(period + 1)
    for v in values[period:]:
        e = v * k + e * (Decimal(1) - k)
    return e

def rsi(values, period=14):
    if len(values) <= period:
        return Decimal(50)
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i-1]
        gains.append(max(d, Decimal(0)))
        losses.append(max(-d, Decimal(0)))
    ag = sum(gains[:period]) / Decimal(period)
    al = sum(losses[:period]) / Decimal(period)
    for i in range(period, len(gains)):
        ag = (ag * Decimal(period-1) + gains[i]) / Decimal(period)
        al = (al * Decimal(period-1) + losses[i]) / Decimal(period)
    if al == 0:
        return Decimal(100)
    rs = ag / al
    return Decimal(100) - Decimal(100) / (Decimal(1) + rs)

def klines(symbol, interval, limit=300):
    rows = public("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    # Exclude the currently forming candle.
    return rows[:-1] if len(rows) > 1 else []

def signal(symbol):
    rows = klines(symbol, INTERVAL, 300)
    hrows = klines(symbol, HTF, 300)
    if len(rows) < 220 or len(hrows) < 220:
        return None

    closes = [Decimal(str(x[4])) for x in rows]
    vols = [Decimal(str(x[7])) for x in rows]
    hcloses = [Decimal(str(x[4])) for x in hrows]
    price = closes[-1]
    e20 = ema(closes, 20)
    e200 = ema(closes, 200)
    he200 = ema(hcloses, 200)
    r = rsi(closes, 14)
    avg_vol = sum(vols[-21:-1]) / Decimal(20)

    long_original = price > e200 and price > e20 and r > 50 and vols[-1] > avg_vol and hcloses[-1] > he200
    short_original = price < e200 and price < e20 and r < 50 and vols[-1] > avg_vol and hcloses[-1] < he200

    # Exact reverse execution.
    if long_original:
        return {"original": "BUY", "execute": "SHORT", "price": price}
    if short_original:
        return {"original": "SELL", "execute": "LONG", "price": price}
    return None

def symbol_info():
    data = public("/fapi/v1/exchangeInfo")
    out = {}
    for s in data.get("symbols", []):
        if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        filters = {f["filterType"]: f for f in s.get("filters", [])}
        out[s["symbol"]] = {
            "step": Decimal(filters.get("LOT_SIZE", {}).get("stepSize", "0.001")),
            "min_qty": Decimal(filters.get("LOT_SIZE", {}).get("minQty", "0")),
            "tick": Decimal(filters.get("PRICE_FILTER", {}).get("tickSize", "0.01")),
        }
    return out

def round_step(v, step):
    if step <= 0:
        return v
    return (v / step).to_integral_value(rounding=ROUND_DOWN) * step

def qty_for(symbol, price, info):
    q = USD_PER_TRADE / price
    q = round_step(q, info[symbol]["step"])
    if q < info[symbol]["min_qty"]:
        return Decimal(0)
    return q

def set_leverage(symbol, leverage=1):
    try:
        signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
    except Exception:
        pass

def order(symbol, side, qty):
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": str(qty),
        "newOrderRespType": "RESULT",
    }
    if not LIVE:
        return {"dry_run": True, **params}
    return signed("POST", "/fapi/v1/order", params)

def close_order(symbol, position_side, qty):
    side = "SELL" if position_side == "LONG" else "BUY"
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": str(qty),
        "reduceOnly": "true",
        "newOrderRespType": "RESULT",
    }
    if not LIVE:
        return {"dry_run": True, **params}
    return signed("POST", "/fapi/v1/order", params)

def open_reversed(symbol, sig, infos):
    if len(STATE["positions"]) >= MAX_POSITIONS or symbol in STATE["positions"]:
        return
    price = sig["price"]
    qty = qty_for(symbol, price, infos)
    if qty <= 0:
        return
    execute = sig["execute"]
    side = "SELL" if execute == "SHORT" else "BUY"
    set_leverage(symbol, 1)
    result = order(symbol, side, qty)
    entry = Decimal(str(result.get("avgPrice") or price))
    tp = entry * (Decimal(1) - TP_PCT) if execute == "SHORT" else entry * (Decimal(1) + TP_PCT)
    STATE["positions"][symbol] = {
        "symbol": symbol, "position": execute, "original": sig["original"],
        "qty": str(qty), "entry": str(entry), "tp": str(tp),
        "opened_at": int(time.time()), "order": result.get("orderId")
    }
    STATE["trades"].append(STATE["positions"][symbol].copy())
    save_state()

def check_take_profits():
    for symbol, p in list(STATE["positions"].items()):
        try:
            price = Decimal(str(public("/fapi/v1/ticker/price", {"symbol": symbol})["price"]))
            entry = Decimal(p["entry"])
            tp = Decimal(p["tp"])
            hit = price <= tp if p["position"] == "SHORT" else price >= tp
            if hit:
                qty = Decimal(p["qty"])
                result = close_order(symbol, p["position"], qty)
                p["closed_at"] = int(time.time())
                p["exit"] = str(price)
                p["result"] = "TP4"
                p["close_order"] = result.get("orderId")
                del STATE["positions"][symbol]
                save_state()
        except Exception as e:
            print("TP_CHECK_ERROR", symbol, str(e), flush=True)

def scan():
    infos = symbol_info()
    tickers = public("/fapi/v1/ticker/24hr")
    symbols = [x["symbol"] for x in tickers
               if x.get("symbol") in infos and Decimal(str(x.get("quoteVolume", "0"))) >= MIN_24H_VOLUME]
    for symbol in symbols:
        try:
            if symbol in STATE["positions"]:
                continue
            sig = signal(symbol)
            if sig:
                print("SIGNAL", symbol, sig, flush=True)
                open_reversed(symbol, sig, infos)
        except Exception as e:
            print("SCAN_ERROR", symbol, str(e), flush=True)
    STATE["last_scan"] = int(time.time())
    save_state()

def bot_loop():
    load_state()
    STATE["running"] = True
    save_state()
    while True:
        try:
            check_take_profits()
            # Scan only after a completed 15m candle, with a small delay.
            now = int(time.time())
            if now % 900 >= 10 and now - int(STATE.get("last_scan", 0)) >= 900:
                scan()
        except Exception as e:
            print("BOT_ERROR", str(e), flush=True)
        time.sleep(SCAN_SECONDS)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "bot": "technical-binance-futures",
        "live": LIVE,
        "testnet": TESTNET,
        "positions": len(STATE.get("positions", {})),
        "last_scan": STATE.get("last_scan", 0),
        "time": datetime.now(timezone.utc).isoformat()
    }

@app.get("/status")
def status():
    return {
        "live": LIVE,
        "testnet": TESTNET,
        "running": STATE.get("running", False),
        "positions": STATE.get("positions", {}),
        "last_scan": STATE.get("last_scan", 0)
    }

if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=bot_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
