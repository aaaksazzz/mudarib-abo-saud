import asyncio,json,time
import httpx,websockets
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path

app=FastAPI(title="التداول الذكي PRO",version="6.0")
STATIC=Path(__file__).parent/"static"
MIN_VOL=1_000_000
WHALE_USD=25_000
TFS=("15m","30m","1h","4h","1d","1w","1M")
RISK={"15m":.01,"30m":.012,"1h":.015,"4h":.02,"1d":.03,"1w":.045,"1M":.07}
FLOW={}
LOCK=asyncio.Lock()
WS=None
CACHE={"at":0,"items":[]}

async def get(url,params=None):
    async with httpx.AsyncClient(timeout=12,headers={"User-Agent":"MudaribPRO/6"}) as c:
        r=await c.get(url,params=params);r.raise_for_status();return r.json()

async def spot_tickers():
    rows=await get("https://api.binance.com/api/v3/ticker/24hr")
    stable={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT"}
    out=[]
    for x in rows:
        s=x.get("symbol","");v=float(x.get("quoteVolume",0) or 0)
        if s.endswith("USDT") and s not in stable and v>=MIN_VOL:
            out.append({"symbol":s,"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":v})
    return sorted(out,key=lambda x:x["volume24h"],reverse=True)

async def candles(symbol,tf):
    rows=await get("https://api.binance.com/api/v3/klines",{"symbol":symbol,"interval":tf,"limit":42})
    if len(rows)<22:return None
    close=[float(x[4]) for x in rows];quote=[float(x[7]) for x in rows];buy=[float(x[10]) for x in rows]
    total=sum(quote);b=sum(buy);sell=max(0,total-b);pressure=(b-sell)/total*100 if total else 0
    avg=sum(quote[:-2])/max(1,len(quote)-2);vr=quote[-1]/avg if avg else 0
    old=sum(quote[:21]);new=sum(quote[21:]);acc=(new/max(old,1)-1)*100
    return {"price":close[-1],"pressure":pressure,"volume_ratio":vr,"acceleration":acc,"move":(close[-1]/close[0]-1)*100}

async def ws_worker(symbols):
    url="wss://stream.binance.com:9443/stream?streams="+"/".join(s.lower()+"@aggTrade" for s in symbols)
    while True:
        try:
            async with websockets.connect(url,ping_interval=120,ping_timeout=30) as ws:
                async for raw in ws:
                    try:
                        e=json.loads(raw).get("data",{});s=e.get("s");usd=float(e.get("p",0))*float(e.get("q",0))
                        if not s or usd<=0:continue
                        buy=not bool(e.get("m",False))
                        async with LOCK:
                            z=FLOW.setdefault(s,{"b":0.0,"s":0.0,"wb":0.0,"ws":0.0,"n":0,"wn":0})
                            z["b" if buy else "s"]+=usd;z["n"]+=1
                            if usd>=WHALE_USD:z["wb" if buy else "ws"]+=usd;z["wn"]+=1
                            if z["n"]>6000:
                                for k in ("b","s","wb","ws"):z[k]*=.5
                                z["n"]=3000
                    except Exception:pass
        except Exception:await asyncio.sleep(2)

async def start_ws():
    global WS
    if WS and not WS.done():return
    try:
        syms=[x["symbol"] for x in (await spot_tickers())[:100]]
        WS=asyncio.create_task(ws_worker(syms))
    except Exception:pass

@app.on_event("startup")
async def startup():await start_ws()

def whale(symbol):
    z=FLOW.get(symbol)
    if not z:return {"available":False,"pressure":0,"trades":0}
    total=z["wb"]+z["ws"]
    return {"available":total>0,"pressure":((z["wb"]-z["ws"])/total*100 if total else 0),"trades":z["wn"],"flow":total}

def signal(symbol,tf,q,w):
    p=q["pressure"];vr=q["volume_ratio"];acc=q["acceleration"]
    req={"15m":(5,1.10,3),"30m":(4,1.08,2.5),"1h":(3.5,1.06,2),"4h":(3,1.05,1.5),"1d":(2.5,1.04,1),"1w":(2,1.03,.5),"1M":(1.5,1.02,0)}[tf]
    pmin,vrmin,amin=req
    if p<pmin or vr<vrmin or acc<amin:return None
    if w["available"] and w["pressure"]<5:return None
    e=q["price"];r=RISK[tf]
    return {"symbol":symbol,"timeframe":tf,"signal":"BUY","direction":"شراء","entry":e,"tp1":e*(1+r),"tp2":e*(1+2*r),"tp3":e*(1+3*r),"sl":e*(1-r),"confidence":min(99,round(50+(p-pmin)*3+(vr-vrmin)*25+min(20,max(0,w["pressure"])),1)),"volume_ratio":round(vr,2),"liquidity":round(p,2),"acceleration":round(acc,2),"whale_pressure":round(w["pressure"],2),"whale_trades":w["trades"],"whale_available":w["available"],"generated_at":int(time.time())}

async def build():
    global CACHE
    if time.time()-CACHE["at"]<20:return CACHE["items"]
    markets=(await spot_tickers())[:80]
    sem=asyncio.Semaphore(8)
    async def one(m):
        async with sem:
            out=[];w=whale(m["symbol"])
            for tf in TFS:
                try:
                    q=await candles(m["symbol"],tf)
                    if q:
                        s=signal(m["symbol"],tf,q,w)
                        if s:out.append(s)
                except Exception:pass
            return out
    groups=await asyncio.gather(*[one(m) for m in markets])
    allx=[s for g in groups for s in g];allx.sort(key=lambda x:(x["confidence"],x["whale_pressure"],x["volume_ratio"]),reverse=True)
    count={tf:0 for tf in TFS};out=[]
    for s in allx:
        if count[s["timeframe"]]<8:out.append(s);count[s["timeframe"]]+=1
    CACHE={"at":time.time(),"items":out};return out

@app.get("/health")
async def health():return {"ok":True,"version":"6.0","engine":"volume-liquidity-whales"}

@app.get("/api/signals/spot")
async def signals_spot():
    await start_ws();return {"items":await build(),"timeframes":TFS,"min_volume":MIN_VOL,"engine":"حجم + سيولة + حيتان"}

@app.get("/api/live-flow")
async def live_flow():
    await start_ws();out=[]
    async with LOCK:
        for s,z in FLOW.items():
            total=z["b"]+z["s"];wt=z["wb"]+z["ws"]
            if total:out.append({"symbol":s,"flow":total,"pressure":(z["b"]-z["s"])/total*100,"whale_flow":wt,"whale_pressure":(z["wb"]-z["ws"])/wt*100 if wt else 0,"whales":z["wn"]})
    return {"items":sorted(out,key=lambda x:(x["whale_flow"],abs(x["whale_pressure"])),reverse=True)[:30]}

@app.get("/api/markets")
async def markets():return {"items":(await spot_tickers())[:100],"min_volume":MIN_VOL}

@app.get("/")
async def root():return FileResponse(STATIC/"index.html")

@app.get("/{path:path}")
async def files(path:str):
    p=STATIC/path
    return FileResponse(p if p.is_file() else STATIC/"index.html")
