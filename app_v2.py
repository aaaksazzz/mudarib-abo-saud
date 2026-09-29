import os, json, time, hmac, hashlib, urllib.parse, urllib.request, sqlite3, secrets, threading, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
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
pwd=CryptContext(schemes=["pbkdf2_sha256"],deprecated="auto")

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
# ---------- MARKET DATA ENGINE ----------
CACHE_TTL=int(os.getenv("DATA_CACHE_TTL","45"))
# كثافة جمع البيانات: كل سوق مقسم إلى دفعات، وكل دفعة تعمل عبر عمال مستقلين.
# لا نفحص آلاف الرموز دفعة واحدة حتى لا يتوقف مصدر البيانات أو يصطدم بالـrate limits.
MARKET_WORKERS={"spot":int(os.getenv("SPOT_DATA_WORKERS","12")),"futures":int(os.getenv("FUTURES_DATA_WORKERS","12")),"contracts":int(os.getenv("CONTRACTS_DATA_WORKERS","8")),"american":int(os.getenv("US_DATA_WORKERS","10")),"saudi":int(os.getenv("SAUDI_DATA_WORKERS","8")),"forex":int(os.getenv("FOREX_DATA_WORKERS","8"))}
MARKET_BATCH_SIZE={"spot":int(os.getenv("SPOT_BATCH_SIZE","15")),"futures":int(os.getenv("FUTURES_BATCH_SIZE","15")),"contracts":int(os.getenv("CONTRACTS_BATCH_SIZE","10")),"american":int(os.getenv("US_BATCH_SIZE","10")),"saudi":int(os.getenv("SAUDI_BATCH_SIZE","10")),"forex":int(os.getenv("FOREX_BATCH_SIZE","8"))}
BATCH_PAUSE=float(os.getenv("DATA_BATCH_PAUSE","0.20"))
_SOURCE_ROUND=0
_SOURCE_LOCK=threading.Lock()
_DATA_CACHE={}; _CACHE_LOCK=threading.Lock()
def cached_get_json(url,ttl=CACHE_TTL):
    t=time.time()
    with _CACHE_LOCK:
        h=_DATA_CACHE.get(url)
        if h and t-h[0]<ttl:return h[1]
    d=json.loads(get(url))
    with _CACHE_LOCK:_DATA_CACHE[url]=(t,d)
    return d
def yahoo(symbol,interval="15m",range_="5d"):
    u="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode({"interval":interval,"range":range_})
    j=cached_get_json(u);r=j["chart"]["result"][0];q=r["indicators"]["quote"][0];out=[]
    for i,ts in enumerate(r.get("timestamp",[])):
        if q["close"][i] is not None:out.append((ts,float(q["open"][i]),float(q["high"][i]),float(q["low"][i]),float(q["close"][i]),float(q["volume"][i] or 0)))
    return out
def binance(symbol,market="spot"):
    base="https://api.binance.com" if market=="spot" else "https://fapi.binance.com";path="/api/v3/klines" if market=="spot" else "/fapi/v1/klines"
    j=cached_get_json(base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":"15m","limit":250}))
    return [(x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[7])) for x in j[:-1]]
def binance_24h(market):
    base="https://api.binance.com" if market=="spot" else "https://fapi.binance.com";path="/api/v3/ticker/24hr" if market=="spot" else "/fapi/v1/ticker/24hr"
    return {x["symbol"]:x for x in cached_get_json(base+path) if x.get("symbol","").endswith("USDT")}
def contracts(symbol):
    j=cached_get_json("https://dapi.binance.com/dapi/v1/klines?"+urllib.parse.urlencode({"symbol":symbol,"interval":"15m","limit":250}))
    return [(x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[7])) for x in j[:-1]]
def market_candles(m,s):
    if m=="spot":return binance(s,"spot")
    if m=="futures":return binance(s,"futures")
    if m=="contracts":return contracts(s)
    return yahoo(s)
def strategy(candles):
    if len(candles)<220:return None
    closes=[x[4] for x in candles];vol=[x[5] for x in candles];p=closes[-1];e20=ema(closes,20);e200=ema(closes,200);r=rsi(closes);avg=sum(vol[-21:-1])/20;ch=(p-closes[-2])/closes[-2]*100
    if not(p<e20 and r<50 and p<e200 and vol[-1]>avg):return None
    score=70+(15 if ch>0 else 0)+(10 if vol[-1]>avg*1.5 else 0)+(5 if r<45 else 0)
    return {"entry":p,"tp":p*1.005,"change15":ch,"confidence":min(score,99),"reason":f"15m: تحت EMA20 وEMA200، RSI={r:.1f}، حجم أعلى من متوسط 20"}
def _scan_one(a):
    m,s,name=a
    try:
        x=strategy(market_candles(m,s))
        return (x["change15"],s,name,x) if x else None
    except Exception:return None

def _chunks(items,size):
    for i in range(0,len(items),max(1,size)):
        yield items[i:i+max(1,size)]

def _scan_batch(market,batch,workers):
    results=[]
    # كل دفعة لها "سرفز" منطقي مستقل: pool خاص ثم ينتقل للدفعة التالية.
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix=f"{market}-srv") as pool:
        futures=[pool.submit(_scan_one,x) for x in batch]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x:results.append(x)
            except Exception:
                continue
    return results

def scan_symbols(market):
    global _SOURCE_ROUND
    c=db()
    rows=c.execute("SELECT symbol,name FROM symbols WHERE market=? AND active=1",(market,)).fetchall()
    candidates=[(market,r["symbol"],r["name"]) for r in rows]
    if market in ("spot","futures"):
        try:
            t=binance_24h(market)
            # الفرز الأولي: الموجب أولاً، والحجم فوق مليون USDT.
            candidates=[x for x in candidates if x[1] in t and float(t[x[1]].get("quoteVolume",0))>=1000000]
            candidates.sort(key=lambda x: float(t.get(x[1],{}).get("priceChangePercent",0)),reverse=True)
        except Exception:
            pass
    batch_size=max(1,MARKET_BATCH_SIZE.get(market,25))
    workers=max(1,MARKET_WORKERS.get(market,8))
    results=[]
    batches=list(_chunks(candidates,batch_size))
    # تدوير نقطة البداية بين الدفعات حتى لا يبقى نفس الجزء عالقاً في الخلف.
    with _SOURCE_LOCK:
        offset=_SOURCE_ROUND % len(batches) if batches else 0
        _SOURCE_ROUND += 1
    ordered=batches[offset:]+batches[:offset]
    for idx,batch in enumerate(ordered,1):
        results.extend(_scan_batch(market,batch,workers))
        if idx < len(ordered):
            time.sleep(BATCH_PAUSE)
    pos=sorted([x for x in results if x[0]>0],key=lambda x:x[0],reverse=True)
    neg=sorted([x for x in results if x[0]<=0],key=lambda x:x[0],reverse=True)
    ranked=(pos or neg)[:20]
    if ranked:
        c.execute("UPDATE signals SET status='archived' WHERE market=? AND status='open'",(market,))
        for rank,(ch,s,name,x) in enumerate(ranked,1):
            c.execute("INSERT INTO signals(market,symbol,side,timeframe,entry,tp,confidence,change15,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'open',?)",(market,s,"BUY","15m",x["entry"],x["tp"],x["confidence"],ch,f"الترتيب #{rank} · {x['reason']}",now()))
        c.commit()
    return ranked
def scan_all_markets():
    # كل سوق مستقل؛ تعطل دفعة/مزود لا يمنع بقية الأسواق من إكمال الجولة.
    out={}
    markets=("spot","futures","contracts","american","saudi","forex")
    for m in markets:
        try:
            out[m]=scan_symbols(m)
        except Exception:
            out[m]=[]
    return out
def seed():
    c=db()
    defaults={
      "american":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","AVGO","NFLX","JPM","WMT","COST","ORCL","CRM","INTC","QCOM","MU"],
      "saudi":["2222.SR","2010.SR","1120.SR","1150.SR","1180.SR","1211.SR","7010.SR","7020.SR","2380.SR","4030.SR"],
      "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","GBPJPY=X","AUDUSD=X","USDCAD=X","GC=F","SI=F","CL=F"]
    }
    for m,syms in defaults.items():
        for s in syms:
            if not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(m,s)).fetchone():
                c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(m,s,s))
    # Refresh Binance universes from exchange metadata.
    for m,base in [("spot","https://api.binance.com/api/v3/exchangeInfo"),("futures","https://fapi.binance.com/fapi/v1/exchangeInfo")]:
        try:
            data=json.loads(get(base))
            for x in data.get("symbols",[]):
                if x.get("status")!="TRADING" or x.get("quoteAsset")!="USDT": continue
                if m=="futures" and x.get("contractType")!="PERPETUAL": continue
                s=x.get("symbol")
                if s and not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(m,s)).fetchone():
                    c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(m,s,s))
        except Exception: pass
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
    sig=db().execute("SELECT * FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 12").fetchall()
    def medal(i):return "👑" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else f"#{i}"))
    cards="".join(f'<div class="card signal"><div class="gold">{medal(i)}</div><h3>{esc(x["symbol"])}</h3><div class="buy">شراء</div><p>دخول {x["entry"]:.6g} · TP +0.5%</p><p>تغير 15د: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(sig,1))
    body=f'<section class="hero"><h1>مضارب ذكي <span class="gold">PRO</span></h1><p class="muted">محرك بيانات متعدد الأسواق · فلترة · استراتيجية 15 دقيقة · ترتيب حسب أقوى تغير.</p><a class="btn primary" href="/scanner">🔎 ابدأ الفحص</a></section><h2>🏆 أفضل الفرص الآن</h2><div class="grid">{cards or "<div class=card>جاري جمع البيانات من محركات الأسواق...</div>"}</div>'
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
    rows=db().execute("SELECT market,symbol,side,timeframe,entry,tp,confidence,change15,created_at FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100").fetchall()
    names={"spot":"₿ السبوت","futures":"↕ الفيوتشر","contracts":"◫ العقود","american":"🇺🇸 الأمريكي","saudi":"🇸🇦 السعودي","forex":"💱 الفوركس والذهب"}
    cards="".join(f'<div class="card signal"><div class="gold"><b>#{i}</b> · {names.get(x["market"],x["market"])}</div><h3>{esc(x["symbol"])}</h3><div class="buy">BUY</div><p>دخول {x["entry"]:.6g} · TP +0.5%</p><p>تغير 15د: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(rows,1))
    return page(req,"الماسح",f'<div class="hero"><h1>🔎 الماسح الذكي</h1><p>كل سوق له محرك بيانات مستقل وعمّال متوازون. الترتيب يبدأ بأعلى تغير ثم شروط الاستراتيجية.</p></div><div class="grid">{cards}</div>')
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
    scan_all_markets()
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
    body='<h1>📰 الأخبار</h1><p class="muted">أخبار محفوظة داخل المنصة وتظهر كصفحات مستقلة.</p><div class="grid">'+''.join(f'<a class="card" href="/news/{x["id"]}"><h3>{esc(x["title"])}</h3><p class="muted">{esc(x["source"])} · {esc(x["published"])}</p></a>' for x in rows)+'</div>'
    return page(req,"الأخبار",body)

@app.get("/news/{nid}",response_class=HTMLResponse)
def news_article(req:Request,nid:int):
    x=db().execute("SELECT * FROM news WHERE id=?",(nid,)).fetchone()
    if not x:return RedirectResponse("/news",303)
    body=f'<article class="card"><h1>{esc(x["title"])}</h1><p class="muted">{esc(x["source"])} · {esc(x["published"])}</p><p>خبر سوقي محفوظ في قاعدة المنصة. المصدر: {esc(x["source"])}.</p><a class="btn" href="/news">رجوع للأخبار</a></article>'
    return page(req,"خبر",body)
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
        try:scan_all_markets()
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
