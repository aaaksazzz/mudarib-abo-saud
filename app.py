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
PIPELINE_TFS=["5m","15m","1h","4h","1d","1w","1M"]
EXCLUDE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","BUSDUSDT"}
MARKETS={
 "crypto_spot":{"name":"سبوت","provider":"binance","symbols":[]},
 "crypto_futures":{"name":"فيوتشر","provider":"binance_futures","symbols":[]},
 "us":{"name":"الأمريكي","provider":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","AMD","NFLX","JPM","WMT","COST","QQQ","SPY"]},
 "contracts":{"name":"العقود","provider":"yahoo","symbols":["ES=F","NQ=F","YM=F","RTY=F","CL=F","GC=F","SI=F"]},
 "saudi":{"name":"السعودي","provider":"yahoo","symbols":["2222.SR","1120.SR","2010.SR","1180.SR","1150.SR","1211.SR","2082.SR","7010.SR","7020.SR","2380.SR"]},
 "forex":{"name":"الفوركس","provider":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F"]}
}

app=FastAPI(title="التداول الذكي PRO",version="9.0")

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT,symbol TEXT,tf TEXT,side TEXT,
      entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,
      status TEXT DEFAULT 'OPEN',pnl REAL DEFAULT 0,created INTEGER,closed INTEGER,source TEXT)""")
    c.commit(); return c

async def req(url,params=None):
    async with httpx.AsyncClient(timeout=15,headers={"User-Agent":"Mozilla/5.0"}) as x:
        r=await x.get(url,params=params); r.raise_for_status(); return r.json()

async def universe(futures=False):
    base="https://fapi.binance.com" if futures else "https://api.binance.com"
    path="/fapi/v1/ticker/24hr" if futures else "/api/v3/ticker/24hr"
    rows=await req(base+path)
    rows=[r for r in rows if r["symbol"].endswith("USDT") and r["symbol"] not in EXCLUDE and float(r.get("quoteVolume",0))>=1000000]
    return sorted(rows,key=lambda r:float(r.get("quoteVolume",0)),reverse=True)[:35]

def closes_volumes(raw,market):
    if market.startswith("crypto"):
        return [float(x[4]) for x in raw],[float(x[7]) for x in raw]
    q=raw.get("indicators",{}).get("quote",[{}])[0]
    return [float(x) for x in q.get("close",[]) if x is not None],[float(x or 0) for x in q.get("volume",[])]

async def market_candles(market,symbol,tf):
    if market=="crypto_spot":
        return await req("https://api.binance.com/api/v3/klines",{"symbol":symbol,"interval":tf,"limit":240})
    if market=="crypto_futures":
        return await req("https://fapi.binance.com/fapi/v1/klines",{"symbol":symbol,"interval":tf,"limit":240})
    sec={"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}[tf]
    now=int(time.time())
    period1=now-sec*240
    interval="1mo" if tf=="1M" else tf
    j=await req("https://query1.finance.yahoo.com/v8/finance/chart/"+symbol,{"period1":period1,"period2":now,"interval":interval})
    result=(j.get("chart",{}).get("result") or [None])[0]
    if not result: return {}
    return result

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

async def pipeline(market,symbol):
    d=await candles_for(market,symbol,PIPELINE_TFS)
    if any(d.get(tf) is None for tf in ("1M","1w","1d","4h","1h","15m","5m")): return None

    # 1) Monthly + Weekly = directional compass. They must agree.
    macro_m=structure_bias(*d["1M"][:3]); macro_w=structure_bias(*d["1w"][:3])
    if macro_m!=macro_w or macro_m=="NEUTRAL": return None
    bias=macro_m

    # 2) Daily + 4H = POI. No entry yet.
    daily=d["1d"]; h4=d["4h"]
    poi=poi_from_structure(*daily[:3],bias) or poi_from_structure(*h4[:3],bias)
    if not poi: return None
    current=d["1h"][0][-1]
    if not inside_zone(current,poi):
        # Allow the 4H leg to be the active POI when price is closer to it.
        p4=poi_from_structure(*h4[:3],bias)
        if not inside_zone(current,p4): return {
            "market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,
            "side":bias,"state":"POI","stage":"منطقة الفرصة","bias":bias,
            "bias_monthly":macro_m,"bias_weekly":macro_w,
            "poi":{"low":round(poi[0],8),"high":round(poi[1],8),"type":poi[2],"tf":"1D/4H"},
            "entry":None,"sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,
            "confidence":65,"time":int(time.time())}
        poi=p4

    # 3) 1H + 15M = confirmation. Must happen inside the POI.
    c1,h1,l1,_=d["1h"]; c15,h15,l15,_=d["15m"]
    confirm=inside_zone(c1[-1],poi) and choch(c15,h15,l15,bias)
    sw=sweep(c15,h15,l15,bias)
    if not confirm:
        return {
            "market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,"side":bias,
            "state":"WAIT_CONFIRMATION","stage":"انتظار التأكيد","bias":bias,
            "bias_monthly":macro_m,"bias_weekly":macro_w,
            "poi":{"low":round(poi[0],8),"high":round(poi[1],8),"type":poi[2],"tf":"1D/4H"},
            "entry":None,"sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,
            "confirmation":{"choch":False,"sweep":sw,"ready":False},
            "confidence":72 if sw else 68,"time":int(time.time())}

    # 4) 5M = execution-only trigger. It can never bypass the higher timeframes.
    c5,h5,l5,v5=d["5m"]
    e5=ema(c5,20)
    trigger=choch(c5,h5,l5,bias) and ((bias=="BUY" and c5[-1]>e5) or (bias=="SELL" and c5[-1]<e5))
    if not trigger:
        return {
            "market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,"side":bias,
            "state":"READY","stage":"جاهز للتنفيذ","bias":bias,
            "bias_monthly":macro_m,"bias_weekly":macro_w,
            "poi":{"low":round(poi[0],8),"high":round(poi[1],8),"type":poi[2],"tf":"1D/4H"},
            "entry":None,"sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,
            "confirmation":{"choch":True,"sweep":sw,"ready":True},
            "execution":{"tf":"5m","trigger":False},
            "confidence":82 if sw else 78,"time":int(time.time())}

    entry=c5[-1]; a=atr(h5,l5,c5) or abs(entry*0.003)
    if bias=="BUY":
        sl=min(min(l5[-8:]),entry-a)
        target_base=max(max(h4[1][-40:]),max(daily[1][-40:]))
        risk=entry-sl
        tps=[target_base]
        tps += [entry+risk*5,entry+risk*8]
        tps=sorted(set(round(x,8) for x in tps if x>entry))
    else:
        sl=max(max(h5[-8:]),entry+a)
        target_base=min(min(h4[2][-40:]),min(daily[2][-40:]))
        risk=sl-entry
        tps=[target_base]
        tps += [entry-risk*5,entry-risk*8]
        tps=sorted(set(round(x,8) for x in tps if x<entry),reverse=True)
    if risk<=0 or not tps:return None
    tp1=tps[0]; tp2=tps[min(1,len(tps)-1)]; tp3=tps[min(2,len(tps)-1)]
    rr=abs(tp1-entry)/risk
    if rr<2: return None
    score=90+(5 if sw else 0)+(4 if macro_m==macro_w else 0)
    return {
      "market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,"tf":"5m",
      "side":bias,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
      "confidence":min(99,score),"rr":round(rr,2),"state":"ENTERED","stage":"إشارة تنفيذ",
      "bias":bias,"bias_monthly":macro_m,"bias_weekly":macro_w,
      "poi":{"low":round(poi[0],8),"high":round(poi[1],8),"type":poi[2],"tf":"1D/4H"},
      "confirmation":{"choch":True,"sweep":sw,"ready":True},
      "execution":{"tf":"5m","trigger":True},"rsi":None,"volume_ratio":None,
      "liquidity":round(v5[-1],0) if v5 else 0,"change":round((entry/c5[-2]-1)*100,2),
      "time":int(time.time())
    }

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
            try:return await pipeline(m,s)
            except Exception:return None
    z=await asyncio.gather(*[one(m,s) for m,s in jobs])
    return sorted([x for x in z if x],key=lambda x:(x["state"]=="ENTERED",x["confidence"],x.get("rr") or 0),reverse=True)

def save(items):
    c=db()
    for x in items:
        if x.get("state")=="ENTERED" and x["confidence"]>=90:
            exists=c.execute("SELECT id FROM trades WHERE market=? AND symbol=? AND tf=? AND status='OPEN'",(x["market"],x["symbol"],x["tf"])).fetchone()
            if not exists:
                c.execute("""INSERT INTO trades(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,confidence,created,source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(x["market"],x["symbol"],x["tf"],x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x["sl"],x["confidence"],int(time.time()),"MULTI_TF_PIPELINE"))
    c.commit();c.close()

async def loop():
    while True:
        try:
            z=await scan_all(); save(z); app.state.data={"at":int(time.time()),"items":z}; app.state.error=""
        except Exception as e: app.state.error=str(e)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start():
    app.state.data={"at":0,"items":[]};app.state.error="";asyncio.create_task(loop())

@app.get("/health")
async def health():
    return {"ok":True,"version":"9.0","engine":"MULTI_TIMEFRAME_PIPELINE","pipeline":"HTF_BIAS->POI->CONFIRMATION->5M_TRIGGER","execution":"PAPER_SAFE"}

@app.get("/api/markets")
async def markets(): return MARKETS

@app.get("/api/signals")
async def signals(market: Optional[str]=None,state: Optional[str]=None):
    if not app.state.data["items"] or time.time()-app.state.data["at"]>180:
        z=await scan_all();save(z);app.state.data={"at":int(time.time()),"items":z}
    items=[x for x in app.state.data["items"] if (not market or x["market"]==market) and (not state or x["state"]==state)]
    return {"updated":app.state.data["at"],"items":items,"timeframes":TFS,"execution_timeframe":"5m","markets":MARKETS,"min_volume":1000000,"pipeline":["HTF_BIAS","POI","CONFIRMATION","5M_TRIGGER"]}

@app.get("/api/pipeline")
async def pipeline_api(market: Optional[str]=None):
    items=app.state.data.get("items",[])
    return {"updated":app.state.data.get("at",0),"items":[x for x in items if not market or x["market"]==market],"pipeline":["شهري+أسبوعي: بوصلة الاتجاه","يومي+4H: منطقة الفرصة","1H+15M: التأكيد","5M: التنفيذ"],"reverse_strategy":False}

@app.get("/api/trades")
async def trades():
    c=db();z=[dict(x) for x in c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 100")];c.close();return z

@app.get("/api/stats")
async def stats():
    c=db();a=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];o=c.execute("SELECT COUNT(*) n FROM trades WHERE status='OPEN'").fetchone()["n"];p=c.execute("SELECT COALESCE(SUM(pnl),0) p FROM trades WHERE status='CLOSED'").fetchone()["p"];c.close();return {"total":a,"open":o,"closed":a-o,"pnl":round(p,4)}

@app.get("/api/settings")
async def settings():
    return {"mode":os.getenv("TRADING_MODE","PAPER").upper(),"execution_ready":False,"engine":"MULTI_TIMEFRAME_PIPELINE","live_orders":False}

@app.get("/")
async def home(): return FileResponse(ROOT/"static/index.html")

@app.get("/static/{name}")
async def static(name): return FileResponse(ROOT/"static"/name)

@app.exception_handler(Exception)
async def err(request,e): return JSONResponse({"error":"server_error","detail":str(e)},500)
