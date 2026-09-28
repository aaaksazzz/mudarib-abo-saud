from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

app=FastAPI(title="التداول الذكي PRO", version="1.0")
BASE=Path(__file__).parent
STORE=BASE/"data.json"
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES=["15m","1h","4h","1d","1w","1M"]
def load():
    try:return json.loads(STORE.read_text())
    except:return {"trades":[]}
def save(x):
    try: STORE.write_text(json.dumps(x,ensure_ascii=False))
    except: pass
def binance(symbol="BTCUSDT", interval="15m", futures=False):
    host="https://fapi.binance.com" if futures else "https://api.binance.com"
    q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":30})
    try:
        with urllib.request.urlopen(host+"/api/v3/klines?"+q if not futures else host+"/fapi/v1/klines?"+q,timeout=3) as r:
            return json.loads(r.read())
    except:return []
def signal(symbol,market,frame):
    futures=market in ("futures","contracts")
    rows=binance(symbol,frame,futures)
    if rows:
        close=float(rows[-1][4]); prev=float(rows[-2][4]); change=(close/prev-1)*100 if prev else 0
        side="BUY" if change>=0 else "SELL"
        if market in ("spot","saudi","us"): side="BUY"
        entry=close; risk=abs(close*0.008)
        if side=="BUY": tp=[entry+risk,entry+risk*2,entry+risk*3]; sl=entry-risk
        else: tp=[entry-risk,entry-risk*2,entry-risk*3]; sl=entry+risk
        ai=max(55,min(92,round(65+abs(change)*8)))
    else:
        entry=100.0; side="BUY" if market not in ("futures","contracts","forex") else "BUY"; risk=.8
        tp=[entry+risk,entry+risk*2,entry+risk*3]; sl=entry-risk; ai=60
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"ai":ai,"entry":entry,"tp1":tp[0],"tp2":tp[1],"tp3":tp[2],"sl":sl,"updated":int(time.time())}
def symbols(market):
    if market=="spot": return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]
    if market in ("futures","contracts"): return ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]
    return ["BTCUSDT","ETHUSDT","SOLUSDT"]
@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","version":"clean-v1","time":datetime.now(timezone.utc).isoformat()}
@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES,"default":"30m"}
@app.get("/api/trades")
def trades(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid market/timeframe"}
    return {"items":[signal(s,market,timeframe) for s in symbols(market)],"market":market,"timeframe":timeframe}
@app.get("/api/scanner")
def scanner(timeframe:str="15m"):
    if timeframe not in FRAMES: timeframe="15m"
    items=[]
    for m in MARKETS:
        for s in symbols(m)[:3]:
            x=signal(s,m,timeframe); items.append(x)
    items.sort(key=lambda x:x["ai"],reverse=True)
    return {"items":items[:18],"timeframe":timeframe}
@app.get("/api/tracker")
def tracker():
    d=load(); items=d.get("trades",[])
    closed=[x for x in items if x.get("status")=="closed"]
    wins=sum(1 for x in closed if x.get("result")=="win")
    losses=sum(1 for x in closed if x.get("result")=="loss")
    return {"items":items,"stats":{"open":sum(x.get("status")=="open" for x in items),"wins":wins,"losses":losses,"closed":len(closed)}}
@app.post("/api/tracker/add")
def tracker_add(item:dict):
    d=load(); item={**item,"id":int(time.time()*1000),"status":"open","created":int(time.time())}; d.setdefault("trades",[]).append(item); save(d); return item
@app.get("/api/news")
def news(): return {"items":[{"title":"تحديث السوق والتحليل الذكي","time":"الآن"},{"title":"متابعة الأسواق على إطار 30 دقيقة","time":"اليوم"},{"title":"مراقبة الفرص الجديدة","time":"اليوم"}]}
@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
