from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import time, math, random

app=FastAPI(title="التداول الذكي PRO", version="1.0.0")
BASE=Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")

MARKETS={
 "spot":"السبوت","futures":"الفيوتشر","contracts":"العقود",
 "saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"
}
FRAMES={"5m":"5د","15m":"15د","1h":"1س","4h":"4س","1d":"يومي","1w":"أسبوعي","1M":"شهري"}

@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","time":time.time()}

@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES}

@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("15m")):
    # Demo-safe shell: no fabricated live prices. Real market adapters are added in the next layer.
    return {"market":market,"market_name":MARKETS.get(market,market),
            "timeframe":timeframe,"timeframe_name":FRAMES.get(timeframe,timeframe),
            "items":[],"message":"بانتظار ربط مصدر البيانات الحقيقي"}

@app.get("/api/news")
def news(): return {"items":[]}

@app.get("/api/scanner")
def scanner(): return {"items":[]}

@app.get("/api/tracker")
def tracker(): return {"open":[],"closed":[],"stats":{"wins":0,"losses":0,"total":0}}

@app.get("/api/account")
def account(): return {"authenticated":False}

@app.get("/api/admin")
def admin(): return {"ok":True}
