import os
import time
import json
import re
import html
import hashlib
import hmac
import secrets
import threading

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET
from functools import wraps

import requests
import psycopg

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session,
    redirect,
)


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
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
# DATABASE / AUTH
# =========================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
)

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
# MARKET DATA SOURCE
# =========================================================

MARKET_SOURCE = "OKX"

OKX_BASES = [
    "https://www.okx.com",
]

OKX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.okx.com/",
}

HTTP = requests.Session()
HTTP.headers.update(OKX_HEADERS)


OKX_INTERVALS = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}


# =========================================================
# CACHE
# =========================================================

MARKET_CACHE = {
    "ts": 0,
    "symbols": []
}

TICKER_CACHE = {
    "ts": 0,
    "items": []
}

KLINE_CACHE = {}

SCAN_CACHE = {}

NEWS_CACHE = {
    "ts": 0,
    "items": []
}

CACHE_LOCK = threading.Lock()


# =========================================================
# FILTERS
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
    "USD1",
    "USDS",
    "USDTB",
    "USAT",
}

LEVERAGED_WORDS = (
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
)

INTERVALS = {
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
}


# =========================================================
# DATABASE
# =========================================================

def db_conn():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL غير مضبوط"
        )

    return psycopg.connect(
        DATABASE_URL
    )


def init_db():

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        plan TEXT NOT NULL DEFAULT 'free',
                        plan_expires TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        id SERIAL PRIMARY KEY,
                        key TEXT UNIQUE NOT NULL,
                        value TEXT NOT NULL DEFAULT ''
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_requests (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL
                            REFERENCES users(id)
                            ON DELETE CASCADE,
                        plan TEXT NOT NULL,
                        amount NUMERIC(12,2) NOT NULL,
                        network TEXT NOT NULL DEFAULT 'TRC20',
                        txid TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        reviewed_at TIMESTAMPTZ NULL
                    )
                """)

            conn.commit()

        print("PostgreSQL connected successfully")
        print("Database tables ready")

    except Exception as e:

        print(
            "Database init error:",
            e
        )


# =========================================================
# PASSWORDS
# =========================================================

def hash_password(password):

    salt = secrets.token_bytes(16)
    iterations = 120000

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        iterations
    )

    return (
        f"pbkdf2${iterations}"
        f"${salt.hex()}"
        f"${digest.hex()}"
    )


def verify_password(
    password,
    stored
):

    try:

        _,
        iterations,
        salt_hex,
        digest_hex = stored.split(
            "$",
            3
        )

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            int(iterations)
        )

        return hmac.compare_digest(
            digest.hex(),
            digest_hex
        )

    except Exception:

        return False


# =========================================================
# USER HELPERS
# =========================================================

def user_row(user_id):

    with db_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    name,
                    email,
                    plan,
                    plan_expires,
                    created_at
                FROM users
                WHERE id=%s
                """,
                (user_id,)
            )

            return cur.fetchone()


def user_json(row):

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "plan": row[3],
        "plan_expires": (
            row[4].isoformat()
            if row[4]
            else None
        ),
        "created_at": (
            row[5].isoformat()
            if row[5]
            else None
        ),
    }


def current_user():

    uid = session.get(
        "user_id"
    )

    if not uid:
        return None

    try:

        return user_row(uid)

    except Exception:

        return None


def is_admin():

    return bool(
        session.get("admin")
    )


def login_required(fn):

    @wraps(fn)
    def wrapper(*args, **kwargs):

        if not current_user():

            return jsonify({
                "ok": False,
                "message": "يجب تسجيل الدخول أولاً"
            }), 401

        return fn(
            *args,
            **kwargs
        )

    return wrapper


def admin_required(fn):

    @wraps(fn)
    def wrapper(*args, **kwargs):

        if not is_admin():

            return jsonify({
                "ok": False,
                "message": "غير مصرح"
            }), 403

        return fn(
            *args,
            **kwargs
        )

    return wrapper


# =========================================================
# OKX HTTP
# =========================================================

def okx_get(
    path,
    params=None,
    timeout=10.0
):

    last_error = (
        "تعذر الاتصال بـ OKX"
    )

    params = params or {}

    for base in OKX_BASES:

        url = base + path

        for attempt in range(3):

            try:

                response = requests.get(
                    url,
                    params=params,
                    headers=OKX_HEADERS,
                    timeout=timeout
                )

                print(
                    f"OKX "
                    f"{path} "
                    f"[{base}] "
                    f"HTTP {response.status_code}"
                )

                if response.status_code == 200:

                    try:

                        data = response.json()

                    except Exception:

                        last_error = (
                            "استجابة OKX غير صالحة"
                        )

                        time.sleep(
                            0.5 * (attempt + 1)
                        )

                        continue

                    code = str(
                        data.get(
                            "code",
                            ""
                        )
                    )

                    if code == "0":

                        return data

                    msg = (
                        data.get(
                            "msg"
                        )
                        or
                        f"OKX code {code}"
                    )

                    last_error = msg

                    time.sleep(
                        0.5 * (attempt + 1)
                    )

                    continue

                if response.status_code in (
                    408,
                    425,
                    429
                ):

                    last_error = (
                        f"OKX HTTP "
                        f"{response.status_code}"
                    )

                    time.sleep(
                        1.2 * (attempt + 1)
                    )

                    continue

                if response.status_code >= 500:

                    last_error = (
                        f"OKX HTTP "
                        f"{response.status_code}"
                    )

                    time.sleep(
                        1.0 * (attempt + 1)
                    )

                    continue

                if response.status_code == 403:

                    body = (
                        response.text[:250]
                        .replace("\n", " ")
                    )

                    last_error = (
                        "OKX HTTP 403"
                    )

                    print(
                        "OKX 403:",
                        body
                    )

                    break

                body = (
                    response.text[:180]
                    .replace("\n", " ")
                )

                last_error = (
                    f"OKX HTTP "
                    f"{response.status_code}"
                    f" {body}"
                )

                break

            except requests.Timeout:

                last_error = (
                    "انتهت مهلة الاتصال بـ OKX"
                )

                time.sleep(
                    0.7 * (attempt + 1)
                )

            except requests.RequestException as e:

                last_error = str(e)[:200]

                time.sleep(
                    0.7 * (attempt + 1)
                )

            except Exception as e:

                last_error = str(e)[:200]

                break

    raise RuntimeError(
        last_error
    )


# =========================================================
# SYMBOL CONVERSION
# =========================================================

def internal_to_okx(symbol):

    symbol = str(
        symbol
    ).upper().strip()

    if symbol.endswith("USDT"):

        base = symbol[:-4]

        return (
            f"{base}-USDT"
        )

    return symbol


def okx_to_internal(symbol):

    symbol = str(
        symbol
    ).upper().strip()

    if symbol.endswith("-USDT"):

        return (
            symbol[:-5]
            + "USDT"
        )

    return symbol.replace(
        "-",
        ""
    )


# =========================================================
# OKX SYMBOLS
# =========================================================

def market_symbols():

    now = time.time()

    with CACHE_LOCK:

        if (
            MARKET_CACHE["symbols"]
            and
            now - MARKET_CACHE["ts"] < 900
        ):

            return MARKET_CACHE[
                "symbols"
            ]

    data = okx_get(
        "/api/v5/public/instruments",
        params={
            "instType": "SPOT"
        },
        timeout=10
    )

    rows = (
        data.get(
            "data",
            []
        )
    )

    result = []

    for item in rows:

        inst_id = str(
            item.get(
                "instId",
                ""
            )
        ).upper()

        base = str(
            item.get(
                "baseCcy",
                ""
            )
        ).upper()

        quote = str(
            item.get(
                "quoteCcy",
                ""
            )
        ).upper()

        state = str(
            item.get(
                "state",
                ""
            )
        ).lower()

        if not inst_id:
            continue

        if state != "live":
            continue

        if quote != "USDT":
            continue

        if not inst_id.endswith(
            "-USDT"
        ):
            continue

        if base in STABLE_BASES:
            continue

        if any(
            word in base
            for word in LEVERAGED_WORDS
        ):
            continue

        result.append({
            "symbol": okx_to_internal(
                inst_id
            ),
            "baseAsset": base,
            "quoteAsset": quote
        })

    unique = {}

    for item in result:

        unique[
            item["symbol"]
        ] = item

    result = list(
        unique.values()
    )

    with CACHE_LOCK:

        MARKET_CACHE["ts"] = now
        MARKET_CACHE[
            "symbols"
        ] = result

    print(
        f"OKX Spot symbols: {len(result)}"
    )

    return result


# =========================================================
# OKX TICKERS
# =========================================================

def ticker24():

    now = time.time()

    with CACHE_LOCK:

        if (
            TICKER_CACHE["items"]
            and
            now - TICKER_CACHE["ts"] < 15
        ):

            return TICKER_CACHE[
                "items"
            ]

    data = okx_get(
        "/api/v5/market/tickers",
        params={
            "instType": "SPOT"
        },
        timeout=8
    )

    items = (
        data.get(
            "data",
            []
        )
    )

    with CACHE_LOCK:

        TICKER_CACHE["ts"] = now
        TICKER_CACHE[
            "items"
        ] = items

    return items


def ticker_map():

    result = {}

    for item in ticker24():

        symbol = okx_to_internal(
            item.get(
                "instId",
                ""
            )
        )

        if symbol:

            result[
                symbol
            ] = item

    return result


# =========================================================
# OKX KLINES
# =========================================================

def okx_klines(
    symbol,
    interval="15m",
    limit=200
):

    symbol = symbol.upper()

    if interval not in OKX_INTERVALS:

        raise RuntimeError(
            f"الفريم غير مدعوم: {interval}"
        )

    limit = max(
        20,
        min(
            int(limit),
            300
        )
    )

    cache_key = (
        f"{symbol}:"
        f"{interval}:"
        f"{limit}"
    )

    now = time.time()

    with CACHE_LOCK:

        cached = KLINE_CACHE.get(
            cache_key
        )

        if (
            cached
            and
            now - cached["ts"] < 15
        ):

            return cached["rows"]

    inst_id = internal_to_okx(
        symbol
    )

    data = okx_get(
        "/api/v5/market/candles",
        params={
            "instId": inst_id,
            "bar": OKX_INTERVALS[
                interval
            ],
            "limit": limit
        },
        timeout=8
    )

    rows = (
        data.get(
            "data",
            []
        )
    )

    rows = list(
        reversed(rows)
    )

    result = []

    for row in rows:

        if len(row) < 6:
            continue

        try:

            volume = (
                row[5]
                if len(row) > 5
                else "0"
            )

            result.append([
                int(
                    float(row[0])
                ),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(volume),
                str(
                    row[7]
                    if len(row) > 7
                    else "0"
                )
            ])

        except Exception:

            continue

    with CACHE_LOCK:

        KLINE_CACHE[
            cache_key
        ] = {
            "ts": now,
            "rows": result
        }

        if len(KLINE_CACHE) > 500:

            oldest = sorted(
                KLINE_CACHE.items(),
                key=lambda x: x[1]["ts"]
            )[:100]

            for key, _ in oldest:

                KLINE_CACHE.pop(
                    key,
                    None
                )

    return result


# =========================================================
# INDICATORS
# =========================================================

def ema(
    values,
    period
):

    if not values:
        return None

    if len(values) < period:
        period = len(values)

    seed = (
        sum(values[:period])
        / period
    )

    e = seed

    k = 2 / (
        period + 1
    )

    for value in values[
        period:
    ]:

        e = (
            value * k
            + e * (1 - k)
        )

    return e


def rsi(
    values,
    period=14
):

    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
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
            avg_gain
            * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss
            * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100
        / (1 + rs)
    )


def atr(
    klines,
    period=14
):

    if len(klines) < 2:
        return 0.0

    trs = []

    for i in range(
        1,
        len(klines)
    ):

        high = float(
            klines[i][2]
        )

        low = float(
            klines[i][3]
        )

        previous_close = float(
            klines[i - 1][4]
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

    if not trs:
        return 0.0

    used = trs[-period:]

    return (
        sum(used)
        / len(used)
    )


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def analyze_klines(
    klines
):

    if not klines:

        raise RuntimeError(
            "لا توجد شموع متاحة"
        )

    closes = [
        float(x[4])
        for x in klines
    ]

    highs = [
        float(x[2])
        for x in klines
    ]

    lows = [
        float(x[3])
        for x in klines
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

    e12 = ema(
        closes,
        12
    )

    e26 = ema(
        closes,
        26
    )

    macd_line = (
        (e12 or 0)
        - (e26 or 0)
    )

    macd_series = []

    start = max(
        26,
        len(closes) - 80
    )

    for i in range(
        start,
        len(closes)
    ):

        a = ema(
            closes[:i + 1],
            12
        ) or 0

        b = ema(
            closes[:i + 1],
            26
        ) or 0

        macd_series.append(
            a - b
        )

    macd_signal = (
        ema(
            macd_series,
            9
        )
        if macd_series
        else 0
    )

    macd_hist = (
        macd_line
        - (macd_signal or 0)
    )

    score = 50

    reasons = []

    if e20 is not None:

        if price > e20:

            score += 8

            reasons.append(
                "السعر فوق EMA20"
            )

        else:

            score -= 8

            reasons.append(
                "السعر تحت EMA20"
            )

    if e50 is not None:

        if price > e50:

            score += 8

            reasons.append(
                "السعر فوق EMA50"
            )

        else:

            score -= 8

            reasons.append(
                "السعر تحت EMA50"
            )

    if e200 is not None:

        if price > e200:

            score += 10

            reasons.append(
                "السعر فوق EMA200"
            )

        else:

            score -= 10

            reasons.append(
                "السعر تحت EMA200"
            )

    if 50 <= rv <= 70:

        score += 8

        reasons.append(
            "RSI في نطاق إيجابي"
        )

    elif rv > 70:

        score += 2

        reasons.append(
            "RSI مرتفع"
        )

    elif rv < 30:

        score += 3

        reasons.append(
            "RSI منخفض"
        )

    else:

        score -= 5

        reasons.append(
            "RSI محايد/ضعيف"
        )

    if macd_hist > 0:

        score += 8

        reasons.append(
            "MACD إيجابي"
        )

    else:

        score -= 8

        reasons.append(
            "MACD سلبي"
        )

    score = max(
        0,
        min(
            100,
            score
        )
    )

    if score >= 80:

        signal = "شراء قوي"
        direction = "buy"

    elif score >= 65:

        signal = "شراء"
        direction = "buy"

    elif score <= 20:

        signal = "بيع قوي"
        direction = "sell"

    elif score <= 35:

        signal = "بيع"
        direction = "sell"

    else:

        signal = "حيادي"
        direction = "neutral"

    a = atr(
        klines,
        14
    )

    risk = max(
        a * 1.5,
        price * 0.01
    )

    if direction == "buy":

        sl = max(
            price - risk,
            0
        )

        tp1 = (
            price
            + risk * 1.5
        )

        tp2 = (
            price
            + risk * 2
        )

        tp3 = (
            price
            + risk * 3
        )

    elif direction == "sell":

        sl = (
            price
            + risk
        )

        tp1 = max(
            price
            - risk * 1.5,
            0
        )

        tp2 = max(
            price
            - risk * 2,
            0
        )

        tp3 = max(
            price
            - risk * 3,
            0
        )

    else:

        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

    support = (
        min(
            lows[-20:]
        )
        if lows
        else None
    )

    resistance = (
        max(
            highs[-20:]
        )
        if highs
        else None
    )

    candles = []

    for x in klines[-100:]:

        candles.append({
            "t": int(x[0]),
            "o": float(x[1]),
            "h": float(x[2]),
            "l": float(x[3]),
            "c": float(x[4]),
            "v": float(x[5])
        })

    return {
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(
            score / 10,
            1
        ),
        "price": price,
        "entry": price,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "rsi": rv,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_hist,
        "atr": a,
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "candles": candles,
    }


# =========================================================
# US MARKET — YAHOO FINANCE
# =========================================================

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart"
)

US_MARKET_CACHE = {
    "ts": 0,
    "interval": "",
    "results": []
}

US_MARKET_CACHE_LOCK = threading.Lock()

US_MARKET_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "GOOG",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "ORCL",
    "PLTR",
    "MU",
    "INTC",
    "QCOM",
    "AMAT",
    "MSTR",
    "COIN",
    "HOOD",
    "SOFI",
    "RIVN",
    "NIO",
    "SMCI",
    "ARM",
    "CRWD",
    "PANW",
    "ADBE",
    "CRM",
    "UBER",
]


def yahoo_interval(interval):

    mapping = {
        "5m": "5m",
        "15m": "15m",
        "1h": "60m",
        "4h": "1h",
        "1d": "1d",
    }

    return mapping.get(
        interval,
        "15m"
    )


def yahoo_klines(
    symbol,
    interval="15m"
):

    symbol = str(
        symbol
    ).upper().strip()

    yahoo_bar = yahoo_interval(
        interval
    )

    if yahoo_bar in (
        "5m",
        "15m"
    ):

        range_value = "5d"

    elif yahoo_bar == "60m":

        range_value = "1mo"

    elif yahoo_bar == "1h":

        range_value = "3mo"

    else:

        range_value = "1y"

    url = (
        f"{YAHOO_CHART_URL}/"
        f"{symbol}"
    )

    response = HTTP.get(
        url,
        params={
            "interval": yahoo_bar,
            "range": range_value,
            "includePrePost": "false",
            "events": "div,splits"
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    chart = data.get(
        "chart",
        {}
    )

    error = chart.get(
        "error"
    )

    if error:

        raise RuntimeError(
            error.get(
                "description",
                "تعذر جلب بيانات السوق الأمريكي"
            )
        )

    rows = (
        chart.get(
            "result"
        )
        or []
    )

    if not rows:
        return []

    result = rows[0]

    timestamps = (
        result.get(
            "timestamp"
        )
        or []
    )

    quote = (
        result
        .get(
            "indicators",
            {}
        )
        .get(
            "quote",
            []
        )
    )

    if not quote:
        return []

    quote = quote[0]

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

    result_rows = []

    size = min(
        len(timestamps),
        len(opens),
        len(highs),
        len(lows),
        len(closes)
    )

    for i in range(size):

        try:

            if (
                opens[i] is None
                or highs[i] is None
                or lows[i] is None
                or closes[i] is None
            ):

                continue

            result_rows.append([
                int(
                    timestamps[i]
                ) * 1000,
                str(opens[i]),
                str(highs[i]),
                str(lows[i]),
                str(closes[i]),
                str(
                    volumes[i]
                    if i < len(volumes)
                    and volumes[i] is not None
                    else 0
                ),
                "0"
            ])

        except Exception:

            continue

    return result_rows


def us_market_signal(
    symbol,
    interval="15m"
):

    rows = yahoo_klines(
        symbol,
        interval
    )

    if len(rows) < 30:
        return None

    analysis = analyze_klines(
        rows
    )

    price = float(
        analysis["price"]
    )

    previous_close = None

    if len(rows) >= 2:

        previous_close = float(
            rows[-2][4]
        )

    if (
        previous_close
        and previous_close > 0
    ):

        change = (
            (
                price
                - previous_close
            )
            / previous_close
        ) * 100

    else:

        change = 0.0

    return {
        "symbol": symbol,
        "ticker": symbol,
        "name": symbol,
        "price": price,
        "change": change,
        "signal": analysis["signal"],
        "direction": analysis["direction"],
        "score": analysis["score"],
        "score10": analysis["score10"],
        "interval": interval,
        "entry": analysis["entry"],
        "tp1": analysis["tp1"],
        "tp2": analysis["tp2"],
        "tp3": analysis["tp3"],
        "tp": analysis["tp1"],
        "sl": analysis["sl"],
        "rsi": analysis["rsi"],
        "ema20": analysis["ema20"],
        "ema50": analysis["ema50"],
        "ema200": analysis["ema200"],
        "signalRank": signal_rank(
            analysis["signal"]
        ),
        "updatedAt": int(
            time.time()
        )
    }


@app.get("/api/usmarket/signals")
def usmarket_signals():

    interval = str(
        request.args.get(
            "interval",
            "15m"
        )
    ).lower()

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    now = time.time()

    with US_MARKET_CACHE_LOCK:

        if (
            US_MARKET_CACHE["results"]
            and
            US_MARKET_CACHE["interval"] == interval
            and
            now - US_MARKET_CACHE["ts"] < 60
        ):

            return jsonify({
                "ok": True,
                "source": "Yahoo Finance",
                "cached": True,
                "results": US_MARKET_CACHE["results"]
            })

    results = []

    def worker(symbol):

        try:

            return us_market_signal(
                symbol,
                interval
            )

        except Exception as e:

            print(
                f"US market {symbol} error:",
                e
            )

            return None

    with ThreadPoolExecutor(
        max_workers=4
    ) as executor:

        futures = [
            executor.submit(
                worker,
                symbol
            )
            for symbol in US_MARKET_SYMBOLS
        ]

        for future in as_completed(
            futures
        ):

            try:

                item = future.result()

                if item:

                    results.append(
                        item
                    )

            except Exception as e:

                print(
                    "US market worker error:",
                    e
                )

    results.sort(
        key=lambda x: (
            x["score"],
            abs(x["change"])
        ),
        reverse=True
    )

    results = results[:20]

    with US_MARKET_CACHE_LOCK:

        US_MARKET_CACHE["ts"] = now
        US_MARKET_CACHE["interval"] = interval
        US_MARKET_CACHE["results"] = results

    return jsonify({
        "ok": True,
        "source": "Yahoo Finance",
        "cached": False,
        "results": results
    })


# =========================================================
# SIGNAL RANK
# =========================================================

def signal_rank(signal):

    return {
        "شراء قوي": 5,
        "شراء": 4,
        "حيادي": 3,
        "بيع": 2,
        "بيع قوي": 1
    }.get(
        signal,
        0
    )


# =========================================================
# BASIC ROUTES
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
        "service": "mudarib-abo-saud",
        "source": MARKET_SOURCE,
        "time": int(time.time())
    })


# =========================================================
# AUTH
# =========================================================

@app.get("/api/auth/me")
def auth_me():

    user = current_user()

    if not user:

        return jsonify({
            "ok": False,
            "message": "غير مسجل"
        }), 401

    return jsonify({
        "ok": True,
        "user": user_json(user)
    })


@app.post("/api/auth/register")
def auth_register():

    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get(
            "name",
            ""
        )
    ).strip()

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    if len(name) < 2:

        return jsonify({
            "ok": False,
            "message": "اكتب الاسم بشكل صحيح"
        }), 400

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        email
    ):

        return jsonify({
            "ok": False,
            "message": "البريد الإلكتروني غير صحيح"
        }), 400

    if len(password) < 6:

        return jsonify({
            "ok": False,
            "message": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
        }), 400

    try:

        password_hash = hash_password(
            password
        )

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE email=%s
                    """,
                    (email,)
                )

                if cur.fetchone():

                    return jsonify({
                        "ok": False,
                        "message": "البريد الإلكتروني مستخدم مسبقًا"
                    }), 409

                cur.execute(
                    """
                    INSERT INTO users
                    (
                        name,
                        email,
                        password_hash
                    )
                    VALUES (%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        name,
                        email,
                        password_hash
                    )
                )

                user_id = cur.fetchone()[0]

            conn.commit()

        session.clear()

        session[
            "user_id"
        ] = user_id

        session.permanent = True

        user = user_row(
            user_id
        )

        return jsonify({
            "ok": True,
            "user": user_json(user),
            "message": "تم إنشاء الحساب بنجاح"
        })

    except Exception as e:

        print(
            "register error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": "تعذر إنشاء الحساب"
        }), 500


@app.post("/api/auth/login")
def auth_login():

    data = request.get_json(
        silent=True
    ) or {}

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        email,
                        plan,
                        plan_expires,
                        created_at,
                        password_hash
                    FROM users
                    WHERE email=%s
                    """,
                    (email,)
                )

                row = cur.fetchone()

        if not row:

            return jsonify({
                "ok": False,
                "message": "البريد أو كلمة المرور غير صحيحة"
            }), 401

        if not verify_password(
            password,
            row[6]
        ):

            return jsonify({
                "ok": False,
                "message": "البريد أو كلمة المرور غير صحيحة"
            }), 401

        session.clear()

        session[
            "user_id"
        ] = row[0]

        session.permanent = True

        return jsonify({
            "ok": True,
            "user": {
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "plan": row[3],
                "plan_expires": (
                    row[4].isoformat()
                    if row[4]
                    else None
                ),
                "created_at": (
                    row[5].isoformat()
                    if row[5]
                    else None
                )
            },
            "message": "تم تسجيل الدخول"
        })

    except Exception as e:

        print(
            "login error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": "تعذر تسجيل الدخول"
        }), 500


@app.post("/api/auth/logout")
def auth_logout():

    session.clear()

    return jsonify({
        "ok": True,
        "message": "تم تسجيل الخروج"
    })


# =========================================================
# ADMIN
# =========================================================

@app.get("/admin")
def admin_page():

    if not is_admin():

        return redirect("/")

    try:

        return render_template(
            "admin.html"
        )

    except Exception:

        return jsonify({
            "ok": True,
            "admin": True,
            "message": "صفحة الإدارة غير موجودة"
        })


@app.get("/api/admin/me")
def admin_me():

    return jsonify({
        "ok": True,
        "admin": is_admin()
    })


@app.post("/api/admin/login")
def admin_login():

    data = request.get_json(
        silent=True
    ) or {}

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

    if not ADMIN_PASSWORD:

        return jsonify({
            "ok": False,
            "message": "ADMIN_PASSWORD غير مضبوط في Render"
        }), 500

    if (
        hmac.compare_digest(
            username,
            ADMIN_USERNAME
        )
        and
        hmac.compare_digest(
            password,
            ADMIN_PASSWORD
        )
    ):

        session.clear()

        session[
            "admin"
        ] = True

        session.permanent = True

        return jsonify({
            "ok": True,
            "admin": True
        })

    return jsonify({
        "ok": False,
        "message": "بيانات الإدارة غير صحيحة"
    }), 401


@app.post("/api/admin/logout")
def admin_logout():

    session.pop(
        "admin",
        None
    )

    return jsonify({
        "ok": True
    })


@app.get("/api/admin/users")
@admin_required
def admin_users():

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        email,
                        plan,
                        plan_expires,
                        created_at
                    FROM users
                    ORDER BY id DESC
                    """
                )

                rows = cur.fetchall()

        users = []

        for row in rows:

            users.append({
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "plan": row[3],
                "plan_expires": (
                    row[4].isoformat()
                    if row[4]
                    else None
                ),
                "created_at": (
                    row[5].isoformat()
                    if row[5]
                    else None
                )
            })

        return jsonify({
            "ok": True,
            "users": users
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


@app.get("/api/admin/payments")
@admin_required
def admin_payments():

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        p.id,
                        p.user_id,
                        u.name,
                        u.email,
                        p.plan,
                        p.amount,
                        p.network,
                        p.txid,
                        p.status,
                        p.created_at,
                        p.reviewed_at
                    FROM payment_requests p
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
                "name": row[2],
                "email": row[3],
                "plan": row[4],
                "amount": float(row[5]),
                "network": row[6],
                "txid": row[7],
                "status": row[8],
                "created_at": (
                    row[9].isoformat()
                    if row[9]
                    else None
                ),
                "reviewed_at": (
                    row[10].isoformat()
                    if row[10]
                    else None
                )
            })

        return jsonify({
            "ok": True,
            "payments": payments
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


@app.post(
    "/api/admin/payment/<int:payment_id>/review"
)
@admin_required
def admin_review_payment(
    payment_id
):

    data = request.get_json(
        silent=True
    ) or {}

    status = str(
        data.get(
            "status",
            ""
        )
    ).lower()

    if status not in (
        "approved",
        "rejected"
    ):

        return jsonify({
            "ok": False,
            "message": "الحالة غير صحيحة"
        }), 400

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        user_id,
                        plan
                    FROM payment_requests
                    WHERE id=%s
                    """,
                    (payment_id,)
                )

                payment = cur.fetchone()

                if not payment:

                    return jsonify({
                        "ok": False,
                        "message": "طلب الدفع غير موجود"
                    }), 404

                user_id = payment[0]
                plan_key = payment[1]

                cur.execute(
                    """
                    UPDATE payment_requests
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

                    plan = PLANS.get(
                        plan_key
                    )

                    if plan:

                        cur.execute(
                            """
                            SELECT plan_expires
                            FROM users
                            WHERE id=%s
                            """,
                            (user_id,)
                        )

                        user_data = cur.fetchone()

                        now = datetime.now(
                            timezone.utc
                        )

                        current_expiry = (
                            user_data[0]
                            if user_data
                            else None
                        )

                        if (
                            current_expiry
                            and current_expiry > now
                        ):

                            start = current_expiry

                        else:

                            start = now

                        expires = (
                            start
                            + timedelta(
                                days=plan["days"]
                            )
                        )

                        cur.execute(
                            """
                            UPDATE users
                            SET
                                plan=%s,
                                plan_expires=%s
                            WHERE id=%s
                            """,
                            (
                                plan_key,
                                expires,
                                user_id
                            )
                        )

            conn.commit()

        return jsonify({
            "ok": True,
            "message": (
                "تم قبول الطلب"
                if status == "approved"
                else "تم رفض الطلب"
            )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# SUBSCRIPTIONS
# =========================================================

@app.get("/api/subscription/plans")
def subscription_plans():

    return jsonify({
        "ok": True,
        "address": PAYMENT_ADDRESS,
        "network": "TRC20",
        "plans": PLANS
    })


@app.get("/api/subscription/my")
@login_required
def subscription_my():

    user = current_user()

    if not user:

        return jsonify({
            "ok": False,
            "message": "يجب تسجيل الدخول"
        }), 401

    active = False

    expires = user[4]

    if expires:

        if expires.tzinfo is None:

            expires = expires.replace(
                tzinfo=timezone.utc
            )

        active = (
            expires
            > datetime.now(
                timezone.utc
            )
        )

    requests_list = []

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        plan,
                        amount,
                        status,
                        created_at
                    FROM payment_requests
                    WHERE user_id=%s
                    ORDER BY id DESC
                    LIMIT 30
                    """,
                    (user[0],)
                )

                rows = cur.fetchall()

        for row in rows:

            plan_data = PLANS.get(
                row[0],
                {}
            )

            requests_list.append({
                "plan": plan_data.get(
                    "name",
                    row[0]
                ),
                "amount": float(
                    row[1]
                ),
                "status": row[2],
                "created_at": (
                    row[3].isoformat()
                    if row[3]
                    else None
                )
            })

    except Exception as e:

        print(
            "subscription history error:",
            e
        )

    current_plan = PLANS.get(
        user[3]
    )

    return jsonify({
        "ok": True,
        "active": active,
        "plan": (
            current_plan["name"]
            if current_plan
            else "free"
        ),
        "expires": (
            expires.isoformat()
            if expires
            else None
        ),
        "requests": requests_list
    })


@app.post("/api/subscription/request")
@login_required
def subscription_request():

    data = request.get_json(
        silent=True
    ) or {}

    plan_key = str(
        data.get(
            "plan",
            ""
        )
    ).strip()

    txid = str(
        data.get(
            "txid",
            ""
        )
    ).strip()

    if plan_key not in PLANS:

        return jsonify({
            "ok": False,
            "message": "الباقة غير صحيحة"
        }), 400

    if len(txid) < 8:

        return jsonify({
            "ok": False,
            "message": "أدخل TXID صحيح"
        }), 400

    user = current_user()

    if not user:

        return jsonify({
            "ok": False,
            "message": "يجب تسجيل الدخول"
        }), 401

    plan = PLANS[
        plan_key
    ]

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM payment_requests
                    WHERE txid=%s
                    """,
                    (txid,)
                )

                if cur.fetchone():

                    return jsonify({
                        "ok": False,
                        "message": "رقم المعاملة مستخدم مسبقًا"
                    }), 409

                cur.execute(
                    """
                    INSERT INTO payment_requests
                    (
                        user_id,
                        plan,
                        amount,
                        network,
                        txid
                    )
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (
                        user[0],
                        plan_key,
                        plan["amount"],
                        "TRC20",
                        txid
                    )
                )

            conn.commit()

        return jsonify({
            "ok": True,
            "message": "تم إرسال طلب الاشتراك، بانتظار المراجعة"
        })

    except Exception as e:

        print(
            "subscription request error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": "تعذر إرسال الطلب"
        }), 500


# =========================================================
# SETTINGS
# =========================================================

@app.get("/api/settings")
def get_settings():

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT key,value
                    FROM settings
                    ORDER BY key
                    """
                )

                rows = cur.fetchall()

        return jsonify({
            "ok": True,
            "settings": {
                str(row[0]): str(row[1])
                for row in rows
            }
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


@app.post("/api/settings")
@admin_required
def save_settings():

    data = request.get_json(
        silent=True
    ) or {}

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                for key, value in data.items():

                    cur.execute(
                        """
                        INSERT INTO settings
                            (key,value)
                        VALUES
                            (%s,%s)
                        ON CONFLICT(key)
                        DO UPDATE SET
                            value=EXCLUDED.value
                        """,
                        (
                            str(key),
                            str(value)
                        )
                    )

            conn.commit()

        return jsonify({
            "ok": True
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# MARKET TEST
# =========================================================

@app.get("/api/binance/test")
def api_market_test():

    try:

        data = okx_get(
            "/api/v5/public/time",
            timeout=8
        )

        rows = data.get(
            "data",
            []
        )

        server_time = None

        if rows:

            try:

                server_time = int(
                    rows[0].get(
                        "ts",
                        0
                    )
                )

            except Exception:

                server_time = None

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "message": "مصدر السوق متصل ويعمل",
            "server_time": server_time
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "source": MARKET_SOURCE,
            "message": str(e)
        }), 502


@app.get("/api/okx/test")
def okx_test_direct():

    return api_market_test()


@app.get("/api/bybit/test")
def bybit_test_direct():

    return api_market_test()


# =========================================================
# MARKETS
# =========================================================

@app.get("/api/binance/markets")
def api_markets():

    try:

        symbols = market_symbols()

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "markets": symbols,
            "count": len(symbols)
        })

    except Exception as e:

        print(
            "markets error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/markets")
def okx_markets_direct():

    return api_markets()


@app.get("/api/bybit/markets")
def bybit_markets_direct():

    return api_markets()


# =========================================================
# PRICES
# =========================================================

@app.get("/api/binance/prices")
def api_prices():

    try:

        symbols = market_symbols()

        allowed = {
            x["symbol"]
            for x in symbols
        }

        items = []

        for item in ticker24():

            symbol = okx_to_internal(
                item.get(
                    "instId",
                    ""
                )
            )

            if symbol not in allowed:
                continue

            try:

                price = float(
                    item.get(
                        "last",
                        0
                    )
                )

                open_24h = float(
                    item.get(
                        "open24h",
                        0
                    )
                    or 0
                )

                if open_24h > 0:

                    change = (
                        (
                            price
                            - open_24h
                        )
                        / open_24h
                    ) * 100

                else:

                    change = 0.0

                volume = float(
                    item.get(
                        "volCcy24h",
                        0
                    )
                    or 0
                )

            except Exception:

                continue

            if price <= 0:
                continue

            items.append({
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": volume
            })

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "prices": items
        })

    except Exception as e:

        print(
            "prices error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/prices")
def okx_prices_direct():

    return api_prices()


@app.get("/api/bybit/prices")
def bybit_prices_direct():

    return api_prices()


# =========================================================
# SINGLE PRICE
# =========================================================

@app.get("/api/binance/price")
def api_price():

    symbol = str(
        request.args.get(
            "symbol",
            "BTCUSDT"
        )
    ).upper()

    if not re.match(
        r"^[A-Z0-9]+USDT$",
        symbol
    ):

        return jsonify({
            "ok": False,
            "message": "رمز العملة غير صحيح"
        }), 400

    try:

        inst_id = internal_to_okx(
            symbol
        )

        data = okx_get(
            "/api/v5/market/ticker",
            params={
                "instId": inst_id
            },
            timeout=8
        )

        rows = (
            data.get(
                "data",
                []
            )
        )

        if not rows:

            return jsonify({
                "ok": False,
                "message": "العملة غير موجودة"
            }), 404

        item = rows[0]

        price = float(
            item.get(
                "last",
                0
            )
        )

        open_24h = float(
            item.get(
                "open24h",
                0
            )
            or 0
        )

        if open_24h > 0:

            change = (
                (
                    price
                    - open_24h
                )
                / open_24h
            ) * 100

        else:

            change = 0.0

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "symbol": symbol,
            "price": price,
            "change": change,
            "volume": float(
                item.get(
                    "volCcy24h",
                    0
                )
                or 0
            )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/price")
def okx_price_direct():

    return api_price()


@app.get("/api/bybit/price")
def bybit_price_direct():

    return api_price()


# =========================================================
# KLINES
# =========================================================

@app.get("/api/binance/klines")
def api_klines():

    symbol = str(
        request.args.get(
            "symbol",
            "BTCUSDT"
        )
    ).upper()

    interval = str(
        request.args.get(
            "interval",
            "15m"
        )
    )

    try:

        limit = int(
            request.args.get(
                "limit",
                200
            )
        )

    except Exception:

        limit = 200

    limit = max(
        20,
        min(
            limit,
            300
        )
    )

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    try:

        rows = okx_klines(
            symbol,
            interval,
            limit
        )

        candles = []

        for row in rows:

            candles.append({
                "t": int(row[0]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5])
            })

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "symbol": symbol,
            "interval": interval,
            "candles": candles
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/klines")
def okx_klines_direct():

    return api_klines()


@app.get("/api/bybit/klines")
def bybit_klines_direct():

    return api_klines()


# =========================================================
# ANALYSIS
# =========================================================

@app.get("/api/binance/analysis")
def api_analysis():

    symbol = str(
        request.args.get(
            "symbol",
            "BTCUSDT"
        )
    ).upper()

    interval = str(
        request.args.get(
            "interval",
            "15m"
        )
    )

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    try:

        klines = okx_klines(
            symbol,
            interval,
            250
        )

        analysis = analyze_klines(
            klines
        )

        try:

            inst_id = internal_to_okx(
                symbol
            )

            data = okx_get(
                "/api/v5/market/ticker",
                params={
                    "instId": inst_id
                },
                timeout=6
            )

            rows = (
                data.get(
                    "data",
                    []
                )
            )

            if rows:

                item = rows[0]

                price = float(
                    item.get(
                        "last",
                        0
                    )
                )

                open_24h = float(
                    item.get(
                        "open24h",
                        0
                    )
                    or 0
                )

                if open_24h > 0:

                    analysis["change"] = (
                        (
                            price
                            - open_24h
                        )
                        / open_24h
                    ) * 100

                else:

                    analysis["change"] = 0.0

        except Exception:

            analysis[
                "change"
            ] = None

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "symbol": symbol,
            "interval": interval,
            "analysis": analysis
        })

    except Exception as e:

        print(
            f"analysis {symbol} error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/analysis")
def okx_analysis_direct():

    return api_analysis()


@app.get("/api/bybit/analysis")
def bybit_analysis_direct():

    return api_analysis()


# =========================================================
# SCANNER
# =========================================================

@app.get("/api/binance/scan")
def api_scan():

    interval = str(
        request.args.get(
            "interval",
            "15m"
        )
    )

    try:

        limit = int(
            request.args.get(
                "limit",
                40
            )
        )

    except Exception:

        limit = 40

    limit = max(
        1,
        min(
            limit,
            100
        )
    )

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    cache_key = (
        f"{interval}:{limit}"
    )

    now = time.time()

    with CACHE_LOCK:

        cached = SCAN_CACHE.get(
            cache_key
        )

        if (
            cached
            and
            now - cached["ts"] < 60
        ):

            return jsonify({
                "ok": True,
                "source": MARKET_SOURCE,
                "cached": True,
                "results": cached["results"]
            })

    try:

        markets = market_symbols()

        allowed = {
            x["symbol"]
            for x in markets
        }

        tickers = ticker24()

        candidates = []

        for ticker in tickers:

            symbol = okx_to_internal(
                ticker.get(
                    "instId",
                    ""
                )
            )

            if symbol not in allowed:
                continue

            try:

                price = float(
                    ticker.get(
                        "last",
                        0
                    )
                )

                if price <= 0:
                    continue

                open_24h = float(
                    ticker.get(
                        "open24h",
                        0
                    )
                    or 0
                )

                if open_24h > 0:

                    change = (
                        (
                            price
                            - open_24h
                        )
                        / open_24h
                    ) * 100

                else:

                    change = 0.0

                quote_volume = float(
                    ticker.get(
                        "volCcy24h",
                        0
                    )
                    or 0
                )

            except Exception:

                continue

            if quote_volume < 1_000_000:
                continue

            candidates.append({
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": quote_volume
            })

        candidates.sort(
            key=lambda x: x["volume"],
            reverse=True
        )

        candidates = candidates[
            :limit
        ]

        results = []

        def analyze_candidate(item):

            symbol = item[
                "symbol"
            ]

            try:

                klines = okx_klines(
                    symbol,
                    interval,
                    220
                )

                if len(klines) < 30:

                    return None

                analysis = analyze_klines(
                    klines
                )

                return {
                    "symbol": symbol,
                    "price": item["price"],
                    "change": item["change"],
                    "volume": item["volume"],
                    "signal": analysis["signal"],
                    "direction": analysis["direction"],
                    "score": analysis["score"],
                    "score10": analysis["score10"],
                    "interval": interval,
                    "entry": analysis["entry"],
                    "tp1": analysis["tp1"],
                    "tp2": analysis["tp2"],
                    "tp3": analysis["tp3"],
                    "sl": analysis["sl"],
                    "rsi": analysis["rsi"],
                    "ema20": analysis["ema20"],
                    "ema50": analysis["ema50"],
                    "ema200": analysis["ema200"],
                    "signalRank": signal_rank(
                        analysis["signal"]
                    ),
                    "updatedAt": int(
                        time.time()
                    )
                }

            except Exception as e:

                print(
                    f"scan {symbol} error:",
                    e
                )

                return None

        with ThreadPoolExecutor(
            max_workers=3
        ) as executor:

            futures = [
                executor.submit(
                    analyze_candidate,
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

                except Exception as e:

                    print(
                        "scanner future error:",
                        e
                    )

        results.sort(
            key=lambda x: (
                x["score"],
                x["volume"]
            ),
            reverse=True
        )

        results = results[
            :limit
        ]

        with CACHE_LOCK:

            SCAN_CACHE[
                cache_key
            ] = {
                "ts": now,
                "results": results
            }

        return jsonify({
            "ok": True,
            "source": MARKET_SOURCE,
            "cached": False,
            "results": results
        })

    except Exception as e:

        print(
            "scanner error:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 502


@app.get("/api/okx/scan")
def okx_scan_direct():

    return api_scan()


@app.get("/api/bybit/scan")
def bybit_scan_direct():

    return api_scan()


# =========================================================
# NEWS
# =========================================================

NEWS_URL = (
    "https://www.coindesk.com/"
    "arc/outboundfeeds/rss/"
)


def load_news_feed():

    try:

        response = HTTP.get(
            NEWS_URL,
            timeout=10
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        items = []

        for item in root.findall(
            ".//item"
        )[:30]:

            title = (
                item.findtext(
                    "title"
                )
                or ""
            ).strip()

            link = (
                item.findtext(
                    "link"
                )
                or ""
            ).strip()

            description = (
                item.findtext(
                    "description"
                )
                or ""
            ).strip()

            published = (
                item.findtext(
                    "pubDate"
                )
                or ""
            ).strip()

            if not title or not link:
                continue

            description = re.sub(
                r"<[^>]+>",
                "",
                description
            )

            description = html.unescape(
                description
            ).strip()

            items.append({
                "title": title,
                "link": link,
                "description": description[:500],
                "published": published,
                "source": "CoinDesk"
            })

        return items

    except Exception as e:

        print(
            "news error:",
            e
        )

        return []


@app.get("/api/news")
def api_news():

    now = time.time()

    with CACHE_LOCK:

        if (
            NEWS_CACHE["items"]
            and
            now - NEWS_CACHE["ts"] < 600
        ):

            return jsonify({
                "ok": True,
                "news": NEWS_CACHE["items"]
            })

    items = load_news_feed()

    with CACHE_LOCK:

        NEWS_CACHE[
            "ts"
        ] = now

        NEWS_CACHE[
            "items"
        ] = items

    return jsonify({
        "ok": True,
        "news": items
    })


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "ok": False,
            "message": "المسار غير موجود"
        }), 404

    try:

        return render_template(
            "index.html"
        )

    except Exception:

        return "Not Found", 404


@app.errorhandler(500)
def internal_error(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "ok": False,
            "message": "خطأ داخلي في الخادم"
        }), 500

    return (
        "Internal Server Error",
        500
    )


# =========================================================
# STARTUP
# =========================================================

try:

    init_db()

except Exception as e:

    print(
        "Startup database error:",
        e
    )


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
