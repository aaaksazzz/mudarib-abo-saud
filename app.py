from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os, sqlite3, secrets
from market_engine import MarketEngine

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=__import__("datetime").timedelta(days=7),
)
if not os.getenv("SECRET_KEY"):
    app.logger.warning("SECRET_KEY is not configured; sessions will be invalidated on restart")
DB = os.getenv("DATABASE_PATH", "smart_trading.db")
engine = MarketEngine()

def db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, enabled INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL, status TEXT DEFAULT 'open', exit_price REAL, pnl_pct REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT);
        CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, published INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)

def login_required(fn):
    @wraps(fn)
    def wrapped(*a,**k):
        if not session.get("user_id"): return redirect(url_for("login"))
        return fn(*a,**k)
    return wrapped

@app.get("/")
def home(): return render_template("index.html", user=session.get("username"))

@app.get("/login")
def login(): return render_template("auth.html", mode="login")

@app.post("/login")
def do_login():
    with db() as c: u=c.execute("SELECT * FROM users WHERE email=?",(request.form.get("email","").lower().strip(),)).fetchone()
    if not u or not check_password_hash(u["password"],request.form.get("password","")):
        flash("بيانات الدخول غير صحيحة"); return redirect(url_for("login"))
    session.update(user_id=u["id"],username=u["username"])
    return redirect(url_for("account"))

@app.get("/register")
def register(): return render_template("auth.html", mode="register")

@app.post("/register")
def do_register():
    username=request.form.get("username","").strip(); email=request.form.get("email","").lower().strip(); password=request.form.get("password","")
    if len(username)<3 or len(password)<8 or "@" not in email:
        flash("تحقق من البيانات؛ كلمة المرور 8 أحرف على الأقل"); return redirect(url_for("register"))
    try:
        with db() as c: c.execute("INSERT INTO users(username,email,password) VALUES(?,?,?)",(username,email,generate_password_hash(password)))
    except sqlite3.IntegrityError:
        flash("اسم المستخدم أو البريد مستخدم مسبقاً"); return redirect(url_for("register"))
    flash("تم إنشاء الحساب، سجل دخولك"); return redirect(url_for("login"))

@app.get("/logout")
def logout(): session.clear(); return redirect(url_for("home"))

@app.get("/account")
@login_required
def account(): return render_template("account.html", user=session.get("username"))

@app.get("/api/markets")
def markets(): return jsonify(engine.market_overview())

@app.get("/api/scan/<market>")
def scan(market):
    timeframe=request.args.get("timeframe","15m")
    if timeframe not in ("1m","15m","1h","4h","1d","1w","1M"): return jsonify(error="فريم غير مدعوم"),400
    try: return jsonify(engine.scan(market,timeframe))
    except ValueError as e: return jsonify(error=str(e)),404
    except Exception: app.logger.exception("scan failed"); return jsonify(error="تعذر جلب بيانات السوق حالياً"),503

@app.get("/api/news")
def news(): return jsonify(engine.news())

@app.get("/api/stats")
@login_required
def stats():
    with db() as c:
        rows=c.execute("SELECT pnl_pct FROM trades WHERE user_id=? AND status='closed' AND pnl_pct IS NOT NULL",(session["user_id"],)).fetchall()
    vals=[r["pnl_pct"] for r in rows]; wins=sum(v>0 for v in vals); losses=sum(v<0 for v in vals)
    return jsonify(total=len(vals),wins=wins,losses=losses,win_rate=round(wins/len(vals)*100,1) if vals else None,net_pct=round(sum(vals),2))

@app.route("/api/trades",methods=["GET","POST"])
@login_required
def trades():
    with db() as c:
        if request.method=="POST":
            x=request.get_json(force=True)
            try: c.execute("INSERT INTO trades(user_id,market,symbol,side,entry,stop,target) VALUES(?,?,?,?,?,?,?)",(session["user_id"],x["market"],x["symbol"],x["side"],float(x["entry"]),float(x["stop"]),float(x["target"])))
            except (KeyError,ValueError): return jsonify(error="بيانات الصفقة غير مكتملة"),400
        rows=c.execute("SELECT * FROM trades WHERE user_id=? ORDER BY id DESC LIMIT 100",(session["user_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/trades/<int:trade_id>/close")
@login_required
def close_trade(trade_id):
    data=request.get_json(silent=True) or {}
    try:
        exit_price=float(data["exit_price"])
        if exit_price<=0: raise ValueError()
    except (KeyError,TypeError,ValueError):
        return jsonify(error="سعر الإغلاق غير صحيح"),400
    with db() as c:
        trade=c.execute("SELECT * FROM trades WHERE id=? AND user_id=?",(trade_id,session["user_id"])).fetchone()
        if not trade: return jsonify(error="الصفقة غير موجودة"),404
        if trade["status"]!="open": return jsonify(error="الصفقة مغلقة مسبقاً"),409
        entry=float(trade["entry"])
        raw=(exit_price-entry)/entry*100
        pnl=raw if trade["side"] in ("شراء","BUY","LONG") else -raw
        c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",(exit_price,round(pnl,4),trade_id,session["user_id"]))
    return jsonify(ok=True,pnl_pct=round(pnl,4),exit_price=exit_price)

@app.post("/api/alerts")
@login_required
def add_alert():
    x=request.get_json(force=True)
    with db() as c: c.execute("INSERT INTO alerts(user_id,market,symbol,direction) VALUES(?,?,?,?)",(session["user_id"],x["market"],x["symbol"],x["direction"]))
    return jsonify(ok=True)

@app.get("/api/alerts")
@login_required
def alerts():
    with db() as c: rows=c.execute("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/blog")
def blog():
    with db() as c: posts=c.execute("SELECT * FROM posts WHERE published=1 ORDER BY id DESC").fetchall()
    return render_template("blog.html",posts=posts)

@app.get("/health")
def health(): return jsonify(status="ok")

init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
