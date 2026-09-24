import os, sqlite3, secrets, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
PORT = int(os.getenv("PORT", "8080"))
DB = os.getenv("SQLITE_FILE", "mudarib.db")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent":"Mozilla/5.0 Mudarib-Abo-Saud/6.0"})
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "aaaksazzz").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
TRC20_ADDRESS = os.getenv("TRC20_ADDRESS", "").strip()
BINANCE_PAY_ID = os.getenv("BINANCE_PAY_ID", "").strip()

PLANS = {"7d":{"name":"7 أيام","days":7,"amount":10},"30d":{"name":"30 يوم","days":30,"amount":20},"90d":{"name":"90 يوم","days":90,"amount":30}}
MARKETS = {
 "saudi":[("2222.SR","أرامكو"),("2010.SR","سابك"),("1120.SR","الراجحي"),("1180.SR","الأهلي السعودي"),("1150.SR","مصرف الإنماء"),("7010.SR","STC"),("1211.SR","معادن"),("2380.SR","بترو رابغ"),("4003.SR","إكسترا"),("4200.SR","الدريس")],
 "usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("GOOGL","Alphabet"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],
 "forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("XAUUSD=X","Gold")]
}

def db():
    c=sqlite3.connect(DB, timeout=20, check_same_thread=False); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL,plan TEXT NOT NULL,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """); c.commit(); c.close()

def json_ok(**x): return jsonify({"ok":True,**x})
def user_name(): return session.get("user")
def is_admin(): return bool(session.get("admin"))

def yahoo(symbol, interval="1d", range_="3mo"):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+symbol
    r=HTTP.get(url,params={"interval":interval,"range":range_},timeout=12); r.raise_for_status()
    res=r.json()["chart"]["result"][0]; q=res["indicators"]["quote"][0]; ts=res.get("timestamp",[])
    rows=[]
    for i,t in enumerate(ts):
        try:
            rows.append({"time":t,"open":float(q["open"][i]),"high":float(q["high"][i]),"low":float(q["low"][i]),"close":float(q["close"][i]),"volume":float(q.get("volume",[0]*len(ts))[i] or 0)})
        except: pass
    return rows

def okx(inst_type="SPOT"):
    r=HTTP.get("https://www.okx.com/api/v5/market/tickers",params={"instType":inst_type},timeout=12); r.raise_for_status()
    return r.json().get("data",[])

def okx_candles(inst, bar="15m", limit=100):
    r=HTTP.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":limit},timeout=12); r.raise_for_status()
    out=[]
    for x in reversed(r.json().get("data",[])):
        try: out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except: pass
    return out

def analyze(candles, symbol, market):
    if len(candles)<8: return None
    c=candles[-1]; prev=candles[-2]
    closes=[x["close"] for x in candles[-20:]]
    avg=sum(closes)/len(closes)
    change=(c["close"]/prev["close"]-1)*100 if prev["close"] else 0
    trend=(c["close"]/avg-1)*100 if avg else 0
    range_pct=((c["high"]-c["low"])/c["low"]*100) if c["low"] else 0
    score=50
    score += max(-20,min(20,trend*8))
    score += max(-15,min(15,change*6))
    if c["close"]>c["open"]: score+=8
    elif c["close"]<c["open"]: score-=8
    score=max(0,min(100,round(score)))
    direction="شراء" if score>=65 else "بيع" if score<=35 else "حيادي"
    entry=c["close"]
    risk=max(abs(entry*0.012), abs(c["high"]-c["low"])*0.7)
    if direction=="شراء": tp1=entry+risk; tp2=entry+risk*2; tp3=entry+risk*3; sl=entry-risk
    elif direction=="بيع": tp1=entry-risk; tp2=entry-risk*2; tp3=entry-risk*3; sl=entry+risk
    else: tp1=tp2=tp3=sl=entry
    return {"symbol":symbol,"price":entry,"entry":entry,"direction":direction,"signal":direction,"score":score,"confidence":max(50,min(95,score if direction!="حيادي" else 50+abs(score-50))),"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"rr":2,"range":range_pct,"change":change,"time":c["time"],"tradeReady":direction!="حيادي"}

def market_items(market):
    if market in MARKETS: return [{"symbol":s,"name":n} for s,n in MARKETS[market]]
    tickers=okx("SWAP" if market=="futures" else "SPOT")
    items=[]
    for x in tickers:
        inst=x.get("instId","")
        if inst.endswith("-USDT-SWAP") if market=="futures" else inst.endswith("-USDT"):
            items.append({"symbol":inst,"name":inst,"price":float(x.get("last") or 0)})
    return items[:40]

def scan(market="crypto", interval="15m", limit=20):
    if market in ("crypto","futures"):
        items=market_items(market)
        def one(item):
            try:
                return analyze(okx_candles(item["symbol"],interval,100),item["symbol"],market)
            except Exception as e:
                print("scan",market,item["symbol"],e); return None
    else:
        items=market_items(market)
        yint={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d"}.get(interval,"1d")
        yrange="5d" if yint in ("5m","15m","30m") else "1mo" if yint=="1h" else "6mo"
        def one(item):
            try: return analyze(yahoo(item["symbol"],yint,yrange),item["symbol"],market)
            except Exception as e:
                print("scan",market,item["symbol"],e); return None
    out=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        fs=[ex.submit(one,x) for x in items]
        for f in as_completed(fs):
            r=f.result()
            if r: out.append(r)
    out.sort(key=lambda x:(x["tradeReady"],x["confidence"],abs(x["change"])),reverse=True)
    return {"ok":True,"market":market,"interval":interval,"results":out[:limit],"updatedAt":datetime.now(timezone.utc).isoformat()}

@app.get("/")
def home(): return render_template("index.html",page_id="dashboard",page_title="مضارب أبو سعود")
@app.get("/spot")
def spot(): return render_template("spot.html",page_id="spot",page_title="صفقات السبوت")
@app.get("/futures")
def futures(): return render_template("futures.html",page_id="futures",page_title="صفقات الفيوتشر")
@app.get("/contracts")
def contracts(): return render_template("contracts.html",page_id="contracts",page_title="العقود الآجلة")
@app.get("/scanner")
def scanner_page(): return render_template("scanner.html",page_id="scanner",page_title="ماسح الفرص")
@app.get("/saudi")
def saudi(): return render_template("saudi.html",page_id="saudi",page_title="السوق السعودي")
@app.get("/usmarket")
def usmarket(): return render_template("usmarket.html",page_id="usmarket",page_title="السوق الأمريكي")
@app.get("/forex")
def forex(): return render_template("forex.html",page_id="forex",page_title="الفوركس والسلع")
@app.get("/news")
def news(): return render_template("news.html",page_id="news",page_title="الأخبار")
@app.get("/subscription")
def subscription(): return render_template("subscription.html",page_id="subscription",page_title="الاشتراك")
@app.get("/login")
def login_page(): return render_template("login.html",page_id="login",page_title="تسجيل الدخول")
@app.get("/register")
def register_page(): return render_template("register.html",page_id="register",page_title="إنشاء حساب")
@app.get("/admin")
def admin_page(): return render_template("admin.html",page_id="admin",page_title="لوحة الإدارة")

@app.get("/api/ai/signals")
@app.get("/api/scan")
def api_signals():
    market=request.args.get("market","crypto").lower()
    interval=request.args.get("interval","15m")
    if market not in {"crypto","futures","saudi","usmarket","forex"}: return jsonify({"ok":False,"message":"السوق غير صحيح"}),400
    try: return jsonify(scan(market,interval,max(1,min(40,int(request.args.get("limit",20))))))
    except Exception as e:
        print("API ERROR",e); return jsonify({"ok":False,"message":"تعذر جلب بيانات السوق","results":[]}),502

@app.get("/api/market/status")
def status():
    out=[]
    for m,n,i in [("crypto","العملات الرقمية","15m"),("futures","الفيوتشر","15m"),("saudi","السوق السعودي","1D"),("usmarket","السوق الأمريكي","1D"),("forex","الفوركس","1H")]:
        try:
            d=scan(m,i,20); buys=sum(x["direction"]=="شراء" for x in d["results"]); sells=sum(x["direction"]=="بيع" for x in d["results"])
            out.append({"market":m,"name":n,"buys":buys,"sells":sells,"signals":len(d["results"])})
        except: out.append({"market":m,"name":n,"buys":0,"sells":0,"signals":0})
    return json_ok(results=out,updatedAt=datetime.now(timezone.utc).isoformat())

@app.post("/api/auth/register")
@app.post("/api/register")
def register():
    d=request.get_json(silent=True) or {}; name=str(d.get("name","")).strip(); email=str(d.get("email","")).strip().lower(); password=str(d.get("password",""))
    username=str(d.get("username") or email).strip()
    if len(name)<2 or "@" not in email or len(password)<6: return jsonify({"ok":False,"message":"تأكد من الاسم والبريد وكلمة المرور (6 أحرف على الأقل)"}),400
    try:
        c=db(); c.execute("INSERT INTO users(username,email,name,password) VALUES(?,?,?,?)",(username,email,name,generate_password_hash(password))); c.commit(); c.close()
        return json_ok(message="تم إنشاء الحساب")
    except sqlite3.IntegrityError: return jsonify({"ok":False,"message":"البريد أو اسم المستخدم مستخدم مسبقاً"}),400
    except Exception as e: print("register",e); return jsonify({"ok":False,"message":"تعذر إنشاء الحساب"}),500

@app.post("/api/auth/login")
@app.post("/api/login")
def login():
    d=request.get_json(silent=True) or {}; ident=str(d.get("email") or d.get("username") or "").strip().lower(); password=str(d.get("password",""))
    if ident==ADMIN_USERNAME.lower() and ADMIN_PASSWORD and secrets.compare_digest(password,ADMIN_PASSWORD):
        session.clear(); session.update(user=ADMIN_USERNAME,admin=True); return json_ok(user=ADMIN_USERNAME,admin=True)
    c=db(); row=c.execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?",(ident,ident)).fetchone(); c.close()
    if not row or not check_password_hash(row["password"],password): return jsonify({"ok":False,"message":"بيانات الدخول غير صحيحة"}),401
    session.clear(); session.update(user=row["username"],admin=bool(row["is_admin"])); return json_ok(user=row["username"],admin=bool(row["is_admin"]),name=row["name"],subscriptionUntil=row["subscription_until"])

@app.post("/api/auth/logout")
@app.post("/api/logout")
def logout(): session.clear(); return json_ok()

@app.get("/api/auth/me")
@app.get("/api/me")
def me(): return json_ok(user=user_name(),admin=is_admin())

@app.post("/api/admin/login")
def admin_login():
    d=request.get_json(silent=True) or {}
    if str(d.get("username","")).strip().lower()==ADMIN_USERNAME.lower() and ADMIN_PASSWORD and secrets.compare_digest(str(d.get("password","")),ADMIN_PASSWORD):
        session.clear(); session.update(user=ADMIN_USERNAME,admin=True); return json_ok(admin=True,user=ADMIN_USERNAME)
    return jsonify({"ok":False,"message":"بيانات الإدارة غير صحيحة"}),401

@app.get("/api/admin/users")
def admin_users():
    if not is_admin(): return jsonify({"ok":False,"message":"غير مصرح"}),403
    c=db(); rows=[dict(x) for x in c.execute("SELECT id,username,email,name,is_admin,subscription_until,created_at FROM users ORDER BY id DESC")]; c.close(); return json_ok(users=rows)

@app.get("/api/admin/payments")
def admin_payments():
    if not is_admin(): return jsonify({"ok":False,"message":"غير مصرح"}),403
    c=db(); rows=[dict(x) for x in c.execute("SELECT * FROM payments ORDER BY id DESC")]; c.close(); return json_ok(payments=rows)

@app.post("/api/subscription/request")
def subscription_request():
    if not user_name(): return jsonify({"ok":False,"message":"سجل دخول أولاً"}),401
    d=request.get_json(silent=True) or {}; plan=d.get("plan"); txid=str(d.get("txid","")).strip()
    if plan not in PLANS: return jsonify({"ok":False,"message":"الباقة غير صحيحة"}),400
    c=db(); c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(user_name(),plan,txid)); c.commit(); c.close()
    return json_ok(message="تم إرسال طلب الدفع للمراجعة")

@app.post("/api/admin/payment/approve")
def approve_payment():
    if not is_admin(): return jsonify({"ok":False,"message":"غير مصرح"}),403
    d=request.get_json(silent=True) or {}; pid=int(d.get("id",0)); c=db(); p=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
    if not p: c.close(); return jsonify({"ok":False,"message":"الطلب غير موجود"}),404
    until=datetime.now(timezone.utc)+timedelta(days=PLANS[p["plan"]]["days"])
    c.execute("UPDATE payments SET status='approved' WHERE id=?",(pid,)); c.execute("UPDATE users SET subscription_until=? WHERE username=?",(until.isoformat(),p["username"])); c.commit(); c.close(); return json_ok(message="تم تفعيل الاشتراك")

@app.get("/api/subscription")
def subscription_info():
    if not user_name(): return json_ok(active=False)
    c=db(); row=c.execute("SELECT subscription_until FROM users WHERE username=?",(user_name(),)).fetchone(); c.close()
    until=row["subscription_until"] if row else None
    active=False
    if until:
        try: active=datetime.fromisoformat(until).replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        except: pass
    return json_ok(active=active,until=until,plans=PLANS,payment={"trc20":TRC20_ADDRESS,"binancePay":BINANCE_PAY_ID})

init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=PORT,debug=False)
