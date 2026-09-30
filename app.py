import os,time,sqlite3,asyncio
from pathlib import Path
from contextlib import closing
import httpx
from fastapi import FastAPI, HTTPException
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

app=FastAPI(title="Whale Flow PRO",version="5.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

MIN_VOL=1_000_000
WHALE_USD=25_000
STABLE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","EURUSDT","USDTUSDT"}

MARKETS={
 "contracts":[("ES=F","ES","S&P 500"),("NQ=F","NQ","Nasdaq 100"),("YM=F","YM","Dow Jones"),("RTY=F","RTY","Russell 2000"),("GC=F","GC","Gold"),("SI=F","SI","Silver"),("CL=F","CL","Crude Oil"),("NG=F","NG","Natural Gas")],
 "us":[("AAPL","AAPL","Apple"),("MSFT","MSFT","Microsoft"),("NVDA","NVDA","NVIDIA"),("AMZN","AMZN","Amazon"),("META","META","Meta"),("TSLA","TSLA","Tesla"),("GOOGL","GOOGL","Alphabet"),("AMD","AMD","AMD")],
 "saudi":[("2222.SR","2222","أرامكو"),("1120.SR","1120","الراجحي"),("2010.SR","2010","سابك"),("1180.SR","1180","الأهلي"),("7010.SR","7010","STC"),("1211.SR","1211","معادن"),("1150.SR","1150","الإنماء"),("2082.SR","2082","ACWA Power")],
 "forex":[("EURUSD=X","EUR/USD","اليورو دولار"),("GBPUSD=X","GBP/USD","الجنيه دولار"),("USDJPY=X","USD/JPY","الدولار ين"),("AUDUSD=X","AUD/USD","الأسترالي دولار"),("USDCAD=X","USD/CAD","الدولار كندي"),("USDCHF=X","USD/CHF","الدولار فرنك"),("GC=F","GOLD","الذهب"),("CL=F","OIL","النفط")]
}

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with closing(conn()) as c:
    c.execute("CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE,market TEXT NOT NULL,created_at REAL)")
    c.commit()

async def get_json(url,params=None,headers=None):
    async with httpx.AsyncClient(timeout=12,headers=headers or {"User-Agent":"Mozilla/5.0"}) as x:
        r=await x.get(url,params=params); r.raise_for_status(); return r.json()

async def bn(path,params=None,base="https://api.binance.com"):
    return await get_json(base+path,params)

async def tickers():
    a=await bn("/api/v3/ticker/24hr"); out=[]
    for x in a:
        s=x.get("symbol","")
        if not s.endswith("USDT") or s in STABLE: continue
        v=float(x.get("quoteVolume",0) or 0)
        if v<MIN_VOL: continue
        out.append({"symbol":s,"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":v})
    return sorted(out,key=lambda x:x["volume24h"],reverse=True)

def stats(trades):
    total=buy=sell=large=lb=ls=0.0; n=ln=0; prices=[]
    for t in trades:
        p=float(t.get("p",0)); q=float(t.get("q",0)); usd=p*q
        total+=usd; prices.append(p); n+=1
        is_buy=not bool(t.get("m",False))
        if is_buy: buy+=usd
        else: sell+=usd
        if usd>=WHALE_USD:
            large+=usd; ln+=1
            if is_buy: lb+=usd
            else: ls+=usd
    pressure=(buy-sell)/total*100 if total else 0
    wp=(lb-ls)/large*100 if large else 0
    return total,buy,sell,pressure,large,lb,ls,wp,n,ln,prices

async def liquidity(symbol):
    trades=await bn("/api/v3/aggTrades",{"symbol":symbol,"limit":1000})
    z=stats(trades); mid=max(1,len(trades)//2); a=stats(trades[:mid]); b=stats(trades[mid:])
    move=(z[10][-1]/z[10][0]-1)*100 if len(z[10])>1 and z[10][0] else 0
    accel=(b[0]/a[0]-1)*100 if a[0] else 0
    wacc=(b[4]/a[4]-1)*100 if a[4] else (100 if b[4]>0 else 0)
    flags={"whale_activity":z[9]>=3,"buy_pressure":z[7]>=8,"liquidity_acceleration":accel>=15,"whale_acceleration":wacc>=15,"not_chasing":abs(move)<=2.5}
    score=round(sum(flags.values())*20,1)
    status="EARLY" if score>=80 and z[7]>=8 and abs(move)<=2.5 else "WATCH" if score>=60 else "QUIET"
    label={"EARLY":"إنذار مبكر","WATCH":"مراقبة حيتان","QUIET":"سيولة هادئة"}[status]
    return {"symbol":symbol,"price":z[10][-1] if z[10] else 0,"move":round(move,2),"flow":round(z[0],2),"buy_flow":round(z[1],2),"sell_flow":round(z[2],2),"pressure":round(z[3],2),"whale_flow":round(z[4],2),"whale_buy":round(z[5],2),"whale_sell":round(z[6],2),"whale_pressure":round(z[7],2),"trades":z[8],"whale_trades":z[9],"acceleration":round(accel,2),"whale_acceleration":round(wacc,2),"score":score,"status":status,"label":label,"updated_at":int(time.time())}

async def yahoo(symbols):
    async with httpx.AsyncClient(timeout=12,headers={"User-Agent":"Mozilla/5.0"}) as x:
        async def one(s,code,name):
            try:
                r=await x.get("https://query1.finance.yahoo.com/v8/finance/chart/"+s,params={"range":"1d","interval":"5m"})
                r.raise_for_status(); j=r.json()["chart"]["result"][0]; q=j["indicators"]["quote"][0]
                closes=[v for v in q.get("close",[]) if v is not None]; vols=[v for v in q.get("volume",[]) if v is not None]
                price=closes[-1] if closes else 0; first=closes[0] if closes else price
                move=(price/first-1)*100 if first else 0
                vol=sum(vols) if vols else 0
                return {"symbol":code,"name":name,"price":price,"change":move,"volume":vol,"source":"Yahoo Finance public chart"}
            except Exception as e:
                return {"symbol":code,"name":name,"error":str(e),"source":"Yahoo Finance public chart"}
        return await asyncio.gather(*[one(*v) for v in symbols])

@app.get("/health")
async def health(): return {"ok":True,"version":"5.0","service":"whale-flow-pro","time":int(time.time())}

@app.get("/api/liquidity")
async def liquidity_scan(limit:int=20):
    try:
        markets=(await tickers())[:30]; out=[]
        for m in markets:
            try:
                x=await liquidity(m["symbol"]); x.update(volume24h=m["volume24h"],change24h=m["change"]); out.append(x)
            except Exception: pass
        out.sort(key=lambda x:(x["score"],x["whale_pressure"],x["whale_flow"]),reverse=True)
        return {"items":out[:max(1,min(limit,30))],"source":"Binance spot aggTrades","whale_threshold":WHALE_USD}
    except Exception as e: return {"items":[],"error":str(e)}

@app.get("/api/liquidity/{symbol}")
async def liquidity_one(symbol:str):
    try: return await liquidity(symbol.upper())
    except Exception as e: return {"error":str(e)}

@app.get("/api/markets")
async def markets(limit:int=80):
    try: return {"items":(await tickers())[:max(1,min(limit,100))],"source":"Binance Spot 24h"}
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/futures")
async def futures():
    try:
        a=await bn("/fapi/v1/ticker/24hr")
        out=[{"symbol":x["symbol"],"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":float(x.get("quoteVolume",0))} for x in a if x["symbol"].endswith("USDT") and x["symbol"] not in STABLE and float(x.get("quoteVolume",0))>=MIN_VOL]
        return {"items":sorted(out,key=lambda x:x["volume24h"],reverse=True)[:100],"source":"Binance Futures"}
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/{market}")
async def other_market(market:str):
    if market not in MARKETS: raise HTTPException(404,"market not found")
    items=await yahoo(MARKETS[market])
    return {"market":market,"items":items,"source":"Yahoo Finance public chart","note":"البيانات العامة لا توفر صفقات حيتان حقيقية؛ يتم عرض السعر والحجم فقط."}

@app.get("/api/tracker")
async def tracker():
    with closing(conn()) as c:return {"items":[dict(x) for x in c.execute("SELECT * FROM watchlist ORDER BY id DESC").fetchall()]}

@app.post("/api/tracker/{market}/{symbol}")
async def add_tracker(market:str,symbol:str):
    with closing(conn()) as c:
        c.execute("INSERT OR IGNORE INTO watchlist(symbol,market,created_at) VALUES(?,?,?)",(symbol.upper(),market,time.time())); c.commit()
    return {"ok":True}

@app.delete("/api/tracker/{market}/{symbol}")
async def del_tracker(market:str,symbol:str):
    with closing(conn()) as c:
        c.execute("DELETE FROM watchlist WHERE symbol=? AND market=?",(symbol.upper(),market)); c.commit()
    return {"ok":True}

@app.get("/api/platform/summary")
async def summary():
    try:
        a=(await liquidity_scan(10))["items"]
        return {"early":sum(x["status"]=="EARLY" for x in a),"watch":sum(x["status"]=="WATCH" for x in a),"tracked":len(a),"min_volume":MIN_VOL,"whale_threshold":WHALE_USD}
    except Exception:return {"early":0,"watch":0,"tracked":0}

@app.get("/api/news")
async def news(): return {"items":[],"message":"مصدر الأخبار غير مفعّل حتى لا نعرض أخبار وهمية."}
@app.get("/api/blog")
async def blog(): return {"items":[],"message":"قسم المقالات جاهز للنشر."}
@app.get("/api/auth/me")
async def me(): return {"authenticated":False,"user":None,"message":"تسجيل الحساب يحتاج مزود هوية قبل تفعيله."}

@app.get("/")
async def root(): return FileResponse(STATIC/"index.html")
@app.get("/{path:path}")
async def files(path:str):
    p=STATIC/path
    return FileResponse(p if p.is_file() else STATIC/"index.html")
