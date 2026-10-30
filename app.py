import os, time, threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, send_from_directory, request
import requests

app = Flask(__name__, static_folder="static")
BASES = {"spot": "https://api.binance.com", "futures": "https://fapi.binance.com"}
STABLES = {"USDC","USDT","BUSD","FDUSD","TUSD","USDP","DAI","EUR"}
_cache, _lock = {}, threading.Lock()
TTL = 30
TIMEFRAMES = {"15m":"15m","1h":"1h","4h":"4h","1d":"1d"}

def cached(key, loader):
    now=time.time()
    with _lock:
        item=_cache.get(key)
        if item and now-item[0] < TTL: return item[1]
    value=loader()
    with _lock: _cache[key]=(time.time(),value)
    return value

def get_json(url, params=None, timeout=8):
    response=requests.get(url,params=params,timeout=timeout,headers={"User-Agent":"SmartTradingPro/1.0"})
    response.raise_for_status()
    return response.json()

def market_tickers(kind):
    base=BASES[kind]
    path="/api/v3/ticker/24hr" if kind=="spot" else "/fapi/v1/ticker/24hr"
    rows=cached(kind+":tickers",lambda:get_json(base+path))
    out=[]
    for x in rows:
        symbol=x.get("symbol","")
        if not symbol.endswith("USDT"): continue
        asset=symbol[:-4]
        if asset in STABLES: continue
        try:
            volume=float(x.get("quoteVolume",0)); change=float(x.get("priceChangePercent",0)); price=float(x.get("lastPrice",0))
        except (TypeError,ValueError): continue
        if volume < 1_000_000 or price <= 0: continue
        out.append({"symbol":symbol,"asset":asset,"price":price,"change24h":change,"volume":volume})
    return sorted(out,key=lambda x:x["volume"],reverse=True)

def candles(kind,symbol,interval):
    path="/api/v3/klines" if kind=="spot" else "/fapi/v1/klines"
    return get_json(BASES[kind]+path,{"symbol":symbol,"interval":interval,"limit":100})

def analyse(kind,item,interval):
    try:
        rows=candles(kind,item["symbol"],interval)
        if len(rows)<55: return None
        closes=[float(r[4]) for r in rows]
        highs=[float(r[2]) for r in rows]
        lows=[float(r[3]) for r in rows]
        fast=sum(closes[-20:])/20
        slow=sum(closes[-50:])/50
        last=closes[-1]
        previous=closes[-2]
        delta=(last/previous-1)*100 if previous else 0
        true_ranges=[]
        for i in range(1,len(rows)):
            true_ranges.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
        atr=sum(true_ranges[-14:])/14
        if atr<=0 or last<=0: return None
        side="BUY" if last>fast>slow and delta>0 else ("SELL" if last<fast<slow and delta<0 else "WAIT")
        if side=="WAIT": return None
        risk=atr*1.5
        if side=="BUY":
            stop=last-risk
            targets=[last+risk*1.5,last+risk*2.5,last+risk*3.5]
        else:
            stop=last+risk
            targets=[last-risk*1.5,last-risk*2.5,last-risk*3.5]
        if stop<=0 or any(x<=0 for x in targets): return None
        separation=abs(fast/slow-1)*100
        strength=round(min(99,50+separation*8+abs(delta)*2),1)
        return {"symbol":item["symbol"],"price":last,"entry":last,"stop_loss":stop,
                "tp1":targets[0],"tp2":targets[1],"tp3":targets[2],
                "risk_percent":round(abs(last-stop)/last*100,3),
                "change24h":item["change24h"],"volume":item["volume"],
                "timeframe":interval,"side":side,"strength":strength}
    except (requests.RequestException,ValueError,TypeError,IndexError,KeyError,ZeroDivisionError):
        return None

@app.get("/")
def home(): return send_from_directory("static","index.html")

@app.get("/health")
def health(): return jsonify({"ok":True,"service":"smart-trading-pro","status":"healthy"})

@app.get("/api/markets")
def markets():
    return jsonify({"markets":[
      {"id":"spot","name":"Binance Spot","status":"live"},
      {"id":"futures","name":"Binance Futures","status":"live"},
      {"id":"us","name":"الأسهم الأمريكية","status":"provider_required"},
      {"id":"saudi","name":"السوق السعودي","status":"provider_required"},
      {"id":"forex","name":"الفوركس والذهب","status":"provider_required"},
      {"id":"alpha","name":"Binance Alpha","status":"provider_required"}
    ]})

@app.get("/api/market/<kind>")
def market(kind):
    if kind not in ("spot","futures"):
        return jsonify({"error":"مصدر البيانات لهذا السوق غير مربوط بعد","status":"provider_required","assets":[],"signals":[]}),503
    interval=request.args.get("timeframe","15m")
    if interval not in TIMEFRAMES: return jsonify({"error":"إطار زمني غير مدعوم"}),400
    try:
        assets=cached(kind+":universe",lambda:market_tickers(kind))
        up=sum(1 for x in assets if x["change24h"]>0)
        down=sum(1 for x in assets if x["change24h"]<0)
        direction="صاعد" if up>down else ("هابط" if down>up else "محايد")
        candidates=sorted(assets,key=lambda x:abs(x["change24h"]),reverse=True)[:18]
        with ThreadPoolExecutor(max_workers=5) as pool:
            analysed=list(pool.map(lambda x:analyse(kind,x,interval),candidates))
        allowed="BUY" if direction=="صاعد" else ("SELL" if direction=="هابط" else None)
        signals=[x for x in analysed if x and allowed and x["side"]==allowed]
        signals.sort(key=lambda x:(x["strength"],abs(x["change24h"])),reverse=True)
        return jsonify({"market":kind,"direction":direction,"up":up,"down":down,"total":len(assets),
                        "timeframe":interval,"signals":signals[:3],"updated":int(time.time()),
                        "source":"Binance public market data","method":"SMA20/SMA50 + ATR(14)",
                        "notice":"مستويات فنية محسوبة من ATR وليست ضماناً؛ الإشارات لا تُحفظ بعد إعادة تشغيل الخدمة."})
    except requests.RequestException as e:
        return jsonify({"error":"تعذر جلب بيانات السوق الآن","detail":str(e)[:180],"assets":[],"signals":[]}),502

@app.errorhandler(404)
def not_found(_): return jsonify({"error":"not_found"}),404

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","8080")))
