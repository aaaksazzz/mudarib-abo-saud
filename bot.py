# ============================================================
# مضارب أبو سعود V2 PRO 🤖
# Binance Spot + Multi User + Dashboard + Login + Subscription
# ============================================================

import os
import time
import json
import hmac
import hashlib
import threading
import urllib.parse
import sqlite3

from decimal import Decimal, ROUND_DOWN
from functools import wraps
from datetime import datetime, timedelta

import requests

from flask import (
    Flask,
    jsonify,
    request,
    session,
    redirect,
    url_for,
    render_template_string
)

from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet


# ============================================================
# SETTINGS
# ============================================================

API_BASE = "https://api.binance.com"
MARKET_BASE = "https://data-api.binance.vision"

DB_FILE = os.getenv("DB_FILE", "users.db")

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_NOW_123456789"
)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

BINANCE_PAY_UID = os.getenv(
    "BINANCE_PAY_UID",
    "28191866"
)

TRC20_ADDRESS = os.getenv(
    "USDT_TRC20_ADDRESS",
    "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"
)

# استراتيجية البوت
TRADE_USDT = float(os.getenv("TRADE_USDT", "10"))
MIN_USDT = 5.0

INITIAL_STOP = -0.02
PROFIT_STEP = 0.01

SCAN_INTERVAL = 180
POSITION_CHECK_SECONDS = 5

# اشتراكات
PLANS = {
    "7": ("7 أيام", 10),
    "30": ("30 يوم", 20),
    "90": ("90 يوم", 30)
}


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY

session_req = requests.Session()
session_req.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-V2-PRO/2.0"
})

db_lock = threading.Lock()


# ============================================================
# ENCRYPTION
# ============================================================

def encryption_key():
    raw = hashlib.sha256(
        SECRET_KEY.encode("utf-8")
    ).digest()

    import base64

    return base64.urlsafe_b64encode(raw)


FERNET = Fernet(encryption_key())


def encrypt_value(value):
    if not value:
        return ""

    return FERNET.encrypt(
        value.encode("utf-8")
    ).decode("utf-8")


def decrypt_value(value):
    if not value:
        return ""

    try:
        return FERNET.decrypt(
            value.encode("utf-8")
        ).decode("utf-8")
    except Exception:
        return ""


# ============================================================
# HELPERS
# ============================================================

def log(message):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True
    )


def now_string():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def db():
    c = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    c.row_factory = sqlite3.Row

    return c


# ============================================================
# DATABASE
# ============================================================

def init_db():

    with db_lock:

        c = db()

        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            active_until TEXT,

            binance_api_key TEXT,
            binance_api_secret TEXT,

            bot_enabled INTEGER DEFAULT 0,

            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan TEXT,
            method TEXT,
            reference TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            approved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            entry REAL,
            exit REAL,
            qty REAL,
            profit_percent REAL,
            profit_usdt REAL,
            opened_at TEXT,
            closed_at TEXT,
            status TEXT
        );
        """)

        admin = c.execute(
            "SELECT id FROM users WHERE is_admin=1 LIMIT 1"
        ).fetchone()

        if not admin:

            c.execute(
                """
                INSERT INTO users
                (
                    username,
                    password_hash,
                    is_admin,
                    created_at
                )
                VALUES (?, ?, 1, ?)
                """,
                (
                    ADMIN_USERNAME,
                    generate_password_hash(ADMIN_PASSWORD),
                    now_string()
                )
            )

        c.commit()
        c.close()


# ============================================================
# AUTH
# ============================================================

def current_user():

    uid = session.get("uid")

    if not uid:
        return None

    c = db()

    user = c.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()

    c.close()

    return user


def login_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if not current_user():

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return f(*args, **kwargs)

    return wrapper


def admin_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user or not user["is_admin"]:

            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return wrapper


def active_subscription(user):

    if not user:
        return False

    if user["is_admin"]:
        return True

    if not user["active_until"]:
        return False

    try:

        until = datetime.strptime(
            user["active_until"],
            "%Y-%m-%d %H:%M:%S"
        )

        return until >= datetime.now()

    except Exception:

        return False


# ============================================================
# HTML DESIGN
# ============================================================

STYLE = """

* {
    box-sizing:border-box;
}

body {
    margin:0;
    background:#070b11;
    color:#f5f7fa;
    font-family:Arial,Tahoma,sans-serif;
}

a {
    color:inherit;
    text-decoration:none;
}

.container {
    width:min(1100px,94%);
    margin:auto;
}

.topbar {
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:18px 0;
    gap:15px;
}

.logo {
    font-size:20px;
    font-weight:900;
}

.nav {
    display:flex;
    gap:8px;
    flex-wrap:wrap;
}

.nav a {
    padding:10px 14px;
    border:1px solid #263241;
    border-radius:10px;
    background:#111923;
    color:#dce5ee;
}

.nav a:hover {
    background:#172230;
}

.hero {
    padding:35px 0 25px;
}

.hero h1 {
    font-size:38px;
    margin:0 0 10px;
}

.hero p {
    color:#9ba8b7;
    line-height:1.8;
}

.card {
    background:#101720;
    border:1px solid #202c39;
    border-radius:20px;
    padding:22px;
    margin-bottom:16px;
    box-shadow:0 12px 35px rgba(0,0,0,.18);
}

.grid {
    display:grid;
    grid-template-columns:
        repeat(auto-fit,minmax(180px,1fr));
    gap:12px;
}

.stat {
    background:#0b1118;
    border:1px solid #202c39;
    padding:17px;
    border-radius:15px;
}

.label {
    color:#8997a7;
    font-size:13px;
}

.value {
    font-size:23px;
    font-weight:900;
    margin-top:8px;
}

.green {
    color:#39d98a;
}

.red {
    color:#ff5967;
}

.yellow {
    color:#f3c969;
}

.muted {
    color:#8997a7;
}

.btn {
    display:inline-block;
    border:0;
    border-radius:12px;
    padding:13px 18px;
    background:#20a36a;
    color:white;
    font-weight:bold;
    cursor:pointer;
}

.btn:hover {
    background:#27bb79;
}

.btn.dark {
    background:#17212c;
    border:1px solid #2a3949;
}

.btn.red {
    background:#b52e3b;
    color:#fff;
}

.form-group {
    margin-bottom:13px;
}

label {
    display:block;
    margin-bottom:7px;
    color:#b8c4d1;
}

input,select {
    width:100%;
    padding:14px;
    border-radius:12px;
    border:1px solid #2b3949;
    background:#080e15;
    color:#fff;
    outline:none;
}

input:focus,
select:focus {
    border-color:#24ae73;
}

.alert {
    padding:13px;
    border-radius:12px;
    margin-bottom:15px;
    background:#16221d;
    color:#66e0a3;
}

.alert.bad {
    background:#26151a;
    color:#ff7781;
}

.badge {
    display:inline-block;
    padding:7px 11px;
    border-radius:30px;
    font-size:12px;
    background:#17251e;
    color:#55db91;
}

.badge.off {
    background:#27171b;
    color:#ff6873;
}

table {
    width:100%;
    border-collapse:collapse;
}

th,td {
    padding:12px 8px;
    border-bottom:1px solid #202c39;
    text-align:right;
}

th {
    color:#8e9bab;
    font-size:13px;
}

.footer {
    text-align:center;
    color:#667384;
    padding:30px 0;
}

@media(max-width:650px) {

    .hero h1 {
        font-size:28px;
    }

    .topbar {
        align-items:flex-start;
        flex-direction:column;
    }

    .nav {
        width:100%;
    }

    .nav a {
        flex:1;
        text-align:center;
    }

    .card {
        padding:16px;
    }
}

"""


def page(title, body):

    return f"""
    <!doctype html>
    <html lang="ar" dir="rtl">

    <head>

        <meta charset="utf-8">

        <meta
            name="viewport"
            content="width=device-width,initial-scale=1"
        >

        <title>{title}</title>

        <style>
        {STYLE}
        </style>

    </head>

    <body>

        <div class="container">

            {body}

            <div class="footer">
                🤖 مضارب أبو سعود V2 PRO
            </div>

        </div>

    </body>

    </html>
    """


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return page(
        "مضارب أبو سعود V2",
        """

        <div class="topbar">

            <div class="logo">
                🤖 مضارب أبو سعود V2
            </div>

            <div class="nav">

                <a href="/login">
                    🔐 تسجيل الدخول
                </a>

                <a href="/register">
                    👤 إنشاء حساب
                </a>

            </div>

        </div>


        <div class="hero">

            <h1>
                تداول آلي باحتراف 🚀
            </h1>

            <p>
                منصة مضارب أبو سعود لمتابعة وإدارة
                تداول Binance Spot من لوحة تحكم واحدة.
            </p>

            <a class="btn" href="/register">
                ابدأ الآن
            </a>

            <a class="btn dark" href="/login">
                لدي حساب
            </a>

        </div>


        <div class="card">

            <h2>⚡ كيف يعمل؟</h2>

            <div class="grid">

                <div class="stat">
                    <div class="label">الاستراتيجية</div>
                    <div class="value">15m + 1h</div>
                </div>

                <div class="stat">
                    <div class="label">الاتجاه</div>
                    <div class="value">EMA 200</div>
                </div>

                <div class="stat">
                    <div class="label">تأكيد الحجم</div>
                    <div class="value">1.5x</div>
                </div>

                <div class="stat">
                    <div class="label">تأمين الربح</div>
                    <div class="value">كل +1%</div>
                </div>

            </div>

        </div>


        <div class="card">

            <h2>🔒 الأمان</h2>

            <p class="muted">
                مفاتيح Binance تحفظ بشكل مشفر داخل قاعدة البيانات.
                استخدم API بصلاحية Spot Trading فقط،
                ولا تفعل صلاحية السحب.
            </p>

        </div>

        """
    )


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    msg = ""

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if len(username) < 3:

            msg = "اسم المستخدم يجب أن يكون 3 أحرف على الأقل."

        elif len(password) < 6:

            msg = "كلمة المرور يجب أن تكون 6 أحرف على الأقل."

        else:

            try:

                c = db()

                c.execute(
                    """
                    INSERT INTO users
                    (
                        username,
                        password_hash,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        username,
                        generate_password_hash(password),
                        now_string()
                    )
                )

                c.commit()
                c.close()

                return redirect(
                    url_for("login")
                )

            except sqlite3.IntegrityError:

                msg = "اسم المستخدم مستخدم مسبقاً."

    return page(
        "إنشاء حساب",
        f"""

        <div class="topbar">

            <div class="logo">
                🤖 مضارب أبو سعود
            </div>

            <div class="nav">
                <a href="/">الرئيسية</a>
                <a href="/login">تسجيل الدخول</a>
            </div>

        </div>

        <div class="card">

            <h2>👤 إنشاء حساب</h2>

            {
                f'<div class="alert bad">{msg}</div>'
                if msg else ""
            }

            <form method="post">

                <div class="form-group">

                    <label>اسم المستخدم</label>

                    <input
                        name="username"
                        required
                        autocomplete="username"
                        placeholder="اسم المستخدم"
                    >

                </div>

                <div class="form-group">

                    <label>كلمة المرور</label>

                    <input
                        name="password"
                        type="password"
                        required
                        autocomplete="new-password"
                        placeholder="كلمة المرور"
                    >

                </div>

                <button class="btn" type="submit">
                    إنشاء الحساب
                </button>

            </form>

        </div>

        """
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    msg = ""

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        c = db()

        user = c.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()

        c.close()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session.clear()

            session["uid"] = user["id"]

            return redirect(
                request.args.get(
                    "next"
                ) or url_for("account")
            )

        msg = "اسم المستخدم أو كلمة المرور غير صحيحة."

    return page(
        "تسجيل الدخول",
        f"""

        <div class="topbar">

            <div class="logo">
                🤖 مضارب أبو سعود
            </div>

            <div class="nav">
                <a href="/">الرئيسية</a>
                <a href="/register">إنشاء حساب</a>
            </div>

        </div>

        <div class="card">

            <h2>🔐 تسجيل الدخول</h2>

            {
                f'<div class="alert bad">{msg}</div>'
                if msg else ""
            }

            <form method="post">

                <div class="form-group">

                    <label>اسم المستخدم</label>

                    <input
                        name="username"
                        required
                        autocomplete="username"
                    >

                </div>

                <div class="form-group">

                    <label>كلمة المرور</label>

                    <input
                        name="password"
                        type="password"
                        required
                        autocomplete="current-password"
                    >

                </div>

                <button class="btn" type="submit">
                    دخول
                </button>

            </form>

        </div>

        """
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ============================================================
# ACCOUNT
# ============================================================

@app.route("/account")
@login_required
def account():

    user = current_user()

    connected = bool(
        user["binance_api_key"]
        and user["binance_api_secret"]
    )

    subscription = (
        "فعّال"
        if active_subscription(user)
        else "غير مشترك"
    )

    bot = (
        "يعمل"
        if user["bot_enabled"]
        else "متوقف"
    )

    return page(
        "لوحة التحكم",
        f"""

        <div class="topbar">

            <div class="logo">
                🤖 لوحة التحكم
            </div>

            <div class="nav">

                <a href="/">
                    الرئيسية
                </a>

                <a href="/subscribe">
                    💳 الاشتراك
                </a>

                <a href="/logout">
                    خروج
                </a>

            </div>

        </div>


        <div class="hero">

            <h1>
                أهلاً {user["username"]} 👋
            </h1>

            <p>
                من هنا تتحكم بحساب Binance والبوت.
            </p>

        </div>


        <div class="card">

            <h2>📊 حالة الحساب</h2>

            <div class="grid">

                <div class="stat">

                    <div class="label">
                        الاشتراك
                    </div>

                    <div class="value">
                        {subscription}
                    </div>

                </div>


                <div class="stat">

                    <div class="label">
                        Binance
                    </div>

                    <div class="value
                        {'green' if connected else 'red'}">

                        {'🟢 متصل' if connected else '🔴 غير مربوط'}

                    </div>

                </div>


                <div class="stat">

                    <div class="label">
                        البوت
                    </div>

                    <div class="value">
                        {bot}
                    </div>

                </div>


                <div class="stat">

                    <div class="label">
                        انتهاء الاشتراك
                    </div>

                    <div class="value">
                        {user["active_until"] or "-"}
                    </div>

                </div>

            </div>

        </div>


        <div class="card">

            <h2>🔑 Binance</h2>

            <p class="muted">
                اربط حساب Binance الخاص بك.
                لا تستخدم صلاحية السحب.
            </p>

            <a class="btn" href="/binance">
                {'⚙️ إدارة Binance' if connected else '🔗 ربط Binance'}
            </a>

        </div>


        <div class="card">

            <h2>🤖 البوت</h2>

            <p class="muted">
                البوت يستخدم استراتيجية 15 دقيقة
                مع تأكيد الاتجاه على الساعة.
            </p>

            <a class="btn" href="/dashboard">
                📈 متابعة الصفقة
            </a>

        </div>

        """
    )


# ============================================================
# BINANCE PAGE
# ============================================================

@app.route("/binance", methods=["GET", "POST"])
@login_required
def binance_settings():

    user = current_user()

    msg = ""
    error = ""

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "save":

            api_key = request.form.get(
                "api_key",
                ""
            ).strip()

            api_secret = request.form.get(
                "api_secret",
                ""
            ).strip()

            if len(api_key) < 10:

                error = "API Key غير صحيح."

            elif len(api_secret) < 10:

                error = "API Secret غير صحيح."

            else:

                c = db()

                c.execute(
                    """
                    UPDATE users
                    SET
                        binance_api_key=?,
                        binance_api_secret=?
                    WHERE id=?
                    """,
                    (
                        encrypt_value(api_key),
                        encrypt_value(api_secret),
                        user["id"]
                    )
                )

                c.commit()
                c.close()

                msg = "تم حفظ بيانات Binance بشكل مشفر."

        elif action == "remove":

            c = db()

            c.execute(
                """
                UPDATE users
                SET
                    binance_api_key=NULL,
                    binance_api_secret=NULL,
                    bot_enabled=0
                WHERE id=?
                """,
                (user["id"],)
            )

            c.commit()
            c.close()

            msg = "تم فصل Binance وإيقاف البوت."

    user = current_user()

    connected = bool(
        user["binance_api_key"]
        and user["binance_api_secret"]
    )

    return page(
        "ربط Binance",
        f"""

        <div class="topbar">

            <div class="logo">
                🔗 ربط Binance
            </div>

            <div class="nav">
                <a href="/account">حسابي</a>
                <a href="/logout">خروج</a>
            </div>

        </div>


        <div class="card">

            <h2>
                {'🟢 Binance مربوط' if connected else '🔴 Binance غير مربوط'}
            </h2>

            {
                f'<div class="alert">{msg}</div>'
                if msg else ""
            }

            {
                f'<div class="alert bad">{error}</div>'
                if error else ""
            }

            <form method="post">

                <input
                    type="hidden"
                    name="action"
                    value="save"
                >

                <div class="form-group">

                    <label>
                        Binance API Key
                    </label>

                    <input
                        name="api_key"
                        autocomplete="off"
                        placeholder="ضع API Key هنا"
                        required
                    >

                </div>


                <div class="form-group">

                    <label>
                        Binance API Secret
                    </label>

                    <input
                        name="api_secret"
                        type="password"
                        autocomplete="new-password"
                        placeholder="ضع API Secret هنا"
                        required
                    >

                </div>


                <button
                    class="btn"
                    type="submit"
                >
                    💾 حفظ وربط Binance
                </button>

            </form>

        </div>


        <div class="card">

            <h3>⚠️ مهم جداً</h3>

            <p class="muted">
                عند إنشاء API من Binance:
            </p>

            <p>
                ✅ فعّل Spot Trading
            </p>

            <p>
                ❌ لا تفعل Withdraw
            </p>

            <p>
                ❌ لا تشارك API Secret مع أي شخص
            </p>

        </div>


        {
            f'''
            <div class="card">

                <h3>🧪 اختبار الاتصال</h3>

                <button
                    class="btn"
                    onclick="testBinance()"
                >
                    اختبار Binance
                </button>

                <div
                    id="testResult"
                    style="margin-top:15px"
                ></div>

            </div>
            '''
            if connected else ""
        }


        {
            f'''
            <div class="card">

                <h3>🛑 فصل Binance</h3>

                <form method="post">

                    <input
                        type="hidden"
                        name="action"
                        value="remove"
                    >

                    <button
                        class="btn red"
                        type="submit"
                    >
                        فصل الحساب وإيقاف البوت
                    </button>

                </form>

            </div>
            '''
            if connected else ""
        }


        <script>

        async function testBinance() {{

            const box =
                document.getElementById(
                    "testResult"
                );

            box.innerText =
                "جاري الاختبار...";

            try {{

                const r =
                    await fetch(
                        "/api/binance/test"
                    );

                const d =
                    await r.json();

                if (d.ok) {{

                    box.innerHTML =
                        '<span class="green">🟢 الاتصال ناجح — الرصيد: '
                        + Number(d.balance).toFixed(4)
                        + ' USDT</span>';

                }} else {{

                    box.innerHTML =
                        '<span class="red">🔴 '
                        + d.error
                        + '</span>';

                }}

            }} catch(e) {{

                box.innerHTML =
                    '<span class="red">🔴 فشل الاتصال</span>';

            }}

        }}

        </script>

        """
    )


# ============================================================
# BINANCE API
# ============================================================

def signed_request(
    api_key,
    api_secret,
    method,
    path,
    params=None
):

    if not api_key or not api_secret:

        raise Exception(
            "Binance API غير مربوط."
        )

    p = dict(params or {})

    p["timestamp"] = int(
        time.time() * 1000
    )

    p["recvWindow"] = 10000

    query = urllib.parse.urlencode(
        p,
        doseq=True
    )

    signature = hmac.new(
        api_secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url = (
        API_BASE
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    r = session_req.request(
        method,
        url,
        headers={
            "X-MBX-APIKEY": api_key
        },
        timeout=20
    )

    try:
        data = r.json()
    except Exception:
        data = r.text

    if r.status_code >= 400:

        raise Exception(
            f"HTTP {r.status_code} | {data}"
        )

    return data


def public_get(path, params=None):

    for attempt in range(4):

        try:

            r = session_req.get(
                MARKET_BASE + path,
                params=params or {},
                timeout=15
            )

            if r.status_code in (418, 429):

                time.sleep(
                    min(
                        30,
                        2 ** attempt + 1
                    )
                )

                continue

            r.raise_for_status()

            return r.json()

        except Exception:

            if attempt == 3:
                raise

            time.sleep(2)


# ============================================================
# USER BINANCE
# ============================================================

def user_credentials(user_id):

    c = db()

    user = c.execute(
        """
        SELECT binance_api_key,
               binance_api_secret
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    c.close()

    if not user:
        return None, None

    return (
        decrypt_value(
            user["binance_api_key"]
        ),
        decrypt_value(
            user["binance_api_secret"]
        )
    )


def get_user_account(user_id):

    api_key, api_secret = user_credentials(
        user_id
    )

    return signed_request(
        api_key,
        api_secret,
        "GET",
        "/api/v3/account"
    )


def get_user_usdt_balance(user_id):

    account = get_user_account(
        user_id
    )

    for balance in account.get(
        "balances",
        []
    ):

        if balance["asset"] == "USDT":

            return float(
                balance["free"]
            )

    return 0.0


def get_user_asset_balance(
    user_id,
    asset
):

    account = get_user_account(
        user_id
    )

    for balance in account.get(
        "balances",
        []
    ):

        if balance["asset"] == asset:

            return (
                float(balance["free"])
                +
                float(balance["locked"])
            )

    return 0.0


# ============================================================
# TEST BINANCE
# ============================================================

@app.route("/api/binance/test")
@login_required
def test_binance():

    user = current_user()

    try:

        balance = get_user_usdt_balance(
            user["id"]
        )

        return jsonify({
            "ok": True,
            "balance": balance
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        })


# ============================================================
# EXCHANGE INFO
# ============================================================

_exchange_info = None
_exchange_lock = threading.Lock()


def get_exchange_info():

    global _exchange_info

    if _exchange_info is not None:

        return _exchange_info

    with _exchange_lock:

        if _exchange_info is None:

            _exchange_info = public_get(
                "/api/v3/exchangeInfo"
            )

    return _exchange_info


def get_symbol_info(symbol):

    return next(
        (
            s
            for s
            in get_exchange_info().get(
                "symbols",
                []
            )
            if s["symbol"] == symbol
        ),
        None
    )


def get_filters(symbol):

    info = get_symbol_info(
        symbol
    )

    if not info:

        raise Exception(
            f"العملة غير موجودة: {symbol}"
        )

    result = {
        "stepSize": 0,
        "minQty": 0,
        "minNotional": 0,
        "tickSize": 0
    }

    for f in info.get(
        "filters",
        []
    ):

        if f["filterType"] == "LOT_SIZE":

            result["stepSize"] = float(
                f["stepSize"]
            )

            result["minQty"] = float(
                f["minQty"]
            )

        elif f["filterType"] in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            result["minNotional"] = float(
                f.get(
                    "minNotional",
                    0
                )
            )

        elif f["filterType"] == "PRICE_FILTER":

            result["tickSize"] = float(
                f["tickSize"]
            )

    return result


def floor_step(value, step):

    if step <= 0:

        return value

    return float(
        (
            Decimal(str(value))
            /
            Decimal(str(step))
        ).to_integral_value(
            rounding=ROUND_DOWN
        )
        *
        Decimal(str(step))
    )


# ============================================================
# MARKET
# ============================================================

def get_price(symbol):

    return float(
        public_get(
            "/api/v3/ticker/price",
            {"symbol": symbol}
        )["price"]
    )


def get_klines(
    symbol,
    interval,
    limit=210
):

    return public_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = sum(
        values[:period]
    ) / period

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
            + result
        )

    return result


# ============================================================
# STRATEGY
# ============================================================

def scan_symbol(symbol):

    try:

        candles = get_klines(
            symbol,
            "15m",
            210
        )

        if len(candles) < 205:

            return False

        closes = [
            float(x[4])
            for x in candles
        ]

        highs = [
            float(x[2])
            for x in candles
        ]

        volumes = [
            float(x[5])
            for x in candles
        ]

        price = closes[-1]

        ema15 = ema(
            closes[-201:],
            200
        )

        resistance = max(
            highs[-21:-1]
        )

        average_volume = (
            sum(volumes[-21:-1])
            / 20
        )

        volume_ratio = (
            volumes[-1]
            / average_volume
            if average_volume
            else 0
        )

        movement = (
            price - closes[-2]
        ) / closes[-2]

        if not ema15:
            return False

        if price <= ema15:
            return False

        if price <= resistance:
            return False

        if volume_ratio < 1.5:
            return False

        if movement < 0.005:
            return False

        if movement > 0.04:
            return False

        # تأكيد الساعة
        candles_1h = get_klines(
            symbol,
            "1h",
            210
        )

        closes_1h = [
            float(x[4])
            for x in candles_1h
        ]

        ema1h = ema(
            closes_1h[-201:],
            200
        )

        if not ema1h:
            return False

        if price <= ema1h:
            return False

        return True

    except Exception as e:

        log(
            f"⚠️ فشل فحص {symbol}: {e}"
        )

        return False


# ============================================================
# USER TRADING
# ============================================================

def market_buy(
    user_id,
    symbol,
    amount
):

    api_key, api_secret = user_credentials(
        user_id
    )

    filters = get_filters(
        symbol
    )

    if (
        filters["minNotional"] > 0
        and
        amount < filters["minNotional"]
    ):

        raise Exception(
            f"المبلغ أقل من الحد الأدنى "
            f"{filters['minNotional']}"
        )

    result = signed_request(
        api_key,
        api_secret,
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{amount:.8f}",
            "newOrderRespType": "FULL"
        }
    )

    qty = float(
        result.get(
            "executedQty",
            0
        )
    )

    quote = float(
        result.get(
            "cummulativeQuoteQty",
            0
        )
    )

    if qty <= 0 or quote <= 0:

        raise Exception(
            f"لم يتم تنفيذ الصفقة: {result}"
        )

    return {
        "symbol": symbol,
        "qty": qty,
        "entry": quote / qty,
        "orderId": result.get(
            "orderId"
        ),
        "quote": quote
    }


def place_stop(
    user_id,
    symbol,
    qty,
    price
):

    api_key, api_secret = user_credentials(
        user_id
    )

    filters = get_filters(
        symbol
    )

    qty = floor_step(
        qty,
        filters["stepSize"]
    )

    price = floor_step(
        price,
        filters["tickSize"]
    )

    return signed_request(
        api_key,
        api_secret,
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "STOP_LOSS",
            "quantity": f"{qty:.8f}",
            "stopPrice": f"{price:.8f}",
            "newOrderRespType": "RESULT"
        }
    )


def get_order(
    user_id,
    symbol,
    order_id
):

    api_key, api_secret = user_credentials(
        user_id
    )

    try:

        return signed_request(
            api_key,
            api_secret,
            "GET",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            }
        )

    except Exception:

        return None


def cancel_order(
    user_id,
    symbol,
    order_id
):

    api_key, api_secret = user_credentials(
        user_id
    )

    try:

        return signed_request(
            api_key,
            api_secret,
            "DELETE",
            "/api/v3/order",
            {
                "symbol": symbol,
                "orderId": order_id
            }
        )

    except Exception as e:

        log(
            f"⚠️ فشل إلغاء الأمر: {e}"
        )

        return None


# ============================================================
# STATE
# ============================================================

user_states = {}
state_lock = threading.Lock()


def get_state(user_id):

    with state_lock:

        return dict(
            user_states.get(
                user_id,
                {}
            )
        )


def set_state(
    user_id,
    state
):

    with state_lock:

        if state:

            user_states[user_id] = dict(
                state
            )

        else:

            user_states.pop(
                user_id,
                None
            )


# ============================================================
# POSITION
# ============================================================

def position_exists(
    user_id,
    symbol
):

    try:

        asset = symbol.replace(
            "USDT",
            ""
        )

        balance = get_user_asset_balance(
            user_id,
            asset
        )

        filters = get_filters(
            symbol
        )

        return balance >= filters[
            "minQty"
        ]

    except Exception:

        return False


def ensure_initial_stop(
    user_id,
    state
):

    if state.get(
        "stop_order_id"
    ):

        return state

    stop_price = (
        float(state["entry"])
        *
        (1 + INITIAL_STOP)
    )

    try:

        result = place_stop(
            user_id,
            state["symbol"],
            state["qty"],
            stop_price
        )

        state["stop_order_id"] = result.get(
            "orderId"
        )

        state["stop_price"] = stop_price

        state["locked_profit"] = INITIAL_STOP

        set_state(
            user_id,
            state
        )

    except Exception as e:

        log(
            f"❌ فشل وقف {state['symbol']}: {e}"
        )

    return state


def raise_stop(
    user_id,
    state,
    profit
):

    level = int(
        profit / PROFIT_STEP
    )

    if level < 1:
        return state

    lock = (
        level
        *
        PROFIT_STEP
    )

    old = float(
        state.get(
            "locked_profit",
            INITIAL_STOP
        )
    )

    if lock <= old:
        return state

    order_id = state.get(
        "stop_order_id"
    )

    if order_id:

        order = get_order(
            user_id,
            state["symbol"],
            order_id
        )

        if (
            order
            and
            order.get("status")
            == "NEW"
        ):

            cancel_order(
                user_id,
                state["symbol"],
                order_id
            )

    stop_price = (
        float(state["entry"])
        *
        (1 + lock)
    )

    try:

        result = place_stop(
            user_id,
            state["symbol"],
            state["qty"],
            stop_price
        )

        state["stop_order_id"] = result.get(
            "orderId"
        )

        state["stop_price"] = stop_price

        state["locked_profit"] = lock

        set_state(
            user_id,
            state
        )

        log(
            f"🔒 user={user_id} "
            f"{state['symbol']} "
            f"تأمين {lock*100:.0f}%"
        )

    except Exception as e:

        log(
            f"❌ فشل تأمين الربح: {e}"
        )

    return state


# ============================================================
# TRADE MANAGER
# ============================================================

def manage_position(
    user_id,
    state
):

    state = ensure_initial_stop(
        user_id,
        state
    )

    set_state(
        user_id,
        state
    )

    symbol = state["symbol"]

    while True:

        try:

            if not position_exists(
                user_id,
                symbol
            ):

                current = get_price(
                    symbol
                )

                entry = float(
                    state["entry"]
                )

                qty = float(
                    state["qty"]
                )

                profit = (
                    current - entry
                ) / entry

                profit_usdt = (
                    current - entry
                ) * qty

                save_trade(
                    user_id,
                    state,
                    current,
                    profit,
                    profit_usdt
                )

                set_state(
                    user_id,
                    {}
                )

                return

            current = get_price(
                symbol
            )

            entry = float(
                state["entry"]
            )

            qty = float(
                state["qty"]
            )

            profit = (
                current - entry
            ) / entry

            profit_usdt = (
                current - entry
            ) * qty

            state["current_price"] = current

            state["profit_percent"] = (
                profit * 100
            )

            state["profit_usdt"] = (
                profit_usdt
            )

            set_state(
                user_id,
                state
            )

            if profit >= PROFIT_STEP:

                state = raise_stop(
                    user_id,
                    state,
                    profit
                )

            order_id = state.get(
                "stop_order_id"
            )

            if order_id:

                order = get_order(
                    user_id,
                    symbol,
                    order_id
                )

                if (
                    order
                    and
                    order.get("status")
                    == "FILLED"
                ):

                    time.sleep(2)

                    current = get_price(
                        symbol
                    )

                    profit = (
                        current - entry
                    ) / entry

                    save_trade(
                        user_id,
                        state,
                        current,
                        profit,
                        (
                            current - entry
                        ) * qty
                    )

                    set_state(
                        user_id,
                        {}
                    )

                    return

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            log(
                f"⚠️ متابعة user={user_id}: {e}"
            )

            time.sleep(5)


def save_trade(
    user_id,
    state,
    exit_price,
    profit,
    profit_usdt
):

    c = db()

    c.execute(
        """
        INSERT INTO trades
        (
            user_id,
            symbol,
            entry,
            exit,
            qty,
            profit_percent,
            profit_usdt,
            opened_at,
            closed_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            state["symbol"],
            float(state["entry"]),
            exit_price,
            float(state["qty"]),
            profit * 100,
            profit_usdt,
            state.get(
                "opened_at",
                now_string()
            ),
            now_string(),
            "closed"
        )
    )

    c.commit()
    c.close()


# ============================================================
# USER BOT
# ============================================================

def user_bot(
    user_id
):

    log(
        f"🤖 تشغيل بوت المستخدم {user_id}"
    )

    while True:

        try:

            c = db()

            user = c.execute(
                "SELECT * FROM users WHERE id=?",
                (user_id,)
            ).fetchone()

            c.close()

            if not user:

                return

            if not active_subscription(
                user
            ):

                time.sleep(30)

                continue

            if not user["bot_enabled"]:

                time.sleep(15)

                continue

            if not (
                user["binance_api_key"]
                and
                user["binance_api_secret"]
            ):

                time.sleep(15)

                continue

            existing = get_state(
                user_id
            )

            if existing.get("symbol"):

                manage_position(
                    user_id,
                    existing
                )

                continue

            balance = get_user_usdt_balance(
                user_id
            )

            if balance < MIN_USDT:

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            amount = min(
                TRADE_USDT,
                balance * 0.995
            )

            if amount < MIN_USDT:

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            symbols = [
                s["symbol"]
                for s in get_exchange_info().get(
                    "symbols",
                    []
                )
                if (
                    s.get("status")
                    == "TRADING"
                    and
                    s.get("quoteAsset")
                    == "USDT"
                    and
                    s.get(
                        "isSpotTradingAllowed"
                    ) is not False
                )
            ]

            for symbol in symbols:

                if get_state(
                    user_id
                ).get("symbol"):

                    break

                if scan_symbol(
                    symbol
                ):

                    try:

                        result = market_buy(
                            user_id,
                            symbol,
                            amount
                        )

                        state = {
                            "symbol": symbol,
                            "entry": result["entry"],
                            "current_price": result["entry"],
                            "qty": result["qty"],
                            "order_id": result["orderId"],
                            "opened_at": now_string(),
                            "profit_percent": 0,
                            "profit_usdt": 0,
                            "locked_profit": INITIAL_STOP,
                            "stop_price": (
                                result["entry"]
                                *
                                (1 + INITIAL_STOP)
                            ),
                            "stop_order_id": None
                        }

                        set_state(
                            user_id,
                            state
                        )

                        log(
                            f"🟢 شراء user={user_id} "
                            f"{symbol} "
                            f"@ {result['entry']}"
                        )

                        manage_position(
                            user_id,
                            state
                        )

                        break

                    except Exception as e:

                        log(
                            f"❌ شراء {symbol}: {e}"
                        )

                time.sleep(
                    0.08
                )

            time.sleep(
                SCAN_INTERVAL
            )

        except Exception as e:

            log(
                f"❌ بوت user={user_id}: {e}"
            )

            time.sleep(15)


bot_threads = {}
bot_threads_lock = threading.Lock()


def start_user_bot(
    user_id
):

    with bot_threads_lock:

        thread = bot_threads.get(
            user_id
        )

        if (
            thread
            and
            thread.is_alive()
        ):

            return

        thread = threading.Thread(
            target=user_bot,
            args=(user_id,),
            daemon=True
        )

        bot_threads[user_id] = thread

        thread.start()


def start_all_bots():

    c = db()

    users = c.execute(
        """
        SELECT id
        FROM users
        WHERE bot_enabled=1
        """
    ).fetchall()

    c.close()

    for user in users:

        start_user_bot(
            user["id"]
        )


# ============================================================
# BOT CONTROL
# ============================================================

@app.route(
    "/bot/toggle",
    methods=["POST"]
)
@login_required
def bot_toggle():

    user = current_user()

    if not active_subscription(
        user
    ):

        return redirect(
            url_for("subscribe")
        )

    if not (
        user["binance_api_key"]
        and
        user["binance_api_secret"]
    ):

        return redirect(
            url_for("binance_settings")
        )

    enabled = request.form.get(
        "enabled"
    ) == "1"

    c = db()

    c.execute(
        """
        UPDATE users
        SET bot_enabled=?
        WHERE id=?
        """,
        (
            1 if enabled else 0,
            user["id"]
        )
    )

    c.commit()
    c.close()

    if enabled:

        start_user_bot(
            user["id"]
        )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# USER DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    state = get_state(
        user["id"]
    )

    try:

        balance = get_user_usdt_balance(
            user["id"]
        )

        connected = True

    except Exception:

        balance = 0

        connected = False

    return page(
        "لوحة التداول",
        f"""

        <div class="topbar">

            <div class="logo">
                📊 مضارب أبو سعود
            </div>

            <div class="nav">
                <a href="/account">
                    حسابي
                </a>

                <a href="/binance">
                    Binance
                </a>

                <a href="/logout">
                    خروج
                </a>
            </div>

        </div>


        <div class="card">

            <h2>📊 لوحة التداول</h2>

            <div class="grid">

                <div class="stat">
                    <div class="label">
                        Binance
                    </div>

                    <div class="value">
                        {
                            "🟢 متصل"
                            if connected
                            else
                            "🔴 غير متصل"
                        }
                    </div>
                </div>


                <div class="stat">

                    <div class="label">
                        الرصيد
                    </div>

                    <div class="value">
                        {balance:.4f} USDT
                    </div>

                </div>


                <div class="stat">

                    <div class="label">
                        مبلغ الصفقة
                    </div>

                    <div class="value">
                        {TRADE_USDT:g} USDT
                    </div>

                </div>


                <div class="stat">

                    <div class="label">
                        البوت
                    </div>

                    <div class="value">

                        {
                            "🟢 يعمل"
                            if user["bot_enabled"]
                            else
                            "🔴 متوقف"
                        }

                    </div>

                </div>

            </div>

        </div>


        <div class="card">

            <h2>🤖 التحكم بالبوت</h2>

            <form
                method="post"
                action="/bot/toggle"
            >

                <input
                    type="hidden"
                    name="enabled"
                    value="{
                        '0'
                        if user['bot_enabled']
                        else
                        '1'
                    }"
                >

                <button
                    class="btn {
                        'red'
                        if user['bot_enabled']
                        else
                        ''
                    }"
                >

                    {
                        "⏹ إيقاف البوت"
                        if user["bot_enabled"]
                        else
                        "▶️ تشغيل البوت"
                    }

                </button>

            </form>

        </div>


        <div class="card">

            <h2>🎯 الصفقة الحالية</h2>

            {
                f'''
                <div class="grid">

                    <div class="stat">
                        <div class="label">العملة</div>
                        <div class="value">
                            {state["symbol"]}
                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">الدخول</div>
                        <div class="value">
                            {float(state["entry"]):.8f}
                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">السعر الحالي</div>
                        <div class="value">
                            {float(state.get("current_price",0)):.8f}
                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">الربح</div>
                        <div class="value
                            {'green' if float(state.get('profit_percent',0)) >= 0 else 'red'}">

                            {float(state.get("profit_percent",0)):.2f}%

                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">الربح USDT</div>
                        <div class="value">
                            {float(state.get("profit_usdt",0)):.4f}
                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">وقف الخسارة</div>
                        <div class="value">
                            {float(state.get("stop_price",0)):.8f}
                        </div>
                    </div>

                    <div class="stat">
                        <div class="label">تأمين الربح</div>
                        <div class="value green">
                            {float(state.get("locked_profit",-0.02))*100:.0f}%
                        </div>
                    </div>

                </div>
                '''
                if state.get("symbol")
                else
                '''
                <p class="muted">
                    لا توجد صفقة مفتوحة حالياً.
                </p>
                '''
            }

        </div>

        """
    )


# ============================================================
# SUBSCRIPTION
# ============================================================

@app.route(
    "/subscribe",
    methods=["GET", "POST"]
)
@login_required
def subscribe():

    user = current_user()

    msg = ""

    if request.method == "POST":

        plan = request.form.get(
            "plan"
        )

        method = request.form.get(
            "method"
        )

        reference = request.form.get(
            "reference",
            ""
        ).strip()

        if plan not in PLANS:

            msg = "الخطة غير صحيحة."

        elif method not in (
            "binance",
            "trc20"
        ):

            msg = "طريقة الدفع غير صحيحة."

        else:

            c = db()

            c.execute(
                """
                INSERT INTO payments
                (
                    user_id,
                    plan,
                    method,
                    reference,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    plan,
                    method,
                    reference,
                    now_string()
                )
            )

            c.commit()
            c.close()

            msg = (
                "تم إرسال طلب الاشتراك. "
                "بانتظار اعتماد الأدمن."
            )

    options = ""

    for key, value in PLANS.items():

        options += (
            f'<option value="{key}">'
            f'{value[0]} — {value[1]} USDT'
            f'</option>'
        )

    return page(
        "الاشتراك",
        f"""

        <div class="topbar">

            <div class="logo">
                💳 الاشتراك
            </div>

            <div class="nav">
                <a href="/account">
                    حسابي
                </a>

                <a href="/logout">
                    خروج
                </a>
            </div>

        </div>


        <div class="card">

            <h2>💳 اختر باقتك</h2>

            {
                f'<div class="alert">{msg}</div>'
                if msg else ""
            }

            <div class="grid">

                <div class="stat">
                    <div class="label">7 أيام</div>
                    <div class="value">10 USDT</div>
                </div>

                <div class="stat">
                    <div class="label">30 يوم</div>
                    <div class="value">20 USDT</div>
                </div>

                <div class="stat">
                    <div class="label">90 يوم</div>
                    <div class="value">30 USDT</div>
                </div>

            </div>

        </div>


        <div class="card">

            <p>
                <b>Binance Pay UID:</b>
                {BINANCE_PAY_UID}
            </p>

            <p>
                <b>USDT TRC20:</b>
                {TRC20_ADDRESS}
            </p>

            <form method="post">

                <div class="form-group">

                    <label>
                        الباقة
                    </label>

                    <select name="plan">
                        {options}
                    </select>

                </div>


                <div class="form-group">

                    <label>
                        طريقة الدفع
                    </label>

                    <select name="method">

                        <option value="binance">
                            Binance Pay
                        </option>

                        <option value="trc20">
                            USDT TRC20
                        </option>

                    </select>

                </div>


                <div class="form-group">

                    <label>
                        رقم العملية / TXID
                    </label>

                    <input
                        name="reference"
                        placeholder="اختياري"
                    >

                </div>


                <button
                    class="btn"
                    type="submit"
                >
                    إرسال طلب الاشتراك
                </button>

            </form>

        </div>

        """
    )


# ============================================================
# ADMIN
# ============================================================

def activate_user(
    user_id,
    days
):

    c = db()

    row = c.execute(
        """
        SELECT active_until
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    base = datetime.now()

    if row and row["active_until"]:

        try:

            old = datetime.strptime(
                row["active_until"],
                "%Y-%m-%d %H:%M:%S"
            )

            if old > base:

                base = old

        except Exception:
            pass

    until = (
        base
        +
        timedelta(days=days)
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    c.execute(
        """
        UPDATE users
        SET active_until=?
        WHERE id=?
        """,
        (
            until,
            user_id
        )
    )

    c.commit()
    c.close()

    return until


@app.route(
    "/admin",
    methods=["GET", "POST"]
)
@admin_required
def admin():

    msg = ""

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "credentials":

            username = request.form.get(
                "new_username",
                ""
            ).strip()

            password = request.form.get(
                "new_password",
                ""
            )

            if (
                len(username) >= 3
                and
                len(password) >= 6
            ):

                user = current_user()

                c = db()

                try:

                    c.execute(
                        """
                        UPDATE users
                        SET
                            username=?,
                            password_hash=?
                        WHERE id=?
                        """,
                        (
                            username,
                            generate_password_hash(
                                password
                            ),
                            user["id"]
                        )
                    )

                    c.commit()

                    msg = (
                        "تم تحديث بيانات الأدمن."
                    )

                except sqlite3.IntegrityError:

                    msg = (
                        "اسم المستخدم مستخدم."
                    )

                c.close()

    c = db()

    users = c.execute(
        """
        SELECT *
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    payments = c.execute(
        """
        SELECT
            p.*,
            u.username
        FROM payments p
        JOIN users u
            ON u.id=p.user_id
        ORDER BY p.id DESC
        LIMIT 50
        """
    ).fetchall()

    c.close()

    users_html = ""

    for user in users:

        connected = bool(
            user["binance_api_key"]
            and
            user["binance_api_secret"]
        )

        if user["is_admin"]:

            action = "👑"

        else:

            action = f"""
            <form
                method="post"
                action="/admin/activate"
            >

                <input
                    type="hidden"
                    name="user_id"
                    value="{user['id']}"
                >

                <select name="plan">

                    <option value="7">
                        7 أيام
                    </option>

                    <option value="30">
                        30 يوم
                    </option>

                    <option value="90">
                        90 يوم
                    </option>

                </select>

                <button class="btn">
                    تفعيل
                </button>

            </form>
            """

        users_html += f"""

        <tr>

            <td>
                {user["username"]}
            </td>

            <td>
                {
                    "🟢"
                    if connected
                    else
                    "🔴"
                }
            </td>

            <td>
                {
                    "يعمل"
                    if user["bot_enabled"]
                    else
                    "متوقف"
                }
            </td>

            <td>
                {user["active_until"] or "-"}
            </td>

            <td>
                {action}
            </td>

        </tr>

        """

    payments_html = ""

    for payment in payments:

        action = ""

        if payment["status"] == "pending":

            action = f"""
            <form
                method="post"
                action="/admin/approve"
            >

                <input
                    type="hidden"
                    name="payment_id"
                    value="{payment['id']}"
                >

                <button class="btn">
                    اعتماد
                </button>

            </form>
            """

        payments_html += f"""

        <tr>

            <td>
                {payment["username"]}
            </td>

            <td>
                {payment["plan"]} يوم
            </td>

            <td>
                {payment["method"]}
            </td>

            <td>
                {payment["reference"] or "-"}
            </td>

            <td>
                {payment["status"]}
            </td>

            <td>
                {action}
            </td>

        </tr>

        """

    return page(
        "لوحة الأدمن",
        f"""

        <div class="topbar">

            <div class="logo">
                👑 لوحة الأدمن
            </div>

            <div class="nav">
                <a href="/account">
                    حسابي
                </a>

                <a href="/">
                    الرئيسية
                </a>

                <a href="/logout">
                    خروج
                </a>
            </div>

        </div>


        {
            f'<div class="alert">{msg}</div>'
            if msg else ""
        }


        <div class="card">

            <h2>⚙️ بيانات الأدمن</h2>

            <form method="post">

                <input
                    type="hidden"
                    name="action"
                    value="credentials"
                >

                <div class="form-group">

                    <label>
                        اسم المستخدم الجديد
                    </label>

                    <input
                        name="new_username"
                    >

                </div>

                <div class="form-group">

                    <label>
                        كلمة المرور الجديدة
                    </label>

                    <input
                        name="new_password"
                        type="password"
                    >

                </div>

                <button class="btn">
                    حفظ
                </button>

            </form>

        </div>


        <div class="card">

            <h2>👥 المستخدمون</h2>

            <table>

                <tr>
                    <th>المستخدم</th>
                    <th>Binance</th>
                    <th>البوت</th>
                    <th>الاشتراك</th>
                    <th>إجراء</th>
                </tr>

                {users_html}

            </table>

        </div>


        <div class="card">

            <h2>💳 طلبات الدفع</h2>

            <table>

                <tr>
                    <th>المستخدم</th>
                    <th>الخطة</th>
                    <th>الدفع</th>
                    <th>المرجع</th>
                    <th>الحالة</th>
                    <th></th>
                </tr>

                {payments_html}

            </table>

        </div>

        """
    )


@app.route(
    "/admin/activate",
    methods=["POST"]
)
@admin_required
def admin_activate():

    user_id = int(
        request.form["user_id"]
    )

    days = int(
        request.form["plan"]
    )

    activate_user(
        user_id,
        days
    )

    return redirect(
        "/admin"
    )


@app.route(
    "/admin/approve",
    methods=["POST"]
)
@admin_required
def admin_approve():

    payment_id = int(
        request.form["payment_id"]
    )

    c = db()

    payment = c.execute(
        """
        SELECT *
        FROM payments
        WHERE id=?
        """,
        (payment_id,)
    ).fetchone()

    c.close()

    if (
        payment
        and
        payment["status"]
        == "pending"
    ):

        activate_user(
            payment["user_id"],
            int(payment["plan"])
        )

        c = db()

        c.execute(
            """
            UPDATE payments
            SET
                status='approved',
                approved_at=?
            WHERE id=?
            """,
            (
                now_string(),
                payment_id
            )
        )

        c.commit()
        c.close()

    return redirect(
        "/admin"
    )


# ============================================================
# PUBLIC API
# ============================================================

@app.route("/api/dashboard")
def public_dashboard():

    state = {}

    with state_lock:

        # عرض صفقة عامة فقط بدون بيانات حساب المستخدم
        for value in user_states.values():

            if value.get("symbol"):

                state = {
                    "symbol": value.get(
                        "symbol"
                    ),
                    "entry": value.get(
                        "entry"
                    ),
                    "current_price": value.get(
                        "current_price"
                    ),
                    "profit_percent": value.get(
                        "profit_percent"
                    ),
                    "locked_profit": value.get(
                        "locked_profit"
                    ),
                    "stop_price": value.get(
                        "stop_price"
                    )
                }

                break

    return jsonify({
        "online": True,
        "trade": state or None
    })


@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": "Mudarib Abo Saud V2 PRO",
        "time": now_string()
    })


# ============================================================
# START
# ============================================================

init_db()


def boot():

    time.sleep(5)

    log(
        "================================================"
    )

    log(
        "🤖 مضارب أبو سعود V2 PRO"
    )

    log(
        "🚀 النظام بدأ التشغيل"
    )

    log(
        "================================================"
    )

    start_all_bots()


threading.Thread(
    target=boot,
    daemon=True
).start()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10000"
            )
        ),
        threaded=True
    )
