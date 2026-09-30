import os,time,sqlite3,asyncio
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse

ROOT=Path(__file__).parent
DATA=Path(os.getenv("DATA_DIR","/data"))
try: DATA.mkdir(parents=True,exist_ok=True)
except Exception: DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"
BASE="https://api.binance.com"
TFS=["15m","30m","1h","4h","1d","1w","1M"]
RISK={"15m":.01,"30m":.012,"1h":.015,"4h":.02,"1d":.03,"1w":.045,"1M":.07}
EXCLUDE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","BUSDUSDT"}
app=FastAPI(title="التداول الذكي PRO",version="7.0")

def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.execute("CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,tf TEXT,side TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,status TEXT DEFAULT 'OPEN',pnl REAL DEFAULT 0,created INTEGER,closed INTEGER,source TEXT)")
 c.commit();return c

async def get(path,params=None):
 async with httpx.AsyncClient(timeout=12) as x:
  r=await x.get(BASE+path,params=params);r.raise_for_status();return r.json()

def ema(a,n):
 if len(a)<n:return None
 e=sum(a[:n])/n;k=2/(n+1)
 for v in a[n:]:e=v*k+e*(1-k)
 return e

def rsi(a,n=14):
 if len(a)<=n:return 50
 g=[];l=[]
 for i in range(1,len(a)):
  d=a[i]-a[i-1];g.append(max(d,0));l.append(max(-d,0))
 ag=sum(g[:n])/n;al=sum(l[:n])/n
 for i in range(n,len(g)):ag=(ag*(n-1)+g[i])/n;al=(al*(n-1)+l[i])/n
 return 100 if al==0 else 100-100/(1+ag/al)

async def universe():
 rows=await get("/api/v3/ticker/24hr")
 rows=[r for r in rows if r["symbol"].endswith("USDT") and r["symbol"] not in EXCLUDE and float(r.get("quoteVolume",0))>=1000000]
 return sorted(rows,key=lambda r:float(r.get("quoteVolume",0)),reverse=True)[:35]

async def analyze(symbol,tf):
 ks=await get("/api/v3/klines",{"symbol":symbol,"interval":tf,"limit":220})
 c=[float(x[4]) for x in ks];q=[float(x[7]) for x in ks]
 if len(c)<30:return None
 p=c[-1];e20=ema(c,20);e200=ema(c,200) or ema(c,min(100,len(c)-1));rr=rsi(c)
 avg=sum(q[-21:-1])/20;vr=q[-1]/avg if avg else 0;chg=(p/c[-2]-1)*100
 valid=p>e200 and p>e20 and rr>=50 and vr>=1.05 and chg>0
 if not valid:return None
 score=50+(18 if p>e200 else 0)+(12 if p>e20 else 0)+(10 if rr>50 else 0)+(7 if vr>=1.2 else 0)+(3 if chg>0 else 0)
 risk=RISK[tf];return {"symbol":symbol,"tf":tf,"side":"BUY","entry":p,"tp1":p*(1+risk*1.2),"tp2":p*(1+risk*2),"tp3":p*(1+risk*3),"sl":p*(1-risk),"confidence":min(99,round(score,1)),"rsi":round(rr,2),"volume_ratio":round(vr,2),"liquidity":round(q[-1],0),"change":round(chg,2),"time":int(time.time())}

async def scan():
 us=await universe();sem=asyncio.Semaphore(8)
 async def one(s,t):
  async with sem:
   try:return await analyze(s,t)
   except:return None
 z=await asyncio.gather(*[one(x["symbol"],t) for x in us for t in TFS])
 return sorted([x for x in z if x],key=lambda x:(x["confidence"],x["volume_ratio"],x["liquidity"]),reverse=True)

def save(items):
 c=db()
 for x in items:
  if x["confidence"]>=70 and not c.execute("SELECT id FROM trades WHERE symbol=? AND tf=? AND status='OPEN'",(x["symbol"],x["tf"])).fetchone():
   c.execute("INSERT INTO trades(symbol,tf,side,entry,tp1,tp2,tp3,sl,confidence,created,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(x["symbol"],x["tf"],x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x["sl"],x["confidence"],int(time.time()),"engine"))
 c.commit();c.close()

async def loop():
 while True:
  try:
   z=await scan();save(z);app.state.data={"at":int(time.time()),"items":z}
  except Exception as e:app.state.error=str(e)
  await asyncio.sleep(60)

@app.on_event("startup")
async def start():
 app.state.data={"at":0,"items":[]};app.state.error="";asyncio.create_task(loop())

@app.get("/health")
async def health():return {"ok":True,"version":"7.0","engine":"EMA20+EMA200+RSI+VOLUME+LIQUIDITY","execution":"PAPER_SAFE"}

@app.get("/api/signals")
async def signals():
 if not app.state.data["items"] or time.time()-app.state.data["at"]>90:
  z=await scan();save(z);app.state.data={"at":int(time.time()),"items":z}
 return {"updated":app.state.data["at"],"items":app.state.data["items"],"timeframes":TFS,"min_volume":1000000}

@app.get("/api/trades")
async def trades():
 c=db();z=[dict(x) for x in c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 100")];c.close();return z

@app.get("/api/stats")
async def stats():
 c=db();a=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];o=c.execute("SELECT COUNT(*) n FROM trades WHERE status='OPEN'").fetchone()["n"];p=c.execute("SELECT COALESCE(SUM(pnl),0) p FROM trades WHERE status='CLOSED'").fetchone()["p"];c.close();return {"total":a,"open":o,"closed":a-o,"pnl":round(p,4)}

@app.get("/api/settings")
async def settings():return {"mode":os.getenv("TRADING_MODE","PAPER").upper(),"execution_ready":bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"))}

@app.get("/")
async def home():return FileResponse(ROOT/"static/index.html")
@app.get("/static/{name}")
async def static(name):return FileResponse(ROOT/"static"/name)
@app.exception_handler(Exception)
async def err(request,e):return JSONResponse({"error":"server_error","detail":str(e)},500)
