import os
import time
import json
import re
import html
import hashlib
import hmac
import secrets
import threading
import csv
import io

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests
import psycopg

from flask import Flask, jsonify, render_template, request, session


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "change-this-secret-key"
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# =========================================================
# ENV
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
)

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    ""
)

PAYMENT_ADDRESS = os.getenv(
    "TRC20_ADDRESS",
    "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"
)


# =========================================================
# PLANS
# =========================================================

PLANS = {
    "7d": {
        "name": "7 أيام",
        "days": 7,
        "amount": 10.0
    },
    "15d": {
        "name": "15 يوم",
        "days": 15,
        "amount": 20.0
    },
    "30d": {
        "name": "30 يوم",
        "days": 30,
        "amount": 30.0
    },
}


# =========================================================
# MARKET SOURCES
# =========================================================

# Crypto = Bybit Spot مباشرة
BYBIT_BASE = os.getenv(
    "BYBIT_BASE",
    "https://api.bybit.com"
).rstrip("/")


# US = Yahoo Finance
YAHOO_BASE = os.getenv(
    "YAHOO_BASE",
    "https://query1.finance.yahoo.com"
).rstrip("/")


NASDAQ_LISTED = (
    "https://www.nasdaqtrader.com/"
    "dynamic/SymDir/nasdaqlisted.txt"
)

OTHER_LISTED = (
    "https://www.nasdaqtrader.com/"
    "dynamic/SymDir/otherlisted.txt"
)


# Saudi
SAUDI_EXCHANGE_HOME = (
    "https://www.saudiexchange.sa/"
)


# =========================================================
# HTTP
# =========================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "Chrome/151.0.0.0 "
        "Mobile Safari/537.36 "
        "Mudarib-Abo-Saud/4.0"
    ),
    "Accept": "application/json,text/plain,*/*",
})


# =========================================================
# CACHE
# =========================================================

MARKET_CACHE = {
    "ts": 0,
    "symbols": []
}

US_CACHE = {
    "ts": 0,
    "symbols": []
}

SAUDI_CACHE = {
    "ts": 0,
    "symbols": []
}

SCAN_CACHE = {}

NEWS_CACHE = {
    "ts": 0,
    "items": []
}

CACHE_LOCK = threading.Lock()


# =========================================================
# CONSTANTS
# =========================================================

STABLE_BASES = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "USDE",
    "DAI",
    "USDP",
    "USDD",
    "USD",
}

INTERVALS = {
    "5m",
    "15m",
    "1h",
    "4h",
    "1d"
}


# =========================================================
# GENERAL
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def json_error(message, status=400):
    return jsonify({
        "ok": False,
        "error": str(message)
    }), status


def safe_json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()

    return value


# =========================================================
# DATABASE
# =========================================================

def db_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured"
        )

    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():
    if not DATABASE_URL:
        print("DB init skipped: DATABASE_URL not configured")
        return

    with db_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),
                    plan TEXT,
                    plan_start TIMESTAMPTZ,
                    plan_end TIMESTAMPTZ,
                    is_active BOOLEAN NOT NULL
                        DEFAULT TRUE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    plan TEXT NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    txid TEXT,
                    status TEXT NOT NULL
                        DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY
                        REFERENCES users(id)
                        ON DELETE CASCADE,
                    settings JSONB NOT NULL
                        DEFAULT '{}'::jsonb
                )
            """)

        conn.commit()


# =========================================================
# PASSWORD
# =========================================================

def hash_password(password):
    salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        180000
    )

    return (
        salt.hex()
        + "$"
        + digest.hex()
    )


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(
            "$",
            1
        )

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            180000
        )

        return hmac.compare_digest(
            digest.hex(),
            digest_hex
        )

    except Exception:
        return False


# =========================================================
# USERS
# =========================================================

def user_row(user_id=None, username=None):

    if not DATABASE_URL:
        return None

    with db_conn() as conn:
        with conn.cursor() as cur:

            if user_id is not None:

                cur.execute(
                    """
                    SELECT
                        id,
                        username,
                        password_hash,
                        created_at,
                        plan,
                        plan_start,
                        plan_end,
                        is_active
                    FROM users
                    WHERE id=%s
                    """,
                    (user_id,)
                )

            else:

                cur.execute(
                    """
                    SELECT
                        id,
                        username,
                        password_hash,
                        created_at,
                        plan,
                        plan_start,
                        plan_end,
                        is_active
                    FROM users
                    WHERE username=%s
                    """,
                    (username,)
                )

            return cur.fetchone()


def user_json(row):

    if not row:
        return None

    return {
        "id": row[0],
        "username": row[1],
        "created_at": (
            row[3].isoformat()
            if row[3]
            else None
        ),
        "plan": row[4],
        "plan_start": (
            row[5].isoformat()
            if row[5]
            else None
        ),
        "plan_end": (
            row[6].isoformat()
            if row[6]
            else None
        ),
        "is_active": bool(row[7])
    }


def current_user():

    uid = session.get("user_id")

    if not uid:
        return None

    return user_row(user_id=uid)


def is_admin():
    return bool(
        session.get("admin")
    )


def admin_required():
    return is_admin()


def subscription_active(row=None):

    row = row or current_user()

    if not row:
        return False

    if not row[7]:
        return False

    if not row[6]:
        return False

    return row[6] > now_utc()


# =========================================================
# GENERIC HTTP
# =========================================================

def http_json(
    url,
    params=None,
    timeout=15
):

    response = HTTP.get(
        url,
        params=params or {},
        timeout=timeout
    )

    response.raise_for_status()

    return response.json()


def http_text(
    url,
    timeout=20
):

    response = HTTP.get(
        url,
        timeout=timeout
    )

    response.raise_for_status()

    return response.text


# =========================================================
# BYBIT DIRECT
# =========================================================

def bybit_get(
    path,
    params=None,
    timeout=20
):
    """
    اتصال مباشر مع Bybit Public API.
    لا يحتاج API Key.
    """

    base = (
        os.getenv(
            "BYBIT_BASE",
            "https://api.bybit.com"
        )
        .strip()
        .rstrip("/")
    )

    if not base:
        base = "https://api.bybit.com"

    url = base + path

    last_error = None

    try:

        response = HTTP.get(
            url,
            params=params or {},
            timeout=timeout
        )

        response.raise_for_status()

        data = response.json()

        ret_code = data.get(
            "retCode"
        )

        if ret_code != 0:

            raise RuntimeError(
                data.get(
                    "retMsg",
                    "Bybit API error"
                )
            )

        return data.get(
            "result",
            {}
        )

    except requests.RequestException as e:

        last_error = (
            "Bybit connection error: "
            + str(e)
        )

    except ValueError as e:

        last_error = (
            "Bybit returned invalid JSON: "
            + str(e)
        )

    except Exception as e:

        last_error = str(e)

    raise RuntimeError(
        last_error or
        "تعذر الاتصال بـ Bybit"
    )


# =========================================================
# BYBIT SYMBOLS
# =========================================================

def bybit_symbols():

    with CACHE_LOCK:

        if (
            MARKET_CACHE["symbols"]
            and
            time.time()
            - MARKET_CACHE["ts"]
            < 1800
        ):
            return MARKET_CACHE["symbols"]

    result = bybit_get(
        "/v5/market/instruments-info",
        {
            "category": "spot",
            "limit": 1000
        }
    )

    rows = []

    for item in result.get(
        "list",
        []
    ):

        try:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            base = str(
                item.get(
                    "baseCoin",
                    ""
                )
            ).upper()

            quote = str(
                item.get(
                    "quoteCoin",
                    ""
                )
            ).upper()

            status = item.get(
                "status"
            )

            if status != "Trading":
                continue

            if quote != "USDT":
                continue

            if base in STABLE_BASES:
                continue

            if not symbol.endswith(
                "USDT"
            ):
                continue

            rows.append({
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "source": "Bybit Spot"
            })

        except Exception:
            continue

    rows.sort(
        key=lambda x: x["symbol"]
    )

    with CACHE_LOCK:

        MARKET_CACHE.update({
            "ts": time.time(),
            "symbols": rows
        })

    return rows


# =========================================================
# BYBIT TICKERS
# =========================================================

def bybit_tickers():

    result = bybit_get(
        "/v5/market/tickers",
        {
            "category": "spot"
        }
    )

    return result.get(
        "list",
        []
    )


# =========================================================
# BYBIT KLINES
# =========================================================

def bybit_kline(
    symbol,
    interval="15m",
    limit=230
):

    interval_map = {
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D"
    }

    iv = interval_map.get(
        interval
    )

    if not iv:
        raise ValueError(
            "الفاصل غير مدعوم"
        )

    try:
        limit = int(limit)
    except Exception:
        limit = 230

    limit = max(
        10,
        min(
            limit,
            1000
        )
    )

    result = bybit_get(
        "/v5/market/kline",
        {
            "category": "spot",
            "symbol": str(
                symbol
            ).upper(),
            "interval": iv,
            "limit": limit
        }
    )

    rows = result.get(
        "list",
        []
    )

    # Bybit:
    # [startTime, open, high, low, close, volume, turnover]

    normalized = []

    for row in reversed(rows):

        try:

            normalized.append([
                int(float(row[0])),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5])
            ])

        except Exception:
            continue

    return normalize_candles(
        normalized
    )


# =========================================================
# BYBIT PRICE
# =========================================================

def bybit_price(symbol):

    symbol = str(
        symbol or "BTCUSDT"
    ).upper()

    result = bybit_get(
        "/v5/market/tickers",
        {
            "category": "spot",
            "symbol": symbol
        }
    )

    rows = result.get(
        "list",
        []
    )

    if not rows:
        raise ValueError(
            "العملة غير موجودة في Bybit Spot"
        )

    item = rows[0]

    return {
        "symbol": symbol,
        "price": float(
            item.get(
                "lastPrice",
                0
            )
        ),
        "change24h": float(
            item.get(
                "price24hPcnt",
                0
            ) or 0
        ) * 100,
        "volume24h": float(
            item.get(
                "turnover24h",
                0
            ) or 0
        ),
        "source": "Bybit Spot"
    }


# =========================================================
# INDICATORS
# =========================================================

def ema(
    values,
    period
):

    if len(values) < period:
        return None

    k = 2 / (
        period + 1
    )

    e = sum(
        values[:period]
    ) / period

    for value in values[period:]:

        e = (
            value * k
            +
            e * (1 - k)
        )

    return e


def rsi(
    values,
    period=14
):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            -
            values[i - 1]
        )

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def atr(
    candles,
    period=14
):

    if len(candles) <= period:
        return None

    trs = []

    for i in range(
        1,
        len(candles)
    ):

        high = float(
            candles[i][2]
        )

        low = float(
            candles[i][3]
        )

        previous_close = float(
            candles[i - 1][4]
        )

        true_range = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            )
        )

        trs.append(
            true_range
        )

    return (
        sum(
            trs[-period:]
        )
        / period
    )


def macd_hist(
    values,
    fast=12,
    slow=26,
    signal=9
):

    if len(values) < (
        slow + signal
    ):
        return None

    line = []

    for i in range(
        slow - 1,
        len(values)
    ):

        fast_ema = ema(
            values[:i + 1],
            fast
        )

        slow_ema = ema(
            values[:i + 1],
            slow
        )

        if (
            fast_ema is not None
            and
            slow_ema is not None
        ):

            line.append(
                fast_ema
                -
                slow_ema
            )

    if len(line) < signal:
        return None

    sig = ema(
        line,
        signal
    )

    if sig is None:
        return None

    return (
        line[-1]
        -
        sig
    )


# =========================================================
# CANDLE NORMALIZATION
# =========================================================

def normalize_candles(
    candles
):

    output = []

    for candle in candles or []:

        try:

            if isinstance(
                candle,
                dict
            ):

                timestamp = int(
                    candle["timestamp"]
                )

                opening = float(
                    candle["open"]
                )

                high = float(
                    candle["high"]
                )

                low = float(
                    candle["low"]
                )

                close = float(
                    candle["close"]
                )

                volume = float(
                    candle["volume"]
                )

            else:

                timestamp = int(
                    float(
                        candle[0]
                    )
                )

                opening = float(
                    candle[1]
                )

                high = float(
                    candle[2]
                )

                low = float(
                    candle[3]
                )

                close = float(
                    candle[4]
                )

                volume = float(
                    candle[5]
                )

            output.append([
                timestamp,
                opening,
                high,
                low,
                close,
                volume
            ])

        except Exception:
            continue

    return sorted(
        output,
        key=lambda x: x[0]
    )


# =========================================================
# ANALYSIS
# =========================================================

def analyze_klines(
    klines,
    symbol=None,
    market="crypto",
    interval="15m"
):

    candles = normalize_candles(
        klines
    )

    if len(candles) < 60:
        raise ValueError(
            "بيانات الشموع غير كافية للتحليل"
        )

    closes = [
        candle[4]
        for candle in candles
    ]

    price = closes[-1]

    e20 = ema(
        closes,
        20
    )

    e50 = ema(
        closes,
        50
    )

    e200 = ema(
        closes,
        200
    )

    rv = rsi(
        closes,
        14
    )

    ah = atr(
        candles,
        14
    )

    mh = macd_hist(
        closes
    )

    score = 50

    if e20 is not None:
        score += (
            8
            if price > e20
            else -8
        )

    if e50 is not None:
        score += (
            8
            if price > e50
            else -8
        )

    if e200 is not None:
        score += (
            10
            if price > e200
            else -10
        )

    if rv is not None:

        if 50 <= rv <= 70:
            score += 8

        elif rv > 70:
            score += 2

        elif rv < 30:
            score += 3

        else:
            score -= 5

    if mh is not None:

        score += (
            8
            if mh > 0
            else -8
        )

    score = max(
        0,
        min(
            100,
            round(
                score,
                2
            )
        )
    )

    if score >= 80:
        signal = "شراء قوي"

    elif score >= 65:
        signal = "شراء"

    elif score <= 20:
        signal = "بيع قوي"

    elif score <= 35:
        signal = "بيع"

    else:
        signal = "حيادي"

    risk = max(
        (
            ah
            if ah
            else price * 0.01
        ) * 1.5,
        price * 0.01
    )

    direction = (
        "BUY"
        if score >= 50
        else "SELL"
    )

    if direction == "BUY":

        sl = price - risk

        tp1 = (
            price
            +
            risk * 1.5
        )

        tp2 = (
            price
            +
            risk * 2
        )

        tp3 = (
            price
            +
            risk * 3
        )

    else:

        sl = price + risk

        tp1 = (
            price
            -
            risk * 1.5
        )

        tp2 = (
            price
            -
            risk * 2
        )

        tp3 = (
            price
            -
            risk * 3
        )

    recent = candles[-20:]

    lows = [
        candle[3]
        for candle in recent
    ]

    highs = [
        candle[2]
        for candle in recent
    ]

    return {
        "symbol": symbol,
        "market": market,
        "interval": interval,

        "signal": signal,
        "direction": direction,
        "score": score,

        "price": price,
        "entry": price,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "sl": sl,

        "support": min(lows),
        "resistance": max(highs),

        "ema20": e20,
        "ema50": e50,
        "ema200": e200,

        "rsi": rv,
        "atr": ah,
        "macd_hist": mh,

        "updated_at":
            now_utc().isoformat(),

        "candles":
            candles[-100:]
    }


# =========================================================
# BYBIT SPOT SCAN
# =========================================================

def scan_spot():

    cache_key = "crypto_scan"

    with CACHE_LOCK:

        cached = SCAN_CACHE.get(
            cache_key
        )

        if (
            cached
            and
            time.time()
            - cached["ts"]
            < 60
        ):

            return cached["data"]

    tickers = bybit_tickers()

    candidates = []

    for ticker in tickers:

        try:

            symbol = str(
                ticker.get(
                    "symbol",
                    ""
                )
            ).upper()

            if not symbol.endswith(
                "USDT"
            ):
                continue

            turnover = float(
                ticker.get(
                    "turnover24h",
                    0
                )
                or 0
            )

            if turnover < 1_000_000:
                continue

            candidates.append(
                ticker
            )

        except Exception:
            continue

    candidates.sort(
        key=lambda x: float(
            x.get(
                "turnover24h",
                0
            )
            or 0
        ),
        reverse=True
    )

    # عدد العملات المراد تحليلها
    scan_limit = int(
        os.getenv(
            "CRYPTO_SCAN_LIMIT",
            "120"
        )
    )

    candidates = candidates[
        :scan_limit
    ]

    def analyze_one(item):

        symbol = item.get(
            "symbol"
        )

        try:

            candles = bybit_kline(
                symbol,
                "15m",
                230
            )

            return analyze_klines(
                candles,
                symbol,
                "spot",
                "15m"
            )

        except Exception as e:

            print(
                "Bybit scan error",
                symbol,
                e
            )

            return None

    results = []

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                analyze_one,
                item
            )
            for item in candidates
        ]

        for future in as_completed(
            futures
        ):

            try:
                result = future.result()

                if result:
                    results.append(
                        result
                    )

            except Exception:
                continue

    results.sort(
        key=lambda x: (
            x["score"],
            x["symbol"]
        ),
        reverse=True
    )

    with CACHE_LOCK:

        SCAN_CACHE[
            cache_key
        ] = {
            "ts": time.time(),
            "data": results
        }

    return results


# =========================================================
# YAHOO
# =========================================================

def yahoo_symbol(symbol):

    return (
        str(symbol)
        .strip()
        .upper()
        .replace(
            "/",
            "-"
        )
    )


def aggregate_candles(
    candles,
    bucket_ms
):

    candles = normalize_candles(
        candles
    )

    if not candles:
        return []

    output = []

    current = None

    for candle in candles:

        bucket = (
            candle[0]
            // bucket_ms
        ) * bucket_ms

        if (
            current is None
            or
            current[0] != bucket
        ):

            if current:
                output.append(
                    current
                )

            current = [
                bucket,
                candle[1],
                candle[2],
                candle[3],
                candle[4],
                candle[5]
            ]

        else:

            current[2] = max(
                current[2],
                candle[2]
            )

            current[3] = min(
                current[3],
                candle[3]
            )

            current[4] = candle[4]

            current[5] += candle[5]

    if current:
        output.append(
            current
        )

    return output


def yahoo_chart(
    symbol,
    interval="15m",
    limit=230
):

    symbol = yahoo_symbol(
        symbol
    )

    if interval == "4h":

        raw = yahoo_chart(
            symbol,
            "1h",
            min(
                limit * 4,
                1000
            )
        )

        return aggregate_candles(
            raw,
            4 * 60 * 60 * 1000
        )[-limit:]

    interval_map = {
        "5m": "5m",
        "15m": "15m",
        "1h": "60m",
        "1d": "1d"
    }

    yahoo_interval = interval_map.get(
        interval
    )

    if not yahoo_interval:
        raise ValueError(
            "فاصل Yahoo غير مدعوم"
        )

    if interval in {
        "5m",
        "15m"
    }:
        chart_range = "10d"

    elif interval == "1h":
        chart_range = "60d"

    else:
        chart_range = "2y"

    data = http_json(
        (
            YAHOO_BASE
            +
            "/v8/finance/chart/"
            +
            symbol
        ),
        {
            "interval":
                yahoo_interval,

            "range":
                chart_range,

            "includePrePost":
                "false",

            "events":
                "div,splits"
        },
        timeout=20
    )

    result = (
        data
        .get("chart", {})
        .get("result")
    )

    if not result:
        raise ValueError(
            "Yahoo لم يرجع بيانات لهذا الرمز"
        )

    root = result[0]

    timestamps = (
        root.get(
            "timestamp"
        )
        or []
    )

    quote = (
        root
        .get(
            "indicators",
            {}
        )
        .get(
            "quote",
            [{}]
        )[0]
    )

    output = []

    opens = quote.get(
        "open",
        []
    )

    highs = quote.get(
        "high",
        []
    )

    lows = quote.get(
        "low",
        []
    )

    closes = quote.get(
        "close",
        []
    )

    volumes = quote.get(
        "volume",
        []
    )

    for i, timestamp in enumerate(
        timestamps
    ):

        try:

            opening = opens[i]
            high = highs[i]
            low = lows[i]
            close = closes[i]

            volume = (
                volumes[i]
                if i < len(volumes)
                else 0
            )

            if None in (
                opening,
                high,
                low,
                close
            ):
                continue

            output.append([
                int(timestamp) * 1000,
                float(opening),
                float(high),
                float(low),
                float(close),
                float(
                    volume or 0
                )
            ])

        except Exception:
            continue

    return normalize_candles(
        output
    )[-int(limit):]


# =========================================================
# US STOCK UNIVERSE
# =========================================================

def us_universe(
    force=False
):

    with CACHE_LOCK:

        if (
            not force
            and
            US_CACHE["symbols"]
            and
            time.time()
            - US_CACHE["ts"]
            < 21600
        ):
            return US_CACHE["symbols"]

    symbols = {}

    # NASDAQ
    try:

        text = http_text(
            NASDAQ_LISTED,
            timeout=25
        )

        reader = csv.DictReader(
            io.StringIO(text),
            delimiter="|"
        )

        for row in reader:

            symbol = (
                row.get(
                    "Symbol"
                )
                or ""
            ).strip()

            if (
                not symbol
                or
                symbol.startswith(
                    "File Creation"
                )
            ):
                continue

            if row.get(
                "Test Issue"
            ) == "Y":
                continue

            name = (
                row.get(
                    "Security Name"
                )
                or ""
            ).upper()

            excluded = (
                "WARRANT",
                "UNIT",
                "RIGHT",
                "PREFERRED",
                "DEBENTURE",
                "NOTE"
            )

            if any(
                word in name
                for word in excluded
            ):
                continue

            symbols[symbol] = {
                "symbol": symbol,
                "name":
                    row.get(
                        "Security Name",
                        symbol
                    ),
                "exchange":
                    "NASDAQ",
                "source":
                    "Yahoo Finance"
            }

    except Exception as e:

        print(
            "NASDAQ universe error:",
            e
        )

    # NYSE / AMEX / other listed
    try:

        text = http_text(
            OTHER_LISTED,
            timeout=25
        )

        reader = csv.DictReader(
            io.StringIO(text),
            delimiter="|"
        )

        for row in reader:

            symbol = (
                row.get(
                    "ACT Symbol"
                )
                or ""
            ).strip()

            if (
                not symbol
                or
                symbol.startswith(
                    "File Creation"
                )
            ):
                continue

            if row.get(
                "Test Issue"
            ) == "Y":
                continue

            if row.get(
                "ETF"
            ) == "Y":
                continue

            name = (
                row.get(
                    "Security Name"
                )
                or ""
            ).upper()

            excluded = (
                "WARRANT",
                "UNIT",
                "RIGHT",
                "PREFERRED",
                "DEBENTURE",
                "NOTE",
                "FUND"
            )

            if any(
                word in name
                for word in excluded
            ):
                continue

            symbols.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name":
                        row.get(
                            "Security Name",
                            symbol
                        ),
                    "exchange":
                        row.get(
                            "Exchange",
                            "US"
                        ),
                    "source":
                        "Yahoo Finance"
                }
            )

    except Exception as e:

        print(
            "US other universe error:",
            e
        )

    rows = sorted(
        symbols.values(),
        key=lambda x: x["symbol"]
    )

    with CACHE_LOCK:

        US_CACHE.update({
            "ts": time.time(),
            "symbols": rows
        })

    return rows


# =========================================================
# US SCAN
# =========================================================

def scan_us(
    limit=None
):

    universe = us_universe()

    symbols = [
        item["symbol"]
        for item in universe
    ]

    if limit:

        try:
            requested = int(limit)
            symbols = symbols[:requested]
        except Exception:
            pass

    # لا نرسل آلاف الطلبات دفعة واحدة إلى Yahoo
    scan_limit = int(
        os.getenv(
            "US_SCAN_LIMIT",
            "150"
        )
    )

    symbols = symbols[
        :scan_limit
    ]

    def analyze_one(symbol):

        try:

            candles = yahoo_chart(
                symbol,
                "15m",
                230
            )

            return analyze_klines(
                candles,
                symbol,
                "us",
                "15m"
            )

        except Exception:
            return None

    results = []

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                analyze_one,
                symbol
            )
            for symbol in symbols
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:
                    results.append(
                        result
                    )

            except Exception:
                continue

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return {
        "universe_count":
            len(universe),

        "scanned":
            len(symbols),

        "results":
            results
    }


# =========================================================
# SAUDI MARKET
# =========================================================

def saudi_universe(
    force=False
):

    with CACHE_LOCK:

        if (
            not force
            and
            SAUDI_CACHE["symbols"]
            and
            time.time()
            - SAUDI_CACHE["ts"]
            < 21600
        ):
            return SAUDI_CACHE["symbols"]

    # رموز تداول السعودية الشائعة.
    # Yahoo يستخدم الصيغة 1120.SR
    codes = [
        "1010",
        "1020",
        "1030",
        "1050",
        "1060",
        "1080",
        "1111",
        "1120",
        "1150",
        "1180",
        "1182",
        "1183",
        "1201",
        "1202",
        "1210",
        "1211",
        "1301",
        "1302",
        "1303",
        "1304",
        "1320",
        "1321",
        "1322",
        "1810",
        "1820",
        "1830",
        "1831",
        "1832",
        "1833",
        "1834",
        "1835",
        "2001",
        "2010",
        "2020",
        "2030",
        "2040",
        "2050",
        "2060",
        "2070",
        "2080",
        "2090",
        "2100",
        "2110",
        "2120",
        "2130",
        "2140",
        "2150",
        "2160",
        "2170",
        "2180",
        "2190",
        "2200",
        "2210",
        "2220",
        "2230",
        "2240",
        "2250",
        "2270",
        "2280",
        "2281",
        "2290",
        "2300",
        "2310",
        "2320",
        "2330",
        "2340",
        "2350",
        "2360",
        "2370",
        "2380",
        "2381",
        "2382",
        "3001",
        "3002",
        "3003",
        "3004",
        "3005",
        "3007",
        "3008",
        "3009",
        "3010",
        "3020",
        "3030",
        "3040",
        "3050",
        "3060",
        "3080",
        "3090",
        "3091",
        "4001",
        "4002",
        "4003",
        "4004",
        "4005",
        "4006",
        "4007",
        "4008",
        "4009",
        "4010",
        "4011",
        "4012",
        "4013",
        "4014",
        "4015",
        "4016",
        "4017",
        "4018",
        "4019",
        "4020",
        "4021",
        "4022",
        "4023",
        "4030",
        "4031",
        "4040",
        "4050",
        "4061",
        "4070",
        "4080",
        "4081",
        "4090",
        "4100",
        "4110",
        "4130",
        "4141",
        "4142",
        "4143",
        "4144",
        "4145",
        "4147",
        "4148",
        "4149",
        "4150",
        "4160",
        "4161",
        "4162",
        "4163",
        "4164",
        "4165",
        "4166",
        "4167",
        "4168",
        "4170",
        "4180",
        "4190",
        "4191",
        "4192",
        "4193",
        "4194",
        "4200",
        "4210",
        "4220",
        "4230",
        "4240",
        "4250",
        "4260",
        "4261",
        "4262",
        "4263",
        "4264",
        "4265",
        "4270",
        "4280",
        "4290",
        "4291",
        "4292",
        "4293",
        "4294",
        "4295",
        "4296",
        "4297",
        "4298",
        "4299",
        "4300",
        "4310",
        "4320",
        "4330",
        "4331",
        "4332",
        "4333",
        "4334",
        "4335",
        "4336",
        "4337",
        "4338",
        "4339",
        "4340",
        "4342",
        "4344",
        "4345",
        "4346",
        "4347",
        "4348",
        "4349",
        "4350",
        "4360",
        "4370",
        "4380",
        "4390",
        "4400",
        "4410",
        "4420",
        "4430",
        "4440",
        "4450",
        "4460",
        "4470",
        "4480",
        "4490",
        "4500",
        "4510",
        "4520",
        "4530",
        "4540",
        "4550",
        "4560",
        "4570",
        "4580",
        "4590",
        "4600",
        "4610",
        "4620",
        "4630",
        "4640",
        "4650",
        "4660",
        "4670",
        "4680",
        "4690",
        "4700",
        "4710",
        "4720",
        "4730",
        "4740",
        "4750",
        "4760",
        "4770",
        "4780",
        "4790",
        "4800",
        "4810",
        "4820",
        "4830",
        "4840",
        "4850",
        "4860",
        "4870",
        "4880",
        "4890",
        "4900",
        "4910",
        "4920",
        "4930",
        "4940",
        "4950",
        "4960",
        "4970",
        "4980",
        "4990",
        "5000",
        "5010",
        "5020",
        "5030",
        "5040",
        "5050",
        "5060",
        "5070",
        "5080",
        "5090",
        "5100",
        "5110",
        "5120",
        "5130",
        "5140",
        "5150",
        "5160",
        "5170",
        "5180",
        "5190",
        "5200",
        "5210",
        "5220",
        "5230",
        "5240",
        "5250",
        "5260",
        "5270",
        "5280",
        "5290",
        "5300",
        "5310",
        "5320",
        "5330",
        "5340",
        "5350",
        "5360",
        "5370",
        "5380",
        "5390",
        "5400",
        "5410",
        "5420",
        "5430",
        "5440",
        "5450",
        "5460",
        "5470",
        "5480",
        "5490",
        "5500",
        "5510",
        "5520",
        "5530",
        "5540",
        "5550",
        "5560",
        "5570",
        "5580",
        "5590",
        "5600",
        "5610",
        "5620",
        "5630",
        "5640",
        "5650",
        "5660",
        "5670",
        "5680",
        "5690",
        "5700",
        "5710",
        "5720",
        "5730",
        "5740",
        "5750",
        "5760",
        "5770",
        "5780",
        "5790",
        "5800",
        "5810",
        "5820",
        "5830",
        "5840",
        "5850",
        "5860",
        "5870",
        "5880",
        "5890",
        "5900",
        "5910",
        "5920",
        "5930",
        "5940",
        "5950",
        "5960",
        "5970",
        "5980",
        "5990",
        "6000",
        "6010",
        "6020",
        "6030",
        "6040",
        "6050",
        "6060",
        "6070",
        "6080",
        "6090",
        "6100",
        "6110",
        "6120",
        "6130",
        "6140",
        "6150",
        "6160",
        "6170",
        "6180",
        "6190",
        "6200",
        "6210",
        "6220",
        "6230",
        "6240",
        "6250",
        "6260",
        "6270",
        "6280",
        "6290",
        "6300",
        "6310",
        "6320",
        "6330",
        "6340",
        "6350",
        "6360",
        "6370",
        "6380",
        "6390",
        "6400",
        "6410",
        "6420",
        "6430",
        "6440",
        "6450",
        "6460",
        "6470",
        "6480",
        "6490",
        "6500",
        "6510",
        "6520",
        "6530",
        "6540",
        "6550",
        "6560",
        "6570",
        "6580",
        "6590",
        "6600",
        "6610",
        "6620",
        "6630",
        "6640",
        "6650",
        "6660",
        "6670",
        "6680",
        "6690",
        "6700",
        "6710",
        "6720",
        "6730",
        "6740",
        "6750",
        "6760",
        "6770",
        "6780",
        "6790",
        "6800",
        "6810",
        "6820",
        "6830",
        "6840",
        "6850",
        "6860",
        "6870",
        "6880",
        "6890",
        "6900",
        "6910",
        "6920",
        "6930",
        "6940",
        "6950",
        "6960",
        "6970",
        "6980",
        "6990",
        "7000",
        "7010",
        "7020",
        "7030",
        "7040",
        "7050",
        "7060",
        "7070",
        "7080",
        "7090",
        "7100",
        "7110",
        "7120",
        "7130",
        "7140",
        "7150",
        "7160",
        "7170",
        "7180",
        "7190",
        "7200",
        "7210",
        "7220",
        "7230",
        "7240",
        "7250",
        "7260",
        "7270",
        "7280",
        "7290",
        "7300",
        "7310",
        "7320",
        "7330",
        "7340",
        "7350",
        "7360",
        "7370",
        "7380",
        "7390",
        "7400",
        "7410",
        "7420",
        "7430",
        "7440",
        "7450",
        "7460",
        "7470",
        "7480",
        "7490",
        "7500",
        "7510",
        "7520",
        "7530",
        "7540",
        "7550",
        "7560",
        "7570",
        "7580",
        "7590",
        "7600",
        "7610",
        "7620",
        "7630",
        "7640",
        "7650",
        "7660",
        "7670",
        "7680",
        "7690",
        "7700",
        "7710",
        "7720",
        "7730",
        "7740",
        "7750",
        "7760",
        "7770",
        "7780",
        "7790",
        "7800",
        "7810",
        "7820",
        "7830",
        "7840",
        "7850",
        "7860",
        "7870",
        "7880",
        "7890",
        "7900",
        "7910",
        "7920",
        "7930",
        "7940",
        "7950",
        "7960",
        "7970",
        "7980",
        "7990",
        "8000",
        "8010",
        "8020",
        "8030",
        "8040",
        "8050",
        "8060",
        "8070",
        "8080",
        "8090",
        "8100",
        "8110",
        "8120",
        "8130",
        "8140",
        "8150",
        "8160",
        "8170",
        "8180",
        "8190",
        "8200",
        "8210",
        "8220",
        "8230",
        "8240",
        "8250",
        "8260",
        "8270",
        "8280",
        "8290",
        "8300",
        "8310",
        "8320",
        "8330",
        "8340",
        "8350",
        "8360",
        "8370",
        "8380",
        "8390",
        "8400",
        "8410",
        "8420",
        "8430",
        "8440",
        "8450",
        "8460",
        "8470",
        "8480",
        "8490",
        "8500",
        "8510",
        "8520",
        "8530",
        "8540",
        "8550",
        "8560",
        "8570",
        "8580",
        "8590",
        "8600",
        "8610",
        "8620",
        "8630",
        "8640",
        "8650",
        "8660",
        "8670",
        "8680",
        "8690",
        "8700",
        "8710",
        "8720",
        "8730",
        "8740",
        "8750",
        "8760",
        "8770",
        "8780",
        "8790",
        "8800",
        "8810",
        "8820",
        "8830",
        "8840",
        "8850",
        "8860",
        "8870",
        "8880",
        "8890",
        "8900",
        "8910",
        "8920",
        "8930",
        "8940",
        "8950",
        "8960",
        "8970",
        "8980",
        "8990",
        "9000",
        "9010",
        "9020",
        "9030",
        "9040",
        "9050",
        "9060",
        "9070",
        "9080",
        "9090",
        "9100",
        "9110",
        "9120",
        "9130",
        "9140",
        "9150",
        "9160",
        "9170",
        "9180",
        "9190",
        "9200",
        "9210",
        "9220",
        "9230",
        "9240",
        "9250",
        "9260",
        "9270",
        "9280",
        "9290",
        "9300",
        "9310",
        "9320",
        "9330",
        "9340",
        "9350",
        "9360",
        "9370",
        "9380",
        "9390",
        "9400",
        "9410",
        "9420",
        "9430",
        "9440",
        "9450",
        "9460",
        "9470",
        "9480",
        "9490",
        "9500",
        "9510",
        "9520",
        "9530",
        "9540",
        "9550",
        "9560",
        "9570",
        "9580",
        "9590",
        "9600",
        "9610",
        "9620",
        "9630",
        "9640",
        "9650",
        "9660",
        "9670",
        "9680",
        "9690",
        "9700",
        "9710",
        "9720",
        "9730",
        "9740",
        "9750",
        "9760",
        "9770",
        "9780",
        "9790",
        "9800",
        "9810",
        "9820",
        "9830",
        "9840",
        "9850",
        "9860",
        "9870",
        "9880",
        "9890",
        "9900",
        "9910",
        "9920",
        "9930",
        "9940",
        "9950",
        "9960",
        "9970",
        "9980",
        "9990"
    ]

    rows = []

    for code in dict.fromkeys(codes):

        rows.append({
            "symbol": code,
            "yahoo_symbol":
                code + ".SR",
            "name": code,
            "exchange":
                "Saudi Exchange",
            "source":
                "Yahoo Finance / Saudi Exchange"
        })

    with CACHE_LOCK:

        SAUDI_CACHE.update({
            "ts": time.time(),
            "symbols": rows
        })

    return rows


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():
    return render_template(
        "index.html"
    )


@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "time":
            now_utc().isoformat(),

        "sources": {
            "crypto":
                "Bybit Spot",
            "us":
                "Yahoo Finance",
            "saudi":
                "Saudi Exchange/Yahoo Finance"
        }
    })


# =========================================================
# AUTH REGISTER
# =========================================================

@app.post("/api/auth/register")
def register():

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    username = str(
        data.get(
            "username",
            ""
        )
    ).strip()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    if (
        len(username) < 3
        or
        len(password) < 6
    ):

        return json_error(
            "اسم المستخدم أو كلمة المرور غير صحيحة"
        )

    if not DATABASE_URL:

        return json_error(
            "قاعدة البيانات غير مهيأة",
            500
        )

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO users(
                        username,
                        password_hash
                    )
                    VALUES(%s,%s)
                    RETURNING id
                    """,
                    (
                        username,
                        hash_password(
                            password
                        )
                    )
                )

                user_id = (
                    cur.fetchone()[0]
                )

            conn.commit()

        session.permanent = True

        session["user_id"] = user_id

        return jsonify({
            "ok": True,
            "user":
                user_json(
                    user_row(
                        user_id=user_id
                    )
                )
        })

    except Exception as e:

        if "duplicate" in str(
            e
        ).lower():

            return json_error(
                "اسم المستخدم موجود مسبقاً"
            )

        print(
            "Register error:",
            e
        )

        return json_error(
            "تعذر إنشاء الحساب",
            500
        )


# =========================================================
# AUTH LOGIN
# =========================================================

@app.post("/api/auth/login")
def login():

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    username = str(
        data.get(
            "username",
            ""
        )
    ).strip()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    row = user_row(
        username=username
    )

    if (
        not row
        or
        not verify_password(
            password,
            row[2]
        )
    ):

        return json_error(
            "بيانات الدخول غير صحيحة",
            401
        )

    session.permanent = True

    session["user_id"] = row[0]

    return jsonify({
        "ok": True,
        "user":
            user_json(row)
    })


# =========================================================
# LOGOUT
# =========================================================

@app.post("/api/auth/logout")
def logout():

    session.pop(
        "user_id",
        None
    )

    return jsonify({
        "ok": True
    })


# =========================================================
# AUTH ME
# =========================================================

@app.get("/api/auth/me")
def auth_me():

    row = current_user()

    return jsonify({
        "ok": True,
        "user":
            user_json(row),
        "authenticated":
            bool(row),
        "subscription_active":
            subscription_active(row)
    })


# =========================================================
# ADMIN
# =========================================================

@app.get("/admin")
def admin_page():

    return render_template(
        "index.html"
    )


@app.post("/api/admin/login")
def admin_login():

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    username = str(
        data.get(
            "username",
            ""
        )
    )

    password = str(
        data.get(
            "password",
            ""
        )
    )

    if (
        username != ADMIN_USERNAME
        or
        not hmac.compare_digest(
            password,
            ADMIN_PASSWORD
        )
    ):

        return json_error(
            "بيانات المدير غير صحيحة",
            401
        )

    session.permanent = True

    session["admin"] = True

    return jsonify({
        "ok": True,
        "admin": True
    })


@app.get("/api/admin/me")
def admin_me():

    return jsonify({
        "ok": True,
        "admin":
            is_admin()
    })


@app.post("/api/admin/logout")
def admin_logout():

    session.pop(
        "admin",
        None
    )

    return jsonify({
        "ok": True
    })


# =========================================================
# ADMIN STATS
# =========================================================

@app.get("/api/admin/stats")
def admin_stats():

    if not admin_required():
        return json_error(
            "غير مصرح",
            403
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT COUNT(*) FROM users"
            )

            users = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM payments
                WHERE status='pending'
                """
            )

            pending = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM payments
                WHERE status='approved'
                """
            )

            approved = cur.fetchone()[0]

    return jsonify({
        "ok": True,
        "users": users,
        "pending_payments":
            pending,
        "approved_payments":
            approved
    })


# =========================================================
# ADMIN USERS
# =========================================================

@app.get("/api/admin/users")
def admin_users():

    if not admin_required():
        return json_error(
            "غير مصرح",
            403
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    username,
                    created_at,
                    plan,
                    plan_start,
                    plan_end,
                    is_active
                FROM users
                ORDER BY id DESC
                """
            )

            rows = cur.fetchall()

    users = []

    for row in rows:

        users.append({
            "id": row[0],
            "username": row[1],
            "created_at":
                safe_json_value(
                    row[2]
                ),
            "plan": row[3],
            "plan_start":
                safe_json_value(
                    row[4]
                ),
            "plan_end":
                safe_json_value(
                    row[5]
                ),
            "is_active": row[6]
        })

    return jsonify({
        "ok": True,
        "users": users
    })


# =========================================================
# ADMIN USER PLAN
# =========================================================

@app.post(
    "/api/admin/users/<int:user_id>/plan"
)
def admin_user_plan(
    user_id
):

    if not admin_required():
        return json_error(
            "غير مصرح",
            403
        )

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = str(
        data.get(
            "plan",
            ""
        )
    )

    days = (
        PLANS
        .get(
            plan,
            {}
        )
        .get(
            "days"
        )
    )

    if not days:
        return json_error(
            "الخطة غير صحيحة"
        )

    start = now_utc()

    end = (
        start
        +
        timedelta(
            days=days
        )
    )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE users
                SET
                    plan=%s,
                    plan_start=%s,
                    plan_end=%s
                WHERE id=%s
                """,
                (
                    plan,
                    start,
                    end,
                    user_id
                )
            )

        conn.commit()

    return jsonify({
        "ok": True
    })


# =========================================================
# ADMIN PAYMENTS
# =========================================================

@app.get("/api/admin/payments")
def admin_payments():

    if not admin_required():
        return json_error(
            "غير مصرح",
            403
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    p.id,
                    p.user_id,
                    u.username,
                    p.plan,
                    p.amount,
                    p.txid,
                    p.status,
                    p.created_at,
                    p.reviewed_at
                FROM payments p
                JOIN users u
                    ON u.id=p.user_id
                ORDER BY p.id DESC
                """
            )

            rows = cur.fetchall()

    payments = []

    for row in rows:

        payments.append({
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "plan": row[3],
            "amount":
                float(row[4]),
            "txid": row[5],
            "status": row[6],
            "created_at":
                safe_json_value(
                    row[7]
                ),
            "reviewed_at":
                safe_json_value(
                    row[8]
                )
        })

    return jsonify({
        "ok": True,
        "payments": payments
    })


# =========================================================
# ADMIN PAYMENT REVIEW
# =========================================================

@app.post(
    "/api/admin/payments/<int:payment_id>/review"
)
def admin_payment_review(
    payment_id
):

    if not admin_required():
        return json_error(
            "غير مصرح",
            403
        )

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    status = str(
        data.get(
            "status",
            ""
        )
    )

    if status not in {
        "approved",
        "rejected"
    }:

        return json_error(
            "الحالة غير صحيحة"
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    user_id,
                    plan
                FROM payments
                WHERE id=%s
                """,
                (payment_id,)
            )

            payment = cur.fetchone()

            if not payment:

                return json_error(
                    "الدفعة غير موجودة",
                    404
                )

            cur.execute(
                """
                UPDATE payments
                SET
                    status=%s,
                    reviewed_at=NOW()
                WHERE id=%s
                """,
                (
                    status,
                    payment_id
                )
            )

            if status == "approved":

                days = PLANS[
                    payment[1]
                ]["days"]

                start = now_utc()

                end = (
                    start
                    +
                    timedelta(
                        days=days
                    )
                )

                cur.execute(
                    """
                    UPDATE users
                    SET
                        plan=%s,
                        plan_start=%s,
                        plan_end=%s
                    WHERE id=%s
                    """,
                    (
                        payment[1],
                        start,
                        end,
                        payment[0]
                    )
                )

        conn.commit()

    return jsonify({
        "ok": True
    })


# =========================================================
# SUBSCRIPTIONS
# =========================================================

@app.get(
    "/api/subscription/plans"
)
def subscription_plans():

    return jsonify({
        "ok": True,
        "plans": PLANS,
        "payment_address":
            PAYMENT_ADDRESS
    })


@app.post(
    "/api/subscription/request"
)
def subscription_request():

    row = current_user()

    if not row:

        return json_error(
            "سجل الدخول أولاً",
            401
        )

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = str(
        data.get(
            "plan",
            ""
        )
    )

    txid = str(
        data.get(
            "txid",
            ""
        )
    ).strip()

    if plan not in PLANS:

        return json_error(
            "الخطة غير صحيحة"
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO payments(
                    user_id,
                    plan,
                    amount,
                    txid
                )
                VALUES(%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    row[0],
                    plan,
                    PLANS[plan]["amount"],
                    txid
                )
            )

            payment_id = (
                cur.fetchone()[0]
            )

        conn.commit()

    return jsonify({
        "ok": True,
        "payment_id":
            payment_id
    })


@app.get(
    "/api/subscription/my"
)
def subscription_my():

    row = current_user()

    return jsonify({
        "ok": True,
        "user":
            user_json(row),
        "active":
            subscription_active(row),
        "plans":
            PLANS,
        "payment_address":
            PAYMENT_ADDRESS
    })


# =========================================================
# SETTINGS
# =========================================================

@app.get("/api/settings")
def get_settings():

    row = current_user()

    if not row:

        return json_error(
            "سجل الدخول أولاً",
            401
        )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT settings
                FROM user_settings
                WHERE user_id=%s
                """,
                (row[0],)
            )

            result = cur.fetchone()

    return jsonify({
        "ok": True,
        "settings":
            result[0]
            if result
            else {}
    })


@app.post("/api/settings")
def save_settings():

    row = current_user()

    if not row:

        return json_error(
            "سجل الدخول أولاً",
            401
        )

    settings = (
        request.get_json(
            silent=True
        )
        or {}
    )

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO user_settings(
                    user_id,
                    settings
                )
                VALUES(%s,%s)
                ON CONFLICT(user_id)
                DO UPDATE SET
                    settings=EXCLUDED.settings
                """,
                (
                    row[0],
                    json.dumps(
                        settings
                    )
                )
            )

        conn.commit()

    return jsonify({
        "ok": True,
        "settings": settings
    })


# =========================================================
# CRYPTO
# OLD BINANCE ROUTES KEPT
# =========================================================

@app.get(
    "/api/binance/test"
)
def crypto_test():

    try:

        bybit_get(
            "/v5/market/time"
        )

        return jsonify({
            "ok": True,
            "connected": True,
            "source":
                "Bybit Spot"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "connected": False,
            "source":
                "Bybit Spot",
            "error":
                str(e)
        }), 502


@app.get(
    "/api/binance/markets"
)
def crypto_markets():

    try:

        return jsonify({
            "ok": True,
            "source":
                "Bybit Spot",
            "markets":
                bybit_symbols()
        })

    except Exception as e:

        print(
            "Markets error:",
            e
        )

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/binance/prices"
)
def crypto_prices():

    try:

        rows = bybit_tickers()

        prices = []

        for row in rows:

            symbol = str(
                row.get(
                    "symbol",
                    ""
                )
            ).upper()

            if symbol.endswith(
                "USDT"
            ):

                prices.append(
                    row
                )

        return jsonify({
            "ok": True,
            "source":
                "Bybit Spot",
            "prices":
                prices
        })

    except Exception as e:

        print(
            "Prices error:",
            e
        )

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/binance/price"
)
def crypto_price():

    try:

        symbol = request.args.get(
            "symbol",
            "BTCUSDT"
        )

        return jsonify({
            "ok": True,
            "data":
                bybit_price(
                    symbol
                )
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/binance/klines"
)
def crypto_klines():

    try:

        symbol = request.args.get(
            "symbol",
            "BTCUSDT"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        limit = request.args.get(
            "limit",
            "230"
        )

        candles = bybit_kline(
            symbol,
            interval,
            int(limit)
        )

        return jsonify({
            "ok": True,
            "source":
                "Bybit Spot",
            "symbol":
                symbol,
            "interval":
                interval,
            "klines":
                candles
        })

    except Exception as e:

        print(
            "Klines error:",
            e
        )

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/binance/analysis"
)
def crypto_analysis():

    try:

        symbol = request.args.get(
            "symbol",
            "BTCUSDT"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        candles = bybit_kline(
            symbol,
            interval,
            230
        )

        analysis = analyze_klines(
            candles,
            symbol,
            "spot",
            interval
        )

        analysis[
            "data_source"
        ] = "Bybit Spot"

        return jsonify({
            "ok": True,
            "analysis":
                analysis
        })

    except Exception as e:

        print(
            "Analysis error:",
            e
        )

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/binance/scan"
)
def crypto_scan():

    try:

        results = scan_spot()

        return jsonify({
            "ok": True,
            "source":
                "Bybit Spot",
            "results":
                results
        })

    except Exception as e:

        print(
            "Scan error:",
            e
        )

        return json_error(
            str(e),
            502
        )


# =========================================================
# ALPHA + FUTURES
# SAME SPOT DATA
# =========================================================

def spot_alias_analysis(
    section
):

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    candles = bybit_kline(
        symbol,
        interval,
        230
    )

    analysis = analyze_klines(
        candles,
        symbol,
        "spot",
        interval
    )

    analysis["section"] = section

    analysis[
        "data_source"
    ] = "Bybit Spot"

    return jsonify({
        "ok": True,
        "analysis":
            analysis
    })


@app.get(
    "/api/alpha/analysis"
)
def alpha_analysis():

    try:

        return spot_alias_analysis(
            "alpha"
        )

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/futures/analysis"
)
def futures_analysis():

    try:

        return spot_alias_analysis(
            "futures"
        )

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/alpha/scan"
)
def alpha_scan():

    try:

        return jsonify({
            "ok": True,
            "section":
                "alpha",
            "source":
                "Bybit Spot",
            "results":
                scan_spot()
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/futures/scan"
)
def futures_scan():

    try:

        return jsonify({
            "ok": True,
            "section":
                "futures",
            "source":
                "Bybit Spot",
            "results":
                scan_spot()
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


# =========================================================
# US ROUTES
# =========================================================

@app.get(
    "/api/us/markets"
)
def us_markets():

    try:

        rows = us_universe()

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",
            "count":
                len(rows),
            "markets":
                rows
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/us/price"
)
def us_price():

    try:

        symbol = request.args.get(
            "symbol",
            "AAPL"
        )

        candles = yahoo_chart(
            symbol,
            "1d",
            5
        )

        if not candles:
            raise ValueError(
                "لا توجد بيانات"
            )

        last = candles[-1]

        previous = (
            candles[-2]
            if len(candles) > 1
            else last
        )

        previous_close = (
            previous[4]
        )

        change = 0

        if previous_close:
            change = (
                (
                    last[4]
                    /
                    previous_close
                )
                - 1
            ) * 100

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",
            "symbol":
                symbol.upper(),
            "price":
                last[4],
            "change24h":
                change
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/us/klines"
)
def us_klines():

    try:

        symbol = request.args.get(
            "symbol",
            "AAPL"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        limit = int(
            request.args.get(
                "limit",
                "230"
            )
        )

        candles = yahoo_chart(
            symbol,
            interval,
            limit
        )

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",
            "symbol":
                symbol.upper(),
            "interval":
                interval,
            "klines":
                candles
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/us/analysis"
)
def us_analysis():

    try:

        symbol = request.args.get(
            "symbol",
            "AAPL"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        candles = yahoo_chart(
            symbol,
            interval,
            230
        )

        return jsonify({
            "ok": True,
            "analysis":
                analyze_klines(
                    candles,
                    symbol,
                    "us",
                    interval
                )
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/us/scan"
)
def us_scan_route():

    try:

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",
            "data":
                scan_us(
                    request.args.get(
                        "limit"
                    )
                )
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


# =========================================================
# SAUDI ROUTES
# =========================================================

@app.get(
    "/api/saudi/markets"
)
def saudi_markets():

    try:

        rows = saudi_universe()

        return jsonify({
            "ok": True,
            "source":
                "Saudi Exchange / Yahoo Finance",
            "count":
                len(rows),
            "markets":
                rows
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/saudi/klines"
)
def saudi_klines():

    try:

        symbol = request.args.get(
            "symbol",
            "1120"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        yahoo = (
            symbol
            if "." in symbol
            else symbol + ".SR"
        )

        limit = int(
            request.args.get(
                "limit",
                "230"
            )
        )

        candles = yahoo_chart(
            yahoo,
            interval,
            limit
        )

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",
            "symbol":
                symbol,
            "interval":
                interval,
            "klines":
                candles
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


@app.get(
    "/api/saudi/analysis"
)
def saudi_analysis():

    try:

        symbol = request.args.get(
            "symbol",
            "1120"
        )

        interval = request.args.get(
            "interval",
            "15m"
        )

        yahoo = (
            symbol
            if "." in symbol
            else symbol + ".SR"
        )

        candles = yahoo_chart(
            yahoo,
            interval,
            230
        )

        return jsonify({
            "ok": True,
            "analysis":
                analyze_klines(
                    candles,
                    symbol,
                    "saudi",
                    interval
                )
        })

    except Exception as e:

        return json_error(
            str(e),
            502
        )


# =========================================================
# NEWS
# =========================================================

@app.get(
    "/api/news"
)
def news():

    with CACHE_LOCK:

        if (
            NEWS_CACHE["items"]
            and
            time.time()
            - NEWS_CACHE["ts"]
            < 600
        ):

            return jsonify({
                "ok": True,
                "items":
                    NEWS_CACHE["items"]
            })

    feeds = [
        "https://www.coindesk.com/"
        "arc/outboundfeeds/rss/"
    ]

    items = []

    for feed in feeds:

        try:

            root = ET.fromstring(
                http_text(
                    feed,
                    timeout=15
                )
            )

            for item in root.findall(
                ".//item"
            )[:30]:

                title = (
                    item.findtext(
                        "title"
                    )
                    or ""
                )

                link = (
                    item.findtext(
                        "link"
                    )
                    or ""
                )

                published = (
                    item.findtext(
                        "pubDate"
                    )
                    or ""
                )

                items.append({
                    "title":
                        html.unescape(
                            title
                        ),
                    "link":
                        link,
                    "published":
                        published
                })

        except Exception as e:

            print(
                "News error:",
                e
            )

            continue

    items = items[:30]

    with CACHE_LOCK:

        NEWS_CACHE.update({
            "ts": time.time(),
            "items": items
        })

    return jsonify({
        "ok": True,
        "items": items
    })


# =========================================================
# DATABASE INIT
# =========================================================

try:

    init_db()

except Exception as e:

    print(
        "DB init warning:",
        e
    )


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
