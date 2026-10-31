import os
import sqlite3
import threading
import time
from datetime import datetime
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

try:
    import yfinance as yf
except ImportError:
    yf = None
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")
BASES = {"spot": "https://api.binance.com", "futures": "https://fapi.binance.com"}
SPOT_BASES = ["https://api.binance.com", "https://api-gcp.binance.com", "https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com", "https://data-api.binance.vision"]
ALPHA_BASE = "https://www.binance.com"
BIQUOTE_BASE = "https://biquote.io"
YAHOO_ENABLED = os.environ.get("YAHOO_FINANCE_ENABLED", "0") == "1"
YAHOO_SYMBOLS = {
    "us": [x.strip().upper() for x in os.environ.get("YAHOO_US_SYMBOLS", "").split(",") if x.strip()],
    "saudi": [x.strip().upper() for x in os.environ.get("YAHOO_SAUDI_SYMBOLS", "").split(",") if x.strip()],
}
SCAN_INTERVAL = "15m"
STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EUR"}
CACHE = {}
CACHE_LOCK = threading.Lock()
CACHE_KEY_LOCKS = {}
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path("/tmp")
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "trades.sqlite3")))

MARKETS = [
    {"id": "spot", "name": "Binance Spot", "provider": "Binance", "status": "live"},
    {"id": "futures", "name": "Binance Futures", "provider": "Binance", "status": "live"},
    {"id": "alpha", "name": "Binance Alpha", "provider": "Binance public Alpha data", "status": "live"},
    {"id": "saudi", "name": "السوق السعودي", "provider": "Yahoo Finance (opt-in)", "status": "optional_disabled"},
    {"id": "us", "name": "الأسهم الأمريكية", "provider": "Yahoo Finance (opt-in)", "status": "optional_disabled"},
    {"id": "contracts", "name": "العقود الأمريكية", "provider": None, "status": "provider_required"},
    {"id": "forex", "name": "الفوركس والذهب", "provider": "BiQuote public FX/Metals feed (no key)", "status": "live"},
]

def cached(key, ttl, loader):
    # Serialize refreshes per key so concurrent page requests do not stampede
    # Binance with identical ticker/candle requests.
    with CACHE_LOCK:
        item = CACHE.get(key)
        if item and time.time() - item[0] < ttl:
            return item[1]
        key_lock = CACHE_KEY_LOCKS.setdefault(key, threading.Lock())
    with key_lock:
        with CACHE_LOCK:
            item = CACHE.get(key)
            if item and time.time() - item[0] < ttl:
                return item[1]
        value = loader()
        with CACHE_LOCK:
            CACHE[key] = (time.time(), value)
        return value

def fetch_json(url, params=None):
    response = requests.get(url, params=params, timeout=(3.5, 7), headers={"User-Agent": "SmartTradingPro/2.0"})
    response.raise_for_status()
    return response.json()


def fetch_first_json(urls, params=None):
    """Try documented public endpoints in order; never return cached stale data on total failure."""
    errors = []
    for url in urls:
        try:
            return fetch_json(url, params)
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
    raise requests.RequestException("All public provider endpoints failed: " + " | ".join(errors[-3:]))


def biquote_market_tickers():
    """Discover live FX/metal symbols from BiQuote and batch-fetch fresh quotes."""
    symbols_payload = cached(
        "biquote:active-symbols", 120,
        lambda: fetch_json(BIQUOTE_BASE + "/api/active")
    )
    if not isinstance(symbols_payload, list):
        raise requests.RequestException("BiQuote returned an invalid symbol catalogue")
    symbols = []
    for row in symbols_payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("name") or row.get("symbol") or "").upper()
        kind = str(row.get("type") or "").lower()
        if symbol and kind in ("forex", "commodity"):
            symbols.append(symbol)
    symbols = list(dict.fromkeys(symbols))
    output = []
    for offset in range(0, len(symbols), 40):
        batch = symbols[offset:offset + 40]
        if not batch:
            continue
        params = [("symbols", symbol) for symbol in batch]
        payload = cached(
            "biquote:latest:" + ",".join(batch), 20,
            lambda params=params: fetch_json(BIQUOTE_BASE + "/api/latest", params)
        )
        if isinstance(payload, dict):
            rows = payload.get("items") or payload.get("data") or payload.get("quotes") or []
            if not rows and all(isinstance(v, dict) for v in payload.values()):
                rows = list(payload.values())
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or row.get("name") or "").upper()
            try:
                price = float(row.get("mid") or row.get("last") or 0)
                change = float(row.get("dayDiffPercent") or row.get("changePercent") or 0)
                age = float(row.get("quoteAgeSeconds", 0))
            except (TypeError, ValueError):
                continue
            if (symbol in batch and price > 0 and not row.get("stale", False)
                    and age <= 300 and str(row.get("marketState", "open")).lower() == "open"):
                output.append({
                    "symbol": symbol, "price": price, "volume": 0.0,
                    "change24h": change, "quote_age_seconds": age,
                })
    if not output:
        raise requests.RequestException("BiQuote has no fresh open FX/metal quotes")
    return output


def biquote_candles(symbol, interval):
    payload = fetch_json(
        BIQUOTE_BASE + f"/api/{symbol}/ohlc",
        {"interval": interval, "limit": 100},
    )
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, list):
        raise requests.RequestException("BiQuote returned invalid OHLC bars")
    rows = []
    for bar in bars:
        if not isinstance(bar, dict) or bar.get("isOpen"):
            continue
        try:
            stamp = str(bar["openTime"]).replace("Z", "+00:00")
            timestamp = int(datetime.fromisoformat(stamp).timestamp() * 1000)
            row = {
                "open": float(bar["open"]), "high": float(bar["high"]),
                "low": float(bar["low"]), "close": float(bar["close"]),
                "volume": float(bar.get("tickVolume") or bar.get("volume") or 0),
                "time": timestamp,
            }
        except (KeyError, TypeError, ValueError):
            continue
        if row["close"] > 0 and row["high"] >= row["low"]:
            rows.append(row)
    rows.sort(key=lambda item: item["time"])
    return rows



def yahoo_market_tickers(kind):
    """Fetch a configured Yahoo watchlist; never pretend it is the whole market."""
    if not YAHOO_ENABLED or yf is None:
        raise requests.RequestException("Yahoo Finance integration is disabled")
    symbols = YAHOO_SYMBOLS.get(kind, [])
    if not symbols:
        raise requests.RequestException(f"No Yahoo symbols configured for {kind}")
    output = []
    now = time.time()
    for symbol in symbols[:100]:
        try:
            frame = yf.Ticker(symbol).history(period="5d", interval="15m", auto_adjust=True, timeout=12)
            if frame is None or frame.empty or "Close" not in frame:
                continue
            frame = frame.dropna(subset=["Close"]).sort_index()
            if len(frame) < 55:
                continue
            stamp = frame.index[-1]
            if getattr(stamp, "tzinfo", None) is None:
                stamp = stamp.tz_localize("UTC")
            age = now - stamp.timestamp()
            if age < 0 or age > 45 * 60:
                continue
            price = float(frame["Close"].iloc[-1])
            prior = float(frame["Close"].iloc[max(0, len(frame) - 27)])
            volume = float(frame["Volume"].tail(26).fillna(0).sum() * price)
            if price <= 0 or prior <= 0:
                continue
            output.append({"symbol": symbol, "price": price, "volume": volume,
                           "change24h": (price / prior - 1) * 100,
                           "quote_age_seconds": int(age)})
        except Exception as exc:
            app.logger.warning("Yahoo quote failed for %s: %s", symbol, exc)
    if not output:
        raise requests.RequestException("Yahoo returned no fresh 15m quotes for the configured watchlist")
    return output


def yahoo_candles(symbol, interval):
    if not YAHOO_ENABLED or yf is None:
        raise requests.RequestException("Yahoo Finance integration is disabled")
    frame = yf.Ticker(symbol).history(period="5d", interval=interval, auto_adjust=True, timeout=12)
    if frame is None or frame.empty:
        raise requests.RequestException("Yahoo returned no candle history")
    rows = []
    now_ms = int(time.time() * 1000)
    for stamp, bar in frame.iterrows():
        try:
            if getattr(stamp, "tzinfo", None) is None:
                stamp = stamp.tz_localize("UTC")
            timestamp = int(stamp.timestamp() * 1000)
            if timestamp + 15 * 60 * 1000 > now_ms:
                continue
            row = {"open": float(bar["Open"]), "high": float(bar["High"]),
                   "low": float(bar["Low"]), "close": float(bar["Close"]),
                   "volume": float(bar.get("Volume", 0) or 0), "time": timestamp}
            if row["close"] > 0 and row["high"] >= row["low"]:
                rows.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda item: item["time"])
    return rows

def alpha_market_tickers():
    token_url = ALPHA_BASE + "/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
    info_url = ALPHA_BASE + "/bapi/defi/v1/public/alpha-trade/get-exchange-info"
    token_response = cached("alpha:tokens", 180, lambda: fetch_json(token_url))
    info_response = cached("alpha:exchange-info", 300, lambda: fetch_json(info_url))
    if not token_response.get("success") or not info_response.get("success"):
        raise requests.RequestException("Binance Alpha public market data unavailable")
    data = token_response.get("data") or []
    info = info_response.get("data") or {}
    tradable = {
        row.get("symbol") for row in info.get("symbols", [])
        if row.get("status") == "TRADING" and row.get("quoteAsset") == "USDT"
    }
    output = []
    for token in data:
        symbol_id = str(token.get("alphaId") or "")
        pair = symbol_id + "USDT"
        if not symbol_id.startswith("ALPHA_") or pair not in tradable or token.get("offline"):
            continue
        try:
            price = float(token.get("price") or 0)
            volume = float(token.get("volume24h") or 0)
            change = float(token.get("percentChange24h") or 0)
        except (TypeError, ValueError):
            continue
        if price > 0 and volume > 0:
            output.append({
                "symbol": pair, "price": price, "volume": volume,
                "change24h": change, "asset": token.get("symbol") or symbol_id,
            })
    return output

def market_tickers(kind):
    if kind == "alpha":
        return cached("alpha:universe", 60, alpha_market_tickers)
    if kind == "forex":
        return cached("forex:universe", 20, biquote_market_tickers)
    if kind in ("saudi", "us"):
        return cached(f"yahoo:{kind}:universe", 60, lambda: yahoo_market_tickers(kind))
    base = BASES[kind]
    path = "/api/v3/ticker/24hr" if kind == "spot" else "/fapi/v1/ticker/24hr"
    if kind == "spot":
        rows = cached(kind + ":tickers", 20, lambda: fetch_first_json([host + path for host in SPOT_BASES]))
    else:
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
    if kind == "forex":
        return cached(f"{kind}:{symbol}:{interval}", 45, lambda: biquote_candles(symbol, interval))
    if kind in ("saudi", "us"):
        return cached(f"{kind}:{symbol}:{interval}", 45, lambda: yahoo_candles(symbol, interval))
    if kind == "alpha":
        path = "/bapi/defi/v1/public/alpha-trade/klines"
        payload = cached(f"{kind}:{symbol}:{interval}", 45, lambda: fetch_json(
            ALPHA_BASE + path, {"symbol": symbol, "interval": interval, "limit": 100}))
        if not payload.get("success"):
            raise requests.RequestException("Binance Alpha candles unavailable")
        raw = payload.get("data") or []
    else:
        path = "/api/v3/klines" if kind == "spot" else "/fapi/v1/klines"
        raw = cached(f"{kind}:{symbol}:{interval}", 45,
                     lambda: fetch_json(BASES[kind] + path, {"symbol": symbol, "interval": interval, "limit": 100}))
    rows = []
    now_ms = int(time.time() * 1000)
    for item in raw:
        try:
            # Binance/Alpha return the currently forming candle as the last row.
            # Never calculate an entry signal from an unfinished 15m candle.
            if len(item) > 6 and int(item[6]) >= now_ms:
                continue
            row = {"open": float(item[1]), "high": float(item[2]), "low": float(item[3]),
                   "close": float(item[4]), "volume": float(item[5]), "time": int(item[0])}
            if row["close"] > 0 and row["high"] >= row["low"]:
                rows.append(row)
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort(key=lambda row: row["time"])
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

def analyse_candidate(kind, item, market_direction):
    try:
        selected = candles(kind, item["symbol"], SCAN_INTERVAL)
        if len(selected) < 55:
            return None
        side = frame_bias(selected)
        if side not in ("BUY", "SELL") or side != market_direction:
            return None
        closes = [x["close"] for x in selected]
        # Indicators use only completed candles; the executable entry reference
        # is the latest validated market quote, not the previous candle close.
        current = float(item["price"])
        momentum = rsi(closes)
        if momentum is None or (side == "BUY" and not 50 <= momentum <= 75) or (side == "SELL" and not 25 <= momentum <= 50):
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
            "change24h": item["change24h"], "volume": item["volume"], "timeframe": SCAN_INTERVAL,
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
            tp3_hit INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, closed_at INTEGER
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(trades)")}
        if "tp3_hit" not in columns:
            connection.execute("ALTER TABLE trades ADD COLUMN tp3_hit INTEGER NOT NULL DEFAULT 0")
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
            required = ("symbol", "timeframe", "side", "entry", "stop_loss", "tp1", "tp2", "tp3")
            if any(key not in signal or signal[key] is None for key in required):
                continue
            try:
                entry, stop, tp1, tp2, tp3 = (float(signal[key]) for key in ("entry", "stop_loss", "tp1", "tp2", "tp3"))
            except (TypeError, ValueError):
                continue
            if not all(value > 0 for value in (entry, stop, tp1, tp2, tp3)):
                continue
            if signal["side"] == "BUY" and not (stop < entry < tp1 < tp2 < tp3):
                continue
            if signal["side"] == "SELL" and not (stop > entry > tp1 > tp2 > tp3):
                continue
            if signal["side"] not in ("BUY", "SELL"):
                continue
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
                tp3_hit=MAX(tp3_hit,?), status=?,updated_at=?,closed_at=? WHERE id=?""",
                (int(tp1_hit), int(tp2_hit), int(tp3_hit), status, now, now if status != "OPEN" else None, trade["id"]))
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
    database = "ok"
    try:
        with db() as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        database = "error"
    return jsonify({
        "ok": database == "ok",
        "service": "smart-trading-pro",
        "status": "healthy" if database == "ok" else "degraded",
        "database": database,
        "live_markets": [item["id"] for item in MARKETS if item["status"] == "live"],
    }), (200 if database == "ok" else 503)

@app.get("/api/markets")
def markets():
    rows = [dict(item) for item in MARKETS]
    for item in rows:
        if item["id"] in ("saudi", "us"):
            configured = YAHOO_ENABLED and yf is not None and bool(YAHOO_SYMBOLS.get(item["id"]))
            item["status"] = "configured_watchlist" if configured else "provider_required"
    return jsonify({"markets": rows})


@app.get("/api/providers")
def providers():
    """Expose provider truth: configured, verified fallback routes versus candidates not integrated."""
    return jsonify({"markets": [
        {"id": "spot", "primary": "Binance Public REST", "fallbacks": [
            "api-gcp.binance.com", "api1.binance.com", "api2.binance.com",
            "api3.binance.com", "api4.binance.com", "data-api.binance.vision"
        ], "status": "configured", "note": "Official public endpoints; spot fallback is active."},
        {"id": "futures", "primary": "Binance USD-M Futures REST", "fallbacks": [],
         "status": "single_source", "note": "Only one documented public base endpoint; no fake mirrors configured."},
        {"id": "alpha", "primary": "Binance Alpha public endpoints", "fallbacks": [],
         "status": "single_source", "note": "No verified equivalent Alpha public backup."},
        {"id": "forex", "primary": "BiQuote public REST", "fallbacks": [],
         "status": "configured_unverified_runtime", "note": "No-key FX/metal quotes and 15m OHLC; source must pass live freshness checks."},
        {"id": "saudi", "primary": "Yahoo Finance via yfinance", "fallbacks": [],
         "status": "optional_disabled" if not YAHOO_ENABLED else ("configured_watchlist" if YAHOO_SYMBOLS["saudi"] else "symbols_required"),
         "note": "Unofficial Yahoo client; private/internal testing only. Configure YAHOO_SAUDI_SYMBOLS; fresh 15m bars required."},
        {"id": "us", "primary": "Yahoo Finance via yfinance", "fallbacks": [],
         "status": "optional_disabled" if not YAHOO_ENABLED else ("configured_watchlist" if YAHOO_SYMBOLS["us"] else "symbols_required"),
         "note": "Unofficial Yahoo client; private/internal testing only. Configure YAHOO_US_SYMBOLS; fresh 15m bars required."},
        {"id": "contracts", "primary": None, "fallbacks": [],
         "status": "provider_required", "note": "No verified no-key 15m futures/options source integrated."}
    ]})


@app.get("/api/market/<kind>")
def market(kind):
    if kind not in BASES and kind not in ("alpha", "forex", "saudi", "us"):
        return jsonify({"ok": False, "status": "provider_required", "message": "مزود البيانات لهذا السوق غير مربوط؛ لن نعرض بيانات غير موثوقة.", "signals": []}), 503
    if kind in ("saudi", "us") and (not YAHOO_ENABLED or yf is None or not YAHOO_SYMBOLS.get(kind)):
        return jsonify({"ok": False, "status": "provider_required", "message": "Yahoo غير مفعّل أو قائمة الرموز غير مضبوطة؛ لم نعرض بيانات غير مكتملة.", "signals": []}), 503
    try:
        assets = cached(kind + ":universe", 20, lambda: market_tickers(kind))
        up = sum(1 for row in assets if row["change24h"] > 0)
        down = sum(1 for row in assets if row["change24h"] < 0)
        flat = len(assets) - up - down
        direction = "BUY" if up > down else ("SELL" if down > up else "NEUTRAL")
        gainers = sorted((row for row in assets if row["change24h"] > 0),
                         key=lambda row: row["change24h"], reverse=True)[:3]
        losers = sorted((row for row in assets if row["change24h"] < 0),
                        key=lambda row: row["change24h"])[:3]
        movers = gainers + losers
        prices = {row["symbol"]: row["price"] for row in assets}
        update_open_trades(kind, prices)
        candidates = sorted(assets, key=lambda row: (abs(row["change24h"]), row["volume"]), reverse=True)[:20]
        signals = []
        if direction != "NEUTRAL":
            with ThreadPoolExecutor(max_workers=6) as pool:
                jobs = [pool.submit(analyse_candidate, kind, row, direction) for row in candidates]
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
            "up": up, "down": down, "flat": flat, "total": len(assets), "timeframe": SCAN_INTERVAL,
            "movers": movers, "signals": signals, "open_trades": active, "updated": int(time.time()),
            "source": ("Yahoo Finance (private/internal test watchlist)" if kind in ("saudi", "us") else "Binance Alpha public market data" if kind == "alpha" else "BiQuote public FX/Metals feed" if kind == "forex" else "Binance public market data"), "strategy": "15m EMA20/50 + RSI14 + ATR14",
            "score_note": "درجة جودة الشروط وليست نسبة نجاح أو احتمال ربح."
        })
    except requests.RequestException:
        app.logger.exception("Market provider request failed: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الاتصال بمصدر السوق الآن؛ لم نستخدم بيانات قديمة أو وهمية.", "market": kind}), 502
    except sqlite3.Error:
        app.logger.exception("Trade database failure: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الوصول إلى سجل الصفقات. تحقق من وحدة التخزين الدائمة.", "market": kind}), 503

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
