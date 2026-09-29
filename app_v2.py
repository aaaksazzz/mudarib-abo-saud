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
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY,market TEXT,symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp REAL,stop REAL,tp1 REAL,tp2 REAL,tp3 REAL,confidence REAL,change15 REAL,reason TEXT,status TEXT DEFAULT 'open',created_at TEXT);\nCREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,signal_id INTEGER,market TEXT,symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp REAL,stop REAL,tp1 REAL,tp2 REAL,tp3 REAL,exit_price REAL,pnl_pct REAL,confidence REAL,change15 REAL,status TEXT DEFAULT 'open',opened_at TEXT,closed_at TEXT);\nCREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source TEXT,published TEXT);
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,title TEXT,slug TEXT UNIQUE,body TEXT,status TEXT DEFAULT 'published',created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT);
"""
def db():
    c=sqlite3.connect(DB,check_same_thread=False); c.row_factory=sqlite3.Row
    c.executescript(SCHEMA)
    for table in ("signals","trades"):
        cols={r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        for col in ("stop","tp1","tp2","tp3"):
            if col not in cols: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
    c.execute("UPDATE trades SET status='archived' WHERE status='open' AND (stop IS NULL OR tp1 IS NULL)")
    c.execute("UPDATE signals SET status='archived' WHERE status='open' AND (stop IS NULL OR tp1 IS NULL)")
    c.commit()
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
def yahoo(symbol,interval="15m",range_="1mo"):
    u="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode({"interval":interval,"range":range_})
    j=cached_get_json(u)
    results=j.get("chart",{}).get("result") or []
    if not results:
        return []
    r=results[0]
    q=(r.get("indicators",{}).get("quote") or [{}])[0]
    out=[]
    volumes=q.get("volume") or []
    for i,ts in enumerate(r.get("timestamp",[])):
        close=q.get("close",[])
        if i < len(close) and close[i] is not None:
            c=float(close[i])
            o=float((q.get("open") or [None]*len(close))[i] or c)
            h=float((q.get("high") or [None]*len(close))[i] or c)
            l=float((q.get("low") or [None]*len(close))[i] or c)
            v=float(volumes[i] or 0) if i < len(volumes) else 0.0
            out.append((ts,o,h,l,c,v))
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
def ema(values, period):
    if len(values)<period:return sum(values)/len(values) if values else 0
    k=2/(period+1); e=sum(values[:period])/period
    for v in values[period:]: e=(v*k)+(e*(1-k))
    return e

def rsi(values, period=14):
    if len(values)<=period:return 50.0
    gains=[];losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    if al==0:return 100.0
    return 100-(100/(1+(ag/al)))
def swing_levels(candles,entry):
    lows=[]; highs=[]
    for i in range(max(2,len(candles)-80),len(candles)-2):
        h=candles[i][2]; l=candles[i][3]
        if h>candles[i-2][2] and h>candles[i-1][2] and h>=candles[i+1][2] and h>=candles[i+2][2] and h>entry: highs.append(h)
        if l<candles[i-2][3] and l<candles[i-1][3] and l<=candles[i+1][3] and l<=candles[i+2][3] and l<entry: lows.append(l)
    if not lows or not highs:return None
    stop=max(lows)*0.999
    tps=sorted(set(highs))[:3]
    return stop,tps

def strategy(candles):
    if len(candles)<220:return None
    closes=[x[4] for x in candles];vol=[x[5] for x in candles];p=closes[-1];e20=ema(closes,20);e200=ema(closes,200);r=rsi(closes);avg=sum(vol[-21:-1])/20;ch=(p-closes[-2])/closes[-2]*100
    if not(p<e20 and r<50 and p<e200 and vol[-1]>avg):return None
    levels=swing_levels(candles,p)
    if not levels:return None
    stop,tps=levels
    tp1=tps[0];tp2=tps[1] if len(tps)>1 else None;tp3=tps[2] if len(tps)>2 else None
    if not(stop<p<tp1):return None
    score=70+(15 if ch>0 else 0)+(10 if vol[-1]>avg*1.5 else 0)+(5 if r<45 else 0)
    return {"entry":p,"stop":stop,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp":tp3 or tp2 or tp1,"change15":ch,"confidence":min(score,99),"reason":f"15m: تحت EMA20 وEMA200، RSI={r:.1f}، حجم أعلى من متوسط 20، وقف وأهداف من قمم وقيعان فعلية"}
def _scan_one(a):
    m,s,name,tf=a
    try:
        x=strategy(market_candles(m,s,tf))
        return (x["change"],s,name,x,tf) if x else None
    except Exception:return None

def _chunks(items,size):
    for i in range(0,len(items),max(1,size)):
        yield items[i:i+max(1,size)]

def _scan_batch(market,batch,workers):
    results=[]
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix=f"{market}-srv") as pool:
        futures=[pool.submit(_scan_one,x) for x in batch]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x:results.append(x)
            except Exception: continue
    return results

def update_open_trades(market):
    c=db(); rows=c.execute("SELECT * FROM trades WHERE market=? AND status='open'",(market,)).fetchall()
    for t in rows:
        try:
            candles=market_candles(market,t["symbol"])
            if not candles: continue
            price=candles[-1][4]
            stop=t["stop"]; target=t["tp3"] or t["tp2"] or t["tp1"] or t["tp"]
            if stop is not None and price<=stop:
                pnl=(stop-t["entry"])/t["entry"]*100
                c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(stop,pnl,now(),t["id"]))
            elif target is not None and price>=target:
                pnl=(target-t["entry"])/t["entry"]*100
                c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(target,pnl,now(),t["id"]))
        except Exception:
            continue
    c.commit()
def scan_symbols(market,tf="15m"):
    global _SOURCE_ROUND
    c=db()
    rows=c.execute("SELECT symbol,name FROM symbols WHERE market=? AND active=1",(market,)).fetchall()
    candidates=[(market,r["symbol"],r["name"],tf) for r in rows]
    if market in ("spot","futures"):
        try:
            t=binance_24h(market)
            candidates=[x for x in candidates if x[1] in t and float(t[x[1]].get("quoteVolume",0))>=1000000]
            candidates.sort(key=lambda x: float(t.get(x[1],{}).get("priceChangePercent",0)),reverse=True)
        except Exception: pass
    batch_size=max(1,MARKET_BATCH_SIZE.get(market,25)); workers=max(1,MARKET_WORKERS.get(market,8)); results=[]
    batches=list(_chunks(candidates,batch_size))
    with _SOURCE_LOCK:
        offset=_SOURCE_ROUND % len(batches) if batches else 0; _SOURCE_ROUND+=1
    ordered=batches[offset:]+batches[:offset]
    for idx,batch in enumerate(ordered,1):
        results.extend(_scan_batch(market,batch,workers))
        if idx<len(ordered): time.sleep(BATCH_PAUSE)
    pos=sorted([x for x in results if x[0]>0],key=lambda x:x[0],reverse=True)
    neg=sorted([x for x in results if x[0]<=0],key=lambda x:x[0],reverse=True)
    ranked=(pos or neg)[:20]
    if ranked:
        c.execute("UPDATE signals SET status='archived' WHERE market=? AND timeframe=? AND status='open'",(market,tf))
        for rank,(ch,sym,name,x,frame) in enumerate(ranked,1):
            c.execute("INSERT INTO signals(market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",(market,sym,"BUY",frame,x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,f"#{rank} · {frame} · {x['reason']}",now()))
            if not c.execute("SELECT 1 FROM trades WHERE market=? AND symbol=? AND timeframe=? AND status='open'",(market,sym,frame)).fetchone():
                c.execute("INSERT INTO trades(signal_id,market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,status,opened_at) VALUES((SELECT id FROM signals WHERE market=? AND symbol=? AND timeframe=? ORDER BY id DESC LIMIT 1),?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",(market,sym,frame,market,sym,"BUY",frame,x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,now()))
    c.commit()
    return ranked

def scan_all_markets():
    out={}
    for tf in TIMEFRAMES:
        out[tf]={}
        for m in ("spot","futures","contracts","american","saudi","forex"):
            try: out[tf][m]=scan_symbols(m,tf)
            except Exception: out[tf][m]=[]
    return out