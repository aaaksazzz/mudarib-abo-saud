# ============================================================
# منصة تحليل العملات الرقمية
# SERVER.PY - FINAL PRO
# ============================================================

import os
import sqlite3
import hashlib
import secrets
import time
import requests

from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect


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
    "CHANGE_THIS_SECRET_KEY_2026"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True


# ============================================================
# ADMIN
# ============================================================

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
)

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    "4573261aA"
)


# ============================================================
# DATABASE
# ============================================================

DB_FILE = os.getenv(
    "DB_FILE",
    "users.db"
)


def get_db():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            created_at INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            theme TEXT DEFAULT 'dark',
            interval TEXT DEFAULT '15m',
            symbol TEXT DEFAULT 'BTCUSDT',
            refresh_seconds INTEGER DEFAULT 30,
            notifications INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# PASSWORD
# ============================================================

def hash_password(password):

    salt = secrets.token_hex(16)

    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120000
    ).hex()

    return f"{salt}${hashed}"


def verify_password(password, stored):

    try:

        salt, saved_hash = stored.split("$", 1)

        check = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120000
        ).hex()

        return secrets.compare_digest(
            check,
            saved_hash
        )

    except Exception:

        return False


# ============================================================
# AUTH
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            return jsonify({
                "ok": False,
                "message": "يجب تسجيل الدخول أولاً"
            }), 401

        return func(*args, **kwargs)

    return wrapper


def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not session.get("is_admin", False):

            return jsonify({
                "ok": False,
                "message": "غير مصرح لك بالدخول"
            }), 403

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# BINANCE
# ============================================================

BINANCE_APIS = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com"
]


def binance_get(path, params=None, timeout=10):

    last_error = None

    for base in BINANCE_APIS:

        try:

            response = requests.get(
                base + path,
                params=params,
                timeout=timeout,
                headers={
                    "User-Agent":
                        "CryptoAnalysisPlatform/2.0"
                }
            )

            if response.status_code == 200:
                return response.json()

            last_error = f"HTTP {response.status_code}"

        except Exception as e:

            last_error = str(e)

    raise RuntimeError(
        f"فشل الاتصال ببيانات Binance: {last_error}"
    )


# ============================================================
# PAGES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/admin")
def admin_page():

    if not session.get("is_admin", False):
        return redirect("/")

    return render_template("admin.html")


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/api/admin/login")
def admin_login():

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
            "message": "أدخل اسم المستخدم وكلمة المرور"
        }), 400

    if (
        secrets.compare_digest(
            username,
            ADMIN_USERNAME
        )
        and
        secrets.compare_digest(
            password,
            ADMIN_PASSWORD
        )
    ):

        session.clear()

        session["is_admin"] = True
        session["admin_username"] = ADMIN_USERNAME

        return jsonify({
            "ok": True,
            "message": "تم دخول لوحة الإدارة",
            "admin": {
                "username": ADMIN_USERNAME
            }
        })

    return jsonify({
        "ok": False,
        "message": "بيانات الأدمن غير صحيحة"
    }), 401


# ============================================================
# ADMIN ME
# ============================================================

@app.get("/api/admin/me")
def admin_me():

    if not session.get("is_admin", False):

        return jsonify({
            "ok": True,
            "logged_in": False
        })

    return jsonify({
        "ok": True,
        "logged_in": True,
        "admin": {
            "username":
                session.get("admin_username")
        }
    })


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.post("/api/admin/logout")
def admin_logout():

    session.clear()

    return jsonify({
        "ok": True,
        "message": "تم تسجيل خروج الأدمن"
    })


# ============================================================
# REGISTER
# ============================================================

@app.post("/api/auth/register")
def register():

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if len(username) < 3:

        return jsonify({
            "ok": False,
            "message":
                "اسم المستخدم يجب أن يكون 3 أحرف أو أكثر"
        }), 400

    if len(password) < 6:

        return jsonify({
            "ok": False,
            "message":
                "كلمة المرور يجب أن تكون 6 أحرف أو أكثر"
        }), 400

    conn = get_db()

    try:

        cursor = conn.execute(
            """
            INSERT INTO users
            (
                username,
                email,
                password_hash,
                plan,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                username,
                email or None,
                hash_password(password),
                "free",
                int(time.time())
            )
        )

        user_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO settings
            (
                user_id,
                theme,
                interval,
                symbol,
                refresh_seconds,
                notifications
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "dark",
                "15m",
                "BTCUSDT",
                30,
                1
            )
        )

        conn.commit()

        session.clear()

        session["user_id"] = user_id
        session["username"] = username
        session["plan"] = "free"

        return jsonify({
            "ok": True,
            "message": "تم إنشاء الحساب بنجاح",
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "plan": "free"
            }
        })

    except sqlite3.IntegrityError:

        return jsonify({
            "ok": False,
            "message":
                "اسم المستخدم أو البريد الإلكتروني مستخدم مسبقاً"
        }), 409

    finally:

        conn.close()


# ============================================================
# LOGIN
# ============================================================

@app.post("/api/auth/login")
def login():

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
            "message":
                "أدخل اسم المستخدم وكلمة المرور"
        }), 400

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    conn.close()

    if not user:

        return jsonify({
            "ok": False,
            "message":
                "اسم المستخدم أو كلمة المرور غير صحيحة"
        }), 401

    if not verify_password(
        password,
        user["password_hash"]
    ):

        return jsonify({
            "ok": False,
            "message":
                "اسم المستخدم أو كلمة المرور غير صحيحة"
        }), 401

    session.clear()

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["plan"] = user["plan"]

    return jsonify({
        "ok": True,
        "message": "تم تسجيل الدخول",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "plan": user["plan"]
        }
    })


# ============================================================
# LOGOUT
# ============================================================

@app.post("/api/auth/logout")
def logout():

    session.clear()

    return jsonify({
        "ok": True,
        "message": "تم تسجيل الخروج"
    })


# ============================================================
# CURRENT USER
# ============================================================

@app.get("/api/auth/me")
def current_user():

    if "user_id" not in session:

        return jsonify({
            "ok": True,
            "logged_in": False
        })

    conn = get_db()

    user = conn.execute(
        """
        SELECT
            id,
            username,
            email,
            plan,
            created_at
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    conn.close()

    if not user:

        session.clear()

        return jsonify({
            "ok": True,
            "logged_in": False
        })

    session["plan"] = user["plan"]

    return jsonify({
        "ok": True,
        "logged_in": True,
        "user": dict(user)
    })


# ============================================================
# SETTINGS GET
# ============================================================

@app.get("/api/settings")
@login_required
def get_settings():

    conn = get_db()

    settings = conn.execute(
        """
        SELECT *
        FROM settings
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    conn.close()

    if not settings:

        return jsonify({
            "ok": False,
            "message": "الإعدادات غير موجودة"
        }), 404

    return jsonify({
        "ok": True,
        "settings": dict(settings)
    })


# ============================================================
# SETTINGS SAVE
# ============================================================

@app.post("/api/settings")
@login_required
def save_settings():

    data = request.get_json(silent=True) or {}

    theme = data.get("theme", "dark")

    interval = data.get(
        "interval",
        "15m"
    )

    symbol = str(
        data.get(
            "symbol",
            "BTCUSDT"
        )
    ).upper()

    try:
        refresh_seconds = int(
            data.get(
                "refresh_seconds",
                30
            )
        )
    except Exception:
        refresh_seconds = 30

    notifications = int(
        bool(
            data.get(
                "notifications",
                True
            )
        )
    )

    if theme not in ("dark", "light"):
        theme = "dark"

    if interval not in (
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
        "1w"
    ):
        interval = "15m"

    refresh_seconds = max(
        10,
        min(refresh_seconds, 3600)
    )

    conn = get_db()

    conn.execute(
        """
        INSERT INTO settings
        (
            user_id,
            theme,
            interval,
            symbol,
            refresh_seconds,
            notifications
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            theme = excluded.theme,
            interval = excluded.interval,
            symbol = excluded.symbol,
            refresh_seconds = excluded.refresh_seconds,
            notifications = excluded.notifications
        """,
        (
            session["user_id"],
            theme,
            interval,
            symbol,
            refresh_seconds,
            notifications
        )
    )

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "تم حفظ الإعدادات"
    })


# ============================================================
# ADMIN STATS
# ============================================================

@app.get("/api/admin/stats")
@admin_required
def admin_stats():

    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    free_users = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE plan = 'free'
        """
    ).fetchone()[0]

    premium_users = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE plan = 'premium'
        """
    ).fetchone()[0]

    today_start = int(time.time()) - 86400

    new_today = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE created_at >= ?
        """,
        (today_start,)
    ).fetchone()[0]

    conn.close()

    return jsonify({
        "ok": True,
        "stats": {
            "total_users": total,
            "free_users": free_users,
            "premium_users": premium_users,
            "new_today": new_today
        }
    })


# ============================================================
# ADMIN USERS
# ============================================================

@app.get("/api/admin/users")
@admin_required
def admin_users():

    conn = get_db()

    users = conn.execute(
        """
        SELECT
            id,
            username,
            email,
            plan,
            created_at
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "users": [dict(user) for user in users]
    })


# ============================================================
# ADMIN CHANGE PLAN
# ============================================================

@app.post("/api/admin/users/<int:user_id>/plan")
@admin_required
def change_plan(user_id):

    data = request.get_json(silent=True) or {}

    plan = str(
        data.get(
            "plan",
            "free"
        )
    ).lower()

    if plan not in ("free", "premium"):

        return jsonify({
            "ok": False,
            "message": "نوع الاشتراك غير صحيح"
        }), 400

    conn = get_db()

    user = conn.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:

        conn.close()

        return jsonify({
            "ok": False,
            "message": "المستخدم غير موجود"
        }), 404

    conn.execute(
        """
        UPDATE users
        SET plan = ?
        WHERE id = ?
        """,
        (plan, user_id)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "تم تحديث الاشتراك"
    })


# ============================================================
# ADMIN DELETE USER
# ============================================================

@app.delete("/api/admin/users/<int:user_id>")
@admin_required
def delete_user(user_id):

    conn = get_db()

    user = conn.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:

        conn.close()

        return jsonify({
            "ok": False,
            "message": "المستخدم غير موجود"
        }), 404

    conn.execute(
        """
        DELETE FROM settings
        WHERE user_id = ?
        """,
        (user_id,)
    )

    conn.execute(
        """
        DELETE FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "تم حذف المستخدم"
    })


# ============================================================
# BINANCE TEST
# ============================================================

@app.get("/api/binance/test")
def binance_test():

    try:

        data = binance_get(
            "/api/v3/ping"
        )

        return jsonify({
            "ok": True,
            "message": "الاتصال بـ Binance يعمل",
            "data": data
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# MARKETS
# ============================================================

@app.get("/api/binance/markets")
def markets():

    try:

        data = binance_get(
            "/api/v3/exchangeInfo"
        )

        result = []

        for item in data.get("symbols", []):

            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get(
                    "isSpotTradingAllowed",
                    True
                )
            ):

                result.append({
                    "symbol": item["symbol"],
                    "baseAsset": item["baseAsset"],
                    "quoteAsset": item["quoteAsset"]
                })

        result.sort(
            key=lambda x: x["symbol"]
        )

        return jsonify({
            "ok": True,
            "count": len(result),

            # الشكل الجديد
            "markets": result,

            # توافق مع النسخ القديمة
            "symbols": result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# PRICES
# ============================================================

@app.get("/api/binance/prices")
def prices():

    try:

        data = binance_get(
            "/api/v3/ticker/24hr"
        )

        result = []

        for item in data:

            symbol = item.get(
                "symbol",
                ""
            )

            if not symbol.endswith("USDT"):
                continue

            try:

                price = float(
                    item["lastPrice"]
                )

                change = float(
                    item["priceChangePercent"]
                )

                high = float(
                    item["highPrice"]
                )

                low = float(
                    item["lowPrice"]
                )

                volume = float(
                    item["quoteVolume"]
                )

                result.append({

                    "symbol": symbol,

                    "price": price,

                    "change": change,
                    "change24h": change,

                    "high": high,
                    "high24h": high,

                    "low": low,
                    "low24h": low,

                    "volume": volume

                })

            except Exception:
                continue

        result.sort(
            key=lambda x: x["volume"],
            reverse=True
        )

        return jsonify({
            "ok": True,
            "count": len(result),
            "prices": result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# SINGLE PRICE
# ============================================================

@app.get("/api/binance/price")
def single_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    try:

        data = binance_get(
            "/api/v3/ticker/24hr",
            {
                "symbol": symbol
            }
        )

        price = float(
            data["lastPrice"]
        )

        change = float(
            data["priceChangePercent"]
        )

        high = float(
            data["highPrice"]
        )

        low = float(
            data["lowPrice"]
        )

        volume = float(
            data["quoteVolume"]
        )

        return jsonify({

            "ok": True,

            "symbol": symbol,

            "price": price,

            "change": change,
            "change24h": change,

            "high": high,
            "high24h": high,

            "low": low,
            "low24h": low,

            "volume": volume

        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# KLINES
# ============================================================

@app.get("/api/binance/klines")
def klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
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
        50,
        min(limit, 1000)
    )

    allowed = {
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w"
    }

    if interval not in allowed:

        return jsonify({
            "ok": False,
            "message":
                "الفاصل الزمني غير صحيح"
        }), 400

    try:

        data = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
        )

        candles = []

        for k in data:

            candles.append({
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            })

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "candles": candles
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
            + result
        )

    return result


def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            -
            values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
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
            (
                avg_gain * (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss * (period - 1)
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


def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous),
            abs(low - previous)
        )

        trs.append(tr)

    return (
        sum(trs[-period:])
        /
        period
    )


def macd(values):

    if len(values) < 35:
        return None

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)

    if ema12 is None or ema26 is None:
        return None

    return ema12 - ema26


# ============================================================
# ANALYSIS
# ============================================================

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

    allowed = {
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
        "1w"
    }

    if interval not in allowed:

        return jsonify({
            "ok": False,
            "message":
                "الفاصل الزمني غير صحيح"
        }), 400

    try:

        raw = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": 250
            }
        )

        candles = []

        for k in raw:

            candles.append({
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            })

        if len(candles) < 50:

            raise RuntimeError(
                "عدد الشموع غير كافٍ للتحليل"
            )

        closes = [
            x["close"]
            for x in candles
        ]

        volumes = [
            x["volume"]
            for x in candles
        ]

        highs = [
            x["high"]
            for x in candles
        ]

        lows = [
            x["low"]
            for x in candles
        ]

        price = closes[-1]

        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, 200)

        rsi_value = rsi(
            closes,
            14
        )

        macd_value = macd(
            closes
        )

        atr_value = atr(
            candles,
            14
        )

        support = min(
            lows[-30:]
        )

        resistance = max(
            highs[-30:]
        )

        avg_volume = (
            sum(volumes[-21:-1])
            /
            20
            if len(volumes) >= 21
            else volumes[-1]
        )

        volume_ratio = (
            volumes[-1] / avg_volume
            if avg_volume
            else 1
        )

        # ====================================================
        # SCORE 0 - 100
        # ====================================================

        score = 50

        reasons = []

        if ema20 is not None:

            if price > ema20:

                score += 8

                reasons.append(
                    "السعر فوق EMA20"
                )

            else:

                score -= 8

                reasons.append(
                    "السعر تحت EMA20"
                )

        if ema50 is not None:

            if price > ema50:

                score += 10

                reasons.append(
                    "السعر فوق EMA50"
                )

            else:

                score -= 10

                reasons.append(
                    "السعر تحت EMA50"
                )

        if ema200 is not None:

            if price > ema200:

                score += 12

                reasons.append(
                    "الاتجاه العام فوق EMA200"
                )

            else:

                score -= 12

                reasons.append(
                    "السعر تحت EMA200"
                )

        if rsi_value is not None:

            if 50 <= rsi_value <= 70:

                score += 8

                reasons.append(
                    "RSI يدعم الزخم الإيجابي"
                )

            elif rsi_value > 70:

                score -= 2

                reasons.append(
                    "RSI في منطقة تشبع شرائي"
                )

            elif rsi_value < 30:

                score += 2

                reasons.append(
                    "RSI في منطقة تشبع بيعي"
                )

            else:

                score -= 4

                reasons.append(
                    "RSI لا يعطي تأكيداً قوياً"
                )

        if volume_ratio >= 1.5:

            score += 10

            reasons.append(
                "ارتفاع واضح في حجم التداول"
            )

        elif volume_ratio >= 1.1:

            score += 4

            reasons.append(
                "حجم التداول أعلى من المتوسط"
            )

        else:

            reasons.append(
                "حجم التداول قريب من المتوسط"
            )

        previous_resistance = max(
            highs[-21:-1]
        )

        if price > previous_resistance:

            score += 10

            reasons.append(
                "اختراق مقاومة قريبة"
            )

        score = max(
            0,
            min(score, 100)
        )

        # ====================================================
        # SIGNAL
        # ====================================================

        if score >= 78:

            signal = "شراء قوي"

        elif score >= 62:

            signal = "شراء"

        elif score <= 22:

            signal = "بيع قوي"

        elif score <= 38:

            signal = "بيع"

        else:

            signal = "حيادي"

        # ====================================================
        # TREND
        # ====================================================

        if (
            ema20
            and
            ema50
            and
            price > ema20
            and
            ema20 > ema50
        ):

            trend = "صاعد"

        elif (
            ema20
            and
            ema50
            and
            price < ema20
            and
            ema20 < ema50
        ):

            trend = "هابط"

        else:

            trend = "جانبي"

        # ====================================================
        # LEVELS
        # ====================================================

        volatility = (
            atr_value
            if atr_value
            else price * 0.01
        )

        if signal in ("شراء", "شراء قوي"):

            entry = price

            sl = max(
                support,
                price - volatility * 1.5
            )

            risk = max(
                entry - sl,
                price * 0.002
            )

            tp1 = entry + risk * 1.5
            tp2 = entry + risk * 2.5
            tp3 = entry + risk * 4.0

        elif signal in ("بيع", "بيع قوي"):

            entry = price

            sl = min(
                resistance,
                price + volatility * 1.5
            )

            risk = max(
                sl - entry,
                price * 0.002
            )

            tp1 = entry - risk * 1.5
            tp2 = entry - risk * 2.5
            tp3 = entry - risk * 4.0

        else:

            entry = price
            sl = support
            tp1 = resistance
            tp2 = resistance
            tp3 = resistance

            risk = abs(
                entry - sl
            )

        reward = abs(
            tp2 - entry
        )

        rr = (
            reward / risk
            if risk > 0
            else 0
        )

        # ====================================================
        # 24H
        # ====================================================

        try:

            ticker = binance_get(
                "/api/v3/ticker/24hr",
                {
                    "symbol": symbol
                }
            )

            change = float(
                ticker["priceChangePercent"]
            )

            high24h = float(
                ticker["highPrice"]
            )

            low24h = float(
                ticker["lowPrice"]
            )

            volume24h = float(
                ticker["quoteVolume"]
            )

        except Exception:

            change = 0
            high24h = price
            low24h = price
            volume24h = 0

        # ====================================================
        # RESPONSE
        # ====================================================

        result = {

            "symbol": symbol,

            "interval": interval,

            "price": price,

            "change": change,
            "change24h": change,

            "high": high24h,
            "high24h": high24h,

            "low": low24h,
            "low24h": low24h,

            "volume": volume24h,

            "signal": signal,

            "score": score,

            # مهم: الواجهة تعرضه /10
            "score10": round(
                score / 10,
                1
            ),

            "entry": entry,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "sl": sl,

            "rr": rr,

            "rsi": rsi_value,

            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,

            "macd": macd_value,

            "atr": atr_value,

            "support": support,
            "resistance": resistance,

            "volumeRatio": volume_ratio,

            "trend": trend,
            "direction": trend,

            "reasons": reasons,

            "candles": candles[-120:]
        }

        return jsonify({

            "ok": True,

            # الشكل الأساسي
            "analysis": result,

            # توافق مباشر
            **result

        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# MARKET SCANNER
# ============================================================

@app.get("/api/binance/scan")
def scan():

    try:

        ticker_data = binance_get(
            "/api/v3/ticker/24hr"
        )

        candidates = []

        for item in ticker_data:

            symbol = item.get(
                "symbol",
                ""
            )

            if not symbol.endswith("USDT"):
                continue

            try:

                change = float(
                    item["priceChangePercent"]
                )

                volume = float(
                    item["quoteVolume"]
                )

                price = float(
                    item["lastPrice"]
                )

                if volume < 500000:
                    continue

                candidates.append({

                    "symbol": symbol,

                    "price": price,

                    "change": change,

                    "change24h": change,

                    "volume": volume

                })

            except Exception:

                continue

        candidates.sort(
            key=lambda x:
                abs(x["change"]),
            reverse=True
        )

        return jsonify({

            "ok": True,

            "count":
                len(candidates),

            "results":
                candidates[:100]

        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({

        "ok": True,

        "service":
            "تحليل العملات الرقمية",

        "status":
            "running"

    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
