"""Mudarib Data Hub - high-throughput market data layer.
Multi-source, concurrent, cached, retrying. Keeps provider failures isolated.
"""
from __future__ import annotations
import json, os, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BINANCE="https://api.binance.com"
FAPI="https://fapi.binance.com"
YAHOO="https://query1.finance.yahoo.com"
LOCK=threading.RLock()
CACHE={}
SOURCE_STATS={}
WORKERS=int(os.getenv("DATA_WORKERS","32"))
TTL=int(os.getenv("DATA_CACHE_TTL","20"))

def _stat(source,ok=True):
    with LOCK:
        s=SOURCE_STATS.setdefault(source,{"ok":0,"errors":0,"last":0})
        s["ok" if ok else "errors"]+=1; s["last"]=int(time.time())

def get_json(url,source="unknown",timeout=8,retries=2):
    key="raw:"+url
    now=time.time()
    with LOCK:
        x=CACHE.get(key)
        if x and now-x[0]<TTL:return x[1]
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"MudaribDataHub/3.0"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                data=json.loads(r.read())
            with LOCK:CACHE[key]=(now,data)
            _stat(source,True); return data
        except Exception:
            if attempt<retries: time.sleep(.25*(attempt+1))
    _stat(source,False); return None

def _binance_symbols(futures=False):
    base=FAPI if futures else BINANCE
    path="/fapi/v1/exchangeInfo" if futures else "/api/v3/exchangeInfo"
    d=get_json(base+path,"binance_futures" if futures else "binance_spot",10) or {}
    out=[]
    for s in d.get("symbols",[]):
        if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT":continue
        if futures and s.get("contractType") not in ("PERPETUAL","CURRENT_QUARTER","NEXT_QUARTER"):continue
        out.append(s["symbol"])
    return sorted(set(out))

def binance_tickers(futures=False,min_volume=0):
    base=FAPI if futures else BINANCE
    path="/fapi/v1/ticker/24hr" if futures else "/api/v3/ticker/24hr"
    d=get_json(base+path,"binance_futures" if futures else "binance_spot",10) or []
    out={}
    for x in d:
        s=x.get("symbol","")
        if s.endswith("USDT") and float(x.get("quoteVolume",0) or 0)>=min_volume:out[s]=x
    return out

def yahoo_quote(symbol,market):
    y=(symbol+".SR") if market=="saudi" else ((symbol+"=X") if market=="forex" else symbol)
    url=YAHOO+"/v8/finance/chart/"+urllib.parse.quote(y,safe="")+"?range=5d&interval=15m"
    d=get_json(url,"yahoo_"+market,8,2)
    try:
        r=(d["chart"]["result"] or [])[0]; m=r.get("meta",{})
        q=(r.get("indicators",{}).get("quote") or [{}])[0]
        closes=[v for v in q.get("close",[]) if v is not None]
        vols=[v for v in q.get("volume",[]) if v is not None]
        p=float(m.get("regularMarketPrice") or closes[-1]); prev=float(m.get("previousClose") or (closes[-2] if len(closes)>1 else p))
        return {"symbol":symbol,"regularMarketPrice":p,"regularMarketChangePercent":(p/prev-1)*100 if prev else 0,"regularMarketVolume":float(vols[-1]) if vols else 0}
    except Exception:return None

def parallel_quotes(symbols,market):
    out={}
    with ThreadPoolExecutor(max_workers=min(WORKERS,max(8,len(symbols)))) as ex:
        fs=[ex.submit(yahoo_quote,s,market) for s in symbols]
        for f in as_completed(fs):
            try:
                x=f.result()
                if x:out[x["symbol"]]=x
            except Exception:pass
    return out

def status():
    with LOCK:
        return {"workers":WORKERS,"cache_entries":len(CACHE),"sources":dict(SOURCE_STATS),"timestamp":int(time.time())}
