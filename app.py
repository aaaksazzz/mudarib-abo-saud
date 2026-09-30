import os,time
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
BASE=Path(__file__).resolve().parent
STATIC=BASE/"static"
app=FastAPI(title="التداول الذكي PRO",version="5.0")
app.mount("/static",StaticFiles(directory=str(STATIC)),name="static")
@app.get("/",include_in_schema=False)
def root(): return FileResponse(STATIC/"index.html")
@app.get("/health")
def health(): return {"status":"ok","version":"5.0","time":int(time.time())}
def interval(tf): return {"15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d","1w":"1w","1M":"1M"}.get(tf,"15m")
async def binance(path,params=None):
    async with httpx.AsyncClient(timeout=12,headers={"User-Agent":"modareb-pro"}) as c:
        r=await c.get("https://api.binance.com"+path,params=params)
        r.raise_for_status()
        return r.json()
@app.get("/api/platform/summary")
def summary(): return {"status":"online","version":"5.0","strategy":"EMA20 + EMA200 + RSI","timeframes":["15m","30m","1h","4h","1d","1w","1M"]}
@app.get("/api/tracker")
def tracker(): return {"open":[],"closed":[],"stats":{"open":0,"closed":0,"wins":0,"losses":0,"pnl":0}}
@app.get("/api/trades")
def trades(): return {"items":[]}
@app.get("/api/news")
def news(): return {"items":[]}
@app.get("/api/auth/me")
def me(): return {"authenticated":False,"user":None}
@app.get("/api/markets")
async def markets(tf:str="15m",limit:int=40):
    try:
        data=await binance("/api/v3/ticker/24hr")
        out=[]
        for x in data:
            s=x.get("symbol","");q=float(x.get("quoteVolume") or 0)
            if s.endswith("USDT") and q>=1000000 and not s.endswith(("USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT")):
                out.append({"symbol":s,"price":float(x.get("lastPrice") or 0),"change":float(x.get("priceChangePercent") or 0),"volume":q})
        out.sort(key=lambda z:abs(z["change"]),reverse=True)
        return {"timeframe":interval(tf),"items":out[:min(max(limit,1),100)],"count":len(out)}
    except Exception as e: return JSONResponse({"error":"تعذر جلب بيانات Binance","detail":str(e)},status_code=502)
@app.get("/api/scanner")
async def scanner(tf:str="15m",limit:int=30): return await markets(tf,limit)
@app.get("/api/signal")
async def signal(symbol:str,tf:str="15m"):
    try:
        k=await binance("/api/v3/klines",{"symbol":symbol.upper(),"interval":interval(tf),"limit":220});c=[float(x[4]) for x in k]
        def ema(n):
            if len(c)<n:return None
            e=sum(c[:n])/n;a=2/(n+1)
            for v in c[n:]:e=v*a+e*(1-a)
            return e
        e20,e200=ema(20),ema(200);g=[];l=[]
        for i in range(1,len(c)):
            d=c[i]-c[i-1];g.append(max(d,0));l.append(max(-d,0))
        ag=sum(g[:14])/14;al=sum(l[:14])/14
        for i in range(14,len(g)):ag=(ag*13+g[i])/14;al=(al*13+l[i])/14
        r=100 if al==0 else 100-(100/(1+ag/al));p=c[-1]
        score=(35 if p<e20 else 0)+(30 if r<50 else 0)+(35 if e200 and p<e200 else 0)
        return {"symbol":symbol.upper(),"timeframe":tf,"price":p,"ema20":e20,"ema200":e200,"rsi":r,"signal":"شراء" if score>=65 else "انتظار","ai":score}
    except Exception as e:return JSONResponse({"error":str(e)},status_code=502)
