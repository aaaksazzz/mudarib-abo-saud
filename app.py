from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, hashlib, hmac, secrets, os, json, time, threading, urllib.parse, urllib.request
from intelligence_engine import scan as intelligence_scan, status as intelligence_status, start_engine
from data_hub import binance_tickers as hub_binance_tickers, parallel_quotes as hub_parallel_quotes, status as data_hub_status

BASE=Path(__file__).parent; DB=BASE/"app.db"; STORE=BASE/"data.json"
app=FastAPI(title="التداول الذكي PRO",version="2.0")
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
REVERSE_STRATEGY=os.getenv("REVERSE_STRATEGY","1").strip().lower() not in ("0","false","no","off")
MIN_SIGNAL_AI=int(os.getenv("MIN_SIGNAL_AI","62"))
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
 start_engine()
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
def health(): return {"status":"ok","service":"mudarib-abo-saud","version":"2.0","time":datetime.now(timezone.utc).isoformat()}
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
 host="https://fapi.binance.com" if futures else "https://api.binance.com"; path="/fapi/v1/klines" if futures else "/api/v3/klines"; q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":30})
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
    ema20=_ema(closes,20); ema50=_ema(closes,50)
    rsi=_rsi(closes,14)
    macd=_ema(closes,12)-_ema(closes,26)
    signal_line=_ema([_ema(closes[:i+1],12)-_ema(closes[:i+1],26) for i in range(25,len(closes))],9)
    atr=sum(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(rows)))/max(1,len(rows)-1)
    vr=vols[-1]/(sum(vols[-21:-1])/20) if len(vols)>21 and sum(vols[-21:-1]) else 1
    return {"price":closes[-1],"ema20":ema20,"ema50":ema50,"rsi":rsi,"macd":macd,"macd_signal":signal_line,"atr":atr,"volume_ratio":vr}

def deep_signal(symbol,market,frame,tickers=None,metrics=None):
    x=(tickers or {}).get(symbol,{})
    m=metrics or {}
    try:
        price=float(m.get("price") or x.get("lastPrice") or x.get("regularMarketPrice") or 0)
        change=float(x.get("priceChangePercent") or x.get("regularMarketChangePercent") or 0)
        volume=float(x.get("quoteVolume") or x.get("regularMarketVolume") or 0)
    except Exception:
        price=0; change=0; volume=0
    # Seven signals are blended into one composite decision.
    trend=_clamp(50+change*5)
    technical=_clamp(50+change*3)
    momentum=_clamp(50+change*7)
    liquidity=_clamp(52+(8 if volume>0 else 0)+change*2)
    mtf=_clamp(50+change*3)
    risk=_clamp(74-abs(change)*6)
    if m:
        trend=_clamp(50+(8 if price>m.get("ema20",price) else -8)+(8 if price>m.get("ema50",price) else -8))
        technical=_clamp(50+(m.get("rsi",50)-50)*0.7+(10 if price>m.get("ema20",price) else -10))
        momentum=_clamp(50+(m.get("rsi",50)-50)*0.8+(12 if m.get("macd",0)>m.get("macd_signal",0) else -12))
        liquidity=_clamp(50+(m.get("volume_ratio",1)-1)*20)
        mtf=_clamp(50+change*2+(10 if price>m.get("ema50",price) else -10))
        risk=_clamp(78-abs(change)*5-(8 if m.get("atr",0)>price*.02 else 0))
    composite=_clamp(trend*.18+technical*.17+momentum*.17+liquidity*.12+mtf*.16+risk*.10)
    raw=[trend,technical,momentum,liquidity,mtf,risk,composite]
    buy_votes=sum(v>=58 for v in raw); sell_votes=sum(v<=42 for v in raw)
    original_side="BUY" if market in ("spot","saudi","us") else ("BUY" if buy_votes>=sell_votes else "SELL")
    agreement=max(buy_votes,sell_votes)
    ai=round(_clamp(composite+agreement*3+(5 if agreement>=5 else 0)))
    side=("SELL" if original_side=="BUY" else "BUY") if REVERSE_STRATEGY else original_side
    if price<=0: price=100.0
    risk_amt=max(price*(0.008 if frame in ("15m","1h") else 0.012),price*0.002)
    if m.get("atr",0)>0: risk_amt=max(risk_amt,m["atr"]*0.8)
    if side=="BUY": t=[price+risk_amt*i for i in (1,2,3)]; sl=price-risk_amt
    else: t=[price-risk_amt*i for i in (1,2,3)]; sl=price+risk_amt
    analysts=[
      {"name":"🧞 جني التداول","score":round(trend)},
      {"name":"📊 الفني","score":round(technical)},
      {"name":"⚡ الزخم","score":round(momentum)},
      {"name":"💰 السيولة والحجم","score":round(liquidity)},
      {"name":"🌐 الاتجاه المتعدد","score":round(mtf)},
      {"name":"🎯 المخاطر","score":round(risk)},
      {"name":"🤖 العقل المركب","score":round(composite)}
    ]
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"original_side":original_side,
            "reversed":REVERSE_STRATEGY,"ai":ai,"agreement":agreement,
            "analysts":analysts,"entry":price,"tp1":t[0],"tp2":t[1],"tp3":t[2],"sl":sl,
            "change":round(change,3),"updated":int(time.time())}


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
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"default":"5m","reverse_strategy":REVERSE_STRATEGY,"min_ai":MIN_SIGNAL_AI}
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
 if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid market/timeframe"}
 key=f"{market}:{timeframe}"
 now=time.time()
 with SIGNAL_CACHE_LOCK:
  cached=SIGNAL_CACHE.get(key)
  if cached and now-cached["time"]<SIGNAL_CACHE_TTL:return cached["data"]
 syms=symbols(market)
 if market in ("spot","futures","contracts"):
  tickers=binance_tickers(market in ("futures","contracts"))
 elif market in ("us","forex","saudi"):
  tickers=yahoo_tickers(syms,market=="forex",market=="saudi")
 else:
  tickers={}
 pool=[fast_signal(s,market,timeframe,tickers) for s in syms if s in tickers or market not in ("us","forex")]
 pool.sort(key=lambda z:(z["ai"],z["agreement"],abs(z.get("change",0))),reverse=True)
 deep_limit=100 if market in ("spot","futures","contracts") else 50
 for z in pool[:deep_limit]:
  z.update(deep_signal(z["symbol"],market,timeframe,tickers,_snapshot(z["symbol"],market,timeframe)))
 items=[z for z in pool if z.get("ai",0)>=MIN_SIGNAL_AI][:MAX_SIGNAL_ITEMS]
 data={"items":items,"market":market,"timeframe":timeframe,"count":len(items),"scanned":len(pool),
       "min_ai":MIN_SIGNAL_AI,"reversed":REVERSE_STRATEGY,"note":"AI confidence is a model score, not a guarantee."}
 with SIGNAL_CACHE_LOCK:SIGNAL_CACHE[key]={"time":now,"data":data}
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
    candidates.sort(key=lambda z:(z["ai"],z["agreement"],abs(z.get("change",0))),reverse=True)
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
                "reverse_strategy":REVERSE_STRATEGY,"max_items":MAX_SIGNAL_ITEMS}

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
            tickers=binance_tickers(market in ("futures","contracts"))
            ranked=sorted(tickers.items(), key=lambda kv: float(kv[1].get("quoteVolume",0) or 0), reverse=True)[:80]
            for symbol,_ in ranked:
                sig=fast_signal(symbol,market,"15m",tickers)
                if sig.get("ai",0)<MIN_SIGNAL_AI or sig.get("agreement",0)<5:
                    continue
                price=_live_price(symbol,market,tickers)
                if price<=0: continue
                c=db()
                row=c.execute("SELECT * FROM trades WHERE source='live' AND symbol=? AND market=? AND timeframe='15m' AND status='open' ORDER BY id DESC LIMIT 1",(symbol,market)).fetchone()
                if row:
                    entry=float(row["entry"] or 0)
                    side=row["side"]
                    pnl=((price-entry)/entry*100) if side=="BUY" and entry else ((entry-price)/entry*100 if entry else 0)
                    tp=price>=float(row["tp1"]) if side=="BUY" else price<=float(row["tp1"])
                    sl=price<=float(row["sl"]) if side=="BUY" else price>=float(row["sl"])
                    if tp or sl:
                        c.execute("UPDATE trades SET status='closed',result=?,pnl=?,current_price=?,closed_at=? WHERE id=?",
                                  ("win" if tp else "loss",round(pnl,4),price,now,row["id"]))
                    else:
                        c.execute("UPDATE trades SET pnl=?,current_price=? WHERE id=?",(round(pnl,4),price,row["id"]))
                    c.commit(); c.close()
                    continue
                recent=c.execute("SELECT created_at FROM trades WHERE source='live' AND symbol=? AND market=? AND timeframe='15m' ORDER BY id DESC LIMIT 1",(symbol,market)).fetchone()
                if recent and now-int(recent["created_at"])<900:
                    c.close(); continue
                c.execute(
                    "INSERT INTO trades(user_id,symbol,market,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status,result,pnl,created_at,source,current_price,closed_at) VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,'open','',0,?,?,0)",
                    (symbol,market,"15m",sig["side"],sig["entry"],sig["tp1"],sig["tp2"],sig["tp3"],sig["sl"],sig["ai"],now,"live",price)
                )
                c.commit(); c.close()
        except Exception:
            continue

def _live_tracker_loop():
    while True:
        try:
            _sync_live_trades()
        except Exception:
            pass
        time.sleep(60)

_LIVE_TRACKER_STARTED=False
def start_live_tracker():
    global _LIVE_TRACKER_STARTED
    if _LIVE_TRACKER_STARTED: return
    _LIVE_TRACKER_STARTED=True
    threading.Thread(target=_live_tracker_loop,name="live-trade-tracker",daemon=True).start()

@app.get("/api/tracker")
def tracker_api(request: Request):
    u = me(request)
    c = db()
    if u:
        rows = c.execute("SELECT * FROM trades WHERE source='live' AND user_id=? ORDER BY created_at DESC LIMIT 200",(u["id"],)).fetchall()
    else:
        rows = c.execute("SELECT * FROM trades WHERE source='live' AND user_id IS NULL ORDER BY created_at DESC LIMIT 200").fetchall()
    stats = {
        "open": sum(1 for x in rows if x["status"]=="open"),
        "wins": sum(1 for x in rows if x["status"]=="closed" and x["result"]=="win"),
        "losses": sum(1 for x in rows if x["status"]=="closed" and x["result"]=="loss"),
        "closed": sum(1 for x in rows if x["status"]=="closed"),
        "pnl": round(sum(float(x["pnl"] or 0) for x in rows), 4)
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
