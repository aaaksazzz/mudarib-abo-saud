import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")
BASES = {"spot": "https://api.binance.com", "futures": "https://fapi.binance.com"}
FRAMES = {"15m", "1h", "4h", "1d"}
STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EUR"}
CACHE = {}
CACHE_LOCK = threading.Lock()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path("/tmp")
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "trades.sqlite3")))

MARKETS = [
    {"id": "spot", "name": "Binance Spot", "provider": "Binance", "status": "live"},
    {"id": "futures", "name": "Binance Futures", "provider": "Binance", "status": "live"},
    {"id": "alpha", "name": "Binance Alpha", "provider": None, "status": "provider_required"},
    {"id": "saudi", "name": "السوق السعودي", "provider": None, "status": "provider_required"},
    {"id": "us", "name": "الأسهم الأمريكية", "provider": None, "status": "provider_required"},
    {"id": "contracts", "name": "العقود الأمريكية", "provider": None, "status": "provider_required"},
    {"id": "forex", "name": "الفوركس والذهب", "provider": None, "status": "provider_required"},
]

def cached(key, ttl, loader):
    now = time.time()
    with CACHE_LOCK:
        item = CACHE.get(key)
        if item and now - item[0] < ttl:
            return item[1]
    value = loader()
    with CACHE_LOCK:
        CACHE[key] = (time.time(), value)
    return value

def fetch_json(url, params=None):
    response = requests.get(url, params=params, timeout=(3.5, 7), headers={"User-Agent": "SmartTradingPro/2.0"})
    response.raise_for_status()
    return response.json()

def market_tickers(kind):
    base = BASES[kind]
    path = "/api/v3/ticker/24hr" if kind == "spot" else "/fapi/v1/ticker/24hr"
    rows = cached(kind + ":tickers", 20, lambda: fetch_json(base + path))
    output = []
    for row in rows:
        symbol = str(row.get("symbol", ""))
        if not symbol.endswith("USDT") or symbol[:-4] in STABLES:
            continue
        try:
            price = float(row["lastPrice"])
            volume = float(row.get("quoteVolume", 0))
            change = float(row.get("priceChangePercent", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and volume >= 1_000_000:
            output.append({"symbol": symbol, "price": price, "volume": volume, "change24h": change})
    return output

def candles(kind, symbol, interval):
    path = "/api/v3/klines" if kind == "spot" else "/fapi/v1/klines"
    raw = cached(f"{kind}:{symbol}:{interval}", 45,
                 lambda: fetch_json(BASES[kind] + path, {"symbol": symbol, "interval": interval, "limit": 100}))
    rows = []
    for item in raw:
        try:
            rows.append({"open": float(item[1]), "high": float(item[2]), "low": float(item[3]),
                         "close": float(item[4]), "volume": float(item[5]), "time": int(item[0])})
        except (TypeError, ValueError, IndexError):
            continue
    return rows

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * alpha + value * (1 - alpha)
    return value

def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = sum(max(x, 0) for x in changes[-period:]) / period
    losses = sum(max(-x, 0) for x in changes[-period:]) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def frame_bias(rows):
    if len(rows) < 55:
        return None
    closes = [x["close"] for x in rows]
    fast, slow = ema(closes, 20), ema(closes, 50)
    if fast is None or slow is None:
        return None
    if closes[-1] > fast > slow:
        return "BUY"
    if closes[-1] < fast < slow:
        return "SELL"
    return "NEUTRAL"

def analyse_candidate(kind, item, interval, market_direction):
    try:
        selected = candles(kind, item["symbol"], interval)
        four_hour = candles(kind, item["symbol"], "4h")
        daily = candles(kind, item["symbol"], "1d")
        if min(len(selected), len(four_hour), len(daily)) < 55:
            return None
        side = frame_bias(selected)
        if side not in ("BUY", "SELL") or side != market_direction:
            return None
        if frame_bias(four_hour) != side or frame_bias(daily) != side:
            return None
        closes = [x["close"] for x in selected]
        current = closes[-1]
        momentum = rsi(closes)
        if momentum is None or (side == "BUY" and not 50 <= momentum <= 72) or (side == "SELL" and not 28 <= momentum <= 50):
            return None
        ranges = []
        for index in range(1, len(selected)):
            prev = closes[index - 1]
            candle = selected[index]
            ranges.append(max(candle["high"] - candle["low"], abs(candle["high"] - prev), abs(candle["low"] - prev)))
        atr = sum(ranges[-14:]) / min(14, len(ranges[-14:]))
        if atr <= 0 or current <= 0:
            return None
        risk = atr * 1.5
        if side == "BUY":
            stop, sign = current - risk, 1
        else:
            stop, sign = current + risk, -1
        if stop <= 0:
            return None
        distance = abs(current - stop)
        score = min(99, round(55 + abs(ema(closes, 20) / ema(closes, 50) - 1) * 1200 + abs(momentum - 50) * 0.35, 1))
        return {
            "symbol": item["symbol"], "side": side, "entry": current, "price": item["price"],
            "stop_loss": stop, "tp1": current + sign * distance, "tp2": current + sign * distance * 2,
            "tp3": current + sign * distance * 3, "risk_percent": round(distance / current * 100, 3),
            "change24h": item["change24h"], "volume": item["volume"], "timeframe": interval,
            "rsi": round(momentum, 1), "quality_score": score, "created_at": int(time.time()),
        }
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
        return None

@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=8)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL, symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL, side TEXT NOT NULL, entry REAL NOT NULL, stop_loss REAL NOT NULL,
            tp1 REAL NOT NULL, tp2 REAL NOT NULL, tp3 REAL NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            tp1_hit INTEGER NOT NULL DEFAULT 0, tp2_hit INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, closed_at INTEGER
        )""")
        connection.commit()
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def save_new_trades(kind, signals):
    now = int(time.time())
    with db() as connection:
        for signal in signals:
            exists = connection.execute(
                "SELECT id FROM trades WHERE market=? AND symbol=? AND timeframe=? AND status='OPEN'",
                (kind, signal["symbol"], signal["timeframe"])
            ).fetchone()
            if not exists:
                connection.execute("""INSERT INTO trades
                    (market,symbol,timeframe,side,entry,stop_loss,tp1,tp2,tp3,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (kind, signal["symbol"], signal["timeframe"], signal["side"], signal["entry"],
                     signal["stop_loss"], signal["tp1"], signal["tp2"], signal["tp3"], now, now))
        connection.commit()

def update_open_trades(kind, prices):
    now = int(time.time())
    with db() as connection:
        rows = connection.execute("SELECT * FROM trades WHERE market=? AND status='OPEN'", (kind,)).fetchall()
        for trade in rows:
            price = prices.get(trade["symbol"])
            if price is None:
                continue
            side = trade["side"]
            stop_hit = price <= trade["stop_loss"] if side == "BUY" else price >= trade["stop_loss"]
            tp1_hit = price >= trade["tp1"] if side == "BUY" else price <= trade["tp1"]
            tp2_hit = price >= trade["tp2"] if side == "BUY" else price <= trade["tp2"]
            tp3_hit = price >= trade["tp3"] if side == "BUY" else price <= trade["tp3"]
            status = "SL" if stop_hit else ("TP3" if tp3_hit else "OPEN")
            connection.execute("""UPDATE trades SET tp1_hit=MAX(tp1_hit,?), tp2_hit=MAX(tp2_hit,?),
                status=?,updated_at=?,closed_at=? WHERE id=?""",
                (int(tp1_hit), int(tp2_hit), status, now, now if status != "OPEN" else None, trade["id"]))
        connection.commit()

@app.get("/")
def home():
    return send_from_directory("static", "index.html")

@app.get("/markets/<market_id>")
def market_page(market_id):
    if market_id not in {item["id"] for item in MARKETS}:
        return send_from_directory("static", "index.html"), 200
    return send_from_directory("static", "index.html")

@app.get("/health")
@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "smart-trading-pro", "status": "healthy"})

@app.get("/api/markets")
def markets():
    return jsonify({"markets": MARKETS})

@app.get("/api/market/<kind>")
def market(kind):
    if kind not in BASES:
        return jsonify({"ok": False, "status": "provider_required", "message": "مزود البيانات لهذا السوق غير مربوط؛ لن نعرض بيانات غير موثوقة.", "signals": []}), 503
    interval = request.args.get("timeframe", "15m")
    if interval not in FRAMES:
        return jsonify({"ok": False, "error": "إطار زمني غير مدعوم"}), 400
    try:
        assets = cached(kind + ":universe", 20, lambda: market_tickers(kind))
        up = sum(1 for row in assets if row["change24h"] > 0)
        down = sum(1 for row in assets if row["change24h"] < 0)
        direction = "BUY" if up > down else ("SELL" if down > up else "NEUTRAL")
        prices = {row["symbol"]: row["price"] for row in assets}
        update_open_trades(kind, prices)
        candidates = sorted(assets, key=lambda row: (abs(row["change24h"]), row["volume"]), reverse=True)[:10]
        signals = []
        if direction != "NEUTRAL":
            with ThreadPoolExecutor(max_workers=6) as pool:
                jobs = [pool.submit(analyse_candidate, kind, row, interval, direction) for row in candidates]
                for job in as_completed(jobs):
                    signal = job.result()
                    if signal:
                        signals.append(signal)
        signals.sort(key=lambda row: (row["quality_score"], abs(row["change24h"])), reverse=True)
        signals = signals[:3]
        save_new_trades(kind, signals)
        with db() as connection:
            active = [dict(row) for row in connection.execute(
                "SELECT * FROM trades WHERE market=? AND status='OPEN' ORDER BY created_at DESC LIMIT 100", (kind,)
            ).fetchall()]
        return jsonify({
            "ok": True, "market": kind, "direction": direction, "direction_ar": {"BUY": "صاعد", "SELL": "هابط", "NEUTRAL": "محايد"}[direction],
            "up": up, "down": down, "total": len(assets), "timeframe": interval,
            "signals": signals, "open_trades": active, "updated": int(time.time()),
            "source": "Binance public market data", "strategy": "EMA20/50 + RSI14 + ATR14 + 4h/1d confirmation",
            "score_note": "درجة جودة الشروط وليست نسبة نجاح أو احتمال ربح."
        })
    except requests.RequestException:
        return jsonify({"ok": False, "error": "تعذر الاتصال بمصدر السوق الآن؛ لم نستخدم بيانات قديمة أو وهمية."}), 502

@app.get("/api/trades")
def trades():
    market_id = request.args.get("market", "")
    with db() as connection:
        if market_id:
            rows = connection.execute("SELECT * FROM trades WHERE market=? ORDER BY created_at DESC LIMIT 200", (market_id,)).fetchall()
        else:
            rows = connection.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT 200").fetchall()
    return jsonify({"items": [dict(row) for row in rows]})

@app.errorhandler(404)
def missing(_):
    return jsonify({"error": "not_found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
