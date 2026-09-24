import os, sqlite3, secrets, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from ai_engine import analyze as ai_analyze

app=Flask(__name__,template_folder="templates",static_folder=None)
app.secret_key=os.getenv("SECRET_KEY",secrets.token_hex(32))
STATIC_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),"static")

@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename, max_age=0)
DB=os.getenv("SQLITE_FILE","mudarib.db")
ADMIN_USERNAME=os.getenv("ADMIN_USERNAME","aaaksazzz").strip()
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","").strip()
TRC20_ADDRESS=os.getenv("TRC20_ADDRESS","").strip()
BINANCE_PAY_ID=os.getenv("BINANCE_PAY_ID","").strip()
PLANS={"7d":{"name":"7 أيام","days":7,"amount":10},"30d":{"name":"30 يوم","days":30,"amount":20},"90d":{"name":"90 يوم","days":90,"amount":30}}
MARKETS={
"saudi":[("2222.SR","أرامكو"),("2010.SR","سابك"),("1120.SR","الراجحي"),("1180.SR","الأهلي السعودي"),("1150.SR","مصرف الإنماء"),("7010.SR","STC"),("1211.SR","معادن"),("2380.SR","بترو رابغ"),("4003.SR","إكسترا"),("4200.SR","الدريس")],
"usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("GOOGL","Alphabet"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],
"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("XAUUSD=X","Gold")]
}
HTTP=requests.Session();HTTP.headers.update({"User-Agent":"Mudarib-Abo-Saud/7.0"})

def db():
 c=sqlite3.connect(DB,timeout=20,check_same_thread=False);c.row_factory=sqlite3.Row;return c
def init_db():
 c=db();c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL,plan TEXT NOT NULL,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);""");c.commit();c.close()
def ok(**x): return jsonify({"ok":True,**x})
def fail(msg,code=400): return jsonify({"ok":False,"message":msg}),code
def current_user():
 u=session.get("user")
 if not u:return None
 c=db();r=c.execute("SELECT * FROM users WHERE username=?",(u,)).fetchone();c.close();return r
def require_admin():
 return bool(session.get("admin"))
def yahoo(symbol,interval="1d",range_="3mo"):
 r=HTTP.get("https://query1.finance.yahoo.com/v8/finance/chart/"+symbol,params={"interval":interval,"range":range_},timeout=12);r.raise_for_status();z=r.json()["chart"]["result"][0];q=z["indicators"]["quote"][0];ts=z.get("timestamp",[]);out=[]
 for i,t in enumerate(ts):
  try:out.append({"time":t,"open":float(q["open"][i]),"high":float(q["high"][i]),"low":float(q["low"][i]),"close":float(q["close"][i]),"volume":float((q.get("volume") or [0]*len(ts))[i] or 0)})
  except:pass
 return out
def okx_candles(inst,bar="15m",limit=100):
 r=HTTP.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":limit},timeout=12);r.raise_for_status();out=[]
 for x in reversed(r.json().get("data",[])):
  try:out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
  except:pass
 return out
def analyze(candles,symbol,market,interval):
 if len(candles)<70:return None
 norm=[]
 for x in candles:
  try:norm.append({"t":x["time"],"o":float(x["open"]),"h":float(x["high"]),"l":float(x["low"]),"c":float(x["close"]),"v":float(x.get("volume",0) or 0)})
  except:pass
 return ai_analyze(norm,symbol,market,interval) if len(norm)>=70 else None
def okx_scan(market,interval):
 bar={"5m":"5m","15m":"15m","30m":"30m","1H":"1H","4H":"4H","1D":"1D"}.get(interval,"15m")
 r=HTTP.get("https://www.okx.com/api/v5/market/tickers",params={"instType":"SPOT" if market=="crypto" else "SWAP"},timeout=12);r.raise_for_status();items=r.json().get("data",[])
 if market=="crypto":items=[x for x in items if x.get("instId","").endswith("-USDT")][:18]
 else:items=[x for x in items if x.get("instId","").endswith("-USDT-SWAP")][:18]
 results=[]
 with ThreadPoolExecutor(max_workers=6) as ex:
  futs={ex.submit(okx_candles,x["instId"],bar,100):x["instId"] for x in items}
  for f in as_completed(futs):
   try:
    inst=futs[f];a=analyze(f.result(),inst.replace("-",""),market,interval)
    if a:results.append(a)
   except:pass
 return sorted(results,key=lambda x:float(x.get("confidence",0)),reverse=True)[:20]
def yahoo_scan(market,interval):
 symbols=MARKETS.get(market,[])
 yi={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d"}.get(interval,"1d")
 yr={"5m":"5d","15m":"1mo","30m":"1mo","1h":"3mo","1d":"1y"}
 results=[]
 with ThreadPoolExecutor(max_workers=5) as ex:
  futs={ex.submit(yahoo,s,yi,yr.get(yi,"3mo")):(s,nm) for s,nm in symbols}
  for f in as_completed(futs):
   s,nm=futs[f]
   try:
    a=analyze(f.result(),s,market,interval)
    if a:a["displayName"]=nm;results.append(a)
   except:pass
 return sorted(results,key=lambda x:float(x.get("confidence",0)),reverse=True)
@app.get("/")
def home_page():return render_template("index.html",page_id="dashboard",page_title="الرئيسية — ذكاء التداول")
@app.get("/<page>")
def page(page):
 mp={"spot":"spot","futures":"futures","contracts":"contracts","scanner":"scanner","saudi":"saudi","usmarket":"usmarket","forex":"forex","news":"news","subscription":"subscription"}
 if page=="login":return render_template("login.html")
 if page=="register":return render_template("register.html")
 if page=="admin":return render_template("admin.html")
 if page in mp:return render_template(mp[page]+".html",page_id=page,page_title=page)
 return ("غير موجود",404)
@app.get("/api/ai/signals")
def signals():
 market=request.args.get("market","crypto");interval=request.args.get("interval","15m")
 try:
  limit=min(max(int(request.args.get("limit",20)),1),20)
  if market=="crypto":rs=okx_scan("crypto",interval)
  elif market in MARKETS:rs=yahoo_scan(market,interval)
  elif market=="futures":rs=okx_scan("futures",interval)
  else:return fail("السوق غير معروف")
  return ok(results=rs[:limit],market=market,interval=interval,updatedAt=datetime.now(timezone.utc).isoformat())
 except Exception as e:return fail("تعذر جلب بيانات السوق: "+str(e),502)
@app.post("/api/auth/register")
def register():
 d=request.get_json(silent=True) or {};name=str(d.get("name","")).strip();email=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 if not name or not email or len(pw)<6:return fail("أدخل الاسم والبريد وكلمة مرور 6 أحرف على الأقل")
 username=email.split("@")[0][:30]
 c=db()
 try:
  c.execute("INSERT INTO users(username,email,name,password) VALUES(?,?,?,?)",(username,email,name,generate_password_hash(pw)));c.commit()
 except sqlite3.IntegrityError:return c.close() or fail("البريد مستخدم مسبقاً")
 c.close();session["user"]=username;session["admin"]=False;return ok(user=username)
@app.post("/api/auth/login")
def login():
 d=request.get_json(silent=True) or {};identity=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 c=db();u=c.execute("SELECT * FROM users WHERE email=? OR username=?",(identity,identity)).fetchone();c.close()
 if not u or not check_password_hash(u["password"],pw):return fail("بيانات الدخول غير صحيحة",401)
 session["user"]=u["username"];session["admin"]=bool(u["is_admin"]);return ok(user=u["username"],admin=bool(u["is_admin"]))
@app.get("/api/me")
def me():
 u=current_user();return ok(user=dict(u) if u else None,admin=require_admin())
@app.post("/api/admin/login")
def admin_login():
 d=request.get_json(silent=True) or {}
 if d.get("username","").strip()==ADMIN_USERNAME and ADMIN_PASSWORD and d.get("password","")==ADMIN_PASSWORD:session["admin"]=True;session["user"]=ADMIN_USERNAME;return ok()
 return fail("بيانات الإدارة غير صحيحة",401)
@app.post("/api/admin/logout")
def admin_logout():session.clear();return ok()
@app.get("/api/subscription")
def subscription():return ok(plans=PLANS,payment={"trc20":TRC20_ADDRESS,"binancePay":BINANCE_PAY_ID})
@app.post("/api/subscription/request")
def sub_request():
 u=current_user()
 if not u:return fail("سجل الدخول أولاً",401)
 d=request.get_json(silent=True) or {};plan=d.get("plan");txid=str(d.get("txid","")).strip()
 if plan not in PLANS or not txid:return fail("اختر الباقة وأدخل رقم العملية")
 c=db();c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(u["username"],plan,txid));c.commit();c.close();return ok()
@app.get("/api/news")
def news_api():
 c=db()
 try:
  c.execute("CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,content TEXT NOT NULL,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
  rows=[dict(x) for x in c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 50").fetchall()];c.commit()
 finally:c.close()
 return ok(news=rows)
@app.get("/api/admin/stats")
def admin_stats():
 if not require_admin():return fail("غير مصرح",403)
 c=db();u=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"];p=c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"];a=c.execute("SELECT COUNT(*) n FROM users WHERE subscription_until IS NOT NULL AND subscription_until>?",(datetime.now(timezone.utc).isoformat(),)).fetchone()["n"];c.close();return ok(users=u,active_subscriptions=a,pending_payments=p,revenue=0)
@app.get("/api/admin/users")
def admin_users():
 if not require_admin():return fail("غير مصرح",403)
 c=db();rows=[dict(x) for x in c.execute("SELECT id,username,email,name,subscription_until,created_at FROM users ORDER BY id DESC").fetchall()];c.close();return ok(users=rows)
@app.get("/api/admin/payments")
def admin_payments():
 if not require_admin():return fail("غير مصرح",403)
 c=db();rows=[dict(x) for x in c.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()];c.close();return ok(payments=rows)
@app.post("/api/admin/payments/approve")
def approve():
 if not require_admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};pid=d.get("id")
 c=db();p=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
 if not p:c.close();return fail("طلب الدفع غير موجود",404)
 plan=PLANS.get(p["plan"])
 u=c.execute("SELECT * FROM users WHERE username=?",(p["username"],)).fetchone()
 base=datetime.now(timezone.utc)
 if u and u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=plan["days"])).isoformat()
 c.execute("UPDATE users SET subscription_until=? WHERE username=?",(until,p["username"]));c.execute("UPDATE payments SET status='approved' WHERE id=?",(pid,));c.commit();c.close();return ok()
@app.post("/api/admin/payments/reject")
def reject():
 if not require_admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=db();c.execute("UPDATE payments SET status='rejected' WHERE id=?",(d.get("id"),));c.commit();c.close();return ok()
@app.post("/api/admin/users/subscription")
def user_subscription():
 if not require_admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=db();u=c.execute("SELECT * FROM users WHERE id=?",(d.get("id"),)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 if d.get("cancel"):until=None
 else:
  base=datetime.now(timezone.utc)
  if u["subscription_until"]:
   try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
   except:pass
  until=(base+timedelta(days=max(0,int(d.get("days",0))))).isoformat()
 c.execute("UPDATE users SET subscription_until=? WHERE id=?",(until,u["id"]));c.commit();c.close();return ok()
@app.post("/api/admin/news")
def add_news():
 if not require_admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};title=str(d.get("title","")).strip();content=str(d.get("content","")).strip()
 if not title or not content:return fail("العنوان والمحتوى مطلوبان")
 c=db();c.execute("CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,content TEXT NOT NULL,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)");c.execute("INSERT INTO news(title,content,source) VALUES(?,?,?)",(title,content,d.get("source","")));c.commit();c.close();return ok()
@app.get("/health")
def health():return ok(status="healthy",time=datetime.now(timezone.utc).isoformat())
init_db()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
