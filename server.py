# -*- coding: utf-8 -*-

import os
import time
import math
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

import requests
import psycopg

from flask import (
    Flask,
    jsonify,
    request,
    session,
    redirect,
    render_template
)


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

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
)

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    ""
)

TRC20_ADDRESS = os.getenv(
    "TRC20_ADDRESS",
    "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"
)

BINANCE_PAY_ID = os.getenv(
    "BINANCE_PAY_ID",
    ""
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
# MARKET SOURCES
# =========================================================

MARKET_SOURCE = "OKX"

OKX_BASE = "https://www.okx.com"

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"


# =========================================================
# REQUEST SESSION
# =========================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/130.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*"
})


# =========================================================
# CACHE
# =========================================================

CACHE = {}

CACHE_LOCK = threading.Lock()


def cache_get(key, ttl=15):

    now = time.time()

    with CACHE_LOCK:

        item = CACHE.get(key)

        if not item:
            return None

        timestamp, value = item

        if now - timestamp > ttl:
            CACHE.pop(key, None)
            return None

        return value


def cache_set(key, value):

    with CACHE_LOCK:
        CACHE[key] = (
            time.time(),
            value
        )


# =========================================================
# DATABASE
# =========================================================

def db():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL غير موجود في Render Environment"
        )

    return psycopg.connect(
        DATABASE_URL,
        autocommit=True
    )


def init_db():

    if not DATABASE_URL:
        print("WARNING: DATABASE_URL غير موجود")
        return

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    is_admin BOOLEAN DEFAULT FALSE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    amount NUMERIC NOT NULL,
                    network TEXT DEFAULT 'TRC20',
                    txid TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ,
                    reviewed_by TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE NOT NULL,
                    plan_id TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    active BOOLEAN DEFAULT TRUE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

    finally:

        conn.close()


# =========================================================
# PASSWORD
# =========================================================

def hash_password(password):

    salt = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120000
    )

    return (
        salt +
        "$" +
        digest.hex()
    )


def verify_password(password, stored):

    try:

        salt, digest = stored.split("$", 1)

        new_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120000
        ).hex()

        return secrets.compare_digest(
            new_digest,
            digest
        )

    except Exception:

        return False


# =========================================================
# USERS
# =========================================================

def get_user(user_id):

    if not user_id or not DATABASE_URL:
        return None

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    username,
                    created_at,
                    is_admin
                FROM users
                WHERE id = %s
            """, (user_id,))

            row = cur.fetchone()

            if not row:
                return None

            return {
                "id": row[0],
                "username": row[1],
                "created_at": row[2].isoformat()
                    if row[2] else None,
                "is_admin": bool(row[3])
            }

    finally:

        conn.close()


def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_user(user_id)


def login_required(fn):

    @wraps(fn)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user:

            return jsonify({
                "ok": False,
                "error": "يجب تسجيل الدخول"
            }), 401

        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):

    @wraps(fn)
    def wrapper(*args, **kwargs):

        if not session.get("admin"):

            return jsonify({
                "ok": False,
                "error": "غير مصرح"
            }), 403

        return fn(*args, **kwargs)

    return wrapper


# =========================================================
# BASIC PAGES
# =========================================================

@app.get("/")
def home():

    return render_template("index.html")


@app.get("/login")
def login_page():

    return render_template("login.html")


@app.get("/register")
def register_page():

    return render_template("register.html")


@app.get("/admin")
def admin_page():

    if not session.get("admin"):
        return redirect("/")

    return render_template("admin.html")


@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud",
        "source": MARKET_SOURCE,
        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })


# =========================================================
# AUTH
# =========================================================

@app.post("/api/auth/register")
def auth_register():

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if len(username) < 3:
        return jsonify({
            "ok": False,
            "error": "اسم المستخدم قصير"
        }), 400

    if len(password) < 6:
        return jsonify({
            "ok": False,
            "error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
        }), 400

    if not DATABASE_URL:
        return jsonify({
            "ok": False,
            "error": "قاعدة البيانات غير مهيأة"
        }), 500

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id
                FROM users
                WHERE LOWER(username) = LOWER(%s)
            """, (username,))

            if cur.fetchone():

                return jsonify({
                    "ok": False,
                    "error": "اسم المستخدم موجود"
                }), 409

            cur.execute("""
                INSERT INTO users (
                    username,
                    password_hash
                )
                VALUES (%s, %s)
                RETURNING id
            """, (
                username,
                hash_password(password)
            ))

            user_id = cur.fetchone()[0]

        session.clear()
        session.permanent = True
        session["user_id"] = user_id

        return jsonify({
            "ok": True,
            "user": get_user(user_id)
        })

    finally:

        conn.close()


@app.post("/api/auth/login")
def auth_login():

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if not username or not password:

        return jsonify({
            "ok": False,
            "error": "أدخل اسم المستخدم وكلمة المرور"
        }), 400

    if not DATABASE_URL:

        return jsonify({
            "ok": False,
            "error": "قاعدة البيانات غير مهيأة"
        }), 500

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    username,
                    password_hash,
                    is_admin
                FROM users
                WHERE LOWER(username) = LOWER(%s)
            """, (username,))

            row = cur.fetchone()

            if not row:

                return jsonify({
                    "ok": False,
                    "error": "بيانات الدخول غير صحيحة"
                }), 401

            if not verify_password(
                password,
                row[2]
            ):

                return jsonify({
                    "ok": False,
                    "error": "بيانات الدخول غير صحيحة"
                }), 401

            session.clear()
            session.permanent = True
            session["user_id"] = row[0]

            if row[3]:
                session["admin"] = True

            return jsonify({
                "ok": True,
                "user": {
                    "id": row[0],
                    "username": row[1],
                    "is_admin": bool(row[3])
                }
            })

    finally:

        conn.close()


@app.post("/api/auth/logout")
def auth_logout():

    session.pop("user_id", None)

    return jsonify({
        "ok": True
    })


@app.get("/api/auth/me")
def auth_me():

    user = current_user()

    if not user:

        return jsonify({
            "ok": True,
            "logged_in": False,
            "user": None
        })

    return jsonify({
        "ok": True,
        "logged_in": True,
        "user": user
    })


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.post("/api/admin/login")
def admin_login():

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if not ADMIN_PASSWORD:

        return jsonify({
            "ok": False,
            "error": "ADMIN_PASSWORD غير موجود في Render"
        }), 500

    if (
        username == ADMIN_USERNAME
        and password == ADMIN_PASSWORD
    ):

        session.clear()
        session.permanent = True
        session["admin"] = True

        return jsonify({
            "ok": True,
            "admin": True
        })

    return jsonify({
        "ok": False,
        "error": "بيانات المدير غير صحيحة"
    }), 401


@app.post("/api/admin/logout")
def admin_logout():

    session.pop("admin", None)

    return jsonify({
        "ok": True
    })


@app.get("/api/admin/me")
def admin_me():

    return jsonify({
        "ok": True,
        "admin": bool(
            session.get("admin")
        )
    })


# =========================================================
# ADMIN USERS
# =========================================================

@app.get("/api/admin/users")
@admin_required
def admin_users():

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    username,
                    created_at,
                    is_admin
                FROM users
                ORDER BY id DESC
            """)

            rows = cur.fetchall()

            users = []

            for row in rows:

                users.append({
                    "id": row[0],
                    "username": row[1],
                    "created_at": row[2].isoformat()
                        if row[2] else None,
                    "is_admin": bool(row[3])
                })

            return jsonify({
                "ok": True,
                "users": users,
                "count": len(users)
            })

    finally:

        conn.close()


# =========================================================
# SUBSCRIPTIONS
# =========================================================

@app.get("/api/subscription/plans")
def subscription_plans():

    return jsonify({
        "ok": True,
        "plans": PLANS,
        "payment": {
            "trc20_address": TRC20_ADDRESS,
            "binance_pay_id": BINANCE_PAY_ID,
            "network": "TRC20"
        }
    })


@app.get("/api/subscription/my")
@login_required
def subscription_my():

    user = current_user()

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    plan_id,
                    started_at,
                    expires_at,
                    active
                FROM subscriptions
                WHERE user_id = %s
                ORDER BY expires_at DESC
                LIMIT 1
            """, (user["id"],))

            row = cur.fetchone()

            if not row:

                return jsonify({
                    "ok": True,
                    "active": False,
                    "subscription": None
                })

            expires = row[2]

            active = bool(
                row[3]
                and expires
                and expires > datetime.now(
                    timezone.utc
                )
            )

            return jsonify({
                "ok": True,
                "active": active,
                "subscription": {
                    "plan_id": row[0],
                    "plan": PLANS.get(
                        row[0],
                        {}
                    ),
                    "started_at": row[1].isoformat()
                        if row[1] else None,
                    "expires_at": row[2].isoformat()
                        if row[2] else None,
                    "active": active
                }
            })

    finally:

        conn.close()


@app.post("/api/subscription/request")
@login_required
def subscription_request():

    data = request.get_json(silent=True) or {}

    plan_id = str(
        data.get("plan_id", "")
    )

    txid = str(
        data.get("txid", "")
    ).strip()

    if plan_id not in PLANS:

        return jsonify({
            "ok": False,
            "error": "الباقة غير صحيحة"
        }), 400

    if len(txid) < 5:

        return jsonify({
            "ok": False,
            "error": "أدخل رقم التحويل"
        }), 400

    user = current_user()
    plan = PLANS[plan_id]

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT id
                FROM payments
                WHERE txid = %s
            """, (txid,))

            if cur.fetchone():

                return jsonify({
                    "ok": False,
                    "error": "رقم التحويل مستخدم مسبقًا"
                }), 409

            cur.execute("""
                INSERT INTO payments (
                    user_id,
                    plan_id,
                    amount,
                    network,
                    txid,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    'TRC20',
                    %s,
                    'pending'
                )
                RETURNING id
            """, (
                user["id"],
                plan_id,
                plan["amount"],
                txid
            ))

            payment_id = cur.fetchone()[0]

        return jsonify({
            "ok": True,
            "payment_id": payment_id,
            "status": "pending"
        })

    finally:

        conn.close()


@app.get("/api/subscription/history")
@login_required
def subscription_history():

    user = current_user()

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    plan_id,
                    amount,
                    network,
                    txid,
                    status,
                    created_at,
                    reviewed_at
                FROM payments
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT 30
            """, (user["id"],))

            rows = cur.fetchall()

            items = []

            for row in rows:

                items.append({
                    "id": row[0],
                    "plan_id": row[1],
                    "plan": PLANS.get(
                        row[1],
                        {}
                    ),
                    "amount": float(row[2]),
                    "network": row[3],
                    "txid": row[4],
                    "status": row[5],
                    "created_at": row[6].isoformat()
                        if row[6] else None,
                    "reviewed_at": row[7].isoformat()
                        if row[7] else None
                })

            return jsonify({
                "ok": True,
                "items": items
            })

    finally:

        conn.close()


# =========================================================
# ADMIN PAYMENTS
# =========================================================

@app.get("/api/admin/payments")
@admin_required
def admin_payments():

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    p.id,
                    p.user_id,
                    u.username,
                    p.plan_id,
                    p.amount,
                    p.network,
                    p.txid,
                    p.status,
                    p.created_at,
                    p.reviewed_at
                FROM payments p
                LEFT JOIN users u
                    ON u.id = p.user_id
                ORDER BY p.id DESC
                LIMIT 200
            """)

            rows = cur.fetchall()

            payments = []

            for row in rows:

                payments.append({
                    "id": row[0],
                    "user_id": row[1],
                    "username": row[2],
                    "plan_id": row[3],
                    "plan": PLANS.get(
                        row[3],
                        {}
                    ),
                    "amount": float(row[4]),
                    "network": row[5],
                    "txid": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat()
                        if row[8] else None,
                    "reviewed_at": row[9].isoformat()
                        if row[9] else None
                })

            return jsonify({
                "ok": True,
                "payments": payments
            })

    finally:

        conn.close()


@app.post("/api/admin/payment/<int:payment_id>/review")
@admin_required
def review_payment(payment_id):

    data = request.get_json(silent=True) or {}

    action = str(
        data.get("action", "")
    ).lower()

    if action not in (
        "approve",
        "reject"
    ):

        return jsonify({
            "ok": False,
            "error": "الإجراء غير صحيح"
        }), 400

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    user_id,
                    plan_id,
                    status
                FROM payments
                WHERE id = %s
            """, (payment_id,))

            payment = cur.fetchone()

            if not payment:

                return jsonify({
                    "ok": False,
                    "error": "الطلب غير موجود"
                }), 404

            user_id = payment[0]
            plan_id = payment[1]

            if action == "reject":

                cur.execute("""
                    UPDATE payments
                    SET
                        status = 'rejected',
                        reviewed_at = NOW(),
                        reviewed_by = %s
                    WHERE id = %s
                """, (
                    ADMIN_USERNAME,
                    payment_id
                ))

                return jsonify({
                    "ok": True,
                    "status": "rejected"
                })

            plan = PLANS.get(plan_id)

            if not plan:

                return jsonify({
                    "ok": False,
                    "error": "الباقة غير موجودة"
                }), 400

            now = datetime.now(
                timezone.utc
            )

            cur.execute("""
                SELECT expires_at
                FROM subscriptions
                WHERE user_id = %s
                LIMIT 1
            """, (user_id,))

            existing = cur.fetchone()

            if (
                existing
                and existing[0]
                and existing[0] > now
            ):

                start = existing[0]

            else:

                start = now

            expires = (
                start +
                timedelta(
                    days=plan["days"]
                )
            )

            cur.execute("""
                INSERT INTO subscriptions (
                    user_id,
                    plan_id,
                    started_at,
                    expires_at,
                    active
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    TRUE
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    plan_id = EXCLUDED.plan_id,
                    started_at = EXCLUDED.started_at,
                    expires_at = EXCLUDED.expires_at,
                    active = TRUE
            """, (
                user_id,
                plan_id,
                start,
                expires
            ))

            cur.execute("""
                UPDATE payments
                SET
                    status = 'approved',
                    reviewed_at = NOW(),
                    reviewed_by = %s
                WHERE id = %s
            """, (
                ADMIN_USERNAME,
                payment_id
            ))

            return jsonify({
                "ok": True,
                "status": "approved",
                "expires_at": expires.isoformat()
            })

    finally:

        conn.close()


# =========================================================
# SETTINGS
# =========================================================

@app.get("/api/settings")
def get_settings():

    if not DATABASE_URL:

        return jsonify({
            "ok": True,
            "settings": {}
        })

    conn = db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT key, value
                FROM settings
                ORDER BY key
            """)

            rows = cur.fetchall()

            settings = {
                row[0]: row[1]
                for row in rows
            }

            return jsonify({
                "ok": True,
                "settings": settings
            })

    finally:

        conn.close()


@app.post("/api/settings")
@admin_required
def save_settings():

    data = request.get_json(
        silent=True
    ) or {}

    conn = db()

    try:

        with conn.cursor() as cur:

            for key, value in data.items():

                key = str(key).strip()

                if not key:
                    continue

                cur.execute("""
                    INSERT INTO settings (
                        key,
                        value
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (key)
                    DO UPDATE SET
                        value = EXCLUDED.value
                """, (
                    key,
                    str(value)
                ))

        return jsonify({
            "ok": True
        })

    finally:

        conn.close()


# =========================================================
# OKX CRYPTO
# =========================================================

def okx_request(path, params=None):

    key = (
        "okx:"
        + path
        + ":"
        + str(params or {})
    )

    cached = cache_get(
        key,
        10
    )

    if cached is not None:
        return cached

    url = OKX_BASE + path

    response = HTTP.get(
        url,
        params=params or {},
        timeout=12
    )

    response.raise_for_status()

    data = response.json()

    cache_set(
        key,
        data
    )

    return data


def crypto_markets():

    data = okx_request(
        "/api/v5/market/tickers",
        {
            "instType": "SPOT"
        }
    )

    result = []

    for x in data.get(
        "data",
        []
    ):

        symbol = x.get(
            "instId",
            ""
        )

        if not symbol.endswith(
            "-USDT"
        ):
            continue

        base = symbol.replace(
            "-USDT",
            ""
        )

        if base.endswith(
            ("USDC", "USD", "USDT")
        ):
            continue

        if any(
            word in base
            for word in (
                "3L",
                "3S",
                "5L",
                "5S",
                "BULL",
                "BEAR"
            )
        ):
            continue

        try:

            price = float(
                x.get("last", 0)
            )

            open24 = float(
                x.get("open24h", 0)
            )

            volume = float(
                x.get("volCcy24h", 0)
            )

            change = (
                (
                    price -
                    open24
                )
                / open24
                * 100
            ) if open24 else 0

            result.append({
                "symbol": base + "USDT",
                "okx_symbol": symbol,
                "price": price,
                "change": change,
                "volume": volume
            })

        except Exception:
            continue

    return result


@app.get("/api/okx/test")
def okx_test():

    try:

        markets = crypto_markets()

        return jsonify({
            "ok": True,
            "source": "OKX",
            "count": len(markets)
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/test")
def binance_test_alias():

    return okx_test()


@app.get("/api/bybit/test")
def bybit_test_alias():

    return okx_test()


@app.get("/api/okx/markets")
def okx_markets():

    try:

        markets = crypto_markets()

        return jsonify({
            "ok": True,
            "source": "OKX",
            "markets": markets,
            "count": len(markets)
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/markets")
def binance_markets_alias():

    return okx_markets()


@app.get("/api/bybit/markets")
def bybit_markets_alias():

    return okx_markets()


# =========================================================
# YAHOO HELPERS
# =========================================================

def yahoo_chart(
    symbol,
    interval="15m",
    range_value="1mo"
):

    symbol = str(
        symbol
    ).strip().upper()

    allowed = {
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d"
    }

    if interval not in allowed:
        interval = "15m"

    key = (
        "yahoo:"
        + symbol
        + ":"
        + interval
        + ":"
        + range_value
    )

    cached = cache_get(
        key,
        20
    )

    if cached is not None:
        return cached

    url = (
        YAHOO_CHART
        + "/"
        + symbol
    )

    response = HTTP.get(
        url,
        params={
            "interval": interval,
            "range": range_value,
            "includePrePost": "false",
            "events": "div,splits"
        },
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    cache_set(
        key,
        data
    )

    return data


def yahoo_candles(
    symbol,
    interval="15m"
):

    range_map = {
        "5m": "5d",
        "15m": "1mo",
        "30m": "1mo",
        "1h": "3mo",
        "4h": "1y",
        "1d": "2y"
    }

    data = yahoo_chart(
        symbol,
        interval,
        range_map.get(
            interval,
            "1mo"
        )
    )

    result = (
        data
        .get("chart", {})
        .get("result")
    )

    if not result:
        return []

    result = result[0]

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

            candles.append({
                "t": int(ts),
                "o": float(o),
                "h": float(h),
                "l": float(l),
                "c": float(c),
                "v": float(
                    volumes[i]
                    or 0
                )
            })

        except Exception:
            continue

    return candles


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):

    if not values:
        return []

    if len(values) < period:

        return [
            None
            for _ in values
        ]

    multiplier = 2 / (
        period + 1
    )

    output = [
        None
    ] * len(values)

    seed = sum(
        values[:period]
    ) / period

    output[
        period - 1
    ] = seed

    previous = seed

    for i in range(
        period,
        len(values)
    ):

        previous = (
            (
                values[i]
                - previous
            )
            * multiplier
            + previous
        )

        output[i] = previous

    return output


def rsi(values, period=14):

    if len(values) <= period:
        return [None] * len(values)

    result = [
        None
    ] * len(values)

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            - values[i - 1]
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

    if avg_loss == 0:

        result[period] = 100

    else:

        rs = (
            avg_gain
            / avg_loss
        )

        result[period] = (
            100
            - 100 / (1 + rs)
        )

    for i in range(
        period + 1,
        len(values)
    ):

        gain = gains[i - 1]
        loss = losses[i - 1]

        avg_gain = (
            (
                avg_gain
                * (period - 1)
                + gain
            )
            / period
        )

        avg_loss = (
            (
                avg_loss
                * (period - 1)
                + loss
            )
            / period
        )

        if avg_loss == 0:

            result[i] = 100

        else:

            rs = (
                avg_gain
                / avg_loss
            )

            result[i] = (
                100
                - 100 / (1 + rs)
            )

    return result


def atr(
    highs,
    lows,
    closes,
    period=14
):

    if len(closes) < 2:

        return [
            None
        ] * len(closes)

    tr = [
        None
    ] * len(closes)

    for i in range(
        1,
        len(closes)
    ):

        tr[i] = max(
            highs[i] - lows[i],
            abs(
                highs[i]
                - closes[i - 1]
            ),
            abs(
                lows[i]
                - closes[i - 1]
            )
        )

    result = [
        None
    ] * len(closes)

    if len(closes) <= period:
        return result

    first = [
        x
        for x in tr[1:period + 1]
        if x is not None
    ]

    if len(first) < period:
        return result

    current = (
        sum(first)
        / period
    )

    result[period] = current

    for i in range(
        period + 1,
        len(closes)
    ):

        current = (
            (
                current
                * (period - 1)
                + tr[i]
            )
            / period
        )

        result[i] = current

    return result


def macd(values):

    fast = ema(
        values,
        12
    )

    slow = ema(
        values,
        26
    )

    line = []

    for i in range(
        len(values)
    ):

        if (
            fast[i] is None
            or slow[i] is None
        ):
            line.append(None)
        else:
            line.append(
                fast[i]
                - slow[i]
            )

    clean = [
        x
        for x in line
        if x is not None
    ]

    signal_values = ema(
        clean,
        9
    )

    signal = [
        None
    ] * (
        len(line)
        - len(signal_values)
    ) + signal_values

    histogram = []

    for i in range(
        len(line)
    ):

        if (
            line[i] is None
            or signal[i] is None
        ):
            histogram.append(None)
        else:
            histogram.append(
                line[i]
                - signal[i]
            )

    return (
        line,
        signal,
        histogram
    )


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def analyze_candles(
    candles,
    interval="15m"
):

    if len(candles) < 60:

        return {
            "signal": "حيادي",
            "direction": "neutral",
            "score": 50,
            "score10": 5.0,
            "price": 0,
            "entry": 0,
            "tp1": 0,
            "tp2": 0,
            "tp3": 0,
            "sl": 0,
            "rsi": 0,
            "ema20": 0,
            "ema50": 0,
            "ema200": 0,
            "macd": 0,
            "macd_signal": 0,
            "macd_histogram": 0,
            "atr": 0,
            "support": 0,
            "resistance": 0,
            "reasons": [
                "بيانات غير كافية للتحليل"
            ],
            "candles": candles[-100:]
        }

    closes = [
        x["c"]
        for x in candles
    ]

    highs = [
        x["h"]
        for x in candles
    ]

    lows = [
        x["l"]
        for x in candles
    ]

    price = closes[-1]

    ema20_values = ema(
        closes,
        20
    )

    ema50_values = ema(
        closes,
        50
    )

    ema200_values = ema(
        closes,
        200
    )

    rsi_values = rsi(
        closes,
        14
    )

    atr_values = atr(
        highs,
        lows,
        closes,
        14
    )

    macd_line, macd_signal_line, macd_hist = macd(
        closes
    )

    e20 = ema20_values[-1]
    e50 = ema50_values[-1]
    e200 = ema200_values[-1]

    rv = rsi_values[-1]

    av = atr_values[-1]

    ml = macd_line[-1]
    ms = macd_signal_line[-1]
    mh = macd_hist[-1]

    support = min(
        lows[-20:]
    )

    resistance = max(
        highs[-20:]
    )

    score = 50
    reasons = []

    # EMA trend
    if e20 and price > e20:

        score += 8
        reasons.append(
            "السعر فوق EMA20"
        )

    else:

        score -= 8
        reasons.append(
            "السعر تحت EMA20"
        )

    if e50 and price > e50:

        score += 8
        reasons.append(
            "السعر فوق EMA50"
        )

    else:

        score -= 8
        reasons.append(
            "السعر تحت EMA50"
        )

    if e200 and price > e200:

        score += 10
        reasons.append(
            "الاتجاه فوق EMA200"
        )

    else:

        score -= 10
        reasons.append(
            "الاتجاه تحت EMA200"
        )

    # RSI
    if rv is not None:

        if 50 <= rv <= 68:

            score += 8
            reasons.append(
                "RSI يدعم الشراء"
            )

        elif 32 <= rv < 50:

            score -= 5
            reasons.append(
                "RSI يميل للضعف"
            )

        elif rv > 72:

            score -= 4
            reasons.append(
                "RSI مرتفع"
            )

        elif rv < 28:

            score += 3
            reasons.append(
                "RSI في تشبع بيع"
            )

    # MACD
    if (
        mh is not None
        and mh > 0
    ):

        score += 8
        reasons.append(
            "MACD إيجابي"
        )

    elif (
        mh is not None
        and mh < 0
    ):

        score -= 8
        reasons.append(
            "MACD سلبي"
        )

    # Candle momentum
    if len(closes) >= 2:

        change = (
            (
                closes[-1]
                - closes[-2]
            )
            / closes[-2]
            * 100
        )

        if change > 0:

            score += 5

        elif change < 0:

            score -= 5

    score = max(
        0,
        min(
            100,
            score
        )
    )

    if score >= 78:

        signal = "شراء قوي"
        direction = "buy"

    elif score >= 62:

        signal = "شراء"
        direction = "buy"

    elif score <= 22:

        signal = "بيع قوي"
        direction = "sell"

    elif score <= 38:

        signal = "بيع"
        direction = "sell"

    else:

        signal = "حيادي"
        direction = "neutral"

    if av is None or av <= 0:

        risk = price * 0.01

    else:

        risk = av * 1.2

    if direction == "buy":

        entry = price

        sl = max(
            0,
            price - risk
        )

        tp1 = price + risk
        tp2 = price + risk * 2
        tp3 = price + risk * 3

    elif direction == "sell":

        entry = price

        sl = price + risk

        tp1 = max(
            0,
            price - risk
        )

        tp2 = max(
            0,
            price - risk * 2
        )

        tp3 = max(
            0,
            price - risk * 3
        )

    else:

        entry = price
        sl = price - risk
        tp1 = price + risk
        tp2 = price + risk * 2
        tp3 = price + risk * 3

    def clean(value):

        if value is None:
            return 0

        return round(
            float(value),
            8
        )

    return {
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(
            score / 10,
            1
        ),
        "price": clean(price),
        "entry": clean(entry),
        "tp1": clean(tp1),
        "tp2": clean(tp2),
        "tp3": clean(tp3),
        "sl": clean(sl),
        "rsi": clean(rv),
        "ema20": clean(e20),
        "ema50": clean(e50),
        "ema200": clean(e200),
        "macd": clean(ml),
        "macd_signal": clean(ms),
        "macd_histogram": clean(mh),
        "atr": clean(av),
        "support": clean(support),
        "resistance": clean(resistance),
        "reasons": reasons,
        "candles": candles[-100:]
    }


# =========================================================
# CRYPTO KLINES
# =========================================================

def okx_interval(interval):

    mapping = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D"
    }

    return mapping.get(
        interval,
        "15m"
    )


def okx_klines(
    symbol,
    interval="15m"
):

    symbol = symbol.upper()

    if symbol.endswith(
        "USDT"
    ):

        base = symbol[:-4]

        inst_id = (
            base
            + "-USDT"
        )

    else:

        inst_id = symbol

    data = okx_request(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": okx_interval(
                interval
            ),
            "limit": "300"
        }
    )

    candles = []

    for row in reversed(
        data.get(
            "data",
            []
        )
    ):

        try:

            candles.append({
                "t": int(row[0]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5])
            })

        except Exception:
            continue

    return candles


@app.get("/api/okx/klines")
def okx_klines_api():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        candles = okx_klines(
            symbol,
            interval
        )

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "candles": candles
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/klines")
def binance_klines_alias():

    return okx_klines_api()


@app.get("/api/bybit/klines")
def bybit_klines_alias():

    return okx_klines_api()


# =========================================================
# GENERIC ANALYSIS API
# =========================================================

@app.get("/api/okx/analysis")
def okx_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        candles = okx_klines(
            symbol,
            interval
        )

        result = analyze_candles(
            candles,
            interval
        )

        result.update({
            "symbol": symbol,
            "interval": interval,
            "source": "OKX",
            "updatedAt": datetime.now(
                timezone.utc
            ).isoformat()
        })

        return jsonify({
            "ok": True,
            **result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/analysis")
def binance_analysis_alias():

    return okx_analysis()


@app.get("/api/bybit/analysis")
def bybit_analysis_alias():

    return okx_analysis()


# =========================================================
# CRYPTO SCANNER
# =========================================================

SCANNER_CACHE = {}


def crypto_scan(
    interval="15m",
    limit=80
):

    key = (
        "crypto_scan:"
        + interval
    )

    cached = cache_get(
        key,
        60
    )

    if cached is not None:
        return cached

    markets = crypto_markets()

    markets.sort(
        key=lambda x: x.get(
            "volume",
            0
        ),
        reverse=True
    )

    markets = markets[
        :limit
    ]

    results = []

    for market in markets:

        try:

            candles = okx_klines(
                market["symbol"],
                interval
            )

            if len(candles) < 60:
                continue

            analysis = analyze_candles(
                candles,
                interval
            )

            result = {
                "symbol": market[
                    "symbol"
                ],
                "price": market[
                    "price"
                ],
                "change": market[
                    "change"
                ],
                "volume": market[
                    "volume"
                ],
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
                "interval": interval,
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
                "signalRank": analysis[
                    "score"
                ],
                "updatedAt": datetime.now(
                    timezone.utc
                ).isoformat()
            }

            results.append(
                result
            )

        except Exception:
            continue

    results.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True
    )

    cache_set(
        key,
        results
    )

    return results


@app.get("/api/okx/scan")
def okx_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        results = crypto_scan(
            interval
        )

        return jsonify({
            "ok": True,
            "source": "OKX",
            "interval": interval,
            "results": results,
            "count": len(results)
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/scan")
def binance_scan_alias():

    return okx_scan()


@app.get("/api/bybit/scan")
def bybit_scan_alias():

    return okx_scan()


# =========================================================
# CRYPTO PRICES
# =========================================================

@app.get("/api/okx/prices")
def okx_prices():

    try:

        markets = crypto_markets()

        return jsonify({
            "ok": True,
            "source": "OKX",
            "prices": markets
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/prices")
def binance_prices_alias():

    return okx_prices()


@app.get("/api/bybit/prices")
def bybit_prices_alias():

    return okx_prices()


@app.get("/api/okx/price")
def okx_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    try:

        markets = crypto_markets()

        for x in markets:

            if x["symbol"] == symbol:

                return jsonify({
                    "ok": True,
                    **x
                })

        return jsonify({
            "ok": False,
            "error": "العملة غير موجودة"
        }), 404

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/binance/price")
def binance_price_alias():

    return okx_price()


@app.get("/api/bybit/price")
def bybit_price_alias():

    return okx_price()


# =========================================================
# SAUDI MARKET
# =========================================================

SAUDI_STOCKS = {
    "2222.SR": "أرامكو السعودية",
    "1120.SR": "الراجحي",
    "2010.SR": "سابك",
    "1180.SR": "الأهلي السعودي",
    "7010.SR": "الاتصالات السعودية",
    "1211.SR": "معادن",
    "2050.SR": "صناعات كهربائية",
    "4030.SR": "البحري",
    "1150.SR": "مصرف الإنماء",
    "1060.SR": "ساب",
    "2020.SR": "سافكو",
    "7020.SR": "زين السعودية",
    "7030.SR": "موبايلي",
    "4001.SR": "أسواق العثيم",
    "4190.SR": "جرير",
    "4191.SR": "أبو معطي",
    "4280.SR": "المملكة",
    "6004.SR": "أسواق المزرعة",
    "6010.SR": "نادك",
    "4003.SR": "إكسترا",
    "4002.SR": "المواساة",
    "4004.SR": "دله الصحية",
    "4008.SR": "ساكو",
    "4050.SR": "ساسكو",
    "4200.SR": "الدريس",
    "4261.SR": "ذيب",
    "4262.SR": "بدجت السعودية",
    "5110.SR": "كهرباء السعودية",
    "2060.SR": "التصنيع",
    "2190.SR": "سيسكو القابضة",
    "2290.SR": "ينساب",
    "2330.SR": "المتقدمة",
    "2380.SR": "بترو رابغ",
    "2350.SR": "كيان السعودية",
    "2100.SR": "وفرة",
    "3003.SR": "أسمنت المدينة",
    "3010.SR": "أسمنت العربية",
    "3030.SR": "أسمنت السعودية",
    "3040.SR": "أسمنت القصيم",
    "3050.SR": "أسمنت الجنوب",
    "3060.SR": "أسمنت ينبع",
    "3090.SR": "أسمنت تبوك",
    "1320.SR": "الإنماء طوكيو",
    "8010.SR": "التعاونية",
    "8040.SR": "ولاء",
    "8050.SR": "سلامة",
    "8060.SR": "ولاء",
    "8100.SR": "سايكو",
    "8120.SR": "اتحاد الخليج الأهلية"
}


def yahoo_quote(
    symbol,
    interval="1d"
):

    candles = yahoo_candles(
        symbol,
        interval
    )

    if not candles:
        return None

    latest = candles[-1]

    previous = (
        candles[-2]
        if len(candles) >= 2
        else latest
    )

    price = latest["c"]

    change = (
        (
            price
            - previous["c"]
        )
        / previous["c"]
        * 100
    ) if previous["c"] else 0

    volume = latest.get(
        "v",
        0
    )

    return {
        "price": price,
        "change": change,
        "volume": volume
    }


def saudi_scan(
    interval="1d"
):

    key = (
        "saudi_scan:"
        + interval
    )

    cached = cache_get(
        key,
        120
    )

    if cached is not None:
        return cached

    results = []

    for ticker, name in SAUDI_STOCKS.items():

        try:

            candles = yahoo_candles(
                ticker,
                interval
            )

            if len(candles) < 60:
                continue

            analysis = analyze_candles(
                candles,
                interval
            )

            latest = candles[-1]
            previous = candles[-2]

            price = latest["c"]

            change = (
                (
                    price
                    - previous["c"]
                )
                / previous["c"]
                * 100
            ) if previous["c"] else 0

            results.append({
                "symbol": ticker.replace(
                    ".SR",
                    ""
                ),
                "ticker": ticker,
                "name": name,
                "price": price,
                "change": change,
                "volume": latest.get(
                    "v",
                    0
                ),
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
                "interval": interval,
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
                "signalRank": analysis[
                    "score"
                ],
                "updatedAt": datetime.now(
                    timezone.utc
                ).isoformat()
            })

        except Exception:
            continue

    results.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True
    )

    cache_set(
        key,
        results
    )

    return results


@app.get("/api/saudi/scan")
def saudi_scan_api():

    interval = request.args.get(
        "interval",
        "1d"
    )

    try:

        results = saudi_scan(
            interval
        )

        return jsonify({
            "ok": True,
            "source": "Saudi",
            "interval": interval,
            "results": results,
            "count": len(results)
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/saudi/analysis")
def saudi_analysis():

    symbol = request.args.get(
        "symbol",
        "2222"
    ).upper()

    interval = request.args.get(
        "interval",
        "1d"
    )

    if not symbol.endswith(
        ".SR"
    ):

        symbol += ".SR"

    try:

        candles = yahoo_candles(
            symbol,
            interval
        )

        result = analyze_candles(
            candles,
            interval
        )

        result.update({
            "symbol": symbol.replace(
                ".SR",
                ""
            ),
            "ticker": symbol,
            "name": SAUDI_STOCKS.get(
                symbol,
                symbol
            ),
            "interval": interval,
            "source": "Saudi",
            "updatedAt": datetime.now(
                timezone.utc
            ).isoformat()
        })

        return jsonify({
            "ok": True,
            **result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/saudi/markets")
def saudi_markets():

    return jsonify({
        "ok": True,
        "source": "Saudi",
        "markets": [
            {
                "ticker": ticker,
                "symbol": ticker.replace(
                    ".SR",
                    ""
                ),
                "name": name
            }
            for ticker, name
            in SAUDI_STOCKS.items()
        ],
        "count": len(
            SAUDI_STOCKS
        )
    })


# =========================================================
# US MARKET
# =========================================================

US_STOCKS = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "META": "Meta",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet C",
    "TSLA": "Tesla",
    "AVGO": "Broadcom",
    "AMD": "AMD",
    "NFLX": "Netflix",
    "JPM": "JPMorgan",
    "V": "Visa",
    "MA": "Mastercard",
    "WMT": "Walmart",
    "COST": "Costco",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    "BAC": "Bank of America",
    "INTC": "Intel",
    "QCOM": "Qualcomm",
    "ORCL": "Oracle",
    "CRM": "Salesforce",
    "ADBE": "Adobe",
    "UBER": "Uber",
    "PYPL": "PayPal",
    "PLTR": "Palantir",
    "COIN": "Coinbase"
}


@app.get("/api/usmarket/signals")
def usmarket_signals():

    interval = request.args.get(
        "interval",
        "1d"
    )

    results = []

    for ticker, name in US_STOCKS.items():

        try:

            candles = yahoo_candles(
                ticker,
                interval
            )

            if len(candles) < 60:
                continue

            analysis = analyze_candles(
                candles,
                interval
            )

            latest = candles[-1]
            previous = candles[-2]

            price = latest["c"]

            change = (
                (
                    price
                    - previous["c"]
                )
                / previous["c"]
                * 100
            ) if previous["c"] else 0

            results.append({
                "symbol": ticker,
                "ticker": ticker,
                "name": name,
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
                "interval": interval,
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
                "tp": analysis[
                    "tp1"
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
                "signalRank": analysis[
                    "score"
                ],
                "updatedAt": datetime.now(
                    timezone.utc
                ).isoformat()
            })

        except Exception:
            continue

    results.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True
    )

    return jsonify({
        "ok": True,
        "source": "US",
        "interval": interval,
        "results": results,
        "count": len(results)
    })


@app.get("/api/usmarket/analysis")
def usmarket_analysis():

    symbol = request.args.get(
        "symbol",
        "AAPL"
    ).upper()

    interval = request.args.get(
        "interval",
        "1d"
    )

    try:

        candles = yahoo_candles(
            symbol,
            interval
        )

        result = analyze_candles(
            candles,
            interval
        )

        result.update({
            "symbol": symbol,
            "ticker": symbol,
            "name": US_STOCKS.get(
                symbol,
                symbol
            ),
            "interval": interval,
            "source": "US",
            "updatedAt": datetime.now(
                timezone.utc
            ).isoformat()
        })

        return jsonify({
            "ok": True,
            **result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/usmarket/markets")
def usmarket_markets():

    return jsonify({
        "ok": True,
        "source": "US",
        "markets": [
            {
                "symbol": ticker,
                "ticker": ticker,
                "name": name
            }
            for ticker, name
            in US_STOCKS.items()
        ],
        "count": len(
            US_STOCKS
        )
    })


# =========================================================
# FOREX
# =========================================================

FOREX_PAIRS = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF",
    "USDCAD=X": "USD/CAD",
    "AUDUSD=X": "AUD/USD",
    "NZDUSD=X": "NZD/USD",
    "EURGBP=X": "EUR/GBP",
    "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY",
    "AUDJPY=X": "AUD/JPY",
    "CADJPY=X": "CAD/JPY",
    "CHFJPY=X": "CHF/JPY",
    "EURAUD=X": "EUR/AUD",
    "EURCHF=X": "EUR/CHF",
    "GBPAUD=X": "GBP/AUD",
    "GBPCAD=X": "GBP/CAD",
    "AUDCAD=X": "AUD/CAD",
    "AUDCHF=X": "AUD/CHF",
    "NZDJPY=X": "NZD/JPY"
}


@app.get("/api/forex/signals")
def forex_signals():

    interval = request.args.get(
        "interval",
        "1h"
    )

    results = []

    for ticker, pair in FOREX_PAIRS.items():

        try:

            candles = yahoo_candles(
                ticker,
                interval
            )

            if len(candles) < 60:
                continue

            analysis = analyze_candles(
                candles,
                interval
            )

            latest = candles[-1]
            previous = candles[-2]

            price = latest["c"]

            change = (
                (
                    price
                    - previous["c"]
                )
                / previous["c"]
                * 100
            ) if previous["c"] else 0

            results.append({
                "symbol": pair,
                "ticker": ticker,
                "name": pair,
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
                "interval": interval,
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
                "tp": analysis[
                    "tp1"
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
                "signalRank": analysis[
                    "score"
                ],
                "updatedAt": datetime.now(
                    timezone.utc
                ).isoformat()
            })

        except Exception:
            continue

    results.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True
    )

    return jsonify({
        "ok": True,
        "source": "Forex",
        "interval": interval,
        "results": results,
        "count": len(results)
    })


@app.get("/api/forex/analysis")
def forex_analysis():

    symbol = request.args.get(
        "symbol",
        "EURUSD"
    ).upper()

    interval = request.args.get(
        "interval",
        "1h"
    )

    if not symbol.endswith(
        "=X"
    ):

        symbol += "=X"

    try:

        candles = yahoo_candles(
            symbol,
            interval
        )

        result = analyze_candles(
            candles,
            interval
        )

        pair = FOREX_PAIRS.get(
            symbol,
            symbol.replace(
                "=X",
                ""
            )
        )

        result.update({
            "symbol": pair,
            "ticker": symbol,
            "name": pair,
            "interval": interval,
            "source": "Forex",
            "updatedAt": datetime.now(
                timezone.utc
            ).isoformat()
        })

        return jsonify({
            "ok": True,
            **result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


@app.get("/api/forex/markets")
def forex_markets():

    return jsonify({
        "ok": True,
        "source": "Forex",
        "markets": [
            {
                "symbol": pair,
                "ticker": ticker,
                "name": pair
            }
            for ticker, pair
            in FOREX_PAIRS.items()
        ],
        "count": len(
            FOREX_PAIRS
        )
    })


# =========================================================
# COMPATIBILITY FUTURES
# =========================================================

@app.get("/api/futures/scan")
def futures_scan():

    # تحليل عقود غير متاح من OKX Spot.
    # نعيد العملات الرقمية كواجهة توافق
    # حتى لا تنكسر الواجهة القديمة.

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        results = crypto_scan(
            interval,
            50
        )

        return jsonify({
            "ok": True,
            "source": "OKX",
            "market": "crypto",
            "interval": interval,
            "results": results,
            "count": len(results),
            "note": "هذه بيانات Spot وليست Futures"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502


# =========================================================
# NEWS
# =========================================================

NEWS_URL = os.getenv(
    "NEWS_URL",
    "https://www.coindesk.com/arc/outboundfeeds/rss/"
)


def translate_text(text):

    if not text:
        return ""

    text = str(text)

    # نحاول ترجمة الأخبار إلى العربية
    # عبر Google Translate public endpoint.
    try:

        response = HTTP.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ar",
                "dt": "t",
                "q": text
            },
            timeout=8
        )

        data = response.json()

        parts = data[0]

        return "".join(
            part[0]
            for part in parts
            if part and part[0]
        )

    except Exception:

        return text


def get_news():

    cached = cache_get(
        "news",
        300
    )

    if cached is not None:
        return cached

    try:

        response = HTTP.get(
            NEWS_URL,
            timeout=15
        )

        response.raise_for_status()

        from xml.etree import ElementTree as ET

        root = ET.fromstring(
            response.content
        )

        items = []

        for item in root.findall(
            ".//item"
        )[:15]:

            title = item.findtext(
                "title",
                ""
            )

            description = item.findtext(
                "description",
                ""
            )

            link = item.findtext(
                "link",
                ""
            )

            pub_date = item.findtext(
                "pubDate",
                ""
            )

            items.append({
                "title": translate_text(
                    title
                ),
                "description": translate_text(
                    description
                ),
                "link": link,
                "date": pub_date,
                "source": "CoinDesk"
            })

        cache_set(
            "news",
            items
        )

        return items

    except Exception as e:

        print(
            "NEWS ERROR:",
            e
        )

        return []


@app.get("/api/news")
def news():

    return jsonify({
        "ok": True,
        "news": get_news()
    })


# =========================================================
# MARKET OVERVIEW
# =========================================================

@app.get("/api/markets/overview")
def markets_overview():

    result = {
        "ok": True,
        "markets": {
            "crypto": {
                "name": "العملات الرقمية",
                "source": "OKX"
            },
            "saudi": {
                "name": "السوق السعودي",
                "source": "Yahoo Finance"
            },
            "us": {
                "name": "السوق الأمريكي",
                "source": "Yahoo Finance"
            },
            "forex": {
                "name": "الفوركس",
                "source": "Yahoo Finance"
            }
        }
    }

    return jsonify(result)


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
            "error": "المسار غير موجود"
        }), 404

    return redirect("/")


@app.errorhandler(500)
def internal_error(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "ok": False,
            "error": "خطأ داخلي في السيرفر"
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
        "DATABASE INIT ERROR:",
        e
    )


# =========================================================
# RUN
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
