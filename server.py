import os
import re
import json
import time
import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, request, jsonify, session, send_from_directory, redirect
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg
except Exception:
    psycopg = None


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

# مهم: في Northflank يفضّل إضافة SECRET_KEY كـ Secret
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

PORT = int(os.getenv("PORT", "8080"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()


# =========================================================
# ADMIN
# =========================================================

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "aaaksazzz").strip()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", os.getenv("ADMIN_KEY", "")).strip()

PAYMENT_ADDRESS = os.getenv("TRC20_ADDRESS", "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6").strip()


# =========================================================
# MARKET SOURCES
# =========================================================

OKX_BASE = "https://www.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 Mudarib-Abo-Saud/5.0"
})


# =========================================================
# CACHE
# =========================================================

CACHE = {}
CACHE_LOCK = threading.Lock()
CACHE_SECONDS = 120


def cache_get(key):

    with CACHE_LOCK:

        item = CACHE.get(key)

        if not item:
            return None

        if time.time() - item["time"] > CACHE_SECONDS:

            CACHE.pop(key, None)

            return None

        return item["data"]


def cache_set(key, data):

    with CACHE_LOCK:

        CACHE[key] = {
            "time": time.time(),
            "data": data
        }


# =========================================================
# HELPERS
# =========================================================

def now_utc():

    return datetime.now(timezone.utc)


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


def hash_password(password):
    return generate_password_hash(str(password))


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


# =========================================================
# DATABASE
# =========================================================

SQLITE_FILE = os.getenv(
    "SQLITE_FILE",
    "mudarib.db"
)


def using_postgres():

    return bool(
        DATABASE_URL and psycopg
    )


def db():

    if using_postgres():

        return psycopg.connect(
            DATABASE_URL,
            connect_timeout=10
        )

    return sqlite3.connect(
        SQLITE_FILE,
        timeout=20,
        check_same_thread=False
    )


def init_db():

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE,
                    name TEXT,
                    password TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    subscription_until TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
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
                CREATE TABLE IF NOT EXISTS news_items (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT,
                    source TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

        else:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE,
                    name TEXT,
                    password TEXT NOT NULL,
                    is_admin INTEGER DEFAULT 0,
                    subscription_until TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    txid TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT,
                    source TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

        conn.commit()
        conn.close()

        print(
            "DATABASE OK:",
            "PostgreSQL" if using_postgres() else "SQLite"
        )

    except Exception as e:

        print(
            "DATABASE ERROR:",
            e
        )


def parse_date(value):

    if not value:
        return None

    if isinstance(value, datetime):

        if value.tzinfo is None:

            return value.replace(
                tzinfo=timezone.utc
            )

        return value

    try:

        text = str(value).replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            text
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except Exception:

        return None


# =========================================================
# PLANS
# =========================================================

PLANS = {

    "7d": {
        "name": "7 أيام",
        "days": 7,
        "amount": 10.0
    },

    "30d": {
        "name": "30 يوم",
        "days": 30,
        "amount": 20.0
    },

    "90d": {
        "name": "90 يوم",
        "days": 90,
        "amount": 30.0
    }

}


# =========================================================
# AUTH
# =========================================================

@app.post("/api/auth/register")
@app.post("/api/register")
def register():

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

    if not username:
        username = email

    if len(name) < 2:

        return jsonify({
            "ok": False,
            "message": "فضلاً اكتب الاسم بشكل صحيح"
        }), 400

    if "@" not in email:

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

        conn = db()
        cur = conn.cursor()

        if using_postgres():

            cur.execute("""
                SELECT id
                FROM users
                WHERE email=%s
                   OR username=%s
            """, (
                email,
                username
            ))

        else:

            cur.execute("""
                SELECT id
                FROM users
                WHERE email=?
                   OR username=?
            """, (
                email,
                username
            ))

        if cur.fetchone():

            conn.close()

            return jsonify({
                "ok": False,
                "message": "البريد الإلكتروني أو اسم المستخدم مستخدم مسبقاً"
            }), 400

        if using_postgres():

            cur.execute("""
                INSERT INTO users
                (username,email,name,password)
                VALUES(%s,%s,%s,%s)
            """, (
                username,
                email,
                name,
                generate_password_hash(password)
            ))

        else:

            cur.execute("""
                INSERT INTO users
                (username,email,name,password)
                VALUES(?,?,?,?)
            """, (
                username,
                email,
                name,
                generate_password_hash(password)
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

        return jsonify({
            "ok": False,
            "message": "تعذر إنشاء الحساب"
        }), 500


@app.post("/api/auth/login")
@app.post("/api/login")
def login():

    data = request.get_json(
        silent=True
    ) or {}

    identifier = str(
        data.get("email")
        or data.get("username")
        or ""
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if not identifier or not password:

        return jsonify({
            "ok": False,
            "message": "أدخل بيانات الدخول"
        }), 400

    # =====================================================
    # ADMIN LOGIN
    # =====================================================

    if (
        identifier == ADMIN_USERNAME.lower()
        and ADMIN_PASSWORD
        and password == ADMIN_PASSWORD
    ):

        session.clear()

        session["user"] = ADMIN_USERNAME
        session["admin"] = True

        return jsonify({
            "ok": True,
            "user": ADMIN_USERNAME,
            "admin": True,
            "subscriptionUntil": None
        })

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

            cur.execute("""
                SELECT
                    username,
                    email,
                    name,
                    password,
                    is_admin,
                    subscription_until
                FROM users
                WHERE LOWER(username)=LOWER(%s)
                   OR LOWER(email)=LOWER(%s)
            """, (
                identifier,
                identifier
            ))

        else:

            cur.execute("""
                SELECT
                    username,
                    email,
                    name,
                    password,
                    is_admin,
                    subscription_until
                FROM users
                WHERE LOWER(username)=LOWER(?)
                   OR LOWER(email)=LOWER(?)
            """, (
                identifier,
                identifier
            ))

        row = cur.fetchone()

        conn.close()

        if not row:

            return jsonify({
                "ok": False,
                "message": "بيانات الدخول غير صحيحة"
            }), 401

        saved_username = row[0]
        saved_email = row[1]
        saved_name = row[2]
        saved_password = row[3]
        is_admin = bool(row[4])
        subscription_until = row[5]

        valid_password = False

        try:
            valid_password = check_password_hash(saved_password, password)
        except Exception:
            valid_password = False

        # دعم الحسابات القديمة التي كانت تستخدم SHA-256، مع ترقية كلمة المرور تلقائياً.
        if not valid_password and saved_password == hash_password(password):
            valid_password = True
            try:
                conn = db()
                cur = conn.cursor()
                if using_postgres():
                    cur.execute("UPDATE users SET password=%s WHERE username=%s", (generate_password_hash(password), saved_username))
                else:
                    cur.execute("UPDATE users SET password=? WHERE username=?", (generate_password_hash(password), saved_username))
                conn.commit()
                conn.close()
            except Exception as upgrade_error:
                print("PASSWORD UPGRADE ERROR:", upgrade_error)

        if not valid_password:

            return jsonify({
                "ok": False,
                "message": "بيانات الدخول غير صحيحة"
            }), 401

        session.clear()

        session["user"] = saved_username
        session["admin"] = is_admin

        return jsonify({
            "ok": True,
            "user": saved_username,
            "email": saved_email,
            "name": saved_name,
            "admin": is_admin,
            "subscriptionUntil": (
                subscription_until.isoformat()
                if hasattr(
                    subscription_until,
                    "isoformat"
                )
                else subscription_until
            )
        })

    except Exception as e:

        print(
            "LOGIN ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "message": "خطأ في قاعدة البيانات"
        }), 500


# =========================================================
# ADMIN AUTH
# =========================================================

def require_admin():

    return bool(
        session.get("admin")
    )


@app.post("/api/admin/login")
def admin_login():

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username")
        or data.get("email")
        or ""
    ).strip()

    password = str(
        data.get("password")
        or ""
    )

    if (
        username.lower() == ADMIN_USERNAME.lower()
        and ADMIN_PASSWORD
        and password == ADMIN_PASSWORD
    ):

        session.clear()

        session["user"] = ADMIN_USERNAME
        session["admin"] = True

        return jsonify({
            "ok": True,
            "admin": True,
            "user": ADMIN_USERNAME
        })

    return jsonify({
        "ok": False,
        "message": "بيانات الأدمن غير صحيحة"
    }), 401


@app.get("/api/admin/me")
def admin_me():

    if require_admin():

        return jsonify({
            "ok": True,
            "admin": True,
            "user": session.get("user")
        })

    return jsonify({
        "ok": True,
        "admin": False,
        "user": None
    })


@app.post("/api/admin/logout")
def admin_logout():

    session.clear()

    return jsonify({
        "ok": True
    })


# =========================================================
# NORMAL AUTH
# =========================================================

@app.post("/api/auth/logout")
@app.post("/api/logout")
def logout():

    session.clear()

    return jsonify({
        "ok": True
    })


@app.get("/api/auth/me")
@app.get("/api/me")
def me():

    username = session.get(
        "user"
    )

    if not username:

        return jsonify({
            "ok": True,
            "user": None,
            "admin": False
        })

    return jsonify({
        "ok": True,
        "user": username,
        "admin": bool(
            session.get("admin")
        )
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

    if str(
        data.get("code")
    ) != "0":

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

    if cached is not None:
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

    key = (
        "okx_tickers_"
        + inst_type
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    rows = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": inst_type
        }
    )

    cache_set(
        key,
        rows
    )

    return rows


def okx_candles(
    inst_id,
    bar="15m",
    limit=120
):

    bar = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
        "1w": "1W"
    }.get(str(bar).lower(), bar)

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def analyze_candles(candles, long_threshold=70, short_threshold=30):

    if len(candles) < 50:
        raise RuntimeError("بيانات غير كافية")

    closes = [safe_float(x.get("c")) for x in candles]
    highs = [safe_float(x.get("h")) for x in candles]
    lows = [safe_float(x.get("l")) for x in candles]
    volumes = [safe_float(x.get("v")) for x in candles]

    price = closes[-1]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    r = rsi(closes)

    # ATR مبسط ومستقر لحساب وقف/هدف متكيف مع تذبذب كل أصل.
    trs = []
    for i in range(1, len(candles)):
        prev = closes[i - 1]
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - prev),
            abs(lows[i] - prev)
        ))
    atr = sum(trs[-14:]) / max(1, len(trs[-14:])) if trs else 0.0
    atr_pct = (atr / price * 100.0) if price else 0.0

    score = 50.0

    if e20 and price > e20:
        score += 8
    elif e20:
        score -= 8

    if e50 and price > e50:
        score += 10
    elif e50:
        score -= 10

    if e200 and price > e200:
        score += 15
    elif e200:
        score -= 15

    if e20 and e50:
        if e20 > e50:
            score += 8
        else:
            score -= 8

    if r >= 55 and r < 70:
        score += 10
    elif r <= 45 and r > 30:
        score -= 10
    elif r >= 70:
        score -= 5
    elif r <= 30:
        score += 5

    # زخم آخر شمعتين + تأكيد حجم.
    if len(closes) >= 4:
        momentum = pct(closes[-1], closes[-4])
        if momentum > 0.35:
            score += 5
        elif momentum < -0.35:
            score -= 5

    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        if avg_vol > 0:
            vr = volumes[-1] / avg_vol
            if vr >= 1.20:
                score += 5 if closes[-1] >= closes[-2] else -5

    score = int(max(0, min(100, round(score))))

    # لا نعرض الصفقة إلا عند وجود توافق فني واضح.
    if score >= long_threshold:
        direction = "LONG"
        signal = "شراء قوي" if score >= 82 else "شراء"
    elif score <= short_threshold:
        direction = "SHORT"
        signal = "بيع قوي" if score <= 18 else "بيع"
    else:
        direction = "WAIT"
        signal = "حيادي"

    # المخاطرة مبنية على ATR، والهدف 2R.
    risk = max(atr, price * 0.005)
    if direction == "LONG":
        sl = price - risk
        tp1 = price + risk
        tp2 = price + (risk * 2.0)
        tp3 = price + (risk * 3.0)
    elif direction == "SHORT":
        sl = price + risk
        tp1 = price - risk
        tp2 = price - (risk * 2.0)
        tp3 = price - (risk * 3.0)
    else:
        sl = price - risk
        tp1 = price + risk
        tp2 = price + (risk * 2.0)
        tp3 = price + (risk * 3.0)

    return {
        "signal": signal,
        "direction": direction,
        "trade": direction in ("LONG", "SHORT"),
        "score": score,
        "score10": round(score / 10, 1),
        "confidence": score if direction == "LONG" else (100 - score if direction == "SHORT" else max(score, 100-score)),
        "price": fmt_price(price),
        "rsi": round(r, 2),
        "atr": fmt_price(atr),
        "atrPct": round(atr_pct, 3),
        "ema20": fmt_price(e20) if e20 else None,
        "ema50": fmt_price(e50) if e50 else None,
        "ema200": fmt_price(e200) if e200 else None,
        "entry": fmt_price(price),
        "tp1": fmt_price(tp1),
        "tp2": fmt_price(tp2),
        "tp3": fmt_price(tp3),
        "sl": fmt_price(sl)
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


def spot_scan(interval="15m", long_threshold=50, short_threshold=50):

    key = (
        "spot_scan_v3_"
        + interval
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    symbols = spot_symbols()

    tickers = okx_tickers(
        "SPOT"
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
        key=lambda x:
        x.get(
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
                bar=interval,
                limit=220
            )

            analysis = analyze_candles(
                candles,
                long_threshold=long_threshold,
                short_threshold=short_threshold
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                **analysis,

                "symbol":
                    item["symbol"],

                "name":
                    item["name"],

                "change":
                    round(change, 2),

                "change24h":
                    round(
                        pct(
                            item.get(
                                "price",
                                0
                            ),
                            candles[-1]["c"]
                        ),
                        2
                    ),

                "volume":
                    item.get(
                        "volume",
                        0
                    ),

                "volume24h":
                    item.get(
                        "quoteVolume",
                        0
                    ),

                "interval":
                    interval,

                "market":
                    "spot",

                "updatedAt":
                    now_utc().isoformat()
            }

        except Exception:

            return None

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                x
            )
            for x in candidates
        ]

        for f in as_completed(
            futures
        ):

            try:

                item = f.result()

                if item:
                    results.append(item)

            except Exception:
                pass

    results.sort(
        key=lambda x:
        x.get(
            "score",
            0
        ),
        reverse=True
    )

    data = {

        "ok": True,

        "market":
            "spot",

        "interval":
            interval,

        "universeCount":
            len(symbols),

        "scannedCount":
            len(candidates),

        "count":
            len(results),

        "results":
            results
    }

    cache_set(
        key,
        data
    )

    return data


@app.get("/api/spot/scan")
@app.get("/api/spot/signals")
@app.get("/api/binance/scan")
def spot_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    allowed = {
        "5m",
        "15m",
        "1H",
        "4H",
        "1D"
    }

    if interval not in allowed:

        interval = "15m"

    try:

        return jsonify(
            spot_scan(
                interval,
                long_threshold=50,
                short_threshold=50
            )
        )

    except Exception as e:

        print(
            "SPOT ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e),
            "results": []
        }), 500


@app.get("/api/spot/analysis")
@app.get("/api/binance/analysis")
def spot_analysis():

    symbol = request.args.get(
        "symbol",
        ""
    ).strip().upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if not symbol:

        return jsonify({
            "ok": False,
            "message": "حدد العملة"
        }), 400

    try:

        if "-" not in symbol:

            if symbol.endswith("USDT"):

                symbol = (
                    symbol[:-4]
                    + "-USDT"
                )

        candles = okx_candles(
            symbol,
            interval,
            220
        )

        result = analyze_candles(
            candles
        )

        result["symbol"] = symbol
        result["interval"] = interval
        result["change"] = round(
            pct(
                candles[-1]["c"],
                candles[-2]["c"]
            ),
            2
        )
        result["candles"] = candles[-100:]

        return jsonify({
            "ok": True,
            "result": result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


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


def futures_scan(interval="15m", long_threshold=50, short_threshold=50):

    key = (
        "futures_scan_v3_"
        + interval
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    symbols = futures_symbols()

    tickers = okx_tickers(
        "SWAP"
    )

    volumes = {}

    for t in tickers:

        inst = t.get(
            "instId"
        )

        if inst:

            volumes[inst] = safe_float(
                t.get(
                    "volCcy24h"
                )
            )

    candidates = []

    for x in symbols:

        candidates.append({
            **x,
            "volume24h":
                volumes.get(
                    x["symbol"],
                    0
                )
        })

    candidates.sort(
        key=lambda x:
        x["volume24h"],
        reverse=True
    )

    candidates = candidates[:80]

    results = []

    def worker(item):

        try:

            candles = okx_candles(
                item["symbol"],
                bar=interval,
                limit=220
            )

            analysis = analyze_candles(
                candles,
                long_threshold=long_threshold,
                short_threshold=short_threshold
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                **analysis,

                "symbol":
                    item["symbol"],

                "name":
                    item["name"],

                "change":
                    round(change, 2),

                "change24h":
                    round(change, 2),

                "volume": 0,

                "volume24h":
                    item["volume24h"],

                "interval":
                    interval,

                "market":
                    "futures",

                "updatedAt":
                    now_utc().isoformat()
            }

        except Exception:

            return None

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                x
            )
            for x in candidates
        ]

        for f in as_completed(
            futures
        ):

            try:

                row = f.result()

                if row:
                    results.append(row)

            except Exception:
                pass

    results.sort(
        key=lambda x:
        x.get(
            "score",
            0
        ),
        reverse=True
    )

    data = {

        "ok": True,

        "market":
            "futures",

        "interval":
            interval,

        "universeCount":
            len(symbols),

        "scannedCount":
            len(candidates),

        "count":
            len(results),

        "results":
            results
    }

    cache_set(
        key,
        data
    )

    return data


# =========================================================
# FUTURES API
# =========================================================

@app.get("/api/futures")
@app.get("/api/futures/signals")
@app.get("/api/futures/scan")
def futures_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    allowed = {
        "5m",
        "15m",
        "1H",
        "4H",
        "1D"
    }

    if interval not in allowed:

        interval = "15m"

    try:

        return jsonify(
            futures_scan(
                interval,
                long_threshold=50,
                short_threshold=50
            )
        )

    except Exception as e:

        print(
            "FUTURES ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e),
            "results": []
        }), 500


# =========================================================
# FUTURES ANALYSIS
# =========================================================

@app.get("/api/futures/analysis")
def futures_analysis():

    symbol = request.args.get(
        "symbol",
        ""
    ).strip().upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if not symbol:

        return jsonify({
            "ok": False,
            "message": "حدد العملة"
        }), 400

    try:

        if "-USDT-SWAP" not in symbol:

            if symbol.endswith("USDT"):

                symbol = (
                    symbol[:-4]
                    + "-USDT-SWAP"
                )

        candles = okx_candles(
            symbol,
            interval,
            220
        )

        result = analyze_candles(
            candles
        )

        result["symbol"] = symbol
        result["interval"] = interval
        result["market"] = "futures"

        return jsonify({
            "ok": True,
            "result": result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# YAHOO
# =========================================================

def yahoo_interval(interval):

    return {

        "5m": "5m",
        "15m": "15m",
        "1H": "60m",
        "1h": "60m",
        "4H": "1h",
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
        "4H": "60d",
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

    last_error = None

    for attempt in range(3):

        try:

            r = HTTP.get(
                url,
                params={
                    "interval":
                        yahoo_interval(interval),

                    "range":
                        yahoo_range(interval),

                    "events":
                        "history"
                },
                timeout=15
            )

            r.raise_for_status()

            data = r.json()

            break

        except Exception as e:

            last_error = e

            if attempt < 2:
                time.sleep(0.35 * (attempt + 1))

    else:

        raise last_error

    result = (
        data
        .get("chart", {})
        .get("result")
    )

    if not result:

        raise RuntimeError(
            "Yahoo no data"
        )

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

            if any(
                x is None
                for x in (
                    o,
                    h,
                    l,
                    c
                )
            ):
                continue

            candles.append({

                "t":
                    int(ts) * 1000,

                "o":
                    safe_float(o),

                "h":
                    safe_float(h),

                "l":
                    safe_float(l),

                "c":
                    safe_float(c),

                "v":
                    safe_float(v)

            })

        except Exception:
            continue

    if len(candles) < 30:

        raise RuntimeError(
            "Yahoo بيانات غير كافية"
        )

    return candles


def yahoo_scan(
    symbols,
    interval,
    long_threshold=70,
    short_threshold=30
):

    results = []

    def worker(item):

        try:

            candles = yahoo_klines(
                item["symbol"],
                interval
            )

            analysis = analyze_candles(
                candles,
                long_threshold=long_threshold,
                short_threshold=short_threshold
            )

            change = pct(
                candles[-1]["c"],
                candles[-2]["c"]
            )

            return {
                **analysis,

                "symbol":
                    item["symbol"],

                "name":
                    item["name"],

                "change":
                    round(change, 2),

                "change24h":
                    round(change, 2),

                "volume":
                    candles[-1]["v"],

                "volume24h":
                    0,

                "interval":
                    interval,

                "updatedAt":
                    now_utc().isoformat()
            }

        except Exception:

            return None

    unique_symbols = {}
    for item in symbols:
        unique_symbols[item["symbol"]] = item

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:

        futures = [
            executor.submit(
                worker,
                x
            )
            for x in unique_symbols.values()
        ]

        for f in as_completed(
            futures
        ):

            try:

                row = f.result()

                if row:
                    results.append(row)

            except Exception:
                pass

    results.sort(
        key=lambda x:
        x.get(
            "score",
            0
        ),
        reverse=True
    )

    return results


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
    ("1150.SR", "الإنماء"),
    ("1060.SR", "بنك البلاد"),
    ("1010.SR", "بنك الرياض"),
    ("1050.SR", "BSF"),
    ("1080.SR", "العربي الوطني"),
    ("1030.SR", "الاستثمار"),
    ("1111.SR", "مجموعة تداول"),
    ("2020.SR", "سابك للمغذيات"),
    ("2030.SR", "المتقدمة"),
    ("2040.SR", "الخزف السعودي"),
    ("2050.SR", "التصنيع"),
    ("2060.SR", "التصنيع"),
    ("2090.SR", "جبسكو"),
    ("2110.SR", "الكابلات"),
    ("2170.SR", "اللجين"),
    ("2180.SR", "فيبكو"),
    ("2200.SR", "أنابيب"),
    ("2210.SR", "نماء"),
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
    ("2380.SR", "بترو رابغ"),

    ("3001.SR", "أسمنت العربية"),
    ("3002.SR", "أسمنت نجران"),
    ("3003.SR", "أسمنت المدينة"),
    ("3004.SR", "أسمنت الشمالية"),
    ("3005.SR", "أسمنت أم القرى"),
    ("3007.SR", "أسمنت الجنوب"),
    ("3008.SR", "أسمنت القصيم"),
    ("3010.SR", "أسمنت العربية"),
    ("3020.SR", "أسمنت اليمامة"),
    ("3050.SR", "أسمنت ينبع"),

    ("4001.SR", "أسواق العثيم"),
    ("4002.SR", "المواساة"),
    ("4003.SR", "إكسترا"),
    ("4004.SR", "دله الصحية"),
    ("4005.SR", "رعاية"),
    ("4007.SR", "الحمادي"),
    ("4008.SR", "ساكو"),
    ("4009.SR", "السعودي الألماني"),
    ("4010.SR", "دار الأركان"),
    ("4013.SR", "سليمان الحبيب"),
    ("4020.SR", "العقارية"),
    ("4030.SR", "البحري"),
    ("4031.SR", "الخدمات الأرضية"),
    ("4040.SR", "جرير"),
    ("4071.SR", "العربية للتعهدات"),
    ("4090.SR", "طيبة"),
    ("4100.SR", "مكة"),
    ("4110.SR", "دور"),
    ("4150.SR", "التعمير"),
    ("4180.SR", "مجموعة الحكير"),
    ("4190.SR", "جرير"),
    ("4200.SR", "الدريس"),
    ("4210.SR", "الأبحاث والإعلام"),
    ("4220.SR", "إعمار"),
    ("4230.SR", "البحر الأحمر"),
    ("4260.SR", "بدجت"),
    ("4280.SR", "المملكة"),
    ("4300.SR", "دار الأركان"),
    ("4310.SR", "مدينة المعرفة"),
    ("4320.SR", "الأندلس"),
    ("4330.SR", "المراكز العربية"),
    ("5110.SR", "كهرباء السعودية"),

    ("6010.SR", "نادك"),
    ("6020.SR", "جاكو"),
    ("6040.SR", "تبوك الزراعية"),
    ("6050.SR", "الأسماك"),
    ("6060.SR", "الشرقية للتنمية"),
    ("6070.SR", "الجوف"),
    ("6090.SR", "جازادكو"),

    ("7020.SR", "اتحاد اتصالات"),
    ("7030.SR", "زين السعودية"),
    ("7040.SR", "عذيب"),

    ("7200.SR", "الدوائية"),
    ("7201.SR", "بحر العرب"),
    ("7202.SR", "عربي قابضة"),
    ("7203.SR", "عذيب"),
    ("7204.SR", "تكامل"),

    ("8010.SR", "التعاونية"),
    ("8012.SR", "جزيرة تكافل"),
    ("8020.SR", "ملاذ"),
    ("8030.SR", "سلامة"),
    ("8040.SR", "ولاء"),
    ("8060.SR", "الدرع العربي"),
    ("8070.SR", "الشرقية للتأمين"),
    ("8100.SR", "سايكو"),
    ("8120.SR", "أمانة"),
    ("8150.SR", "أسيج"),
    ("8160.SR", "التأمين العربية"),
    ("8170.SR", "اتحاد الخليج"),
    ("8180.SR", "الصقر"),
    ("8200.SR", "الإعادة السعودية"),
    ("8210.SR", "بروج"),
    ("8230.SR", "تكافل الراجحي"),
    ("8240.SR", "تشب"),
    ("8250.SR", "جي آي جي"),
    ("8260.SR", "الخليجية العامة"),
    ("8280.SR", "العالمية"),
    ("8300.SR", "الوطنية"),
    ("8310.SR", "أمانة"),
    ("8311.SR", "عناية"),
    ("8312.SR", "عناية"),
    ("9400.SR", "الخدمات")
]


@app.get("/api/saudi/scan")
@app.get("/api/saudi/signals")
def saudi_api():

    interval = request.args.get(
        "interval",
        "15m"
    ).strip()

    if interval not in {
        "15m",
        "1H",
        "1D"
    }:
        interval = "15m"

    try:
        limit = int(
            request.args.get(
                "limit",
                "40"
            )
        )
    except Exception:
        limit = 40

    limit = max(
        5,
        min(limit, 60)
    )

    key = (
        "saudi_trades_v3_"
        + interval
        + "_"
        + str(limit)
    )

    cached = cache_get(key)

    if cached is not None:
        return jsonify(cached)

    symbols = [
        {
            "symbol": s,
            "name": n
        }
        for s, n in SAUDI_SYMBOLS
    ]

    # نستخدم عتبة 55/45 لاختيار BUY/SELL حقيقي من النموذج، ثم نعرض أقوى الإشارات فقط.
    # مصدر احتياطي تلقائي للسوق السعودي:
    # إذا لم تُرجع Yahoo بيانات 15m ننتقل إلى 1H ثم 1D.
    scan_interval = interval

    all_results = yahoo_scan(
        symbols,
        scan_interval,
        long_threshold=50,
        short_threshold=50
    )

    if not all_results and interval == "15m":
        scan_interval = "1H"
        all_results = yahoo_scan(
            symbols,
            scan_interval,
            long_threshold=50,
            short_threshold=50
        )

    if not all_results and interval in {"15m", "1H"}:
        scan_interval = "1D"
        all_results = yahoo_scan(
            symbols,
            scan_interval,
            long_threshold=50,
            short_threshold=50
        )

    results = [
        row for row in all_results
        if row.get("trade") is True
        and row.get("direction") in {"LONG", "SHORT"}
    ]

    results.sort(
        key=lambda row: abs(row.get("score", 50) - 50),
        reverse=True
    )

    results = results[:limit]

    data = {
        "ok": True,
        "market": "saudi",
        "interval": interval,
        "dataInterval": scan_interval,
        "universeCount": len(symbols),
        "scannedCount": len(symbols),
        "count": len(results),
        "results": results,
        "message": (
            "أفضل صفقات شراء/بيع حسب أقوى إشارة فنية"
            if results else
            "تعذر الحصول على بيانات الأسهم السعودية حالياً"
        )
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

    key = "us_symbol_directory"

    cached = cache_get(key)

    if cached is not None:
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

                if len(parts) < 4:
                    continue

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

                if row.get(
                    "ETF"
                ) == "Y":
                    continue

                symbol = (
                    row.get("Symbol")
                    or row.get("ACT Symbol")
                    or ""
                ).strip()

                name = (
                    row.get("Security Name")
                    or ""
                ).strip()

                if not symbol:
                    continue

                if not re.match(
                    r"^[A-Za-z0-9.\-]+$",
                    symbol
                ):
                    continue

                upper_name = name.upper()

                if any(
                    x in upper_name
                    for x in bad_words
                ):
                    continue

                yahoo_symbol = symbol.replace(
                    ".",
                    "-"
                )

                result.append({
                    "symbol": yahoo_symbol,
                    "name": name
                })

        except Exception as e:

            print(
                "US symbols error:",
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
        key=lambda x:
        x["symbol"]
    )

    cache_set(
        key,
        result
    )

    return result


@app.get("/api/usmarket/signals")
@app.get("/api/usmarket/scan")
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

    # Keep the live scan responsive and reduce Yahoo rate-limit errors.
    symbols = symbols[:150]

    key = (
        "us_"
        + interval
    )

    cached = cache_get(key)

    if cached is not None:
        return jsonify(cached)

    results = yahoo_scan(
        symbols,
        interval
    )

    data = {

        "ok": True,

        "market":
            "usmarket",

        "interval":
            interval,

        "universeCount":
            len(symbols),

        "scannedCount":
            len(symbols),

        "count":
            len(results),

        "results":
            results
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
@app.get("/api/forex/scan")
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
        "forex_v3_"
        + interval
    )

    cached = cache_get(key)

    if cached is not None:
        return jsonify(cached)

    symbols = [
        {
            "symbol": s,
            "name": n
        }
        for s, n in FOREX_SYMBOLS
    ]

    # نستخدم عتبة 55/45 لاختيار BUY/SELL حقيقي من النموذج.
    all_results = yahoo_scan(
        symbols,
        interval,
        long_threshold=50,
        short_threshold=50
    )

    results = [
        row for row in all_results
        if row.get("trade") is True
        and row.get("direction") in {"LONG", "SHORT"}
    ]

    results.sort(
        key=lambda row: abs(row.get("score", 50) - 50),
        reverse=True
    )

    results = results[:10]

    data = {
        "ok": True,
        "market": "forex",
        "interval": interval,
        "universeCount": len(symbols),
        "scannedCount": len(symbols),
        "count": len(results),
        "results": results,
        "message": (
            "أفضل 10 صفقات BUY/SELL حسب أقوى إشارة فنية"
            if results else
            "تعذر الحصول على بيانات السوق حالياً"
        )
    }

    cache_set(
        key,
        data
    )

    return jsonify(data)


# =========================================================
# RECENT
# =========================================================

@app.get("/api/recent")
@app.get("/api/spot/recent")
def recent_api():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        data = spot_scan(
            interval
        )

        results = data.get(
            "results",
            []
        )

        recent = [
            x for x in results
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

            "market":
                "spot",

            "count":
                len(recent[:30]),

            "results":
                recent[:30]

        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e),
            "results": []
        }), 500


# =========================================================
# NEWS
# =========================================================

NEWS_URLS = [

    "https://feeds.feedburner.com/Argaam",

    "https://www.argaam.com/ar/feed"

]


@app.get("/api/news")
@app.get("/api/news/latest")
def news():

    items = []

    # الأخبار التي ينشرها الأدمن تظهر أولاً.
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, content, url, source, created_at
            FROM news_items
            ORDER BY id DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        conn.close()

        local_items = [{
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "url": row[3] or "#",
            "source": row[4] or "مضارب أبو سعود",
            "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5]
        } for row in rows]
    except Exception as e:
        print("LOCAL NEWS ERROR:", e)
        local_items = []

    items = list(local_items)

    for url in NEWS_URLS:

        try:

            r = HTTP.get(
                url,
                timeout=8
            )

            # نقرأ الأخبار العربية فقط قدر الإمكان، ونحوّل العناوين
            # الإنجليزية المعروفة إلى عناوين عربية قبل عرضها.
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

                # إزالة وسوم RSS والرموز غير المرغوبة.
                title = html.unescape(title)
                title = re.sub(r"^\s*(Reuters|Bloomberg|CNBC|Yahoo Finance|MarketWatch)\s*[-:|]\s*", "", title, flags=re.I)

                if not title:
                    continue

                # لا نعرض الخبر الإنجليزي الخام للمستخدم.
                # إذا كان المصدر عربيًا يبقى العنوان كما هو.
                if not re.search(r"[\u0600-\u06FF]", title):
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


@app.post("/api/admin/news")
def admin_create_news():
    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    url = str(data.get("url", "")).strip()
    source = str(data.get("source", "مضارب أبو سعود")).strip()

    if len(title) < 2 or len(content) < 2:
        return jsonify({"ok": False, "message": "العنوان والمحتوى مطلوبان"}), 400

    try:
        conn = db()
        cur = conn.cursor()
        if using_postgres():
            cur.execute(
                "INSERT INTO news_items (title, content, url, source) VALUES (%s,%s,%s,%s)",
                (title, content, url or None, source or "مضارب أبو سعود")
            )
        else:
            cur.execute(
                "INSERT INTO news_items (title, content, url, source) VALUES (?,?,?,?)",
                (title, content, url or None, source or "مضارب أبو سعود")
            )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "تم نشر الخبر"})
    except Exception as e:
        print("CREATE NEWS ERROR:", e)
        return jsonify({"ok": False, "message": "تعذر نشر الخبر"}), 500


@app.get("/api/admin/news")
def admin_list_news():
    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, content, url, source, created_at
            FROM news_items
            ORDER BY id DESC
            LIMIT 200
        """)
        rows = cur.fetchall()
        conn.close()
        return jsonify({"ok": True, "results": [{
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "url": row[3],
            "source": row[4],
            "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5]
        } for row in rows]})
    except Exception as e:
        return jsonify({"ok": False, "message": "تعذر تحميل الأخبار"}), 500


@app.delete("/api/admin/news/<int:news_id>")
def admin_delete_news(news_id):
    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403
    try:
        conn = db()
        cur = conn.cursor()
        if using_postgres():
            cur.execute("DELETE FROM news_items WHERE id=%s", (news_id,))
        else:
            cur.execute("DELETE FROM news_items WHERE id=?", (news_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "تم حذف الخبر"})
    except Exception as e:
        return jsonify({"ok": False, "message": "تعذر حذف الخبر"}), 500


# =========================================================
# PLANS
# =========================================================

@app.get("/api/subscription/plans")
def subscription_plans_alias():

    return plans()


@app.get("/api/plans")
def plans():

    return jsonify({

        "ok": True,

        "plans":
            PLANS,

        "paymentAddress":
            PAYMENT_ADDRESS

    })


# =========================================================
# PAYMENT
# =========================================================

@app.post("/api/payment")
@app.post("/api/subscription/payment")
def payment():

    if not session.get("user"):

        return jsonify({
            "ok": False,
            "message": "سجل دخول أولاً"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    plan = data.get("plan") or data.get("plan_id")

    txid = str(
        data.get(
            "txid",
            ""
        )
    ).strip()

    if plan not in PLANS:

        return jsonify({
            "ok": False,
            "message": "الباقة غير صحيحة"
        }), 400

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

            cur.execute("""
                INSERT INTO payment_requests
                (username,plan,txid)
                VALUES(%s,%s,%s)
            """, (
                session["user"],
                plan,
                txid
            ))

        else:

            cur.execute("""
                INSERT INTO payment_requests
                (username,plan,txid)
                VALUES(?,?,?)
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

        return jsonify({
            "ok": False,
            "message": "تعذر إرسال طلب الدفع"
        }), 500


# =========================================================
# PAYMENT HISTORY
# =========================================================

@app.get("/api/payment/history")
@app.get("/api/subscription/history")
def payment_history():

    username = session.get(
        "user"
    )

    if not username:

        return jsonify({
            "ok": False,
            "message": "سجل دخول أولاً"
        }), 401

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

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
                username,
            ))

        else:

            cur.execute("""
                SELECT
                    id,
                    plan,
                    txid,
                    status,
                    created_at
                FROM payment_requests
                WHERE username=?
                ORDER BY id DESC
                LIMIT 50
            """, (
                username,
            ))

        rows = cur.fetchall()

        conn.close()

        results = []

        for row in rows:

            results.append({

                "id":
                    row[0],

                "plan":
                    row[1],

                "txid":
                    row[2],

                "status":
                    row[3],

                "createdAt":
                    (
                        row[4].isoformat()
                        if hasattr(
                            row[4],
                            "isoformat"
                        )
                        else row[4]
                    )

            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e),
            "results": []
        }), 500


# =========================================================
# ADMIN STATS
# =========================================================

@app.get("/api/admin/stats")
def admin_stats():

    if not require_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 403

    try:

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM users"
        )

        users = cur.fetchone()[0]

        if using_postgres():

            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until > NOW()
            """)

        else:

            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until > datetime('now')
            """)

        active = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM payment_requests
            WHERE status='pending'
        """)

        pending = cur.fetchone()[0]

        cur.execute("""
            SELECT plan
            FROM payment_requests
            WHERE status='approved'
        """)

        rows = cur.fetchall()

        revenue = 0

        for row in rows:

            plan = row[0]

            if plan in PLANS:

                revenue += PLANS[
                    plan
                ]["amount"]

        conn.close()

        return jsonify({

            "ok": True,

            "users":
                users,

            "active":
                active,

            "pending":
                pending,

            "revenue":
                round(
                    revenue,
                    2
                )

        })

    except Exception as e:

        print(
            "STATS ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# ADMIN PAYMENTS
# =========================================================

@app.get("/api/admin/payments")
def admin_payments():

    if not require_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 403

    try:

        conn = db()
        cur = conn.cursor()

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

                "id":
                    row[0],

                "username":
                    row[1],

                "plan":
                    row[2],

                "txid":
                    row[3],

                "status":
                    row[4],

                "createdAt":
                    (
                        row[5].isoformat()
                        if hasattr(
                            row[5],
                            "isoformat"
                        )
                        else row[5]
                    )

            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# ADMIN REVIEW PAYMENT
# =========================================================

@app.post(
    "/api/admin/payments/<int:payment_id>/review"
)
def review_payment(payment_id):

    if not require_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    action = str(
        data.get(
            "action",
            ""
        )
    ).lower()

    if not action:
        if request.path.endswith("/approve"):
            action = "approve"
        elif request.path.endswith("/reject"):
            action = "reject"

    if action not in {
        "approve",
        "reject"
    }:

        return jsonify({
            "ok": False,
            "message": "الإجراء غير صحيح"
        }), 400

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

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

        else:

            cur.execute("""
                SELECT
                    username,
                    plan,
                    status
                FROM payment_requests
                WHERE id=?
            """, (
                payment_id,
            ))

        row = cur.fetchone()

        if not row:

            conn.close()

            return jsonify({
                "ok": False,
                "message": "الطلب غير موجود"
            }), 404

        username = row[0]
        plan = row[1]

        if action == "reject":

            if using_postgres():

                cur.execute("""
                    UPDATE payment_requests
                    SET status='rejected'
                    WHERE id=%s
                """, (
                    payment_id,
                ))

            else:

                cur.execute("""
                    UPDATE payment_requests
                    SET status='rejected'
                    WHERE id=?
                """, (
                    payment_id,
                ))

        else:

            if plan not in PLANS:

                conn.close()

                return jsonify({
                    "ok": False,
                    "message": "الباقة غير صحيحة"
                }), 400

            if using_postgres():

                cur.execute("""
                    SELECT subscription_until
                    FROM users
                    WHERE username=%s
                """, (
                    username,
                ))

            else:

                cur.execute("""
                    SELECT subscription_until
                    FROM users
                    WHERE username=?
                """, (
                    username,
                ))

            user = cur.fetchone()

            current = (
                parse_date(user[0])
                if user and user[0]
                else now_utc()
            )

            if not current or current < now_utc():

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

            if using_postgres():

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
                    UPDATE users
                    SET subscription_until=?
                    WHERE username=?
                """, (
                    until.isoformat(),
                    username
                ))

                cur.execute("""
                    UPDATE payment_requests
                    SET status='approved'
                    WHERE id=?
                """, (
                    payment_id,
                ))

        conn.commit()
        conn.close()

        return jsonify({
            "ok": True,
            "message": "تم تحديث الطلب"
        })

    except Exception as e:

        print(
            "REVIEW ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# ADMIN COMPATIBILITY ROUTES
# =========================================================

@app.get("/api/admin/dashboard")
def admin_dashboard_compat():

    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403

    try:
        conn = db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        users_count = cur.fetchone()[0]

        if using_postgres():
            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until > NOW()
            """)
        else:
            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until > ?
            """, (now_utc().isoformat(),))
        active_count = cur.fetchone()[0]

        cur.execute("""
            SELECT id, username, plan, txid, status, created_at
            FROM payment_requests
            ORDER BY id DESC
            LIMIT 200
        """)
        payment_rows = cur.fetchall()

        cur.execute("""
            SELECT id, username, email, name, is_admin,
                   subscription_until, created_at
            FROM users
            ORDER BY id DESC
            LIMIT 500
        """)
        user_rows = cur.fetchall()

        conn.close()

        payments = [{
            "id": r[0],
            "username": r[1],
            "plan": r[2],
            "txid": r[3],
            "status": r[4],
            "createdAt": r[5].isoformat() if hasattr(r[5], "isoformat") else r[5]
        } for r in payment_rows]

        users_list = [{
            "id": r[0],
            "username": r[1],
            "email": r[2],
            "name": r[3],
            "admin": bool(r[4]),
            "subscriptionUntil": r[5].isoformat() if hasattr(r[5], "isoformat") else r[5],
            "createdAt": r[6].isoformat() if hasattr(r[6], "isoformat") else r[6]
        } for r in user_rows]

        pending = sum(1 for r in payment_rows if r[4] == "pending")
        revenue = sum(PLANS.get(r[2], {}).get("amount", 0) for r in payment_rows if r[4] == "approved")

        return jsonify({
            "ok": True,
            "users": users_count,
            "active": active_count,
            "pending": pending,
            "revenue": round(revenue, 2),
            "payments": payments,
            "users_list": users_list
        })

    except Exception as e:
        print("ADMIN DASHBOARD ERROR:", e)
        return jsonify({"ok": False, "message": "تعذر تحميل لوحة الإدارة"}), 500


@app.post("/api/admin/payments/approve")
@app.post("/api/admin/payments/reject")
def admin_payment_compat():
    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403

    payment_id = (request.get_json(silent=True) or {}).get("id")
    try:
        payment_id = int(payment_id)
    except Exception:
        return jsonify({"ok": False, "message": "رقم الطلب غير صحيح"}), 400

    action = "approve" if request.path.endswith("/approve") else "reject"

    # Reuse the same review logic through a direct internal call.
    return review_payment(payment_id)


@app.post("/api/admin/users/subscription")
def admin_subscription_compat():
    if not require_admin():
        return jsonify({"ok": False, "message": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get("id"))
        days = int(data.get("days", 0))
    except Exception:
        return jsonify({"ok": False, "message": "بيانات الاشتراك غير صحيحة"}), 400

    try:
        conn = db()
        cur = conn.cursor()

        current_sql = "SELECT subscription_until FROM users WHERE id=%s" if using_postgres() else "SELECT subscription_until FROM users WHERE id=?"
        cur.execute(current_sql, (user_id,))
        row = cur.fetchone()

        if not row:
            conn.close()
            return jsonify({"ok": False, "message": "المستخدم غير موجود"}), 404

        if data.get("cancel") or days <= 0:
            until = None
        else:
            current = parse_date(row[0]) if row[0] else None
            base = current if current and current > now_utc() else now_utc()
            until = base + timedelta(days=days)

        update_sql = "UPDATE users SET subscription_until=%s WHERE id=%s" if using_postgres() else "UPDATE users SET subscription_until=? WHERE id=?"
        cur.execute(update_sql, (until, user_id) if using_postgres() else ((until.isoformat() if until else None), user_id))

        conn.commit()
        conn.close()

        return jsonify({"ok": True, "message": "تم تحديث الاشتراك"})
    except Exception as e:
        print("ADMIN SUBSCRIPTION ERROR:", e)
        return jsonify({"ok": False, "message": "تعذر تحديث الاشتراك"}), 500


# =========================================================
# ADMIN USERS
# =========================================================

@app.get("/api/admin/users")
def admin_users():

    if not require_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 403

    try:

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                username,
                email,
                name,
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

                "id":
                    row[0],

                "username":
                    row[1],

                "email":
                    row[2],

                "name":
                    row[3],

                "admin":
                    bool(row[4]),

                "subscriptionUntil":
                    (
                        row[5].isoformat()
                        if hasattr(
                            row[5],
                            "isoformat"
                        )
                        else row[5]
                    ),

                "createdAt":
                    (
                        row[6].isoformat()
                        if hasattr(
                            row[6],
                            "isoformat"
                        )
                        else row[6]
                    )

            })

        return jsonify({
            "ok": True,
            "results": results
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# ADMIN CHANGE PLAN
# =========================================================

@app.post(
    "/api/admin/users/<int:user_id>/plan"
)
def admin_change_plan(user_id):

    if not require_admin():

        return jsonify({
            "ok": False,
            "message": "غير مصرح"
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    plan = data.get(
        "plan"
    )

    if plan not in PLANS and plan != "free":

        return jsonify({
            "ok": False,
            "message": "الباقة غير صحيحة"
        }), 400

    try:

        conn = db()
        cur = conn.cursor()

        if plan == "free":

            if using_postgres():

                cur.execute("""
                    UPDATE users
                    SET subscription_until=NULL
                    WHERE id=%s
                """, (
                    user_id,
                ))

            else:

                cur.execute("""
                    UPDATE users
                    SET subscription_until=NULL
                    WHERE id=?
                """, (
                    user_id,
                ))

        else:

            until = (
                now_utc()
                +
                timedelta(
                    days=PLANS[
                        plan
                    ]["days"]
                )
            )

            if using_postgres():

                cur.execute("""
                    UPDATE users
                    SET subscription_until=%s
                    WHERE id=%s
                """, (
                    until,
                    user_id
                ))

            else:

                cur.execute("""
                    UPDATE users
                    SET subscription_until=?
                    WHERE id=?
                """, (
                    until.isoformat(),
                    user_id
                ))

        affected = cur.rowcount

        conn.commit()
        conn.close()

        if not affected:

            return jsonify({
                "ok": False,
                "message": "المستخدم غير موجود"
            }), 404

        return jsonify({
            "ok": True,
            "message": "تم تحديث الاشتراك"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# SUBSCRIPTION
# =========================================================

@app.get("/api/subscription")
@app.get("/api/auth/subscription")
def subscription():

    username = session.get(
        "user"
    )

    if not username:

        return jsonify({
            "ok": True,
            "loggedIn": False
        })

    try:

        conn = db()
        cur = conn.cursor()

        if using_postgres():

            cur.execute("""
                SELECT subscription_until
                FROM users
                WHERE username=%s
            """, (
                username,
            ))

        else:

            cur.execute("""
                SELECT subscription_until
                FROM users
                WHERE username=?
            """, (
                username,
            ))

        row = cur.fetchone()

        conn.close()

        until = (
            row[0]
            if row
            else None
        )

        active = False

        if until:

            dt = parse_date(
                until
            )

            if dt:
                active = (
                    dt > now_utc()
                )

        return jsonify({

            "ok": True,

            "loggedIn": True,

            "active": active,

            "subscriptionUntil":
                (
                    until.isoformat()
                    if hasattr(
                        until,
                        "isoformat"
                    )
                    else until
                )

        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================================================
# API ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "ok": False,
            "message": "المسار غير موجود",
            "path": request.path
        }), 404
    return error


@app.errorhandler(500)
def handle_500(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "ok": False,
            "message": "خطأ داخلي في الخادم"
        }), 500
    return error


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
@app.get("/healthz")
@app.get("/health-check")
@app.get("/api/health")
def health():

    return jsonify({

        "ok": True,

        "service":
            "mudarib-abo-saud",

        "database":
            (
                "PostgreSQL"
                if using_postgres()
                else "SQLite"
            ),

        "spot":
            "OKX",

        "futures":
            "OKX",

        "saudi":
            "Yahoo Finance",

        "usmarket":
            "Yahoo Finance + Nasdaq Trader",

        "forex":
            "Yahoo Finance",

        "time":
            now_utc().isoformat()

    }), 200


# =========================================================
# OLD BINANCE COMPATIBILITY
# =========================================================

@app.get("/api/binance/test")
def old_binance_test():

    return jsonify({

        "ok": False,

        "message":
            "تم تحويل مصدر العملات إلى OKX"

    })


# =========================================================
# HEALTH
# =========================================================

@app.get("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud",
        "time": now_utc().isoformat()
    })


# =========================================================
# FRONTEND / PAGE ROUTES
# =========================================================

STATIC_DIR = os.path.abspath(
    app.static_folder
)

TEMPLATES_DIR = os.path.abspath(
    app.template_folder
)


def serve_page(filename):

    static_path = os.path.join(
        STATIC_DIR,
        filename
    )

    if os.path.isfile(
        static_path
    ):

        return send_from_directory(
            STATIC_DIR,
            filename
        )

    template_path = os.path.join(
        TEMPLATES_DIR,
        filename
    )

    if os.path.isfile(
        template_path
    ):

        return send_from_directory(
            TEMPLATES_DIR,
            filename
        )

    return None


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    page = serve_page(
        "index.html"
    )

    if page:
        return page

    return """
    <!doctype html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>مضارب أبو سعود</title>
    </head>
    <body>
        <h1>مضارب أبو سعود</h1>
        <p>index.html غير موجود</p>
    </body>
    </html>
    """, 404


# =========================================================
# LOGIN
# =========================================================

@app.route("/login")
@app.route("/login.html")
def login_page():

    page = serve_page(
        "login.html"
    )

    if page:
        return page

    return redirect("/")


# =========================================================
# REGISTER
# =========================================================

@app.route("/register")
@app.route("/register.html")
def register_page():

    page = serve_page(
        "register.html"
    )

    if page:
        return page

    return redirect("/")


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin")
@app.route("/admin/")
@app.route("/admin.html")
def admin_page():

    page = serve_page(
        "admin.html"
    )

    if page:
        return page

    return """
    <!doctype html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>لوحة الأدمن</title>
    </head>
    <body>
        <h1>لوحة الأدمن</h1>
        <p>admin.html غير موجود</p>
    </body>
    </html>
    """, 404


# =========================================================
# STATIC ASSETS
# =========================================================

@app.route("/static/<path:filename>")
def static_assets(filename):

    file_path = os.path.join(
        STATIC_DIR,
        filename
    )

    if not os.path.isfile(
        file_path
    ):

        return jsonify({
            "ok": False,
            "message": "الملف غير موجود",
            "file": filename
        }), 404

    return send_from_directory(
        STATIC_DIR,
        filename
    )


# =========================================================
# DIRECT STATIC FILES
# =========================================================

@app.route("/<path:path>")
def static_files(path):

    if path.startswith("api/"):

        return jsonify({
            "ok": False,
            "message": "API route not found",
            "path": "/" + path
        }), 404

    file_path = os.path.join(
        STATIC_DIR,
        path
    )

    if os.path.isfile(
        file_path
    ):

        return send_from_directory(
            STATIC_DIR,
            path
        )

    index_path = os.path.join(
        STATIC_DIR,
        "index.html"
    )

    if os.path.isfile(
        index_path
    ):

        return send_from_directory(
            STATIC_DIR,
            "index.html"
        )

    return jsonify({
        "ok": False,
        "message": "المسار غير موجود",
        "path": "/" + path
    }), 404


# =========================================================
# STARTUP
# =========================================================

init_db()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
