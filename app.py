import os, time, json, hmac, hashlib, urllib.parse, urllib.request, threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from fastapi import FastAPI

# Technical Binance Futures bot only. No recommendations / web UI.
# Strategy: BUY-only on 15m weakness, filtered by 1h EMA200.
# BUY setup: 1h price below EMA200, 15m price below EMA20, 15m RSI < 50,
# preferably/strictly 15m price below EMA200, with volume above the prior 20-candle average.
# No stop loss. Take profit = 1%, tracked and placed on Binance.
# LIVE trading is disabled unless BINANCE_LIVE=true.

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
LIVE = os.getenv("BINANCE_LIVE", "false").lower() == "true"
TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
QUOTE = "USDT"
INTERVAL = "15m"
HTF = "1h"
TP_PCT = Decimal("0.01")
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

    # BUY-only setup: buy weakness / dip.
    buy_setup = (
        hcloses[-1] < he200 and
        price < e20 and
        r < 50 and
        price < e200 and
        vols[-1] > avg_vol
    )

    if buy_setup:
        return {"original": "BUY", "execute": "LONG", "price": price}
    return None
def sync_binance_positions():
    # Adopt manually opened LONG positions so the bot can continue managing them.
    if not LIVE or not API_KEY or not API_SECRET:
        return
    try:
        rows = signed("GET", "/fapi/v2/positionRisk")
        for p in rows:
            symbol = p.get("symbol")
            amt = Decimal(str(p.get("positionAmt", "0")))
            if not symbol or amt <= 0:
                continue
            if symbol in STATE["positions"]:
                continue
            entry = Decimal(str(p.get("entryPrice", "0")))
            if entry <= 0:
                continue
            qty = abs(amt)
            tp = entry * (Decimal(1) + TP_PCT)
            tp_result = place_take_profit(symbol, "LONG", qty, tp)
            STATE["positions"][symbol] = {
                "symbol": symbol, "position": "LONG", "original": "MANUAL",
                "qty": str(qty), "entry": str(entry), "tp": str(tp),
                "opened_at": int(time.time()), "order": None,
                "tp_order": tp_result.get("orderId")
            }
            STATE["trades"].append(STATE["positions"][symbol].copy())
            print("ADOPTED_MANUAL_LONG", symbol, "entry", str(entry), "tp", str(tp), flush=True)
        save_state()
    except Exception as e:
        print("POSITION_SYNC_ERROR", str(e), flush=True)

def place_take_profit(symbol, position_side, qty, tp_price):
    # Native Binance Futures TP-MARKET: Binance remains responsible for the exit.
    if not LIVE:
        return {"dry_run": True, "symbol": symbol, "type": "TAKE_PROFIT_MARKET",
                "stopPrice": str(tp_price), "closePosition": "true"}
    side = "SELL" if position_side == "LONG" else "BUY"
    return signed("POST", "/fapi/v1/order", {
        "symbol": symbol,
        "side": side,
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": str(tp_price),
        "closePosition": "true",
        "workingType": "MARK_PRICE",
        "priceProtect": "TRUE",
    })

def scan():
    infos = symbol_info()
    tickers = public("/fapi/v1/ticker/24hr")
    ticker_map = {x["symbol"]: x for x in tickers}
    symbols = [x["symbol"] for x in tickers
               if x.get("symbol") in infos and Decimal(str(x.get("quoteVolume", "0"))) >= MIN_24H_VOLUME]

    candidates = []
    for symbol in symbols:
        try:
            if symbol in STATE["positions"]:
                continue
            sig = signal(symbol)
            if sig:
                # Rank qualifying coins by the latest completed 15m candle change %.
                rows = klines(symbol, INTERVAL, 3)
                if len(rows) < 2:
                    continue
                prev_close = Decimal(str(rows[-2][4]))
                last_close = Decimal(str(rows[-1][4]))
                change_pct = ((last_close - prev_close) / prev_close) * Decimal(100)
                candidates.append((change_pct, symbol, sig))
        except Exception as e:
            print("SCAN_ERROR", symbol, str(e), flush=True)

    # Take only the strongest 15m change among qualifying BUY setups.
    candidates.sort(key=lambda x: x[0], reverse=True)
    if candidates:
        change_pct, symbol, sig = candidates[0]
        print("BEST_BUY", symbol, "15m_change_pct", str(change_pct), sig, flush=True)
        open_long(symbol, sig, infos)

    STATE["last_scan"] = int(time.time())
    save_state()

