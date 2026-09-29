import os, json, time, hmac, hashlib, urllib.parse, urllib.request, sqlite3, secrets, threading, xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

DB=os.getenv("DATABASE_PATH","site.db")
ADMIN_EMAIL=os.getenv("ADMIN_EMAIL","admin@example.com")
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","change-me-now")
SECRET_KEY=os.getenv("SESSION_SECRET","change-this-secret")
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")

app=FastAPI(title="مضارب ذكي PRO")
app.add_middleware(SessionMiddleware,secret_key=SECRET_KEY,max_age=60*60*24*30)

SCHEMA="""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,name TEXT,role TEXT DEFAULT 'user',active INTEGER DEFAULT 1,created_at TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY,user_id INTEGER,plan TEXT,days INTEGER,price REAL,status TEXT DEFAULT 'pending',created_at TEXT,expires_at TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,user_id INTEGER,plan TEXT,amount REAL,method TEXT,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT);
CREATE TABLE IF NOT EXISTS symbols(id INTEGER PRIMARY KEY,market TEXT,symbol TEXT,name TEXT,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY,market TEXT,symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp REAL,confidence REAL,change15 REAL,reason TEXT,status TEXT DEFAULT 'open',created_at TEXT);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source TEXT,published TEXT);
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,title TEXT,slug TEXT UNIQUE,body TEXT,status TEXT DEFAULT 'published',created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT);
"""
def db():
    c=sqlite3.connect(DB,check_same_thread=False); c.row_factory=sqlite3.Row
    c.executescript(SCHEMA); c.commit()
    if not c.execute("SELECT 1 FROM users WHERE email=?",(ADMIN_EMAIL,)).fetchone():
        c.execute("INSERT INTO users(email,password,name,role,created_at) VALUES(?,?,?,?,?)",(ADMIN_EMAIL,pwd.hash(ADMIN_PASSWORD),"المدير","admin",now()))
        c.commit()
    return c
def now(): return datetime.now(timezone.utc).isoformat()
def user(req):
    uid=req.session.get("uid")
    if not uid:return None
    return db().execute("SELECT * FROM users WHERE id=? AND active=1",(uid,)).fetchone()
def esc(x): return str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
def get(url,headers=None):
    r=urllib.request.Request(url,headers=headers or {"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(r,timeout=12) as x:return x.read()
def yahoo(symbol,interval="15m",range_="5d"):
    u="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?interval="+interval+"&range="+range_
    j=json.loads(get(u)); res=j["chart"]["result"][0]; q=res["indicators"]["quote"][0]
    out=[]
    for i,ts in enumerate(res["timestamp"]):
        if q["close"][i] is not None: out.append((ts,float(q["open"][i]),float(q["high"][i]),float(q["low"][i]),float(q["close"][i]),float(q["volume"][i] or 0)))
    return out
def binance(symbol,market="spot"):
    base="https://api.binance.com" if market=="spot" else "https://fapi.binance.com"
    path="/api/v3/klines" if market=="spot" else "/fapi/v1/klines"
    u=base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":"15m","limit":250})
    j=json.loads(get(u));return [(x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[7])) for x in j[:-1]]
def ema(a,n):
    if len(a)<n:return None
    e=sum(a[:n])/n;k=2/(n+1)
    for x in a[n:]:e=x*k+e*(1-k)
    return e
def rsi(a,n=14):
    if len(a)<=n:return 50
    g=[];l=[]
    for i in range(1,len(a)):
        d=a[i]-a[i-1];g.append(max(d,0));l.append(max(-d,0))
    ag=sum(g[:n])/n;al=sum(l[:n])/n
    for i in range(n,len(g)):ag=(ag*(n-1)+g[i])/n;al=(al*(n-1)+l[i])/n
    return 100 if al==0 else 100-(100/(1+ag/al))
def strategy(candles):
    if len(candles)<220:return None
    closes=[x[4] for x in candles];vol=[x[5] for x in candles];p=closes[-1]
    e20=ema(closes,20);e200=ema(closes,200);r=rsi(closes)
    avg=sum(vol[-21:-1])/20
    ch=(p-closes[-2])/closes[-2]*100
    ok=p<e20 and r<50 and p<e200 and vol[-1]>avg
    if not ok:return None
    score=70
    if ch>0:score+=15
    if vol[-1]>avg*1.5:score+=10
    if r<45:score+=5
    return {"entry":p,"tp":p*1.005,"change15":ch,"confidence":min(score,99),"reason":f"15m: تحت EMA20 وEMA200، RSI={r:.1f}، حجم أعلى من متوسط 20"}
def market_candles(m,s):
    if m in ("spot","futures","contracts"):return binance(s,"spot" if m=="spot" else "futures")
    return yahoo(s)
def scan_symbols(market):
    c=db(); rows=c.execute("SELECT symbol,name FROM symbols WHERE market=? AND active=1",(market,)).fetchall()
    results=[]
    for r in rows:
        try:
            x=strategy(market_candles(market,r["symbol"]))
            if x:results.append((x["change15"],r["symbol"],r["name"],x))
        except Exception:pass
    # positive first, then highest change among all qualifying as fallback
    pos=[x for x in results if x[0]>0]; pool=pos if pos else results
    pool.sort(key=lambda x:x[0],reverse=True)
    if pool:
        _,s,n,x=pool[0]
        c.execute("INSERT INTO signals(market,symbol,side,timeframe,entry,tp,confidence,change15,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (market,s,"BUY","15m",x["entry"],x["tp"],x["confidence"],x["change15"],x["reason"],now()))
        c.commit()
    return pool
def seed():
    c=db()
    defaults={
      "spot":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"],
      "futures":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"],
      "contracts":["BTCUSDT","ETHUSDT"],
      "american":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD"],
      "saudi":["2222.SR","2010.SR","1120.SR","1150.SR","1180.SR"],
      "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","GC=F","CL=F"]
    }
    for m,syms in defaults.items():
        for s in syms:
            if not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(m,s)).fetchone():
                c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(m,s,s))
    c.commit()
seed()

CSS="""*{box-sizing:border-box}body{margin:0;background:#07111f;color:#eef5ff;font-family:Arial,sans-serif}a{color:inherit;text-decoration:none}.wrap{max-width:1400px;margin:auto;padding:18px}.top{position:sticky;top:0;z-index:5;background:#09182b;border-bottom:1px solid #1b3554;padding:12px}.nav{display:flex;gap:8px;overflow:auto}.nav a,.btn{padding:10px 14px;border-radius:10px;background:#10233b;white-space:nowrap}.brand{font-size:22px;font-weight:800;margin-bottom:10px}.hero{padding:28px;border-radius:20px;background:linear-gradient(135deg,#102a48,#0b1829);border:1px solid #1d3b60}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.card{background:#0d1d31;border:1px solid #193554;border-radius:16px;padding:16px}.muted{color:#91a8c2}.buy{color:#39e58c}.gold{color:#f5c451}.danger{color:#ff6b78}input,textarea,select{width:100%;padding:12px;margin:6px 0;background:#07111f;color:white;border:1px solid #274666;border-radius:10px}.btn{border:0;color:white;cursor:pointer;display:inline-block}.primary{background:#1769d1}.goldbg{background:#b88417}.stat{font-size:28px;font-weight:800}.table{width:100%;border-collapse:collapse}.table td,.table th{padding:10px;border-bottom:1px solid #193554;text-align:right}.pill{display:inline-block;padding:5px 9px;border-radius:999px;background:#173455}.signal{border-right:4px solid #39e58c}.footer{padding:30px;text-align:center;color:#7e94ae}"""
def page(req,title,body):
    u=user(req); role=u["role"] if u else ""
    nav=[("الرئيسية","/"),("السبوت","/market/spot"),("الفيوتشر","/market/futures"),("العقود","/market/contracts"),("الأمريكي","/market/american"),("السعودي","/market/saudi"),("فوركس وذهب","/market/forex"),("الماسح","/scanner"),("الأخبار","/news"),("المدونة","/blog"),("الاشتراكات","/subscriptions")]
    if u:nav += [("حسابي","/account")]
    if role=="admin":nav += [("الإدارة","/admin")]
    if not u:nav += [("دخول","/login"),("تسجيل","/register")]
    n="".join(f'<a href="{x[1]}">{x[0]}</a>' for x in nav)
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | مضارب ذكي PRO</title><style>{CSS}</style><div class="top"><div class="wrap"><div class="brand">◆ مضارب ذكي <span class="gold">PRO</span></div><div class="nav">{n}</div></div></div><main class="wrap">{body}</main><div class="footer">مضارب ذكي PRO — منصة تحليل وفرز أسواق متعددة</div></html>'''
def require(req,role=None):
    u=user(req)
    if not u:return RedirectResponse("/login",303)
    if role and u["role"]!=role:return RedirectResponse("/",303)
    return u

@app.get("/",response_class=HTMLResponse)
def home(req:Request):
    c=db(); sig=c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 8").fetchall()
    cards="".join(f'<div class="card signal"><b>{esc(x["symbol"])}</b><div class="buy">شراء</div><p>دخول {x["entry"]:.4f} — هدف +0.5%</p><small>تغير 15د: {x["change15"]:.2f}% · مطابقة {x["confidence"]:.0f}%</small></div>' for x in sig)
    body=f'<section class="hero"><h1>منصة تداول متعددة الأسواق</h1><p class="muted">فلترة آلية وفق الاستراتيجية الموحدة على 15 دقيقة، ثم اختيار أقوى فرصة من المرشحين.</p><a class="btn primary" href="/scanner">ابدأ الفحص الآن</a></section><h2>آخر التوصيات</h2><div class="grid">{cards or "<div class=card>لا توجد توصيات حتى الآن — شغّل الماسح من الإدارة.</div>"}</div>'
    return page(req,"الرئيسية",body)

@app.get("/market/{market}",response_class=HTMLResponse)
def market(req:Request,market:str):
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس والذهب"}
    if market not in names:return RedirectResponse("/",303)
    c=db(); rows=c.execute("SELECT * FROM signals WHERE market=? ORDER BY id DESC LIMIT 30",(market,)).fetchall()
    body=f'<h1>{names[market]}</h1><p class="muted">15 دقيقة · شراء فقط · هدف 0.5%</p><div class="grid">'+''.join(f'<div class="card signal"><h3>{esc(x["symbol"])}</h3><span class="pill">BUY</span><p>دخول: {x["entry"]:.5f}</p><p>TP: {x["tp"]:.5f}</p><p>تغير 15د: {x["change15"]:.2f}%</p><p>مطابقة: {x["confidence"]:.0f}%</p></div>' for x in rows)+'</div>'
    return page(req,names[market],body)

@app.get("/scanner",response_class=HTMLResponse)
def scanner(req:Request):
    body='<div class="hero"><h1>🔎 الماسح الذكي</h1><p>أولاً يرشّح تغير 15 دقيقة الموجب، ثم يطبق الشروط، ثم يختار أعلى تغير. إذا لم يوجد موجب يستخدم أعلى تغير سلبي.</p><div class="grid">'+''.join(f'<a class="card" href="/market/{m}"><b>{n}</b><p class="muted">فحص الاستراتيجية الموحدة</p></a>' for m,n in [("spot","السبوت"),("futures","الفيوتشر"),("contracts","العقود"),("american","الأمريكي"),("saudi","السعودي"),("forex","الفوركس والذهب")])+'</div></div>'
    return page(req,"الماسح",body)

@app.get("/register",response_class=HTMLResponse)
def register_form(req:Request):
    return page(req,"تسجيل",'<div class="card"><h2>إنشاء حساب</h2><form method="post"><input name="name" placeholder="الاسم"><input name="email" type="email" placeholder="البريد"><input name="password" type="password" placeholder="كلمة المرور"><button class="btn primary">تسجيل</button></form></div>')
@app.post("/register")
def register(req:Request,name:str=Form(""),email:str=Form(""),password:str=Form("")):
    c=db()
    try:c.execute("INSERT INTO users(email,password,name,created_at) VALUES(?,?,?,?)",(email.lower().strip(),pwd.hash(password),name,now()));c.commit()
    except sqlite3.IntegrityError:return RedirectResponse("/register",303)
    return RedirectResponse("/login",303)
@app.get("/login",response_class=HTMLResponse)
def login_form(req:Request):
    return page(req,"دخول",'<div class="card"><h2>تسجيل الدخول</h2><form method="post"><input name="email" type="email" placeholder="البريد"><input name="password" type="password" placeholder="كلمة المرور"><button class="btn primary">دخول</button></form></div>')
@app.post("/login")
def login(req:Request,email:str=Form(""),password:str=Form("")):
    u=db().execute("SELECT * FROM users WHERE email=? AND active=1",(email.lower().strip(),)).fetchone()
    if not u or not pwd.verify(password,u["password"]):return RedirectResponse("/login",303)
    req.session["uid"]=u["id"];return RedirectResponse("/",303)
@app.get("/logout")
def logout(req:Request):req.session.clear();return RedirectResponse("/",303)
@app.get("/account",response_class=HTMLResponse)
def account(req:Request):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    c=db(); subs=c.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    body=f'<div class="card"><h2>حسابي</h2><p>{esc(u["name"] or u["email"])}</p><p>الحالة: <span class="buy">نشط</span></p><a class="btn" href="/logout">خروج</a></div><h2>الاشتراكات</h2><div class="grid">'+''.join(f'<div class="card">{esc(x["plan"])} — {x["status"]}</div>' for x in subs)+'</div>'
    return page(req,"حسابي",body)

@app.get("/subscriptions",response_class=HTMLResponse)
def subscriptions(req:Request):
    plans=[("7 أيام",7,10),("15 يوم",15,20),("30 يوم",30,30)]
    cards="".join(f'<div class="card"><h2>{p[0]}</h2><div class="stat">{p[2]} <small>USDT</small></div><p>الوصول إلى التوصيات والماسح والأسواق</p><a class="btn goldbg" href="/subscribe?days={p[1]}&price={p[2]}">طلب الاشتراك</a></div>' for p in plans)
    return page(req,"الاشتراكات",'<h1>الاشتراكات</h1><div class="grid">'+cards+'</div><p class="muted">الدفع يمر بطلب ومراجعة الإدارة قبل التفعيل.</p>')

@app.get("/subscribe",response_class=HTMLResponse)
def subscribe(req:Request,days:int,price:float):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    return page(req,"طلب اشتراك",f'<div class="card"><h2>طلب اشتراك {days} يوم</h2><form method="post"><input name="method" placeholder="طريقة الدفع"><input name="txid" placeholder="رقم العملية"><input type="hidden" name="days" value="{days}"><input type="hidden" name="price" value="{price}"><button class="btn goldbg">إرسال الطلب</button></form></div>')
@app.post("/subscribe")
def subscribe_post(req:Request,days:int=Form(...),price:float=Form(...),method:str=Form(""),txid:str=Form("")):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    c=db();c.execute("INSERT INTO payments(user_id,plan,amount,method,txid,created_at) VALUES(?,?,?,?,?,?)",(u["id"],f"{days} يوم",price,method,txid,now()));c.commit();return RedirectResponse("/account",303)

@app.get("/admin",response_class=HTMLResponse)
def admin(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db(); users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]; payments=c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"]; sig=c.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"]
    body=f'<h1>لوحة الإدارة</h1><div class="grid"><div class="card"><div class="stat">{users}</div>حسابات</div><div class="card"><div class="stat">{payments}</div>طلبات دفع معلقة</div><div class="card"><div class="stat">{sig}</div>توصيات</div></div><div class="card"><h2>تشغيل الفحص</h2><form method="post" action="/admin/scan"><button class="btn primary">فحص جميع الأسواق الآن</button></form></div><div class="card"><h2>إضافة رمز للسكانر</h2><form method="post" action="/admin/symbol"><select name="market"><option>spot</option><option>futures</option><option>contracts</option><option>american</option><option>saudi</option><option>forex</option></select><input name="symbol" placeholder="رمز السوق"><button class="btn">إضافة</button></form></div><div class="card"><a class="btn" href="/admin/payments">إدارة المدفوعات</a></div>'
    return page(req,"الإدارة",body)
@app.post("/admin/scan")
def admin_scan(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    for m in ["spot","futures","contracts","american","saudi","forex"]:
        try:scan_symbols(m)
        except Exception:pass
    return RedirectResponse("/admin",303)
@app.post("/admin/symbol")
def admin_symbol(req:Request,market:str=Form(...),symbol:str=Form(...)):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db();c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(market,symbol.strip().upper(),symbol.strip().upper()));c.commit();return RedirectResponse("/admin",303)
@app.get("/admin/payments",response_class=HTMLResponse)
def payments(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    rows=db().execute("SELECT p.*,u.email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC").fetchall()
    body='<div class="card"><h1>المدفوعات</h1><table class="table"><tr><th>المستخدم</th><th>الخطة</th><th>المبلغ</th><th>الحالة</th><th></th></tr>'+''.join(f'<tr><td>{esc(x["email"])}</td><td>{x["plan"]}</td><td>{x["amount"]}</td><td>{x["status"]}</td><td><a class="btn" href="/admin/payment/{x["id"]}/approve">اعتماد</a></td></tr>' for x in rows)+'</table></div>'
    return page(req,"المدفوعات",body)
@app.get("/admin/payment/{pid}/approve")
def approve(req:Request,pid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db();p=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
    if p:
        c.execute("UPDATE payments SET status='approved' WHERE id=?",(pid,))
        days=int(str(p["plan"]).split()[0]);c.execute("INSERT INTO subscriptions(user_id,plan,days,price,status,created_at) VALUES(?,?,?,?,?,?)",(p["user_id"],p["plan"],days,p["amount"],"active",now()));c.commit()
    return RedirectResponse("/admin/payments",303)

@app.get("/news",response_class=HTMLResponse)
def news(req:Request):
    c=db();rows=c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 30").fetchall()
    body='<h1>📰 الأخبار</h1><div class="grid">'+''.join(f'<a class="card" href="{esc(x["url"])}"><h3>{esc(x["title"])}</h3><p class="muted">{esc(x["source"])}</p></a>' for x in rows)+'</div>'
    return page(req,"الأخبار",body)
@app.get("/blog",response_class=HTMLResponse)
def blog(req:Request):
    rows=db().execute("SELECT * FROM posts WHERE status='published' ORDER BY id DESC").fetchall()
    body='<h1>✎ المدونة</h1><div class="grid">'+''.join(f'<a class="card" href="/blog/{esc(x["slug"])}"><h2>{esc(x["title"])}</h2><p class="muted">{esc(x["created_at"])}</p></a>' for x in rows)+'</div>'
    return page(req,"المدونة",body)
@app.get("/blog/{slug}",response_class=HTMLResponse)
def article(req:Request,slug:str):
    x=db().execute("SELECT * FROM posts WHERE slug=? AND status='published'",(slug,)).fetchone()
    if not x:return RedirectResponse("/blog",303)
    return page(req,x["title"],f'<article class="card"><h1>{esc(x["title"])}</h1><div>{esc(x["body"]).replace(chr(10),"<br>")}</div></article>')

def news_loop():
    while True:
        try:
            xml=get("https://feeds.bbci.co.uk/arabic/rss.xml");root=ET.fromstring(xml)
            c=db()
            for item in root.findall(".//item")[:20]:
                t=item.findtext("title") or "";u=item.findtext("link") or "";d=item.findtext("pubDate") or ""
                if t and not c.execute("SELECT 1 FROM news WHERE url=?",(u,)).fetchone():c.execute("INSERT INTO news(title,url,source,published) VALUES(?,?,?,?)",(t,u,"BBC عربي",d))
            c.commit()
        except Exception:pass
        time.sleep(900)
def scan_loop():
    while True:
        for m in ["spot","futures","contracts","american","saudi","forex"]:
            try:scan_symbols(m)
            except Exception:pass
        time.sleep(int(os.getenv("SCAN_SECONDS","900")))
@app.on_event("startup")
def startup():
    db()
    threading.Thread(target=news_loop,daemon=True).start()
    threading.Thread(target=scan_loop,daemon=True).start()
@app.get("/health")
def health():return {"ok":True,"service":"mudarib-smart-pro","time":now()}
if __name__=="__main__":
    import uvicorn;uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
