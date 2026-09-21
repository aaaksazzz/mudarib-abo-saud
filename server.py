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
    session,
    redirect,
    url_for,
)


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

# مهم جداً:
# لا تستخدم مفتاح عشوائي يتغير مع كل Restart في Render
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "ضع SECRET_KEY ثابت وقوي بطول 32 حرفاً أو أكثر في Render Environment."
    )

app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_NAME="mudarib_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") != "0",
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_PATH="/",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# ============================================================
# ENV
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "aaaksazzz").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()

TRC20_ADDRESS = os.getenv(
    "TRC20_ADDRESS",
    "ضع_عنوان_TRON_TRX_USDT_هنا"
).strip()

PORT = int(os.getenv("PORT", "10000"))


# ============================================================
# BINANCE
# ============================================================

SPOT_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
]

FUTURES_BASES = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]

HTTP_TIMEOUT = 12

session_http = requests.Session()
session_http.headers.update({
    "User-Agent": "Mudarib-Abo-Saud/1.0"
})


# ============================================================
# CACHE
# ============================================================

CACHE = {
    "markets": {
        "time": 0,
        "data": []
    },
    "spot_scan": {
        "time": 0,
        "data": []
    },
    "futures_scan": {
        "time": 0,
        "data": []
    },
    "news": {
        "time": 0,
        "data": []
    }
}

CACHE_LOCK = threading.Lock()


# ============================================================
# DATABASE
# ============================================================

DB_LOCK = threading.Lock()


def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL غير موجود في Render.")

    return psycopg.connect(
        DATABASE_URL,
        autocommit=True,
    )


def init_db():
    with DB_LOCK:
        with db() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        is_premium BOOLEAN DEFAULT FALSE,
                        premium_until TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_requests (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        plan TEXT NOT NULL,
                        amount NUMERIC NOT NULL,
                        method TEXT NOT NULL,
                        txid TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        reviewed_at TIMESTAMPTZ NULL
                    )
                """)


# ============================================================
# PASSWORD
# ============================================================

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    rounds = 240_000

    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )

    return (
        f"pbkdf2_sha256${rounds}$"
        f"{salt.hex()}$"
        f"{key.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, key_hex = stored.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        rounds = int(rounds)

        salt = bytes.fromhex(salt_hex)

        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            rounds,
        )

        return hmac.compare_digest(
            key.hex(),
            key_hex,
        )

    except Exception:
        return False


# ============================================================
# USER
# ============================================================

def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id,
                        name,
                        email,
                        is_active,
                        is_premium,
                        premium_until,
                        created_at
                    FROM users
                    WHERE id=%s
                """, (user_id,))

                row = cur.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "email": row[2],
            "is_active": row[3],
            "is_premium": row[4],
            "premium_until": (
                row[5].isoformat()
                if row[5]
                else None
            ),
            "created_at": (
                row[6].isoformat()
                if row[6]
                else None
            ),
        }

    except Exception as e:
        print("USER ERROR:", e)
        return None


# ============================================================
# ADMIN
# ============================================================

def create_admin_token(username):
    timestamp = int(time.time())

    raw = f"{username}:{timestamp}"

    signature = hmac.new(
        SECRET_KEY.encode(),
        raw.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"{username}:{timestamp}:{signature}"


def verify_admin_token(token):
    if not token:
        return False

    try:
        username, timestamp, signature = token.split(":", 2)

        timestamp = int(timestamp)

        if time.time() - timestamp > 86400:
            return False

        raw = f"{username}:{timestamp}"

        expected = hmac.new(
            SECRET_KEY.encode(),
            raw.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return False

        return hmac.compare_digest(
            username,
            ADMIN_USERNAME,
        )

    except Exception:
        return False


def is_admin():
    if session.get("admin") is True:
        return True

    token = request.headers.get("X-Admin-Token", "").strip()

    if token and verify_admin_token(token):
        return True

    auth = request.headers.get("Authorization", "").strip()

    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()

        if verify_admin_token(token):
            return True

    return False


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return jsonify({
                "ok": False,
                "error": "غير مصرح"
            }), 401

        return fn(*args, **kwargs)

    return wrapper


# ============================================================
# PLANS
# ============================================================

PLANS = {
    "7d": {
        "name": "7 أيام",
        "days": 7,
        "amount": 10
    },
    "15d": {
        "name": "15 يوم",
        "days": 15,
        "amount": 20
    },
    "30d": {
        "name": "30 يوم",
        "days": 30,
        "amount": 30
    },
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value, max_len=500):
    if value is None:
        return ""

    value = html.unescape(str(value))

    value = re.sub(
        r"<[^>]+>",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()[:max_len]


def now_utc():
    return datetime.now(timezone.utc)


def safe_float(value, default=0):
    try:
        return float(value)
    except Exception:
        return default


def binance_get(path, params=None, futures=False):
    bases = FUTURES_BASES if futures else SPOT_BASES

    last_error = None

    for base in bases:
        try:
            r = session_http.get(
                base + path,
                params=params or {},
                timeout=HTTP_TIMEOUT,
            )

            if r.status_code == 200:
                return r.json()

            last_error = f"{r.status_code}: {r.text[:300]}"

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"Binance API failed: {last_error}"
    )


# ============================================================
# TECHNICAL ANALYSIS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def calculate_atr(klines, period=14):
    if len(klines) < period + 1:
        return 0

    trs = []

    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        previous_close = float(klines[i - 1][4])

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        trs.append(tr)

    if len(trs) < period:
        return 0

    return sum(trs[-period:]) / period


def analyze_klines(klines):
    if not klines or len(klines) < 50:
        return {
            "signal": "محايد",
            "score": 50,
            "price": 0,
            "ema20": 0,
            "ema50": 0,
            "ema200": 0,
            "rsi": 50,
            "atr": 0,
        }

    closes = [
        float(x[4])
        for x in klines
    ]

    price = closes[-1]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = (
        ema(closes, 200)
        if len(closes) >= 200
        else ema(closes, min(100, len(closes)))
    )

    r = rsi(closes, 14)

    atr_value = calculate_atr(klines)

    score = 50

    if e20 and price > e20:
        score += 10
    else:
        score -= 10

    if e50 and price > e50:
        score += 10
    else:
        score -= 10

    if e200 and price > e200:
        score += 15
    else:
        score -= 15

    if r >= 55:
        score += 10
    elif r <= 45:
        score -= 10

    recent = closes[-5:]

    if recent[-1] > recent[0]:
        score += 5
    else:
        score -= 5

    score = max(0, min(100, score))

    if score >= 70:
        signal = "شراء قوي"
    elif score >= 60:
        signal = "شراء"
    elif score <= 30:
        signal = "بيع قوي"
    elif score <= 40:
        signal = "بيع"
    else:
        signal = "محايد"

    return {
        "signal": signal,
        "score": score,
        "price": price,
        "ema20": e20 or 0,
        "ema50": e50 or 0,
        "ema200": e200 or 0,
        "rsi": r,
        "atr": atr_value,
    }


# ============================================================
# SPOT MARKETS
# ============================================================

def get_spot_markets():
    with CACHE_LOCK:
        if (
            time.time() - CACHE["markets"]["time"] < 300
            and CACHE["markets"]["data"]
        ):
            return CACHE["markets"]["data"]

    data = binance_get(
        "/api/v3/exchangeInfo"
    )

    result = []

    for symbol in data.get("symbols", []):

        if symbol.get("status") != "TRADING":
            continue

        if symbol.get("quoteAsset") != "USDT":
            continue

        if symbol.get("isSpotTradingAllowed") is False:
            continue

        result.append(symbol["symbol"])

    with CACHE_LOCK:
        CACHE["markets"] = {
            "time": time.time(),
            "data": result,
        }

    return result


# ============================================================
# SPOT SCAN
# ============================================================

def scan_one_spot(symbol, interval):
    try:
        klines = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": 220,
            }
        )

        analysis = analyze_klines(klines)

        return {
            "symbol": symbol,
            "price": analysis["price"],
            "signal": analysis["signal"],
            "score": analysis["score"],
            "rsi": round(analysis["rsi"], 2),
            "ema20": analysis["ema20"],
            "ema50": analysis["ema50"],
            "ema200": analysis["ema200"],
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e)
        }


@app.get("/api/binance/scan")
def api_spot_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    if interval not in {
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
    }:
        interval = "15m"

    with CACHE_LOCK:
        if (
            time.time() - CACHE["spot_scan"]["time"] < 45
            and CACHE["spot_scan"]["data"]
        ):
            return jsonify({
                "ok": True,
                "data": CACHE["spot_scan"]["data"],
                "cached": True,
            })

    try:
        tickers = binance_get(
            "/api/v3/ticker/24hr"
        )

        candidates = []

        for item in tickers:

            symbol = item.get("symbol", "")

            if not symbol.endswith("USDT"):
                continue

            volume = safe_float(
                item.get("quoteVolume")
            )

            if volume < 1_000_000:
                continue

            candidates.append({
                "symbol": symbol,
                "volume": volume,
                "change": safe_float(
                    item.get("priceChangePercent")
                ),
            })

        candidates.sort(
            key=lambda x: x["volume"],
            reverse=True
        )

        candidates = candidates[:40]

        results = []

        with ThreadPoolExecutor(max_workers=6) as executor:

            futures = [
                executor.submit(
                    scan_one_spot,
                    x["symbol"],
                    interval
                )
                for x in candidates
            ]

            for future in as_completed(futures):

                item = future.result()

                if "error" not in item:
                    results.append(item)

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        with CACHE_LOCK:
            CACHE["spot_scan"] = {
                "time": time.time(),
                "data": results,
            }

        return jsonify({
            "ok": True,
            "data": results,
            "cached": False,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# ============================================================
# BINANCE PRICE
# ============================================================

@app.get("/api/binance/price")
def api_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    try:
        data = binance_get(
            "/api/v3/ticker/price",
            {"symbol": symbol}
        )

        return jsonify({
            "ok": True,
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# BINANCE ANALYSIS
# ============================================================

@app.get("/api/binance/analysis")
def api_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        klines = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": 220,
            }
        )

        result = analyze_klines(klines)

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "data": result,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# FUTURES
# ============================================================

def get_futures_symbols():

    data = binance_get(
        "/fapi/v1/exchangeInfo",
        futures=True,
    )

    result = set()

    for item in data.get("symbols", []):

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("contractType") != "PERPETUAL":
            continue

        result.add(item["symbol"])

    return result


def scan_futures_one(symbol):

    try:

        klines = binance_get(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "15m",
                "limit": 220,
            },
            futures=True,
        )

        analysis = analyze_klines(klines)

        price = analysis["price"]

        if price <= 0:
            return None

        if analysis["score"] >= 65:

            direction = "LONG"
            signal = "شراء"

            risk = max(
                analysis["atr"] * 1.5,
                price * 0.01
            )

            entry = price
            stop = price - risk
            target = price + risk * 1.5

        elif analysis["score"] <= 35:

            direction = "SHORT"
            signal = "بيع"

            risk = max(
                analysis["atr"] * 1.5,
                price * 0.01
            )

            entry = price
            stop = price + risk
            target = price - risk * 1.5

        else:
            return None

        return {
            "symbol": symbol,
            "direction": direction,
            "signal": signal,
            "score": analysis["score"],
            "entry": entry,
            "target": target,
            "stop": stop,
            "rsi": round(analysis["rsi"], 2),
            "leverage": 3,
        }

    except Exception:
        return None


@app.get("/api/futures/scan")
def api_futures_scan():

    with CACHE_LOCK:

        if (
            time.time() - CACHE["futures_scan"]["time"] < 60
            and CACHE["futures_scan"]["data"]
        ):
            return jsonify({
                "ok": True,
                "data": CACHE["futures_scan"]["data"],
                "cached": True,
            })

    try:

        symbols = get_futures_symbols()

        tickers = binance_get(
            "/fapi/v1/ticker/24hr",
            futures=True,
        )

        volume_map = {}

        for item in tickers:

            symbol = item.get("symbol", "")

            if symbol not in symbols:
                continue

            volume = safe_float(
                item.get("quoteVolume")
            )

            if volume >= 1_000_000:
                volume_map[symbol] = volume

        top_symbols = sorted(
            volume_map,
            key=volume_map.get,
            reverse=True
        )[:50]

        results = []

        with ThreadPoolExecutor(max_workers=6) as executor:

            jobs = [
                executor.submit(
                    scan_futures_one,
                    symbol
                )
                for symbol in top_symbols
            ]

            for future in as_completed(jobs):

                result = future.result()

                if result:
                    result["volume"] = volume_map.get(
                        result["symbol"],
                        0
                    )

                    results.append(result)

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        results = results[:20]

        with CACHE_LOCK:
            CACHE["futures_scan"] = {
                "time": time.time(),
                "data": results,
            }

        return jsonify({
            "ok": True,
            "data": results,
            "cached": False,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# ============================================================
# FUTURES TEST
# ============================================================

@app.get("/api/futures/test")
def futures_test():

    try:

        data = binance_get(
            "/fapi/v1/ping",
            futures=True,
        )

        return jsonify({
            "ok": True,
            "message": "Binance Futures متصل",
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# ============================================================
# NEWS
# ============================================================

NEWS_URL = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/"
)


def translate_to_arabic(text):

    text = clean_text(
        text,
        900
    )

    if not text:
        return ""

    try:

        response = session_http.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ar",
                "dt": "t",
                "q": text,
            },
            timeout=8,
        )

        if response.status_code != 200:
            return text

        data = response.json()

        parts = []

        for item in data[0]:

            if item and item[0]:
                parts.append(item[0])

        translated = "".join(parts).strip()

        return translated or text

    except Exception:
        return text


def fetch_news():

    with CACHE_LOCK:

        if (
            time.time() - CACHE["news"]["time"] < 600
            and CACHE["news"]["data"]
        ):
            return CACHE["news"]["data"]

    try:

        response = session_http.get(
            NEWS_URL,
            timeout=12,
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        items = []

        for item in root.findall(".//item")[:12]:

            title_en = clean_text(
                item.findtext("title"),
                250
            )

            desc_en = clean_text(
                item.findtext("description"),
                700
            )

            if not title_en:
                continue

            title_ar = translate_to_arabic(
                title_en
            )

            desc_ar = translate_to_arabic(
                desc_en
            )

            items.append({
                "id": len(items),
                "title": title_ar,
                "description": desc_ar,
                "source": "CoinDesk",
                "published": clean_text(
                    item.findtext("pubDate"),
                    100
                ),
            })

        with CACHE_LOCK:
            CACHE["news"] = {
                "time": time.time(),
                "data": items,
            }

        return items

    except Exception as e:

        print("NEWS ERROR:", e)

        return []


@app.get("/api/news")
def api_news():

    try:

        news = fetch_news()

        return jsonify({
            "ok": True,
            "data": news,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/login")
def login_page():
    return render_template("login.html")


@app.get("/register")
def register_page():
    return render_template("register.html")


@app.get("/admin")
def admin_page():
    return render_template("admin.html")


@app.post("/api/auth/register")
def api_register():

    data = request.get_json(
        silent=True
    ) or {}

    name = clean_text(
        data.get("name"),
        80
    )

    email = clean_text(
        data.get("email"),
        160
    ).lower()

    password = str(
        data.get("password") or ""
    )

    if len(name) < 2:
        return jsonify({
            "ok": False,
            "error": "اكتب الاسم بشكل صحيح."
        }), 400

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        email
    ):
        return jsonify({
            "ok": False,
            "error": "البريد الإلكتروني غير صحيح."
        }), 400

    if len(password) < 6:
        return jsonify({
            "ok": False,
            "error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل."
        }), 400

    try:

        password_hash = hash_password(
            password
        )

        with db() as conn:
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
                        "error": "البريد مستخدم مسبقاً."
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
                        password_hash,
                    )
                )

                user_id = cur.fetchone()[0]

        # لا نسجل دخول تلقائي بعد التسجيل
        session.pop("user_id", None)

        return jsonify({
            "ok": True,
            "message": "تم إنشاء الحساب بنجاح. سجل دخولك الآن.",
            "redirect": "/login",
            "user_id": user_id,
        })

    except Exception as e:

        print("REGISTER ERROR:", e)

        return jsonify({
            "ok": False,
            "error": "تعذر إنشاء الحساب حالياً."
        }), 500


@app.post("/api/auth/login")
def api_login():

    data = request.get_json(
        silent=True
    ) or {}

    email = clean_text(
        data.get("email"),
        160
    ).lower()

    password = str(
        data.get("password") or ""
    )

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        email,
                        password_hash,
                        is_active
                    FROM users
                    WHERE email=%s
                    """,
                    (email,)
                )

                row = cur.fetchone()

        if not row:
            return jsonify({
                "ok": False,
                "error": "البريد أو كلمة المرور غير صحيحة."
            }), 401

        if not row[4]:
            return jsonify({
                "ok": False,
                "error": "الحساب موقوف."
            }), 403

        if not verify_password(
            password,
            row[3]
        ):
            return jsonify({
                "ok": False,
                "error": "البريد أو كلمة المرور غير صحيحة."
            }), 401

        session.permanent = True
        session["user_id"] = row[0]

        return jsonify({
            "ok": True,
            "message": "تم تسجيل الدخول.",
            "user": {
                "id": row[0],
                "name": row[1],
                "email": row[2],
            },
            "redirect": "/",
        })

    except Exception as e:

        print("LOGIN ERROR:", e)

        return jsonify({
            "ok": False,
            "error": "تعذر تسجيل الدخول حالياً."
        }), 500


@app.post("/api/auth/logout")
def api_logout():

    session.pop("user_id", None)

    return jsonify({
        "ok": True
    })


@app.get("/api/auth/me")
def api_auth_me():

    user = get_current_user()

    return jsonify({
        "ok": True,
        "logged_in": bool(user),
        "user": user,
    })


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/api/admin/login")
def api_admin_login():

    data = request.get_json(
        silent=True
    ) or {}

    username = clean_text(
        data.get("username"),
        100
    )

    password = str(
        data.get("password") or ""
    )

    key = str(
        data.get("key") or ""
    )

    valid = False

    if (
        username == ADMIN_USERNAME
        and ADMIN_PASSWORD
        and hmac.compare_digest(
            password,
            ADMIN_PASSWORD
        )
    ):
        valid = True

    if (
        ADMIN_KEY
        and key
        and hmac.compare_digest(
            key,
            ADMIN_KEY
        )
    ):
        valid = True

    if not valid:
        return jsonify({
            "ok": False,
            "error": "بيانات الأدمن غير صحيحة."
        }), 401

    session.permanent = True
    session["admin"] = True

    token = create_admin_token(
        ADMIN_USERNAME
    )

    return jsonify({
        "ok": True,
        "token": token,
        "redirect": "/admin",
    })


@app.get("/api/admin/me")
def api_admin_me():

    return jsonify({
        "ok": True,
        "admin": is_admin(),
        "username": (
            ADMIN_USERNAME
            if is_admin()
            else None
        )
    })


@app.post("/api/admin/logout")
def api_admin_logout():

    session.pop("admin", None)

    return jsonify({
        "ok": True
    })


# ============================================================
# ADMIN STATS
# ============================================================

@app.get("/api/admin/stats")
@admin_required
def admin_stats():

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    "SELECT COUNT(*) FROM users"
                )
                users = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM users
                    WHERE is_premium=TRUE
                    """
                )
                premium = cur.fetchone()[0]

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
                    SELECT COUNT(*)
                    FROM payment_requests
                    WHERE status='approved'
                    """
                )
                approved = cur.fetchone()[0]

        return jsonify({
            "ok": True,
            "data": {
                "users": users,
                "premium": premium,
                "pending": pending,
                "approved": approved,
            }
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# ADMIN USERS
# ============================================================

@app.get("/api/admin/users")
@admin_required
def admin_users():

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        id,
                        name,
                        email,
                        is_active,
                        is_premium,
                        premium_until,
                        created_at
                    FROM users
                    ORDER BY id DESC
                    LIMIT 200
                """)

                rows = cur.fetchall()

        users = []

        for row in rows:

            users.append({
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "is_active": row[3],
                "is_premium": row[4],
                "premium_until": (
                    row[5].isoformat()
                    if row[5]
                    else None
                ),
                "created_at": (
                    row[6].isoformat()
                    if row[6]
                    else None
                ),
            })

        return jsonify({
            "ok": True,
            "data": users,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# ADMIN PAYMENTS
# ============================================================

@app.get("/api/admin/payments")
@admin_required
def admin_payments():

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        p.id,
                        p.user_id,
                        u.name,
                        u.email,
                        p.plan,
                        p.amount,
                        p.method,
                        p.txid,
                        p.status,
                        p.created_at
                    FROM payment_requests p
                    LEFT JOIN users u
                        ON u.id=p.user_id
                    ORDER BY p.id DESC
                    LIMIT 200
                """)

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
                "method": row[6],
                "txid": row[7],
                "status": row[8],
                "created_at": (
                    row[9].isoformat()
                    if row[9]
                    else None
                ),
            })

        return jsonify({
            "ok": True,
            "data": payments,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# SUBSCRIPTION
# ============================================================

@app.get("/api/subscription/plans")
def subscription_plans():

    return jsonify({
        "ok": True,
        "data": PLANS,
    })


@app.get("/api/subscription/my")
def my_subscription():

    user = get_current_user()

    if not user:
        return jsonify({
            "ok": True,
            "logged_in": False,
        })

    return jsonify({
        "ok": True,
        "logged_in": True,
        "data": {
            "is_premium": user["is_premium"],
            "premium_until": user["premium_until"],
        }
    })


@app.post("/api/subscription/request")
def subscription_request():

    user = get_current_user()

    if not user:
        return jsonify({
            "ok": False,
            "error": "يجب تسجيل الدخول أولاً."
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    plan = str(
        data.get("plan") or ""
    ).strip()

    method = str(
        data.get("method") or "TRC20"
    ).strip()

    txid = clean_text(
        data.get("txid"),
        250
    )

    if plan not in PLANS:
        return jsonify({
            "ok": False,
            "error": "الباقة غير صحيحة."
        }), 400

    if not txid:
        return jsonify({
            "ok": False,
            "error": "أدخل رقم العملية TXID."
        }), 400

    amount = PLANS[plan]["amount"]

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO payment_requests
                    (
                        user_id,
                        plan,
                        amount,
                        method,
                        txid
                    )
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (
                        user["id"],
                        plan,
                        amount,
                        method,
                        txid,
                    )
                )

        return jsonify({
            "ok": True,
            "message": "تم إرسال طلب الاشتراك للمراجعة."
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# ADMIN PAYMENT REVIEW
# ============================================================

@app.post("/api/admin/payments/<int:payment_id>/review")
@admin_required
def review_payment(payment_id):

    data = request.get_json(
        silent=True
    ) or {}

    action = str(
        data.get("action") or ""
    ).lower()

    if action not in {
        "approve",
        "reject",
    }:
        return jsonify({
            "ok": False,
            "error": "الإجراء غير صحيح."
        }), 400

    try:

        with db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        user_id,
                        plan,
                        status
                    FROM payment_requests
                    WHERE id=%s
                    """,
                    (payment_id,)
                )

                payment = cur.fetchone()

                if not payment:
                    return jsonify({
                        "ok": False,
                        "error": "الطلب غير موجود."
                    }), 404

                if payment[3] != "pending":
                    return jsonify({
                        "ok": False,
                        "error": "تمت مراجعة الطلب مسبقاً."
                    }), 400

                if action == "reject":

                    cur.execute(
                        """
                        UPDATE payment_requests
                        SET
                            status='rejected',
                            reviewed_at=NOW()
                        WHERE id=%s
                        """,
                        (payment_id,)
                    )

                else:

                    plan = PLANS.get(
                        payment[2]
                    )

                    if not plan:
                        return jsonify({
                            "ok": False,
                            "error": "الباقة غير موجودة."
                        }), 400

                    cur.execute(
                        """
                        SELECT premium_until
                        FROM users
                        WHERE id=%s
                        """,
                        (payment[1],)
                    )

                    user_row = cur.fetchone()

                    current_until = (
                        user_row[0]
                        if user_row
                        else None
                    )

                    now = now_utc()

                    if (
                        current_until
                        and current_until > now
                    ):
                        start = current_until
                    else:
                        start = now

                    new_until = (
                        start
                        + timedelta(
                            days=plan["days"]
                        )
                    )

                    cur.execute(
                        """
                        UPDATE users
                        SET
                            is_premium=TRUE,
                            premium_until=%s
                        WHERE id=%s
                        """,
                        (
                            new_until,
                            payment[1],
                        )
                    )

                    cur.execute(
                        """
                        UPDATE payment_requests
                        SET
                            status='approved',
                            reviewed_at=NOW()
                        WHERE id=%s
                        """,
                        (payment_id,)
                    )

        return jsonify({
            "ok": True,
            "message": (
                "تم قبول الاشتراك."
                if action == "approve"
                else "تم رفض الطلب."
            )
        })

    except Exception as e:

        print("PAYMENT REVIEW ERROR:", e)

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# ============================================================
# SETTINGS
# ============================================================

@app.get("/api/settings/public")
def public_settings():

    return jsonify({
        "ok": True,
        "data": {
            "trc20_address": TRC20_ADDRESS,
            "plans": PLANS,
        }
    })


# ============================================================
# BINANCE CONNECTION TEST
# ============================================================

@app.get("/api/binance/test")
def binance_test():

    try:

        data = binance_get(
            "/api/v3/ping"
        )

        return jsonify({
            "ok": True,
            "message": "Binance Spot متصل",
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud",
        "time": now_utc().isoformat(),
    })


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return render_template("index.html")


# ============================================================
# STARTUP
# ============================================================

try:
    init_db()
    print("Database initialized successfully.")

except Exception as e:
    print("DATABASE INIT ERROR:", e)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
    )
