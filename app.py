import os, time, sqlite3, hashlib, secrets
from pathlib import Path
from contextlib import contextmanager
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE=Path(__file__).resolve().parent
STATIC=BASE/"static"
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=BASE/"data"
    DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/"platform.db"

app=FastAPI(title="التداول الذكي PRO",version="6.0")
app.mount("/static",StaticFiles(directory=str(STATIC)),name="static")

TF={"15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d","1w":"1w","1M":"1M"}
STABLE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDSUSDT","BUSDUSDT"}

@contextmanager
def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,symbol TEXT NOT NULL,market TEXT NOT NULL,side TEXT NOT NULL,entry REAL NOT NULL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,timeframe TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',opened_at INTEGER NOT NULL,closed_at INTEGER,pnl REAL);
        CREATE INDEX IF NOT EXISTS ix_trades_user_status ON trades(user_id,status);
        """)
init_db()

@app.get("/",include_in_schema=False)
def root(): return FileResponse(STATIC/"index.html")

@app.get("/health")
def health(): return {"status":"ok","version":"6.0","db":str(DB),"time":int(time.time())}

async def binance(path,params=None,base="https://api.binance.com"):
    async with httpx.AsyncClient(timeout=15,headers={"User-Agent":"modareb-pro/6.0"}) as c:
        r=await c.get(base+path,params=params)
        r.raise_for_status()
        return r.json()

def ema(vals,n):
    if len(vals)<n:return None
    e=sum(vals[:n])/n;a=2/(n+1)
    for v in vals[n:]:e=v*a+e*(1-a)
    return e

def rsi(vals,n=14):
    if len(vals)<=n:return None
    gains=[];losses=[]
    for i in range(1,len(vals)):
        d=vals[i]-vals[i-1];gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[:n])/n;al=sum(losses[:n])/n
    for i in range(n,len(gains)):
        ag=(ag*(n-1)+gains[i])/n;al=(al*(n-1)+losses[i])/n
    return 100 if al==0 else 100-(100/(1+ag/al))

async def closes(symbol,interval,limit=230):
    k=await binance("/api/v3/klines",{"symbol":symbol,"interval":interval,"limit":limit})
    return [float(x[4]) for x in k]

async def strategy(symbol):
    c15=await closes(symbol,"15m",230)
    c1h=await closes(symbol,"1h",230)
    p=c15[-1]
    p1h=c1h[-1]
    e20=ema(c15,20);e200_15=ema(c15,200);e200_1h=ema(c1h,200);rr=rsi(c15)
    checks={
        "1h_below_ema200": bool(e200_1h and p1h<e200_1h),
        "15m_below_ema20": bool(e20 and p<e20),
        "rsi_below_50": bool(rr is not None and rr<50),
        "15m_below_ema200": bool(e200_15 and p<e200_15)
    }
    score=sum(25 for v in checks.values())
    # The chosen strategy is evaluated as one setup; there is no reverse mode.
    ready=all(checks.values())
    return {"symbol":symbol,"price":p,"ema20":e20,"ema200_15m":e200_15,"ema200_1h":e200_1h,"rsi":rr,"score":score,"ready":ready,"checks":checks}

async def spot_symbols(limit=80):
    data=await binance("/api/v3/ticker/24hr")
    out=[]
    for x in data:
        s=x.get("symbol","");q=float(x.get("quoteVolume") or 0)
        if s.endswith("USDT") and q>=1_000_000 and s not in STABLE:
            out.append({"symbol":s,"price":float(x.get("lastPrice") or 0),"change24h":float(x.get("priceChangePercent") or 0),"volume":q})
    out.sort(key=lambda z:(z["change24h"],z["volume"]),reverse=True)
    return out[:min(max(limit,1),150)]

def user_id(request:Request):
    token=request.cookies.get("session")
    if not token:return None
    with db() as c:
        row=c.execute("SELECT user_id FROM sessions WHERE token=?",(token,)).fetchone()
        return row["user_id"] if row else None

def close_expired(uid=None):
    now=int(time.time())
    with db() as c:
        q="SELECT * FROM trades WHERE status='open' AND opened_at<=?"
        args=[now-3600]
        if uid is not None:q+=" AND user_id=?";args.append(uid)
        rows=c.execute(q,args).fetchall()
        for t in rows:
            price=t["tp1"] if t["tp1"] is not None else t["entry"]
            pnl=((price-t["entry"])/t["entry"]*100) if t["side"]=="BUY" else ((t["entry"]-price)/t["entry"]*100)
            c.execute("UPDATE trades SET status='closed',closed_at=?,pnl=? WHERE id=?",(now,round(pnl,4),t["id"]))

@app.get("/api/platform/summary")
def summary():
    close_expired()
    with db() as c:
        users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        open_n=c.execute("SELECT COUNT(*) n FROM trades WHERE status='open'").fetchone()["n"]
    return {"status":"online","version":"6.0","users":users,"open_trades":open_n,"strategy":"1h EMA200 + 15m EMA20 + RSI<50 + 15m EMA200","timeframes":list(TF)}

@app.get("/api/markets")
async def markets(tf:str="15m",limit:int=40):
    try:\n        items=await spot_symbols(limit)\n        return {"timeframe":TF.get(tf,"15m"),"items":items,"count":len(items)}
    except Exception as e:return JSONResponse({"error":"تعذر جلب بيانات Binance","detail":str(e)},status_code=502)

@app.get("/api/futures")
async def futures(limit:int=50):
    try:
        data=await binance("/fapi/v1/ticker/24hr",base="https://fapi.binance.com")
        out=[]
        for x in data:
            s=x.get("symbol","");q=float(x.get("quoteVolume") or 0)
            if s.endswith("USDT") and q>=1_000_000 and s not in STABLE:
                out.append({"symbol":s,"price":float(x.get("lastPrice") or 0),"change24h":float(x.get("priceChangePercent") or 0),"volume":q})
        out.sort(key=lambda z:abs(z["change24h"]),reverse=True)
        return {"items":out[:min(max(limit,1),100)],"count":len(out)}
    except Exception as e:return JSONResponse({"error":"تعذر جلب بيانات Futures","detail":str(e)},status_code=502)

@app.get("/api/contracts")
async def contracts(limit:int=50):
    return await futures(limit)

@app.get("/api/scanner")
async def scanner(tf:str="15m",limit:int=20):
    try:
        syms=await spot_symbols(min(limit,40));out=[]
        for x in syms:
            try:
                s=await strategy(x["symbol"])
                if s["ready"] or s["score"]>=50:
                    x.update({"score":s["score"],"ready":s["ready"],"rsi":s["rsi"],"ema20":s["ema20"],"ema200":s["ema200_15m"]})
                    out.append(x)
            except Exception: pass
        out.sort(key=lambda z:(z["ready"],z["score"],abs(z["change24h"])),reverse=True)
        return {"timeframe":TF.get(tf,"15m"),"items":out,"count":len(out)}
    except Exception as e:return JSONResponse({"error":"تعذر تشغيل الماسح","detail":str(e)},status_code=502)

@app.get("/api/signal")
async def signal(symbol:str):
    try:return await strategy(symbol.upper())
    except Exception as e:return JSONResponse({"error":str(e)},status_code=502)

@app.get("/api/trades")
def trades(request:Request,market:str="spot",timeframe:str="15m"):
    uid=user_id(request)
    if uid is None:return {"items":[],"authenticated":False}
    close_expired(uid)
    with db() as c:
        rows=c.execute("SELECT * FROM trades WHERE user_id=? ORDER BY opened_at DESC",(uid,)).fetchall()
    return {"authenticated":True,"items":[dict(r) for r in rows]}

@app.get("/api/tracker")
def tracker(request:Request):
    uid=user_id(request)
    if uid is None:return {"authenticated":False,"open":[],"closed":[],"stats":{"open":0,"closed":0,"wins":0,"losses":0,"pnl":0}}
    close_expired(uid)
    with db() as c:
        rows=c.execute("SELECT * FROM trades WHERE user_id=? ORDER BY opened_at DESC",(uid,)).fetchall()
    items=[dict(r) for r in rows];op=[x for x in items if x["status"]=="open"];cl=[x for x in items if x["status"]=="closed"]
    wins=sum(1 for x in cl if (x["pnl"] or 0)>0);losses=sum(1 for x in cl if (x["pnl"] or 0)<=0);pnl=round(sum((x["pnl"] or 0) for x in cl),4)
    return {"authenticated":True,"open":op,"closed":cl,"stats":{"open":len(op),"closed":len(cl),"wins":wins,"losses":losses,"pnl":pnl}}

@app.post("/api/trades")
async def create_trade(request:Request):
    uid=user_id(request)
    if uid is None:return JSONResponse({"error":"سجل الدخول أولاً"},status_code=401)
    data=await request.json();symbol=str(data.get("symbol","")).upper()
    if not symbol:return JSONResponse({"error":"الرمز مطلوب"},status_code=400)
    try:
        p=float(data.get("entry"));tp1=float(data.get("tp1"));sl=float(data.get("sl"))
    except Exception:return JSONResponse({"error":"بيانات الصفقة غير صحيحة"},status_code=400)
    now=int(time.time())
    with db() as c:
        c.execute("INSERT INTO trades(user_id,symbol,market,side,entry,tp1,tp2,tp3,sl,timeframe,status,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(uid,symbol,"spot","BUY",p,tp1,data.get("tp2"),data.get("tp3"),sl,str(data.get("timeframe","15m")),"open",now))
    return {"ok":True}

@app.post("/api/trades/{trade_id}/close")
def close_trade(trade_id:int,request:Request):
    uid=user_id(request)
    if uid is None:return JSONResponse({"error":"سجل الدخول أولاً"},status_code=401)
    with db() as c:
        t=c.execute("SELECT * FROM trades WHERE id=? AND user_id=? AND status='open'",(trade_id,uid)).fetchone()
        if not t:return JSONResponse({"error":"الصفقة غير موجودة"},status_code=404)
        price=float(request.query_params.get("price") or t["entry"])
        pnl=((price-t["entry"])/t["entry"]*100) if t["side"]=="BUY" else ((t["entry"]-price)/t["entry"]*100)
        c.execute("UPDATE trades SET status='closed',closed_at=?,pnl=? WHERE id=?",(int(time.time()),round(pnl,4),trade_id))
    return {"ok":True,"pnl":round(pnl,4)}

@app.post("/api/auth/register")
async def register(request:Request):
    data=await request.json();email=str(data.get("email","")).strip().lower();pw=str(data.get("password",""))
    if len(email)<5 or len(pw)<6:return JSONResponse({"error":"البريد وكلمة المرور مطلوبة، وكلمة المرور 6 أحرف على الأقل"},status_code=400)
    h=hashlib.sha256(pw.encode()).hexdigest()
    try:
        with db() as c:c.execute("INSERT INTO users(email,password,created_at) VALUES(?,?,?)",(email,h,int(time.time())));uid=c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone()["id"]
    except sqlite3.IntegrityError:return JSONResponse({"error":"الحساب موجود مسبقاً"},status_code=409)
    token=secrets.token_urlsafe(32)
    with db() as c:c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",(token,uid,int(time.time())))
    r=JSONResponse({"ok":True,"email":email});r.set_cookie("session",token,httponly=True,samesite="lax",max_age=2592000);return r

@app.post("/api/auth/login")
async def login(request:Request):
    data=await request.json();email=str(data.get("email","")).strip().lower();pw=str(data.get("password",""));h=hashlib.sha256(pw.encode()).hexdigest()
    with db() as c:row=c.execute("SELECT id,email FROM users WHERE email=? AND password=?",(email,h)).fetchone()
    if not row:return JSONResponse({"error":"بيانات الدخول غير صحيحة"},status_code=401)
    token=secrets.token_urlsafe(32)
    with db() as c:c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",(token,row["id"],int(time.time())))
    r=JSONResponse({"ok":True,"email":row["email"]});r.set_cookie("session",token,httponly=True,samesite="lax",max_age=2592000);return r

@app.post("/api/auth/logout")
def logout(request:Request):
    token=request.cookies.get("session")
    if token:
        with db() as c:c.execute("DELETE FROM sessions WHERE token=?",(token,))
    r=JSONResponse({"ok":True});r.delete_cookie("session");return r

@app.get("/api/auth/me")
def me(request:Request):
    uid=user_id(request)
    if not uid:return {"authenticated":False,"user":None}
    with db() as c:row=c.execute("SELECT id,email,created_at FROM users WHERE id=?",(uid,)).fetchone()
    return {"authenticated":True,"user":dict(row) if row else None}

@app.get("/api/news")
def news():
    return {"items":[
        {"title":"بيانات السوق مباشرة من Binance","source":"Binance","time":"LIVE","text":"الماسح يعتمد على بيانات السوق الحالية ولا ينشئ صفقات وهمية."},
        {"title":"الاستراتيجية الموحدة","source":"التداول الذكي PRO","time":"LIVE","text":"EMA200 على الساعة + EMA20 وRSI وEMA200 على 15 دقيقة."}
    ]}

@app.get("/api/saudi")
def saudi(): return {"available":False,"message":"مصدر السوق السعودي يحتاج مزود بيانات مخصص؛ لن نعرض أرقاماً وهمية."}

@app.get("/api/us")
def us(): return {"available":False,"message":"مصدر السوق الأمريكي يحتاج مزود بيانات مخصص؛ لن نعرض أرقاماً وهمية."}

@app.get("/api/forex")
def forex(): return {"available":False,"message":"مصدر الفوركس والذهب يحتاج مزود بيانات مخصص؛ لن نعرض أرقاماً وهمية."}
