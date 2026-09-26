from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import httpx,asyncio
from db import init_db,rows,one
from strategy import signal_from_klines
app=FastAPI(title="التداول الذكي PRO",version="2.0")
BASE=Path(__file__).parent
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
@app.on_event("startup")
def startup():init_db()
@app.get("/health")
def health():return {"status":"ok","service":"trading-pro"}
@app.get("/")
def home():return FileResponse(BASE/"static/index.html")
@app.get("/api/trades")
def trades(market="spot",timeframe="15m",limit:int=50):return rows("SELECT * FROM trades WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT ?",(market,timeframe,limit))
@app.get("/api/stats")
def stats():
    total=one("SELECT COUNT(*) n FROM trades")["n"];closed=one("SELECT COUNT(*) n FROM trades WHERE status='closed'")["n"];wins=one("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl>0")["n"];pnl=one("SELECT COALESCE(SUM(pnl),0) n FROM trades WHERE status='closed'")["n"]
    return {"open":total-closed,"closed":closed,"wins":wins,"losses":closed-wins,"win_rate":round(wins/closed*100,2) if closed else None,"pnl":round(pnl,4)}
async def klines(symbol="BTCUSDT",interval="15m",limit=250):
    async with httpx.AsyncClient(timeout=8) as c:
        r=await c.get("https://api.binance.com/api/v3/klines",params={"symbol":symbol,"interval":interval,"limit":limit});r.raise_for_status();return r.json()
@app.get("/api/market/{symbol}")
async def market(symbol:str,timeframe="15m"):
    try:
        k=await klines(symbol.upper(),timeframe);return {"symbol":symbol.upper(),"timeframe":timeframe,"price":float(k[-1][4]),"signal":signal_from_klines(k)}
    except Exception:raise HTTPException(502,"تعذر جلب بيانات السوق حالياً")
@app.get("/api/scanner")
async def scanner(timeframe="15m"):
    symbols=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","LINKUSDT"]
    async def check(s):
        try:
            k=await klines(s,timeframe);sig=signal_from_klines(k)
            return {"symbol":s,"price":float(k[-1][4]),"signal":sig} if sig else None
        except Exception:return None
    return [x for x in await asyncio.gather(*(check(s) for s in symbols)) if x]
@app.get("/api/news")
def news():return rows("SELECT * FROM news ORDER BY id DESC LIMIT 30")
