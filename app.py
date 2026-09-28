from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, hashlib, hmac, secrets, os, json, time, urllib.parse, urllib.request
from intelligence_engine import scan as intelligence_scan, status as intelligence_status, start_engine

BASE=Path(__file__).parent; DB=BASE/"app.db"; STORE=BASE/"data.json"
app=FastAPI(title="التداول الذكي PRO",version="2.0")
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES=["15m","1h","4h","1d","1w","1M"]; SESSION_DAYS=30; PLANS={"7d":10,"15d":20,"30d":30}

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
@app.on_event("startup")
def startup():
 init_db()
 start_engine()
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
    side="BUY" if market in ("spot","saudi","us") else ("BUY" if buy_votes>=sell_votes else "SELL")
    agreement=max(buy_votes,sell_votes)
    ai=round(_clamp(composite+agreement*3+(5 if agreement>=5 else 0)))
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
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"ai":ai,"agreement":agreement,
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
  if out:
   SYMBOL_CACHE[key]={"time":now,"symbols":out}
   return out
 except Exception:
  pass
 return cached["symbols"] if cached else ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]

SYMBOL_LIST_CACHE={}
SYMBOL_LIST_TTL=1800
FOREX_SYMBOLS=["EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD","EURGBP","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCHF","GBPCHF","AUDCAD","AUDCHF","CADJPY","NZDJPY","NZDCHF","GBPAUD","GBPCAD","EURCAD","USDMXN","USDZAR","USDTRY","USDNOK","USDSEK","USDSGD","USDHKD","USDCNH","USDPLN","USDHUF","USDCZK"]

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
 if m=="us": return all_us_stocks()
 if m=="forex": return FOREX_SYMBOLS
 return ["BTCUSDT","ETHUSDT","SOLUSDT"]
@app.get("/api/markets")
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"default":"15m"}
TICKER_CACHE={}
TICKER_CACHE_TTL=30

def binance_tickers(futures=False):
 key="futures" if futures else "spot"; now=time.time(); cached=TICKER_CACHE.get(key)
 if cached and now-cached["time"]<TICKER_CACHE_TTL:return cached["data"]
 host="https://fapi.binance.com" if futures else "https://api.binance.com"
 path="/fapi/v1/ticker/24hr" if futures else "/api/v3/ticker/24hr"
 try:
  with urllib.request.urlopen(host+path,timeout=8) as r:data=json.loads(r.read())
  data={x["symbol"]:x for x in data if x.get("symbol")}
  TICKER_CACHE[key]={"time":now,"data":data}; return data
 except Exception:
  return cached["data"] if cached else {}

def yahoo_tickers(symbols_list,forex=False):
 from concurrent.futures import ThreadPoolExecutor,as_completed
 chunks=[symbols_list[i:i+100] for i in range(0,len(symbols_list),100)]
 def fetch(chunk):
  qs=",".join((s+"=X") if forex else s for s in chunk)
  try:
   url="https://query1.finance.yahoo.com/v7/finance/quote?"+urllib.parse.urlencode({"symbols":qs})
   with urllib.request.urlopen(url,timeout=8) as r:data=json.loads(r.read())
   return data.get("quoteResponse",{}).get("result",[])
  except Exception:return []
 out={}
 with ThreadPoolExecutor(max_workers=12) as ex:
  for fut in as_completed([ex.submit(fetch,ch) for ch in chunks]):
   for x in fut.result(): out[x.get("symbol","").replace("=X","")]=x
 return out

def fast_signal(symbol,market,frame,tickers):
    return deep_signal(symbol,market,frame,tickers)

@app.get("/api/trades")
def trades(market="spot",timeframe="15m"):
 if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid market/timeframe"}
 syms=symbols(market)
 if market in ("spot","futures","contracts"):
  tickers=binance_tickers(market in ("futures","contracts"))
 elif market in ("us","forex"):
  tickers=yahoo_tickers(syms,market=="forex")
 else:
  tickers={}
 items=[fast_signal(s,market,timeframe,tickers) for s in syms if s in tickers or market not in ("us","forex")]
 return {"items":items,"market":market,"timeframe":timeframe,"count":len(items)}
@app.get("/api/scanner")
def scanner(timeframe="15m"):
    if timeframe not in FRAMES: timeframe="15m"
    candidates=[]
    for market in MARKETS:
        syms=symbols(market)
        if market in ("spot","futures","contracts"): tk=binance_tickers(market in ("futures","contracts"))
        elif market in ("us","forex"): tk=yahoo_tickers(syms,market=="forex")
        else: tk={}
        pool=[deep_signal(sym,market,timeframe,tk) for sym in syms if (not tk or sym in tk)]
        pool.sort(key=lambda z:(z["ai"],z["agreement"],abs(z.get("change",0))),reverse=True)
        # Deep indicator study is applied to the strongest candidates, keeping the scan broad.
        for z in pool[:40]:
            z.update(deep_signal(z["symbol"],market,timeframe,tk,_snapshot(z["symbol"],market,timeframe)))
        candidates.extend(pool[:40])
    candidates.sort(key=lambda z:(z["ai"],z["agreement"],abs(z.get("change",0))),reverse=True)
    return {"items":candidates[:80],"timeframe":timeframe,"scanned":sum(len(symbols(m)) for m in MARKETS),"analysts":7}



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
