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

import requests
import psycopg

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session
)


# ============================================================
# APP
# ============================================================

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


# ============================================================
# ENV
# ============================================================

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


# ============================================================
# PLANS
# ============================================================

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


# ============================================================
# BINANCE
# ============================================================

BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
]

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "Mudarib-Abo-Saud/2.0"
})


# ============================================================
# YAHOO FINANCE
# لا يحتاج Binance API Key
# ============================================================

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{}"
)

YAHOO_SCREENER_URL = (
    "https://query1.finance.yahoo.com/"
    "v1/finance/screener/predefined/saved"
)

US_MARKET_CACHE = {
    "ts": 0,
    "items": [],
    "symbols": [],
    "symbols_ts": 0
}

US_SYMBOLS_CACHE_SECONDS = 900
US_ANALYSIS_CACHE_SECONDS = 60

US_ANALYSIS_CACHE = {}

US_MARKET_LOCK = threading.Lock()


# ============================================================
# CACHE
# ============================================================

MARKET_CACHE = {
    "ts": 0,
    "symbols": []
}

SCAN_CACHE = {}

NEWS_CACHE = {
    "ts": 0,
    "items": []
}

ALPHA_CACHE = {
    "ts": 0,
    "items": []
}

FUTURES_CACHE = {
    "ts": 0,
    "items": []
}

CACHE_LOCK = threading.Lock()


# ============================================================
# CONSTANTS
# ============================================================

STABLE_BASES = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "USDE",
    "DAI",
    "USDP",
    "USDD"
}

INTERVALS = {
    "5m",
    "15m",
    "1h",
    "4h",
    "1d"
}


# ============================================================
# DATABASE
# ============================================================

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

        print(
            "PostgreSQL connected successfully"
        )

        print(
            "Database tables ready"
        )

    except Exception as e:

        print(
            "Database init error:",
            e
        )


# ============================================================
# PASSWORDS
# ============================================================

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
        f"pbkdf2${iterations}$"
        f"{salt.hex()}${digest.hex()}"
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


# ============================================================
# USERS
# ============================================================

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
        "plan_expires":
            row[4].isoformat()
            if row[4]
            else None,
        "created_at":
            row[5].isoformat()
            if row[5]
            else None,
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


# ============================================================
# BINANCE REQUEST
# ============================================================

def binance_get(
    path,
    params=None,
    timeout=4.0
):

    last_error = (
        "تعذر الاتصال بـ Binance"
    )

    for base in BINANCE_BASES:

        try:

            r = HTTP.get(
                base + path,
                params=params or {},
                timeout=timeout
            )

            if r.status_code == 200:
                return r.json()

            last_error = (
                f"Binance HTTP {r.status_code}"
            )

            if (
                r.status_code in (418, 429)
                or r.status_code >= 500
            ):
                continue

        except requests.RequestException as e:

            last_error = str(e)[:180]

            continue

    raise RuntimeError(
        last_error
    )


# ============================================================
# MARKET SYMBOLS
# ============================================================

def market_symbols():

    now = time.time()

    with CACHE_LOCK:

        if (
            MARKET_CACHE["symbols"]
            and
            now - MARKET_CACHE["ts"] < 900
        ):

            return MARKET_CACHE["symbols"]

    data = binance_get(
        "/api/v3/exchangeInfo",
        timeout=5
    )

    result = []

    for s in data.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol",
            ""
        )

        base = s.get(
            "baseAsset",
            ""
        )

        if s.get(
            "status"
        ) != "TRADING":

            continue

        if s.get(
            "quoteAsset"
        ) != "USDT":

            continue

        if s.get(
            "isSpotTradingAllowed"
        ) is False:

            continue

        if base in STABLE_BASES:

            continue

        if any(
            x in base
            for x in (
                "UP",
                "DOWN",
                "BULL",
                "BEAR"
            )
        ):

            continue

        result.append({
            "symbol": symbol,
            "baseAsset": base,
            "quoteAsset": "USDT"
        })

    with CACHE_LOCK:

        MARKET_CACHE.update({
            "ts": now,
            "symbols": result
        })

    return result


# ============================================================
# INDICATORS
# ============================================================

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

    for v in values[period:]:

        e = (
            v * k
            +
            e * (1 - k)
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

        d = (
            values[i]
            -
            values[i - 1]
        )

        gains.append(
            max(d, 0)
        )

        losses.append(
            max(-d, 0)
        )

    avg_gain = (
        sum(gains[:period])
        /
        period
    )

    avg_loss = (
        sum(losses[:period])
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            avg_gain * (period - 1)
            +
            gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    return 100 - (
        100 /
        (
            1 +
            avg_gain / avg_loss
        )
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

        prev = float(
            klines[i - 1][4]
        )

        trs.append(
            max(
                high - low,
                abs(high - prev),
                abs(low - prev)
            )
        )

    return (
        sum(trs[-period:])
        /
        min(
            period,
            len(trs)
        )
    )


# ============================================================
# MAIN ANALYSIS ENGINE
# ============================================================

def analyze_klines(
    klines
):

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
        -
        (e26 or 0)
    )

    macd_series = []

    for i in range(
        max(
            26,
            len(closes) - 80
        ),
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
        -
        (macd_signal or 0)
    )

    score = 50

    reasons = []

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

    elif direction == "sell":

        sl = price + risk

        tp1 = max(
            price -
            risk * 1.5,
            0
        )

        tp2 = max(
            price -
            risk * 2,
            0
        )

        tp3 = max(
            price -
            risk * 3,
            0
        )

    else:

        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

    support = min(
        lows[-20:]
    )

    resistance = max(
        highs[-20:]
    )

    candles = [
        {
            "t": int(x[0]),
            "o": float(x[1]),
            "h": float(x[2]),
            "l": float(x[3]),
            "c": float(x[4]),
            "v": float(x[5])
        }
        for x in klines[-100:]
    ]

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
        "candles": candles
    }


# ============================================================
# SIGNAL RANK
# ============================================================

def signal_rank(
    signal
):

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


# ============================================================
# FUTURES LEVERAGE
# ============================================================

def futures_leverage(
    score
):

    score = float(
        score or 0
    )

    if score >= 90:
        return 10

    if score >= 80:
        return 7

    if score >= 70:
        return 5

    return 0


# ============================================================
# FUTURES SIGNAL BUILDER
# ============================================================

def futures_signal_from_analysis(
    symbol,
    ticker,
    analysis
):

    score = float(
        analysis.get(
            "score",
            0
        )
    )

    direction = analysis.get(
        "direction",
        "neutral"
    )

    if direction not in (
        "buy",
        "sell"
    ):

        return None

    leverage = futures_leverage(
        score
    )

    if leverage <= 0:
        return None

    price = float(
        analysis.get(
            "price",
            0
        )
    )

    if price <= 0:
        return None

    atr_value = float(
        analysis.get("atr")
        or price * 0.01
    )

    risk = max(
        atr_value * 1.2,
        price * 0.008
    )

    if direction == "buy":

        side = "LONG"
        signal = "شراء قوي"

        entry = price

        sl = max(
            price - risk,
            0
        )

        tp1 = (
            price
            +
            risk * 1.5
        )

        tp2 = (
            price
            +
            risk * 2.2
        )

        tp3 = (
            price
            +
            risk * 3.0
        )

    else:

        side = "SHORT"
        signal = "بيع قوي"

        entry = price

        sl = price + risk

        tp1 = max(
            price -
            risk * 1.5,
            0
        )

        tp2 = max(
            price -
            risk * 2.2,
            0
        )

        tp3 = max(
            price -
            risk * 3.0,
            0
        )

    reasons = list(
        analysis.get(
            "reasons"
        ) or []
    )

    reasons.insert(
        0,
        f"تحليل فيوتشر متعدد الإشارات — قوة {round(score)}%"
    )

    reasons.append(
        f"الرافعة المقترحة {leverage}x"
    )

    return {
        "symbol": symbol,

        "side": side,
        "direction": direction,
        "signal": signal,

        "score": round(
            score,
            1
        ),

        "score10": round(
            score / 10,
            1
        ),

        "leverage": leverage,

        "price": price,
        "entry": entry,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "sl": sl,

        "rsi": analysis.get(
            "rsi"
        ),

        "ema20": analysis.get(
            "ema20"
        ),

        "ema50": analysis.get(
            "ema50"
        ),

        "ema200": analysis.get(
            "ema200"
        ),

        "macd": analysis.get(
            "macd"
        ),

        "macd_signal":
            analysis.get(
                "macd_signal"
            ),

        "macd_histogram":
            analysis.get(
                "macd_histogram"
            ),

        "atr": analysis.get(
            "atr"
        ),

        "volume": float(
            ticker.get(
                "quoteVolume",
                0
            )
        ),

        "change": float(
            ticker.get(
                "priceChangePercent",
                0
            )
        ),

        "interval": "15m",

        "reasons": reasons,

        "updatedAt": int(
            time.time() * 1000
        )
    }


# ============================================================
# ALPHA SIGNAL BUILDER
# ============================================================

def alpha_signal_from_analysis(
    symbol,
    ticker,
    analysis
):

    score = float(
        analysis.get(
            "score",
            0
        )
    )

    direction = analysis.get(
        "direction",
        "neutral"
    )

    if score < 80:
        return None

    if direction not in (
        "buy",
        "sell"
    ):
        return None

    reasons = list(
        analysis.get(
            "reasons"
        ) or []
    )

    reasons.insert(
        0,
        f"Alpha AI — قوة التحليل {round(score)}%"
    )

    return {
        "symbol": symbol,

        "signal": analysis.get(
            "signal"
        ),

        "direction": direction,

        "score": round(
            score,
            1
        ),

        "score10": round(
            score / 10,
            1
        ),

        "price": analysis.get(
            "price"
        ),

        "entry": analysis.get(
            "entry"
        ),

        "tp1": analysis.get(
            "tp1"
        ),

        "tp2": analysis.get(
            "tp2"
        ),

        "tp3": analysis.get(
            "tp3"
        ),

        "sl": analysis.get(
            "sl"
        ),

        "rsi": analysis.get(
            "rsi"
        ),

        "ema20": analysis.get(
            "ema20"
        ),

        "ema50": analysis.get(
            "ema50"
        ),

        "ema200": analysis.get(
            "ema200"
        ),

        "macd": analysis.get(
            "macd"
        ),

        "macd_signal":
            analysis.get(
                "macd_signal"
            ),

        "macd_histogram":
            analysis.get(
                "macd_histogram"
            ),

        "atr": analysis.get(
            "atr"
        ),

        "volume": float(
            ticker.get(
                "quoteVolume",
                0
            )
        ),

        "change": float(
            ticker.get(
                "priceChangePercent",
                0
            )
        ),

        "interval": "15m",

        "reasons": reasons,

        "updatedAt": int(
            time.time() * 1000
        )
    }


# ============================================================
# YAHOO REQUEST
# ============================================================

def yahoo_get_chart(
    symbol,
    interval="15m",
    range_value="5d"
):

    url = YAHOO_CHART_URL.format(
        symbol
    )

    r = HTTP.get(
        url,
        params={
            "interval": interval,
            "range": range_value,
            "events": "history",
            "includeAdjustedClose": "true"
        },
        timeout=8
    )

    r.raise_for_status()

    data = r.json()

    result = (
        data
        .get("chart", {})
        .get("result")
    )

    if not result:
        raise RuntimeError(
            f"لا توجد بيانات للسهم {symbol}"
        )

    return result[0]


def yahoo_candles(
    symbol,
    interval="15m",
    range_value="5d"
):

    result = yahoo_get_chart(
        symbol,
        interval,
        range_value
    )

    timestamps = result.get(
        "timestamp",
        []
    )

    quote = (
        result
        .get("indicators", {})
        .get("quote", [{}])[0]
    )

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

    candles = []

    for i, ts in enumerate(
        timestamps
    ):

        try:

            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]

            if (
                o is None
                or h is None
                or l is None
                or c is None
            ):

                continue

            v = (
                volumes[i]
                if i < len(volumes)
                and volumes[i] is not None
                else 0
            )

            candles.append([
                int(ts) * 1000,
                float(o),
                float(h),
                float(l),
                float(c),
                float(v)
            ])

        except Exception:

            continue

    if len(candles) < 50:

        raise RuntimeError(
            f"بيانات {symbol} غير كافية"
        )

    return candles


# ============================================================
# YAHOO SYMBOL DISCOVERY
# ============================================================

def yahoo_screener_page(
    start=0,
    count=250
):

    params = {
        "scrIds": "most_actives",
        "count": count,
        "start": start,
        "formatted": "false",
        "lang": "en-US",
        "region": "US"
    }

    r = HTTP.get(
        YAHOO_SCREENER_URL,
        params=params,
        timeout=10
    )

    r.raise_for_status()

    return r.json()


def discover_us_symbols():

    now = time.time()

    with US_MARKET_LOCK:

        cached = list(
            US_MARKET_CACHE["symbols"]
        )

        cached_ts = (
            US_MARKET_CACHE["symbols_ts"]
        )

    if (
        cached
        and
        now - cached_ts
        < US_SYMBOLS_CACHE_SECONDS
    ):

        return cached

    symbols = []

    try:

        # Yahoo Most Active يعيد الأسهم الأمريكية
        # على صفحات متعددة.
        #
        # نطلب عدة صفحات حتى لا نبقى على
        # قائمة ثابتة.

        page_size = 250

        for start in range(
            0,
            1000,
            page_size
        ):

            data = yahoo_screener_page(
                start=start,
                count=page_size
            )

            quotes = (
                data
                .get(
                    "finance",
                    {}
                )
                .get(
                    "result",
                    [{}]
                )[0]
                .get(
                    "quotes",
                    []
                )
            )

            if not quotes:
                break

            for q in quotes:

                symbol = str(
                    q.get(
                        "symbol",
                        ""
                    )
                ).upper().strip()

                if not symbol:
                    continue

                quote_type = str(
                    q.get(
                        "quoteType",
                        "EQUITY"
                    )
                ).upper()

                if quote_type not in (
                    "",
                    "EQUITY"
                ):

                    continue

                # نستبعد الأدوات التي ليست سهمًا عاديًا
                if any(
                    symbol.endswith(x)
                    for x in (
                        "=X",
                        "=F",
                        "-USD",
                        ".NS",
                        ".L",
                        ".DE"
                    )
                ):

                    continue

                symbols.append(
                    symbol
                )

            if len(quotes) < page_size:
                break

        # إزالة التكرار
        symbols = list(
            dict.fromkeys(
                symbols
            )
        )

        if symbols:

            with US_MARKET_LOCK:

                US_MARKET_CACHE[
                    "symbols"
                ] = symbols

                US_MARKET_CACHE[
                    "symbols_ts"
                ] = time.time()

            return symbols

    except Exception as e:

        print(
            "Yahoo symbol discovery error:",
            str(e)[:200]
        )

    # fallback بسيط في حال تعذر المصدر
    fallback = [
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
        "PLTR",
        "INTC",
        "MU",
        "QCOM",
        "COIN",
        "MSTR",
        "JPM",
        "BAC",
        "WMT",
        "COST",
        "SPY",
        "QQQ"
    ]

    return fallback


# ============================================================
# US MARKET SINGLE ANALYSIS
# ============================================================

def analyze_us_symbol(
    symbol
):

    cache_key = symbol

    now = time.time()

    with US_MARKET_LOCK:

        cached = US_ANALYSIS_CACHE.get(
            cache_key
        )

    if (
        cached
        and
        now - cached["ts"]
        < US_ANALYSIS_CACHE_SECONDS
    ):

        return cached["data"]

    candles = yahoo_candles(
        symbol,
        interval="15m",
        range_value="5d"
    )

    analysis = analyze_klines(
        candles
    )

    price = float(
        analysis["price"]
    )

    previous = float(
        candles[-2][4]
    )

    change = (
        (
            price - previous
        )
        /
        previous
        *
        100
        if previous
        else 0
    )

    item = {
        "symbol": symbol,
        "name": symbol,

        "price": price,
        "change": change,

        "signal": analysis[
            "signal"
        ],

        "direction": analysis[
            "direction"
        ],

        "score": analysis[
            "score"
        ],

        "score10": analysis[
            "score10"
        ],

        "entry": analysis[
            "entry"
        ],

        "tp1": analysis[
            "tp1"
        ],

        "tp2": analysis[
            "tp2"
        ],

        "tp3": analysis[
            "tp3"
        ],

        "sl": analysis[
            "sl"
        ],

        "rsi": analysis[
            "rsi"
        ],

        "ema20": analysis[
            "ema20"
        ],

        "ema50": analysis[
            "ema50"
        ],

        "ema200": analysis[
            "ema200"
        ],

        "macd": analysis[
            "macd"
        ],

        "macd_signal":
            analysis[
                "macd_signal"
            ],

        "macd_histogram":
            analysis[
                "macd_histogram"
            ],

        "atr": analysis[
            "atr"
        ],

        "interval": "15m",

        "reasons": analysis[
            "reasons"
        ],

        "updatedAt": int(
            time.time() * 1000
        )
    }

    with US_MARKET_LOCK:

        US_ANALYSIS_CACHE[
            cache_key
        ] = {
            "ts": time.time(),
            "data": item
        }

    return item


# ============================================================
# US MARKET SIGNALS
# ============================================================

@app.get(
    "/api/us-market/signals"
)
def us_market_signals():

    try:

        symbols = discover_us_symbols()

        # لا نضرب Yahoo بآلاف الطلبات
        # في نفس اللحظة.
        #
        # كل دورة نحلل مجموعة كبيرة من
        # الأسهم النشطة التي أعادها Yahoo.

        max_per_cycle = int(
            os.getenv(
                "US_MARKET_SCAN_LIMIT",
                "250"
            )
        )

        selected = symbols[
            :max_per_cycle
        ]

        results = []

        def worker(symbol):

            try:

                return analyze_us_symbol(
                    symbol
                )

            except Exception as e:

                print(
                    "US analysis error:",
                    symbol,
                    str(e)[:120]
                )

                return None

        with ThreadPoolExecutor(
            max_workers=8
        ) as pool:

            futures = [
                pool.submit(
                    worker,
                    symbol
                )
                for symbol in selected
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

                except Exception:
                    pass

        # الأقوى أولًا
        results.sort(
            key=lambda x: (
                x.get(
                    "score",
                    0
                ),
                abs(
                    x.get(
                        "change",
                        0
                    )
                )
            ),
            reverse=True
        )

        with US_MARKET_LOCK:

            US_MARKET_CACHE[
                "items"
            ] = results

            US_MARKET_CACHE[
                "ts"
            ] = time.time()

        return jsonify({
            "ok": True,

            "signals": results,

            "count": len(
                results
            ),

            "symbols_available":
                len(symbols),

            "symbols_scanned":
                len(selected),

            "cached": False,

            "source":
                "Yahoo Finance",

            "interval":
                "15m",

            "updatedAt":
                int(
                    time.time() * 1000
                )
        })

    except Exception as e:

        with US_MARKET_LOCK:

            cached = list(
                US_MARKET_CACHE[
                    "items"
                ]
            )

            symbols = list(
                US_MARKET_CACHE[
                    "symbols"
                ]
            )

        if cached:

            return jsonify({
                "ok": True,
                "signals": cached,
                "count": len(cached),
                "symbols_available":
                    len(symbols),
                "cached": True,
                "warning":
                    "تم عرض آخر تحليل أمريكي محفوظ",
                "source":
                    "Yahoo Finance"
            })

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# US MARKET SYMBOLS API
# ============================================================

@app.get(
    "/api/us-market/symbols"
)
def us_market_symbols():

    try:

        symbols = discover_us_symbols()

        return jsonify({
            "ok": True,
            "count": len(symbols),
            "symbols": symbols,
            "source":
                "Yahoo Finance"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# US MARKET SINGLE SYMBOL
# ============================================================

@app.get(
    "/api/us-market/analysis"
)
def us_market_analysis():

    symbol = (
        request.args.get(
            "symbol",
            ""
        )
        .upper()
        .strip()
    )

    if not symbol:

        return jsonify({
            "ok": False,
            "message":
                "symbol مطلوب"
        }), 400

    try:

        result = analyze_us_symbol(
            symbol
        )

        return jsonify({
            "ok": True,
            "analysis": result,
            "source":
                "Yahoo Finance"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "service":
            "mudarib-abo-saud",
        "time":
            int(time.time())
    })


# ============================================================
# AUTH REGISTER
# ============================================================

@app.post(
    "/api/auth/register"
)
def register():

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

    if (
        len(name) < 2
        or "@" not in email
        or len(password) < 6
    ):

        return jsonify({
            "ok": False,
            "message":
                "أدخل الاسم والبريد وكلمة مرور 6 أحرف على الأقل"
        }), 400

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO users(
                        name,
                        email,
                        password_hash
                    )
                    VALUES(%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        name,
                        email,
                        hash_password(
                            password
                        )
                    )
                )

                uid = cur.fetchone()[0]

            conn.commit()

        session.clear()

        session.permanent = True

        session[
            "user_id"
        ] = uid

        return jsonify({
            "ok": True,
            "user": user_json(
                user_row(uid)
            )
        })

    except psycopg.errors.UniqueViolation:

        return jsonify({
            "ok": False,
            "message":
                "البريد مستخدم مسبقًا"
        }), 409

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# AUTH LOGIN
# ============================================================

@app.post(
    "/api/auth/login"
)
def login():

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
                        password_hash
                    FROM users
                    WHERE email=%s
                    """,
                    (email,)
                )

                row = cur.fetchone()

        if (
            not row
            or not verify_password(
                password,
                row[1]
            )
        ):

            return jsonify({
                "ok": False,
                "message":
                    "بيانات الدخول غير صحيحة"
            }), 401

        session.clear()

        session.permanent = True

        session[
            "user_id"
        ] = row[0]

        return jsonify({
            "ok": True,
            "user": user_json(
                user_row(
                    row[0]
                )
            )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# AUTH LOGOUT
# ============================================================

@app.post(
    "/api/auth/logout"
)
def logout():

    session.pop(
        "user_id",
        None
    )

    return jsonify({
        "ok": True
    })


# ============================================================
# AUTH ME
# ============================================================

@app.get(
    "/api/auth/me"
)
def auth_me():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "غير مسجل دخول"
        }), 401

    return jsonify({
        "ok": True,
        "user": user_json(u)
    })


# ============================================================
# ADMIN PAGE
# ============================================================

@app.get("/admin")
def admin_page():

    return render_template(
        "admin.html"
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post(
    "/api/admin/login"
)
def admin_login():

    data = request.get_json(
        silent=True
    ) or {}

    if (
        hmac.compare_digest(
            str(
                data.get(
                    "username",
                    ""
                )
            ),
            ADMIN_USERNAME
        )
        and
        hmac.compare_digest(
            str(
                data.get(
                    "password",
                    ""
                )
            ),
            ADMIN_PASSWORD
        )
    ):

        session.clear()

        session.permanent = True

        session[
            "admin"
        ] = True

        return jsonify({
            "ok": True
        })

    return jsonify({
        "ok": False,
        "message":
            "بيانات الأدمن غير صحيحة"
    }), 401


# ============================================================
# ADMIN ME
# ============================================================

@app.get(
    "/api/admin/me"
)
def admin_me():

    return jsonify({
        "ok": True,
        "admin":
            is_admin()
    })


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.post(
    "/api/admin/logout"
)
def admin_logout():

    session.clear()

    return jsonify({
        "ok": True
    })


# ============================================================
# ADMIN STATS
# ============================================================

@app.get(
    "/api/admin/stats"
)
def admin_stats():

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT COUNT(*) FROM users"
                )

                users = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM users
                    WHERE plan <> 'free'
                    AND plan_expires > NOW()
                    """
                )

                active = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM payment_requests
                    WHERE status='pending'
                    """
                )

                pending = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COALESCE(
                        SUM(amount),
                        0
                    )
                    FROM payment_requests
                    WHERE status='approved'
                    """
                )

                revenue = float(
                    cur.fetchone()[0]
                    or 0
                )

        return jsonify({
            "ok": True,
            "users": users,
            "active": active,
            "pending": pending,
            "revenue": revenue
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# ADMIN USERS
# ============================================================

@app.get(
    "/api/admin/users"
)
def admin_users():

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

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

        return jsonify({
            "ok": True,
            "users": [
                user_json(r)
                for r in rows
            ]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# ADMIN PLAN
# ============================================================

@app.post(
    "/api/admin/users/<int:user_id>/plan"
)
def admin_plan(user_id):

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    plan = data.get(
        "plan",
        "free"
    )

    if plan not in {
        "free",
        "7d",
        "15d",
        "30d"
    }:

        return jsonify({
            "ok": False,
            "message":
                "خطة غير صحيحة"
        }), 400

    expires = None

    if plan in PLANS:

        expires = (
            datetime.now(
                timezone.utc
            )
            +
            timedelta(
                days=PLANS[
                    plan
                ]["days"]
            )
        )

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE users
                    SET
                        plan=%s,
                        plan_expires=%s
                    WHERE id=%s
                    """,
                    (
                        plan,
                        expires,
                        user_id
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


# ============================================================
# ADMIN PAYMENTS
# ============================================================

@app.get(
    "/api/admin/payments"
)
def admin_payments():

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

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
                    LIMIT 200
                    """
                )

                rows = cur.fetchall()

        return jsonify({
            "ok": True,
            "payments": [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "name": r[2],
                    "email": r[3],
                    "plan": r[4],
                    "amount":
                        float(r[5]),
                    "network": r[6],
                    "txid": r[7],
                    "status": r[8],
                    "created_at":
                        r[9].isoformat(),
                    "reviewed_at":
                        r[10].isoformat()
                        if r[10]
                        else None
                }
                for r in rows
            ]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# REVIEW PAYMENT
# ============================================================

@app.post(
    "/api/admin/payments/<int:payment_id>/review"
)
def review_payment(
    payment_id
):

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    action = data.get(
        "action"
    )

    if action not in {
        "approve",
        "reject"
    }:

        return jsonify({
            "ok": False,
            "message":
                "إجراء غير صحيح"
        }), 400

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        user_id,
                        plan,
                        status
                    FROM payment_requests
                    WHERE id=%s
                    FOR UPDATE
                    """,
                    (payment_id,)
                )

                p = cur.fetchone()

                if not p:

                    return jsonify({
                        "ok": False,
                        "message":
                            "الطلب غير موجود"
                    }), 404

                if p[2] != "pending":

                    return jsonify({
                        "ok": False,
                        "message":
                            "تمت مراجعة الطلب مسبقًا"
                    }), 409

                if action == "approve":

                    days = PLANS[
                        p[1]
                    ]["days"]

                    cur.execute(
                        """
                        SELECT plan_expires
                        FROM users
                        WHERE id=%s
                        FOR UPDATE
                        """,
                        (p[0],)
                    )

                    old = cur.fetchone()[0]

                    base = (
                        max(
                            old,
                            datetime.now(
                                timezone.utc
                            )
                        )
                        if old
                        else
                        datetime.now(
                            timezone.utc
                        )
                    )

                    expires = (
                        base
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
                            plan_expires=%s
                        WHERE id=%s
                        """,
                        (
                            p[1],
                            expires,
                            p[0]
                        )
                    )

                    status = "approved"

                else:

                    status = "rejected"

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

            conn.commit()

        return jsonify({
            "ok": True,
            "status": status
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# SUBSCRIPTION PLANS
# ============================================================

@app.get(
    "/api/subscription/plans"
)
def subscription_plans():

    return jsonify({
        "ok": True,
        "network": "TRC20",
        "address":
            PAYMENT_ADDRESS,
        "plans": PLANS
    })


# ============================================================
# SUBSCRIPTION REQUEST
# ============================================================

@app.post(
    "/api/subscription/request"
)
def subscription_request():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "سجل دخول أولاً"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    plan = data.get(
        "plan"
    )

    txid = str(
        data.get(
            "txid",
            ""
        )
    ).strip()

    if plan not in PLANS:

        return jsonify({
            "ok": False,
            "message":
                "اختر باقة صحيحة"
        }), 400

    if (
        len(txid) < 8
        or len(txid) > 200
    ):

        return jsonify({
            "ok": False,
            "message":
                "أدخل TXID صحيح"
        }), 400

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
                        "message":
                            "TXID مستخدم مسبقًا"
                    }), 409

                cur.execute(
                    """
                    INSERT INTO payment_requests(
                        user_id,
                        plan,
                        amount,
                        network,
                        txid
                    )
                    VALUES(
                        %s,%s,%s,'TRC20',%s
                    )
                    RETURNING id
                    """,
                    (
                        u[0],
                        plan,
                        PLANS[
                            plan
                        ]["amount"],
                        txid
                    )
                )

                pid = cur.fetchone()[0]

            conn.commit()

        return jsonify({
            "ok": True,
            "message":
                "تم إرسال طلب الدفع للمراجعة",
            "id": pid
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# MY SUBSCRIPTION
# ============================================================

@app.get(
    "/api/subscription/my"
)
def my_subscription():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "غير مسجل دخول"
        }), 401

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        plan,
                        amount,
                        status,
                        txid,
                        created_at,
                        reviewed_at
                    FROM payment_requests
                    WHERE user_id=%s
                    ORDER BY id DESC
                    LIMIT 10
                    """,
                    (u[0],)
                )

                rows = cur.fetchall()

        active = (
            u[3] != "free"
            and u[4]
            and u[4] >
                datetime.now(
                    timezone.utc
                )
        )

        return jsonify({
            "ok": True,
            "active": bool(active),
            "plan": u[3],
            "expires":
                u[4].isoformat()
                if u[4]
                else None,

            "requests": [
                {
                    "id": r[0],
                    "plan": r[1],
                    "amount":
                        float(r[2]),
                    "status": r[3],
                    "txid": r[4],
                    "created_at":
                        r[5].isoformat(),
                    "reviewed_at":
                        r[6].isoformat()
                        if r[6]
                        else None
                }
                for r in rows
            ]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# SETTINGS GET
# ============================================================

@app.get(
    "/api/settings"
)
def get_settings():

    u = current_user()

    key = (
        f"user:{u[0]}:settings"
        if u
        else
        "public:settings"
    )

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT value
                    FROM settings
                    WHERE key=%s
                    """,
                    (key,)
                )

                row = cur.fetchone()

        return jsonify({
            "ok": True,
            "settings":
                json.loads(
                    row[0]
                )
                if row
                else {}
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# ============================================================
# SETTINGS SAVE
# ============================================================

@app.post(
    "/api/settings"
)
def save_settings():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "سجل دخول أولاً"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    key = (
        f"user:{u[0]}:settings"
    )

    value = json.dumps(
        data,
        ensure_ascii=False
    )

    try:

        with db_conn() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO settings(
                        key,
                        value
                    )
                    VALUES(%s,%s)

                    ON CONFLICT(key)
                    DO UPDATE SET
                        value=EXCLUDED.value
                    """,
                    (
                        key,
                        value
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


# ============================================================
# BINANCE TEST
# ============================================================

@app.get(
    "/api/binance/test"
)
def binance_test():

    try:

        binance_get(
            "/api/v3/ping",
            timeout=3
        )

        return jsonify({
            "ok": True,
            "binance": True
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# BINANCE MARKETS
# ============================================================

@app.get(
    "/api/binance/markets"
)
def markets():

    try:

        return jsonify({
            "ok": True,
            "symbols":
                market_symbols()
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# BINANCE PRICES
# ============================================================

@app.get(
    "/api/binance/prices"
)
def prices():

    try:

        tick = ticker24()

        wanted = {
            x.strip().upper()
            for x in request.args.get(
                "symbols",
                ""
            ).split(",")
            if x.strip()
        }

        out = []

        for t in tick:

            if t.get(
                "symbol"
            ) in wanted:

                out.append({
                    "symbol":
                        t["symbol"],

                    "price":
                        float(
                            t.get(
                                "lastPrice",
                                0
                            )
                        ),

                    "change":
                        float(
                            t.get(
                                "priceChangePercent",
                                0
                            )
                        ),

                    "volume":
                        float(
                            t.get(
                                "quoteVolume",
                                0
                            )
                        )
                })

        return jsonify({
            "ok": True,
            "prices": out
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# BINANCE PRICE
# ============================================================

@app.get(
    "/api/binance/price"
)
def price():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    if not symbol:

        return jsonify({
            "ok": False,
            "message":
                "symbol مطلوب"
        }), 400

    try:

        t = binance_get(
            "/api/v3/ticker/24hr",
            {
                "symbol":
                    symbol
            },
            timeout=3
        )

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "price":
                float(
                    t["lastPrice"]
                ),
            "change":
                float(
                    t.get(
                        "priceChangePercent",
                        0
                    )
                ),
            "volume":
                float(
                    t.get(
                        "quoteVolume",
                        0
                    )
                )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# KLINES
# ============================================================

@app.get(
    "/api/binance/klines"
)
def klines():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if (
        not symbol
        or interval not in INTERVALS
    ):

        return jsonify({
            "ok": False,
            "message":
                "بيانات غير صحيحة"
        }), 400

    try:

        data = binance_get(
            "/api/v3/klines",
            {
                "symbol":
                    symbol,

                "interval":
                    interval,

                "limit":
                    210
            },
            timeout=4
        )

        return jsonify({
            "ok": True,
            "klines": data
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# SINGLE ANALYSIS
# ============================================================

@app.get(
    "/api/binance/analysis"
)
def analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message":
                "فريم غير صحيح"
        }), 400

    try:

        k = binance_get(
            "/api/v3/klines",
            {
                "symbol":
                    symbol,

                "interval":
                    interval,

                "limit":
                    230
            },
            timeout=5
        )

        a = analyze_klines(
            k
        )

        a["symbol"] = symbol

        a["interval"] = interval

        return jsonify({
            "ok": True,
            "analysis": a
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# SPOT SCANNER
# ============================================================

@app.get(
    "/api/binance/scan"
)
def scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    requested = max(
        5,
        min(
            int(
                request.args.get(
                    "limit",
                    40
                )
            ),
            100
        )
    )

    if interval not in INTERVALS:

        return jsonify({
            "ok": False,
            "message":
                "فريم غير صحيح"
        }), 400

    now = time.time()

    with CACHE_LOCK:

        cached = SCAN_CACHE.get(
            interval
        )

    if (
        cached
        and
        now - cached["ts"] < 45
    ):

        payload = dict(
            cached["payload"]
        )

        payload[
            "cached"
        ] = True

        return jsonify(
            payload
        )

    try:

        markets = {
            x["symbol"]
            for x in market_symbols()
        }

        tickers = ticker24()

        candidates = []

        for t in tickers:

            s = t.get(
                "symbol",
                ""
            )

            if s not in markets:
                continue

            try:

                qv = float(
                    t.get(
                        "quoteVolume",
                        0
                    )
                )

            except Exception:

                qv = 0

            if qv < 1_000_000:
                continue

            candidates.append(
                (
                    qv,
                    t
                )
            )

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        cap = min(
            requested,
            40
        )

        selected = candidates[
            :cap
        ]

        results = []

        def worker(item):

            qv, t = item

            symbol = t[
                "symbol"
            ]

            k = binance_get(
                "/api/v3/klines",
                {
                    "symbol":
                        symbol,

                    "interval":
                        interval,

                    "limit":
                        210
                },
                timeout=3.5
            )

            a = analyze_klines(
                k
            )

            return {
                "symbol":
                    symbol,

                "price":
                    float(
                        t.get(
                            "lastPrice",
                            a["price"]
                        )
                    ),

                "change":
                    float(
                        t.get(
                            "priceChangePercent",
                            0
                        )
                    ),

                "volume":
                    qv,

                "signal":
                    a["signal"],

                "direction":
                    a["direction"],

                "score":
                    a["score"],

                "score10":
                    a["score10"],

                "interval":
                    interval,

                "entry":
                    a["entry"],

                "tp1":
                    a["tp1"],

                "tp2":
                    a["tp2"],

                "tp3":
                    a["tp3"],

                "sl":
                    a["sl"],

                "signalRank":
                    signal_rank(
                        a["signal"]
                    ),

                "updatedAt":
                    int(
                        time.time()
                        * 1000
                    )
            }

        with ThreadPoolExecutor(
            max_workers=6
        ) as pool:

            futures = [
                pool.submit(
                    worker,
                    x
                )
                for x in selected
            ]

            for f in as_completed(
                futures
            ):

                try:

                    results.append(
                        f.result()
                    )

                except Exception:

                    pass

        results.sort(
            key=lambda x:
                x["volume"],
            reverse=True
        )

        if not results:

            raise RuntimeError(
                "تعذر جلب بيانات العملات الآن"
            )

        payload = {
            "ok": True,
            "interval": interval,
            "count":
                len(results),
            "requested":
                requested,
            "scanned":
                len(selected),
            "results":
                results,
            "cached":
                False
        }

        with CACHE_LOCK:

            SCAN_CACHE[
                interval
            ] = {
                "ts":
                    time.time(),

                "payload":
                    payload
            }

        return jsonify(
            payload
        )

    except Exception as e:

        with CACHE_LOCK:

            cached = SCAN_CACHE.get(
                interval
            )

        if cached:

            payload = dict(
                cached["payload"]
            )

            payload[
                "cached"
            ] = True

            payload[
                "warning"
            ] = (
                "تم عرض آخر نتيجة محفوظة"
            )

            return jsonify(
                payload
            )

        return jsonify({
            "ok": False,
            "message":
                str(e)
        }), 503


# ============================================================
# ALPHA SIGNALS
# ============================================================

@app.get(
    "/api/alpha/signals"
)
def alpha_signals():

    now = time.time()

    with CACHE_LOCK:

        cached_items = list(
            ALPHA_CACHE[
                "items"
            ]
        )

        cached_ts = (
            ALPHA_CACHE[
                "ts"
            ]
        )

    if (
        cached_items
        and
        now - cached_ts < 60
    ):

        return jsonify({
            "ok": True,
            "signals":
                cached_items,
            "count":
                len(cached_items),
            "cached":
                True
        })

    try:

        markets = {
            x["symbol"]
            for x in market_symbols()
        }

        tickers = ticker24()

        candidates = []

        for ticker in tickers:

            symbol = ticker.get(
                "symbol",
                ""
            )

            if symbol not in markets:
                continue

            try:

                volume = float(
                    ticker.get(
                        "quoteVolume",
                        0
                    )
                )

            except Exception:

                volume = 0

            if volume < 1_000_000:
                continue

            candidates.append(
                (
                    volume,
                    ticker
                )
            )

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        selected = candidates[
            :40
        ]

        results = []

        def worker(item):

            volume, ticker = item

            symbol = ticker[
                "symbol"
            ]

            try:

                klines_data = binance_get(
                    "/api/v3/klines",
                    {
                        "symbol":
                            symbol,

                        "interval":
                            "15m",

                        "limit":
                            230
                    },
                    timeout=4
                )

                analysis_data = (
                    analyze_klines(
                        klines_data
                    )
                )

                return (
                    alpha_signal_from_analysis(
                        symbol,
                        ticker,
                        analysis_data
                    )
                )

            except Exception:

                return None

        with ThreadPoolExecutor(
            max_workers=6
        ) as pool:

            futures = [
                pool.submit(
                    worker,
                    item
                )
                for item in selected
            ]

            for future in as_completed(
                futures
            ):

                try:

                    result = (
                        future.result()
                    )

                    if result:
                        results.append(
                            result
                        )

                except Exception:

                    pass

        results.sort(
            key=lambda x: (
                x["score"],
                x["volume"]
            ),
            reverse=True
        )

        results = results[
            :15
        ]

        with CACHE_LOCK:

            ALPHA_CACHE.update({
                "ts":
                    time.time(),

                "items":
                    results
            })

        return jsonify({
            "ok": True,
            "signals":
                results,
            "count":
                len(results),
            "cached":
                False,
            "updatedAt":
                int(
                    time.time()
                    * 1000
                )
        })

    except Exception as e:

        with CACHE_LOCK:

            cached_items = list(
                ALPHA_CACHE[
                    "items"
                ]
            )

        if cached_items:

            return jsonify({
                "ok": True,
                "signals":
                    cached_items,
                "count":
                    len(cached_items),
                "cached":
                    True,
                "warning":
                    "تم عرض آخر صفقات Alpha محفوظة"
            })

        return jsonify({
            "ok": False,
            "message":
                str(e)
        }), 503


# ============================================================
# FUTURES SIGNALS
# ============================================================

@app.get(
    "/api/futures/signals"
)
def futures_signals():

    now = time.time()

    with CACHE_LOCK:

        cached_items = list(
            FUTURES_CACHE[
                "items"
            ]
        )

        cached_ts = (
            FUTURES_CACHE[
                "ts"
            ]
        )

    if (
        cached_items
        and
        now - cached_ts < 60
    ):

        return jsonify({
            "ok": True,
            "signals":
                cached_items,
            "count":
                len(cached_items),
            "cached":
                True
        })

    try:

        markets = {
            x["symbol"]
            for x in market_symbols()
        }

        tickers = ticker24()

        candidates = []

        for ticker in tickers:

            symbol = ticker.get(
                "symbol",
                ""
            )

            if symbol not in markets:
                continue

            try:

                volume = float(
                    ticker.get(
                        "quoteVolume",
                        0
                    )
                )

            except Exception:

                volume = 0

            if volume < 1_000_000:
                continue

            candidates.append(
                (
                    volume,
                    ticker
                )
            )

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        selected = candidates[
            :40
        ]

        results = []

        def worker(item):

            volume, ticker = item

            symbol = ticker[
                "symbol"
            ]

            try:

                klines_data = binance_get(
                    "/api/v3/klines",
                    {
                        "symbol":
                            symbol,

                        "interval":
                            "15m",

                        "limit":
                            230
                    },
                    timeout=4
                )

                analysis_data = (
                    analyze_klines(
                        klines_data
                    )
                )

                return (
                    futures_signal_from_analysis(
                        symbol,
                        ticker,
                        analysis_data
                    )
                )

            except Exception:

                return None

        with ThreadPoolExecutor(
            max_workers=6
        ) as pool:

            futures = [
                pool.submit(
                    worker,
                    item
                )
                for item in selected
            ]

            for future in as_completed(
                futures
            ):

                try:

                    result = (
                        future.result()
                    )

                    if result:
                        results.append(
                            result
                        )

                except Exception:

                    pass

        results.sort(
            key=lambda x: (
                x["score"],
                x["volume"]
            ),
            reverse=True
        )

        results = results[
            :15
        ]

        with CACHE_LOCK:

            FUTURES_CACHE.update({
                "ts":
                    time.time(),

                "items":
                    results
            })

        return jsonify({
            "ok": True,
            "signals":
                results,
            "count":
                len(results),
            "cached":
                False,
            "updatedAt":
                int(
                    time.time()
                    * 1000
                )
        })

    except Exception as e:

        with CACHE_LOCK:

            cached_items = list(
                FUTURES_CACHE[
                    "items"
                ]
            )

        if cached_items:

            return jsonify({
                "ok": True,
                "signals":
                    cached_items,
                "count":
                    len(cached_items),
                "cached":
                    True,
                "warning":
                    "تم عرض آخر صفقات الفيوتشر محفوظة"
            })

        return jsonify({
            "ok": False,
            "message":
                str(e)
        }), 503


# ============================================================
# 24H TICKER
# ============================================================

def ticker24():

    return binance_get(
        "/api/v3/ticker/24hr",
        timeout=5
    )


# ============================================================
# NEWS
# ============================================================

def clean_html(
    text
):

    text = re.sub(
        r"<[^>]+>",
        " ",
        text or ""
    )

    return re.sub(
        r"\s+",
        " ",
        html.unescape(
            text
        )
    ).strip()


@app.get(
    "/api/news"
)
def news():

    now = time.time()

    with CACHE_LOCK:

        if (
            NEWS_CACHE["items"]
            and
            now - NEWS_CACHE["ts"]
            < 600
        ):

            return jsonify({
                "ok": True,
                "news":
                    NEWS_CACHE[
                        "items"
                    ],
                "cached":
                    True
            })

    feeds = [
        (
            "CoinDesk",
            "https://www.coindesk.com/arc/outboundfeeds/rss/"
        )
    ]

    items = []

    for source, url in feeds:

        try:

            r = HTTP.get(
                url,
                timeout=5
            )

            r.raise_for_status()

            root = ET.fromstring(
                r.content
            )

            for item in root.findall(
                ".//item"
            )[:12]:

                title = clean_html(
                    item.findtext(
                        "title"
                    )
                )

                link = (
                    item.findtext(
                        "link"
                    )
                    or ""
                )

                pub = (
                    item.findtext(
                        "pubDate"
                    )
                    or ""
                )

                desc = clean_html(
                    item.findtext(
                        "description"
                    )
                )

                if title and link:

                    items.append({
                        "title":
                            title,

                        "link":
                            link,

                        "source":
                            source,

                        "published":
                            pub,

                        "description":
                            desc[:220]
                    })

        except Exception:

            pass

    with CACHE_LOCK:

        NEWS_CACHE.update({
            "ts":
                time.time(),

            "items":
                items[:12]
        })

    return jsonify({
        "ok": True,
        "news":
            items[:12],
        "cached":
            False,
        "message":
            None
            if items
            else
            "تعذر جلب الأخبار الآن"
    })


# ============================================================
# START DATABASE
# ============================================================

init_db()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",

        port=int(
            os.getenv(
                "PORT",
                10000
            )
        ),

        debug=False
    )
