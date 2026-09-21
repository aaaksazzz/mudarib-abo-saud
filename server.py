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


# ============================================================
# APP
# ============================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not SECRET_KEY:
    print("WARNING: SECRET_KEY غير مضبوط في Render")
    SECRET_KEY = secrets.token_hex(32)

app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_PATH="/",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# ============================================================
# ENV
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
).strip()

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    ""
).strip()

PAYMENT_ADDRESS = os.getenv(
    "TRC20_ADDRESS",
    "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"
).strip()


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


# ============================================================
# PASSWORD
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
        f"pbkdf2$"
        f"{iterations}$"
        f"{salt.hex()}$"
        f"{digest.hex()}"
    )


def verify_password(password, stored):

    try:

        _, iterations, salt_hex, digest_hex = stored.split(
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
# USER
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

    uid = session.get("user_id")

    if not uid:
        return None

    try:
        return user_row(uid)

    except Exception:
        return None


# ============================================================
# ADMIN AUTH
# ============================================================

def generate_admin_token():

    """
    رمز إداري ثابت وموقّع.
    لا يتم تخزين كلمة المرور داخل المتصفح.
    """

    payload = f"{ADMIN_USERNAME}:admin"

    signature = hmac.new(
        SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    return f"{payload}:{signature}"


def verify_admin_token(token):

    if not token:
        return False

    expected = generate_admin_token()

    return hmac.compare_digest(
        str(token),
        expected
    )


def get_admin_token():

    token = request.headers.get(
        "X-Admin-Token",
        ""
    ).strip()

    if token:
        return token

    auth = request.headers.get(
        "Authorization",
        ""
    ).strip()

    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return ""


def is_admin():

    # الطريقة الجديدة
    token = get_admin_token()

    if verify_admin_token(token):
        return True

    # دعم الجلسة القديمة أيضًا
    return bool(session.get("admin"))


def admin_required():

    if not is_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 401

    return None


# ============================================================
# BINANCE
# ============================================================

def binance_get(
    path,
    params=None,
    timeout=4.0
):

    last_error = "تعذر الاتصال بـ Binance"

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

    raise RuntimeError(last_error)


# ============================================================
# MARKETS
# ============================================================

def market_symbols():

    now = time.time()

    with CACHE_LOCK:

        if (
            MARKET_CACHE["symbols"]
            and now - MARKET_CACHE["ts"] < 900
        ):
            return MARKET_CACHE["symbols"]

    data = binance_get(
        "/api/v3/exchangeInfo",
        timeout=5
    )

    result = []

    for s in data.get("symbols", []):

        symbol = s.get("symbol", "")
        base = s.get("baseAsset", "")

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        if s.get("isSpotTradingAllowed") is False:
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

def ema(values, period):

    if not values:
        return None

    if len(values) < period:
        period = len(values)

    seed = sum(
        values[:period]
    ) / period

    e = seed

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

        gains.append(max(d, 0))
        losses.append(max(-d, 0))

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
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    return 100 - (
        100 /
        (
            1
            + avg_gain / avg_loss
        )
    )


def atr(klines, period=14):

    if len(klines) < 2:
        return 0.0

    trs = []

    for i in range(1, len(klines)):

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
# ANALYSIS
# ============================================================

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

    rv = rsi(closes, 14)

    e12 = ema(closes, 12)
    e26 = ema(closes, 26)

    macd_line = (
        (e12 or 0)
        - (e26 or 0)
    )

    macd_series = []

    for i in range(
        max(26, len(closes) - 80),
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
        ema(macd_series, 9)
        if macd_series
        else 0
    )

    macd_hist = (
        macd_line
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


def ticker24():

    return binance_get(
        "/api/v3/ticker/24hr",
        timeout=5
    )


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


# ============================================================
# WEBSITE
# ============================================================

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
        "time": int(time.time())
    })


# ============================================================
# AUTH
# ============================================================

@app.post("/api/auth/register")
def register():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    name = str(
        data.get("name", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
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
                    INSERT INTO users
                    (
                        name,
                        email,
                        password_hash
                    )
                    VALUES
                    (%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        name,
                        email,
                        hash_password(password)
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


@app.post("/api/auth/login")
def login():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
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


@app.post("/api/admin/login")
def admin_login():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if (
        hmac.compare_digest(
            username,
            ADMIN_USERNAME
        )
        and hmac.compare_digest(
            password,
            ADMIN_PASSWORD
        )
    ):

        token = generate_admin_token()

        # نخلي الجلسة تعمل أيضًا
        session.clear()
        session.permanent = True
        session["admin"] = True

        return jsonify({
            "ok": True,
            "admin": True,
            "token": token
        })

    return jsonify({
        "ok": False,
        "message":
            "بيانات الأدمن غير صحيحة"
    }), 401


@app.get("/api/admin/me")
def admin_me():

    if is_admin():

        return jsonify({
            "ok": True,
            "admin": True
        })

    return jsonify({
        "ok": True,
        "admin": False
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


# ============================================================
# ADMIN STATS
# ============================================================

@app.get("/api/admin/stats")
def admin_stats():

    denied = admin_required()

    if denied:
        return denied

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
                    WHERE
                        plan <> 'free'
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

@app.get("/api/admin/users")
def admin_users():

    denied = admin_required()

    if denied:
        return denied

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


@app.post("/api/admin/users/<int:user_id>/plan")
def admin_plan(user_id):

    denied = admin_required()

    if denied:
        return denied

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

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


# ============================================================
# ADMIN PAYMENTS
# ============================================================

@app.get("/api/admin/payments")
def admin_payments():

    denied = admin_required()

    if denied:
        return denied

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
                    ON u.id = p.user_id

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
                    "created_at": r[9].isoformat(),
                    "reviewed_at":
                        (
                            r[10].isoformat()
                            if r[10]
                            else None
                        )
                }

                for r in rows
            ]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


@app.post("/api/admin/payments/<int:payment_id>/review")
def review_payment(payment_id):

    denied = admin_required()

    if denied:
        return denied

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

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

                    now = datetime.now(
                        timezone.utc
                    )

                    if old:
                        base = max(
                            old,
                            now
                        )
                    else:
                        base = now

                    expires = (
                        base
                        + timedelta(
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
# SUBSCRIPTIONS
# ============================================================

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

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

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
                    INSERT INTO payment_requests
                    (
                        user_id,
                        plan,
                        amount,
                        network,
                        txid
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
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

        now = datetime.now(
            timezone.utc
        )

        active = (
            u[3] != "free"
            and u[4] is not None
            and u[4] > now
        )

        return jsonify({
            "ok": True,
            "active": bool(active),
            "plan": u[3],
            "expires": (
                u[4].isoformat()
                if u[4]
                else None
            ),
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
                        (
                            r[6].isoformat()
                            if r[6]
                            else None
                        )
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
# SETTINGS
# ============================================================

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
                (
                    json.loads(row[0])
                    if row
                    else {}
                )
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

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

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
                    INSERT INTO settings
                    (key,value)
                    VALUES
                    (%s,%s)

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
# BINANCE API
# ============================================================

@app.get("/api/binance/test")
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


@app.get("/api/binance/markets")
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


@app.get("/api/binance/prices")
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

            if t.get("symbol") in wanted:

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


@app.get("/api/binance/price")
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
                "symbol": symbol
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


@app.get("/api/binance/klines")
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
                "symbol": symbol,
                "interval": interval,
                "limit": 210
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


@app.get("/api/binance/analysis")
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
                "symbol": symbol,
                "interval": interval,
                "limit": 230
            },
            timeout=5
        )

        a = analyze_klines(k)

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


@app.get("/api/binance/scan")
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
        and now - cached["ts"] < 45
    ):

        payload = dict(
            cached["payload"]
        )

        payload["cached"] = True

        return jsonify(payload)

    try:

        markets_set = {
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

            if s not in markets_set:
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

        selected = candidates[:cap]

        results = []

        def worker(item):

            qv, t = item

            symbol = t["symbol"]

            k = binance_get(
                "/api/v3/klines",
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": 210
                },
                timeout=3.5
            )

            a = analyze_klines(k)

            return {
                "symbol": symbol,

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

                "volume": qv,

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
                        time.time() * 1000
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
            key=lambda x: x["volume"],
            reverse=True
        )

        if not results:

            raise RuntimeError(
                "تعذر جلب بيانات العملات الآن"
            )

        payload = {
            "ok": True,
            "interval": interval,
            "count": len(results),
            "requested": requested,
            "scanned": len(selected),
            "results": results,
            "cached": False
        }

        with CACHE_LOCK:

            SCAN_CACHE[interval] = {
                "ts": time.time(),
                "payload": payload
            }

        return jsonify(payload)

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

            return jsonify(payload)

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# NEWS
# ============================================================

def clean_html(text):

    text = re.sub(
        r"<[^>]+>",
        " ",
        text or ""
    )

    return re.sub(
        r"\s+",
        " ",
        html.unescape(text)
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
                        "title": title,
                        "link": link,
                        "source": source,
                        "published": pub,
                        "description":
                            desc[:220]
                    })

        except Exception:
            pass

    with CACHE_LOCK:

        NEWS_CACHE.update({
            "ts": time.time(),
            "items": items[:12]
        })

    return jsonify({
        "ok": True,
        "news": items[:12],
        "cached": False,
        "message":
            None
            if items
            else
            "تعذر جلب الأخبار الآن"
    })


# ============================================================
# START
# ============================================================

init_db()


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
