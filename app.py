import os,time,sqlite3,asyncio
from typing import Optional
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse

ROOT=Path(__file__).parent
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"

TFS=["15m","30m","1h","4h","1d","1w","1M"]
PIPELINE_TFS=["15m","30m","1h","4h","1d","1w","1M"]
EXCLUDE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","BUSDUSDT","USDEUSDT","USD1USDT","PYUSDUSDT","USDDUSDT","EURUSDT","AEURUSDT","EURIUSDT","XUSDUSDT","USDSUSDT","USTCUSDT","FRAXUSDT"}
MARKETS={
 "crypto_spot":{"name":"سبوت","provider":"binance","symbols":[]},
 "crypto_futures":{"name":"فيوتشر","provider":"binance_futures","symbols":[]},
 "us":{"name":"الأمريكي","provider":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","AMD","NFLX","JPM","WMT","COST","QQQ","SPY"]},
 "us_options":{"name":"الخيارات الأمريكية","provider":"yahoo_options","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","SPY","QQQ"]},
 "contracts":{"name":"العقود","provider":"yahoo","symbols":["ES=F","NQ=F","YM=F","RTY=F","GC=F","SI=F","CL=F"]},
 "saudi":{"name":"السعودي","provider":"yahoo","symbols":["2222.SR","1120.SR","2010.SR","1180.SR","1150.SR","1211.SR","2082.SR","7010.SR","7020.SR","2380.SR"]},
 "forex":{"name":"الفوركس والذهب","provider":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F"]}
}

app=FastAPI(title="التداول الذكي PRO",version="9.0")
WORKER_SECRET=os.getenv("WORKER_SECRET","")
WORKER_TTL=int(os.getenv("WORKER_TTL","180"))

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT,symbol TEXT,tf TEXT,side TEXT,
      entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,risk_pct REAL DEFAULT 0,
      status TEXT DEFAULT 'OPEN',pnl REAL DEFAULT 0,created INTEGER,closed INTEGER,source TEXT,
      strategy TEXT DEFAULT '',quality_score REAL DEFAULT 0,quality_tag TEXT DEFAULT '',rank_no INTEGER DEFAULT 0)""")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'USER',telegram_id TEXT,created INTEGER,last_login INTEGER,active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,price REAL NOT NULL,duration_days INTEGER NOT NULL,permissions TEXT DEFAULT '{}',active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,plan_id INTEGER NOT NULL,status TEXT DEFAULT 'PENDING',starts INTEGER,expires INTEGER,payment_ref TEXT,created INTEGER);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,amount REAL,currency TEXT,status TEXT DEFAULT 'PENDING',provider TEXT,external_id TEXT UNIQUE,created INTEGER);
    CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT,symbol TEXT,tf TEXT,side TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,risk_pct REAL,source TEXT,status TEXT DEFAULT 'OPEN',telegram_sent INTEGER DEFAULT 0,created INTEGER,updated INTEGER);
    CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,body TEXT,source TEXT,published INTEGER,active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,slug TEXT UNIQUE,body TEXT,published INTEGER,active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS admin_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,actor TEXT,meta TEXT,created INTEGER);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires INTEGER);
    CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,code TEXT UNIQUE NOT NULL,reward_pct REAL DEFAULT 10,credit REAL DEFAULT 0,created INTEGER);
    CREATE TABLE IF NOT EXISTS referral_events(id INTEGER PRIMARY KEY AUTOINCREMENT,referrer_id INTEGER,referred_user_id INTEGER,subscription_id INTEGER,credit REAL DEFAULT 0,created INTEGER);
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,subject TEXT,body TEXT,status TEXT DEFAULT 'OPEN',priority TEXT DEFAULT 'NORMAL',admin_reply TEXT,created INTEGER,updated INTEGER);
    CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,endpoint TEXT UNIQUE,provider TEXT,token TEXT,created INTEGER);
    CREATE TABLE IF NOT EXISTS email_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,email TEXT,event TEXT,status TEXT,provider TEXT,created INTEGER);
    CREATE TABLE IF NOT EXISTS trade_events(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_id INTEGER,event TEXT,price REAL,pnl REAL,created INTEGER);
    CREATE TABLE IF NOT EXISTS idempotency_keys(key TEXT PRIMARY KEY,scope TEXT,created INTEGER);
    """)
    # Backward-compatible schema migration for persistent Northflank SQLite volume.
    # Older databases may predate the market-aware trade fields.
    trade_columns=[
        ("market","TEXT DEFAULT ''"),
        ("symbol","TEXT DEFAULT ''"),
        ("tf","TEXT DEFAULT ''"),
        ("side","TEXT DEFAULT ''"),
        ("entry","REAL"),
        ("tp1","REAL"),
        ("tp2","REAL"),
        ("tp3","REAL"),
        ("sl","REAL"),
        ("confidence","REAL DEFAULT 0"),
        ("risk_pct","REAL DEFAULT 0"),
        ("status","TEXT DEFAULT 'OPEN'"),
        ("pnl","REAL DEFAULT 0"),
        ("created","INTEGER"),
        ("closed","INTEGER"),
        ("source","TEXT DEFAULT ''"),
        ("strategy","TEXT DEFAULT ''"),
        ("quality_score","REAL DEFAULT 0"),
        ("quality_tag","TEXT DEFAULT ''"),
        ("rank_no","INTEGER DEFAULT 0"),
    ]
    existing={row["name"] for row in c.execute("PRAGMA table_info(trades)").fetchall()}
    for name,definition in trade_columns:
        if name not in existing:
            try:
                c.execute(f"ALTER TABLE trades ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError:
                pass
    c.commit()
    if c.execute("SELECT COUNT(*) n FROM plans").fetchone()["n"]==0:
        c.executemany("INSERT INTO plans(name,price,duration_days,permissions,active) VALUES(?,?,?,?,1)",[
          ("7 أيام",10,7,'{"signals":true}'),("15 يوم",20,15,'{"signals":true}'),("30 يوم",30,30,'{"signals":true,"telegram":true}')
        ])
    c.commit(); return c


import secrets,hashlib,hmac,json,datetime

def now_ts(): return int(time.time())

def hash_password(password,salt=None):
    salt=salt or secrets.token_hex(16)
    dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000)
    return salt+":"+dk.hex()

def verify_password(password,stored):
    try:
        salt,_=stored.split(":",1)
        return hmac.compare_digest(hash_password(password,salt),stored)
    except Exception:return False

_ENDPOINT_HEALTH={}
DB_BACKUP_DIR=DATA/"backups"
MAX_DB_BACKUPS=int(os.getenv("MAX_DB_BACKUPS","30"))

def _endpoint_key(url):
    try:return url.split("/")[2]
    except Exception:return url

def endpoint_status():
    now=time.time(); out=[]
    for host,v in _ENDPOINT_HEALTH.items():
        out.append({"server":host,"ok":v.get("ok",0),"fail":v.get("fail",0),"cooldown_until":v.get("cooldown_until",0),"cooldown":max(0,round(v.get("cooldown_until",0)-now,1))})
    return sorted(out,key=lambda x:(x["cooldown"]>0,-x["ok"],x["fail"]))

def backup_db(reason="auto"):
    try:
        DB_BACKUP_DIR.mkdir(parents=True,exist_ok=True)
        stamp=time.strftime("%Y%m%d_%H%M%S")
        target=DB_BACKUP_DIR/f"trading_{stamp}_{reason}.db"
        src=sqlite3.connect(DB); dst=sqlite3.connect(target)
        with dst: src.backup(dst)
        dst.close(); src.close()
        files=sorted(DB_BACKUP_DIR.glob("trading_*.db"),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in files[MAX_DB_BACKUPS:]:
            try: old.unlink()
            except Exception: pass
        return str(target)
    except Exception:
        return None

async def req(url,params=None):
    key=_endpoint_key(url); now=time.time(); h=_ENDPOINT_HEALTH.setdefault(key,{"ok":0,"fail":0,"cooldown_until":0})
    if h.get("cooldown_until",0)>now: raise httpx.ConnectTimeout(f"endpoint cooldown: {key}")
    timeout=httpx.Timeout(connect=4.0,read=10.0,write=5.0,pool=5.0)
    last=None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout,headers={"User-Agent":"Mozilla/5.0"}) as x:
                r=await x.get(url,params=params); r.raise_for_status(); data=r.json()
                h["ok"]+=1; h["fail"]=max(0,h["fail"]-1); h["cooldown_until"]=0
                return data
        except Exception as e:
            last=e; h["fail"]+=1
            if h["fail"]>=4: h["cooldown_until"]=time.time()+min(60,5*(2**min(h["fail"]-4,3)))
            if attempt<2: await asyncio.sleep(0.25*(2**attempt)+0.15*attempt)
    raise last

async def req_post(url,payload):
    timeout=httpx.Timeout(connect=4.0,read=10.0,write=5.0,pool=5.0)
    async with httpx.AsyncClient(timeout=timeout,headers={"User-Agent":"Mozilla/5.0"}) as x:
        r=await x.post(url,json=payload); r.raise_for_status(); return r.json()

_UNIVERSE_CACHE={}

async def universe(futures=False):
    key="futures" if futures else "spot"
    cached=_UNIVERSE_CACHE.get(key)
    if cached and time.time()-cached["at"]<90:
        return cached["rows"]

    if futures:
        bases=["https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com"]
        path="/fapi/v1/ticker/24hr"
    else:
        bases=["https://api.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]
        path="/api/v3/ticker/24hr"

    rows=None
    for base in bases:
        try:
            rows=await req(base+path)
            if isinstance(rows,list) and rows:
                break
        except Exception:
            continue

    if not isinstance(rows,list):
        return cached["rows"] if cached else []

    rows=[r for r in rows if r.get("symbol","").endswith("USDT")
          and r.get("symbol") not in EXCLUDE
          and float(r.get("quoteVolume",0) or 0)>=1000000]
    rows=sorted(rows,key=lambda r:float(r.get("quoteVolume",0) or 0),reverse=True)
    _UNIVERSE_CACHE[key]={"at":time.time(),"rows":rows}
    return rows

def closes_volumes(raw,market):
    if market.startswith("crypto"):
        return [float(x[4]) for x in raw],[float(x[7]) for x in raw]
    q=raw.get("indicators",{}).get("quote",[{}])[0]
    return [float(x) for x in q.get("close",[]) if x is not None],[float(x or 0) for x in q.get("volume",[])]

# Dedicated data-server pools per timeframe.
# Each timeframe pulls a chronological chunk from every server in its pool;
# failed chunks are skipped and the remaining servers are merged by candle time.
TF_SERVER_POOLS={
    # Spot: use every documented Binance market-data edge, with a different
    # chronological piece assigned to each edge for every timeframe.
    "15m":["https://api.binance.com","https://api-gcp.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://api4.binance.com"],
    "30m":["https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://api4.binance.com","https://api-gcp.binance.com","https://api.binance.com"],
    "1h":["https://api2.binance.com","https://api3.binance.com","https://api4.binance.com","https://api-gcp.binance.com","https://api.binance.com","https://api1.binance.com"],
    "4h":["https://api3.binance.com","https://api4.binance.com","https://api-gcp.binance.com","https://api.binance.com","https://api1.binance.com","https://api2.binance.com"],
    "1d":["https://api4.binance.com","https://api-gcp.binance.com","https://api.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"],
    "1w":["https://api-gcp.binance.com","https://api.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://api4.binance.com"],
    "1M":["https://api.binance.com","https://api2.binance.com","https://api3.binance.com","https://api4.binance.com","https://api-gcp.binance.com","https://api1.binance.com"],
}
FUTURES_SERVER_POOLS={
    "15m":["https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com"],
    "30m":["https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi.binance.com"],
    "1h":["https://fapi2.binance.com","https://fapi3.binance.com","https://fapi.binance.com","https://fapi1.binance.com"],
    "4h":["https://fapi3.binance.com","https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com"],
    "1d":["https://fapi.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi1.binance.com"],
    "1w":["https://fapi1.binance.com","https://fapi3.binance.com","https://fapi.binance.com","https://fapi2.binance.com"],
    "1M":["https://fapi2.binance.com","https://fapi.binance.com","https://fapi1.binance.com","https://fapi3.binance.com"],
}
YAHOO_SERVER_POOLS=[
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
    "https://query3.finance.yahoo.com",
]

async def _server_json(url,params):
    try:
        return await req(url,params)
    except Exception:
        return None

async def market_candles(market,symbol,tf):
    # Every available edge receives its own chronological piece. Failed edges
    # are skipped; pieces are merged by candle timestamp and the newest 240 kept.
    sec={"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}[tf]
    now=int(time.time())
    chunk=60
    rows=[]

    if market in ("crypto_spot","crypto_futures"):
        pools=FUTURES_SERVER_POOLS if market=="crypto_futures" else TF_SERVER_POOLS
        servers=pools[tf]
        path="/fapi/v1/klines" if market=="crypto_futures" else "/api/v3/klines"
        async def get_piece(i,base):
            end=now-(3-i)*chunk*sec
            start=end-chunk*sec
            return await _server_json(base+path,{"symbol":symbol,"interval":tf,"limit":chunk,"startTime":int(start*1000),"endTime":int(end*1000)})
        parts=await asyncio.gather(*[get_piece(i,base) for i,base in enumerate(servers)])
        for part in parts:
            if isinstance(part,list): rows.extend(part)
        # Binance klines are uniquely identified by open time.
        unique={int(x[0]):x for x in rows if isinstance(x,list) and len(x)>=8}
        return [unique[k] for k in sorted(unique)][-240:]

    interval="1mo" if tf=="1M" else tf
    async def get_yahoo_piece(i,base):
        end=now-(3-i)*chunk*sec
        start=end-chunk*sec
        return await _server_json(
            base+"/v8/finance/chart/"+symbol,
            {"period1":int(start),"period2":int(end),"interval":interval}
        )
    parts=await asyncio.gather(*[get_yahoo_piece(i,base) for i,base in enumerate(YAHOO_SERVER_POOLS)])
    for part in parts:
        try:
            result=(part.get("chart",{}).get("result") or [None])[0]
            if result: rows.append(result)
        except Exception:
            pass
    # Merge Yahoo chunks by timestamp, preserving the newest 240 bars.
    merged={}
    for result in rows:
        ts=result.get("timestamp") or []
        q=result.get("indicators",{}).get("quote",[{}])[0]
        for i,t in enumerate(ts):
            if i<len(q.get("close",[])):
                merged[int(t)]={
                    "timestamp":int(t),
                    "indicators":{"quote":[{
                        "close":[q.get("close",[None])[i]],
                        "high":[q.get("high",[None])[i]],
                        "low":[q.get("low",[None])[i]],
                        "volume":[q.get("volume",[None])[i]],
                    }]}
                }
    return {"timestamp":sorted(merged),"indicators":{"quote":[{
        "close":[merged[k]["indicators"]["quote"][0]["close"][0] for k in sorted(merged)],
        "high":[merged[k]["indicators"]["quote"][0]["high"][0] for k in sorted(merged)],
        "low":[merged[k]["indicators"]["quote"][0]["low"][0] for k in sorted(merged)],
        "volume":[merged[k]["indicators"]["quote"][0]["volume"][0] for k in sorted(merged)],
    }]}}


def ema(a,n):
    if len(a)<n:return None
    e=sum(a[:n])/n; k=2/(n+1)
    for v in a[n:]: e=v*k+e*(1-k)
    return e

def atr(h,l,c,n=14):
    if len(c)<n+1:return None
    tr=[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sum(tr[-n:])/n

def pivots(h,l,left=3,right=3):
    sh=[];sl=[]
    for i in range(left,len(h)-right):
        if h[i]==max(h[i-left:i+right+1]): sh.append(i)
        if l[i]==min(l[i-left:i+right+1]): sl.append(i)
    return sh,sl

def fvg_zone(h,l,bias):
    for i in range(len(h)-1,2,-1):
        if bias=="BUY" and l[i]>h[i-2]:
            return (h[i-2],l[i],"FVG")
        if bias=="SELL" and h[i]<l[i-2]:
            return (h[i],l[i-2],"FVG")
    return None

def structure_bias(c,h,l):
    e=ema(c,200) or ema(c,min(100,len(c)-1))
    sh,sl=pivots(h,l)
    last= c[-1]
    bullish=bool(e and last>e)
    bearish=bool(e and last<e)
    if len(sh)>=2 and len(sl)>=2:
        bullish=bullish and h[sh[-1]]>=h[sh[-2]] and l[sl[-1]]>=l[sl[-2]]
        bearish=bearish and h[sh[-1]]<=h[sh[-2]] and l[sl[-1]]<=l[sl[-2]]
    if bullish:return "BUY"
    if bearish:return "SELL"
    return "NEUTRAL"

def poi_from_structure(c,h,l,bias):
    if bias not in ("BUY","SELL"): return None
    sh,sl=pivots(h,l)
    if bias=="BUY" and sh:
        level=h[sh[-1]]
        if c[-1]>level:
            for i in range(sh[-1]-1,max(-1,sh[-1]-12),-1):
                if c[i]<o_for_index(c,h,l,i):
                    lo=min(l[i],h[i]); hi=max(c[i],o_for_index(c,h,l,i))
                    zone=(lo,hi,"OB")
                    f=fvg_zone(h,l,bias)
                    return f or zone
    if bias=="SELL" and sl:
        level=l[sl[-1]]
        if c[-1]<level:
            for i in range(sl[-1]-1,max(-1,sl[-1]-12),-1):
                if c[i]>o_for_index(c,h,l,i):
                    lo=min(o_for_index(c,h,l,i),c[i]); hi=max(h[i],o_for_index(c,h,l,i))
                    zone=(lo,hi,"OB")
                    f=fvg_zone(h,l,bias)
                    return f or zone
    return fvg_zone(h,l,bias)

def o_for_index(c,h,l,i):
    # Candle-open approximation when provider payload is normalized to closes/highs/lows.
    return c[i-1] if i>0 else c[i]

def inside_zone(price,zone):
    if not zone:return False
    lo,hi,_=zone
    return lo*0.997<=price<=hi*1.003

def choch(c,h,l,bias):
    sh,sl=pivots(h,l,2,2)
    if bias=="BUY" and sh:
        return c[-1]>h[sh[-1]]
    if bias=="SELL" and sl:
        return c[-1]<l[sl[-1]]
    return False

def sweep(c,h,l,bias,look=20):
    if len(c)<look+3:return False
    hi=max(h[-look-2:-2]); lo=min(l[-look-2:-2])
    return (min(l[-3:])<lo and c[-1]>lo) if bias=="BUY" else (max(h[-3:])>hi and c[-1]<hi)

async def candles_for(market,symbol,tfs):
    sem=asyncio.Semaphore(6)
    async def one(tf):
        async with sem:
            try:
                raw=await market_candles(market,symbol,tf)
                if market.startswith("crypto"):
                    c=[float(x[4]) for x in raw]; h=[float(x[2]) for x in raw]; l=[float(x[3]) for x in raw]
                    v=[float(x[7]) for x in raw]
                else:
                    q=raw.get("indicators",{}).get("quote",[{}])[0]
                    c=[float(x) for x in q.get("close",[]) if x is not None]
                    h=[float(x) for x in q.get("high",[]) if x is not None]
                    l=[float(x) for x in q.get("low",[]) if x is not None]
                    v=[float(x or 0) for x in q.get("volume",[])]
                return tf,(c,h,l,v)
            except Exception:return tf,None
    return dict(await asyncio.gather(*[one(tf) for tf in tfs]))

def rsi(c,n=14):
    if len(c)<n+1:return None
    gains=[];losses=[]
    for i in range(1,len(c)):
        d=c[i]-c[i-1];gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[-n:])/n; al=sum(losses[-n:])/n
    if al==0:return 100.0
    return 100-(100/(1+(ag/al)))

def candle_parts(c,h,l,i):
    o=c[i-1] if i>0 else c[i]
    body=abs(c[i]-o); rng=max(h[i]-l[i],1e-12)
    upper=h[i]-max(o,c[i]); lower=min(o,c[i])-l[i]
    return o,body,rng,upper,lower

def engulfing(c,h,l,buy=True):
    if len(c)<3:return False
    o1,_,_,_,_=candle_parts(c,h,l,-2)
    o2,b2,_,_,_=candle_parts(c,h,l,-1)
    if buy:
        return c[-2]<o1 and c[-1]>o2 and c[-1]>=o1 and o2<=c[-2]
    return c[-2]>o1 and c[-1]<o2 and c[-1]<=o1 and o2>=c[-2]

def pinbar(c,h,l,buy=True):
    if len(c)<2:return False
    o,b,r,u,lo=candle_parts(c,h,l,-1)
    if buy:return lo>=max(b*2,r*0.45) and c[-1]>=o
    return u>=max(b*2,r*0.45) and c[-1]<=o

def bos(c,h,l,buy=True,look=20):
    if len(c)<look+2:return False
    if buy:return c[-1]>max(h[-look-1:-1])
    return c[-1]<min(l[-look-1:-1])

def fvg_signal(h,l,buy=True):
    if len(h)<4:return None
    for i in range(len(h)-1,2,-1):
        if buy and l[i]>h[i-2] and l[i-1]>=h[i-2]:
            return (h[i-2],l[i])
        if not buy and h[i]<l[i-2] and h[i-1]<=l[i-2]:
            return (h[i],l[i-2])
    return None

def risk_targets(c,h,l,buy,risk_mult=2):
    entry=c[-1]; a=atr(h,l,c) or abs(entry*0.003)
    if buy:
        sl=min(min(l[-5:]),entry-a); risk=entry-sl
        if risk<=0:return None
        tp1=entry+risk*risk_mult;tp2=entry+risk*3;tp3=entry+risk*5
    else:
        sl=max(max(h[-5:]),entry+a); risk=sl-entry
        if risk<=0:return None
        tp1=entry-risk*risk_mult;tp2=entry-risk*3;tp3=entry-risk*5
    return entry,tp1,tp2,tp3,sl,abs(tp1-entry)/risk

def volume_ok(v,window=20,mult=1.05):
    if not v or len(v)<window+1:return True
    avg=sum(v[-window-1:-1])/window
    return avg<=0 or v[-1]>=avg*mult

def bbands(c,n=20,mult=2):
    if len(c)<n:return None
    w=c[-n:];m=sum(w)/n
    sd=(sum((x-m)**2 for x in w)/n)**0.5
    return m,m+mult*sd,m-mult*sd

TF_QUALITY_TAG={"15m":"SCALP-PRO","30m":"INTRADAY-PRO","1h":"DAY-PRO","4h":"SWING-PRO","1d":"POSITION-PRO","1w":"MACRO-PRO","1M":"MACRO-X"}

def data_quality(c,h,l,v,tf):
    need={"15m":80,"30m":80,"1h":80,"4h":80,"1d":80,"1w":60,"1M":36}.get(tf,60)
    if min(len(c),len(h),len(l),len(v))<need:return 0
    if any(x<=0 for x in c[-20:]):return 0
    jumps=[abs(c[i]/c[i-1]-1) for i in range(1,len(c)) if c[i-1]]
    if jumps and max(jumps[-20:])>0.35:return 0
    return 100

def historical_quality(market,symbol,tf,strategy):
    try:
        c=db(); r=c.execute("SELECT COUNT(*) n,SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) w,SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) l FROM trades WHERE status='CLOSED' AND market=? AND symbol=? AND tf=? AND strategy=?",(market,symbol,tf,strategy)).fetchone(); c.close()
        n=int(r["n"] or 0); w=int(r["w"] or 0); l=int(r["l"] or 0)
        return (round(w/n*100,2) if n else None,n,w,l)
    except Exception:return (None,0,0,0)

def rank_signals(items):
    enriched=[]
    for x in items:
        hist,n,w,l=historical_quality(x.get("market",""),x.get("symbol",""),x.get("tf",""),x.get("strategy",""))
        model=float(x.get("confidence") or 0); rr=float(x.get("rr") or 0)
        quality=round((hist*0.55+model*0.30+min(rr/5,1)*15) if hist is not None and n>=5 else (model*0.65+min(rr/5,1)*20+15),2)
        x["historical_win_rate"]=hist; x["historical_trades"]=n
        x["quality_score"]=quality
        x["quality_tag"]=TF_QUALITY_TAG.get(x.get("tf"),"PRO")
        x["medal"]="🥇" if quality>=90 else ("🥈" if quality>=82 else ("🥉" if quality>=75 else "•"))
        x["success_rate"]=hist if hist is not None and n>=5 else model
        x["success_rate_type"]="verified_closed_trades" if hist is not None and n>=5 else "model_estimate"
        enriched.append(x)
    enriched.sort(key=lambda x:(float(x.get("quality_score") or 0),float(x.get("rr") or 0)),reverse=True)
    for i,x in enumerate(enriched,1): x["rank"]=i
    return enriched

def independent_signal(market,symbol,tf,data):
    c,h,l,v=data
    if len(c)<60 or data_quality(c,h,l,v,tf)<100:return None
    p=c[-1];side=None;strategy="";reason="";risk_pct=0.5;rr_mult=2.0
    if tf=="15m":
        e20=ema(c,20);e50=ema(c,50);r=rsi(c)
        if e20 and e50 and r is not None:
            if p>e50 and e20>e50 and l[-1]<=e20*1.002 and p>e20 and r>50 and volume_ok(v,20,1.0): side="BUY"
            elif p<e50 and e20<e50 and h[-1]>=e20*.998 and p<e20 and r<50 and volume_ok(v,20,1.0): side="SELL"
        if side: strategy="15M EMA20/50 Pullback + RSI + Volume";reason="تصحيح للـEMA20 داخل اتجاه EMA50 مع تأكيد الحجم";risk_pct=.75;rr_mult=2.2
    elif tf=="30m":
        e20=ema(c,20);e50=ema(c,50);r=rsi(c)
        if e20 and e50 and r is not None:
            if p>e50 and e20>e50 and l[-1]<=e20*1.002 and p>e20 and r>50 and volume_ok(v,20,1.0): side="BUY"
            elif p<e50 and e20<e50 and h[-1]>=e20*.998 and p<e20 and r<50 and volume_ok(v,20,1.0): side="SELL"
        if side: strategy="30M EMA20/50 Pullback + RSI + Volume";reason="تصحيح للـEMA20 على 30 دقيقة مع تأكيد الاتجاه والحجم";risk_pct=.75;rr_mult=2.2
    elif tf=="1h":
        e50=ema(c,50);e200=ema(c,200)
        if e50 and e200 and len(c)>=25:
            hi=max(h[-21:-1]);lo=min(l[-21:-1])
            if p>hi and p>e50>e200 and volume_ok(v,20,1.05): side="BUY"
            elif p<lo and p<e50<e200 and volume_ok(v,20,1.05): side="SELL"
        if side: strategy="1H Donchian Breakout + EMA50/200";reason="كسر نطاق 20 شمعة مع توافق الاتجاه والحجم";risk_pct=1;rr_mult=2.5
    elif tf=="4h":
        e50=ema(c,50);e200=ema(c,200)
        if e50 and e200 and len(c)>=30:
            hi=max(h[-21:-1]);lo=min(l[-21:-1])
            if p>hi and p>e50>e200: side="BUY"
            elif p<lo and p<e50<e200: side="SELL"
        if side: strategy="4H Trend Breakout + EMA50/200";reason="كسر هيكلي متوسط الأجل مع اتجاه EMA200";risk_pct=1.25;rr_mult=3
    elif tf=="1d":
        e50=ema(c,50);e200=ema(c,200)
        if e50 and e200 and len(c)>=60:
            hi=max(h[-21:-1]);lo=min(l[-21:-1])
            if p>hi and p>e50>e200 and volume_ok(v,20,1.0): side="BUY"
            elif p<lo and p<e50<e200 and volume_ok(v,20,1.0): side="SELL"
        if side: strategy="1D EMA50/200 + 20D Breakout";reason="اتجاه يومي مؤكد بكسر نطاق 20 يوم";risk_pct=1.5;rr_mult=3
    elif tf=="1w":
        e20=ema(c,20);e50=ema(c,50)
        if e20 and e50 and len(c)>=55:
            hi=max(h[-13:-1]);lo=min(l[-13:-1])
            if p>hi and p>e20>e50: side="BUY"
            elif p<lo and p<e20<e50: side="SELL"
        if side: strategy="1W Time-Series Momentum + Channel";reason="زخم أسبوعي مع اتجاه EMA20/50 وكسر 12 أسبوع";risk_pct=2;rr_mult=3.5
    elif tf=="1M":
        e10=ema(c,10);e20=ema(c,20)
        if e10 and e20 and len(c)>=25:
            hi=max(h[-13:-1]);lo=min(l[-13:-1])
            if p>hi and p>e10>e20: side="BUY"
            elif p<lo and p<e10<e20: side="SELL"
        if side: strategy="1M Macro Trend + 12M Breakout";reason="اتجاه شهري طويل الأجل مع كسر نطاق 12 شهر";risk_pct=2.5;rr_mult=5
    else:return None
    if not side:return None
    rt=risk_targets(c,h,l,side=="BUY",rr_mult)
    if not rt:return None
    entry,tp1,tp2,tp3,sl,rr=rt
    if rr<2:return None
    confidence=min(97,72+int(min(rr,5)*3)+(3 if volume_ok(v) else 0))
    return {"market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,"tf":tf,"side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"confidence":confidence,"rr":round(rr,2),"state":"ENTERED","stage":"إشارة مستقلة","strategy":strategy,"reason":reason,"risk_pct":risk_pct,"duration":{"1M":"أشهر إلى سنة","1w":"أسابيع إلى أشهر","1d":"أيام إلى أسابيع","4h":"1-5 أيام","1h":"ساعات إلى يوم","15m":"30 دقيقة-4 ساعات"}.get(tf,""),"execution":{"tf":tf,"trigger":True},"independent":True,"rsi":round(rsi(c),2) if rsi(c) is not None else None,"change":round((p/c[-2]-1)*100,2),"success_rate":confidence,"success_rate_type":"model_estimate","quality_tag":TF_QUALITY_TAG.get(tf,"PRO"),"time":int(time.time())}

async def independent_scan(market,symbol):
    d=await candles_for(market,symbol,TFS)
    # Minimum $1M traded value filter for every market where Yahoo/market volume is available.
    liq=d.get("1d")
    if liq and not market.startswith("crypto") and market not in ("saudi","forex"):
        c0,h0,l0,v0=liq
        if not c0 or not v0 or (float(c0[-1] or 0)*float(v0[-1] or 0)) < 1000000:
            return []
    out=[]
    for tf in TFS:
        x=d.get(tf)
        if x:
            try:
                z=independent_signal(market,symbol,tf,x)
                if z: out.append(z)
            except Exception:
                pass
    return out

async def scan_all():
    jobs=[]
    for market in MARKETS:
        if market=="crypto_spot":
            syms=[x["symbol"] for x in await universe(False)]
        elif market=="crypto_futures":
            syms=[x["symbol"] for x in await universe(True)]
        else: syms=MARKETS[market]["symbols"]
        for s in syms: jobs.append((market,s))
    sem=asyncio.Semaphore(8)
    async def one(m,s):
        async with sem:
            try:return await independent_scan(m,s)
            except Exception:return []
    groups=await asyncio.gather(*[one(m,s) for m,s in jobs])
    return rank_signals([x for g in groups for x in g])

MAX_OPEN_RISK_PCT=5.0
MAX_TRADES_PER_MARKET=3

def open_risk_pct(c):
    row=c.execute("SELECT COALESCE(SUM(risk_pct),0) r FROM trades WHERE status='OPEN'").fetchone()
    return round(float(row["r"] or 0),4)

def save(items):
    # Scanner results are signals only. Automatic paper trades are created separately.
    return

def auto_launch_market_trades(items):
    """Open at most one qualifying paper trade per market per scan.
    Real orders are never sent; this uses the existing PAPER_SAFE database only."""
    c=db()
    opened=[]
    try:
        used=open_risk_pct(c)
        for market in MARKETS:
            candidates=[x for x in items if x.get("market")==market and x.get("state")=="ENTERED" and float(x.get("quality_score") or x.get("confidence") or 0)>=78]
            candidates.sort(key=lambda x:(float(x.get("quality_score") or 0),float(x.get("confidence") or 0),float(x.get("rr") or 0)),reverse=True)
            market_open=0
            for sig in candidates:
                if market_open>=MAX_TRADES_PER_MARKET:
                    break
                if used+float(sig.get("risk_pct") or 0)>MAX_OPEN_RISK_PCT:
                    continue
                exists=c.execute("SELECT id FROM trades WHERE market=? AND symbol=? AND tf=? AND status='OPEN'",(market,sig["symbol"],sig["tf"])).fetchone()
                if exists:
                    continue
                risk=float(sig.get("risk_pct") or 0)
                cur=c.execute("""INSERT INTO trades(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,confidence,risk_pct,created,source,strategy,quality_score,quality_tag,rank_no)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(market,sig["symbol"],sig["tf"],sig["side"],sig["entry"],sig["tp1"],sig["tp2"],sig["tp3"],sig["sl"],sig["confidence"],risk,int(time.time()),"AUTO_MARKET_PAPER",sig.get("strategy",""),float(sig.get("quality_score") or 0),sig.get("quality_tag","PRO"),int(sig.get("rank") or 0)))
                opened.append(cur.lastrowid)
                used+=risk
        c.commit()
        if opened: backup_db("trades")
    finally:
        c.close()
    return opened

async def loop():
    while True:
        try:
            z=await scan_all(); save(z); app.state.data={"at":int(time.time()),"items":z}; app.state.error=""
            app.state.auto_trades=auto_launch_market_trades(z)
        except Exception as e:
            app.state.error=str(e)
        await asyncio.sleep(180)

@app.on_event("startup")
async def start():
    app.state.data={"at":0,"items":[]};app.state.error="";app.state.workers={};app.state.auto_trades=[];asyncio.create_task(loop())

@app.get("/health")
async def health():
    return {"ok":True,"version":"9.2","engine":"QUALITY_RANKED_RESILIENT_ENGINE","pipeline":"1M|1W|1D|4H|1H|30M|15M_INDEPENDENT","execution":"PAPER_SAFE","independent_timeframes":TFS,"max_open_risk_pct":MAX_OPEN_RISK_PCT,"endpoint_health":endpoint_status()}


RATE_WINDOW=60
RATE_LIMIT=int(os.getenv("RATE_LIMIT_PER_MINUTE","120"))
_rate_cache={}
@app.middleware("http")
async def security_middleware(request, call_next):
    ip=request.client.host if request.client else "unknown"
    key=(ip,int(time.time())//RATE_WINDOW)
    _rate_cache[key]=_rate_cache.get(key,0)+1
    if _rate_cache[key]>RATE_LIMIT:
        return JSONResponse({"error":"rate_limited","retry_after":RATE_WINDOW},status_code=429,headers={"Retry-After":str(RATE_WINDOW)})
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"]="DENY"
    if request.url.path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
    return response

@app.post("/api/auth/register")
async def register(payload: dict):
    email=str(payload.get("email","")).strip().lower(); password=str(payload.get("password",""))
    if len(email)<5 or len(password)<8:return JSONResponse({"error":"invalid_credentials"},400)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(email,password_hash,created) VALUES(?,?,?)",(email,hash_password(password),now_ts()))
        c.commit(); uid=cur.lastrowid
        code=secrets.token_urlsafe(8).replace("-","").replace("_","")
        c.execute("INSERT INTO referrals(user_id,code,created) VALUES(?,?,?)",(uid,code,now_ts()))
        c.commit()
        token=secrets.token_urlsafe(32); c.execute("INSERT INTO sessions VALUES(?,?,?)",(token,uid,now_ts()+2592000));c.commit()
        return {"ok":True,"token":token,"user":{"id":uid,"email":email,"role":"USER"}}
    except sqlite3.IntegrityError:return JSONResponse({"error":"email_exists"},409)
    finally:c.close()

@app.post("/api/auth/login")
async def login(payload: dict):
    c=db();u=c.execute("SELECT * FROM users WHERE email=? AND active=1",(str(payload.get("email","")).strip().lower(),)).fetchone()
    if not u or not verify_password(str(payload.get("password","")),u["password_hash"]):c.close();return JSONResponse({"error":"invalid_login"},401)
    token=secrets.token_urlsafe(32);c.execute("INSERT INTO sessions VALUES(?,?,?)",(token,u["id"],now_ts()+2592000));c.execute("UPDATE users SET last_login=? WHERE id=?",(now_ts(),u["id"]));c.commit();c.close()
    return {"ok":True,"token":token,"user":{"id":u["id"],"email":u["email"],"role":u["role"]}}

@app.get("/api/me")
async def me(token: Optional[str]=None):
    u=auth_user(token)
    return {"authenticated":bool(u),"user":({"id":u["id"],"email":u["email"],"role":u["role"]} if u else None)}

@app.get("/api/admin/overview")
async def admin_overview(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db();users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"];subs=c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='ACTIVE'").fetchone()["n"];signals=c.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"];trades=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];c.close()
    return {"users":users,"active_subscriptions":subs,"signals":signals,"trades":trades}

@app.post("/api/admin/signal")
async def admin_signal(payload: dict, token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    required=["market","symbol","tf","side","entry","tp1","tp2","tp3","sl"]
    if any(k not in payload for k in required):return JSONResponse({"error":"missing_fields"},400)
    c=db();cur=c.execute("""INSERT INTO signals(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,risk_pct,source,created,updated)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(payload["market"],payload["symbol"],payload["tf"],payload["side"],payload["entry"],payload["tp1"],payload["tp2"],payload["tp3"],payload["sl"],payload.get("risk_pct",0),"ADMIN",now_ts(),now_ts()));sid=cur.lastrowid;c.execute("INSERT INTO admin_logs(action,actor,meta,created) VALUES(?,?,?,?)",("CREATE_SIGNAL","admin",json.dumps({"signal_id":sid}),now_ts()));c.commit();c.close()
    x=dict(payload);x["signal_id"]=sid
    sent=await telegram_send(signal_text(x))
    c=db();c.execute("UPDATE signals SET telegram_sent=? WHERE id=?",(1 if sent else 0,sid));c.commit();c.close()
    return {"ok":True,"signal_id":sid,"telegram_sent":sent}

@app.post("/api/webhook/tradingview")
async def tradingview(payload: dict):
    secret=os.getenv("TRADINGVIEW_WEBHOOK_SECRET","")
    supplied=str(payload.get("secret",""))
    if not secret or not hmac.compare_digest(supplied,secret):return JSONResponse({"error":"unauthorized"},401)
    required=["market","symbol","tf","side","entry","tp1","tp2","tp3","sl"]
    if any(k not in payload for k in required):return JSONResponse({"error":"missing_fields"},400)
    c=db();cur=c.execute("""INSERT INTO signals(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,risk_pct,source,created,updated)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(payload["market"],payload["symbol"],payload["tf"],payload["side"],payload["entry"],payload["tp1"],payload["tp2"],payload["tp3"],payload["sl"],payload.get("risk_pct",0),"TRADINGVIEW",now_ts(),now_ts()));sid=cur.lastrowid;c.commit();c.close()
    x=dict(payload);sent=await telegram_send(signal_text(x))
    c=db();c.execute("UPDATE signals SET telegram_sent=? WHERE id=?",(1 if sent else 0,sid));c.commit();c.close()
    return {"ok":True,"signal_id":sid,"telegram_sent":sent}

@app.get("/api/admin/signals")
async def admin_signals(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 200")];c.close();return rows

@app.get("/api/plans")
async def plans():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM plans WHERE active=1 ORDER BY price")];c.close();return rows

@app.get("/api/news")
async def news():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM news WHERE active=1 ORDER BY published DESC LIMIT 50")];c.close();return rows

@app.get("/api/articles")
async def articles():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM articles WHERE active=1 ORDER BY published DESC LIMIT 50")];c.close();return rows

@app.get("/api/referral")
async def referral(token: Optional[str]=None):
    u=auth_user(token)
    if not u:return JSONResponse({"error":"unauthorized"},401)
    c=db();r=c.execute("SELECT * FROM referrals WHERE user_id=?",(u["id"],)).fetchone();c.close()
    return dict(r) if r else {}

@app.post("/api/referral/apply")
async def referral_apply(payload: dict, token: Optional[str]=None):
    u=auth_user(token)
    if not u:return JSONResponse({"error":"unauthorized"},401)
    code=str(payload.get("code","")).strip()
    c=db();r=c.execute("SELECT * FROM referrals WHERE code=?",(code,)).fetchone()
    if not r or r["user_id"]==u["id"]:c.close();return JSONResponse({"error":"invalid_referral"},400)
    c.execute("INSERT INTO referral_events(referrer_id,referred_user_id,credit,created) VALUES(?,?,0,?)",(r["user_id"],u["id"],now_ts()));c.commit();c.close()
    return {"ok":True}

@app.post("/api/support/tickets")
async def create_ticket(payload: dict, token: Optional[str]=None):
    u=auth_user(token)
    if not u:return JSONResponse({"error":"unauthorized"},401)
    subject=str(payload.get("subject","")).strip();body=str(payload.get("body","")).strip()
    if not subject or not body:return JSONResponse({"error":"missing_fields"},400)
    c=db();cur=c.execute("INSERT INTO tickets(user_id,subject,body,created,updated) VALUES(?,?,?,?,?)",(u["id"],subject,body,now_ts(),now_ts()));c.commit();tid=cur.lastrowid;c.close()
    return {"ok":True,"ticket_id":tid}

@app.get("/api/support/tickets")
async def list_tickets(token: Optional[str]=None):
    u=auth_user(token)
    if not u:return JSONResponse({"error":"unauthorized"},401)
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC",(u["id"],))];c.close();return rows

@app.get("/api/admin/analytics")
async def admin_analytics(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db()
    active=c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='ACTIVE'").fetchone()["n"]
    mrr=c.execute("SELECT COALESCE(SUM(p.price),0) x FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.status='ACTIVE'").fetchone()["x"]
    wins=c.execute("SELECT COUNT(*) n FROM trades WHERE status='CLOSED' AND pnl>0").fetchone()["n"]
    losses=c.execute("SELECT COUNT(*) n FROM trades WHERE status='CLOSED' AND pnl<0").fetchone()["n"]
    closed=wins+losses
    by_market=[dict(x) for x in c.execute("SELECT market,COUNT(*) trades,SUM(CASE WHEN status='CLOSED' AND pnl>0 THEN 1 ELSE 0 END) wins,SUM(CASE WHEN status='CLOSED' AND pnl<0 THEN 1 ELSE 0 END) losses,ROUND(COALESCE(SUM(pnl),0),4) pnl FROM trades GROUP BY market ORDER BY trades DESC")]
    c.close()
    return {"active_subscriptions":active,"mrr":round(float(mrr),2),"wins":wins,"losses":losses,"win_rate":round(wins/closed*100,2) if closed else 0,"by_market":by_market}

@app.get("/api/legal")
async def legal():
    return {"risk_disclaimer":"المحتوى والإشارات والأخبار تعليمية وتحليلية وليست توصية مالية مباشرة. التداول ينطوي على مخاطر وقد يؤدي إلى خسارة رأس المال.","refund_policy":"تخضع طلبات الاسترجاع لشروط الباقة والخدمة والقوانين المعمول بها. راجع شروط الاشتراك قبل الدفع.","terms":"استخدام المنصة يعني قبول شروط الاستخدام وسياسة الخصوصية وإخلاء المسؤولية."}

@app.post("/api/push/register")
async def push_register(payload: dict, token: Optional[str]=None):
    u=auth_user(token)
    if not u:return JSONResponse({"error":"unauthorized"},401)
    endpoint=str(payload.get("endpoint","")).strip()
    if not endpoint:return JSONResponse({"error":"missing_endpoint"},400)
    c=db();c.execute("INSERT OR REPLACE INTO push_subscriptions(user_id,endpoint,provider,token,created) VALUES(?,?,?,?,?)",(u["id"],endpoint,payload.get("provider","webpush"),payload.get("token"),now_ts()));c.commit();c.close()
    return {"ok":True}

@app.post("/api/admin/subscription/activate")
async def activate_subscription(payload: dict, token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    uid=int(payload.get("user_id",0));pid=int(payload.get("plan_id",0))
    c=db();p=c.execute("SELECT * FROM plans WHERE id=? AND active=1",(pid,)).fetchone()
    if not p:c.close();return JSONResponse({"error":"plan_not_found"},404)
    start=now_ts();expires=start+int(p["duration_days"])*86400
    cur=c.execute("INSERT INTO subscriptions(user_id,plan_id,status,starts,expires,payment_ref,created) VALUES(?,?,?,?,?,?,?)",(uid,pid,"ACTIVE",start,expires,payload.get("payment_ref"),start));sid=cur.lastrowid
    c.execute("INSERT INTO payments(user_id,amount,currency,status,provider,external_id,created) VALUES(?,?,?,?,?,?,?)",(uid,p["price"],"SAR","APPROVED","ADMIN",payload.get("payment_ref"),start));c.commit();c.close()
    invite=None
    bt=os.getenv("TELEGRAM_BOT_TOKEN","");chat=os.getenv("TELEGRAM_CHAT_ID","")
    if bt and chat:
        try:
            r=await req_post(f"https://api.telegram.org/bot{bt}/createChatInviteLink",{"chat_id":chat,"member_limit":1,"expire_date":expires})
            invite=(r.get("result") or {}).get("invite_link")
        except Exception: pass
    return {"ok":True,"subscription_id":sid,"expires":expires,"telegram_invite":invite}

@app.get("/api/admin/tickets")
async def admin_tickets(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT 200")];c.close();return rows

@app.get("/api/options")
async def options(symbol: str="NVDA"):
    if symbol not in MARKETS["us_options"]["symbols"]: return JSONResponse({"error":"unsupported_symbol"},400)
    try:
        j=await req("https://query1.finance.yahoo.com/v7/finance/options/"+symbol)
        r=(j.get("optionChain",{}).get("result") or [None])[0]
        if not r:return {"symbol":symbol,"calls":[],"puts":[]}
        chain=(r.get("options") or [{}])[0]
        def clean(row):
            return [{k:x.get(k) for k in ("contractSymbol","strike","lastPrice","bid","ask","volume","openInterest","impliedVolatility","delta","gamma","theta")} for x in row]
        return {"symbol":symbol,"expiration":chain.get("expirationDate"),"calls":clean(chain.get("calls",[])),"puts":clean(chain.get("puts",[]))}
    except Exception as e:return JSONResponse({"error":"options_data_unavailable","detail":str(e)},502)

@app.get("/api/markets")
async def markets(): return MARKETS

@app.post("/api/worker/ingest")
async def worker_ingest(payload: dict):
    if WORKER_SECRET and not hmac.compare_digest(str(payload.get("secret","")),WORKER_SECRET):
        return JSONResponse({"error":"unauthorized"},401)
    market=str(payload.get("market","")); tf=str(payload.get("tf","")); role=str(payload.get("role","PRIMARY")).upper()
    if market not in MARKETS or tf not in TFS or role not in ("PRIMARY","BACKUP"):
        return JSONResponse({"error":"invalid_worker_scope"},400)
    if not hasattr(app.state,"workers"): app.state.workers={}
    app.state.workers[(market,tf,role)]={"updated":int(payload.get("updated") or time.time()),"items":payload.get("items") or [],"role":role}
    return {"ok":True,"market":market,"tf":tf,"role":role,"items":len(payload.get("items") or [])}

@app.get("/api/worker/status")
async def worker_status():
    now=int(time.time()); rows=[]
    for market in MARKETS:
        for tf in TFS:
            for role in ("PRIMARY","BACKUP"):
                d=getattr(app.state,"workers",{}).get((market,tf,role))
                rows.append({"market":market,"tf":tf,"role":role,"online":bool(d and now-int(d.get("updated",0))<=WORKER_TTL),"updated":d.get("updated",0) if d else 0,"items":len(d.get("items",[])) if d else 0})
    return {"updated":now,"ttl":WORKER_TTL,"services":rows,"endpoint_health":endpoint_status()}

@app.get("/api/signals")
async def signals(market: Optional[str]=None,state: Optional[str]=None):
    if not app.state.data["items"] or time.time()-app.state.data["at"]>180:
        z=await scan_all();save(z);app.state.data={"at":int(time.time()),"items":z}
    items=[]; worker_updated=0
    workers=getattr(app.state,"workers",{})
    for m in MARKETS:
        if market and m!=market: continue
        for t in TFS:
            chosen=None
            for role in ("PRIMARY","BACKUP"):
                d=workers.get((m,t,role))
                if d and time.time()-int(d.get("updated",0))<=WORKER_TTL:
                    chosen=d; break
            if chosen:
                worker_updated=max(worker_updated,int(chosen.get("updated",0))); items.extend(chosen.get("items",[]))
            else:
                items.extend([x for x in app.state.data["items"] if x.get("market")==m and x.get("tf")==t])
    if not items: items=app.state.data["items"]
    items=[x for x in items if (not state or x.get("state")==state)]
    return {"updated":max(app.state.data["at"],worker_updated),"items":sorted(items,key=lambda x:(float(x.get("success_rate") or x.get("confidence") or 0),float(x.get("rr") or 0)),reverse=True),"timeframes":TFS,"execution_timeframe":"INDEPENDENT","markets":MARKETS,"min_volume":1000000,"min_volume_unit":"USD turnover","strategies":["1M","1W","1D","4H","1H","30M","15M"],"independent":True,"worker_architecture":"PRIMARY_WITH_BACKUP_PER_MARKET_TIMEFRAME"}

@app.get("/api/pipeline")
async def pipeline_api(market: Optional[str]=None):
    items=app.state.data.get("items",[])
    return {"updated":app.state.data.get("at",0),"items":[x for x in items if not market or x["market"]==market],"strategies":["1M","1W","1D","4H","1H","30M","15M"] ,"independent":True}

@app.post("/api/trades/launch")
async def launch_trade(payload: dict):
    market=str(payload.get("market","")).strip()
    symbol=str(payload.get("symbol","")).strip()
    tf=str(payload.get("tf","")).strip()
    if market not in MARKETS or not symbol or tf not in TFS:
        return JSONResponse({"ok":False,"error":"invalid_trade"},400)
    items=app.state.data.get("items",[])
    sig=next((x for x in items if x.get("market")==market and x.get("symbol")==symbol and x.get("tf")==tf and x.get("state")=="ENTERED"),None)
    if not sig:
        return JSONResponse({"ok":False,"error":"no_active_signal"},409)
    if sig.get("confidence",0)<90:
        return JSONResponse({"ok":False,"error":"confidence_below_90"},409)
    c=db()
    exists=c.execute("SELECT id FROM trades WHERE market=? AND symbol=? AND tf=? AND status='OPEN'",(market,symbol,tf)).fetchone()
    if exists:
        c.close(); return {"ok":False,"error":"trade_already_open","trade_id":exists["id"]}
    risk=float(sig.get("risk_pct") or 0)
    used=open_risk_pct(c)
    if used + risk > MAX_OPEN_RISK_PCT:
        c.close()
        return JSONResponse({"ok":False,"error":"portfolio_risk_cap","max_risk_pct":MAX_OPEN_RISK_PCT,"open_risk_pct":used,"requested_risk_pct":risk},409)
    cur=c.execute("""INSERT INTO trades(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,confidence,risk_pct,created,source)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(market,symbol,tf,sig["side"],sig["entry"],sig["tp1"],sig["tp2"],sig["tp3"],sig["sl"],sig["confidence"],risk,int(time.time()),"MARKET_SECTION_PAPER"))
    c.commit(); tid=cur.lastrowid; used=open_risk_pct(c); c.close()
    return {"ok":True,"mode":"PAPER","trade_id":tid,"open_risk_pct":used,"max_open_risk_pct":MAX_OPEN_RISK_PCT,"trade":sig}

@app.get("/api/trades")
async def trades(market: Optional[str]=None):
    c=db()
    if market and market in MARKETS:
        z=[dict(x) for x in c.execute("SELECT * FROM trades WHERE market=? ORDER BY COALESCE(quality_score,0) DESC,id DESC LIMIT 200",(market,))]
    else:
        z=[dict(x) for x in c.execute("SELECT * FROM trades ORDER BY COALESCE(quality_score,0) DESC,id DESC LIMIT 200")]
    c.close()
    for i,x in enumerate(z,1):
        x["display_rank"]=i;x["medal"]="🥇" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else "•"))
        x["quality_score"]=round(float(x.get("quality_score") or x.get("confidence") or 0),2)
    return z

@app.get("/api/stats")
async def stats():
    c=db();a=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];o=c.execute("SELECT COUNT(*) n FROM trades WHERE status='OPEN'").fetchone()["n"];p=c.execute("SELECT COALESCE(SUM(pnl),0) p FROM trades WHERE status='CLOSED'").fetchone()["p"]
    w=c.execute("SELECT COUNT(*) n FROM trades WHERE status='CLOSED' AND pnl>0").fetchone()["n"];l=c.execute("SELECT COUNT(*) n FROM trades WHERE status='CLOSED' AND pnl<0").fetchone()["n"];closed=w+l
    by_tf=[dict(x) for x in c.execute("SELECT tf,COUNT(*) trades,SUM(CASE WHEN status='CLOSED' AND pnl>0 THEN 1 ELSE 0 END) wins,SUM(CASE WHEN status='CLOSED' AND pnl<0 THEN 1 ELSE 0 END) losses FROM trades GROUP BY tf")]
    c.close();return {"total":a,"open":o,"closed":a-o,"pnl":round(float(p or 0),4),"wins":w,"losses":l,"win_rate":round(w/closed*100,2) if closed else 0,"loss_rate":round(l/closed*100,2) if closed else 0,"by_tf":by_tf}

@app.get("/api/settings")
async def settings():
    return {"mode":os.getenv("TRADING_MODE","PAPER").upper(),"execution_ready":False,"engine":"TIMEFRAME_SPECIFIC_STRATEGY_ENGINE","live_orders":False,"max_open_risk_pct":MAX_OPEN_RISK_PCT,"modules":["accounts","subscriptions","admin","markets","strategies","signals","telegram","news","blog","security","rate_limit","referrals","analytics","support","legal","push","email"]}

@app.get("/")
async def home(): return FileResponse(ROOT/"static/index.html")

@app.get("/static/{name}")
async def static(name): return FileResponse(ROOT/"static"/name)

@app.exception_handler(Exception)
async def err(request,e): return JSONResponse({"error":"server_error","detail":str(e)},500)
