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
from gammaflip_client import fetch_supported_crypto
from market_ranking import rank_market_assets
from institutional_flow import analyse_orderbook_flow

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
GAMMAFLIP_API_KEY = os.environ.get("GAMMAFLIP_API_KEY", "").strip()
GAMMAFLIP_DAILY_BUDGET = max(5, int(os.environ.get("GAMMAFLIP_DAILY_BUDGET", "40")))
GAMMAFLIP_CACHE_SECONDS = 900
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
            if kind == "us" and volume < 1_000_000:
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
    fetch_interval = "60m" if interval == "4h" else interval
    period = "1y" if interval == "1d" else "3mo" if interval in ("1h", "4h") else "5d"
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

def binance_active_symbols(kind):
    """Return currently tradable USDT symbols from Binance exchange metadata."""
    path = "/api/v3/exchangeInfo" if kind == "spot" else ("/dapi/v1/exchangeInfo" if kind == "coinm" else "/fapi/v1/exchangeInfo")
    urls = [host + path for host in SPOT_BASES] if kind == "spot" else [BASES[kind] + path]
    payload = cached(kind + ":exchange-info", 300, lambda: fetch_first_json(urls))
    symbols = set()
    for row in payload.get("symbols", []):
        expected_quote = "USD" if kind == "coinm" else "USDT"
        if row.get("status") != "TRADING" or row.get("quoteAsset") != expected_quote:
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

def analyse_candidate(kind, item, market_direction, diagnostics=None):
    """GAMMA PRO: liquidity sweep/absorption analysis; no indicator-based entries."""
    def reject(reason):
        if diagnostics is not None:
            diagnostics["reason"] = reason
        return None
    try:
        selected = candles(kind, item["symbol"], SCAN_INTERVAL)
        if len(selected) < 25:
            return reject("insufficient_candles")
        if diagnostics is not None:
            diagnostics["candles_ready"] = True
        if market_direction not in ("BUY", "SELL"):
            return reject("neutral_market")
        try:
            signal = analyse_liquidity_candidate(
                selected, item["price"], market_direction, market_kind=kind, diagnostics=diagnostics
            )
        except TypeError:
            # Backward-compatible with test doubles/older adapters that do not accept diagnostics.
            signal = analyse_liquidity_candidate(selected, item["price"], market_direction, market_kind=kind)
            if diagnostics is not None:
                diagnostics["reason"] = "accepted" if signal else "analysis_adapter_legacy"
        if not signal:
            return None

        # HAWK QUANT PRO: confirm the 15m liquidity event against independent
        # 1h/4h/1d price structure. Higher-timeframe data is fetched only for
        # candidates that already passed the 15m setup, keeping provider load bounded.
        from hawk_quant_engine import assess_timeframe_alignment
        higher_timeframes = {}
        for interval in ("1h", "4h", "1d"):
            history = candles(kind, item["symbol"], interval)
            higher_timeframes[interval] = history
        alignment = assess_timeframe_alignment(higher_timeframes, market_direction)
        if not alignment["confirmed"]:
            return reject("timeframe_conflict")
        # Add a live order-book snapshot where the exchange exposes it.
        # The snapshot is contextual evidence, not proof of hidden institutional orders.
        flow = analyse_orderbook_flow(
            kind, item["symbol"], market_direction,
            lambda url, params: cached(
                f"orderbook:{kind}:{item['symbol']}", 5,
                lambda: fetch_json(url, params)
            )
        )
        signal["institutional_flow"] = flow
        if flow.get("status") == "supportive":
            signal["quality_score"] = min(100, float(signal.get("quality_score", 0)) + 3)
        elif flow.get("status") == "opposing":
            signal["quality_score"] = max(0, float(signal.get("quality_score", 0)) - 3)

        signal.update({
            "symbol": item["symbol"],
            "price": item["price"],
            "change24h": item["change24h"],
            "volume": item["volume"],
            "fast_mover_score": item.get("fast_mover_score", 0),
            "fast_mover_rank": item.get("fast_mover_rank"),
            "timeframe": SCAN_INTERVAL,
            "strategy": "HAWK QUANT PRO",
            "timeframe_alignment": alignment["states"],
            "timeframe_score": alignment["score"],
            "quality_score": round(min(100, float(signal.get("quality_score", 0)) + alignment["bonus"]), 1),
        })
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
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
            subscription_expires_at INTEGER, created_at INTEGER NOT NULL
        )""")
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


def auth_setup_ready():
    return AUTH_CONFIGURED


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


@app.get("/api/auth/me")
def auth_me():
    if not auth_setup_ready():
        return jsonify({"ok": False, "configured": False, "message": "يلزم إعداد بيانات الأدمن ومفتاح الجلسة على الخادم."}), 503
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
            # Keep active trade tracking bounded: expire setups after 24 hours.
            if now - int(trade["created_at"]) >= 24 * 60 * 60:
                connection.execute(
                    "UPDATE trades SET status='EXPIRED',updated_at=?,closed_at=? WHERE id=?",
                    (now, now, trade["id"])
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
def latest_news():
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
        {"id": "gammaflip", "primary": "GammaFlip crypto options GEX API", "fallbacks": [],
         "status": "configured" if GAMMAFLIP_API_KEY else "secret_required",
         "note": "Read-only combined options GEX for BTC, ETH, SOL, XRP and HYPE; manual refresh only, 15-minute cache."}
    ]})


@app.get("/api/system/status")
def system_status():
    """Lightweight diagnostics: local DB/cache state and declared provider configuration."""
    database = "ok"
    total_trades = open_trades = closed_trades = 0
    latest_trade_update = None
    try:
        with db() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS opened,
                          SUM(CASE WHEN status!='OPEN' THEN 1 ELSE 0 END) AS closed,
                          MAX(updated_at) AS latest_update
                   FROM trades"""
            ).fetchone()
            total_trades = int(row["total"] or 0)
            open_trades = int(row["opened"] or 0)
            closed_trades = int(row["closed"] or 0)
            latest_trade_update = row["latest_update"]
    except sqlite3.Error:
        database = "error"

    with CACHE_LOCK:
        cache_entries = len(CACHE)
        cache_last_update = max((item[0] for item in CACHE.values()), default=None)

    provider_rows = providers().get_json().get("markets", [])
    market_rows = markets().get_json().get("markets", [])
    provider_by_id = {item["id"]: item for item in provider_rows}
    result_markets = []
    for item in market_rows:
        provider = provider_by_id.get(item["id"], {})
        status = provider.get("status", item.get("status", "unknown"))
        result_markets.append({
            "id": item["id"], "name": item["name"],
            "provider": provider.get("primary") or item.get("provider") or "غير مربوط",
            "status": status,
            "note": provider.get("note", ""),
            "fallbacks": len(provider.get("fallbacks") or []),
        })

    result_markets.append({
        "id": "gammaflip", "name": "Gamma Exposure للعملات الرقمية",
        "provider": "GammaFlip Options GEX API",
        "status": "configured" if GAMMAFLIP_API_KEY else "secret_required",
        "note": "بيانات خيارات حقيقية لـ BTC وETH وSOL وXRP وHYPE عند ضبط المفتاح.",
        "fallbacks": 0,
    })

    return jsonify({
        "ok": database == "ok",
        "timestamp": int(time.time()),
        "database": database,
        "cache_entries": cache_entries,
        "cache_last_update": cache_last_update,
        "trades": {
            "total": total_trades, "open": open_trades, "closed": closed_trades,
            "latest_update": latest_trade_update,
        },
        "gamma": {"configured": bool(GAMMAFLIP_API_KEY),
                  "symbols": ["BTC", "ETH", "SOL", "XRP", "HYPE"]},
        "markets": result_markets,
        "diagnostics_scope": "configuration_and_local_health_only",
    }), (200 if database == "ok" else 503)


@app.get("/api/market/<kind>")
def market(kind):
    if kind not in BASES and kind not in ("alpha", "forex", "saudi", "us"):
        return jsonify({"ok": False, "status": "provider_required", "message": "مزود البيانات لهذا السوق غير مربوط؛ لن نعرض بيانات غير موثوقة.", "signals": []}), 503
    if kind in ("saudi", "us") and (not YAHOO_ENABLED or yf is None or not YAHOO_SYMBOLS.get(kind)):
        return jsonify({"ok": False, "status": "provider_required", "message": "Yahoo غير مفعّل أو قائمة الرموز غير مضبوطة؛ لم نعرض بيانات غير مكتملة.", "signals": []}), 503
    try:
        assets = cached(kind + ":universe", 20, lambda: market_tickers(kind))
        assets = rank_market_assets(assets)
        up = sum(1 for row in assets if row["change24h"] > 0)
        down = sum(1 for row in assets if row["change24h"] < 0)
        flat = len(assets) - up - down
        direction = "BUY" if up > down else ("SELL" if down > up else "NEUTRAL")
        # Show highest-priority fast movers first, regardless of direction.
        movers = [row for row in assets if row["change24h"] != 0][:6]
        fast_movers = assets[:10]
        prices = {row["symbol"]: row["price"] for row in assets}
        update_open_trades(kind, prices)
        # Scan a wider, still bounded batch of the fastest/highest-volume assets.
        candidates = assets[:40]
        signals = []
        diagnostic_rows = [{} for _ in candidates]
        if direction != "NEUTRAL":
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = {
                    pool.submit(analyse_candidate, kind, row, direction, diagnostic_rows[index]): index
                    for index, row in enumerate(candidates)
                }
                for job in as_completed(jobs):
                    signal = job.result()
                    if signal:
                        signals.append(signal)
        else:
            for item in diagnostic_rows:
                item["reason"] = "neutral_market"
        rejection_counts = {}
        for item in diagnostic_rows:
            reason = item.get("reason", "unknown")
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        signals.sort(key=lambda row: (
            row.get("fast_mover_score", 0), row["quality_score"], abs(row["change24h"])
        ), reverse=True)
        signals = signals[:3]
        save_new_trades(kind, signals)
        with db() as connection:
            active = [dict(row) for row in connection.execute(
                "SELECT * FROM trades WHERE market=? AND status='OPEN' ORDER BY created_at DESC LIMIT 100", (kind,)
            ).fetchall()]
        return jsonify({
            "ok": True, "market": kind, "direction": direction, "direction_ar": {"BUY": "صاعد", "SELL": "هابط", "NEUTRAL": "محايد"}[direction],
            "up": up, "down": down, "flat": flat, "total": len(assets), "timeframe": SCAN_INTERVAL,
            "movers": movers, "fast_movers": fast_movers,
            "fast_mover_method": "50% زخم 24س + 30% نطاق الحركة + 20% السيولة النسبية؛ أوزان الحقول المتاحة فقط",
            "signals": signals, "open_trades": active,
            "scan_diagnostics": {
                "universe_size": len(assets), "candidates_scanned": len(candidates),
                "candles_ready": sum(1 for item in diagnostic_rows if item.get("candles_ready") is True),
                "accepted_before_top3": rejection_counts.get("accepted", 0),
                "rejected_by_reason": {key: value for key, value in rejection_counts.items() if key != "accepted"},
            },
            "updated": int(time.time()),
            "source": ("Yahoo Finance (private/internal test watchlist)" if kind in ("saudi", "us") else "Binance Alpha public market data" if kind == "alpha" else "BiQuote public FX/Metals feed" if kind == "forex" else "Binance public market data"), "strategy": "HAWK QUANT PRO · Multi-timeframe Structure + Liquidity Sweep + Absorption",
            "gamma_status": "خيارات/GEX غير متاحة من مزود موثوق لكل الأسواق؛ لا يتم اختلاق قيم Gamma.",
            "analysis_mode": "سيولة سعرية وحجم شموع؛ ضغط تقديري وليس تدفق صفقات منفذة",
            "score_note": "درجة جودة الشروط وليست نسبة نجاح أو احتمال ربح. يلزم توافق 1h و4h واليومي قبل اعتماد الفرصة."
        })
    except requests.RequestException:
        app.logger.exception("Market provider request failed: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الاتصال بمصدر السوق الآن؛ لم نستخدم بيانات قديمة أو وهمية.", "market": kind}), 502
    except sqlite3.Error:
        app.logger.exception("Trade database failure: %s", kind)
        return jsonify({"ok": False, "error": "تعذر الوصول إلى سجل الصفقات. تحقق من وحدة التخزين الدائمة.", "market": kind}), 503

@app.get("/api/gamma/crypto")
def crypto_gamma():
    """On-demand combined options GEX for the five coins with verified options coverage."""
    if not GAMMAFLIP_API_KEY:
        return jsonify({
            "status": "not_configured",
            "message": "مصدر Gamma الحقيقي غير مربوط. أضف GAMMAFLIP_API_KEY في أسرار Northflank.",
            "symbols": ["BTC", "ETH", "SOL", "XRP", "HYPE"],
            "items": [],
        })
    try:
        result = cached(
            "gammaflip:crypto:all",
            GAMMAFLIP_CACHE_SECONDS,
            lambda: fetch_supported_crypto(GAMMAFLIP_API_KEY, budget=GAMMAFLIP_DAILY_BUDGET),
        )
        result["symbols"] = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
        return jsonify(result)
    except (requests.RequestException, ValueError, TypeError):
        app.logger.exception("GammaFlip crypto GEX request failed")
        return jsonify({"status": "unavailable", "message": "تعذر جلب بيانات Gamma؛ استمر تحليل السيولة دون قيم مختلقة.", "items": []}), 502


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
