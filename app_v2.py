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
            cur=c.execute("INSERT INTO signals(market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",(market,s,"BUY","15m",x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,f"الترتيب #{rank} · {x['reason']}",now()))
            sid=cur.lastrowid
            if not c.execute("SELECT 1 FROM trades WHERE market=? AND symbol=? AND status='open'",(market,s)).fetchone():
                c.execute("INSERT INTO trades(signal_id,market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,status,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sid,market,s,"BUY","15m",x["entry"],x["tp"],x["stop"],x["tp1"],x["tp2"],x["tp3"],x["confidence"],ch,"open",now()))
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
    nav=[("home","الرئيسية","/"),("trade","الصفقات","/trades"),("scan","الماسح","/scanner"),("spot","السبوت","/market/spot"),("futures","الفيوتشر","/market/futures"),("contract","العقود","/market/contracts"),("us","الأمريكي","/market/american"),("sa","السعودي","/market/saudi"),("fx","فوركس وذهب","/market/forex"),("news","الأخبار","/news"),("blog","المدونة","/blog"),("star","الاشتراكات","/subscriptions")]
    if u:nav += [("user","حسابي","/account")]
    if role=="admin":nav += [("admin","الإدارة","/admin")]
    if not u:nav += [("login","دخول","/login"),("user","تسجيل","/register")]
    n="".join(f'<a href="{x[2]}">{icon(x[0])}<span>{x[1]}</span></a>' for x in nav)
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | مضارب ذكي PRO</title><style>{CSS}</style><header class="top"><div class="wrap"><div class="brandbar"><div><span class="brandmark">{icon("trade")}</span><span class="brand">مضارب ذكي <span class="pro">PRO</span></span><small>منصة تحليل أسواق متعددة</small></div></div><nav class="nav">{n}</nav></div></header><main class="wrap">{body}</main><footer class="footer">مضارب ذكي PRO · تحليل وفرز أسواق متعددة</footer></html>'''
def require(req,role=None):
    u=user(req)
    if not u:return RedirectResponse("/login",303)
    if role and u["role"]!=role:return RedirectResponse("/",303)
    return u

@app.get("/",response_class=HTMLResponse)
def home(req:Request):
    sig=db().execute("SELECT * FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 12").fetchall()
    def medal(i):return "👑" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else f"#{i}"))
    cards="".join(f'<div class="card signal"><div class="gold">{medal(i)}</div><h3>{esc(x["symbol"])}</h3><div class="buy">شراء</div><p>دخول {x["entry"]:.6g} · وقف {x["stop"]:.6g} · TP1 {x["tp1"]:.6g} · TP2 {x["tp2"]:.6g} · TP3 {x["tp3"]:.6g}</p><p>تغير 15د: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(sig,1))
    body=f'<section class="hero"><h1>مضارب ذكي <span class="gold">PRO</span></h1><p class="muted">محرك بيانات متعدد الأسواق · فلترة · استراتيجية 15 دقيقة · ترتيب حسب أقوى تغير.</p><a class="btn primary" href="/scanner">🔎 ابدأ الفحص</a></section><h2>🏆 أفضل الفرص الآن</h2><div class="grid">{cards or "<div class=card>جاري جمع البيانات من محركات الأسواق...</div>"}</div>'
    return page(req,"الرئيسية",body)

@app.get("/market/{market}",response_class=HTMLResponse)
def market(req:Request,market:str):
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس والذهب"}
    if market not in names:return RedirectResponse("/",303)
    c=db(); rows=c.execute("SELECT * FROM signals WHERE market=? ORDER BY id DESC LIMIT 30",(market,)).fetchall()
    body=f'<h1>{names[market]}</h1><p class="muted">15 دقيقة · شراء فقط · وقف وأهداف من القمم والقيعان الفعلية</p><div class="grid">'+''.join(f'<div class="card signal"><h3>{esc(x["symbol"])}</h3><span class="pill">BUY</span><p>دخول: {x["entry"]:.5f}</p><p>وقف: {x["stop"]:.5f} · TP1: {x["tp1"]:.5f} · TP2: {x["tp2"]:.5f} · TP3: {x["tp3"]:.5f}</p><p>تغير 15د: {x["change15"]:.2f}%</p><p>مطابقة: {x["confidence"]:.0f}%</p></div>' for x in rows)+'</div>'
    return page(req,names[market],body)

@app.get("/scanner",response_class=HTMLResponse)
def scanner(req:Request):
    rows=db().execute("SELECT market,symbol,side,timeframe,entry,tp,confidence,change15,created_at FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100").fetchall()
    names={"spot":"₿ السبوت","futures":"↕ الفيوتشر","contracts":"◫ العقود","american":"🇺🇸 الأمريكي","saudi":"🇸🇦 السعودي","forex":"💱 الفوركس والذهب"}
    cards="".join(f'<div class="card signal"><div class="gold"><b>#{i}</b> · {names.get(x["market"],x["market"])}</div><h3>{esc(x["symbol"])}</h3><div class="buy">BUY</div><p>دخول {x["entry"]:.6g} · وقف {x["stop"]:.6g} · TP1 {x["tp1"]:.6g} · TP2 {x["tp2"]:.6g} · TP3 {x["tp3"]:.6g}</p><p>تغير 15د: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(rows,1))
    return page(req,"الماسح",f'<div class="hero"><h1>🔎 الماسح الذكي</h1><p>كل سوق له محرك بيانات مستقل وعمّال متوازون. الترتيب يبدأ بأعلى تغير ثم شروط الاستراتيجية.</p></div><div class="grid">{cards}</div>')
@app.get("/trades",response_class=HTMLResponse)
def trades_page(req:Request):
    c=db()
    open_rows=c.execute("SELECT * FROM trades WHERE status='open' ORDER BY confidence DESC, id DESC LIMIT 100").fetchall()
    recent=c.execute("SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC, id DESC LIMIT 20").fetchall()
    closed=c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_pct),0) pnl FROM trades WHERE status='closed'").fetchone()
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
        entry=float(x["entry"] or 0)
        stop=float(x["stop"] or 0)
        stop_pct=((entry-stop)/entry*100) if entry else 0
        tp_html="".join(f'<div class="tp-item"><span>TP{j}</span><b>{num(v)}</b><em class="level-profit">+{((float(v)-entry)/entry*100):.2f}%</em></div>' for j,v in enumerate(tps,1) if v is not None)
        return f'''
        <article class="trade-card">
          <div class="trade-head">
            <div class="rank-badge">{i:02d}</div>
            <div class="symbol-block"><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])} · {esc(x["timeframe"] or "15m")}</span></div>
            <div class="status-live"><i></i> مفتوحة</div>
          </div>
          <div class="trade-main">
            <div class="entry-box"><small>سعر الدخول</small><strong>{num(x["entry"])}</strong><span>BUY</span></div>
            <div class="levels">
              <div class="level stop"><span>وقف حقيقي <small>−{stop_pct:.2f}%</small></span><b>{num(x["stop"])}</b></div>
              <div class="tp-row">{tp_html}</div>
            </div>
          </div>
          <div class="trade-foot">
            <span>AI <b>{float(x["confidence"] or 0):.0f}%</b></span>
            <span>تغير 15د <b>{pct(x["change15"])}</b></span>
            <span>فتح <b>{esc((x["opened_at"] or "")[:16])}</b></span>
          </div>
        </article>'''
    def closed_card(x):
        pnl=float(x["pnl_pct"] or 0)
        cls="profit" if pnl>0 else "loss"
        return f'<div class="closed-row"><div><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])}</span></div><div><span>{esc(x["side"] or "BUY")}</span><span>{esc(x["closed_at"] or "")[:16]}</span></div><b class="{cls}">{pnl:+.2f}%</b></div>'

    cards="".join(trade_card(x,i) for i,x in enumerate(open_rows,1))
    history="".join(closed_card(x) for x in recent)
    body=f'''
    <style>
      .trades-wrap{{max-width:1180px;margin:auto}}
      .trades-hero{{padding:24px 0 18px;display:flex;justify-content:space-between;gap:18px;align-items:flex-end}}
      .trades-hero h1{{margin:0;font-size:clamp(26px,4vw,40px);letter-spacing:-1px}}
      .trades-hero p{{margin:8px 0 0;color:#8f9bb0}}
      .live-dot{{display:inline-flex;align-items:center;gap:8px;padding:9px 13px;border:1px solid #233247;border-radius:999px;background:#0d1622;color:#aab7c9;font-size:13px}}
      .live-dot i,.status-live i{{width:7px;height:7px;border-radius:50%;background:#28d17c;display:inline-block;box-shadow:0 0 10px #28d17c}}
      .trade-stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:8px 0 26px}}
      .trade-stat{{padding:16px;border:1px solid #202d3f;background:linear-gradient(145deg,#101a27,#0b131e);border-radius:16px}}
      .trade-stat small{{color:#7f8da3;display:block;margin-bottom:8px}}
      .trade-stat strong{{font-size:23px}}
      .trade-stat .green{{color:#35d98a}} .trade-stat .red{{color:#ff6574}}
      .section-title{{display:flex;justify-content:space-between;align-items:center;margin:22px 0 12px}}
      .section-title h2{{margin:0;font-size:20px}}
      .section-title span{{color:#77869b;font-size:13px}}
      .trade-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
      .trade-card{{position:relative;overflow:hidden;border:1px solid #243247;border-radius:19px;background:linear-gradient(145deg,#111c2a 0%,#0b131f 100%);box-shadow:0 12px 30px rgba(0,0,0,.16);padding:17px}}
      .trade-card:before{{content:"";position:absolute;right:0;top:0;width:4px;height:100%;background:#20c779}}
      .trade-head,.trade-foot,.trade-main{{display:flex;align-items:center}}
      .trade-head{{gap:11px}}
      .rank-badge{{width:35px;height:35px;border-radius:11px;display:grid;place-items:center;background:#172438;color:#d9e3f0;font-weight:800}}
      .symbol-block{{min-width:0;flex:1}}
      .symbol-block strong{{display:block;font-size:19px;letter-spacing:.2px}}
      .symbol-block span{{display:block;color:#7e8da3;font-size:12px;margin-top:3px}}
      .status-live{{font-size:11px;color:#5fe29b;display:flex;align-items:center;gap:6px}}
      .trade-main{{gap:12px;margin-top:16px}}
      .entry-box{{min-width:145px;padding:13px;border-radius:14px;background:#0b1521;border:1px solid #1d2a3d}}
      .entry-box small{{display:block;color:#7e8da3;font-size:11px}}
      .entry-box strong{{display:block;font-size:20px;margin:5px 0}}
      .entry-box span{{font-size:10px;color:#35d98a;font-weight:800}}
      .levels{{flex:1}}
      .level{{display:flex;justify-content:space-between;padding:9px 11px;border-radius:10px;background:#0e1724;margin-bottom:7px}}
      .level span{{font-size:12px;color:#8794a7}} .level b{{font-size:13px}}
      .level.stop{{border-right:3px solid #ff5e70}} .level.stop b{{color:#ff7180}}
      .tp-row{{display:flex;gap:7px}}
      .tp-item{{flex:1;padding:8px 5px;border:1px solid #1e3540;border-radius:9px;text-align:center;background:#0c1821}}
       .tp-item span{{display:block;font-size:10px;color:#48d99a}} .tp-item b{{display:block;font-size:12px;margin-top:3px}} .level-profit{{display:block;color:#48d99a!important;font-size:10px!important;margin-top:2px}}
      .trade-foot{{justify-content:space-between;gap:8px;margin-top:13px;padding-top:11px;border-top:1px solid #1c2939;color:#718096;font-size:11px}}
      .trade-foot b{{color:#dbe4ef;margin-right:3px}}
      .closed-list{{border:1px solid #202d3f;border-radius:16px;overflow:hidden;background:#0d1622}}
      .closed-row{{display:grid;grid-template-columns:1fr 1fr auto;align-items:center;gap:10px;padding:13px 15px;border-bottom:1px solid #1a2636}}
      .closed-row:last-child{{border-bottom:0}}
      .closed-row strong,.closed-row span{{display:block}} .closed-row span{{color:#77869b;font-size:11px;margin-top:3px}}
      .closed-row>div:nth-child(2){{display:flex;gap:15px}} .closed-row .profit{{color:#35d98a}} .closed-row .loss{{color:#ff6574}}
      .empty-trades{{padding:40px;text-align:center;color:#7f8da3;border:1px dashed #26364c;border-radius:16px;background:#0c1520}}
      @media(max-width:800px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-grid{{grid-template-columns:1fr}}.trades-hero{{align-items:flex-start;flex-direction:column}}}}
      @media(max-width:520px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-main{{align-items:stretch;flex-direction:column}}.entry-box{{min-width:0}}.trade-foot{{flex-wrap:wrap}}.closed-row{{grid-template-columns:1fr auto}}.closed-row>div:nth-child(2){{display:none}}}}
    </style>
    <div class="trades-wrap">
      <div class="trades-hero"><div><h1>متابع الصفقات</h1><p>مراقبة الصفقات المفتوحة والنتائج الفعلية بشكل واضح وسريع.</p></div><div class="live-dot"><i></i> بيانات حية</div></div>
      <div class="trade-stats">
        <div class="trade-stat"><small>مفتوحة</small><strong>{len(open_rows)}</strong></div>
        <div class="trade-stat"><small>مغلقة</small><strong>{total}</strong></div>
        <div class="trade-stat"><small>رابحة</small><strong class="green">{wins}</strong></div>
        <div class="trade-stat"><small>خاسرة</small><strong class="red">{losses}</strong></div>
        <div class="trade-stat"><small>نسبة النجاح</small><strong>{winrate:.1f}%</strong></div>
      </div>
      <div class="section-title"><h2>الصفقات المفتوحة</h2><span>{len(open_rows)} صفقة · مرتبة حسب AI%</span></div>
      <div class="trade-grid">{cards or '<div class="empty-trades">ما فيه صفقات مفتوحة حاليًا.</div>'}</div>
      <div class="section-title"><h2>آخر الصفقات المغلقة</h2><span>آخر 20 صفقة</span></div>
      <div class="closed-list">{history or '<div class="empty-trades">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>
    </div>'''
    return page(req,"متابع الصفقات",body)
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
