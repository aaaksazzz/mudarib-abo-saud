import os
import re
import time
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import psycopg

from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
    render_template,
)


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY"
)

PORT = int(os.getenv("PORT", "8080"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
).strip()

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    ""
)

PAYMENT_ADDRESS = os.getenv(
    "TRC20_ADDRESS",
    "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"
)

OKX_BASE = "https://www.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 Mudarib-Abo-Saud/4.0"
})

CACHE = {}
CACHE_LOCK = threading.Lock()

CACHE_SECONDS = 120


# =========================================================
# SESSION
# =========================================================

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30)
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
    }
}


# =========================================================
# HELPERS
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def cache_get(key):
    with CACHE_LOCK:
        item = CACHE.get(key)

        if not item:
            return None

        if time.time() - item["time"] > CACHE_SECONDS:
            return None

        return item["data"]


def cache_set(key, data):
    with CACHE_LOCK:
        CACHE[key] = {
            "time": time.time(),
            "data": data
        }


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def pct(a, b):
    if not b:
        return 0.0

    return ((a - b) / b) * 100.0


def fmt_price(value):
    value = safe_float(value)

    if value >= 1000:
        return round(value, 2)

    if value >= 1:
        return round(value, 4)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


def normalize_signal(score):

    if score >= 80:
        return "شراء قوي"

    if score >= 65:
        return "شراء"

    if score <= 20:
        return "بيع قوي"

    if score <= 35:
        return "بيع"

    return "حيادي"


def hash_password(password):
    return hashlib.sha256(
        str(password).encode("utf-8")
    ).hexdigest()


def json_error(message, status=400):
    return jsonify({
        "ok": False,
        "message": message
    }), status


# =========================================================
# DATABASE
# =========================================================

def db():

    if not DATABASE_URL:
        return None

    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():

    if not DATABASE_URL:
        print(
            "WARNING: DATABASE_URL غير موجود - "
            "الموقع سيعمل بدون تسجيل حسابات"
        )
        return

    try:

        conn = db()

        if not conn:
            return

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    subscription_until TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS name TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS email TEXT
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                users_email_unique_idx
                ON users(email)
                WHERE email IS NOT NULL
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    txid TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

        conn.commit()
        conn.close()

        print("DATABASE OK")

    except Exception as e:

        print("DATABASE ERROR:", e)


# =========================================================
# AUTH HELPERS
# =========================================================

def current_user():

    username = session.get("user")

    if not username:
        return None

    if username == ADMIN_USERNAME:
        return {
            "username": username,
            "name": "Admin",
            "email": None,
            "admin": True,
            "subscriptionUntil": None
        }

    if not DATABASE_URL:
        return {
            "username": username,
            "name": username,
            "email": None,
            "admin": bool(
                session.get("admin")
            ),
            "subscriptionUntil": None
        }

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    username,
                    name,
                    email,
                    is_admin,
                    subscription_until
                FROM users
                WHERE username=%s
            """, (username,))

            row = cur.fetchone()

        conn.close()

        if not row:
            return None

        return {
            "username": row[0],
            "name": row[1] or row[0],
            "email": row[2],
            "admin": bool(row[3]),
            "subscriptionUntil": (
                row[4].isoformat()
                if row[4]
                else None
            )
        }

    except Exception:
        return None


def require_login():

    if not session.get("user"):
        return json_error(
            "سجل دخول أولاً",
            401
        )

    return None


def require_admin():

    return bool(
        session.get("admin")
        and session.get("user")
    )


# =========================================================
# AUTH - REGISTER
# =========================================================

def do_register():

    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get("name", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if len(name) < 2:
        return json_error(
            "فضلاً اكتب الاسم بشكل صحيح"
        )

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        email
    ):
        return json_error(
            "البريد الإلكتروني غير صحيح"
        )

    if len(password) < 6:
        return json_error(
            "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
        )

    if not DATABASE_URL:
        return json_error(
            "قاعدة البيانات غير مفعلة في السيرفر",
            500
        )

    if not username:
        username = email

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id
                FROM users
                WHERE username=%s
                   OR email=%s
            """, (
                username,
                email
            ))

            if cur.fetchone():

                conn.close()

                return json_error(
                    "البريد الإلكتروني أو اسم المستخدم مستخدم مسبقاً",
                    409
                )

            cur.execute("""
                INSERT INTO users
                (
                    username,
                    password,
                    name,
                    email
                )
                VALUES(%s,%s,%s,%s)
            """, (
                username,
                hash_password(password),
                name,
                email
            ))

        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "message": "تم إنشاء الحساب بنجاح"
        })

    except Exception as e:

        print(
            "REGISTER ERROR:",
            e
        )

        return json_error(
            "تعذر إنشاء الحساب",
            500
        )


@app.post("/api/auth/register")
@app.post("/api/register")
def register():
    return do_register()


# =========================================================
# AUTH - LOGIN
# =========================================================

def do_login():

    data = request.get_json(
        silent=True
    ) or {}

    email = str(
        data.get("email", "")
    ).strip().lower()

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    # دعم تسجيل الدخول بالإيميل أو اسم المستخدم
    identity = email or username

    # ADMIN
    if (
        identity == ADMIN_USERNAME
        and ADMIN_PASSWORD
        and password == ADMIN_PASSWORD
    ):

        session.clear()
        session.permanent = True

        session["user"] = ADMIN_USERNAME
        session["admin"] = True

        return jsonify({
            "ok": True,
            "user": ADMIN_USERNAME,
            "username": ADMIN_USERNAME,
            "admin": True
        })

    if not identity:
        return json_error(
            "أدخل البريد الإلكتروني"
        )

    if not DATABASE_URL:
        return json_error(
            "قاعدة البيانات غير مفعلة في السيرفر",
            500
        )

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    username,
                    password,
                    name,
                    email,
                    is_admin,
                    subscription_until
                FROM users
                WHERE LOWER(COALESCE(email,''))=%s
                   OR LOWER(username)=%s
                LIMIT 1
            """, (
                identity.lower(),
                identity.lower()
            ))

            row = cur.fetchone()

        conn.close()

        if not row:
            return json_error(
                "بيانات الدخول غير صحيحة",
                401
            )

        (
            saved_username,
            saved_password,
            saved_name,
            saved_email,
            is_admin,
            subscription_until
        ) = row

        if saved_password != hash_password(password):

            return json_error(
                "بيانات الدخول غير صحيحة",
                401
            )

        session.clear()
        session.permanent = True

        session["user"] = saved_username
        session["admin"] = bool(is_admin)

        return jsonify({
            "ok": True,
            "user": saved_username,
            "username": saved_username,
            "name": saved_name or saved_username,
            "email": saved_email,
            "admin": bool(is_admin),
            "subscriptionUntil": (
                subscription_until.isoformat()
                if subscription_until
                else None
            )
        })

    except Exception as e:

        print(
            "LOGIN ERROR:",
            e
        )

        return json_error(
            "خطأ في قاعدة البيانات",
            500
        )


@app.post("/api/auth/login")
@app.post("/api/login")
def login():
    return do_login()


# =========================================================
# AUTH - ME
# =========================================================

@app.get("/api/auth/me")
@app.get("/api/me")
def me():

    user = current_user()

    if not user:

        return jsonify({
            "ok": True,
            "user": None,
            "admin": False
        })

    return jsonify({
        "ok": True,
        "user": user.get("username"),
        "username": user.get("username"),
        "name": user.get("name"),
        "email": user.get("email"),
        "admin": user.get("admin", False),
        "subscriptionUntil": user.get(
            "subscriptionUntil"
        )
    })


# =========================================================
# AUTH - LOGOUT
# =========================================================

@app.post("/api/auth/logout")
@app.post("/api/logout")
def logout():

    session.clear()

    return jsonify({
        "ok": True,
        "message": "تم تسجيل الخروج"
    })


# =========================================================
# ADMIN AUTH
# =========================================================

@app.post("/api/admin/login")
def admin_login():

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if not ADMIN_PASSWORD:
        return json_error(
            "ADMIN_PASSWORD غير موجود في Environment Variables",
            500
        )

    if (
        username != ADMIN_USERNAME
        or password != ADMIN_PASSWORD
    ):
        return json_error(
            "بيانات الأدمن غير صحيحة",
            401
        )

    session.clear()
    session.permanent = True

    session["user"] = ADMIN_USERNAME
    session["admin"] = True

    return jsonify({
        "ok": True,
        "admin": True,
        "user": ADMIN_USERNAME
    })


@app.get("/api/admin/me")
def admin_me():

    return jsonify({
        "ok": True,
        "admin": require_admin(),
        "user": (
            session.get("user")
            if require_admin()
            else None
        )
    })


@app.post("/api/admin/logout")
def admin_logout():

    session.clear()

    return jsonify({
        "ok": True
    })


# =========================================================
# OKX
# =========================================================

def okx_get(path, params=None):

    r = HTTP.get(
        OKX_BASE + path,
        params=params or {},
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    if data.get("code") != "0":

        raise RuntimeError(
            data.get(
                "msg",
                "OKX API error"
            )
        )

    return data.get(
        "data",
        []
    )


def okx_instruments(inst_type):

    key = (
        "okx_instruments_"
        + inst_type
    )

    cached = cache_get(key)

    if cached:
        return cached

    rows = okx_get(
        "/api/v5/public/instruments",
        {
            "instType": inst_type
        }
    )

    cache_set(
        key,
        rows
    )

    return rows


def okx_tickers(inst_type):

    return okx_get(
        "/api/v5/market/tickers",
        {
            "instType": inst_type
        }
    )


def okx_candles(
    inst_id,
    bar="15m",
    limit=120
):

    rows = okx_get(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit)
        }
    )

    result = []

    for x in reversed(rows):

        if len(x) < 6:
            continue

        result.append({
            "t": int(x[0]),
            "o": safe_float(x[1]),
            "h": safe_float(x[2]),
            "l": safe_float(x[3]),
            "c": safe_float(x[4]),
            "v": safe_float(x[5])
        })

    return result


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    k = 2 / (period + 1)

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            price * k
            +
            value * (1 - k)
        )

    return value


def rsi(values, period=14):

    if len(values) <= period:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def analyze_candles(candles):

    if len(candles) < 30:
        raise RuntimeError(
            "بيانات غير كافية"
        )

    closes = [
        x["c"]
        for x in candles
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
    ) if len(closes) >= 200 else None

    r = rsi(closes)

    score = 50

    if e20:

        if price > e20:
            score += 10
        else:
            score -= 10

    if e50:

        if price > e50:
            score += 10
        else:
            score -= 10

    if e200:

        if price > e200:
            score += 15
        else:
            score -= 15

    if r >= 70:

        score -= 8

    elif r >= 55:

        score += 10

    elif r <= 30:

        score += 8

    elif r <= 45:

        score -= 5

    score = max(
        0,
        min(100, score)
    )

    signal = normalize_signal(
        score
    )

    direction = (
        "LONG"
        if score >= 55
        else
        "SHORT"
        if score <= 45
        else
        "WAIT"
    )

    entry = price

    return {
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(
            score / 10,
            1
        ),
        "price": fmt_price(price),
        "rsi": round(r, 2),
        "ema20": (
            fmt_price(e20)
            if e20
            else None
        ),
        "ema50": (
            fmt_price(e50)
            if e50
            else None
        ),
        "ema200": (
            fmt_price(e200)
            if e200
            else None
        ),
        "entry": fmt_price(entry),
        "tp1": fmt_price(
            price * 1.01
        ),
        "tp2": fmt_price(
            price * 1.02
        ),
        "tp3": fmt_price(
            price * 1.03
        ),
        "sl": fmt_price(
            price * 0.98
        )
    }


# =========================================================
# SPOT
# =========================================================

STABLES = {
    "USDT",
    "USDC",
    "DAI",
    "FDUSD",
    "USDE",
    "TUSD",
    "USDG"
}


def spot_symbols():

    instruments = okx_instruments(
        "SPOT"
    )

    result = []

    for x in instruments:

        inst = x.get(
            "instId",
            ""
        )

        if not inst.endswith(
            "-USDT"
        ):
            continue

        if x.get("state") != "live":
            continue

        base = inst.split("-")[0]

        if base in STABLES:
            continue

        result.append({
            "symbol": inst,
            "name": base
        })

    return result


def spot_scan(interval="15m"):

    key = (
        "spot_scan_"
        + interval
    )

    cached = cache_get(key)

    if cached:
        return cached

    symbols = spot_symbols()

    tickers = []

    try:
        tickers = okx_tickers(
            "SPOT"
        )
    except Exception as e:
        print(
            "OKX spot ticker error:",
            e
        )

    volume_map = {}

    for t in tickers:

        inst = t.get(
            "instId"
        )

        if inst:

            volume_map[inst] = {
                "price": safe_float(
                    t.get("last")
                ),
                "volume": safe_float(
                    t.get("vol24h")
                ),
                "quoteVolume": safe_float(
                    t.get("volCcy24h")
                )
            }

    candidates = []

    for s in symbols:

        info = volume_map.get(
            s["symbol"],
            {}
        )

        quote_volume = safe_float(
            info.get(
                "quoteVolume"
            )
        )

        if quote_volume >= 1_000_000:

            candidates.append({
                **s,
                **info
            })

    candidates.sort(
        key=lambda x: x.get(
            "quoteVolume",
            0
        ),
        reverse=True
    )

    candidates = candidates[:80]

    results = []

    def worker(item):

        try:

            candles = okx_candles(
                item["symbol"],
                interval,
                100
            )

            analysis = analyze_candles(
                candles
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                "symbol": item["symbol"],
                "name": item["name"],
                "price": analysis["price"],
                "change": round(
                    change,
                    2
                ),
                "change24h": round(
                    safe_float(
                        item.get(
                            "price",
                            0
                        )
                    ),
                    4
                ),
                "signal": analysis["signal"],
                "direction": analysis["direction"],
                "score": analysis["score"],
                "score10": analysis["score10"],
                "rsi": analysis["rsi"],
                "ema20": analysis["ema20"],
                "ema50": analysis["ema50"],
                "ema200": analysis["ema200"],
                "entry": analysis["entry"],
                "tp1": analysis["tp1"],
                "tp2": analysis["tp2"],
                "tp3": analysis["tp3"],
                "sl": analysis["sl"],
                "volume": item.get(
                    "volume",
                    0
                ),
                "volume24h": item.get(
                    "quoteVolume",
                    0
                ),
                "interval": interval,
                "market": "spot",
                "updatedAt": now_utc().isoformat()
            }

        except Exception as e:

            return None

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item
            )
            for item in candidates
        ]

        for future in as_completed(
            futures
        ):

            try:

                row = future.result()

                if row:
                    results.append(row)

            except Exception:
                pass

    results.sort(
        key=lambda x: x.get(
            "score",
            0
        ),
        reverse=True
    )

    data = {
        "ok": True,
        "market": "spot",
        "interval": interval,
        "universeCount": len(symbols),
        "scannedCount": len(candidates),
        "count": len(results),
        "results": results
    }

    cache_set(
        key,
        data
    )

    return data


@app.get("/api/spot/scan")
@app.get("/api/spot/signals")
def spot_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    if interval not in {
        "5m",
        "15m",
        "1H",
        "4H",
        "1D"
    }:
        interval = "15m"

    try:

        return jsonify(
            spot_scan(interval)
        )

    except Exception as e:

        return json_error(
            str(e),
            500
        )


@app.get("/api/spot/analysis")
def spot_analysis():

    symbol = request.args.get(
        "symbol",
        "BTC-USDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        candles = okx_candles(
            symbol,
            interval,
            200
        )

        analysis = analyze_candles(
            candles
        )

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "analysis": analysis,
            "candles": candles[-100:]
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# FUTURES
# =========================================================

def futures_symbols():

    instruments = okx_instruments(
        "SWAP"
    )

    result = []

    for x in instruments:

        inst = x.get(
            "instId",
            ""
        )

        if not inst.endswith(
            "-USDT-SWAP"
        ):
            continue

        if x.get("state") != "live":
            continue

        result.append({
            "symbol": inst,
            "name": inst.replace(
                "-USDT-SWAP",
                ""
            )
        })

    return result


def futures_scan(interval="15m"):

    key = (
        "futures_scan_"
        + interval
    )

    cached = cache_get(key)

    if cached:
        return cached

    symbols = futures_symbols()

    try:
        tickers = okx_tickers(
            "SWAP"
        )
    except Exception:
        tickers = []

    volumes = {}

    for t in tickers:

        inst = t.get(
            "instId"
        )

        if inst:

            volumes[inst] = safe_float(
                t.get("volCcy24h")
            )

    candidates = []

    for x in symbols:

        candidates.append({
            **x,
            "volume24h": volumes.get(
                x["symbol"],
                0
            )
        })

    candidates.sort(
        key=lambda x: x[
            "volume24h"
        ],
        reverse=True
    )

    candidates = candidates[:80]

    results = []

    def worker(item):

        try:

            candles = okx_candles(
                item["symbol"],
                interval,
                100
            )

            analysis = analyze_candles(
                candles
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                "symbol": item["symbol"],
                "name": item["name"],
                "price": analysis["price"],
                "change": round(
                    change,
                    2
                ),
                "change24h": round(
                    change,
                    2
                ),
                "signal": analysis["signal"],
                "direction": analysis["direction"],
                "score": analysis["score"],
                "score10": analysis["score10"],
                "rsi": analysis["rsi"],
                "ema20": analysis["ema20"],
                "ema50": analysis["ema50"],
                "ema200": analysis["ema200"],
                "entry": analysis["entry"],
                "tp1": analysis["tp1"],
                "tp2": analysis["tp2"],
                "tp3": analysis["tp3"],
                "sl": analysis["sl"],
                "volume": 0,
                "volume24h": item["volume24h"],
                "interval": interval,
                "market": "futures",
                "updatedAt": now_utc().isoformat()
            }

        except Exception:
            return None

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item
            )
            for item in candidates
        ]

        for future in as_completed(
            futures
        ):

            try:

                row = future.result()

                if row:
                    results.append(row)

            except Exception:
                pass

    results.sort(
        key=lambda x: x.get(
            "score",
            0
        ),
        reverse=True
    )

    data = {
        "ok": True,
        "market": "futures",
        "interval": interval,
        "universeCount": len(symbols),
        "scannedCount": len(candidates),
        "count": len(results),
        "results": results
    }

    cache_set(
        key,
        data
    )

    return data


@app.get("/api/futures/scan")
def futures_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    if interval not in {
        "5m",
        "15m",
        "1H",
        "4H",
        "1D"
    }:
        interval = "15m"

    try:

        return jsonify(
            futures_scan(interval)
        )

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# YAHOO
# =========================================================

def yahoo_interval(interval):

    return {
        "5m": "5m",
        "15m": "15m",
        "1H": "60m",
        "1h": "60m",
        "1D": "1d",
        "1d": "1d"
    }.get(
        interval,
        "15m"
    )


def yahoo_range(interval):

    return {
        "5m": "5d",
        "15m": "10d",
        "1H": "30d",
        "1h": "30d",
        "1D": "1y",
        "1d": "1y"
    }.get(
        interval,
        "10d"
    )


def yahoo_klines(
    symbol,
    interval
):

    url = (
        YAHOO_BASE
        + "/v8/finance/chart/"
        + requests.utils.quote(
            symbol,
            safe=""
        )
    )

    r = HTTP.get(
        url,
        params={
            "interval": yahoo_interval(
                interval
            ),
            "range": yahoo_range(
                interval
            ),
            "events": "history"
        },
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    result = (
        data.get(
            "chart",
            {}
        ).get(
            "result"
        )
    )

    if not result:
        raise RuntimeError(
            "لا توجد بيانات"
        )

    result = result[0]

    timestamps = result.get(
        "timestamp",
        []
    )

    quote = (
        result.get(
            "indicators",
            {}
        ).get(
            "quote",
            [{}]
        )[0]
    )

    candles = []

    for i, ts in enumerate(
        timestamps
    ):

        try:

            o = quote["open"][i]
            h = quote["high"][i]
            l = quote["low"][i]
            c = quote["close"][i]

            volumes = quote.get(
                "volume",
                []
            )

            v = (
                volumes[i]
                if i < len(volumes)
                else 0
            )

            if None in (
                o,
                h,
                l,
                c
            ):
                continue

            candles.append({
                "t": int(ts) * 1000,
                "o": safe_float(o),
                "h": safe_float(h),
                "l": safe_float(l),
                "c": safe_float(c),
                "v": safe_float(v)
            })

        except Exception:
            continue

    if len(candles) < 30:

        raise RuntimeError(
            "بيانات غير كافية"
        )

    return candles


# =========================================================
# SAUDI MARKET
# =========================================================

SAUDI_SYMBOLS = [
    ("2222.SR", "أرامكو السعودية"),
    ("1120.SR", "مصرف الراجحي"),
    ("1180.SR", "الأهلي السعودي"),
    ("2010.SR", "سابك"),
    ("1211.SR", "معادن"),
    ("7010.SR", "stc"),
    ("1150.SR", "مصرف الإنماء"),
    ("1060.SR", "مصرف البلاد"),
    ("1010.SR", "بنك الرياض"),
    ("1080.SR", "البنك العربي الوطني"),
    ("1030.SR", "البنك السعودي للاستثمار"),
    ("1050.SR", "بنك الأول"),
    ("1111.SR", "مجموعة تداول"),
    ("2020.SR", "سابك للمغذيات الزراعية"),
    ("2030.SR", "المتقدمة"),
    ("2040.SR", "الخزف السعودي"),
    ("2050.SR", "التصنيع"),
    ("2090.SR", "الجبس"),
    ("2110.SR", "الكابلات السعودية"),
    ("2170.SR", "اللجين"),
    ("2180.SR", "فيبكو"),
    ("2200.SR", "أنابيب السعودية"),
    ("2210.SR", "نماء للكيماويات"),
    ("2220.SR", "معدنية"),
    ("2240.SR", "الزامل"),
    ("2250.SR", "مجموعة فتيحي"),
    ("2290.SR", "ينساب"),
    ("2300.SR", "صناعة الورق"),
    ("2310.SR", "سبكيم"),
    ("2320.SR", "البابطين"),
    ("2340.SR", "العربية"),
    ("2350.SR", "كيان"),
    ("2360.SR", "الفخارية"),
    ("2370.SR", "مسك"),
    ("2380.SR", "رابغ للتكرير"),
    ("3001.SR", "أسمنت العربية"),
    ("3002.SR", "أسمنت نجران"),
    ("3003.SR", "أسمنت المدينة"),
    ("3004.SR", "أسمنت الشمالية"),
    ("3005.SR", "أسمنت أم القرى"),
    ("3007.SR", "أسمنت الجنوب"),
    ("3008.SR", "أسمنت القصيم"),
    ("3010.SR", "أسمنت العربية"),
    ("3020.SR", "أسمنت اليمامة"),
    ("3030.SR", "أسمنت السعودية"),
    ("3040.SR", "أسمنت القصيم"),
    ("3050.SR", "أسمنت ينبع"),
    ("4001.SR", "أسواق العثيم"),
    ("4002.SR", "المواساة"),
    ("4003.SR", "إكسترا"),
    ("4004.SR", "دله الصحية"),
    ("4005.SR", "رعاية"),
    ("4007.SR", "الحمادي"),
    ("4008.SR", "ساكو"),
    ("4009.SR", "المستشفى السعودي الألماني"),
    ("4010.SR", "دار الأركان"),
    ("4012.SR", "الأندلس"),
    ("4013.SR", "الحبيب"),
    ("4020.SR", "العقارية"),
    ("4030.SR", "البحري"),
    ("4031.SR", "الخدمات الأرضية"),
    ("4040.SR", "جرير"),
    ("4050.SR", "ساكو"),
    ("4071.SR", "العربية للتعهدات"),
    ("4090.SR", "طيبة"),
    ("4100.SR", "مكة"),
    ("4150.SR", "التعمير"),
    ("4190.SR", "جرير"),
    ("4200.SR", "الدريس"),
    ("4210.SR", "الأبحاث والإعلام"),
    ("4220.SR", "إعمار"),
    ("4230.SR", "البحر الأحمر"),
    ("4260.SR", "بدجت"),
    ("4280.SR", "المملكة"),
    ("4310.SR", "مدينة المعرفة"),
    ("5110.SR", "كهرباء السعودية"),
    ("6010.SR", "نادك"),
    ("6020.SR", "جاكو"),
    ("6040.SR", "تبوك الزراعية"),
    ("6050.SR", "الأسماك"),
    ("6070.SR", "الجوف"),
    ("6090.SR", "جازادكو"),
    ("7020.SR", "اتحاد اتصالات"),
    ("7030.SR", "زين السعودية"),
    ("7040.SR", "عذيب"),
    ("7200.SR", "الدوائية"),
    ("7201.SR", "بحر العرب"),
    ("8010.SR", "التعاونية"),
    ("8020.SR", "ملاذ"),
    ("8040.SR", "ولاء"),
    ("8060.SR", "الدرع العربي"),
    ("8100.SR", "سايكو"),
    ("8160.SR", "التأمين العربية"),
    ("8200.SR", "الإعادة السعودية"),
    ("8230.SR", "تكافل الراجحي"),
    ("8300.SR", "الوطنية")
]


def yahoo_scan(
    symbols,
    interval
):

    results = []

    def worker(item):

        try:

            candles = yahoo_klines(
                item["symbol"],
                interval
            )

            analysis = analyze_candles(
                candles
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                "symbol": item["symbol"],
                "name": item["name"],
                "price": analysis["price"],
                "change": round(
                    change,
                    2
                ),
                "change24h": round(
                    change,
                    2
                ),
                "signal": analysis["signal"],
                "direction": analysis["direction"],
                "score": analysis["score"],
                "score10": analysis["score10"],
                "rsi": analysis["rsi"],
                "ema20": analysis["ema20"],
                "ema50": analysis["ema50"],
                "ema200": analysis["ema200"],
                "entry": analysis["entry"],
                "tp1": analysis["tp1"],
                "tp2": analysis["tp2"],
                "tp3": analysis["tp3"],
                "sl": analysis["sl"],
                "volume": candles[-1]["v"],
                "volume24h": 0,
                "interval": interval,
                "market": "other",
                "updatedAt": now_utc().isoformat()
            }

        except Exception:
            return None

    with ThreadPoolExecutor(
        max_workers=10
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item
            )
            for item in symbols
        ]

        for future in as_completed(
            futures
        ):

            try:

                row = future.result()

                if row:
                    results.append(row)

            except Exception:
                pass

    results.sort(
        key=lambda x: x.get(
            "score",
            0
        ),
        reverse=True
    )

    return results


# =========================================================
# SAUDI API
# =========================================================

@app.get("/api/saudi/scan")
def saudi_api():

    interval = request.args.get(
        "interval",
        "1D"
    )

    if interval not in {
        "15m",
        "1H",
        "1D"
    }:
        interval = "1D"

    key = (
        "saudi_"
        + interval
    )

    cached = cache_get(key)

    if cached:
        return jsonify(cached)

    results = yahoo_scan(
        [
            {
                "symbol": x[0],
                "name": x[1]
            }
            for x in SAUDI_SYMBOLS
        ],
        interval
    )

    data = {
        "ok": True,
        "market": "saudi",
        "interval": interval,
        "universeCount": len(
            SAUDI_SYMBOLS
        ),
        "scannedCount": len(
            SAUDI_SYMBOLS
        ),
        "count": len(results),
        "results": results
    }

    cache_set(
        key,
        data
    )

    return jsonify(data)


# =========================================================
# US MARKET
# =========================================================

def us_symbols():

    key = "us_symbols"

    cached = cache_get(key)

    if cached:
        return cached

    result = []

    urls = [
        "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    ]

    bad_words = [
        "WARRANT",
        "RIGHT",
        "UNIT",
        "NOTE",
        "DEBENTURE",
        "PREFERRED",
        "PREF ",
        "ETF"
    ]

    for url in urls:

        try:

            r = HTTP.get(
                url,
                timeout=15
            )

            r.raise_for_status()

            lines = r.text.splitlines()

            if not lines:
                continue

            headers = [
                x.strip()
                for x in lines[0].split("|")
            ]

            for line in lines[1:]:

                if not line.strip():
                    continue

                parts = line.split("|")

                row = dict(
                    zip(
                        headers,
                        parts
                    )
                )

                if "File Creation Time" in row:
                    continue

                if row.get(
                    "Test Issue"
                ) == "Y":
                    continue

                symbol = (
                    row.get("Symbol")
                    or
                    row.get("ACT Symbol")
                    or ""
                ).strip()

                name = (
                    row.get(
                        "Security Name"
                    )
                    or ""
                ).strip()

                if not symbol:
                    continue

                if not re.match(
                    r"^[A-Za-z0-9.\-]+$",
                    symbol
                ):
                    continue

                if any(
                    word in name.upper()
                    for word in bad_words
                ):
                    continue

                result.append({
                    "symbol": symbol.replace(
                        ".",
                        "-"
                    ),
                    "name": name
                })

        except Exception as e:

            print(
                "US symbol error:",
                e
            )

    unique = {}

    for item in result:
        unique[
            item["symbol"]
        ] = item

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda x: x["symbol"]
    )

    cache_set(
        key,
        result
    )

    return result


@app.get("/api/usmarket/signals")
def usmarket_api():

    interval = request.args.get(
        "interval",
        "1D"
    )

    if interval not in {
        "15m",
        "1H",
        "1D"
    }:
        interval = "1D"

    symbols = us_symbols()

    symbols = symbols[:300]

    key = (
        "us_"
        + interval
    )

    cached = cache_get(key)

    if cached:
        return jsonify(cached)

    results = yahoo_scan(
        symbols,
        interval
    )

    for row in results:
        row["market"] = "usmarket"

    data = {
        "ok": True,
        "market": "usmarket",
        "interval": interval,
        "universeCount": len(
            symbols
        ),
        "scannedCount": len(
            symbols
        ),
        "count": len(results),
        "results": results
    }

    cache_set(
        key,
        data
    )

    return jsonify(data)


# =========================================================
# FOREX
# =========================================================

FOREX_SYMBOLS = [
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("USDCAD=X", "USD/CAD"),
    ("NZDUSD=X", "NZD/USD"),
    ("EURGBP=X", "EUR/GBP"),
    ("EURJPY=X", "EUR/JPY"),
    ("EURCHF=X", "EUR/CHF"),
    ("EURAUD=X", "EUR/AUD"),
    ("EURCAD=X", "EUR/CAD"),
    ("EURNZD=X", "EUR/NZD"),
    ("GBPJPY=X", "GBP/JPY"),
    ("GBPCHF=X", "GBP/CHF"),
    ("GBPAUD=X", "GBP/AUD"),
    ("GBPCAD=X", "GBP/CAD"),
    ("GBPNZD=X", "GBP/NZD"),
    ("AUDJPY=X", "AUD/JPY"),
    ("AUDCHF=X", "AUD/CHF"),
    ("AUDCAD=X", "AUD/CAD"),
    ("AUDNZD=X", "AUD/NZD"),
    ("CADJPY=X", "CAD/JPY"),
    ("CADCHF=X", "CAD/CHF"),
    ("NZDJPY=X", "NZD/JPY"),
    ("NZDCHF=X", "NZD/CHF"),
    ("USDSEK=X", "USD/SEK"),
    ("USDNOK=X", "USD/NOK"),
    ("USDPLN=X", "USD/PLN"),
    ("USDTRY=X", "USD/TRY"),
    ("USDMXN=X", "USD/MXN"),
    ("USDZAR=X", "USD/ZAR"),
    ("USDSGD=X", "USD/SGD"),
    ("USDHKD=X", "USD/HKD"),
    ("USDCNH=X", "USD/CNH")
]


@app.get("/api/forex/signals")
def forex_api():

    interval = request.args.get(
        "interval",
        "1H"
    )

    if interval not in {
        "15m",
        "1H",
        "1D"
    }:
        interval = "1H"

    key = (
        "forex_"
        + interval
    )

    cached = cache_get(key)

    if cached:
        return jsonify(cached)

    symbols = [
        {
            "symbol": symbol,
            "name": name
        }
        for symbol, name
        in FOREX_SYMBOLS
    ]

    results = yahoo_scan(
        symbols,
        interval
    )

    for row in results:
        row["market"] = "forex"

    data = {
        "ok": True,
        "market": "forex",
        "interval": interval,
        "universeCount": len(symbols),
        "scannedCount": len(symbols),
        "count": len(results),
        "results": results
    }

    cache_set(
        key,
        data
    )

    return jsonify(data)


# =========================================================
# RECENT SPOT
# =========================================================

@app.get("/api/recent")
def recent_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        data = spot_scan(
            interval
        )

        recent = [
            x
            for x in data.get(
                "results",
                []
            )
            if x.get("signal")
            in {
                "شراء",
                "شراء قوي"
            }
        ]

        recent.sort(
            key=lambda x: (
                x.get(
                    "score",
                    0
                ),
                x.get(
                    "change",
                    0
                )
            ),
            reverse=True
        )

        return jsonify({
            "ok": True,
            "market": "spot",
            "count": len(
                recent[:30]
            ),
            "results": recent[:30]
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# NEWS
# =========================================================

NEWS_URLS = [
    "https://feeds.feedburner.com/Argaam",
    "https://www.argaam.com/ar/feed"
]


@app.get("/api/news")
def news():

    items = []

    for url in NEWS_URLS:

        try:

            r = HTTP.get(
                url,
                timeout=10
            )

            titles = re.findall(
                r"<title[^>]*>(.*?)</title>",
                r.text,
                flags=re.I | re.S
            )

            links = re.findall(
                r"<link[^>]*>(.*?)</link>",
                r.text,
                flags=re.I | re.S
            )

            for i, title in enumerate(
                titles[1:20]
            ):

                title = re.sub(
                    r"<.*?>",
                    "",
                    title
                ).strip()

                if not title:
                    continue

                link = ""

                if i < len(links):
                    link = re.sub(
                        r"<.*?>",
                        "",
                        links[i]
                    ).strip()

                items.append({
                    "title": title,
                    "url": link
                })

            if items:
                break

        except Exception:
            continue

    return jsonify({
        "ok": True,
        "results": items[:20]
    })


# =========================================================
# PLANS
# =========================================================

@app.get("/api/plans")
def plans():

    return jsonify({
        "ok": True,
        "plans": PLANS,
        "paymentAddress": PAYMENT_ADDRESS
    })


# =========================================================
# SUBSCRIPTION
# =========================================================

@app.get("/api/subscription")
def subscription():

    if not session.get("user"):

        return jsonify({
            "ok": True,
            "loggedIn": False,
            "active": False,
            "subscriptionUntil": None
        })

    user = current_user()

    until = None
    active = False

    if user:
        until = user.get(
            "subscriptionUntil"
        )

        if until:

            try:

                dt = datetime.fromisoformat(
                    until
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=timezone.utc
                    )

                active = (
                    dt > now_utc()
                )

            except Exception:
                active = False

    return jsonify({
        "ok": True,
        "loggedIn": True,
        "active": active,
        "subscriptionUntil": until,
        "user": (
            user.get("username")
            if user
            else None
        )
    })


# =========================================================
# PAYMENT
# =========================================================

@app.post("/api/payment")
def payment():

    auth = require_login()

    if auth:
        return auth

    data = request.get_json(
        silent=True
    ) or {}

    plan = str(
        data.get("plan", "")
    ).strip()

    txid = str(
        data.get("txid", "")
    ).strip()

    if plan not in PLANS:
        return json_error(
            "الباقة غير صحيحة"
        )

    if not DATABASE_URL:
        return json_error(
            "قاعدة البيانات غير مفعلة",
            500
        )

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO payment_requests
                (
                    username,
                    plan,
                    txid
                )
                VALUES(%s,%s,%s)
            """, (
                session["user"],
                plan,
                txid
            ))

        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "message": "تم إرسال طلب الدفع"
        })

    except Exception as e:

        print(
            "PAYMENT ERROR:",
            e
        )

        return json_error(
            "تعذر إرسال طلب الدفع",
            500
        )


@app.get("/api/payment/history")
def payment_history():

    auth = require_login()

    if auth:
        return auth

    if not DATABASE_URL:

        return jsonify({
            "ok": True,
            "results": []
        })

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    plan,
                    txid,
                    status,
                    created_at
                FROM payment_requests
                WHERE username=%s
                ORDER BY id DESC
                LIMIT 50
            """, (
                session["user"],
            ))

            rows = cur.fetchall()

        conn.close()

        results = []

        for row in rows:

            results.append({
                "id": row[0],
                "plan": row[1],
                "txid": row[2],
                "status": row[3],
                "createdAt": (
                    row[4].isoformat()
                    if row[4]
                    else None
                )
            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# ADMIN - STATS
# =========================================================

@app.get("/api/admin/stats")
def admin_stats():

    if not require_admin():
        return json_error(
            "غير مصرح",
            403
        )

    if not DATABASE_URL:

        return jsonify({
            "ok": True,
            "users": 0,
            "active": 0,
            "pending": 0,
            "revenue": 0
        })

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute(
                "SELECT COUNT(*) FROM users"
            )

            users = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until > NOW()
            """)

            active = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                FROM payment_requests
                WHERE status='pending'
            """)

            pending = cur.fetchone()[0]

            cur.execute("""
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN plan='7d' THEN 10
                            WHEN plan='15d' THEN 20
                            WHEN plan='30d' THEN 30
                            ELSE 0
                        END
                    ),
                    0
                )
                FROM payment_requests
                WHERE status='approved'
            """)

            revenue = cur.fetchone()[0]

        conn.close()

        return jsonify({
            "ok": True,
            "users": users,
            "active": active,
            "pending": pending,
            "revenue": float(
                revenue or 0
            )
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# ADMIN - USERS
# =========================================================

@app.get("/api/admin/users")
def admin_users():

    if not require_admin():
        return json_error(
            "غير مصرح",
            403
        )

    if not DATABASE_URL:

        return jsonify({
            "ok": True,
            "results": []
        })

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    username,
                    name,
                    email,
                    is_admin,
                    subscription_until,
                    created_at
                FROM users
                ORDER BY id DESC
                LIMIT 500
            """)

            rows = cur.fetchall()

        conn.close()

        results = []

        for row in rows:

            results.append({
                "id": row[0],
                "username": row[1],
                "name": row[2] or row[1],
                "email": row[3],
                "admin": bool(row[4]),
                "subscriptionUntil": (
                    row[5].isoformat()
                    if row[5]
                    else None
                ),
                "createdAt": (
                    row[6].isoformat()
                    if row[6]
                    else None
                )
            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# ADMIN - PAYMENTS
# =========================================================

@app.get("/api/admin/payments")
def admin_payments():

    if not require_admin():
        return json_error(
            "غير مصرح",
            403
        )

    if not DATABASE_URL:

        return jsonify({
            "ok": True,
            "results": []
        })

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    username,
                    plan,
                    txid,
                    status,
                    created_at
                FROM payment_requests
                ORDER BY id DESC
                LIMIT 200
            """)

            rows = cur.fetchall()

        conn.close()

        results = []

        for row in rows:

            results.append({
                "id": row[0],
                "username": row[1],
                "plan": row[2],
                "txid": row[3],
                "status": row[4],
                "createdAt": (
                    row[5].isoformat()
                    if row[5]
                    else None
                )
            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# ADMIN - REVIEW PAYMENT
# =========================================================

def review_payment(payment_id, action):

    if not require_admin():
        return json_error(
            "غير مصرح",
            403
        )

    if action not in {
        "approve",
        "reject"
    }:
        return json_error(
            "الإجراء غير صحيح"
        )

    if not DATABASE_URL:
        return json_error(
            "قاعدة البيانات غير مفعلة",
            500
        )

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    username,
                    plan,
                    status
                FROM payment_requests
                WHERE id=%s
            """, (
                payment_id,
            ))

            row = cur.fetchone()

            if not row:

                conn.close()

                return json_error(
                    "طلب الدفع غير موجود",
                    404
                )

            username, plan, old_status = row

            if plan not in PLANS:

                conn.close()

                return json_error(
                    "الباقة غير صحيحة",
                    400
                )

            if action == "approve":

                cur.execute("""
                    SELECT
                        subscription_until
                    FROM users
                    WHERE username=%s
                """, (
                    username,
                ))

                user = cur.fetchone()

                current = (
                    user[0]
                    if user and user[0]
                    else now_utc()
                )

                if current < now_utc():
                    current = now_utc()

                until = (
                    current
                    +
                    timedelta(
                        days=PLANS[
                            plan
                        ]["days"]
                    )
                )

                cur.execute("""
                    UPDATE users
                    SET subscription_until=%s
                    WHERE username=%s
                """, (
                    until,
                    username
                ))

                cur.execute("""
                    UPDATE payment_requests
                    SET status='approved'
                    WHERE id=%s
                """, (
                    payment_id,
                ))

            else:

                cur.execute("""
                    UPDATE payment_requests
                    SET status='rejected'
                    WHERE id=%s
                """, (
                    payment_id,
                ))

        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "message": (
                "تمت الموافقة"
                if action == "approve"
                else
                "تم الرفض"
            )
        })

    except Exception as e:

        print(
            "REVIEW ERROR:",
            e
        )

        return json_error(
            str(e),
            500
        )


@app.post("/api/admin/payments/<int:payment_id>/review")
def admin_review_payment(
    payment_id
):

    data = request.get_json(
        silent=True
    ) or {}

    action = str(
        data.get(
            "action",
            ""
        )
    ).strip().lower()

    return review_payment(
        payment_id,
        action
    )


@app.post("/api/admin/payment/<int:payment_id>/review")
def admin_review_payment_old(
    payment_id
):

    data = request.get_json(
        silent=True
    ) or {}

    action = str(
        data.get(
            "action",
            ""
        )
    ).strip().lower()

    return review_payment(
        payment_id,
        action
    )


@app.post("/api/admin/payment/approve")
def admin_approve_payment():

    data = request.get_json(
        silent=True
    ) or {}

    payment_id = data.get(
        "id"
    )

    return review_payment(
        payment_id,
        "approve"
    )


# =========================================================
# ADMIN - USER PLAN
# =========================================================

@app.post("/api/admin/users/<int:user_id>/plan")
def admin_user_plan(user_id):

    if not require_admin():
        return json_error(
            "غير مصرح",
            403
        )

    data = request.get_json(
        silent=True
    ) or {}

    plan = str(
        data.get(
            "plan",
            ""
        )
    ).strip()

    if plan not in PLANS:
        return json_error(
            "الباقة غير صحيحة"
        )

    if not DATABASE_URL:
        return json_error(
            "قاعدة البيانات غير مفعلة",
            500
        )

    try:

        conn = db()

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    subscription_until
                FROM users
                WHERE id=%s
            """, (
                user_id,
            ))

            row = cur.fetchone()

            if not row:

                conn.close()

                return json_error(
                    "المستخدم غير موجود",
                    404
                )

            current = (
                row[0]
                if row[0]
                else now_utc()
            )

            if current < now_utc():
                current = now_utc()

            until = (
                current
                +
                timedelta(
                    days=PLANS[
                        plan
                    ]["days"]
                )
            )

            cur.execute("""
                UPDATE users
                SET subscription_until=%s
                WHERE id=%s
            """, (
                until,
                user_id
            ))

        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "subscriptionUntil":
                until.isoformat()
        })

    except Exception as e:

        return json_error(
            str(e),
            500
        )


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud",
        "spot": "OKX",
        "futures": "OKX",
        "saudi": "Yahoo Finance",
        "usmarket": "Yahoo Finance + Nasdaq Trader",
        "forex": "Yahoo Finance",
        "database": bool(
            DATABASE_URL
        ),
        "adminConfigured": bool(
            ADMIN_PASSWORD
        ),
        "time": now_utc().isoformat()
    })


@app.get("/api/binance/test")
def old_binance_test():

    return jsonify({
        "ok": False,
        "message": "تم تحويل مصدر العملات إلى OKX"
    })


# =========================================================
# PAGES
# =========================================================

@app.route("/")
def index():

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.route("/login")
def login_page():

    template = os.path.join(
        app.template_folder,
        "login.html"
    )

    if os.path.isfile(template):
        return render_template(
            "login.html"
        )

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.route("/register")
def register_page():

    template = os.path.join(
        app.template_folder,
        "register.html"
    )

    if os.path.isfile(template):
        return render_template(
            "register.html"
        )

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.route("/admin")
def admin_page():

    template = os.path.join(
        app.template_folder,
        "admin.html"
    )

    if os.path.isfile(template):
        return render_template(
            "admin.html"
        )

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.route("/<path:path>")
def static_files(path):

    file_path = os.path.join(
        app.static_folder,
        path
    )

    if os.path.isfile(file_path):

        return send_from_directory(
            app.static_folder,
            path
        )

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


# =========================================================
# START
# =========================================================

init_db()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
