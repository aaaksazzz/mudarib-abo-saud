import os,time,sqlite3
from pathlib import Path
from contextlib import closing
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

ROOT=Path(__file__).parent
STATIC=ROOT/"static"
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"

app=FastAPI(title="Whale Liquidity PRO",version="4.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

STABLE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","EURUSDT","USDTUSDT"}
MIN_VOL=1_000_000
WHALE_USD=25_000

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

with closing(conn()) as c:
    c.execute("CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE,created_at REAL)")
    c.commit()

async def bn(path,params=None,base="https://api.binance.com"):
    async with httpx.AsyncClient(timeout=10) as x:
        r=await x.get(base+path,params=params)
        r.raise_for_status()
        return r.json()

async def tickers():
    a=await bn("/api/v3/ticker/24hr")
    out=[]
    for x in a:
        s=x.get("symbol","")
        if not s.endswith("USDT") or s in STABLE: continue
        v=float(x.get("quoteVolume",0) or 0)
        if v<MIN_VOL: continue
        out.append({"symbol":s,"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":v})
    out.sort(key=lambda x:x["volume24h"],reverse=True)
    return out

def whale_stats(trades):
    total=buy=sell=large=large_buy=large_sell=0.0
    count=large_count=0
    prices=[]
    for t in trades:
        q=float(t.get("p",0)); qty=float(t.get("q",0)); usd=q*qty
        total+=usd; prices.append(q)
        is_buy=not bool(t.get("m",False))
        if is_buy: buy+=usd
        else: sell+=usd
        count+=1
        if usd>=WHALE_USD:
            large+=usd; large_count+=1
            if is_buy: large_buy+=usd
            else: large_sell+=usd
    pressure=(buy-sell)/total*100 if total else 0
    whale_pressure=(large_buy-large_sell)/large*100 if large else 0
    return total,buy,sell,pressure,large,large_buy,large_sell,whale_pressure,count,large_count,prices

async def liquidity(symbol):
    trades=await bn("/api/v3/aggTrades",{"symbol":symbol,"limit":1000})
    total,buy,sell,pressure,large,large_buy,large_sell,whale_pressure,count,large_count,prices=whale_stats(trades)
    price=prices[-1] if prices else 0
    first=prices[0] if prices else price
    move=(price/first-1)*100 if first else 0
    # Split recent trades into two halves to detect acceleration without technical indicators.
    mid=max(1,len(trades)//2)
    a=whale_stats(trades[:mid]); b=whale_stats(trades[mid:])
    recent_flow=b[0]; old_flow=a[0]
    acceleration=(recent_flow/old_flow-1)*100 if old_flow else 0
    whale_accel=(b[4]/a[4]-1)*100 if a[4] else (100 if b[4]>0 else 0)
    # Early-alert logic: big-money activity and buy pressure are rising while price has not already exploded.
    flags={
        "whale_activity": large_count>=3,
        "buy_pressure": whale_pressure>=8,
        "liquidity_acceleration": acceleration>=15,
        "whale_acceleration": whale_accel>=15,
        "not_chasing": abs(move)<=2.5,
    }
    score=round(sum(flags.values())/len(flags)*100,1)
    if score>=80 and whale_pressure>=8 and abs(move)<=2.5:
        status="EARLY"
        label="إنذار مبكر"
    elif score>=60:
        status="WATCH"
        label="مراقبة حيتان"
    else:
        status="QUIET"
        label="سيولة هادئة"
    return {
        "symbol":symbol,"price":price,"move":round(move,2),
        "flow":round(total,2),"buy_flow":round(buy,2),"sell_flow":round(sell,2),
        "pressure":round(pressure,2),"whale_flow":round(large,2),
        "whale_buy":round(large_buy,2),"whale_sell":round(large_sell,2),
        "whale_pressure":round(whale_pressure,2),"trades":count,"whale_trades":large_count,
        "acceleration":round(acceleration,2),"whale_acceleration":round(whale_accel,2),
        "score":score,"status":status,"label":label,"flags":flags,
        "updated_at":int(time.time())
    }

@app.get("/health")
async def health():
    return {"ok":True,"version":"4.0","service":"whale-liquidity-pro","time":int(time.time())}

@app.get("/api/liquidity")
async def liquidity_scan(limit:int=15):
    try:
        markets=(await tickers())[:30]
        out=[]
        for m in markets:
            try:
                x=await liquidity(m["symbol"])
                x.update(volume24h=m["volume24h"],change24h=m["change"])
                out.append(x)
            except Exception:
                continue
        out.sort(key=lambda x:(x["score"],x["whale_pressure"],x["whale_flow"],x["acceleration"]),reverse=True)
        return {"items":out[:max(1,min(limit,30))],"source":"Binance spot aggTrades","whale_threshold":WHALE_USD}
    except Exception as e:
        return {"items":[],"error":str(e)}

@app.get("/api/markets")
async def markets(limit:int=30):
    try:
        return {"items":(await tickers())[:max(1,min(limit,100))]}
    except Exception as e: return {"items":[],"error":str(e)}

@app.get("/api/liquidity/{symbol}")
async def liquidity_one(symbol:str):
    try: return await liquidity(symbol.upper())
    except Exception as e: return {"error":str(e)}

@app.get("/api/tracker")
async def tracker():
    with closing(conn()) as c:
        return {"items":[dict(x) for x in c.execute("SELECT * FROM watchlist ORDER BY id DESC").fetchall()]}

@app.get("/api/platform/summary")
async def summary():
    try:
        items=(await liquidity_scan(10))["items"]
        return {"early":sum(x["status"]=="EARLY" for x in items),"watch":sum(x["status"]=="WATCH" for x in items),"tracked":len(items),"min_volume":MIN_VOL,"whale_threshold":WHALE_USD}
    except Exception as e: return {"early":0,"watch":0,"tracked":0,"error":str(e)}

@app.get("/api/futures")
async def futures():
    try:
        a=await bn("/fapi/v1/ticker/24hr")
        out=[{"symbol":x["symbol"],"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":float(x.get("quoteVolume",0))} for x in a if x["symbol"].endswith("USDT") and x["symbol"] not in STABLE and float(x.get("quoteVolume",0))>=MIN_VOL]
        out.sort(key=lambda x:x["volume24h"],reverse=True)
        return {"items":out[:100]}
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/news")
async def news(): return {"items":[]}
@app.get("/api/blog")
async def blog(): return {"items":[]}
@app.get("/api/auth/me")
async def me(): return {"authenticated":False,"user":None}

@app.get("/")
async def root(): return FileResponse(STATIC/"index.html")
@app.get("/{path:path}")
async def files(path:str):
    p=STATIC/path
    return FileResponse(p if p.is_file() else STATIC/"index.html")
