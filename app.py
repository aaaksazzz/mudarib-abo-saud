import os
import sqlite3
import threading
import time
from datetime import datetime
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from functools import wraps
import re
import xml.etree.ElementTree as ET

import requests
from gamma_engine import analyse_liquidity_candidate
from market_ranking import rank_market_assets
from institutional_flow import analyse_orderbook_flow
from scan_rotation import select_scan_batch, select_priority_scan_batch

try:
    import yfinance as yf
except ImportError:
    yf = None
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
AUTH_CONFIGURED = bool(len(SECRET_KEY) >= 32 and ADMIN_EMAIL and len(ADMIN_PASSWORD) >= 12)
app.secret_key = SECRET_KEY or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)
BASES = {"spot": "https://api.binance.com", "futures": "https://fapi.binance.com", "coinm": "https://dapi.binance.com"}
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
SCAN_CURSORS = {}
SCAN_CURSOR_LOCK = threading.Lock()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).expanduser()
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "trades.sqlite3"))).expanduser()
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    # Never silently fall back to ephemeral storage: that would make trade
    # history appear to vanish after a container restart.
    raise RuntimeError(
        f"Persistent trade database directory is unavailable: {DB_PATH.parent}"
    ) from exc
DB_INIT_LOCK = threading.Lock()
SAVE_NEW_TRADES_LOCK = threading.Lock() 
SUBSCRIPTION_PRICES={1:30,2:60,3:90,6:180,12:360}
PAYMENT_WALLETS={"solana":{"label":"Solana","address":"8mUuMV7WFNTsFEmGsw3t5EpTWGUzw5618Mjgh1svugaH"},"trc20":{"label":"TRC20","address":"TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"},"binance_pay":{"label":"Binance Pay","address":"28191866"}}
USDT_SOLANA_MINT="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDT_TRC20_CONTRACT="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6"
SECTION_NAMES={"spot":"Binance Spot","futures":"Binance Futures","coinm":"COIN-M","alpha":"Binance Alpha","saudi":"السوق السعودي","us":"الأسهم الأمريكية","contracts":"العقود الأمريكية","forex":"الفوركس والذهب","direction":"توجه السوق","opportunities":"فرص التداول","open-trades":"متابعة الصفقات","history":"سجل الصفقات","news":"الأخبار","blog":"المدونة"}


MARKETS = [
    {"id": "spot", "name": "Binance Spot", "provider": "Binance", "status": "live"},
    {"id": "futures", "name": "Binance USD-M Futures", "provider": "Binance", "status": "live"},
    {"id": "coinm", "name": "Binance COIN-M Futures", "provider": "Binance", "status": "live"},
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
            recent = frame.tail(26)
            volume = float(recent["Volume"].fillna(0).sum() * price)
            if price <= 0 or prior <= 0:
                continue
            if volume < 1_000_000:
                continue
            high = float(recent["High"].max()) if "High" in recent else price
            low = float(recent["Low"].min()) if "Low" in recent else price
            output.append({"symbol": symbol, "price": price, "volume": volume,
                           "change24h": (price / prior - 1) * 100,
                           "range24h": ((high - low) / price * 100) if high >= low > 0 else 0.0,
                           "quote_age_seconds": int(age)})
        except Exception as exc:
            app.logger.warning("Yahoo quote failed for %s: %s", symbol, exc)
    if not output:
        raise requests.RequestException("Yahoo returned no fresh 15m quotes for the configured watchlist")
    return output


def yahoo_candles(symbol, interval):
    if not YAHOO_ENABLED or yf is None:
        raise requests.RequestException("Yahoo Finance integration is disabled")
    # Yahoo's hourly endpoint does not offer native 4h bars. Build them
    # from hourly OHLCV; request enough history for stable 4h and daily structure.
    fetch_interval = {"4h": "60m", "1w": "1wk", "1M": "1mo"}.get(interval, interval)
    period = ("10y" if interval == "1M" else "5y" if interval == "1w"
              else "1y" if interval == "1d" else "3mo" if interval in ("1h", "4h") else "5d")
    frame = yf.Ticker(symbol).history(period=period, interval=fetch_interval, auto_adjust=True, timeout=12)
    if frame is None or frame.empty:
        raise requests.RequestException("Yahoo returned no candle history")
    if interval == "4h":
        frame = frame.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna(subset=["Open", "High", "Low", "Close"])
    rows = []
    now_ms = int(time.time() * 1000)
    for stamp, bar in frame.iterrows():
        try:
            if getattr(stamp, "tzinfo", None) is None:
                stamp = stamp.tz_localize("UTC")
            timestamp = int(stamp.timestamp() * 1000)
            if interval == "1M":
                current = datetime.utcfromtimestamp(now_ms / 1000)
                if stamp.year == current.year and stamp.month == current.month:
                    continue
            else:
                candle_ms = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000,
                             "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000,
                             "1w": 7 * 24 * 60 * 60 * 1000}.get(interval, 15 * 60 * 1000)
                if timestamp + candle_ms > now_ms:
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
        if price > 0 and volume >= 1_000_000:
            output.append({
                "symbol": pair, "price": price, "volume": volume,
                "change24h": change, "asset": token.get("symbol") or symbol_id,
            })
    return output

def binance_active_symbols(kind):
    """Return currently tradable USDT symbols from Binance exchange metadata."""
    path = "/api/v3/exchangeInfo" if kind == "spot" else ("/dapi/v1/exchangeInfo" if kind == "coinm" else "/fapi/v1/exchangeInfo")
    urls = [host + path for host in SPOT_BASES] if kind == "spot" else [BASES[kind] + path]
    payload = cached(kind + ":exchange-info", 300, lambda: fetch_first_json(urls))
    symbols = set()
    for row in payload.get("symbols", []):
        expected_quote = "USD" if kind == "coinm" else "USDT"
        # Binance COIN-M exchangeInfo uses contractStatus; Spot and USD-M use status.
        status_field = "contractStatus" if kind == "coinm" else "status"
        if row.get(status_field) != "TRADING" or row.get("quoteAsset") != expected_quote:
            continue
        if kind == "spot" and row.get("isSpotTradingAllowed") is False:
            continue
        if kind in ("futures", "coinm") and row.get("contractType") != "PERPETUAL":
            continue
        symbols.add(str(row.get("symbol", "")))
    if not symbols:
        quote = "USD" if kind == "coinm" else "USDT"
        raise requests.RequestException(f"Binance returned no active {kind} {quote} symbols")
    return symbols


def market_tickers(kind):
    if kind == "alpha":
        return cached("alpha:universe", 60, alpha_market_tickers)
    if kind == "forex":
        return cached("forex:universe", 20, biquote_market_tickers)
    if kind in ("saudi", "us"):
        return cached(f"yahoo:{kind}:universe", 60, lambda: yahoo_market_tickers(kind))
    base = BASES[kind]
    path = "/api/v3/ticker/24hr" if kind == "spot" else ("/dapi/v1/ticker/24hr" if kind == "coinm" else "/fapi/v1/ticker/24hr")
    if kind == "spot":
        rows = cached(kind + ":tickers", 20, lambda: fetch_first_json([host + path for host in SPOT_BASES]))
    else:
        rows = cached(kind + ":tickers", 20, lambda: fetch_json(base + path))
    active_symbols = cached(kind + ":active-symbols", 300, lambda: binance_active_symbols(kind))
    output = []
    for row in rows:
        symbol = str(row.get("symbol", ""))
        if symbol not in active_symbols:
            continue
        if kind == "coinm":
            if not symbol.endswith("_PERP"):
                continue
        elif not symbol.endswith("USDT") or symbol[:-4] in STABLES:
            continue
        try:
            price = float(row["lastPrice"])
            volume = float(row.get("quoteVolume", 0))
            change = float(row.get("priceChangePercent", 0))
            high = float(row.get("highPrice", 0) or 0)
            low = float(row.get("lowPrice", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and volume >= 1_000_000:
            output.append({"symbol": symbol, "price": price, "volume": volume, "change24h": change,
                           "range24h": ((high - low) / price * 100) if high >= low > 0 else 0.0})
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
        path = "/api/v3/klines" if kind == "spot" else ("/dapi/v1/klines" if kind == "coinm" else "/fapi/v1/klines")
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

def analyse_candidate(kind, item, market_direction=None, diagnostics=None, timeframe="15m"):
    """Require aligned 4h + daily direction, rank/confirm the entry on the selected timeframe."""
    def reject(reason):
        if diagnostics is not None:
            diagnostics["reason"] = reason
        return None

    try:
        from timeframe_strategy import assess_timeframe

        reference_rows = {
            "4h": candles(kind, item["symbol"], "4h"),
            "1d": candles(kind, item["symbol"], "1d"),
        }
        if any(len(rows) < 35 for rows in reference_rows.values()):
            if diagnostics is not None:
                diagnostics["reference_candles"] = {key: len(rows) for key, rows in reference_rows.items()}
                diagnostics["candles_required"] = 35
            return reject("insufficient_reference_candles")

        reference = {key: assess_timeframe(rows) for key, rows in reference_rows.items()}
        buy_states = {"BUY", "STRONG_BUY"}
        sell_states = {"SELL", "STRONG_SELL"}
        states = [reference["4h"]["state"], reference["1d"]["state"]]
        if all(state in buy_states for state in states):
            side = "BUY"
        elif all(state in sell_states for state in states):
            side = "SELL"
        else:
            if diagnostics is not None:
                diagnostics["reference_states"] = {"4h": states[0], "1d": states[1]}
            return reject("reference_timeframes_not_aligned")

        # Market-wide direction is a hard trade-side gate, not a ranking hint:
        # bullish breadth permits BUY only; bearish breadth permits SELL only.
        # Neutral/unknown breadth blocks all new trades.
        if market_direction not in ("BUY", "SELL"):
            return reject("market_direction_neutral_no_new_trades")
        if side != market_direction:
            if diagnostics is not None:
                diagnostics["market_direction"] = market_direction
                diagnostics["candidate_side"] = side
            return reject("candidate_side_conflicts_with_market_direction")

        entry_rows = candles(kind, item["symbol"], timeframe)
        if len(entry_rows) < 35:
            if diagnostics is not None:
                diagnostics["candles_received"] = len(entry_rows)
                diagnostics["candles_required"] = 35
            return reject("insufficient_candles")
        if diagnostics is not None:
            diagnostics["candles_ready"] = True

        # Entry is triggered by a completed-candle liquidity sweep or absorption,
        # not by a second indicator-direction score on the entry timeframe.
        entry_diagnostics = {}
        levels = analyse_liquidity_candidate(
            entry_rows, item["price"], side, market_kind=kind,
            diagnostics=entry_diagnostics,
        )
        if not levels:
            return reject(entry_diagnostics.get("reason", "liquidity_setup_not_confirmed"))

        ranking_rows = entry_rows if timeframe == "15m" else candles(kind, item["symbol"], "15m")
        if len(ranking_rows) < 2:
            return reject("insufficient_15m_ranking_candles")
        closes = [float(row["close"]) for row in ranking_rows[-2:]]
        change_tf = (closes[-1] / closes[-2] - 1) * 100 if closes[-2] else 0.0
        reference_state = (
            "STRONG_BUY" if side == "BUY" and all(state == "STRONG_BUY" for state in states)
            else "STRONG_SELL" if side == "SELL" and all(state == "STRONG_SELL" for state in states)
            else side
        )
        state_ar = {"BUY": "شراء", "STRONG_BUY": "شراء قوي",
                    "SELL": "بيع", "STRONG_SELL": "بيع قوي"}
        signal = {
            **levels, "side": side, "price": item["price"],
            "symbol": item["symbol"], "change24h": item["change24h"],
            "change_timeframe": round(change_tf, 4), "volume": item["volume"],
            "fast_mover_score": item.get("fast_mover_score", 0),
            "fast_mover_rank": item.get("fast_mover_rank"),
            "timeframe": timeframe, "signal_candle_time": int(entry_rows[-1]["time"]),
            "strategy": "4H + Daily direction · liquidity sweep/absorption entry",
            "signal_state": reference_state,
            "signal_state_ar": state_ar.get(reference_state, "محايد"),
            "quality_score": levels["quality_score"],
            "entry_analysis": {
                "liquidity_event": levels.get("liquidity_event"),
                "volume_ratio": levels.get("volume_ratio"),
                "flow_pressure": levels.get("flow_pressure"),
                "risk_percent": levels.get("risk_percent"),
            },
            "reference_analysis": reference,
            "analysis_scope": "4h_daily_direction_plus_liquidity_entry",
            "quality_label": "قوة شروط السيولة من 100 وليست احتمال نجاح",
            "analysis_note": "اتجاه 4 ساعات واليومي متوافق؛ الدخول بعد سحب سيولة أو امتصاص مؤكد على الفريم المحدد",
        }
        flow = analyse_orderbook_flow(
            kind, item["symbol"], side,
            lambda url, params: cached(
                f"orderbook:{kind}:{item['symbol']}", 5,
                lambda: fetch_json(url, params)
            ),
        )
        signal["institutional_flow"] = flow
        signal["orderbook_context"] = flow.get("status", "unavailable")
        if diagnostics is not None:
            diagnostics["reason"] = "accepted"
        return signal
    except requests.RequestException:
        return reject("provider_error")
    except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
        return reject("analysis_error")

@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=8)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=8000")
        connection.execute("PRAGMA synchronous=FULL")
        with DB_INIT_LOCK:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL, symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL, side TEXT NOT NULL, entry REAL NOT NULL, stop_loss REAL NOT NULL,
            tp1 REAL NOT NULL, tp2 REAL NOT NULL, tp3 REAL NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            tp1_hit INTEGER NOT NULL DEFAULT 0, tp2_hit INTEGER NOT NULL DEFAULT 0,
            tp3_hit INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, closed_at INTEGER,
            signal_candle_time INTEGER NOT NULL DEFAULT 0
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(trades)")}
        if "tp3_hit" not in columns:
            connection.execute("ALTER TABLE trades ADD COLUMN tp3_hit INTEGER NOT NULL DEFAULT 0")
        if "signal_candle_time" not in columns:
            connection.execute("ALTER TABLE trades ADD COLUMN signal_candle_time INTEGER NOT NULL DEFAULT 0")
        connection.execute("""CREATE TABLE IF NOT EXISTS market_snapshots (
            market TEXT PRIMARY KEY, direction TEXT NOT NULL, up INTEGER NOT NULL,
            down INTEGER NOT NULL, flat INTEGER NOT NULL, total INTEGER NOT NULL,
            source TEXT NOT NULL, updated_at INTEGER NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
            subscription_expires_at INTEGER, created_at INTEGER NOT NULL
        )""") 
        connection.execute("""CREATE TABLE IF NOT EXISTS payment_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,months INTEGER NOT NULL,
            amount_usdt REAL NOT NULL,network TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
            tx_hash TEXT UNIQUE,created_at INTEGER NOT NULL,verified_at INTEGER,note TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS section_settings (
            section TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL)""")
        for section in SECTION_NAMES:
            connection.execute("INSERT OR IGNORE INTO section_settings(section,enabled,updated_at) VALUES(?,1,?)",(section,int(time.time())))

        if AUTH_CONFIGURED:
            admin = connection.execute(
                "SELECT id, password_hash, role FROM users WHERE email=?", (ADMIN_EMAIL,)
            ).fetchone()
            if not admin:
                connection.execute(
                    "INSERT INTO users(email,password_hash,role,created_at) VALUES(?,?,?,?)",
                    (ADMIN_EMAIL, generate_password_hash(ADMIN_PASSWORD), "admin", int(time.time()))
                )
            else:
                # Northflank incident response: the configured bootstrap password is
                # authoritative. Changing ADMIN_PASSWORD rotates the stored admin
                # credential on the next request without deleting users/subscriptions.
                password_matches = check_password_hash(admin["password_hash"], ADMIN_PASSWORD)
                if not password_matches:
                    connection.execute(
                        "UPDATE users SET password_hash=?, role='admin' WHERE id=?",
                        (generate_password_hash(ADMIN_PASSWORD), admin["id"])
                    )
                elif admin["role"] != "admin":
                    connection.execute("UPDATE users SET role='admin' WHERE id=?", (admin["id"],))
        connection.commit()
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_market_snapshot(market, direction, up, down, flat, total, source):
    now = int(time.time())
    with db() as connection:
        connection.execute(
            """INSERT INTO market_snapshots
               (market,direction,up,down,flat,total,source,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(market) DO UPDATE SET
                 direction=excluded.direction, up=excluded.up, down=excluded.down,
                 flat=excluded.flat, total=excluded.total, source=excluded.source,
                 updated_at=excluded.updated_at""",
            (market, direction, int(up), int(down), int(flat), int(total), str(source), now),
        )
    return now


def load_market_snapshot(market):
    with db() as connection:
        row = connection.execute("SELECT * FROM market_snapshots WHERE market=?", (market,)).fetchone()
    return dict(row) if row else None


def load_saved_market_trades(market, timeframe):
    with db() as connection:
        rows = connection.execute(
            """SELECT * FROM trades WHERE market=? AND status='OPEN'
               ORDER BY created_at DESC LIMIT 100""", (market,)
        ).fetchall()
    open_trades = []
    for row in rows:
        trade = dict(row)
        trade.update({
            "current_price": None, "live_pnl_percent": None, "price": None,
            "quality_score": None, "signal_state_ar": "صفقة مؤكدة محفوظة ومفتوحة",
            "fast_mover_score": 0, "change24h": 0, "change_timeframe": 0,
            "institutional_flow": {"status": "unavailable"}, "persisted": True,
        })
        open_trades.append(trade)
    signals = [dict(row) for row in open_trades if row["timeframe"] == timeframe][:3]
    return signals, open_trades

def auth_setup_ready():
    return AUTH_CONFIGURED
 
def subscription_active(user):
    return bool(user and (user["role"]=="admin" or (user["subscription_expires_at"] and int(user["subscription_expires_at"])>int(time.time()))))

def section_enabled(section):
    with db() as c: row=c.execute("SELECT enabled FROM section_settings WHERE section=?",(section,)).fetchone()
    return bool(row["enabled"]) if row else True

def require_paid_access(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        if not auth_setup_ready(): return jsonify({"ok":False,"message":"تسجيل الدخول غير مهيأ."}),503
        user=current_user()
        if not user:return jsonify({"ok":False,"error":"login_required","message":"سجل الدخول أولاً."}),401
        if not subscription_active(user):return jsonify({"ok":False,"error":"subscription_required","message":"يلزم اشتراك نشط."}),403
        return fn(*args,**kwargs)
    return wrapped

def tron_address_hex(address):
    alphabet="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number=0
    for char in address:
        number=number*58+alphabet.index(char)
    raw=number.to_bytes((number.bit_length()+7)//8,"big")
    raw=(b"\\x00"*(len(address)-len(address.lstrip("1"))))+raw
    if len(raw)!=25:raise ValueError("عنوان TRON غير صحيح.")
    import hashlib
    checksum=hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4]
    if checksum!=raw[21:]:raise ValueError("تعذر التحقق من عنوان TRON.")
    return raw[1:21].hex()


def verify_trc20_transfer(txid,expected):
    response=requests.post("https://api.trongrid.io/wallet/gettransactioninfobyid",
                           json={"value":txid},timeout=(4,12))
    response.raise_for_status()
    info=response.json()
    if not info or info.get("id","").lower()!=txid.lower() or (info.get("receipt") or {}).get("result")!="SUCCESS":
        return {"confirmed":False,"reason":"معاملة TRON غير مؤكدة أو فاشلة."}
    receiver=tron_address_hex(PAYMENT_WALLETS["trc20"]["address"])
    contract=tron_address_hex(USDT_TRC20_CONTRACT)
    transfer_topic="ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    for log in info.get("log",[]):
        topics=[str(x).lower().removeprefix("0x") for x in log.get("topics",[])]
        if len(topics)<3 or topics[0]!=transfer_topic:continue
        if str(log.get("address","")).lower().removeprefix("0x")[-40:]!=contract:continue
        if topics[2][-40:]!=receiver:continue
        amount=int(str(log.get("data","0")).removeprefix("0x"),16)/1_000_000
        if amount>=expected:return {"confirmed":True,"amount":amount,"timestamp":int(info.get("blockTimeStamp",0)/1000)}
    return {"confirmed":False,"reason":"لم نعثر على تحويل USDT مؤكّد إلى محفظتك."}

def verify_solana_transfer(signature,expected):
    rpc="https://api.mainnet-beta.solana.com"
    def call(method,params):
        r=requests.post(rpc,json={"jsonrpc":"2.0","id":1,"method":method,"params":params},timeout=(4,15));r.raise_for_status();d=r.json()
        if d.get("error") or "result" not in d:raise ValueError("تعذر قراءة معاملة Solana.")
        return d["result"]
    wallet=PAYMENT_WALLETS["solana"]["address"]
    a=call("getTokenAccountsByOwner",[wallet,{"mint":USDT_SOLANA_MINT},{"encoding":"jsonParsed","commitment":"finalized"}])
    dests={x["pubkey"] for x in a.get("value",[])}
    tx=call("getTransaction",[signature,{"encoding":"jsonParsed","commitment":"finalized","maxSupportedTransactionVersion":0}])
    if not tx or (tx.get("meta") or {}).get("err") is not None:return {"confirmed":False,"reason":"المعاملة غير مؤكدة أو فاشلة."}
    msg=(tx.get("transaction") or {}).get("message") or {};ins=list(msg.get("instructions",[]))
    for group in (tx.get("meta") or {}).get("innerInstructions",[]):ins.extend(group.get("instructions",[]))
    for item in ins:
        p=item.get("parsed") or {};i=p.get("info") or {}
        if p.get("type") not in ("transfer","transferChecked") or i.get("mint")!=USDT_SOLANA_MINT or i.get("destination") not in dests:continue
        t=i.get("tokenAmount") or {};amount=float(t.get("uiAmountString") or int(i.get("amount",0))/(10**int(t.get("decimals",6))))
        if amount>=expected:return {"confirmed":True,"amount":amount,"timestamp":int(tx.get("blockTime") or 0)}
    return {"confirmed":False,"reason":"لم نعثر على تحويل USDT مؤكّد إلى محفظتك."}


def public_user(row):
    now = int(time.time())
    is_admin = row["role"] == "admin"
    expiry = row["subscription_expires_at"]
    active = is_admin or bool(expiry and int(expiry) > now)
    return {"id": row["id"], "email": row["email"], "role": row["role"],
            "is_admin": is_admin, "subscribed": active,
            "subscription_expires_at": expiry}


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as connection:
        return connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def require_login(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not auth_setup_ready():
            return jsonify({"ok": False, "error": "auth_setup_required",
                            "message": "يلزم ضبط SECRET_KEY وبيانات الأدمن في إعدادات الخادم."}), 503
        if current_user() is None:
            return jsonify({"ok": False, "error": "login_required", "message": "سجل الدخول أولاً."}), 401
        return fn(*args, **kwargs)
    return wrapped


def require_subscription(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not auth_setup_ready():
            return jsonify({"ok": False, "error": "auth_setup_required",
                            "message": "نظام الاشتراكات يحتاج إعداد الخادم أولاً."}), 503
        user = current_user()
        if user is None:
            return jsonify({"ok": False, "error": "login_required", "message": "سجل الدخول أولاً."}), 401
        if user["role"] != "admin" and (not user["subscription_expires_at"] or int(user["subscription_expires_at"]) <= int(time.time())):
            return jsonify({"ok": False, "error": "subscription_required",
                            "message": "حسابك غير مشترك أو انتهى اشتراكك. تواصل مع الإدارة لتفعيل الوصول."}), 403
        return fn(*args, **kwargs)
    return wrapped


def require_admin(fn):
    @wraps(fn)
    @require_login
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            return jsonify({"ok": False, "error": "admin_required", "message": "هذه الصفحة للأدمن فقط."}), 403
        return fn(*args, **kwargs)
    return wrapped


@app.before_request
def protect_admin_api_only():
    # Market data and analysis are read-only public endpoints. Account and
    # subscription management remains protected by require_admin decorators.
    # Never apply a subscription gate to every /api route.
    return None


@app.get("/api/auth/me")
def auth_me():
    if not auth_setup_ready():
        return jsonify({"ok": True, "configured": False, "user": None, "auth_available": False, "message": "المشاهدة العامة متاحة؛ يلزم إعداد بيانات الأدمن لتفعيل تسجيل الدخول."}), 200
    user = current_user()
    return jsonify({"ok": True, "configured": True, "user": public_user(user) if user else None})


@app.post("/api/auth/register")
def auth_register():
    if not auth_setup_ready():
        return jsonify({"ok": False, "error": "auth_setup_required", "message": "نظام التسجيل غير مهيأ على الخادم."}), 503
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 190:
        return jsonify({"ok": False, "message": "أدخل بريدًا إلكترونيًا صحيحًا."}), 400
    if len(password) < 10 or len(password) > 200:
        return jsonify({"ok": False, "message": "كلمة المرور يجب أن تكون 10 أحرف على الأقل."}), 400
    try:
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO users(email,password_hash,role,created_at) VALUES(?,?,?,?)",
                (email, generate_password_hash(password), "user", int(time.time()))
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "message": "هذا البريد مسجل مسبقًا."}), 409
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    with db() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return jsonify({"ok": True, "user": public_user(row)}), 201


@app.post("/api/auth/login")
def auth_login():
    if not auth_setup_ready():
        return jsonify({"ok": False, "error": "auth_setup_required", "message": "نظام الدخول غير مهيأ على الخادم."}), 503
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with db() as connection:
        row = connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"ok": False, "message": "البريد أو كلمة المرور غير صحيحة."}), 401
    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return jsonify({"ok": True, "user": public_user(row)})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})
 
@app.get("/api/payments/options")
@require_login
def payment_options():
    return jsonify({"prices":SUBSCRIPTION_PRICES,"networks":{k:{"label":v["label"],"address":v["address"]} for k,v in PAYMENT_WALLETS.items()}})

@app.post("/api/payments/orders")
@require_login
def create_payment_order():
    d=request.get_json(silent=True) or {}
    try:months=int(d.get("months"))
    except (TypeError,ValueError):return jsonify({"ok":False,"message":"اختر مدة صحيحة."}),400
    network=str(d.get("network","")).lower()
    if months not in SUBSCRIPTION_PRICES or network not in PAYMENT_WALLETS:return jsonify({"ok":False,"message":"الباقة أو الشبكة غير مدعومة."}),400
    user=current_user()
    if user["role"]=="admin":return jsonify({"ok":False,"message":"حساب الإدارة لا يحتاج اشتراكاً."}),400
    amount=SUBSCRIPTION_PRICES[months]
    with db() as c:
        cur=c.execute("INSERT INTO payment_orders(user_id,months,amount_usdt,network,created_at) VALUES(?,?,?,?,?)",(user["id"],months,amount,network,int(time.time())))
        oid=cur.lastrowid
    return jsonify({"ok":True,"order":{"id":oid,"months":months,"amount_usdt":amount},"payment":{**PAYMENT_WALLETS[network],"automatic_verification":network in ("trc20","solana")}}),201

@app.post("/api/payments/reference")
@require_login
def submit_binance_pay_reference():
    d=request.get_json(silent=True) or {}
    try:oid=int(d.get("order_id"))
    except (TypeError,ValueError):return jsonify({"ok":False,"message":"طلب غير صحيح."}),400
    reference=str(d.get("reference","")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,120}",reference):return jsonify({"ok":False,"message":"أدخل رقم مرجع التحويل الصحيح."}),400
    user=current_user()
    with db() as c:
        cur=c.execute("UPDATE payment_orders SET note=? WHERE id=? AND user_id=? AND network='binance_pay' AND status='pending'",("مرجع Binance Pay: "+reference,oid,user["id"]))
    if cur.rowcount!=1:return jsonify({"ok":False,"message":"طلب Binance Pay غير موجود أو تمت معالجته."}),404
    return jsonify({"ok":True,"message":"تم إرسال مرجع التحويل للمراجعة داخل المنصة."})


@app.post("/api/payments/verify")
@require_login
def verify_payment():
    d=request.get_json(silent=True) or {}
    try:oid=int(d.get("order_id"))
    except (TypeError,ValueError):return jsonify({"ok":False,"message":"طلب غير صحيح."}),400
    txid=str(d.get("tx_hash","")).strip()
    if not re.fullmatch(r"[A-Za-z0-9]{32,100}",txid):return jsonify({"ok":False,"message":"رقم المعاملة غير صحيح."}),400
    user=current_user()
    with db() as c:order=c.execute("SELECT * FROM payment_orders WHERE id=? AND user_id=?",(oid,user["id"])).fetchone()
    if not order:return jsonify({"ok":False,"message":"الطلب غير موجود."}),404
    if order["status"]=="paid":return jsonify({"ok":True,"message":"الاشتراك مفعّل مسبقاً."})
    if order["network"]=="binance_pay":return jsonify({"ok":False,"message":"Binance Pay يحتاج مراجعة الإدارة؛ لا يمكن التحقق آلياً من المعرّف وحده."}),409
    try:result=verify_trc20_transfer(txid,order["amount_usdt"]) if order["network"]=="trc20" else verify_solana_transfer(txid,order["amount_usdt"])
    except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
        app.logger.warning("Payment verification error: %s",exc);return jsonify({"ok":False,"message":"تعذر التحقق من الشبكة. حاول لاحقاً."}),503
    if not result.get("confirmed"):return jsonify({"ok":False,"message":result.get("reason","لم يتم تأكيد التحويل.")}),422
    if not result.get("timestamp") or int(result["timestamp"]) < int(order["created_at"]):
        return jsonify({"ok":False,"message":"المعاملة أقدم من طلب الدفع أو وقتها غير متاح؛ أنشئ طلباً جديداً وحوّل بعده."}),422
    now=int(time.time())
    try:
        with db() as c:
            cur=c.execute("UPDATE payment_orders SET status='paid',tx_hash=?,verified_at=? WHERE id=? AND user_id=? AND status='pending'",(txid,now,oid,user["id"]))
            if cur.rowcount!=1:return jsonify({"ok":False,"message":"تمت معالجة الطلب مسبقاً."}),409
            row=c.execute("SELECT subscription_expires_at FROM users WHERE id=?",(user["id"],)).fetchone()
            expiry=max(now,int(row["subscription_expires_at"] or 0))+int(order["months"])*30*86400
            c.execute("UPDATE users SET subscription_expires_at=? WHERE id=?",(expiry,user["id"]))
    except sqlite3.IntegrityError:return jsonify({"ok":False,"message":"رقم المعاملة مستخدم سابقاً."}),409
    return jsonify({"ok":True,"message":"تم تأكيد التحويل وتفعيل الاشتراك.","subscription_expires_at":expiry})

@app.get("/api/admin/payments")
@require_admin
def admin_payments():
    with db() as c:rows=c.execute("SELECT p.*,u.email FROM payment_orders p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC LIMIT 100").fetchall()
    return jsonify({"payments":[dict(x) for x in rows]})

@app.post("/api/admin/payments/action")
@require_admin
def admin_payment_action():
    d=request.get_json(silent=True) or {};oid=int(d.get("order_id",0));action=d.get("action")
    if action not in ("approve","reject"):return jsonify({"ok":False,"message":"إجراء غير صحيح."}),400
    with db() as c:
        p=c.execute("SELECT * FROM payment_orders WHERE id=?",(oid,)).fetchone()
        if not p or p["network"]!="binance_pay" or p["status"]!="pending":return jsonify({"ok":False,"message":"طلب Binance Pay المعلق غير موجود."}),404
        if action=="approve":
            now=int(time.time());u=c.execute("SELECT subscription_expires_at FROM users WHERE id=?",(p["user_id"],)).fetchone()
            expiry=max(now,int(u["subscription_expires_at"] or 0))+p["months"]*30*86400
            c.execute("UPDATE users SET subscription_expires_at=? WHERE id=?",(expiry,p["user_id"]))
            c.execute("UPDATE payment_orders SET status='paid',verified_at=? WHERE id=?",(now,oid))
        else:c.execute("UPDATE payment_orders SET status='rejected' WHERE id=?",(oid,))
    return jsonify({"ok":True})

@app.get("/api/access/sections")
@require_paid_access
def access_sections():
    with db() as c: rows=c.execute("SELECT section,enabled FROM section_settings").fetchall()
    return jsonify({"sections":{x["section"]:bool(x["enabled"]) for x in rows}})


@app.get("/api/admin/sections")
@require_admin
def admin_sections():
    with db() as c:rows=c.execute("SELECT section,enabled FROM section_settings ORDER BY section").fetchall()
    return jsonify({"sections":[{"id":x["section"],"name":SECTION_NAMES[x["section"]],"enabled":bool(x["enabled"])} for x in rows]})

@app.post("/api/admin/sections")
@require_admin
def update_admin_section():
    d=request.get_json(silent=True) or {};key=str(d.get("section",""))
    if key not in SECTION_NAMES:return jsonify({"ok":False,"message":"القسم غير معروف."}),400
    enabled=1 if d.get("enabled") is True else 0
    with db() as c:c.execute("UPDATE section_settings SET enabled=?,updated_at=? WHERE section=?",(enabled,int(time.time()),key))
    return jsonify({"ok":True,"enabled":bool(enabled)})


@app.get("/api/admin/users")
@require_admin
def admin_users():
    with db() as connection:
        rows = connection.execute(
            "SELECT id,email,role,subscription_expires_at,created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
    now = int(time.time())
    users = []
    for row in rows:
        item = dict(row)
        item["subscribed"] = item["role"] == "admin" or bool(item["subscription_expires_at"] and item["subscription_expires_at"] > now)
        users.append(item)
    return jsonify({"ok": True, "users": users})


@app.post("/api/admin/subscription")
@require_admin
def admin_subscription():
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "معرّف الحساب غير صحيح."}), 400
    action = str(data.get("action", "grant")).lower()
    with db() as connection:
        target = connection.execute("SELECT id,role,subscription_expires_at FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            return jsonify({"ok": False, "message": "الحساب غير موجود."}), 404
        if target["role"] == "admin":
            return jsonify({"ok": False, "message": "لا يمكن تعديل اشتراك حساب الأدمن."}), 400
        if action == "revoke":
            connection.execute("UPDATE users SET subscription_expires_at=NULL WHERE id=?", (user_id,))
            expiry = None
        elif action == "grant":
            try:
                days = int(data.get("days", 30))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "message": "عدد الأيام غير صحيح."}), 400
            if days < 1 or days > 3650:
                return jsonify({"ok": False, "message": "مدة الاشتراك من يوم إلى 3650 يوم."}), 400
            now = int(time.time())
            start = max(now, int(target["subscription_expires_at"] or 0))
            expiry = start + days * 86400
            connection.execute("UPDATE users SET subscription_expires_at=? WHERE id=?", (expiry, user_id))
        else:
            return jsonify({"ok": False, "message": "الإجراء غير معروف."}), 400
    return jsonify({"ok": True, "subscription_expires_at": expiry})


def save_new_trades(kind, signals):
    """Save at most one trade per symbol/timeframe/completed candle.

    A new completed candle may create a fresh trade even when an earlier trade
    for the same symbol and timeframe is still open or recently closed.
    """
    now = int(time.time())
    inserted = []
    with SAVE_NEW_TRADES_LOCK:
        with db() as connection:
            for signal in signals:
                if len(inserted) >= 3:
                    break
                required = ("symbol", "timeframe", "side", "entry", "stop_loss", "tp1", "tp2", "tp3")
                if any(key not in signal or signal[key] is None for key in required):
                    continue
                try:
                    entry, stop, tp1, tp2, tp3 = (
                        float(signal[key]) for key in ("entry", "stop_loss", "tp1", "tp2", "tp3")
                    )
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
                try:
                    candle_time = int(signal.get("signal_candle_time") or now)
                except (TypeError, ValueError, OverflowError):
                    continue
                recent = connection.execute(
                    """SELECT id FROM trades
                       WHERE market=? AND symbol=? AND timeframe=? AND signal_candle_time=?
                       LIMIT 1""",
                    (kind, signal["symbol"], signal["timeframe"], candle_time)
                ).fetchone()
                if recent:
                    continue
                connection.execute("""INSERT INTO trades
                    (market,symbol,timeframe,side,entry,stop_loss,tp1,tp2,tp3,created_at,updated_at,signal_candle_time)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (kind, signal["symbol"], signal["timeframe"], signal["side"], entry,
                     stop, tp1, tp2, tp3, now, now, candle_time))
                inserted.append(signal)
            connection.commit()
    return inserted

def update_open_trades(kind, prices):
    now = int(time.time())
    expiry_seconds = 24 * 60 * 60
    with db() as connection:
        rows = connection.execute("SELECT * FROM trades WHERE market=? AND status='OPEN'", (kind,)).fetchall()
        for trade in rows:
            # Expire stale opportunities even when a provider has no current quote.
            if now - int(trade["created_at"]) >= expiry_seconds:
                connection.execute(
                    "UPDATE trades SET status='EXPIRED',updated_at=?,closed_at=? WHERE id=?",
                    (now, now, trade["id"]),
                )
                continue
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
        return send_from_directory("static", "index.html"), 404
    return send_from_directory("static", "index.html")

@app.get("/sections/<section_id>")
def section_page(section_id):
    allowed = {"direction", "movers", "opportunities", "open-trades", "history", "system"}
    if section_id not in allowed:
        return send_from_directory("static", "index.html"), 404
    return send_from_directory("static", "index.html")

@app.get("/blog")
@app.get("/news")
@app.get("/admin")
def editorial_page():
    return send_from_directory("static", "index.html")

@app.get("/api/news")
@require_paid_access
def latest_news():
    if current_user()["role"]!="admin" and not section_enabled("news"):
        return jsonify({"ok":False,"error":"section_locked","message":"قسم الأخبار مغلق من الإدارة."}),403

    def load_news():
        url = "https://news.google.com/rss/search?q=markets+crypto+stocks+forex&hl=ar&gl=SA&ceid=SA:ar"
        response = requests.get(url, timeout=(3.5, 7), headers={"User-Agent": "SmartTradingPro/2.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for node in root.findall("./channel/item")[:20]:
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            source = (node.findtext("source") or "Google News").strip()
            published = (node.findtext("pubDate") or "").strip()
            if title and link.startswith(("https://", "http://")):
                items.append({"title": title, "url": link, "source": source, "published": published})
        return items
    try:
        items = cached("editorial:news:ar", 300, load_news)
        return jsonify({"items": items, "source": "Google News RSS", "updated": int(time.time())})
    except (requests.RequestException, ET.ParseError):
        app.logger.exception("News feed unavailable")
        return jsonify({"items": [], "source": "Google News RSS", "error": "تعذر جلب الأخبار حاليًا؛ حاول التحديث لاحقًا."}), 502

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
        "trade_storage": "mounted_volume" if os.path.ismount(DATA_DIR) else "container_filesystem",
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
        {"id": "coinm", "primary": "Binance COIN-M Futures REST", "fallbacks": [],
         "status": "single_source", "note": "DAPI public exchangeInfo, 24h ticker and OHLCV; USD-quoted perpetual contracts only."},
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
         "status": "provider_required", "note": "No verified no-key 15m futures/options source integrated."},
        {"id": "gamma_local", "primary": "تحليل سيولة محلي من OHLCV", "fallbacks": [],
         "status": "local_no_key",
         "note": "تحليل السعر والحجم وسحب السيولة والامتصاص من بيانات الشموع العامة؛ لا يدّعي قياس خيارات GEX."}
    ]})



@app.get("/api/overview")
@require_paid_access
def home_overview():

    """Small cached cross-market snapshot; never invents unavailable market coverage."""
    names = {item["id"]: item["name"] for item in MARKETS}
    kinds = ["spot", "futures", "coinm", "alpha", "forex"]
    if YAHOO_ENABLED and yf is not None:
        kinds.extend(kind for kind in ("us", "saudi") if YAHOO_SYMBOLS.get(kind))

    def fetch_universe(kind):
        rows = rank_market_assets(cached(kind + ":universe", 20, lambda: market_tickers(kind)))
        up = sum(1 for row in rows if row["change24h"] > 0)
        down = sum(1 for row in rows if row["change24h"] < 0)
        flat = len(rows) - up - down
        direction = "BUY" if up > down else ("SELL" if down > up else "NEUTRAL")
        return kind, rows, {"up": up, "down": down, "flat": flat, "direction": direction}

    def build():
        universes = {}
        breadth = {}
        errors = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(fetch_universe, kind): kind for kind in kinds}
            for job in as_completed(jobs):
                kind = jobs[job]
                try:
                    _, rows, counts = job.result()
                    universes[kind] = rows
                    breadth[kind] = counts
                except Exception as exc:
                    errors[kind] = str(exc)[:180]
                    app.logger.warning("Home overview unavailable for %s: %s", kind, exc)

        market_rows = []
        for item in MARKETS:
            kind = item["id"]
            rows = universes.get(kind, [])
            if kind in universes:
                status = "watchlist" if kind in ("us", "saudi") else "live"
            elif kind in ("saudi", "us") and kind not in kinds:
                status = "provider_required"
            elif kind == "contracts":
                status = "provider_required"
            else:
                status = "unavailable"
            market_rows.append({
                "id": kind, "name": names.get(kind, kind), "status": status,
                "eligible_assets": len(rows), "error": errors.get(kind),
                "up": breadth.get(kind, {}).get("up"),
                "down": breadth.get(kind, {}).get("down"),
                "flat": breadth.get(kind, {}).get("flat"),
                "direction": breadth.get(kind, {}).get("direction"),
            })

        movers = []
        for kind, rows in universes.items():
            for row in rows[:5]:
                movers.append({
                    "market": kind, "market_name": names.get(kind, kind),
                    "symbol": row["symbol"], "price": row["price"],
                    "change24h": row["change24h"], "volume": row.get("volume", 0),
                    "fast_mover_score": row.get("fast_mover_score", 0),
                })
        movers.sort(key=lambda row: (
            row["fast_mover_score"], abs(row["change24h"]), row["volume"]
        ), reverse=True)
        return {
            "ok": True, "markets": market_rows,
            "eligible_assets": sum(len(rows) for rows in universes.values()),
            "available_markets": len(universes),
            "fast_movers": movers[:8], "updated": int(time.time()),
            "fast_mover_method": "ترتيب نسبي للزخم اليومي ونطاق الحركة والسيولة المتاحة؛ ليس توصية تداول.",
        }

    try:
        payload = cached("home:overview", 30, build)
        return jsonify(payload)
    except Exception:
        app.logger.exception("Home overview failed")
        return jsonify({"ok": False, "error": "تعذر تحديث ملخص الأسواق حاليًا."}), 502


@app.get("/api/market/<kind>")
@require_paid_access
def market(kind):
    section=request.args.get("section") or kind
    if section in SECTION_NAMES and current_user()["role"]!="admin" and not section_enabled(section):
        return jsonify({"ok":False,"error":"section_locked","message":"هذا القسم مغلق من الإدارة."}),403

    if kind not in BASES and kind not in ("alpha", "forex", "saudi", "us"):
        return jsonify({"ok": False, "status": "provider_required", "message": "مزود البيانات لهذا السوق غير مربوط؛ لن نعرض بيانات غير موثوقة.", "signals": []}), 503
    if kind in ("saudi", "us") and (not YAHOO_ENABLED or yf is None or not YAHOO_SYMBOLS.get(kind)):
        return jsonify({"ok": False, "status": "provider_required", "message": "Yahoo غير مفعّل أو قائمة الرموز غير مضبوطة؛ لم نعرض بيانات غير مكتملة.", "signals": []}), 503
    timeframe=request.args.get("timeframe","15m").strip()
    if timeframe not in ("15m","1h","4h","1d","1w","1M"):
        return jsonify({"ok":False,"error":"فريم التحليل غير مدعوم"}),400
    try:
        assets = cached(kind + ":universe", 20, lambda: market_tickers(kind))
        assets = rank_market_assets(assets)
        up = sum(1 for row in assets if row["change24h"] > 0)
        down = sum(1 for row in assets if row["change24h"] < 0)
        flat = len(assets) - up - down
        direction = "BUY" if up > down else ("SELL" if down > up else "NEUTRAL")
        source_label = ("Yahoo Finance (private/internal test watchlist)" if kind in ("saudi", "us") else "Binance Alpha public market data" if kind == "alpha" else "BiQuote public FX/Metals feed" if kind == "forex" else "Binance public market data")
        snapshot_updated = save_market_snapshot(kind, direction, up, down, flat, len(assets), source_label)
        # Show highest-priority fast movers first, regardless of direction.
        movers = [row for row in assets if row["change24h"] != 0][:6]
        fast_movers = assets[:10]
        prices = {row["symbol"]: row["price"] for row in assets}
        update_open_trades(kind, prices)
        # Scan a bounded rotating batch so large universes are covered over successive refreshes.
        with SCAN_CURSOR_LOCK:
            scan_offset = SCAN_CURSORS.get(kind, 0)
            candidates, next_scan_offset, scan_offset, priority_candidates = select_priority_scan_batch(assets, scan_offset, 12, 6)
            SCAN_CURSORS[kind] = next_scan_offset
        signals = []
        diagnostic_rows = [{} for _ in candidates]
        # Signal eligibility is determined by the selected asset's two reference
        # timeframes, not by aggregate 24h market breadth. A neutral market-wide
        # count must not suppress individually aligned setups.
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {
                pool.submit(analyse_candidate, kind, row, direction, diagnostic_rows[index], timeframe): index
                for index, row in enumerate(candidates)
            }
            for job in as_completed(jobs):
                try:
                    signal = job.result()
                except Exception:
                    # One malformed provider response or adapter failure must not
                    # cancel the scan for every other candidate in this market.
                    index = jobs[job]
                    diagnostic_rows[index]["reason"] = "analysis_error"
                    app.logger.exception("Candidate analysis failed: %s %s", kind, candidates[index].get("symbol"))
                    continue
                if signal:
                    signals.append(signal)
        rejection_counts = {}
        for item in diagnostic_rows:
            reason = item.get("reason", "unknown")
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        for row in signals:
            row["ranking_score"] = round(
                row["quality_score"] * 0.65 + float(row.get("fast_mover_score", 0) or 0) * 0.35, 1
            )
        signals.sort(key=lambda row: (
            row.get("change_timeframe", 0) if row.get("side") == "BUY" else -row.get("change_timeframe", 0),
            row["quality_score"], row["ranking_score"],
        ), reverse=True)
        # Only show opportunities that were actually saved. Repeated scans of
        # the same symbol/timeframe stay in the position tracker, not as fresh cards.
        signals = save_new_trades(kind, signals)
        with db() as connection:
            active = [dict(row) for row in connection.execute(
                """SELECT * FROM trades
                   WHERE market=? AND timeframe=? AND status='OPEN'
                   ORDER BY created_at DESC LIMIT 100""",
                (kind, timeframe)
            ).fetchall()]
        # Never show an opposite-side open trade as a current opportunity
        # when the latest market breadth has flipped direction.
        active = [trade for trade in active if trade.get("side") == direction]
        for trade in active:
            trade["current_price"] = prices.get(trade["symbol"])
            trade["live_pnl_percent"] = (
                round(((trade["current_price"] / trade["entry"] - 1) * (1 if trade["side"] == "BUY" else -1)) * 100, 2)
                if trade["current_price"] is not None and trade["entry"] else None
            )

        # Keep confirmed opportunities visible across refreshes. A signal is
        # inserted only once per completed candle; returning only newly inserted
        # rows made its card disappear on the next refresh even while OPEN.
        display_by_key = {
            (row["symbol"], row["timeframe"]): dict(row)
            for row in signals
        }
        ticker_by_symbol = {row["symbol"]: row for row in assets}
        for trade in active:
            if trade["timeframe"] != timeframe:
                continue
            key = (trade["symbol"], trade["timeframe"])
            if key in display_by_key:
                continue
            quote = ticker_by_symbol.get(trade["symbol"], {})
            entry = float(trade["entry"] or 0)
            stop = float(trade["stop_loss"] or 0)
            display_by_key[key] = {
                **trade,
                "price": trade.get("current_price"),
                "risk_percent": round(abs(entry - stop) / entry * 100, 3) if entry > 0 else None,
                "quality_score": None,
                "signal_state_ar": "صفقة مؤكدة محفوظة ومفتوحة",
                "fast_mover_score": quote.get("fast_mover_score", 0),
                "change24h": quote.get("change24h", 0),
                "change_timeframe": 0,
                "institutional_flow": {"status": "unavailable"},
                "persisted": True,
            }
        signals = list(display_by_key.values())[:3]
        return jsonify({
            "ok": True, "market": kind, "direction": direction, "direction_ar": {"BUY": "صاعد", "SELL": "هابط", "NEUTRAL": "محايد"}[direction],
            "up": up, "down": down, "flat": flat, "total": len(assets), "timeframe": timeframe,
            "movers": movers, "fast_movers": fast_movers,
            "fast_mover_method": "50% زخم 24س + 30% نطاق الحركة + 20% السيولة النسبية؛ أوزان الحقول المتاحة فقط",
            "signals": signals, "open_trades": active,
            "scan_diagnostics": {
                "universe_size": len(assets), "candidates_scanned": len(candidates),
                "scan_offset": scan_offset, "next_scan_offset": next_scan_offset,
                "priority_candidates": priority_candidates,
                "scan_cycle_complete": bool(assets) and next_scan_offset <= scan_offset,
                "candles_ready": sum(1 for item in diagnostic_rows if item.get("candles_ready") is True),
                "candles_required": 35,
                "accepted_before_top3": rejection_counts.get("accepted", 0),
                "rejected_by_reason": {key: value for key, value in rejection_counts.items() if key != "accepted"},
            },
            "updated": snapshot_updated, "snapshot_stale": False,
            "source": source_label, "strategy": "4H + Daily confirmation · selected-timeframe entry",
            "gamma_status": "خيارات/GEX غير متاحة من مزود موثوق لكل الأسواق؛ لا يتم اختلاق قيم Gamma.",
            "analysis_mode": "سيولة سعرية وحجم شموع؛ ضغط تقديري وليس تدفق صفقات منفذة",
            "score_note": "اتجاه 4 ساعات واليومي من بنية OHLCV والزخم والحجم؛ الدخول من سحب السيولة أو الامتصاص وتأكيد الشمعة على الفريم المحدد. درجة الجودة من 100 وليست احتمال نجاح."
        })
    except requests.RequestException:
        app.logger.exception("Market provider request failed: %s", kind)
        try:
            snapshot = load_market_snapshot(kind)
            if snapshot:
                saved_signals, saved_open = load_saved_market_trades(kind, timeframe)
                # On provider outage, preserve only saved trades aligned with
                # the last persisted market direction.
                saved_signals = [trade for trade in saved_signals if trade.get("side") == snapshot["direction"]]
                saved_open = [trade for trade in saved_open if trade.get("side") == snapshot["direction"]]
                return jsonify({
                    "ok": True, "market": kind, "direction": snapshot["direction"],
                    "direction_ar": {"BUY": "صاعد", "SELL": "هابط", "NEUTRAL": "محايد"}[snapshot["direction"]],
                    "up": snapshot["up"], "down": snapshot["down"], "flat": snapshot["flat"],
                    "total": snapshot["total"], "timeframe": timeframe,
                    "signals": saved_signals, "open_trades": saved_open,
                    "movers": [], "fast_movers": [],
                    "scan_diagnostics": {"universe_size": snapshot["total"], "candidates_scanned": 0, "rejected_by_reason": {}},
                    "updated": snapshot["updated_at"], "snapshot_stale": True,
                    "source": snapshot["source"], "strategy": "4H + Daily confirmation · selected-timeframe entry",
                    "message": "تعذر تحديث المصدر؛ نعرض آخر اتجاه وصفقات محفوظة دون اختلاق بيانات جديدة."
                })
        except sqlite3.Error:
            app.logger.exception("Could not load persisted market snapshot: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الاتصال بمصدر السوق الآن؛ لم نستخدم بيانات قديمة أو وهمية.", "market": kind}), 502
    except sqlite3.Error:
        app.logger.exception("Trade database failure: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الوصول إلى سجل الصفقات. تحقق من وحدة التخزين الدائمة.", "market": kind}), 503

@app.get("/api/analysis/method")
@app.get("/api/gamma/crypto")
def crypto_gamma():
    """No-key local OHLCV analysis method; the legacy route remains compatible."""
    return jsonify({
        "status": "local_analysis",
        "mode": "ohlcv_liquidity_proxy",
        "provider": "بيانات OHLCV العامة ومحرك التحليل الداخلي",
        "message": "يعمل بدون أي مفاتيح API عبر تحليل السعر والحجم وسحب السيولة والامتصاص. لا يدّعي توفير Gamma Exposure أو بيانات خيارات.",
        "symbols": [],
        "items": [],
        "metrics": ["volume_ratio", "price_pressure", "liquidity_sweeps", "absorption"],
    })

@app.get("/api/trades")
@require_paid_access
def trades():
    if current_user()["role"]!="admin" and not section_enabled("history"):
        return jsonify({"ok":False,"error":"section_locked","message":"سجل الصفقات مغلق من الإدارة."}),403
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
