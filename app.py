import hashlib
import hmac
import os
import secrets
import sqlite3
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE=Path(__file__).resolve().parent
DATA_DIR=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA_DIR.mkdir(parents=True,exist_ok=True)
except PermissionError:
    DATA_DIR=BASE/"data"; DATA_DIR.mkdir(parents=True,exist_ok=True)
DB_PATH=DATA_DIR/"app.db"
SECRET=os.getenv("SESSION_SECRET") or secrets.token_hex(32)
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود الأمريكية","us":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس"}
TIMEFRAMES=["15m","30m","1h","4h","1d","1w","1M"]

app=FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware,secret_key=SECRET,max_age=60*60*24*14)
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,timeframe TEXT NOT NULL,change_pct REAL NOT NULL DEFAULT 0,profit_pct REAL,loss_pct REAL,ai_pct REAL,tag TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT NOT NULL,email TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)
    c.commit(); c.close()

def password_hash(password:str,salt:Optional[str]=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000)
    return salt+"$"+digest.hex()

def password_ok(password,stored):
    try:
        salt,expected=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000).hex()
        return hmac.compare_digest(actual,expected)
    except ValueError: return False

def current_user(request:Request):
    uid=request.session.get("user_id")
    if not uid:return None
    c=db(); row=c.execute("SELECT id,name,email,is_admin FROM users WHERE id=?",(uid,)).fetchone(); c.close()
    return dict(row) if row else None

def page(request:Request,title:str):
    user=current_user(request)
    html=(BASE/"static"/"index.html").read_text(encoding="utf-8")
    boot="<script>window.__PAGE_TITLE__="+repr(title)+";window.__USER__="+repr(user)+";</script>"
    return HTMLResponse(html.replace("</head>",boot+"</head>"))

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok","service":"trading-pro"}

@app.get("/",response_class=HTMLResponse)
def home(request:Request): return page(request,"الرئيسية")

@app.get("/market/{market}",response_class=HTMLResponse)
def market_page(request:Request,market:str):
    return page(request,MARKETS[market]) if market in MARKETS else RedirectResponse("/",status_code=303)

@app.get("/blog",response_class=HTMLResponse)
def blog(request:Request): return page(request,"المدونة")

@app.get("/forum",response_class=HTMLResponse)
def forum(request:Request): return RedirectResponse("/blog",status_code=303)

@app.get("/account",response_class=HTMLResponse)
def account(request:Request): return page(request,"حسابي")

@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request):
    u=current_user(request)
    return page(request,"الإدارة") if u and u["is_admin"] else RedirectResponse("/account",status_code=303)

@app.post("/api/register")
def register(request:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...)):
    name=name.strip(); email=email.strip().lower()
    if len(name)<2 or len(password)<6 or "@" not in email:
        return JSONResponse({"ok":False,"message":"تحقق من البيانات وكلمة المرور 6 أحرف على الأقل"},status_code=400)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,?)",(name,email,password_hash(password),1 if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]==0 else 0)); c.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError:
        c.close(); return JSONResponse({"ok":False,"message":"البريد مستخدم مسبقاً"},status_code=409)
    c.close(); request.session["user_id"]=uid
    return {"ok":True,"message":"تم إنشاء الحساب"}

@app.post("/api/login")
def login(request:Request,email:str=Form(...),password:str=Form(...)):
    c=db(); row=c.execute("SELECT * FROM users WHERE email=?",(email.strip().lower(),)).fetchone(); c.close()
    if not row or not password_ok(password,row["password_hash"]):
        return JSONResponse({"ok":False,"message":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
    request.session["user_id"]=row["id"]; return {"ok":True,"message":"تم تسجيل الدخول"}

@app.post("/api/logout")
def logout(request:Request): request.session.clear(); return {"ok":True}

@app.get("/api/me")
def me(request:Request): return {"user":current_user(request)}

@app.get("/api/message")
def active_message():
    c=db(); row=c.execute("SELECT id,title,body FROM messages WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone(); c.close()
    return {"message":dict(row) if row else None}

@app.get("/api/trades/{market}")
def trades(market:str,timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    c=db()
    rows=c.execute("""SELECT id,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl,status,created_at
    FROM trades WHERE market=? AND timeframe=? AND status='open'
    ORDER BY change_pct DESC,COALESCE(ai_pct,0) DESC,id ASC""",(market,timeframe)).fetchall()
    c.close(); out=[]
    for rank,row in enumerate(rows,1):
        x=dict(row); x["rank"]=rank; x["medal"]="🥇" if rank==1 else "🥈" if rank==2 else "🥉" if rank==3 else ""; out.append(x)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"trades":out}

@app.post("/api/support")
def support(request:Request,name:str=Form(...),email:str=Form(...),body:str=Form(...)):
    u=current_user(request); c=db()
    c.execute("INSERT INTO support_messages(user_id,name,email,body) VALUES(?,?,?,?)",(u["id"] if u else None,name.strip(),email.strip().lower(),body.strip()))
    c.commit(); c.close(); return {"ok":True,"message":"تم إرسال رسالتك للدعم"}


# ===== Strategy engine: Spot BUY =====
def _binance_json(url, timeout=4):
    req=urllib.request.Request(url, headers={"User-Agent":"mudarib-pro/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def _ema(values, period):
    if len(values) < period: return None
    k=2/(period+1); e=sum(values[:period])/period
    for v in values[period:]: e=(v*k)+(e*(1-k))
    return e

def _rsi(values, period=14):
    if len(values) < period+1: return None
    gains=[]; losses=[]
    for a,b in zip(values[-period-1:-1], values[-period:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/period; al=sum(losses)/period
    if al==0: return 100.0
    return 100-(100/(1+(ag/al)))

def _scan_spot_strategy(timeframe="15m", limit_symbols=30):
    if timeframe not in {"15m","30m","1h","4h","1d","1w","1M"}: return []
    tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr")
    candidates=[]
    for t in tickers:
        s=t.get("symbol","")
        if not s.endswith("USDT") or s.endswith(("USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT")): continue
        try:
            q=float(t.get("quoteVolume",0))
            if q>=1_000_000: candidates.append((q,s))
        except: pass
    candidates=sorted(candidates,reverse=True)[:limit_symbols]
    def scan_one(item):
        _,symbol=item
        p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":260})
        klines=_binance_json("https://api.binance.com/api/v3/klines?"+p,timeout=4)
        closes=[float(x[4]) for x in klines]; lows=[float(x[3]) for x in klines]
        price=closes[-1]; ema20=_ema(closes,20); ema200=_ema(closes,200); rsi=_rsi(closes)
        if None in (ema20,ema200,rsi) or not (price < ema20 and price < ema200 and rsi < 50): return None
        sl=min(lows[-20:]); risk=price-sl
        if risk<=0 or risk/price>0.08: return None
        change=(price-closes[-2])/closes[-2]*100
        if abs(change)<=1: return None
        tp1=price+risk; tp2=price+risk*2; tp3=price+risk*3
        ai=max(50,min(99,50+(50-rsi)*0.8+(ema20-price)/price*500))
        return {"symbol":symbol,"side":"BUY","timeframe":timeframe,"change_pct":change,"profit_pct":risk/price*100*2,"loss_pct":risk/price*100,"ai_pct":ai,"tag":"استراتيجية "+timeframe,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"status":"open"}
    found=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures=[pool.submit(scan_one,item) for item in candidates]
        for future in as_completed(futures):
            try:
                row=future.result(timeout=0.2)
                if row: found.append(row)
            except Exception: pass
    return sorted([x for x in found if abs(float(x.get("change_pct",0))) > 1],key=lambda x:(abs(x["change_pct"]),x["ai_pct"]),reverse=True)[:20]

@app.get("/api/strategy/scan")
def strategy_scan(market:str="spot",timeframe:str="15m"):
    if market!="spot":
        return {"market":market,"timeframe":timeframe,"trades":[],"message":"المحرك الحالي مطبق للسبوت فقط"}
    try:
        rows=_scan_spot_strategy(timeframe)
        return {"market":"spot","market_name":MARKETS["spot"],"timeframe":timeframe,
                "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)


# ===== Multi-market live strategy engines =====
MARKET_RULES={
    "spot":{"sides":["BUY"],"source":"spot"},
    "futures":{"sides":["BUY","SELL"],"source":"futures"},
    "contracts":{"sides":["BUY","SELL"],"source":"yahoo"},
    "us":{"sides":["BUY"],"source":"yahoo"},
    "saudi":{"sides":["BUY"],"source":"yahoo"},
    "forex":{"sides":["BUY","SELL"],"source":"yahoo"},
}
FOREX_SYMBOLS=["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X"]
US_CONTRACT_SYMBOLS=["ES=F","NQ=F","YM=F","RTY=F","GC=F","SI=F","CL=F","NG=F","ZB=F","ZN=F"]
US_SYMBOLS=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","JPM","V","WMT","COST","ORCL"]
# Tadawul symbols are Yahoo-style 1180.SR etc.; keep a liquid core and allow expansion.
SAUDI_SYMBOLS=["2222.SR","1120.SR","1180.SR","2010.SR","7010.SR","7020.SR","1211.SR","2050.SR","2280.SR","1150.SR","1050.SR","1060.SR"]

def _yahoo_chart(symbol, interval="15m", range_="60d"):
    q=urllib.parse.quote(symbol,safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval={interval}&range={range_}"
    d=_binance_json(url)
    r=d.get("chart",{}).get("result") or []
    if not r: return []
    rr=r[0]; ts=rr.get("timestamp") or []; qd=rr.get("indicators",{}).get("quote",[{}])[0]
    closes=qd.get("close",[]); lows=qd.get("low",[])
    return [(float(x),float(l)) for x,l in zip(closes,lows) if x is not None and l is not None]

def _strategy_rows(symbol, timeframe, sides, candles):
    if len(candles)<200: return []
    closes=[x[0] for x in candles]; lows=[x[1] for x in candles]
    price=closes[-1]; ema20=_ema(closes,20); ema200=_ema(closes,200); rsi=_rsi(closes)
    if None in (ema20,ema200,rsi): return []
    change=(price-closes[-2])/closes[-2]*100
    out=[]
    long_ok=price<ema20 and price<ema200 and rsi<50
    short_ok=price>ema20 and price>ema200 and rsi>50
    for side in sides:
        ok=long_ok if side=="BUY" else short_ok
        if not ok: continue
        if side=="BUY":
            sl=min(lows[-20:]); risk=price-sl
            if risk<=0 or risk/price>0.08: continue
            tp1, tp2, tp3=price+risk,price+2*risk,price+3*risk
            profit=risk/price*200; loss=risk/price*100
        else:
            recent_high=max(closes[-20:]); risk=recent_high-price
            if risk<=0 or risk/price>0.08: continue
            sl=recent_high; tp1,tp2,tp3=price-risk,price-2*risk,price-3*risk
            profit=risk/price*200; loss=risk/price*100
        ai=max(50,min(99,50+abs(50-rsi)*0.8+abs(ema20-price)/price*500))
        out.append({"symbol":symbol,"side":side,"timeframe":timeframe,"change_pct":change,
                    "profit_pct":profit,"loss_pct":loss,"ai_pct":ai,
                    "tag":("شراء" if side=="BUY" else "بيع")+" "+timeframe,
                    "entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"status":"open"})
    return out

def _market_universe(market):
    if market=="forex": return FOREX_SYMBOLS
    if market=="us": return US_SYMBOLS
    if market=="saudi": return SAUDI_SYMBOLS
    return []

def _scan_yahoo_market(market,timeframe):
    interval=timeframe
    range_map={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
    interval_map={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    def scan_one(symbol):
        candles=_yahoo_chart(symbol,interval_map[interval],range_map[interval])
        return _strategy_rows(symbol,timeframe,MARKET_RULES[market]["sides"],candles)
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(scan_one,s) for s in _market_universe(market)]
        for future in as_completed(futures):
            try: rows.extend(future.result(timeout=0.2))
            except Exception: pass
    return sorted([x for x in rows if abs(float(x.get("change_pct",0))) > 1],key=lambda x:(abs(x["change_pct"]),x["ai_pct"]),reverse=True)[:20]

def _scan_binance_futures(timeframe):
    tickers=_binance_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
    candidates=[]
    for t in tickers:
        s=t.get("symbol","")
        if s.endswith("USDT"):
            try:
                q=float(t.get("quoteVolume",0))
                if q>=1_000_000: candidates.append((q,s))
            except: pass
    def scan_one(item):
        _,symbol=item
        p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":260})
        k=_binance_json("https://fapi.binance.com/fapi/v1/klines?"+p,timeout=4)
        candles=[(float(x[4]),float(x[3])) for x in k]
        return _strategy_rows(symbol,timeframe,["BUY","SELL"],candles)
    rows=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures=[pool.submit(scan_one,item) for item in sorted(candidates,reverse=True)[:40]]
        for future in as_completed(futures):
            try: rows.extend(future.result(timeout=0.2))
            except Exception: pass
    rows=[x for x in rows if abs(float(x.get("change_pct",0))) > 1]
    return sorted(rows,key=lambda x:(abs(x["change_pct"]),x["ai_pct"]),reverse=True)[:20]

# ===== Backward-compatible API aliases =====
@app.get("/api/auth/me")
def auth_me(request:Request):
    return me(request)

@app.get("/api/admin/me")
def admin_me(request:Request):
    u=admin_only(request)
    return {"user":u} if u else JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)

@app.get("/api/spot/scan")
def legacy_spot_scan(interval:str="15m",limit:int=40):
    if interval not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        rows=_scan_spot_strategy(interval, min(max(limit,1),40))
        return {"market":"spot","timeframe":interval,"trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)

@app.get("/api/binance/scan")
def legacy_binance_scan(interval:str="15m",limit:int=40):
    return legacy_spot_scan(interval,limit)

@app.get("/api/spot/analysis")
def legacy_spot_analysis(symbol:str,interval:str="15m"):
    if interval not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        rows=_scan_spot_strategy(interval,40)
        for x in rows:
            if x["symbol"]==symbol.upper():
                return x
        return {"symbol":symbol.upper(),"timeframe":interval,"found":False,"message":"لا توجد إشارة مطابقة حالياً"}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر تحليل الرمز حالياً"},status_code=502)

@app.get("/api/binance/analysis")
def legacy_binance_analysis(symbol:str,interval:str="15m"):
    return legacy_spot_analysis(symbol,interval)

@app.get("/api/strategy/scan-all")
def strategy_scan_all(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    try:
        if market=="spot":
            rows=_scan_spot_strategy(timeframe)
        elif market in ("futures","contracts"):
            rows=_scan_binance_futures(timeframe)
        else:
            rows=_scan_yahoo_market(market,timeframe)
        return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,
                "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)

def admin_only(request):
    u=current_user(request); return u if u and u["is_admin"] else None

@app.get("/api/admin/summary")
def admin_summary(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); a=c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; b=c.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]; d=c.execute("SELECT COUNT(*) c FROM support_messages WHERE status='new'").fetchone()["c"]; c.close()
    return {"users":a,"trades":b,"new_support":d}

@app.post("/api/admin/trades")
def admin_trade(request:Request,market:str=Form(...),symbol:str=Form(...),side:str=Form(...),timeframe:str=Form(...),change_pct:float=Form(...),profit_pct:float=Form(...),loss_pct:float=Form(...),ai_pct:float=Form(...),tag:str=Form(""),entry:float=Form(...),tp1:float=Form(...),tp2:float=Form(...),tp3:float=Form(...),sl:float=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    if market not in MARKETS or timeframe not in TIMEFRAMES or side not in {"BUY","SELL"}: return JSONResponse({"ok":False,"message":"بيانات الصفقة غير صالحة"},status_code=400)
    c=db(); c.execute("""INSERT INTO trades(market,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(market,symbol.upper(),side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl)); c.commit(); c.close()
    return {"ok":True,"message":"تم حفظ الصفقة"}

@app.post("/api/admin/message")
def admin_message(request:Request,title:str=Form(...),body:str=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); c.execute("UPDATE messages SET active=0"); c.execute("INSERT INTO messages(title,body,active) VALUES(?,?,1)",(title,body)); c.commit(); c.close()
    return {"ok":True,"message":"تم نشر الرسالة"}
