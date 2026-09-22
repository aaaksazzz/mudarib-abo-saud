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

from flask import Flask, jsonify, render_template, request, session


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
    PERMANENT_SESSION_LIFETIME=timedelta(days=30)
)


# =========================================================
# DATABASE / ADMIN / PAYMENT
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
    }
}


# =========================================================
# BYBIT
# =========================================================

# مصدر بيانات السوق: Bybit V5
# لا توجد حاجة إلى API Key للبيانات العامة.

BYBIT_BASES = [
    "https://api.bybit.com",
    "https://api.bytick.com",
]

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "Mudarib-Abo-Saud/3.0"
})


# =========================================================
# CACHE
# =========================================================

MARKET_CACHE = {
    "ts": 0,
    "symbols": []
}

FUTURES_CACHE = {
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
# MARKET CONSTANTS
# =========================================================

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


# واجهة Bybit تستخدم أرقام مختلفة للفريمات
BYBIT_INTERVALS = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D"
}


# =========================================================
# DATABASE
# =========================================================

def db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL غير مضبوط")

    return psycopg.connect(DATABASE_URL)


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
        print("Database init error:", e)


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


def verify_password(password, stored):
    try:
        _,
        iterations,
        salt_hex,
        digest_hex = stored.split("$", 3)

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
# USERS
# =========================================================

def user_row(uid):
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
                (uid,)
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
        )
    }


def current_user():
    uid = session.get("user_id")

    if not uid:
        return None

    try:
        return user_row(uid)

    except Exception:
        return None


def is_admin():
    return bool(session.get("admin"))


# =========================================================
# BYBIT REQUEST
# =========================================================

def bybit_get(path, params=None, timeout=6):
    last = "تعذر الاتصال بـ Bybit"

    for base in BYBIT_BASES:

        for attempt in range(2):

            try:
                response = HTTP.get(
                    base + path,
                    params=params or {},
                    timeout=timeout
                )

                try:
                    data = response.json()

                except ValueError:
                    data = {}

                if (
                    response.status_code == 200
                    and data.get("retCode") == 0
                ):
                    return data.get("result", {})

                msg = (
                    data.get("retMsg")
                    or response.text[:160]
                    or "خطأ غير معروف"
                )

                last = (
                    f"Bybit {base} "
                    f"HTTP {response.status_code}: "
                    f"{msg}"
                )

                if (
                    response.status_code in (418, 429)
                    or response.status_code >= 500
                ):
                    time.sleep(
                        0.4 * (attempt + 1)
                    )
                    continue

                break

            except requests.RequestException as e:

                last = (
                    f"Bybit {base}: "
                    f"{str(e)[:180]}"
                )

                time.sleep(
                    0.35 * (attempt + 1)
                )

    raise RuntimeError(last)


# =========================================================
# BYBIT SPOT SYMBOLS
# =========================================================

def market_symbols():
    now = time.time()

    with CACHE_LOCK:
        if (
            MARKET_CACHE["symbols"]
            and now - MARKET_CACHE["ts"] < 900
        ):
            return MARKET_CACHE["symbols"]

    result = []

    cursor = ""

    while True:

        params = {
            "category": "spot",
            "limit": 1000
        }

        if cursor:
            params["cursor"] = cursor

        data = bybit_get(
            "/v5/market/instruments-info",
            params,
            8
        )

        for s in data.get("list", []):

            symbol = s.get("symbol", "")
            base = s.get("baseCoin", "")
            quote = s.get("quoteCoin", "")

            if s.get("status") != "Trading":
                continue

            if quote != "USDT":
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

        cursor = (
            data.get("nextPageCursor")
            or ""
        )

        if not cursor:
            break

    with CACHE_LOCK:
        MARKET_CACHE.update({
            "ts": now,
            "symbols": result
        })

    return result


# =========================================================
# BYBIT FUTURES SYMBOLS
# =========================================================

def futures_symbols():
    now = time.time()

    with CACHE_LOCK:

        if (
            FUTURES_CACHE["symbols"]
            and now - FUTURES_CACHE["ts"] < 900
        ):
            return FUTURES_CACHE["symbols"]

    result = []

    cursor = ""

    while True:

        params = {
            "category": "linear",
            "limit": 1000
        }

        if cursor:
            params["cursor"] = cursor

        data = bybit_get(
            "/v5/market/instruments-info",
            params,
            8
        )

        for s in data.get("list", []):

            symbol = s.get("symbol", "")

            if s.get("status") != "Trading":
                continue

            if s.get("quoteCoin") != "USDT":
                continue

            if s.get("contractType") != "LinearPerpetual":
                continue

            result.append({
                "symbol": symbol,
                "baseAsset": s.get(
                    "baseCoin",
                    ""
                ),
                "quoteAsset": "USDT",
                "leverage": s.get(
                    "leverageFilter",
                    {}
                ).get(
                    "maxLeverage",
                    "1"
                )
            })

        cursor = (
            data.get("nextPageCursor")
            or ""
        )

        if not cursor:
            break

    with CACHE_LOCK:
        FUTURES_CACHE.update({
            "ts": now,
            "symbols": result
        })

    return result


# =========================================================
# BYBIT KLINES
# =========================================================

def bybit_klines(
    symbol,
    interval="15m",
    category="spot",
    limit=210
):

    data = bybit_get(
        "/v5/market/kline",
        {
            "category": category,
            "symbol": symbol,
            "interval": BYBIT_INTERVALS[interval],
            "limit": min(limit, 1000)
        },
        6
    )

    # Bybit يرجع الأحدث أولاً
    rows = list(
        reversed(
            data.get("list", [])
        )
    )

    return [
        [
            int(x[0]),
            float(x[1]),
            float(x[2]),
            float(x[3]),
            float(x[4]),
            float(x[5])
        ]
        for x in rows
    ]


# =========================================================
# BYBIT TICKERS
# =========================================================

def bybit_tickers(category="spot"):
    return bybit_get(
        "/v5/market/tickers",
        {
            "category": category
        },
        7
    ).get(
        "list",
        []
    )


def ticker_map(category="spot"):
    return {
        x.get("symbol"): x
        for x in bybit_tickers(category)
        if x.get("symbol")
    }


# =========================================================
# TECHNICAL INDICATORS
# =========================================================

def ema(values, period):

    if not values:
        return None

    if len(values) < period:
        period = len(values)

    e = sum(
        values[:period]
    ) / period

    k = 2 / (period + 1)

    for v in values[period:]:
        e = (
            v * k
            + e * (1 - k)
        )

    return e


def rsi(values, period=14):

    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):

        d = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(d, 0)
        )

        losses.append(
            max(-d, 0)
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
                + gains[i]
            )
            / period
        )

        avg_loss = (
            (
                avg_loss
                * (period - 1)
                + losses[i]
            )
            / period
        )

    if avg_loss == 0:
        return 100.0

    return 100 - (
        100
        / (
            1
            + avg_gain / avg_loss
        )
    )


def atr(klines, period=14):

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

        previous = float(
            klines[i - 1][4]
        )

        trs.append(
            max(
                high - low,
                abs(
                    high - previous
                ),
                abs(
                    low - previous
                )
            )
        )

    return (
        sum(trs[-period:])
        / min(
            period,
            len(trs)
        )
    )


# =========================================================
# ANALYSIS
# =========================================================

def analyze_klines(klines):

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

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    rv = rsi(closes)

    e12 = ema(closes, 12)
    e26 = ema(closes, 26)

    macd = (
        (e12 or 0)
        - (e26 or 0)
    )

    series = []

    for i in range(
        max(
            26,
            len(closes) - 80
        ),
        len(closes)
    ):

        series.append(
            (
                ema(
                    closes[:i + 1],
                    12
                )
                or 0
            )
            -
            (
                ema(
                    closes[:i + 1],
                    26
                )
                or 0
            )
        )

    macd_signal = (
        ema(series, 9)
        if series
        else 0
    )

    macd_hist = (
        macd
        - (macd_signal or 0)
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
        min(100, score)
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

    risk = max(
        atr(klines) * 1.5,
        price * 0.01
    )

    if direction == "buy":

        sl = max(
            price - risk,
            0
        )

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2
        tp3 = price + risk * 3

    elif direction == "sell":

        sl = price + risk

        tp1 = max(
            price - risk * 1.5,
            0
        )

        tp2 = max(
            price - risk * 2,
            0
        )

        tp3 = max(
            price - risk * 3,
            0
        )

    else:

        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

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

        "macd": macd,
        "macd_signal": macd_signal,
        "macd_histogram": macd_hist,

        "atr": atr(klines),

        "support": min(
            lows[-20:]
        ),

        "resistance": max(
            highs[-20:]
        ),

        "reasons": reasons,
        "candles": candles
    }


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
# MAIN
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
        "source": "Bybit",
        "time": int(time.time())
    })


# =========================================================
# AUTH REGISTER
# =========================================================

@app.post("/api/auth/register")
def register():

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    name = str(
        d.get("name", "")
    ).strip()

    email = str(
        d.get("email", "")
    ).strip().lower()

    password = str(
        d.get("password", "")
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
        session["user_id"] = uid

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


# =========================================================
# AUTH LOGIN
# =========================================================

@app.post("/api/auth/login")
def login():

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    email = str(
        d.get("email", "")
    ).strip().lower()

    password = str(
        d.get("password", "")
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
        session["user_id"] = row[0]

        return jsonify({
            "ok": True,
            "user": user_json(
                user_row(row[0])
            )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


@app.post("/api/auth/logout")
def logout():

    session.pop(
        "user_id",
        None
    )

    return jsonify({
        "ok": True
    })


@app.get("/api/auth/me")
def auth_me():

    u = current_user()

    if u:

        return jsonify({
            "ok": True,
            "user": user_json(u)
        })

    return jsonify({
        "ok": False,
        "message":
            "غير مسجل دخول"
    }), 401


# =========================================================
# ADMIN
# =========================================================

@app.get("/admin")
def admin_page():

    return render_template(
        "admin.html"
    )


@app.post("/api/admin/login")
def admin_login():

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    username = str(
        d.get("username", "")
    )

    password = str(
        d.get("password", "")
    )

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
        session.permanent = True
        session["admin"] = True

        return jsonify({
            "ok": True
        })

    return jsonify({
        "ok": False,
        "message":
            "بيانات الأدمن غير صحيحة"
    }), 401


@app.get("/api/admin/me")
def admin_me():

    return jsonify({
        "ok": True,
        "admin": is_admin()
    })


@app.post("/api/admin/logout")
def admin_logout():

    session.clear()

    return jsonify({
        "ok": True
    })


@app.get("/api/admin/stats")
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
                    cur.fetchone()[0] or 0
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


@app.get("/api/admin/users")
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

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = d.get(
        "plan",
        "free"
    )

    expires = None

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

    if plan in PLANS:

        expires = (
            datetime.now(timezone.utc)
            + timedelta(
                days=PLANS[plan]["days"]
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


# =========================================================
# ADMIN PAYMENTS
# =========================================================

@app.get("/api/admin/payments")
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
                    "amount": float(r[5]),
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


@app.post(
    "/api/admin/payments/<int:payment_id>/review"
)
def review_payment(payment_id):

    if not is_admin():

        return jsonify({
            "ok": False,
            "message":
                "غير مصرح"
        }), 401

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    action = d.get(
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

                status = "rejected"

                if action == "approve":

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
                        else datetime.now(
                            timezone.utc
                        )
                    )

                    expires = (
                        base
                        + timedelta(
                            days=PLANS[
                                p[1]
                            ]["days"]
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


# =========================================================
# SUBSCRIPTIONS
# =========================================================

@app.get("/api/subscription/plans")
def subscription_plans():

    return jsonify({
        "ok": True,
        "network": "TRC20",
        "address": PAYMENT_ADDRESS,
        "plans": PLANS
    })


@app.post("/api/subscription/request")
def subscription_request():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "سجل دخول أولاً"
        }), 401

    d = (
        request.get_json(
            silent=True
        )
        or {}
    )

    plan = d.get("plan")

    txid = str(
        d.get("txid", "")
    ).strip()

    if plan not in PLANS:

        return jsonify({
            "ok": False,
            "message":
                "اختر باقة صحيحة"
        }), 400

    if len(txid) < 8 or len(txid) > 200:

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
                        %s,%s,%s,
                        'TRC20',
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        u[0],
                        plan,
                        PLANS[plan]["amount"],
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


@app.get("/api/subscription/my")
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
                datetime.now(timezone.utc)
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
                    "amount": float(r[2]),
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


# =========================================================
# SETTINGS
# =========================================================

@app.get("/api/settings")
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


@app.post("/api/settings")
def save_settings():

    u = current_user()

    if not u:

        return jsonify({
            "ok": False,
            "message":
                "سجل دخول أولاً"
        }), 401

    value = json.dumps(
        request.get_json(
            silent=True
        )
        or {},
        ensure_ascii=False
    )

    key = f"user:{u[0]}:settings"

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


# =========================================================
# BYBIT TEST
# =========================================================

@app.get("/api/bybit/test")
@app.get("/api/binance/test")
def exchange_test():

    try:

        bybit_get(
            "/v5/market/time",
            timeout=4
        )

        return jsonify({
            "ok": True,
            "source": "Bybit",
            "bybit": True,
            "binance": False,
            "bases": BYBIT_BASES
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "source": "Bybit",
            "bybit": False,
            "binance": False,
            "message": str(e)
        }), 503


# =========================================================
# MARKETS
# =========================================================

@app.get("/api/binance/markets")
@app.get("/api/bybit/markets")
def markets():

    try:

        return jsonify({
            "ok": True,
            "source": "Bybit",
            "symbols":
                market_symbols()
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# SPOT PRICES
# =========================================================

def spot_price_rows(wanted=None):

    out = []

    for t in bybit_tickers("spot"):

        symbol = t.get(
            "symbol",
            ""
        )

        if (
            wanted
            and symbol not in wanted
        ):
            continue

        out.append({
            "symbol": symbol,

            "price": float(
                t.get(
                    "lastPrice"
                )
                or 0
            ),

            "change": float(
                t.get(
                    "price24hPcnt"
                )
                or 0
            ) * 100,

            "volume": float(
                t.get(
                    "turnover24h"
                )
                or 0
            )
        })

    return out


@app.get("/api/binance/prices")
@app.get("/api/bybit/prices")
def prices():

    try:

        wanted = {
            x.strip().upper()
            for x in
            request.args.get(
                "symbols",
                ""
            ).split(",")
            if x.strip()
        }

        return jsonify({
            "ok": True,
            "source": "Bybit",
            "prices":
                spot_price_rows(
                    wanted
                )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# SINGLE PRICE
# =========================================================

@app.get("/api/binance/price")
@app.get("/api/bybit/price")
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

        t = next(
            (
                x
                for x
                in bybit_tickers("spot")
                if x.get(
                    "symbol"
                ) == symbol
            ),
            None
        )

        if not t:

            raise RuntimeError(
                "العملة غير موجودة في Bybit Spot"
            )

        return jsonify({
            "ok": True,
            "source": "Bybit",
            "symbol": symbol,

            "price": float(
                t.get(
                    "lastPrice"
                )
                or 0
            ),

            "change": float(
                t.get(
                    "price24hPcnt"
                )
                or 0
            ) * 100,

            "volume": float(
                t.get(
                    "turnover24h"
                )
                or 0
            )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# KLINES
# =========================================================

@app.get("/api/binance/klines")
@app.get("/api/bybit/klines")
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

        return jsonify({
            "ok": True,
            "source": "Bybit",
            "klines":
                bybit_klines(
                    symbol,
                    interval,
                    "spot",
                    210
                )
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# ANALYSIS
# =========================================================

@app.get("/api/binance/analysis")
@app.get("/api/bybit/analysis")
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

        a = analyze_klines(
            bybit_klines(
                symbol,
                interval,
                "spot",
                230
            )
        )

        a.update({
            "symbol": symbol,
            "interval": interval,
            "source": "Bybit"
        })

        return jsonify({
            "ok": True,
            "analysis": a
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# SPOT SCANNER
# =========================================================

@app.get("/api/binance/scan")
def scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

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

    except Exception:

        requested = 40

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
            and now - cached["ts"] < 45
        ):

            payload = dict(
                cached["payload"]
            )

            payload["cached"] = True

            return jsonify(
                payload
            )

    try:

        symbols = {
            x["symbol"]
            for x in market_symbols()
        }

        candidates = []

        for t in bybit_tickers("spot"):

            symbol = t.get(
                "symbol",
                ""
            )

            if symbol not in symbols:
                continue

            quote_volume = float(
                t.get(
                    "turnover24h"
                )
                or 0
            )

            # نفس شرط السيولة
            if quote_volume < 1_000_000:
                continue

            candidates.append(
                (
                    quote_volume,
                    t
                )
            )

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        selected = candidates[
            :min(
                requested,
                40
            )
        ]

        results = []

        def worker(item):

            quote_volume, t = item

            symbol = t["symbol"]

            a = analyze_klines(
                bybit_klines(
                    symbol,
                    interval,
                    "spot",
                    210
                )
            )

            return {
                "symbol": symbol,

                "price": float(
                    t.get(
                        "lastPrice"
                    )
                    or a["price"]
                ),

                "change": float(
                    t.get(
                        "price24hPcnt"
                    )
                    or 0
                ) * 100,

                "volume": quote_volume,

                "signal": a["signal"],
                "direction": a["direction"],

                "score": a["score"],
                "score10": a["score10"],

                "interval": interval,

                "entry": a["entry"],
                "tp1": a["tp1"],
                "tp2": a["tp2"],
                "tp3": a["tp3"],
                "sl": a["sl"],

                "signalRank":
                    signal_rank(
                        a["signal"]
                    ),

                "updatedAt":
                    int(
                        time.time()
                        * 1000
                    ),

                "source": "Bybit"
            }

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
                    results.append(
                        future.result()
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
            "source": "Bybit",
            "interval": interval,
            "count": len(results),
            "requested": requested,
            "scanned": len(selected),
            "results": results,
            "cached": False
        }

        with CACHE_LOCK:

            SCAN_CACHE[
                interval
            ] = {
                "ts": time.time(),
                "payload": payload
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

            payload["cached"] = True

            payload["warning"] = (
                "تم عرض آخر نتيجة محفوظة"
            )

            return jsonify(
                payload
            )

        return jsonify({
            "ok": False,
            "source": "Bybit",
            "message": str(e)
        }), 503


# =========================================================
# FUTURES
# =========================================================

@app.get("/api/futures/signals")
def futures_signals():

    try:

        symbols = {
            x["symbol"]: x
            for x in futures_symbols()
        }

        rows = []

        for t in bybit_tickers(
            "linear"
        ):

            symbol = t.get(
                "symbol",
                ""
            )

            if symbol not in symbols:
                continue

            volume = float(
                t.get(
                    "turnover24h"
                )
                or 0
            )

            if volume < 1_000_000:
                continue

            a = analyze_klines(
                bybit_klines(
                    symbol,
                    "15m",
                    "linear",
                    210
                )
            )

            if a["direction"] == "neutral":
                continue

            rows.append({
                "symbol": symbol,

                "signal": a["signal"],
                "direction": a["direction"],

                "side":
                    "LONG"
                    if a["direction"] == "buy"
                    else "SHORT",

                "price": a["price"],
                "entry": a["entry"],

                "tp1": a["tp1"],
                "tp2": a["tp2"],
                "sl": a["sl"],

                "score": a["score"],

                "leverage":
                    symbols[
                        symbol
                    ].get(
                        "leverage",
                        "1"
                    ),

                "volume": volume,

                "source": "Bybit"
            })

        rows.sort(
            key=lambda x:
                x["score"],
            reverse=True
        )

        return jsonify({
            "ok": True,
            "signals": rows[:50]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# ALPHA
# =========================================================

@app.get("/api/alpha/signals")
def alpha_signals():

    response = futures_signals()

    data = response.get_json()

    rows = (
        data.get(
            "signals",
            []
        )
        if data
        else []
    )

    for x in rows:

        x["type"] = "alpha"
        x["market"] = "futures"
        x["source"] = "Bybit Linear"

    return jsonify({
        "ok": True,
        "signals": rows[:30]
    })


# =========================================================
# US MARKET
# =========================================================

@app.get("/api/us-market/signals")
def us_market():

    symbols = [
        "SPY",
        "QQQ",
        "NVDA",
        "TSLA",
        "AAPL",
        "MSFT",
        "AMZN",
        "META",
        "GOOGL",
        "AMD"
    ]

    out = []

    for symbol in symbols:

        try:

            response = HTTP.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                + symbol,
                params={
                    "range": "5d",
                    "interval": "15m"
                },
                timeout=5
            )

            data = response.json()

            result = (
                data["chart"]["result"][0]
            )

            quote = (
                result["indicators"]
                ["quote"][0]
            )

            closes = [
                float(x)
                for x in quote["close"]
                if x is not None
            ]

            if len(closes) < 30:
                continue

            fake_klines = [
                [
                    0,
                    0,
                    max(closes[-30:]),
                    min(closes[-30:]),
                    closes[-1],
                    0
                ]
                for _ in range(30)
            ]

            a = analyze_klines(
                fake_klines
            )

            out.append({
                "symbol": symbol,
                "price": closes[-1],

                "change":
                    (
                        closes[-1]
                        / closes[-2]
                        - 1
                    ) * 100,

                "signal": a["signal"],
                "direction":
                    a["direction"],
                "score":
                    a["score"],

                "source":
                    "Yahoo Finance"
            })

        except Exception:
            pass

    return jsonify({
        "ok": True,
        "signals": out
    })


# =========================================================
# SAUDI MARKET
# =========================================================

SAUDI_MARKET_SERVER = os.getenv(
    "SAUDI_MARKET_SERVER",
    "https://mwq-tdwl.onrender.com"
)


@app.get("/api/saudi/signals")
def saudi_signals():

    try:

        response = HTTP.get(
            SAUDI_MARKET_SERVER
            + "/api/signals",
            timeout=12
        )

        return (
            jsonify(
                response.json()
            ),
            response.status_code
        )

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


@app.get("/api/signals")
def signals_alias():

    return saudi_signals()


# =========================================================
# NEWS
# =========================================================

def clean_html(text):

    return re.sub(
        r"\s+",
        " ",
        html.unescape(
            re.sub(
                r"<[^>]+>",
                " ",
                text or ""
            )
        )
    ).strip()


@app.get("/api/news")
def news():

    now = time.time()

    with CACHE_LOCK:

        if (
            NEWS_CACHE["items"]
            and now - NEWS_CACHE["ts"] < 600
        ):

            return jsonify({
                "ok": True,
                "news":
                    NEWS_CACHE["items"],
                "cached": True
            })

    items = []

    try:

        response = HTTP.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            timeout=6
        )

        root = ET.fromstring(
            response.content
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

            published = (
                item.findtext(
                    "pubDate"
                )
                or ""
            )

            description = clean_html(
                item.findtext(
                    "description"
                )
            )

            if title and link:

                items.append({
                    "title": title,
                    "link": link,
                    "source": "CoinDesk",
                    "published": published,
                    "description":
                        description[:220]
                })

    except Exception:
        pass

    with CACHE_LOCK:

        NEWS_CACHE.update({
            "ts": time.time(),
            "items": items
        })

    return jsonify({
        "ok": True,
        "news": items,
        "cached": False,
        "message":
            None
            if items
            else
            "تعذر جلب الأخبار الآن"
    })


# =========================================================
# START DATABASE
# =========================================================

init_db()


# =========================================================
# RUN
# =========================================================

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
