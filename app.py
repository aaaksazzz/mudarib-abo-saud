import os,sqlite3,time
from pathlib import Path
from contextlib import closing
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

ROOT=Path(__file__).parent
STATIC=ROOT/"static"
DATA=Path(os.getenv("DATA_DIR","/data"))
try: DATA.mkdir(parents=True,exist_ok=True)
except Exception: DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"
app=FastAPI(title="Trading PRO",version="3.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
STABLE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT"}
MIN_VOL=1000000

def conn():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with closing(conn()) as c:
 c.execute("CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,timeframe TEXT,confidence REAL,status TEXT DEFAULT 'open',opened_at REAL,closed_at REAL,close_price REAL,pnl REAL DEFAULT 0)")
 c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,name TEXT,created_at REAL)")
 c.commit()

async def bn(path,params=None):
 async with httpx.AsyncClient(timeout=12) as x:
  r=await x.get("https://api.binance.com"+path,params=params); r.raise_for_status(); return r.json()

def ema(a,n):
 if not a:return 0
 k=2/(n+1); e=a[0]
 for v in a[1:]:e=v*k+e*(1-k)
 return e

def rsi(a,n=14):
 if len(a)<n+1:return 50
 g=sum(max(b-a,0) for a,b in zip(a[-n-1:-1],a[-n:]))/n
 l=sum(max(a-b,0) for a,b in zip(a[-n-1:-1],a[-n:]))/n
 return 100 if l==0 else 100-100/(1+g/l)

async def spot():
 a=await bn("/api/v3/ticker/24hr")
 a=[x for x in a if x.get("symbol","").endswith("USDT") and x["symbol"] not in STABLE and float(x.get("quoteVolume",0))>=MIN_VOL]
 a.sort(key=lambda x:abs(float(x["priceChangePercent"])),reverse=True)
 return [{"symbol":x["symbol"],"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume":float(x["quoteVolume"])} for x in a]

async def sig(symbol):
 k15=await bn("/api/v3/klines",{"symbol":symbol,"interval":"15m","limit":220})
 k1=await bn("/api/v3/klines",{"symbol":symbol,"interval":"1h","limit":220})
 c=[float(x[4]) for x in k15]; h=[float(x[4]) for x in k1]; p=c[-1]
 e20=ema(c,20); e15=ema(c,200); e1=ema(h,200); rr=rsi(c)
 checks=[p<e1,p<e20,rr<50,p<e15]; score=round(sum(checks)/4*100,1)
 return {"symbol":symbol,"timeframe":"15m","price":p,"entry":p,"tp1":p*1.01,"tp2":p*1.02,"tp3":p*1.04,"sl":p*.98,"rsi":round(rr,2),"confidence":score,"signal":"BUY" if score>=75 else "WATCH","checks":checks}

@app.get("/health")
async def health(): return {"ok":True,"version":"3.0","service":"trading-pro","time":int(time.time())}

@app.get("/api/markets")
async def markets(limit:int=100):
 try:return {"items":(await spot())[:max(1,min(limit,200))]}
 except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/scanner")
async def scanner(limit:int=20):
 try:
  out=[]
  for x in (await spot())[:40]:
   try:
    s=await sig(x["symbol"]); s.update(change=x["change"],volume=x["volume"]); out.append(s)
   except Exception:pass
  out.sort(key=lambda x:(x["confidence"],abs(x["change"])),reverse=True)
  return {"items":out[:max(1,min(limit,40))]}
 except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/signal")
async def signal(symbol:str):
 try:return await sig(symbol.upper())
 except Exception as e:return {"error":str(e)}

@app.get("/api/futures")
async def futures():
 try:
  a=await bn("/fapi/v1/ticker/24hr")
  out=[{"symbol":x["symbol"],"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume":float(x["quoteVolume"])} for x in a if x["symbol"].endswith("USDT") and x["symbol"] not in STABLE and float(x.get("quoteVolume",0))>=MIN_VOL]
  out.sort(key=lambda x:abs(x["change"]),reverse=True); return {"items":out[:100]}
 except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/trades")
async def trades():
 with closing(conn()) as c:return {"items":[dict(x) for x in c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 200").fetchall()]}

@app.get("/api/tracker")
async def tracker():return await trades()

@app.get("/api/platform/summary")
async def summary():
 with closing(conn()) as c:
  return {"open":c.execute("SELECT count(*) FROM trades WHERE status='open'").fetchone()[0],"closed":c.execute("SELECT count(*) FROM trades WHERE status='closed'").fetchone()[0],"min_volume":MIN_VOL}

@app.get("/api/news")
async def news():return {"items":[]}
@app.get("/api/blog")
async def blog():return {"items":[]}
@app.get("/api/auth/me")
async def me():return {"authenticated":False,"user":None}
@app.get("/api/contracts")
async def contracts():return {"items":[],"message":"لا توجد بيانات وهمية. اربط مصدر العقود عند توفره."}
@app.get("/api/saudi")
async def saudi():return {"items":[],"message":"لا توجد بيانات وهمية. اربط مصدر السوق السعودي عند توفره."}
@app.get("/api/us")
async def us():return {"items":[],"message":"لا توجد بيانات وهمية. اربط مصدر السوق الأمريكي عند توفره."}
@app.get("/api/forex")
async def forex():return {"items":[],"message":"لا توجد بيانات وهمية. اربط مصدر الفوركس والذهب عند توفره."}

@app.get("/")
async def root():return FileResponse(STATIC/"index.html")
@app.get("/{path:path}")
async def files(path:str):
 p=STATIC/path
 return FileResponse(p if p.is_file() else STATIC/"index.html")
