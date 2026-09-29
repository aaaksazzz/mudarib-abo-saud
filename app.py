from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, hashlib, hmac, secrets, os, json, time, threading, urllib.parse, urllib.request
from intelligence_engine import scan as intelligence_scan, status as intelligence_status, start_engine
from data_hub import binance_tickers as hub_binance_tickers, parallel_quotes as hub_parallel_quotes, status as data_hub_status
from mega_v4_engine import start as start_mega_v4, status as mega_v4_status, get_signals as mega_get_signals, latest_price as mega_latest_price

BASE=Path(__file__).parent; DB=BASE/"app.db"; STORE=BASE/"data.json"
app=FastAPI(title="التداول الذكي PRO",version="4.0")
STATIC=BASE/"static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.get("/")
def homepage():
    return FileResponse(STATIC/"index.html")
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES=["5m","15m","1h","4h","1d","1w","1M"]; SESSION_DAYS=30; PLANS={"7d":10,"15d":20,"30d":30}
SIGNAL_CACHE={}
SIGNAL_CACHE_LOCK=__import__("threading").RLock()
SIGNAL_CACHE_TTL=int(os.getenv("SIGNAL_CACHE_TTL","180"))
MIN_SIGNAL_AI=int(os.getenv("MIN_SIGNAL_AI","58"))
MAX_SIGNAL_ITEMS=int(os.getenv("MAX_SIGNAL_ITEMS","120"))

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def hp(p,s=None):
 s=s or secrets.token_hex(16); return s,hashlib.pbkdf2_hmac("sha256",p.encode(),s.encode(),310000).hex()
def init_db():
 c=db(); c.executescript("""
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,salt TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',active INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,slug TEXT UNIQUE NOT NULL,excerpt TEXT DEFAULT '',body TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,symbol TEXT NOT NULL,market TEXT NOT NULL,timeframe TEXT NOT NULL,side TEXT NOT NULL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,ai REAL DEFAULT 0,status TEXT DEFAULT 'open',result TEXT DEFAULT '',pnl REAL DEFAULT 0,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,plan TEXT NOT NULL,amount REAL NOT NULL,method TEXT DEFAULT '',txid TEXT DEFAULT '',status TEXT DEFAULT 'pending',created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS backtest_results(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,updated_at INTEGER NOT NULL);
 """)
 e=os.getenv("ADMIN_EMAIL","").strip().lower(); p=os.getenv("ADMIN_PASSWORD","")
 if e and p:
  r=c.execute("SELECT id FROM users WHERE email=?",(e,)).fetchone()
  if not r:
   s,ph=hp(p); c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",(e,ph,s,"admin",1,int(time.time())))
  else: c.execute("UPDATE users SET role='admin',active=1 WHERE email=?",(e,))
 c.commit(); c.close()
 # Add live-tracking columns to existing databases without destroying data.
 c=db()
 cols={r["name"] for r in c.execute("PRAGMA table_info(trades)").fetchall()}
 for name,sql in {
   "source":"ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'",
   "current_price":"ALTER TABLE trades ADD COLUMN current_price REAL DEFAULT 0",
   "closed_at":"ALTER TABLE trades ADD COLUMN closed_at INTEGER DEFAULT 0"
 }.items():
  if name not in cols:
   try: c.execute(sql)
   except Exception: pass
 if "source" not in cols:
  try: c.execute("UPDATE trades SET source='legacy'")
  except Exception: pass
 c.commit(); c.close()
@app.on_event("startup")
def startup():
 init_db()
 start_mega_v4()
 start_live_tracker()
def me(request):
 t=request.cookies.get("session")
 if not t:return None
 c=db(); r=c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",(hashlib.sha256(t.encode()).hexdigest(),int(time.time()))).fetchone(); c.close()
 return dict(r) if r else None
def user(request):
 u=me(request)
 if not u: raise HTTPException(401,"يجب تسجيل الدخول")
 return u
def admin(request):
 u=user(request)
 if u["role"]!="admin": raise HTTPException(403,"ليس لديك صلاحية الإدارة")
 return u

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","version":"4.0","time":datetime.now(timezone.utc).isoformat()}
@app.post("/api/auth/register")
def register(d:dict):
 e=str(d.get("email","")).strip().lower(); p=str(d.get("password",""))
 if "@" not in e: raise HTTPException(400,"البريد غير صحيح")
 if len(p)<8: raise HTTPException(400,"كلمة المرور 8 أحرف على الأقل")
 s,ph=hp(p); c=db()
 try: cur=c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",(e,ph,s,"user",1,int(time.time()))); c.commit(); uid=cur.lastrowid
 except sqlite3.IntegrityError: c.close(); raise HTTPException(409,"الحساب موجود مسبقاً")
 c.close(); return {"ok":True,"user":{"id":uid,"email":e,"role":"user"}}
@app.post("/api/auth/login")
def login(d:dict):
 e=str(d.get("email","")).strip().lower(); p=str(d.get("password","")); c=db(); r=c.execute("SELECT * FROM users WHERE email=?",(e,)).fetchone(); c.close()
 if not r or not r["active"]: raise HTTPException(401,"بيانات الدخول غير صحيحة")
 _,ph=hp(p,r["salt"])
 if not hmac.compare_digest(ph,r["password_hash"]): raise HTTPException(401,"بيانات الدخول غير صحيحة")
 t=secrets.token_urlsafe(48); now=int(time.time()); c=db(); c.execute("INSERT INTO sessions VALUES(?,?,?,?)",(hashlib.sha256(t.encode()).hexdigest(),r["id"],now+SESSION_DAYS*86400,now)); c.commit(); c.close()
 x=JSONResponse({"ok":True,"user":{"id":r["id"],"email":r["email"],"role":r["role"]}}); x.set_cookie("session",t,max_age=SESSION_DAYS*86400,httponly=True,samesite="lax",secure=True,path="/"); return x
@app.post("/api/auth/logout")
def logout(request:Request):
 t=request.cookies.get("session")
 if t:
  c=db(); c.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(t.encode()).hexdigest(),)); c.commit(); c.close()
 x=JSONResponse({"ok":True}); x.delete_cookie("session",path="/"); return x
@app.get("/api/auth/me")
def auth_me(request:Request):
 u=me(request); return {"authenticated":bool(u),"user":({"id":u["id"],"email":u["email"],"role":u["role"]} if u else None)}

def binance(symbol,interval,futures=False):
 host="https://fapi.binance.com" if futures else "https://api.binance.com"; path="/fapi/v1/klines" if futures else "/api/v3/klines"; q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":250})
 try:
  with urllib.request.urlopen(host+path+"?"+q,timeout=4) as r:return json.loads(r.read())
 except:return []
def _clamp(v,a=0,b=100): return max(a,min(b,v))

def _ema(values, period):
    if len(values)<period: return values[-1] if values else 0
    k=2/(period+1); e=sum(values[:period])/period
    for v in values[period:]: e=v*k+e*(1-k)
    return e

def _rsi(values, period=14):
    if len(values)<=period: return 50
    gains=[]; losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    if al==0: return 100
    return 100-(100/(1+ag/al))

def _snapshot(symbol,market,frame):
    if market not in ("spot","futures","contracts"): return {}
    rows=binance(symbol,frame,market in ("futures","contracts"))
    if len(rows)<20: return {}
    closes=[float(r[4]) for r in rows]; highs=[float(r[2]) for r in rows]; lows=[float(r[3]) for r in rows]
    vols=[float(r[7]) for r in rows]
    ema20=_ema(closes,20); ema50=_ema(closes,50); ema200=_ema(closes,200)
    rsi=_rsi(closes,14)
    macd=_ema(closes,12)-_ema(closes,26)
    signal_line=_ema([_ema(closes[:i+1],12)-_ema(closes[:i+1],26) for i in range(25,len(closes))],9)
    atr=sum(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(rows)))/max(1,len(rows)-1)
    vr=vols[-1]/(sum(vols[-21:-1])/20) if len(vols)>21 and sum(vols[-21:-1]) else 1
    return {"price":closes[-1],"ema20":ema20,"ema50":ema50,"ema200":ema200,"rsi":rsi,"macd":macd,"macd_signal":signal_line,"atr":atr,"volume_ratio":vr}

def deep_signal(symbol,market,frame,tickers=None,metrics=None):
    x=(tickers or {}).get(symbol,{})
    m=metrics or {}
    try:
        price=float(m.get("price") or x.get("lastPrice") or x.get("regularMarketPrice") or 0)
        change=float(x.get("priceChangePercent") or x.get("regularMarketChangePercent") or 0)
        volume=float(x.get("quoteVolume") or x.get("regularMarketVolume") or 0)
    except Exception:
        price=0; change=0; volume=0
    ema200=m.get("ema200")
    macd=m.get("macd")
    if price<=0 or ema200 is None or macd is None:
        return None
    # Locked strategy: no reversal.
    # BUY / BUY STRONG: price below EMA200 AND MACD below zero.
    # SELL / SELL STRONG: price above EMA200 AND MACD above zero.
    if price < ema200 and macd < 0:
        side="BUY"
    elif price > ema200 and macd > 0:
        side="SELL"
    else:
        return None
    # Spot remains buy-only.
    if market=="spot" and side!="BUY":
        return None
    ema20=m.get("ema20",price); ema50=m.get("ema50",price)
    volume_ratio=float(m.get("volume_ratio",1) or 1)
    rsi=float(m.get("rsi",50) or 50)
    agreement=1
    ai=round(_clamp(62 + (8 if ((side=="BUY" and price<ema200 and macd<0) or (side=="SELL" and price>ema200 and macd>0)) else 0)
                     + min(max(volume_ratio-1,0)*15,15)
                     + (5 if (side=="BUY" and rsi<50) or (side=="SELL" and rsi>50) else 0)))
    ai=_clamp(ai,0,99)
    risk_amt=max(price*(0.008 if frame in ("15m","1h") else 0.012),price*0.002)
    if m.get("atr",0)>0: risk_amt=max(risk_amt,float(m["atr"])*0.8)
    if side=="BUY": t=[price+risk_amt*i for i in (1,2,3)]; sl=price-risk_amt
    else: t=[price-risk_amt*i for i in (1,2,3)]; sl=price+risk_amt
    # Trading rule: bearish setup opens BUY; bullish setup opens SELL.
    original_side=side
    old_tp=list(t)
    side="SELL" if original_side=="BUY" else "BUY"
    if original_side=="BUY":
        t=[price-(v-price) for v in old_tp]; sl=price+(price-sl)
    else:
        t=[price+(v-price) for v in old_tp]; sl=price-(sl-price)
    strength="أفضل تغير" if side=="BUY" else "أسوأ تغير"
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"original_side":original_side,
            "label":strength,"ai":ai,"agreement":agreement,
            "entry":price,"tp1":t[0],"tp2":t[1],"tp3":t[2],"sl":sl,
            "change":round(change,3),"updated":int(time.time()),
            "ema200":round(float(ema200),10),"macd":round(float(macd),10),
            "strategy":"EMA200 + MACD zero (locked)"}


def signal(symbol,market,frame):
    rows=binance(symbol,frame,market in ("futures","contracts"))
    if rows:
        q={}
        last=rows[-1]; prev=rows[-2]
        q["lastPrice"]=last[4]
        q["priceChangePercent"]=(float(last[4])/float(prev[4])-1)*100 if float(prev[4]) else 0
        q["quoteVolume"]=sum(float(r[7]) for r in rows[-20:])
        return deep_signal(symbol,market,frame,{symbol:q})
    return deep_signal(symbol,market,frame,{symbol:{}})

SYMBOL_CACHE={}
SYMBOL_CACHE_TTL=300

def all_binance_symbols(futures=False):
 key="futures" if futures else "spot"; now=time.time()
 cached=SYMBOL_CACHE.get(key)
 if cached and now-cached["time"]<SYMBOL_CACHE_TTL:
  return cached["symbols"]
 host="https://fapi.binance.com" if futures else "https://api.binance.com"
 path="/fapi/v1/exchangeInfo" if futures else "/api/v3/exchangeInfo"
 try:
  with urllib.request.urlopen(host+path,timeout=8) as r:
   data=json.loads(r.read())
  out=[]
  for x in data.get("symbols",[]):
   if x.get("status")!="TRADING": continue
   if x.get("quoteAsset")!="USDT": continue
   if not futures and str(x.get("baseAsset","")).upper() in BT_STABLECOINS: continue
   if futures and x.get("contractType") not in (None,"PERPETUAL","CURRENT_QUARTER","NEXT_QUARTER"): continue
   out.append(x["symbol"])
  out=sorted(set(out))
  # Spot: only USDT pairs with 24h quote volume above 1,000,000 USDT.
  if not futures and out:
   try:
    with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/24hr",timeout=8) as r:
     tickers=json.loads(r.read())
    allowed=set(out)
    liquid={str(x.get("symbol")) for x in tickers if x.get("symbol") in allowed and float(x.get("quoteVolume",0) or 0)>1000000}
    if liquid: out=sorted(liquid)
   except Exception:
    pass
  if out:
   SYMBOL_CACHE[key]={"time":now,"symbols":out}
   return out
 except Exception:
  pass
 return cached["symbols"] if cached else ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]

SYMBOL_LIST_CACHE={}
SYMBOL_LIST_TTL=1800
FOREX_SYMBOLS=["EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD","EURGBP","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCHF","GBPCHF","AUDCAD","AUDCHF","CADJPY","NZDJPY","NZDCHF","GBPAUD","GBPCAD","EURCAD","USDMXN","USDZAR","USDTRY","USDNOK","USDSEK","USDSGD","USDHKD","USDCNH","USDPLN","USDHUF","USDCZK"]
SAUDI_SYMBOLS_CACHE=None
def all_saudi_stocks():
 global SAUDI_SYMBOLS_CACHE
 if SAUDI_SYMBOLS_CACHE:return SAUDI_SYMBOLS_CACHE
 try:
  url="https://www.saudiexchange.sa/Resources/Reports-v2/Yearly_ar.html"
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
  with urllib.request.urlopen(req,timeout=12) as r: html=r.read().decode("utf-8","ignore")
  import re
  codes=re.findall(r">\s*(\d{4})\s*<",html)
  vals=sorted(set(codes+["1324"]))
  if len(vals)>=100:
   SAUDI_SYMBOLS_CACHE=vals
   return vals
 except Exception: pass
 return ["1010","1120","1150","1180","2010","2020","2222","2223","2280","2290","2380","2381","2382","3030","4001","4013","4030","4190","4200","4250","4261","4300","4321","6015","7020","7202","7203","8010","8230"]

def all_us_stocks():
 key="us_stocks"; now=time.time(); cached=SYMBOL_LIST_CACHE.get(key)
 if cached and now-cached["time"]<SYMBOL_LIST_TTL:return cached["symbols"]
 urls=["https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt","https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"]
 out=set()
 try:
  for url in urls:
   with urllib.request.urlopen(url,timeout=10) as r: txt=r.read().decode("utf-8","ignore")
   lines=txt.splitlines()
   for line in lines[1:]:
    if not line or line.startswith("File Creation Time"):continue
    parts=line.split("|")
    sym=parts[1].strip() if len(parts)>1 else ""
    test=parts[-1].strip() if parts else ""
    if sym and sym not in ("Symbol","File Creation Time") and not sym.startswith("$") and "test" not in test.lower():
     if "^" not in sym and "/" not in sym: out.add(sym.replace(".","-"))
  vals=sorted(out)
  if vals: SYMBOL_LIST_CACHE[key]={"time":now,"symbols":vals}; return vals
 except Exception:
  pass
 return cached["symbols"] if cached else ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA"]

def symbols(m):
 if m=="spot": return all_binance_symbols(False)
 if m in ("futures","contracts"): return all_binance_symbols(True)
 if m=="saudi": return all_saudi_stocks()
 if m=="us": return all_us_stocks()
 if m=="forex": return FOREX_SYMBOLS
 return ["BTCUSDT","ETHUSDT","SOLUSDT"]
@app.get("/api/data/status")
def data_status():
 return data_hub_status()

@app.get("/api/markets")
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"default":"5m","min_ai":MIN_SIGNAL_AI}
TICKER_CACHE={}
TICKER_CACHE_TTL=30

def binance_tickers(futures=False):
 return hub_binance_tickers(futures,min_volume=1000000 if not futures else 0)

def yahoo_tickers(symbols_list,forex=False,saudi=False):
 return hub_parallel_quotes(symbols_list,"forex" if forex else ("saudi" if saudi else "us"))

def fast_signal(symbol,market,frame,tickers):
    return deep_signal(symbol,market,frame,tickers)

@app.get("/api/trades")
def trades(market="spot",timeframe="15m"):
    if market not in MARKETS or timeframe not in FRAMES:
        return {"items":[],"error":"invalid market/timeframe"}
    key=f"{market}:{timeframe}"
    now=time.time()
    with SIGNAL_CACHE_LOCK:
        cached=SIGNAL_CACHE.get(key)
        if cached and now-cached["time"]<SIGNAL_CACHE_TTL:
            return cached["data"]

    items=[]
    # Crypto markets use the dedicated mega scanner because it already performs
    # the bulk Binance scan and indicator calculation. This avoids one HTTP
    # request per symbol and fixes empty spot results.
    if market in ("spot","futures","contracts"):
        engine_market="futures" if market in ("futures","contracts") else "spot"
        raw=mega_get_signals(engine_market,timeframe,min(MAX_SIGNAL_ITEMS,200))
        for z in raw.get("items",[]):
            x=dict(z)
            x["market"]=market
            original=x.get("original_side",x.get("side"))
            x["original_side"]=original
            if float(x.get("ai",0) or 0)>=MIN_SIGNAL_AI:
                items.append(x)
    else:
        syms=symbols(market)
        tickers=yahoo_tickers(syms,market=="forex",market=="saudi")
        # Non-crypto markets: only accept complete indicator snapshots.
        for sym in syms[:200]:
            try:
                x=deep_signal(sym,market,timeframe,tickers,_snapshot(sym,market,timeframe))
                if x and float(x.get("ai",0) or 0)>=MIN_SIGNAL_AI:
                    items.append(x)
            except Exception:
                continue

    # Keep the requested directional ordering.
    buys=sorted([x for x in items if x.get("side")=="BUY"],
                key=lambda x:(x.get("change",0),x.get("ai",0)),reverse=True)
    sells=sorted([x for x in items if x.get("side")=="SELL"],
                 key=lambda x:(x.get("change",0),-x.get("ai",0)))
    items=(buys+sells)[:MAX_SIGNAL_ITEMS]
    data={"items":items,"market":market,"timeframe":timeframe,"count":len(items),
          "scanned":len(items),"min_ai":MIN_SIGNAL_AI,
          "note":"AI confidence is a model score, not a guarantee."}
    with SIGNAL_CACHE_LOCK:
        SIGNAL_CACHE[key]={"time":now,"data":data}
    return data

@app.get("/api/scanner")
def scanner(timeframe="15m"):
    if timeframe not in FRAMES: timeframe="15m"
    candidates=[]
    for market in MARKETS:
        syms=symbols(market)
        if market in ("spot","futures","contracts"): tk=binance_tickers(market in ("futures","contracts"))
        elif market in ("us","forex","saudi"): tk=yahoo_tickers(syms,market=="forex",market=="saudi")
        else: tk={}
        pool=[deep_signal(sym,market,timeframe,tk) for sym in syms if (not tk or sym in tk)]
        pool.sort(key=lambda z:(z["ai"],z["agreement"],abs(z.get("change",0))),reverse=True)
        # Deep indicator study is applied to the strongest candidates, keeping the scan broad.
        for z in pool[:40]:
            z.update(deep_signal(z["symbol"],market,timeframe,tk,_snapshot(z["symbol"],market,timeframe)))
        candidates.extend(pool[:40])
    candidates.sort(key=lambda z:(abs(z.get("change",0)),z.get("ai",0),z.get("agreement",0)),reverse=True)
    return {"items":candidates[:80],"timeframe":timeframe,"scanned":sum(len(symbols(m)) for m in MARKETS),"analysts":7}



def _signal_warmer():
    while True:
        try:
            for frame in FRAMES[:3]:
                for market in ("spot","futures"):
                    try: trades(market,frame)
                    except Exception: pass
        except Exception:
            pass
        time.sleep(SIGNAL_CACHE_TTL)

@app.get("/api/signals/status")
def signals_status():
    with SIGNAL_CACHE_LOCK:
        return {"running":True,"cache_entries":len(SIGNAL_CACHE),"ttl":SIGNAL_CACHE_TTL,
                "frames":FRAMES,"markets":list(MARKETS),"min_ai":MIN_SIGNAL_AI,
                "max_items":MAX_SIGNAL_ITEMS}

@app.get("/api/mega-v4/status")
def mega_v4_status_api():
    return mega_v4_status()

@app.get("/api/mega-v4")
def mega_v4_api(timeframe="15m", market="spot", limit=120):
    if timeframe not in FRAMES: timeframe="15m"
    if market not in ("spot","futures","contracts"): market="spot"
    data=mega_get_signals("futures" if market=="contracts" else market,timeframe,max(1,min(int(limit),200)))
    items=[]
    for z in data.get("items",[]):
        x=dict(z); x["market"]=market
        if reverse:
            original=x["side"]; entry=float(x["entry"]); x["original_side"]=original
            x["side"]="SELL" if original=="BUY" else "BUY"
            old=[float(x["tp1"]),float(x["tp2"]),float(x["tp3"])]
            if original=="BUY":
                x["tp1"],x["tp2"],x["tp3"]=[entry-(v-entry) for v in old]; x["sl"]=entry+(entry-float(x["sl"]))
            else:
                x["tp1"],x["tp2"],x["tp3"]=[entry+(entry-v) for v in old]; x["sl"]=entry-(float(x["sl"])-entry)
        items.append(x)
    data["items"]=items; data["market"]=market
    data["note"]="AI confidence is a model score, not a guarantee."
    return data

@app.get("/api/intelligence/status")
def intelligence_status_api():
 return intelligence_status()

@app.get("/api/intelligence")
def intelligence_api(timeframe="15m", market="spot", limit=50):
 if timeframe not in ("5m","15m","1h","4h","1d","1w","1M"): timeframe="15m"
 if market not in ("spot","futures","contracts"): market="spot"
 data=intelligence_scan(timeframe,max(1,min(int(limit),100)),market in ("futures","contracts"))
 data["market"]=market
 return data



# --- Historical backtest: original BUY vs reversed SELL ---
BT_STATE={"running":False,"done":False,"progress":0,"total":0,"result":None,"error":None,"started":0,"finished":0}
BT_LOCK=threading.RLock()
BT_RESULT_FILE=BASE/"backtest_result.json"
BT_STABLECOINS={"USDC","FDUSD","TUSD","USDP","DAI","USDS","USDE","PYUSD","EURC","USD1","USDD","BUSD"}

def _bt_get_15m(symbol,start_ms,end_ms):
    out=[]; cursor=int(end_ms)
    for _ in range(8):
        q=urllib.parse.urlencode({"symbol":symbol,"interval":"15m","limit":1000,"endTime":cursor})
        try:
            with urllib.request.urlopen("https://api.binance.com/api/v3/klines?"+q,timeout=8) as r: rows=json.loads(r.read())
        except Exception: break
        if not rows: break
        out=rows+out; oldest=int(rows[0][0])
        if oldest<=start_ms or len(rows)<1000: break
        cursor=oldest-1
    seen=set(); clean=[]
    for r in out:
        t=int(r[0])
        if start_ms<=t<=end_ms and t not in seen: seen.add(t); clean.append(r)
    return sorted(clean,key=lambda x:int(x[0]))

def _bt_ema(vals,p):
    out=[None]*len(vals)
    if len(vals)<p:return out
    e=sum(vals[:p])/p; out[p-1]=e; k=2/(p+1)
    for i in range(p,len(vals)): e=vals[i]*k+e*(1-k); out[i]=e
    return out

def _bt_rsi(vals,p=14):
    out=[None]*len(vals)
    if len(vals)<=p:return out
    g=[0.0]*len(vals); l=[0.0]*len(vals)
    for i in range(1,len(vals)):
        d=vals[i]-vals[i-1]; g[i]=max(d,0); l[i]=max(-d,0)
    ag=sum(g[1:p+1])/p; al=sum(l[1:p+1])/p
    out[p]=100 if al==0 else 100-(100/(1+ag/al))
    for i in range(p+1,len(vals)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        out[i]=100 if al==0 else 100-(100/(1+ag/al))
    return out

def _bt_symbol(symbol,start_ms,end_ms):
    rows=_bt_get_15m(symbol,start_ms-45*86400000,end_ms)
    if len(rows)<1000:return []
    ts=[int(r[0]) for r in rows]; op=[float(r[1]) for r in rows]
    hi=[float(r[2]) for r in rows]; lo=[float(r[3]) for r in rows]; cl=[float(r[4]) for r in rows]; vol=[float(r[7]) for r in rows]
    e20=_bt_ema(cl,20); e200=_bt_ema(cl,200); rs=_bt_rsi(cl)
    hc={}
    for i,t in enumerate(ts): hc[t-(t%3600000)]=cl[i]
    hk=sorted(hc); he=_bt_ema([hc[h] for h in hk],200); hm={h:(hc[h],he[i]) for i,h in enumerate(hk)}
    out=[]; positions={"BUY":None,"SELL":None}
    for i in range(200,len(rows)-1):
        t=ts[i]
        for side,pos in list(positions.items()):
            if not pos: continue
            entry=pos["entry"]
            if side=="BUY":
                if lo[i]<=entry*0.98: out.append({"side":"BUY","result":"loss","pnl":-2.0,"time":pos["time"]}); positions[side]=None
                elif hi[i]>=entry*1.04: out.append({"side":"BUY","result":"win","pnl":4.0,"time":pos["time"]}); positions[side]=None
            else:
                if hi[i]>=entry*1.02: out.append({"side":"SELL","result":"loss","pnl":-2.0,"time":pos["time"]}); positions[side]=None
                elif lo[i]<=entry*0.96: out.append({"side":"SELL","result":"win","pnl":4.0,"time":pos["time"]}); positions[side]=None
        if t<start_ms: continue
        prev=t-(t%3600000)-3600000
        if prev not in hm or hm[prev][1] is None or e20[i] is None or e200[i] is None or rs[i] is None: continue
        hclose,hema=hm[prev]
        avg=sum(vol[i-20:i])/20
        if hclose>hema and cl[i]>e20[i] and rs[i]>50 and vol[i]>avg and cl[i]>e200[i]:
            entry=op[i+1]
            if entry>0:
                if positions["BUY"] is None: positions["BUY"]={"entry":entry,"time":ts[i+1]}
                if positions["SELL"] is None: positions["SELL"]={"entry":entry,"time":ts[i+1]}
    return out

def _bt_summary(trades):
    wins=sum(x["result"]=="win" for x in trades); losses=len(trades)-wins; net=sum(x["pnl"] for x in trades)
    eq=peak=dd=0
    for x in sorted(trades,key=lambda z:z["time"]): eq+=x["pnl"]; peak=max(peak,eq); dd=min(dd,eq-peak)
    return {"trades":len(trades),"wins":wins,"losses":losses,"win_rate":round(wins/len(trades)*100,2) if trades else 0,"net_pct":round(net,2),"profit_factor":round((wins*4)/(losses*2),2) if losses else None,"max_drawdown_pct":round(abs(dd),2)}

def _bt_run(limit=0):
    now=int(time.time()*1000); end=now-(now%900000)-1; start=end-30*86400000
    syms=all_binance_symbols(False)
    # Keep only Spot USDT pairs with 24h quote volume above 1,000,000 USDT.
    try:
        with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/24hr",timeout=15) as r: tick=json.loads(r.read())
        liquid={str(x.get("symbol")) for x in tick if str(x.get("symbol","")).endswith("USDT") and float(x.get("quoteVolume",0) or 0)>1000000}
        syms=[x for x in syms if x in liquid]
    except Exception:
        pass
    if limit>0: syms=syms[:limit]
    with BT_LOCK: BT_STATE.update({"running":True,"done":False,"progress":0,"total":len(syms),"result":None,"error":None,"started":int(time.time())})
    alltr=[]; failed=0
    from concurrent.futures import ThreadPoolExecutor,as_completed
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs=[ex.submit(_bt_symbol,x,start,end) for x in syms]
        for n,f in enumerate(as_completed(fs),1):
            try: alltr.extend(f.result())
            except Exception: failed+=1
            with BT_LOCK: BT_STATE["progress"]=n
    result={"period_days":30,"symbols":len(syms),"failed_symbols":failed,"original_buy":_bt_summary([x for x in alltr if x["side"]=="BUY"]),"reversed_sell":_bt_summary([x for x in alltr if x["side"]=="SELL"]),"sl_pct":2,"tp_pct":4,"stablecoins_excluded":sorted(BT_STABLECOINS),"liquidity_rule":"24h quote volume > 1,000,000 USDT","timeframe":"15m"}
    try: BT_RESULT_FILE.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
    except Exception: pass
    try:
        payload=json.dumps(result,ensure_ascii=False)
        c=db(); c.execute("INSERT INTO backtest_results(id,payload,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(payload,int(time.time()))); c.commit(); c.close()
    except Exception: pass
    with BT_LOCK: BT_STATE.update({"running":False,"done":True,"progress":len(syms),"result":result,"finished":int(time.time())})

@app.post("/api/backtest/both")
def start_backtest_both(limit:int=0):
    with BT_LOCK:
        if BT_STATE["running"]: return {"ok":True,"started":False,"state":dict(BT_STATE)}
    threading.Thread(target=_bt_run,args=(max(0,min(limit,2000)),),daemon=True).start()
    return {"ok":True,"started":True}

@app.get("/api/backtest/both/status")
def backtest_both_status():
    with BT_LOCK: state=dict(BT_STATE)
    if not state["result"] and not state["running"]:
        try:
            c=db(); row=c.execute("SELECT payload FROM backtest_results WHERE id=1").fetchone(); c.close()
            if row:
                state["result"]=json.loads(row["payload"]); state["done"]=True
        except Exception: pass
        if not state["result"] and BT_RESULT_FILE.exists():
            try: state["result"]=json.loads(BT_RESULT_FILE.read_text(encoding="utf-8")); state["done"]=True
            except Exception: pass
    return state

# --- Content, tracker and admin API ---
def _live_price(symbol, market, tickers):
    try:
        x=tickers.get(symbol,{})
        return float(x.get("lastPrice") or x.get("regularMarketPrice") or 0)
    except Exception:
        return 0.0

def _sync_live_trades():
    now=int(time.time())
    for market in ("spot","futures","contracts"):
        try:
            data=mega_get_signals("futures" if market=="contracts" else market,"15m",160)
            candidates=data.get("items",[])
            c=db()
            for raw in candidates:
                sig=dict(raw); sig["market"]=market
                if sig.get("ai",0)<MIN_SIGNAL_AI: continue
                original=sig["side"]; entry=float(sig["entry"]); old=[float(sig["tp1"]),float(sig["tp2"]),float(sig["tp3"])]
                sig["side"]="SELL" if original=="BUY" else "BUY"
                if original=="BUY":
                    sig["tp1"],sig["tp2"],sig["tp3"]=[entry-(v-entry) for v in old]; sig["sl"]=entry+(entry-float(sig["sl"]))
                else:
                    sig["tp1"],sig["tp2"],sig["tp3"]=[entry+(v-entry) for v in old]; sig["sl"]=entry-(float(sig["sl"])-entry)
                price=float(mega_latest_price(sig["symbol"],"futures" if market in ("futures","contracts") else "spot") or sig.get("entry",0) or 0)
                if price<=0: continue
                row=c.execute("SELECT * FROM trades WHERE source='live' AND symbol=? AND market=? AND timeframe='15m' AND status='open' ORDER BY id DESC LIMIT 1",(sig["symbol"],market)).fetchone()
                if row:
                    entry=float(row["entry"] or 0); side=row["side"]
                    pnl=((price-entry)/entry*100) if side=="BUY" and entry else ((entry-price)/entry*100 if entry else 0)
                    tp=price>=float(row["tp1"]) if side=="BUY" else price<=float(row["tp1"])
                    sl=price<=float(row["sl"]) if side=="BUY" else price>=float(row["sl"])
                    if tp or sl:
                        c.execute("UPDATE trades SET status='closed',result=?,pnl=?,current_price=?,closed_at=? WHERE id=?",( "win" if tp else "loss",round(pnl,4),price,now,row["id"]))
                    else:
                        c.execute("UPDATE trades SET pnl=?,current_price=? WHERE id=?",(round(pnl,4),price,row["id"]))
                    continue
                recent=c.execute("SELECT created_at FROM trades WHERE source='live' AND symbol=? AND market=? AND timeframe='15m' ORDER BY id DESC LIMIT 1",(sig["symbol"],market)).fetchone()
                if recent and now-int(recent["created_at"])<600: continue
                c.execute("INSERT INTO trades(user_id,symbol,market,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status,result,pnl,created_at,source,current_price,closed_at) VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,'open','',0,?,?,0)",
                          (sig["symbol"],market,"15m",sig["side"],sig["entry"],sig["tp1"],sig["tp2"],sig["tp3"],sig["sl"],sig["ai"],now,"live",price))
            c.commit(); c.close()
        except Exception:
            continue

def _live_tracker_loop():
    while True:
        try:
            _sync_live_trades()
        except Exception:
            pass
        time.sleep(90)

_LIVE_TRACKER_STARTED=False
def start_live_tracker():
    global _LIVE_TRACKER_STARTED
    if _LIVE_TRACKER_STARTED: return
    _LIVE_TRACKER_STARTED=True
    threading.Thread(target=_live_tracker_loop,name="live-trade-tracker",daemon=True).start()

@app.get("/api/tracker")
def tracker_api(request: Request):
    # Public tracker: all server-created live trades. User accounts do not hide
    # the global live performance counters.
    c = db()
    rows = c.execute("SELECT * FROM trades WHERE source='live' ORDER BY created_at DESC LIMIT 200").fetchall()
    open_count = c.execute("SELECT COUNT(*) n FROM trades WHERE source='live' AND status='open'").fetchone()["n"]
    win_count = c.execute("SELECT COUNT(*) n FROM trades WHERE source='live' AND status='closed' AND result='win'").fetchone()["n"]
    loss_count = c.execute("SELECT COUNT(*) n FROM trades WHERE source='live' AND status='closed' AND result='loss'").fetchone()["n"]
    closed_count = c.execute("SELECT COUNT(*) n FROM trades WHERE source='live' AND status='closed'").fetchone()["n"]
    pnl_row = c.execute("SELECT COALESCE(SUM(pnl),0) v FROM trades WHERE source='live'").fetchone()
    stats = {
        "open": int(open_count or 0),
        "wins": int(win_count or 0),
        "losses": int(loss_count or 0),
        "closed": int(closed_count or 0),
        "pnl": round(float(pnl_row["v"] or 0), 4),
        "total": int((open_count or 0) + (closed_count or 0))
    }
    items=[dict(x) for x in rows]
    c.close()
    return {"items":items,"stats":stats}

@app.get("/api/blog")
def blog_api():
    c=db()
    rows=c.execute("SELECT id,title,slug,excerpt,created_at,updated_at FROM articles WHERE published=1 ORDER BY created_at DESC LIMIT 100").fetchall()
    c.close()
    return {"items":[dict(x) for x in rows]}

@app.get("/api/blog/{slug}")
def blog_item(slug:str):
    c=db()
    r=c.execute("SELECT id,title,slug,excerpt,body,created_at,updated_at FROM articles WHERE slug=? AND published=1",(slug,)).fetchone()
    c.close()
    if not r: raise HTTPException(404,"المقال غير موجود")
    return dict(r)

@app.get("/api/news")
def news_api():
    # Internal market bulletin: no dependency on a fragile external news feed.
    now=int(time.time())
    items=[]
    for market,label in MARKETS.items():
        items.append({
            "title": f"تحديث {label}: بيانات السوق متاحة الآن للتحليل",
            "time": now,
            "market": market,
            "type": "market"
        })
    return {"items":items,"updated":now,"source":"internal-market-feed"}

@app.get("/api/admin/stats")
def admin_stats(request:Request):
    admin(request)
    c=db()
    users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    articles=c.execute("SELECT COUNT(*) n FROM articles").fetchone()["n"]
    trades_count=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"]
    pending=c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='pending'").fetchone()["n"]
    c.close()
    return {"users":users,"articles":articles,"trades":trades_count,"pending_subscriptions":pending}

@app.get("/api/admin/users")
def admin_users(request:Request):
    admin(request)
    c=db()
    rows=c.execute("SELECT id,email,role,active,created_at FROM users ORDER BY id DESC").fetchall()
    c.close()
    return {"items":[dict(x) for x in rows]}

@app.patch("/api/admin/users/{uid}")
def admin_user_update(uid:int,d:dict,request:Request):
    admin(request)
    fields=[]; vals=[]
    if "role" in d and d["role"] in ("user","admin"):
        fields.append("role=?"); vals.append(d["role"])
    if "active" in d:
        fields.append("active=?"); vals.append(1 if d["active"] else 0)
    if not fields: return {"ok":True}
    vals.append(uid)
    c=db(); c.execute("UPDATE users SET "+",".join(fields)+" WHERE id=?",vals); c.commit(); c.close()
    return {"ok":True}

@app.get("/api/admin/blog/all")
def admin_blog_all(request:Request):
    admin(request)
    c=db()
    rows=c.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()
    c.close()
    return {"items":[dict(x) for x in rows]}

@app.post("/api/admin/blog")
def admin_blog_add(d:dict,request:Request):
    admin(request)
    title=str(d.get("title","")).strip()
    slug=str(d.get("slug","")).strip().lower().replace(" ","-")
    excerpt=str(d.get("excerpt","")).strip()
    body=str(d.get("body","")).strip()
    if not title or not slug or not body: raise HTTPException(400,"العنوان والرابط والمحتوى مطلوبة")
    now=int(time.time()); c=db()
    try:
        cur=c.execute("INSERT INTO articles(title,slug,excerpt,body,published,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(title,slug,excerpt,body,1 if d.get("published",True) else 0,now,now))
        c.commit(); aid=cur.lastrowid
    except sqlite3.IntegrityError:
        c.close(); raise HTTPException(409,"رابط المقال موجود مسبقاً")
    c.close()
    return {"ok":True,"id":aid}

@app.delete("/api/admin/blog/{aid}")
def admin_blog_delete(aid:int,request:Request):
    admin(request)
    c=db(); c.execute("DELETE FROM articles WHERE id=?",(aid,)); c.commit(); c.close()
    return {"ok":True}

@app.get("/api/admin/subscriptions")
def admin_subscriptions(request:Request):
    admin(request)
    c=db()
    rows=c.execute("SELECT s.*,u.email FROM subscriptions s JOIN users u ON u.id=s.user_id ORDER BY s.created_at DESC").fetchall()
    c.close()
    return {"items":[dict(x) for x in rows]}

@app.patch("/api/admin/subscriptions/{sid}")
def admin_subscription_update(sid:int,d:dict,request:Request):
    admin(request)
    status=str(d.get("status",""))
    if status not in ("pending","approved","rejected"): raise HTTPException(400,"حالة غير صحيحة")
    c=db(); c.execute("UPDATE subscriptions SET status=? WHERE id=?",(status,sid)); c.commit(); c.close()
    return {"ok":True}

@app.post("/api/admin/telegram/test")
def admin_telegram_test(request:Request):
    admin(request)
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.getenv("TELEGRAM_CHAT_ID","").strip() or os.getenv("TELEGRAM_CHANNEL","").strip()
    if not token or not chat:
        raise HTTPException(503,"أضف TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID في Northflank")
    payload=json.dumps({"chat_id":chat,"text":"✅ اختبار اتصال التداول الذكي PRO"}).encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=payload,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            data=json.loads(r.read())
        return {"ok":bool(data.get("ok"))}
    except Exception as e:
        raise HTTPException(502,"تعذر إرسال اختبار Telegram")
