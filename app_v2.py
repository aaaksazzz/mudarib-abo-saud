# DEPLOY GUARD: syntax audited before deployment.
import os, json, time, hmac, hashlib, urllib.parse, urllib.request, sqlite3, secrets, threading, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

DB=os.getenv("DATABASE_PATH","site.db")
ADMIN_EMAIL=os.getenv("ADMIN_EMAIL","admin@example.com").strip().lower()
ADMIN_USERNAME=os.getenv("ADMIN_USERNAME","aaaksazzz").strip()
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
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY,market TEXT,symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp REAL,stop REAL,tp1 REAL,tp2 REAL,tp3 REAL,confidence REAL,change15 REAL,reason TEXT,status TEXT DEFAULT 'open',created_at TEXT);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,signal_id INTEGER,market TEXT,symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp REAL,stop REAL,tp1 REAL,tp2 REAL,tp3 REAL,exit_price REAL,pnl_pct REAL,confidence REAL,change15 REAL,status TEXT DEFAULT 'open',opened_at TEXT,closed_at TEXT);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source TEXT,published TEXT,body TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,title TEXT,slug TEXT UNIQUE,body TEXT,status TEXT DEFAULT 'published',created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT);
CREATE TABLE IF NOT EXISTS support_tickets(id INTEGER PRIMARY KEY,user_id INTEGER,name TEXT,email TEXT,message TEXT,status TEXT DEFAULT 'open',admin_reply TEXT DEFAULT '',created_at TEXT,updated_at TEXT);
"""
def db():
    # SQLite على التخزين المشترك يحتاج مهلة انتظار بدل فشل الطلب عند قفل مؤقت.
    c=sqlite3.connect(DB,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    c.executescript(SCHEMA)
    cols_news={r[1] for r in c.execute("PRAGMA table_info(news)").fetchall()}
    if "body" not in cols_news: c.execute("ALTER TABLE news ADD COLUMN body TEXT DEFAULT ''")
    for table in ("signals","trades"):
        cols={r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        for col in ("stop","tp1","tp2","tp3"):
            if col not in cols: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
    c.execute("UPDATE trades SET status='archived' WHERE status='open' AND (stop IS NULL OR tp1 IS NULL)")
    c.execute("UPDATE signals SET status='archived' WHERE status='open' AND (stop IS NULL OR tp1 IS NULL)")
    c.commit()
    if not c.execute("SELECT 1 FROM users WHERE email=?",(ADMIN_EMAIL,)).fetchone():
        c.execute("INSERT INTO users(email,password,name,role,created_at) VALUES(?,?,?,?,?)",(ADMIN_EMAIL,pwd.hash(ADMIN_PASSWORD),ADMIN_USERNAME,"admin",now()))
    else:
        c.execute("UPDATE users SET name=?, role='admin', active=1 WHERE email=?",(ADMIN_USERNAME,ADMIN_EMAIL))
    c.commit()
    return c
def now(): return datetime.now(timezone.utc).isoformat()

FEATURE_DEFAULTS={
    "accounts":1,"trades":1,"scanner":1,"bot":1,
    "spot":1,"futures":1,"contracts":1,"american":1,"saudi":1,"forex":1,
    "news":1,"blog":1,"subscriptions":1,"support":1,"telegram":1
}
def feature_enabled(key):
    try:
        r=db().execute("SELECT v FROM settings WHERE k=?",("feature:"+key,)).fetchone()
        return bool(int(r["v"])) if r else bool(FEATURE_DEFAULTS.get(key,1))
    except Exception:
        return bool(FEATURE_DEFAULTS.get(key,1))
def set_feature(key,enabled):
    c=db()
    c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",("feature:"+key,"1" if enabled else "0"))
    c.commit()

@app.middleware("http")
async def feature_gate(req:Request,call_next):
    path=req.url.path
    key=None
    if path=="/register": key="accounts"
    elif path in ("/account",): key="accounts"
    elif path.startswith("/support"): key="support"
    elif path.startswith("/subscriptions"): key="subscriptions"
    elif path.startswith("/trades"): key="trades"
    elif path.startswith("/scanner"): key="scanner"
    elif path.startswith("/bot"): key="bot"
    elif path.startswith("/news"): key="news"
    elif path.startswith("/blog"): key="blog"
    elif path.startswith("/market/"):
        market=path.split("/")[2] if len(path.split("/"))>2 else ""
        key=market if market in ("spot","futures","contracts","american","saudi","forex") else None
    if key and not feature_enabled(key):
        return HTMLResponse("<!doctype html><html lang='ar' dir='rtl'><meta name='viewport' content='width=device-width,initial-scale=1'><body style='font-family:Arial;background:#0b1020;color:#fff;padding:40px;text-align:center'><h1>الخدمة متوقفة مؤقتًا</h1><p>تم إيقاف هذا القسم من لوحة الإدارة.</p><a href='/' style='color:#60a5fa'>العودة للرئيسية</a></body></html>",status_code=503)
    return await call_next(req)

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
TIMEFRAMES=("5m","15m","1h","4h","1d","1w","1mo")
_TIMEFRAME_ROUND=0
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

def binance(symbol,market="spot",interval="15m"):
    base="https://api.binance.com" if market=="spot" else "https://fapi.binance.com";path="/api/v3/klines" if market=="spot" else "/fapi/v1/klines"
    interval="1M" if interval=="1mo" else interval
    j=cached_get_json(base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":250}))
    return [(x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[7])) for x in j[:-1]]
def binance_24h(market):
    base="https://api.binance.com" if market=="spot" else "https://fapi.binance.com";path="/api/v3/ticker/24hr" if market=="spot" else "/fapi/v1/ticker/24hr"
    return {x["symbol"]:x for x in cached_get_json(base+path) if x.get("symbol","").endswith("USDT")}
def contracts(symbol,interval="15m"):
    interval="1M" if interval=="1mo" else interval
    j=cached_get_json("https://dapi.binance.com/dapi/v1/klines?"+urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":250}))
    return [(x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[7])) for x in j[:-1]]
def market_candles(m,s,interval="15m"):
    if m=="spot":return binance(s,"spot",interval)
    if m=="futures":return binance(s,"futures",interval)
    if m=="contracts":return contracts(s,interval)
    ranges={"5m":"60d","15m":"60d","1h":"2y","4h":"2y","1d":"5y","1w":"10y","1mo":"max"}
    return yahoo(s,interval,ranges.get(interval,"1mo"))
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
def swing_levels(candles,entry,side="BUY"):
    lows=[]; highs=[]
    for i in range(max(2,len(candles)-80),len(candles)-2):
        h=candles[i][2]; l=candles[i][3]
        if h>candles[i-2][2] and h>candles[i-1][2] and h>=candles[i+1][2] and h>=candles[i+2][2] and h>entry: highs.append(h)
        if l<candles[i-2][3] and l<candles[i-1][3] and l<=candles[i+1][3] and l<=candles[i+2][3] and l<entry: lows.append(l)
    if not lows or not highs:return None
    if side=="BUY":
        return max(lows)*0.999,sorted(set(highs))[:3]
    return min(highs)*1.001,sorted(set(lows),reverse=True)[:3]

def strategy(candles,tf="15m",side="BUY"):
    if len(candles)<220:return None
    closes=[x[4] for x in candles];vol=[x[5] for x in candles];p=closes[-1];e20=ema(closes,20);e200=ema(closes,200);r=rsi(closes);avg=sum(vol[-21:-1])/20;ch=(p-closes[-2])/closes[-2]*100
    ok=(p>e20 and r>50 and p>e200 and vol[-1]>avg) if side=="BUY" else (p<e20 and r<50 and p<e200 and vol[-1]>avg)
    if not ok:return None
    levels=swing_levels(candles,p,side)
    if not levels:return None
    stop,tps=levels;tp1=tps[0];tp2=tps[1] if len(tps)>1 else None;tp3=tps[2] if len(tps)>2 else None
    if side=="BUY":
        if not(stop<p<tp1):return None
        score=70+(15 if ch>0 else 0)+(10 if vol[-1]>avg*1.5 else 0)+(5 if r>55 else 0)
        reason=tf+": شراء، السعر فوق EMA20 وEMA200 وRSI فوق 50 وحجم أعلى من المتوسط"
    else:
        if not(tp1<p<stop):return None
        score=70+(15 if ch<0 else 0)+(10 if vol[-1]>avg*1.5 else 0)+(5 if r<45 else 0)
        reason=tf+": بيع، السعر تحت EMA20 وEMA200 وRSI تحت 50 وحجم أعلى من المتوسط"
    return {"entry":p,"side":side,"stop":stop,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp":tp3 or tp2 or tp1,"change15":ch,"confidence":min(score,99),"reason":reason}

def _scan_one(a):
    m,s,name,tf=a
    try:
        candles=market_candles(m,s,tf)
        sides=("BUY","SELL") if m in ("futures","contracts","forex") else ("BUY",)
        out=[]
        for side in sides:
            x=strategy(candles,tf,side)
            if x: out.append((x["change15"],s,name,x,tf))
        return out
    except Exception:return []

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
                if x:results.extend(x)
            except Exception:
                continue
    return results

def update_open_trades(market):
    c=db(); rows=c.execute("SELECT * FROM trades WHERE market=? AND status='open'",(market,)).fetchall()
    for t in rows:
        try:
            candles=market_candles(market,t["symbol"],t["timeframe"] or "15m")
            if not candles: continue
            price=candles[-1][4]
            stop=t["stop"]; target=t["tp3"] or t["tp2"] or t["tp1"] or t["tp"]; entry=t["entry"]
            if (t["side"] or "BUY")=="SELL":
                if stop is not None and price>=stop:
                    pnl=(entry-stop)/entry*100
                    c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(stop,pnl,now(),t["id"]))
                elif target is not None and price<=target:
                    pnl=(entry-target)/entry*100
                    c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(target,pnl,now(),t["id"]))
            else:
                if stop is not None and price<=stop:
                    pnl=(stop-entry)/entry*100
                    c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(stop,pnl,now(),t["id"]))
                elif target is not None and price>=target:
                    pnl=(target-entry)/entry*100
                    c.execute("UPDATE trades SET status='closed',exit_price=?,pnl_pct=?,closed_at=? WHERE id=?",(target,pnl,now(),t["id"]))
        except Exception:
            continue
    c.commit()
def scan_symbols(market,tf="5m"):
    global _SOURCE_ROUND
    c=db(); rows=c.execute("SELECT symbol,name FROM symbols WHERE market=? AND active=1",(market,)).fetchall()
    candidates=[(market,r["symbol"],r["name"],tf) for r in rows]
    if market in ("spot","futures"):
        try:
            t=binance_24h(market)
            candidates=[x for x in candidates if x[1] in t and float(t[x[1]].get("quoteVolume",0))>=1000000]
            candidates.sort(key=lambda x: float(t.get(x[1],{}).get("priceChangePercent",0)),reverse=True)
        except Exception: pass
    batch_size=max(1,MARKET_BATCH_SIZE.get(market,25));workers=max(1,MARKET_WORKERS.get(market,8));results=[]
    batches=list(_chunks(candidates,batch_size))
    with _SOURCE_LOCK:
        offset=_SOURCE_ROUND%len(batches) if batches else 0;_SOURCE_ROUND+=1
    for idx,batch in enumerate(batches[offset:]+batches[:offset],1):
        results.extend(_scan_batch(market,batch,workers))
        if idx<len(batches):time.sleep(BATCH_PAUSE)
    pos=sorted([x for x in results if x[0]>0],key=lambda x:x[0],reverse=True);neg=sorted([x for x in results if x[0]<=0],key=lambda x:x[0],reverse=True);ranked=(pos or neg)[:20]
    if ranked:
        c.execute("UPDATE signals SET status='archived' WHERE market=? AND timeframe=? AND status='open'",(market,tf))
        for rank,(ch,sym,name,x,frame) in enumerate(ranked,1):
            cur=c.execute("INSERT INTO signals(market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",(market,sym,x["side"],frame,x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,f"الترتيب #{rank} · {x['reason']}",now()));sid=cur.lastrowid
            if not c.execute("SELECT 1 FROM trades WHERE market=? AND symbol=? AND timeframe=? AND status='open'",(market,sym,frame)).fetchone():
                c.execute("INSERT INTO trades(signal_id,market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,status,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sid,market,sym,x["side"],frame,x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,"open",now()))
        c.commit()
    return ranked
def scan_all_markets(tf=None):
    global _TIMEFRAME_ROUND
    if tf is None:
        tf=TIMEFRAMES[_TIMEFRAME_ROUND%len(TIMEFRAMES)];_TIMEFRAME_ROUND+=1
    out={"timeframe":tf}
    for m in ("spot","futures","contracts","american","saudi","forex"):
        if not feature_enabled(m):
            out[m]=[]
            continue
        try: out[m]=scan_symbols(m,tf)
        except Exception: out[m]=[]
    return out

def _timeframe_key(tf,ts=None):
    ts=time.time() if ts is None else ts
    if tf=="5m": return int(ts//300)
    if tf=="15m": return int(ts//900)
    if tf=="1h": return int(ts//3600)
    if tf=="4h": return int(ts//14400)
    if tf=="1d": return int(ts//86400)
    if tf=="1w":
        d=datetime.fromtimestamp(ts,timezone.utc)
        y,w,_=d.isocalendar()
        return (y,w)
    if tf=="1mo":
        d=datetime.fromtimestamp(ts,timezone.utc)
        return (d.year,d.month)
    return int(ts)

def _scan_loop():
    # كل فريم له دورة مستقلة: بعد إغلاق شمعة الفريم يعاد استخراج صفقاته.
    last_keys={}
    while True:
        try:
            for tf in TIMEFRAMES:
                key=_timeframe_key(tf)
                if last_keys.get(tf)!=key:
                    scan_all_markets(tf)
                    last_keys[tf]=key
        except Exception:
            pass
        time.sleep(10)
def seed():
    c=db()
    defaults={
      "american":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","AVGO","NFLX","JPM","WMT","COST","ORCL","CRM","INTC","QCOM","MU","PLTR","ADBE","CSCO","AMAT","LRCX","TXN","INTU","NOW","UBER","SHOP","PANW","CRWD","SNOW","PYPL","BKNG","ABNB","DIS","KO","PEP","MCD","V","MA","HD","LOW","BA","CAT","GE","IBM","XOM","CVX","COP","LLY","JNJ","MRK","PFE","ABBV","TMO","UNH","NKE","SBUX","GS","MS","BAC","C","WFC","BLK","AXP","DE","UPS","RTX","HON","ARM","SMCI","MSTR"],
      "saudi":["2222.SR","2010.SR","1120.SR","1150.SR","1180.SR","1211.SR","7010.SR","7020.SR","2380.SR","4030.SR","1010.SR","1060.SR","1140.SR","1182.SR","1183.SR","1201.SR","1202.SR","1210.SR","1301.SR","1320.SR","2001.SR","2040.SR","2060.SR","2080.SR","2090.SR","2160.SR","2170.SR","2180.SR","2200.SR","2210.SR","2220.SR","2240.SR","2250.SR","2290.SR","2300.SR","2310.SR","2330.SR","2350.SR","2360.SR","2380.SR","3003.SR","3008.SR","3010.SR","3020.SR","3030.SR","3040.SR","3050.SR","3060.SR","3080.SR","3090.SR","3091.SR","4001.SR","4002.SR","4003.SR","4004.SR","4005.SR","4007.SR","4008.SR","4013.SR","4014.SR","4015.SR","4020.SR","4030.SR","4031.SR","4040.SR","4050.SR","4051.SR","4061.SR","4070.SR","4080.SR","4090.SR","4100.SR","4140.SR","4150.SR","4160.SR","4170.SR","4180.SR","4190.SR","4200.SR","4210.SR","4220.SR","4230.SR","4240.SR","4250.SR","4260.SR","4270.SR","4280.SR","4290.SR","4300.SR","4310.SR","4320.SR","4330.SR","4340.SR","5110.SR","6001.SR","6002.SR","6010.SR","6020.SR","6040.SR","6050.SR","6060.SR","6070.SR","6090.SR","7010.SR","7030.SR","7040.SR","7200.SR","7201.SR","7202.SR","7203.SR","7204.SR"],
      "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","USDCAD=X","AUDUSD=X","NZDUSD=X","EURGBP=X","EURJPY=X","EURCHF=X","GBPJPY=X","GBPAUD=X","GBPCAD=X","AUDJPY=X","CADJPY=X","NZDJPY=X","GC=F","SI=F","PL=F","PA=F","CL=F","BZ=F","NG=F","HG=F","ZC=F","ZW=F"]
    }
    for m,syms in defaults.items():
        for s in syms:
            if not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(m,s)).fetchone():
                c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(m,s,s))
    # Refresh Binance universes for Spot, USD-M Futures and COIN-M Contracts.
    for m,base in [("spot","https://api.binance.com/api/v3/exchangeInfo"),("futures","https://fapi.binance.com/fapi/v1/exchangeInfo"),("contracts","https://dapi.binance.com/dapi/v1/exchangeInfo")]:
        try:
            data=json.loads(get(base))
            for x in data.get("symbols",[]):
                if x.get("status")!="TRADING": continue
                if m=="contracts":
                    if x.get("contractStatus") not in (None,"TRADING"): continue
                    if x.get("contractType")!="PERPETUAL": continue
                elif x.get("quoteAsset")!="USDT":
                    continue
                s=x.get("symbol")
                if s and not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(m,s)).fetchone():
                    c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(m,s,s))
        except Exception: pass
    c.commit()
seed()

CSS="""*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#050b14;color:#eef5ff;font-family:Arial,Tahoma,sans-serif;min-height:100vh}a{color:inherit;text-decoration:none}button,a,.btn{touch-action:manipulation}.wrap{max-width:1480px;margin:auto;padding:18px}.top{position:sticky;top:0;z-index:50;background:rgba(5,11,20,.92);backdrop-filter:blur(18px);border-bottom:1px solid #17283d}.brandbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 0 14px}.brand{font-size:24px;font-weight:900;letter-spacing:.2px}.brandmark{display:inline-flex;width:38px;height:38px;align-items:center;justify-content:center;border-radius:12px;background:linear-gradient(135deg,#19d98b,#1c8cff);box-shadow:0 8px 30px rgba(28,140,255,.22);margin-left:8px}.brand small{display:block;color:#7f93aa;font-size:11px;font-weight:600;margin-top:4px}.pro{color:#58d9ff}.nav{display:flex;gap:8px;overflow-x:auto;padding:4px 0 2px;scrollbar-width:none}.nav::-webkit-scrollbar{display:none}.nav a{display:flex;align-items:center;gap:8px;padding:10px 13px;border-radius:13px;background:#0a1524;border:1px solid #172a40;white-space:nowrap;font-weight:800;color:#aebed0;transition:.18s}.nav a:hover{background:#102238;border-color:#285071;color:#fff;transform:translateY(-1px)}.nav .ico{width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center}.nav svg{width:19px;height:19px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.hero{position:relative;overflow:hidden;padding:30px;border-radius:24px;background:radial-gradient(circle at 85% 20%,rgba(24,146,255,.16),transparent 32%),radial-gradient(circle at 15% 90%,rgba(25,217,139,.12),transparent 30%),linear-gradient(135deg,#0c1b2d,#07111d 65%);border:1px solid #1b344e;box-shadow:0 22px 60px rgba(0,0,0,.22)}.hero h1{font-size:clamp(28px,4vw,46px);margin:0 0 10px}.hero p{max-width:760px;line-height:1.8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.market-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}.market-tile{position:relative;overflow:hidden;min-height:150px;padding:20px;border-radius:20px;background:linear-gradient(145deg,#0d1b2d,#091321);border:1px solid #1a3048;transition:.2s}.market-tile:hover{transform:translateY(-3px);border-color:#2d5d82}.market-icon{width:58px;height:58px;border-radius:17px;display:flex;align-items:center;justify-content:center;margin-bottom:14px}.market-icon svg{width:34px;height:34px;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.spot{background:rgba(35,220,142,.12);color:#38e39a}.futures{background:rgba(53,148,255,.12);color:#55a9ff}.contracts{background:rgba(168,92,255,.12);color:#b276ff}.american{background:rgba(67,139,255,.12);color:#65a8ff}.saudi{background:rgba(30,190,123,.12);color:#42d99a}.forex{background:rgba(244,183,72,.12);color:#f3bf55}.card{background:linear-gradient(145deg,#0b1828,#08121e);border:1px solid #182f46;border-radius:18px;padding:17px;box-shadow:0 12px 32px rgba(0,0,0,.12)}.card h2,.card h3{margin-top:4px}.muted{color:#8196ad}.buy{color:#35e39a}.gold{color:#f5c451}.danger{color:#ff6878}.stat{font-size:30px;font-weight:900}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.statbox{padding:16px;border-radius:16px;background:#091522;border:1px solid #172d43}.statbox small{display:block;color:#71869d;margin-bottom:7px}.btn{border:1px solid #21425f;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 15px;border-radius:12px;font-weight:800}.primary{background:linear-gradient(135deg,#1577dd,#1762b8);border-color:#2688ed}.goldbg{background:#9b721c}.pill{display:inline-flex;align-items:center;padding:5px 9px;border-radius:999px;background:#10243a;border:1px solid #1d3d5a;color:#a9c2da;font-size:12px;font-weight:800}.signal{border-right:3px solid #35e39a}.signal-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.rank{font-weight:900;color:#f5c451}.price-row{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:13px 0}.price-box{padding:10px;border-radius:12px;background:#08111d;border:1px solid #14283c}.price-box small{display:block;color:#71869d;margin-bottom:4px}.price-box b{font-size:13px}.table{width:100%;border-collapse:collapse}.table td,.table th{padding:11px;border-bottom:1px solid #162d43;text-align:right}.footer{padding:35px 18px;text-align:center;color:#667d95}.section-title{display:flex;align-items:end;justify-content:space-between;gap:10px;margin:28px 0 12px}.section-title h2{margin:0}.top-opportunity{border:1px solid rgba(245,196,81,.25);box-shadow:0 12px 40px rgba(245,196,81,.06)}input,textarea,select{width:100%;padding:12px;margin:6px 0;background:#07111f;color:white;border:1px solid #274666;border-radius:10px}@media(max-width:900px){.market-grid{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.wrap{padding:12px}.brandbar{padding-bottom:9px}.brand{font-size:20px}.nav a{padding:9px 11px;font-size:13px}.hero{padding:22px;border-radius:19px}.market-grid{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.price-row{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}"""
def icon(kind):
    paths={
      "home":'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
      "trade":'<path d="M4 17 9 12l4 3 7-8"/><path d="M17 7h3v3"/>',
      "scan":'<circle cx="11" cy="11" r="6"/><path d="m16 16 5 5"/>',
      "spot":'<circle cx="12" cy="12" r="8"/><path d="M8 12h8M12 8v8"/>',
      "futures":'<path d="M4 16V8m5 11V5m6 14v-8m5 5V4"/><path d="m3 12 5-5 4 3 7-7"/>',
      "contract":'<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h5M9 13h6M9 17h6"/>',
      "us":'<path d="M4 18V7h16v11"/><path d="M7 11h10M7 14h10"/><path d="m6 7 2-3 2 3 2-3 2 3 2-3 2 3"/>',
      "sa":'<path d="M4 18V9h16v9"/><path d="M8 9V5h8v4M7 14h10"/>',
      "fx":'<circle cx="9" cy="10" r="5"/><circle cx="15" cy="14" r="5"/><path d="m12 7 2-2m-2 12 2 2"/>',
      "news":'<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
      "blog":'<path d="M5 3h11l3 3v15H5z"/><path d="M9 12h6M9 16h6M16 3v4h3"/>',
      "star":'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
      "user":'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
      "admin":'<path d="M12 3 20 6v6c0 5-3.3 8-8 9-4.7-1-8-4-8-9V6z"/><path d="m9 12 2 2 4-5"/>',
      "login":'<path d="M10 17l5-5-5-5M15 12H3"/><path d="M13 3h6v18h-6"/>'
    }
    return f'<span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true">{paths.get(kind,"")}</svg></span>'
def page(req,title,body):
    u=user(req); role=u["role"] if u else ""
    nav=[("home","الرئيسية","/"),("trade","الصفقات","/trades"),("trade","بوت السبوت","/bot"),("scan","الماسح","/scanner"),("spot","السبوت","/market/spot"),("futures","الفيوتشر","/market/futures"),("contract","العقود","/market/contracts"),("us","الأمريكي","/market/american"),("sa","السعودي","/market/saudi"),("fx","فوركس وذهب","/market/forex"),("news","الأخبار","/news"),("blog","المدونة","/blog"),("star","الاشتراكات","/subscriptions")]
    if u:nav += [("user","حسابي","/account"),("support","الدعم الفني","/support")]
    if role=="admin":nav += [("admin","الإدارة","/admin"),("support","طلبات الدعم","/admin/support")]
    if not u:nav += [("login","دخول","/login"),("user","تسجيل","/register")]
    n="".join(f'<a href="{x[2]}">{icon(x[0])}<span>{x[1]}</span></a>' for x in nav)
    canonical=str(req.url).split("?")[0]
    desc="منصة مضارب ذكي PRO لتحليل الأسواق والإشارات والصفقات متعددة الفريمات."
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{esc(desc)}"><meta name="robots" content="index,follow"><link rel="canonical" href="{esc(canonical)}"><meta property="og:title" content="{esc(title)} | مضارب ذكي PRO"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="website"><title>{esc(title)} | مضارب ذكي PRO</title><style>{CSS}.support-fab{{position:fixed;left:18px;bottom:18px;width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:24px;background:linear-gradient(135deg,#111827,#2563eb);border:1px solid rgba(255,255,255,.18);box-shadow:0 10px 30px rgba(0,0,0,.35);z-index:9999}}.support-fab:hover{{transform:translateY(-2px)}}@media(max-width:600px){{.support-fab{{left:14px;bottom:14px;width:50px;height:50px;font-size:22px}}}}</style><header class="top"><div class="wrap"><div class="brandbar"><div><span class="brandmark">{icon("trade")}</span><span class="brand">مضارب ذكي <span class="pro">PRO</span></span><small>منصة تحليل أسواق متعددة</small></div></div><nav class="nav">{n}</nav></div></header><main class="wrap">{body}</main><a class="support-fab" href="/support" title="الدعم الفني" aria-label="الدعم الفني">💬</a><footer class="footer">مضارب ذكي PRO · تحليل وفرز أسواق متعددة</footer></html>'''
def require(req,role=None):
    u=user(req)
    if not u:return RedirectResponse("/login",303)
    if role and u["role"]!=role:return RedirectResponse("/",303)
    return u

@app.get("/",response_class=HTMLResponse)
def home(req:Request):
    sig=db().execute("SELECT * FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 12").fetchall()
    def medal(i):return "👑" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else f"#{i}"))
    cards="".join(f'<div class="card signal"><div class="gold">{medal(i)}</div><h3>{esc(x["symbol"])}</h3><div class="{("buy" if x["side"]=="BUY" else "danger")}">{("شراء" if x["side"]=="BUY" else "بيع")}</div><p>دخول {float(x["entry"] or 0):.6g} · وقف {float(x["stop"] or 0):.6g} · TP1 {float(x["tp1"] or 0):.6g} · TP2 {float(x["tp2"] or 0):.6g} · TP3 {float(x["tp3"] or 0):.6g}</p><p>تغير 5د: <b>{float(x["change15"] or 0):.2f}%</b></p><p>AI%: <b>{float(x["confidence"] or 0):.0f}%</b></p></div>' for i,x in enumerate(sig,1))
    body=f'<section class="hero"><h1>مضارب ذكي <span class="gold">PRO</span></h1><p class="muted">محرك بيانات متعدد الأسواق · كل فريم يطبق الاستراتيجية بشكل مستقل · ترتيب حسب أقوى تغير.</p><a class="btn primary" href="/scanner">🔎 ابدأ الفحص</a></section><a href="https://t.me/tadol1" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div class="card" style="margin:18px 0;border:1px solid rgba(37,99,235,.35);background:linear-gradient(135deg,rgba(37,99,235,.12),rgba(17,24,39,.5))"><h2 style="margin:0 0 6px">قناة مضارب ذكي</h2><p class="muted" style="margin:0">تابع الإشارات والتنبيهات وآخر تحديثات المنصة على قناتنا.</p><div style="margin-top:12px"><span class="btn primary">الدخول إلى القناة</span></div></div></a><h2>🏆 أفضل الفرص الآن</h2><div class="grid">{cards or "<div class=card>جاري جمع البيانات من محركات الأسواق...</div>"}</div>'
    return page(req,"الرئيسية",body)

@app.get("/market/{market}",response_class=HTMLResponse)
def market(req:Request,market:str,tf:str="all"):
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس والذهب"}
    if market not in names:return RedirectResponse("/",303)
    if tf not in TIMEFRAMES:tf="all"
    c=db();
    if tf=="all": rows=c.execute("SELECT * FROM signals WHERE market=? ORDER BY id DESC LIMIT 30",(market,)).fetchall()
    else: rows=c.execute("SELECT * FROM signals WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 30",(market,tf)).fetchall()
    tabs=" ".join(f'<a class="pill" href="/market/{market}?tf={x}">{x}</a>' for x in TIMEFRAMES)
    cards="".join(f'<div class="card signal"><h3>{esc(x["symbol"])}</h3><span class="pill">{("بيع" if x["side"]=="SELL" else "شراء")} · {esc(x["timeframe"])}</span><p>دخول: {x["entry"]:.5f}</p><p>وقف: {x["stop"]:.5f} · TP1: {x["tp1"]:.5f} · TP2: {x["tp2"]:.5f} · TP3: {x["tp3"]:.5f}</p><p>تغير الفريم: {x["change15"]:.2f}% · AI: {x["confidence"]:.0f}%</p></div>' for x in rows)
    return page(req,names[market],f'<h1>{names[market]}</h1><p class="muted">كل الفريمات — اختر الفريم لعرض صفقاته</p><div style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0">{tabs}</div><div class="grid">{cards or "<div class=card>لا توجد صفقات لهذا الفريم حاليًا.</div>"}</div>')

@app.get("/scanner",response_class=HTMLResponse)
def scanner(req:Request,tf:str="all"):
    if tf not in TIMEFRAMES:tf="all"
    c=db();
    if tf=="all": rows=c.execute("SELECT market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,created_at FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100").fetchall()
    else: rows=c.execute("SELECT market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,created_at FROM signals WHERE status='open' AND timeframe=? ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100",(tf,)).fetchall()
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"الأمريكي","saudi":"السعودي","forex":"فوركس وذهب"}
    tabs=" ".join(f'<a class="pill" href="/scanner?tf={x}">{x}</a>' for x in TIMEFRAMES)
    cards="".join(f'<div class="card signal"><div class="gold"><b>#{i}</b> · {names.get(x["market"],x["market"])}</div><h3>{esc(x["symbol"])}</h3><div class="{("buy" if x["side"]=="BUY" else "danger")}">{esc(x["side"])} · {esc(x["timeframe"])}</div><p>دخول {x["entry"]:.6g} · وقف {x["stop"]:.6g} · TP1 {x["tp1"]:.6g} · TP2 {x["tp2"]:.6g} · TP3 {x["tp3"]:.6g}</p><p>تغير الفريم: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(rows,1))
    return page(req,"الماسح",f'<div class="hero"><h1>الماسح الذكي</h1><p>كل الأسواق · كل الفريمات · كل فريم يطبق الاستراتيجية بشكل مستقل</p><div style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0">{tabs}</div></div><div class="grid">{cards or "<div class=card>لا توجد إشارات لهذا الفريم حاليًا.</div>"}</div>')
@app.get("/trades",response_class=HTMLResponse)
def trades_page(req:Request):
    c=db()
    open_rows=c.execute("SELECT * FROM trades WHERE status='open' ORDER BY confidence DESC, id DESC LIMIT 100").fetchall()
    recent=c.execute("SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC, id DESC LIMIT 20").fetchall()
    closed=c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_pct),0) pnl FROM trades WHERE status='closed'").fetchone()
    def period_stats(days):
        cutoff=(datetime.now(timezone.utc)-__import__("datetime").timedelta(days=days)).isoformat()
        r=c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_pct),0) pnl FROM trades WHERE status='closed' AND closed_at>=?",(cutoff,)).fetchone()
        return int(r["n"] or 0),float(r["pnl"] or 0)
    day_n,day_pnl=period_stats(1); week_n,week_pnl=period_stats(7); month_n,month_pnl=period_stats(30); year_n,year_pnl=period_stats(365)
    wins=c.execute("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl_pct>0").fetchone()["n"]
    losses=c.execute("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl_pct<=0").fetchone()["n"]
    total=closed["n"] or 0
    winrate=(wins/total*100) if total else 0

    def num(v):
        return "—" if v is None else f"{float(v):.8g}"
    def pct(v):
        return "—" if v is None else f"{float(v):+.2f}%"
    def market_label(m):
        return {"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"الأمريكي","saudi":"السعودي","forex":"فوركس وذهب"}.get(m,m)
    def trade_card(x,i):
        tps=[x["tp1"],x["tp2"],x["tp3"]]
        entry=float(x["entry"] or 0); stop=float(x["stop"] or 0); side=x["side"] or "BUY"
        is_sell=side=="SELL"
        stop_pct=((entry-stop)/entry*100) if is_sell and entry else ((stop-entry)/entry*100 if entry else 0)
        def level_pct(v):
            if not entry or v is None:return 0
            return ((entry-float(v))/entry*100) if is_sell else ((float(v)-entry)/entry*100)
        tp_html="".join(f'<div class="tp-item"><span>TP{j}</span><b>{num(v)}</b><em>{level_pct(v):+.2f}%</em></div>' for j,v in enumerate(tps,1) if v is not None)
        direction="بيع" if is_sell else "شراء"
        tone="sell" if is_sell else "buy"
        return f'''
        <article class="trade-card {tone}">
          <div class="trade-top">
            <div class="rank">{("👑" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i:02d}")}</div>
            <div class="asset"><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])} · {esc(x["timeframe"] or "—")}</span></div>
            <div class="direction"><b>{direction}</b><small>● مفتوحة</small><em>صفقة ذكية</em></div>
          </div>
          <div class="trade-entry">
            <div><small>الدخول</small><strong>{num(x["entry"])}</strong></div>
            <div class="ai"><small>AI</small><strong>{float(x["confidence"] or 0):.0f}%</strong></div>
          </div>
          <div class="risk-row">
            <div class="stop-box"><span>🛑 وقف الخسارة</span><b>{num(x["stop"])}</b><em>{stop_pct:+.2f}%</em></div>
          </div>
          <div class="targets-title"><span>الأهداف</span><small>الربح المحتمل من الدخول</small></div>
          <div class="targets">{tp_html}</div>
          <div class="trade-meta"><span>تغير الفريم <b>{pct(x["change15"])}</b></span><span>فتح {esc((x["opened_at"] or "")[:16])}</span></div>
        </article>'''
    def closed_card(x):
        pnl=float(x["pnl_pct"] or 0)
        cls="profit" if pnl>0 else "loss"
        return f'<div class="closed-row"><div><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])}</span></div><div><span>{esc(x["side"] or "BUY")}</span><span>{esc(x["closed_at"] or "")[:16]}</span></div><b class="{cls}">{pnl:+.2f}%</b></div>'

    cards="".join(trade_card(x,i) for i,x in enumerate(open_rows,1))
    history="".join(closed_card(x) for x in recent)
    body=f'''
    <style>
      .trades-wrap{{max-width:1220px;margin:auto}}
      .trades-hero{{padding:28px 0 20px;display:flex;justify-content:space-between;align-items:end;gap:18px}}
      .trades-hero h1{{margin:0;font-size:clamp(28px,4vw,42px);letter-spacing:-1.4px}}
      .trades-hero p{{margin:8px 0 0;color:#8290a4}}
      .live-dot{{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid #223047;border-radius:999px;background:#0c1521;color:#b8c4d4;font-size:12px}}
      .live-dot i{{width:7px;height:7px;border-radius:50%;background:#2fe08a;box-shadow:0 0 12px #2fe08a}}
      .trade-stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:4px 0 30px}}
      .trade-stat{{padding:17px 18px;border:1px solid #1e2b3d;background:#0c1521;border-radius:16px}}
      .trade-stat small{{display:block;color:#718097;margin-bottom:8px}}.trade-stat strong{{font-size:24px}}.trade-stat .green{{color:#38dc91}}.trade-stat .red{{color:#ff6678}}
      .section-title{{display:flex;justify-content:space-between;align-items:center;margin:24px 0 12px}}.section-title h2{{margin:0;font-size:20px}}.section-title span{{color:#718097;font-size:12px}}
      .trade-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
      .trade-card{{position:relative;overflow:hidden;border:1px solid #263a52;border-radius:22px;background:radial-gradient(circle at 100% 0,#172a3d 0,#111d2b 35%,#09121d 78%);padding:19px;box-shadow:0 18px 45px rgba(0,0,0,.22)}}
      .trade-card:after{{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:#29d789}}.trade-card.sell:after{{background:#ff5e70}}
      .trade-top{{display:flex;align-items:center;gap:11px}}.rank{{width:38px;height:38px;display:grid;place-items:center;border-radius:12px;background:#172438;font-size:15px;font-weight:900}}.asset{{flex:1;min-width:0}}.asset strong{{display:block;font-size:19px}}.asset span{{display:block;color:#718097;font-size:11px;margin-top:3px}}.direction{{text-align:left;min-width:76px}}.direction b{{display:block;font-size:12px;color:#35dc91}}.trade-card.sell .direction b{{color:#ff6879}}.direction small{{display:block;color:#69778d;font-size:10px;margin-top:3px}}.direction em{{display:inline-block;margin-top:6px;padding:3px 7px;border-radius:999px;background:#173126;color:#55dfa2;font-size:8px;font-style:normal}}.trade-card.sell .direction em{{background:#351d25;color:#ff8290}}
      .trade-entry{{display:grid;grid-template-columns:1fr 92px;gap:9px;margin-top:15px}}.trade-entry>div{{padding:13px 14px;border:1px solid #1b2a3d;background:#0b1521;border-radius:14px}}.trade-entry small{{display:block;color:#708097;font-size:10px}}.trade-entry strong{{display:block;font-size:21px;margin-top:5px}}.trade-entry .ai{{text-align:center;border-color:#24403a}}.trade-entry .ai strong{{color:#45dfa0;font-size:20px}}
      .risk-row{{margin-top:9px}}.stop-box{{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:10px;padding:11px 13px;background:#15151e;border:1px solid #39232c;border-radius:12px}}.stop-box span{{color:#a6aebe;font-size:11px}}.stop-box b{{color:#ff7180;font-size:13px}}.stop-box em{{color:#ff7180;font-size:11px;font-style:normal}}
      .targets-title{{display:flex;justify-content:space-between;align-items:center;margin:16px 2px 8px}}.targets-title span{{font-size:13px;font-weight:800}}.targets-title small{{color:#65748a;font-size:10px}}.targets{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}}.tp-item{{text-align:center;padding:10px 5px;border:1px solid #1d3540;background:#0b1920;border-radius:11px}}.tp-item span{{display:block;color:#55dca4;font-size:10px;font-weight:800}}.tp-item b{{display:block;font-size:13px;margin:4px 0}}.tp-item em{{font-style:normal;color:#42d99b;font-size:11px}}
      .trade-meta{{display:flex;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid #192638;color:#68778d;font-size:10px}}.trade-meta b{{color:#cdd7e4}}
      .closed-list{{border:1px solid #202d3f;border-radius:16px;overflow:hidden;background:#0d1622}}.closed-row{{display:grid;grid-template-columns:1fr 1fr auto;align-items:center;gap:10px;padding:13px 15px;border-bottom:1px solid #1a2636}}.closed-row:last-child{{border-bottom:0}}.closed-row strong,.closed-row span{{display:block}}.closed-row span{{color:#77869b;font-size:11px;margin-top:3px}}.closed-row>div:nth-child(2){{display:flex;gap:15px}}.closed-row .profit{{color:#35d98a}}.closed-row .loss{{color:#ff6574}}.empty-trades{{padding:40px;text-align:center;color:#7f8da3;border:1px dashed #26364c;border-radius:16px;background:#0c1520}}
      @media(max-width:800px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-grid{{grid-template-columns:1fr}}.trades-hero{{align-items:flex-start;flex-direction:column}}}}
      @media(max-width:520px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-entry{{grid-template-columns:1fr 82px}}.trade-entry strong{{font-size:18px}}.stop-box{{grid-template-columns:1fr auto}}.stop-box em{{grid-column:2}}.targets-title small{{display:none}}.trade-meta{{flex-wrap:wrap}}.closed-row{{grid-template-columns:1fr auto}}.closed-row>div:nth-child(2){{display:none}}}}
    </style>
    <div class="trades-wrap">
      <div class="trades-hero"><div><h1>متابع الصفقات</h1><p>مراقبة الصفقات المفتوحة والنتائج الفعلية بشكل واضح وسريع.</p></div><div class="live-dot"><i></i> بيانات حية</div></div>
      <div class="trade-stats">
        <div class="trade-stat"><small>مفتوحة</small><strong>{len(open_rows)}</strong></div>
        <div class="trade-stat"><small>مغلقة</small><strong>{total}</strong></div>
        <div class="trade-stat"><small>رابحة</small><strong class="green">{wins}</strong></div>
        <div class="trade-stat"><small>خاسرة</small><strong class="red">{losses}</strong></div>
        <div class="trade-stat"><small>نسبة النجاح</small><strong>{winrate:.1f}%</strong></div><div class="trade-stat"><small>اليوم</small><strong class="{'green' if day_pnl>=0 else 'red'}">{day_pnl:+.2f}%</strong></div><div class="trade-stat"><small>الأسبوع</small><strong class="{'green' if week_pnl>=0 else 'red'}">{week_pnl:+.2f}%</strong></div><div class="trade-stat"><small>الشهر</small><strong class="{'green' if month_pnl>=0 else 'red'}">{month_pnl:+.2f}%</strong></div><div class="trade-stat"><small>السنة</small><strong class="{'green' if year_pnl>=0 else 'red'}">{year_pnl:+.2f}%</strong></div>
      </div>
      <div class="section-title"><h2>الصفقات المفتوحة</h2><span>{len(open_rows)} صفقة · مرتبة حسب AI%</span></div>
      <div class="trade-grid">{cards or '<div class="empty-trades">ما فيه صفقات مفتوحة حاليًا.</div>'}</div>
      <div class="section-title"><h2>آخر الصفقات المغلقة</h2><span>آخر 20 صفقة</span></div>
      <div class="closed-list">{history or '<div class="empty-trades">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>
    </div>'''
    return page(req,"متابع الصفقات",body)
@app.get("/register",response_class=HTMLResponse)
def register_form(req:Request):
    return page(req,"تسجيل",'<div class="card"><h2>إنشاء حساب</h2><form method="post"><input name="name" placeholder="الاسم"><input name="email" type="text" placeholder="البريد أو اسم المدير"><input name="password" type="password" placeholder="كلمة المرور"><button class="btn primary">تسجيل</button></form></div>')
@app.post("/register")
def register(req:Request,name:str=Form(""),email:str=Form(""),password:str=Form("")):
    email=email.strip().lower(); name=name.strip()
    if not email or not password or len(password)<6:
        return RedirectResponse("/register",303)
    c=db()
    try:
        c.execute("INSERT INTO users(email,password,name,created_at) VALUES(?,?,?,?)",(email,pwd.hash(password),name,now()))
        c.commit()
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        c.rollback()
        return RedirectResponse("/register",303)
    return RedirectResponse("/login",303)
@app.get("/login",response_class=HTMLResponse)
def login_form(req:Request):
    return page(req,"دخول",'<div class="card"><h2>تسجيل الدخول</h2><form method="post"><input name="email" type="text" placeholder="البريد أو اسم المدير"><input name="password" type="password" placeholder="كلمة المرور"><button class="btn primary">دخول</button></form></div>')
@app.post("/login")
def login(req:Request,email:str=Form(""),password:str=Form("")):
    login_value=email.strip()
    c=db()
    u=c.execute("SELECT * FROM users WHERE active=1 AND (lower(email)=? OR lower(name)=?)",(login_value.lower(),login_value.lower())).fetchone()
    if not u or not pwd.verify(password,u["password"]):return RedirectResponse("/login",303)
    req.session["uid"]=u["id"]
    return RedirectResponse("/admin" if u["role"]=="admin" else "/",303)
@app.get("/logout")
def logout(req:Request):req.session.clear();return RedirectResponse("/",303)
@app.get("/support",response_class=HTMLResponse)
def support(req:Request):
    u=require(req)
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT * FROM support_tickets WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    cards="".join(f'<div class="card"><h3>طلب #{x["id"]} — {("مفتوح" if x["status"]=="open" else "مغلق")}</h3><p>{esc(x["message"])}</p><p class="muted">{esc(x["admin_reply"] or "بانتظار رد الإدارة")}</p></div>' for x in rows)
    body=f'<div class="hero"><h1>الدعم الفني</h1><p>إذا عندك مشكلة أو تبي تتواصل مع الإدارة، ارسل طلبك هنا.</p><form method="post" action="/support"><textarea name="message" required placeholder="اكتب رسالتك للإدارة" style="min-height:140px"></textarea><button class="btn primary">إرسال للإدارة</button></form></div><h2>طلباتك السابقة</h2><div class="grid">{cards or "<div class=card>ما عندك طلبات دعم سابقة.</div>"}</div>'
    return page(req,"الدعم الفني",body)

@app.post("/support")
def support_post(req:Request,message:str=Form("")):
    u=require(req)
    if not hasattr(u,"__getitem__"): return u
    msg=message.strip()
    if not msg:return RedirectResponse("/support",303)
    c=db();c.execute("INSERT INTO support_tickets(user_id,name,email,message,created_at,updated_at) VALUES(?,?,?,?,?,?)",(u["id"],u["name"],u["email"],msg,now(),now()));c.commit()
    return RedirectResponse("/support",303)

@app.get("/account",response_class=HTMLResponse)
def account(req:Request):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    c=db(); c.execute("UPDATE subscriptions SET status='expired' WHERE user_id=? AND status='active' AND expires_at IS NOT NULL AND expires_at<=?",(u["id"],now())); c.commit(); subs=c.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
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
    features=[("accounts","الحسابات والتسجيل"),("trades","الصفقات"),("scanner","الماسح الذكي"),("bot","بوت السبوت"),("spot","السبوت"),("futures","الفيوتشر"),("contracts","العقود"),("american","السوق الأمريكي"),("saudi","السوق السعودي"),("forex","الفوركس والذهب"),("news","الأخبار"),("blog","المدونة"),("subscriptions","الاشتراكات"),("support","الدعم الفني"),("telegram","تيليجرام")]
    feature_cards="".join(f'<div class="card"><div class="section-title"><b>{label}</b><span class="pill {("buy" if feature_enabled(key) else "danger")}">{("مفتوح" if feature_enabled(key) else "مغلق")}</span></div><form method="post" action="/admin/feature/{key}"><button class="btn {("primary" if not feature_enabled(key) else "")}">{("فتح القسم" if not feature_enabled(key) else "إغلاق القسم")}</button></form></div>' for key,label in features)
    body=f'<h1>لوحة الإدارة</h1><div class="grid"><div class="card"><div class="stat">{users}</div>حسابات</div><div class="card"><div class="stat">{payments}</div>طلبات دفع معلقة</div><div class="card"><div class="stat">{sig}</div>توصيات</div></div><div class="card"><h2>التحكم الكامل بالخدمات</h2><p class="muted">تقدر تفتح أو تقفل أي قسم مباشرة من هنا.</p><div class="grid">{feature_cards}</div></div><div class="card"><h2>تشغيل الفحص</h2><form method="post" action="/admin/scan"><button class="btn primary">فحص جميع الأسواق الآن</button></form></div><div class="card"><h2>إضافة رمز للسكانر</h2><form method="post" action="/admin/symbol"><select name="market"><option>spot</option><option>futures</option><option>contracts</option><option>american</option><option>saudi</option><option>forex</option></select><input name="symbol" placeholder="رمز السوق"><button class="btn">إضافة</button></form></div><div class="card"><a class="btn" href="/admin/users">إدارة الحسابات</a> <a class="btn" href="/admin/payments">إدارة المدفوعات</a> <a class="btn" href="/bot">بوت السبوت</a></div>'
    return page(req,"الإدارة",body)
@app.get("/admin/users",response_class=HTMLResponse)
def admin_users(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id DESC").fetchall()
    cards=[]
    for x in rows:
        state="نشط" if x["active"] else "موقوف"
        action="إيقاف" if x["active"] else "تفعيل"
        role_action="إلغاء المدير" if x["role"]=="admin" else "تعيين مدير"
        cards.append(f'<div class="card"><h3>{esc(x["name"] or x["email"])}</h3><p>{esc(x["email"])}</p><p>الصلاحية: {esc(x["role"])} · الحالة: {state}</p><a class="btn" href="/admin/user/{x["id"]}/toggle">{action}</a> <a class="btn" href="/admin/user/{x["id"]}/role">{role_action}</a></div>')
    return page(req,"إدارة الحسابات",'<h1>إدارة الحسابات</h1><div class="grid">'+''.join(cards)+'</div>')

@app.get("/admin/user/{uid}/toggle")
def admin_user_toggle(req:Request,uid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db(); c.execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND id<>?",(uid,u["id"])); c.commit()
    return RedirectResponse("/admin/users",303)

@app.get("/admin/user/{uid}/role")
def admin_user_role(req:Request,uid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db(); c.execute("UPDATE users SET role=CASE role WHEN 'admin' THEN 'user' ELSE 'admin' END WHERE id=? AND id<>?",(uid,u["id"])); c.commit()
    return RedirectResponse("/admin/users",303)

@app.post("/admin/feature/{key}")
def admin_feature(req:Request,key:str):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    if key not in FEATURE_DEFAULTS: return RedirectResponse("/admin",303)
    set_feature(key,not feature_enabled(key))
    return RedirectResponse("/admin",303)

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
@app.get("/admin/support",response_class=HTMLResponse)
def admin_support(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT * FROM support_tickets ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, id DESC").fetchall()
    body='<h1>الدعم الفني</h1><div class="grid">'+''.join(f'<div class="card"><h3>#{x["id"]} · {esc(x["name"] or x["email"])}</h3><p class="muted">{esc(x["email"])} · {esc(x["created_at"])}</p><p>{esc(x["message"])}</p><p class="muted">{esc(x["admin_reply"] or "لا يوجد رد بعد")}</p><form method="post" action="/admin/support/{x["id"]}/reply"><textarea name="reply" required placeholder="رد الإدارة"></textarea><button class="btn primary">إرسال الرد</button></form></div>' for x in rows)+'</div>'
    return page(req,"الدعم الفني",body)

@app.post("/admin/support/{tid}/reply")
def admin_support_reply(req:Request,tid:int,reply:str=Form("")):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db();c.execute("UPDATE support_tickets SET admin_reply=?,status='closed',updated_at=? WHERE id=?",(reply.strip(),now(),tid));c.commit()
    return RedirectResponse("/admin/support",303)

@app.get("/admin/payments",response_class=HTMLResponse)
def payments(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    rows=db().execute("SELECT p.*,u.email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC").fetchall()
    body='<div class="card"><h1>المدفوعات</h1><table class="table"><tr><th>المستخدم</th><th>الخطة</th><th>المبلغ</th><th>الحالة</th><th></th></tr>'+''.join(f'<tr><td>{esc(x["email"])}</td><td>{x["plan"]}</td><td>{x["amount"]}</td><td>{x["status"]}</td><td><a class="btn" href="/admin/payment/{x["id"]}/approve">اعتماد</a> <a class="btn" href="/admin/payment/{x["id"]}/reject">رفض</a></td></tr>' for x in rows)+'</table></div>'
    return page(req,"المدفوعات",body)
@app.get("/admin/payment/{pid}/reject")
def reject_payment(req:Request,pid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db(); c.execute("UPDATE payments SET status='rejected' WHERE id=?",(pid,)); c.commit()
    return RedirectResponse("/admin/payments",303)
@app.get("/admin/payment/{pid}/approve")
def approve(req:Request,pid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db();p=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
    if p:
        c.execute("UPDATE payments SET status='approved' WHERE id=?",(pid,))
        days=int(str(p["plan"]).split()[0]);created=now(); expires=(datetime.now(timezone.utc)+__import__("datetime").timedelta(days=days)).isoformat(); c.execute("INSERT INTO subscriptions(user_id,plan,days,price,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",(p["user_id"],p["plan"],days,p["amount"],"active",created,expires));c.commit()
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
    body=f'<article class="card"><h1>{esc(x["title"])}</h1><p class="muted">{esc(x["source"])} · {esc(x["published"])}</p><div style="line-height:2">{esc(x["body"] or "خبر سوقي محفوظ في قاعدة المنصة.").replace(chr(10),"<br>")}</div><a class="btn" href="/news">رجوع للأخبار</a></article>'
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
            if not feature_enabled("news"):
                time.sleep(60); continue
            xml=get("https://feeds.bbci.co.uk/arabic/rss.xml");root=ET.fromstring(xml)
            c=db()
            for item in root.findall(".//item")[:20]:
                t=item.findtext("title") or "";u=item.findtext("link") or "";d=item.findtext("pubDate") or "";desc=item.findtext("description") or ""
                if t and not c.execute("SELECT 1 FROM news WHERE url=?",(u,)).fetchone():c.execute("INSERT INTO news(title,url,source,published,body) VALUES(?,?,?,?,?)",(t,u,"BBC عربي",d,desc))
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
    threading.Thread(target=_scan_loop,daemon=True).start()
@app.get("/robots.txt")
def robots(): return HTMLResponse("User-agent: *\
Allow: /\
Sitemap: /sitemap.xml",media_type="text/plain")
@app.get("/sitemap.xml")
def sitemap(req:Request):
    base=str(req.base_url).rstrip("/"); urls=["/","/trades","/scanner","/market/spot","/market/futures","/market/contracts","/market/american","/market/saudi","/market/forex","/news","/blog","/subscriptions","/login","/register"]
    c=db()
    for x in c.execute("SELECT id FROM news ORDER BY id DESC LIMIT 500").fetchall(): urls.append(f"/news/{x['id']}")
    for x in c.execute("SELECT slug FROM posts WHERE status='published' ORDER BY id DESC LIMIT 500").fetchall(): urls.append("/blog/"+urllib.parse.quote(x["slug"]))
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{esc(base+u)}</loc></url>" for u in urls)+'</urlset>'
    return HTMLResponse(xml,media_type="application/xml")
@app.get("/health")
def health():
    checks={}
    try:
        c=db(); c.execute("SELECT 1").fetchone(); checks["database"]="ok"
    except Exception: checks["database"]="error"
    checks["telegram"]="on" if feature_enabled("telegram") else "off"
    checks["scanner"]="on" if feature_enabled("scanner") else "off"
    checks["bot"]="on" if feature_enabled("bot") else "off"
    checks["markets"]={k:("on" if feature_enabled(k) else "off") for k in ("spot","futures","contracts","american","saudi","forex")}
    checks["data_cache_entries"]=len(_DATA_CACHE)
    return {"ok":True,"service":"mudarib-smart-pro","time":now(),"database":DB,"checks":checks}
if __name__=="__main__":
    import uvicorn;uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
