import os
import time
import math
import hmac
import hashlib
import requests

from functools import wraps
from flask import (
    Flask,
    jsonify,
    request,
    session,
    render_template,
)

import psycopg
from psycopg.rows import dict_row
from psycopg import errors

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# APP
# ============================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_2026"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True


# ============================================================
# ENV
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "aaaksazzz"
)

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    "4573261aA"
)


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
    "https://api4.binance.com",
]

REQUEST_TIMEOUT = 15


# ============================================================
# DATABASE - POSTGRESQL
# ============================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL غير موجود في Environment Variables"
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


def init_db():
    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                created_at BIGINT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id BIGINT PRIMARY KEY
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                theme TEXT NOT NULL DEFAULT 'dark',
                interval TEXT NOT NULL DEFAULT '15m',
                symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
                refresh_seconds INTEGER NOT NULL DEFAULT 30,
                notifications BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)


# ============================================================
# PASSWORD HASH
# ============================================================

def hash_password(password):
    salt = os.urandom(16)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        120000,
    )

    return (
        "pbkdf2_sha256$120000$"
        + salt.hex()
        + "$"
        + derived.hex()
    )


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations)

        salt = bytes.fromhex(salt_hex)

        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        ).hex()

        return hmac.compare_digest(
            calculated,
            hash_hex,
        )

    except Exception:
        return False


# ============================================================
# HELPERS
# ============================================================

def now_ts():
    return int(time.time())


def json_body():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {}

    return data


def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                username,
                email,
                plan,
                created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        ).fetchone()

    return row


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
                "error": "صلاحيات الأدمن مطلوبة"
            }), 403

        return fn(*args, **kwargs)

    return wrapper


# ============================================================
# PAGE
# ============================================================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/admin")
def admin_page():
    return render_template("admin.html")


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/api/admin/login")
def admin_login():

    data = json_body()

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if (
        username == ADMIN_USERNAME
        and password == ADMIN_PASSWORD
    ):
        session.clear()
        session["admin"] = True

        return jsonify({
            "ok": True,
            "admin": True,
            "username": ADMIN_USERNAME,
        })

    return jsonify({
        "ok": False,
        "error": "بيانات الأدمن غير صحيحة"
    }), 401


@app.get("/api/admin/me")
def admin_me():

    if session.get("admin"):
        return jsonify({
            "ok": True,
            "admin": True,
            "username": ADMIN_USERNAME,
        })

    return jsonify({
        "ok": False,
        "admin": False,
    }), 401


@app.post("/api/admin/logout")
def admin_logout():

    session.pop("admin", None)

    return jsonify({
        "ok": True
    })


# ============================================================
# REGISTER
# ============================================================

@app.post("/api/auth/register")
def register():

    data = json_body()

    username = str(
        data.get("username", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if not username:
        return jsonify({
            "ok": False,
            "error": "اسم المستخدم مطلوب"
        }), 400

    if len(username) < 3:
        return jsonify({
            "ok": False,
            "error": "اسم المستخدم يجب أن يكون 3 أحرف على الأقل"
        }), 400

    if len(password) < 6:
        return jsonify({
            "ok": False,
            "error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
        }), 400

    email = email or None

    password_hash = hash_password(password)

    try:

        with get_db() as conn:

            row = conn.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    password_hash,
                    plan,
                    created_at
                )
                VALUES (%s, %s, %s, 'free', %s)
                RETURNING id
                """,
                (
                    username,
                    email,
                    password_hash,
                    now_ts(),
                ),
            ).fetchone()

            user_id = row["id"]

            conn.execute(
                """
                INSERT INTO settings (
                    user_id
                )
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id,),
            )

        session.clear()
        session["user_id"] = user_id

        return jsonify({
            "ok": True,
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "plan": "free",
            }
        })

    except errors.UniqueViolation:

        return jsonify({
            "ok": False,
            "error": "اسم المستخدم أو البريد الإلكتروني مستخدم مسبقًا"
        }), 409


# ============================================================
# USER LOGIN
# ============================================================

@app.post("/api/auth/login")
def login():

    data = json_body()

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    with get_db() as conn:

        user = conn.execute(
            """
            SELECT
                id,
                username,
                email,
                password_hash,
                plan,
                created_at
            FROM users
            WHERE username = %s
            """,
            (username,),
        ).fetchone()

    if not user:
        return jsonify({
            "ok": False,
            "error": "اسم المستخدم أو كلمة المرور غير صحيحة"
        }), 401

    if not verify_password(
        password,
        user["password_hash"]
    ):
        return jsonify({
            "ok": False,
            "error": "اسم المستخدم أو كلمة المرور غير صحيحة"
        }), 401

    session.clear()
    session["user_id"] = user["id"]

    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "plan": user["plan"],
            "created_at": user["created_at"],
        }
    })


@app.post("/api/auth/logout")
def logout():

    session.pop("user_id", None)

    return jsonify({
        "ok": True
    })


@app.get("/api/auth/me")
def auth_me():

    user = current_user()

    if not user:
        return jsonify({
            "ok": False,
            "logged_in": False,
        }), 401

    return jsonify({
        "ok": True,
        "logged_in": True,
        "user": user,
    })


# ============================================================
# SETTINGS
# ============================================================

@app.get("/api/settings")
@login_required
def get_settings():

    user = current_user()

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT
                theme,
                interval,
                symbol,
                refresh_seconds,
                notifications
            FROM settings
            WHERE user_id = %s
            """,
            (user["id"],),
        ).fetchone()

        if not row:

            conn.execute(
                """
                INSERT INTO settings (
                    user_id
                )
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user["id"],),
            )

            row = conn.execute(
                """
                SELECT
                    theme,
                    interval,
                    symbol,
                    refresh_seconds,
                    notifications
                FROM settings
                WHERE user_id = %s
                """,
                (user["id"],),
            ).fetchone()

    return jsonify({
        "ok": True,
        "settings": row,
    })


@app.post("/api/settings")
@login_required
def save_settings():

    user = current_user()
    data = json_body()

    theme = str(
        data.get("theme", "dark")
    )

    interval = str(
        data.get("interval", "15m")
    )

    symbol = str(
        data.get("symbol", "BTCUSDT")
    ).upper()

    try:
        refresh_seconds = int(
            data.get("refresh_seconds", 30)
        )
    except Exception:
        refresh_seconds = 30

    notifications = data.get(
        "notifications",
        True
    )

    if isinstance(notifications, str):
        notifications = notifications.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
    else:
        notifications = bool(notifications)

    refresh_seconds = max(
        5,
        min(refresh_seconds, 3600)
    )

    with get_db() as conn:

        conn.execute(
            """
            INSERT INTO settings (
                user_id,
                theme,
                interval,
                symbol,
                refresh_seconds,
                notifications
            )
            VALUES (
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                theme = EXCLUDED.theme,
                interval = EXCLUDED.interval,
                symbol = EXCLUDED.symbol,
                refresh_seconds = EXCLUDED.refresh_seconds,
                notifications = EXCLUDED.notifications
            """,
            (
                user["id"],
                theme,
                interval,
                symbol,
                refresh_seconds,
                notifications,
            ),
        )

    return jsonify({
        "ok": True
    })


# ============================================================
# ADMIN STATS
# ============================================================

@app.get("/api/admin/stats")
@admin_required
def admin_stats():

    with get_db() as conn:

        total = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            """
        ).fetchone()["count"]

        free = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            WHERE plan = 'free'
            """
        ).fetchone()["count"]

        premium = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            WHERE plan = 'premium'
            """
        ).fetchone()["count"]

    return jsonify({
        "ok": True,
        "total_users": total,
        "free_users": free,
        "premium_users": premium,
    })


@app.get("/api/admin/users")
@admin_required
def admin_users():

    with get_db() as conn:

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

    return jsonify({
        "ok": True,
        "users": users,
    })


@app.post("/api/admin/users/<int:user_id>/plan")
@admin_required
def admin_update_plan(user_id):

    data = json_body()

    plan = str(
        data.get("plan", "free")
    ).strip().lower()

    allowed = {
        "free",
        "premium",
    }

    if plan not in allowed:
        return jsonify({
            "ok": False,
            "error": "الخطة غير صحيحة"
        }), 400

    with get_db() as conn:

        row = conn.execute(
            """
            UPDATE users
            SET plan = %s
            WHERE id = %s
            RETURNING id, username, email, plan
            """,
            (
                plan,
                user_id,
            ),
        ).fetchone()

    if not row:
        return jsonify({
            "ok": False,
            "error": "المستخدم غير موجود"
        }), 404

    return jsonify({
        "ok": True,
        "user": row,
    })


@app.delete("/api/admin/users/<int:user_id>")
@admin_required
def admin_delete_user(user_id):

    with get_db() as conn:

        row = conn.execute(
            """
            DELETE FROM users
            WHERE id = %s
            RETURNING id
            """,
            (user_id,),
        ).fetchone()

    if not row:
        return jsonify({
            "ok": False,
            "error": "المستخدم غير موجود"
        }), 404

    return jsonify({
        "ok": True
    })


# ============================================================
# BINANCE REQUEST
# ============================================================

def binance_get(path, params=None):

    last_error = None

    for base in BINANCE_APIS:

        try:

            url = base.rstrip("/") + path

            response = requests.get(
                url,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": "Mudarib-Abo-Saud/1.0"
                },
            )

            if response.status_code == 200:
                return response.json()

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

            if response.status_code in (
                418,
                429,
                500,
                502,
                503,
                504,
            ):
                time.sleep(0.4)
                continue

        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError(
        last_error or "فشل الاتصال مع Binance"
    )


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
            "binance": True,
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "binance": False,
            "error": str(e),
        }), 503


# ============================================================
# MARKETS
# ============================================================

@app.get("/api/binance/markets")
def binance_markets():

    try:

        data = binance_get(
            "/api/v3/exchangeInfo"
        )

        symbols = []

        for item in data.get(
            "symbols",
            []
        ):

            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed", True)
            ):
                symbols.append({
                    "symbol": item["symbol"],
                    "baseAsset": item["baseAsset"],
                    "quoteAsset": item["quoteAsset"],
                })

        return jsonify({
            "ok": True,
            "count": len(symbols),
            "symbols": symbols,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


# ============================================================
# PRICES
# ============================================================

@app.get("/api/binance/prices")
def binance_prices():

    try:

        data = binance_get(
            "/api/v3/ticker/price"
        )

        prices = []

        for item in data:

            symbol = item.get(
                "symbol",
                ""
            )

            if symbol.endswith("USDT"):
                prices.append({
                    "symbol": symbol,
                    "price": item.get("price"),
                })

        return jsonify({
            "ok": True,
            "prices": prices,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


@app.get("/api/binance/price")
def binance_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    try:

        data = binance_get(
            "/api/v3/ticker/price",
            {
                "symbol": symbol
            },
        )

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "price": float(data["price"]),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


# ============================================================
# KLINES
# ============================================================

@app.get("/api/binance/klines")
def binance_klines():

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
                "200"
            )
        )
    except Exception:
        limit = 200

    limit = max(
        10,
        min(limit, 1000)
    )

    try:

        data = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
        )

        candles = []

        for k in data:

            candles.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
            })

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "candles": candles,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):

    if not values:
        return []

    period = int(period)

    result = [None] * len(values)

    if len(values) < period:
        return result

    initial = sum(
        values[:period]
    ) / period

    result[period - 1] = initial

    multiplier = 2 / (
        period + 1
    )

    previous = initial

    for i in range(
        period,
        len(values)
    ):

        previous = (
            values[i] - previous
        ) * multiplier + previous

        result[i] = previous

    return result


def rsi(values, period=14):

    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i] - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period]) / period
    )

    avg_loss = (
        sum(losses[:period]) / period
    )

    if avg_loss == 0:
        result[period] = 100
    else:
        rs = avg_gain / avg_loss
        result[period] = (
            100 - (100 / (1 + rs))
        )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss * (period - 1)
            )
            + losses[i]
        ) / period

        if avg_loss == 0:
            result[i + 1] = 100
        else:

            rs = (
                avg_gain / avg_loss
            )

            result[i + 1] = (
                100 - (100 / (1 + rs))
            )

    return result


def atr(candles, period=14):

    result = [None] * len(candles)

    if len(candles) <= period:
        return result

    trs = []

    for i, candle in enumerate(candles):

        high = candle["high"]
        low = candle["low"]

        if i == 0:
            tr = high - low
        else:

            previous_close = (
                candles[i - 1]["close"]
            )

            tr = max(
                high - low,
                abs(
                    high - previous_close
                ),
                abs(
                    low - previous_close
                ),
            )

        trs.append(tr)

    current = (
        sum(trs[:period]) / period
    )

    result[period - 1] = current

    for i in range(
        period,
        len(trs)
    ):

        current = (
            (
                current * (period - 1)
            )
            + trs[i]
        ) / period

        result[i] = current

    return result


def macd(values):

    fast = ema(values, 12)
    slow = ema(values, 26)

    macd_line = []

    for i in range(len(values)):

        if (
            fast[i] is None
            or slow[i] is None
        ):
            macd_line.append(None)
        else:
            macd_line.append(
                fast[i] - slow[i]
            )

    valid = [
        x for x in macd_line
        if x is not None
    ]

    signal_values = ema(
        valid,
        9
    )

    signal = [None] * len(
        macd_line
    )

    j = 0

    for i in range(
        len(macd_line)
    ):

        if macd_line[i] is not None:

            if j < len(signal_values):
                signal[i] = signal_values[j]

            j += 1

    histogram = []

    for i in range(
        len(macd_line)
    ):

        if (
            macd_line[i] is None
            or signal[i] is None
        ):
            histogram.append(None)
        else:
            histogram.append(
                macd_line[i] - signal[i]
            )

    return (
        macd_line,
        signal,
        histogram,
    )


# ============================================================
# ANALYSIS
# ============================================================

def safe_round(value, digits=8):

    if value is None:
        return None

    try:
        return round(
            float(value),
            digits
        )
    except Exception:
        return None


def calculate_analysis(
    candles,
    symbol,
    interval
):

    if len(candles) < 50:
        raise ValueError(
            "عدد الشموع غير كافٍ للتحليل"
        )

    closes = [
        c["close"]
        for c in candles
    ]

    volumes = [
        c["volume"]
        for c in candles
    ]

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
        candles,
        14
    )

    macd_line, macd_signal, macd_hist = (
        macd(closes)
    )

    last = candles[-1]

    price = last["close"]

    ema20_value = ema20_values[-1]
    ema50_value = ema50_values[-1]
    ema200_value = ema200_values[-1]

    rsi_value = rsi_values[-1]
    atr_value = atr_values[-1]

    macd_value = macd_line[-1]
    macd_signal_value = macd_signal[-1]
    macd_hist_value = macd_hist[-1]

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 50
    reasons = []

    if (
        ema20_value is not None
        and price > ema20_value
    ):
        score += 8
        reasons.append(
            "السعر فوق EMA20"
        )
    else:
        score -= 8
        reasons.append(
            "السعر تحت EMA20"
        )

    if (
        ema50_value is not None
        and price > ema50_value
    ):
        score += 8
        reasons.append(
            "السعر فوق EMA50"
        )
    else:
        score -= 8
        reasons.append(
            "السعر تحت EMA50"
        )

    if (
        ema200_value is not None
        and price > ema200_value
    ):
        score += 10
        reasons.append(
            "السعر فوق EMA200"
        )
    else:
        score -= 10
        reasons.append(
            "السعر تحت EMA200"
        )

    if rsi_value is not None:

        if 50 <= rsi_value <= 70:
            score += 8
            reasons.append(
                "RSI داعم للشراء"
            )

        elif rsi_value > 70:
            score += 2
            reasons.append(
                "RSI مرتفع"
            )

        elif rsi_value < 30:
            score += 3
            reasons.append(
                "RSI في منطقة تشبع بيع"
            )

        else:
            score -= 5
            reasons.append(
                "RSI ضعيف"
            )

    if (
        macd_hist_value is not None
        and macd_hist_value > 0
    ):
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

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if score >= 80:
        signal = "شراء قوي"
        direction = "صاعد"

    elif score >= 65:
        signal = "شراء"
        direction = "صاعد"

    elif score <= 20:
        signal = "بيع قوي"
        direction = "هابط"

    elif score <= 35:
        signal = "بيع"
        direction = "هابط"

    else:
        signal = "حيادي"
        direction = "محايد"

    # --------------------------------------------------------
    # SUPPORT / RESISTANCE
    # --------------------------------------------------------

    recent = candles[-20:]

    support = min(
        c["low"]
        for c in recent
    )

    resistance = max(
        c["high"]
        for c in recent
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if len(volumes) >= 21:

        average_volume = (
            sum(volumes[-21:-1])
            / 20
        )

        volume_ratio = (
            volumes[-1] / average_volume
            if average_volume > 0
            else 0
        )

    else:
        volume_ratio = 0

    # --------------------------------------------------------
    # TARGETS
    # --------------------------------------------------------

    entry = price

    if atr_value is None:
        atr_value = price * 0.01

    if signal in (
        "شراء",
        "شراء قوي"
    ):

        sl = min(
            support,
            entry - (
                atr_value * 1.5
            )
        )

        risk = max(
            entry - sl,
            entry * 0.005
        )

        tp1 = entry + risk
        tp2 = entry + (
            risk * 2
        )
        tp3 = entry + (
            risk * 3
        )

    elif signal in (
        "بيع",
        "بيع قوي"
    ):

        sl = max(
            resistance,
            entry + (
                atr_value * 1.5
            )
        )

        risk = max(
            sl - entry,
            entry * 0.005
        )

        tp1 = entry - risk
        tp2 = entry - (
            risk * 2
        )
        tp3 = entry - (
            risk * 3
        )

    else:

        sl = support

        risk = abs(
            entry - support
        )

        if risk <= 0:
            risk = entry * 0.01

        tp1 = resistance
        tp2 = entry + (
            risk * 2
        )
        tp3 = entry + (
            risk * 3
        )

    rr = (
        abs(tp2 - entry)
        / abs(entry - sl)
        if abs(entry - sl) > 0
        else 0
    )

    # --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candles_output = []

    for c in candles[-100:]:

        candles_output.append({
            "time": c["open_time"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["volume"],
        })

    return {
        "symbol": symbol,
        "interval": interval,

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10": round(
            score / 10,
            1
        ),

        "entry": safe_round(entry),
        "tp1": safe_round(tp1),
        "tp2": safe_round(tp2),
        "tp3": safe_round(tp3),
        "sl": safe_round(sl),

        "rr": safe_round(
            rr,
            2
        ),

        "price": safe_round(
            price
        ),

        "rsi": safe_round(
            rsi_value,
            2
        ),

        "ema20": safe_round(
            ema20_value
        ),

        "ema50": safe_round(
            ema50_value
        ),

        "ema200": safe_round(
            ema200_value
        ),

        "macd": safe_round(
            macd_value
        ),

        "macd_signal": safe_round(
            macd_signal_value
        ),

        "macd_histogram": safe_round(
            macd_hist_value
        ),

        "atr": safe_round(
            atr_value
        ),

        "support": safe_round(
            support
        ),

        "resistance": safe_round(
            resistance
        ),

        "volume_ratio": safe_round(
            volume_ratio,
            2
        ),

        "reasons": reasons,

        "candles": candles_output,
    }


# ============================================================
# ANALYSIS API
# ============================================================

@app.get("/api/binance/analysis")
def binance_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        raw = binance_get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": 250,
            },
        )

        candles = []

        for k in raw:

            candles.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
            })

        result = calculate_analysis(
            candles,
            symbol,
            interval
        )

        return jsonify({
            "ok": True,
            "analysis": result,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


# ============================================================
# SCAN
# ============================================================

@app.get("/api/binance/scan")
def binance_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    limit = request.args.get(
        "limit",
        "30"
    )

    try:
        limit = max(
            1,
            min(int(limit), 100)
        )
    except Exception:
        limit = 30

    try:

        exchange = binance_get(
            "/api/v3/exchangeInfo"
        )

        symbols = []

        for item in exchange.get(
            "symbols",
            []
        ):

            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed", True)
            ):
                symbols.append(
                    item["symbol"]
                )

        results = []

        for symbol in symbols[:limit]:

            try:

                raw = binance_get(
                    "/api/v3/klines",
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": 250,
                    },
                )

                candles = []

                for k in raw:

                    candles.append({
                        "open_time": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": k[6],
                    })

                analysis = calculate_analysis(
                    candles,
                    symbol,
                    interval
                )

                results.append({
                    "symbol": symbol,
                    "signal": analysis["signal"],
                    "score": analysis["score"],
                    "score10": analysis["score10"],
                    "price": analysis["price"],
                    "rsi": analysis["rsi"],
                    "direction": analysis["direction"],
                })

            except Exception:
                continue

        results.sort(
            key=lambda x: x.get(
                "score",
                0
            ),
            reverse=True
        )

        return jsonify({
            "ok": True,
            "interval": interval,
            "count": len(results),
            "results": results,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 503


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    try:

        with get_db() as conn:

            conn.execute(
                "SELECT 1"
            ).fetchone()

        return jsonify({
            "ok": True,
            "status": "running",
            "database": "postgresql",
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "status": "database_error",
            "database": "postgresql",
            "error": str(e),
        }), 503


# ============================================================
# DATABASE INIT
# ============================================================

try:
    init_db()
    print("==========================================")
    print(" PostgreSQL connected successfully")
    print(" Database tables ready")
    print("==========================================")

except Exception as e:

    print("==========================================")
    print(" DATABASE ERROR")
    print(str(e))
    print("==========================================")

    # نخلي Render يوضح الخطأ في Logs
    raise


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
        debug=False,
    )
