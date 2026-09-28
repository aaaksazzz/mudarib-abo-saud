"""
Mudarib Intelligence Engine V3
Large market-analysis service. No classic indicators are used for the decision layer.
It studies raw price, trades, depth, liquidity, derivatives positioning and cross-market context.
"""
from __future__ import annotations
import json, math, os, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque

BASE_URL="https://api.binance.com"
FUT_URL="https://fapi.binance.com"
FRAMES=("5m","15m","1h","4h","1d","1w","1M")
MARKETS=("spot","futures","contracts")

CACHE={}
CACHE_LOCK=threading.Lock()
SCAN_CACHE={}
RUNNING=False
LAST_RUN=0
STATS={"cycles":0,"symbols":0,"raw_requests":0,"errors":0,"last_duration":0}

def _now(): return time.time()
def _clamp(x,a=0,b=100):
    try:return max(a,min(b,float(x)))
    except:return a
def _get(url,timeout=5):
    global STATS
    try:
        STATS["raw_requests"]+=1
        with urllib.request.urlopen(url,timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        STATS["errors"]+=1
        return None

def _cached(key,ttl,loader):
    now=_now()
    with CACHE_LOCK:
        v=CACHE.get(key)
        if v and now-v[0]<ttl:return v[1]
    x=loader()
    if x is not None:
        with CACHE_LOCK:CACHE[key]=(now,x)
    return x

def symbols(futures=False):
    key="symbols:futures" if futures else "symbols:spot"
    def load():
        base=FUT_URL if futures else BASE_URL
        path="/fapi/v1/exchangeInfo" if futures else "/api/v3/exchangeInfo"
        d=_get(base+path,8) or {}
        out=[]
        for s in d.get("symbols",[]):
            if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT":continue
            if futures and s.get("contractType") not in ("PERPETUAL","CURRENT_QUARTER","NEXT_QUARTER"):continue
            out.append(s.get("symbol"))
        return sorted(set(x for x in out if x))
    return _cached(key,300,load) or ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"]

def raw_klines(symbol,frame,futures=False,limit=120):
    base=FUT_URL if futures else BASE_URL
    path="/fapi/v1/klines" if futures else "/api/v3/klines"
    q=urllib.parse.urlencode({"symbol":symbol,"interval":frame,"limit":limit})
    return _cached(f"k:{futures}:{symbol}:{frame}",8,lambda:_get(base+path+"?"+q,6)) or []

def depth(symbol,futures=False,limit=100):
    base=FUT_URL if futures else BASE_URL
    path="/fapi/v1/depth" if futures else "/api/v3/depth"
    q=urllib.parse.urlencode({"symbol":symbol,"limit":limit})
    return _cached(f"d:{futures}:{symbol}",4,lambda:_get(base+path+"?"+q,5)) or {}

def trades(symbol,futures=False,limit=1000):
    base=FUT_URL if futures else BASE_URL
    path="/fapi/v1/aggTrades" if futures else "/api/v3/aggTrades"
    q=urllib.parse.urlencode({"symbol":symbol,"limit":limit})
    return _cached(f"t:{futures}:{symbol}",4,lambda:_get(base+path+"?"+q,6)) or []

def derivatives(symbol):
    q=urllib.parse.urlencode({"symbol":symbol})
    return {
      "funding":_cached("fund:"+symbol,30,lambda:_get(FUT_URL+"/fapi/v1/premiumIndex?"+q,5)) or {},
      "oi":_cached("oi:"+symbol,20,lambda:_get(FUT_URL+"/fapi/v1/openInterest?"+q,5)) or {},
      "longshort":_cached("ls:"+symbol,30,lambda:_get(FUT_URL+"/futures/data/globalLongShortAccountRatio?"+q+"&period=5m&limit=30",5)) or [],
    }

def _book_metrics(b):
    bids=[(float(x[0]),float(x[1])) for x in b.get("bids",[]) if len(x)>1]
    asks=[(float(x[0]),float(x[1])) for x in b.get("asks",[]) if len(x)>1]
    if not bids or not asks:return {}
    bidv=sum(x[1] for x in bids); askv=sum(x[1] for x in asks)
    mid=(bids[0][0]+asks[0][0])/2
    near=lambda rows:sum(q for p,q in rows if abs(p-mid)/mid<=0.003)
    nb,na=near(bids),near(asks)
    walls_b=max(bids,key=lambda x:x[1])[1] if bids else 0
    walls_a=max(asks,key=lambda x:x[1])[1] if asks else 0
    return {"bid_volume":bidv,"ask_volume":askv,"imbalance":_clamp(50+50*(bidv-askv)/(bidv+askv or 1)),
            "near_bid":nb,"near_ask":na,"bid_wall":walls_b,"ask_wall":walls_a,
            "spread":(asks[0][0]-bids[0][0])/mid*100}

def _flow_metrics(rows):
    buy=sell=0.0; buy_n=sell_n=0
    for x in rows:
        try:
            q=float(x.get("q",0))
            # Binance aggTrade m=True means buyer is maker => aggressive sell.
            if x.get("m"):sell+=q;sell_n+=1
            else:buy+=q;buy_n+=1
        except:pass
    total=buy+sell
    delta=(buy-sell)/(total or 1)
    return {"buy":buy,"sell":sell,"delta":delta,"buy_trades":buy_n,"sell_trades":sell_n,
            "pressure":_clamp(50+delta*50)}

def _structure(rows):
    if len(rows)<12:return {}
    c=[float(x[4]) for x in rows]; h=[float(x[2]) for x in rows]; l=[float(x[3]) for x in rows]
    # Raw swing structure, no moving averages.
    highs=[]; lows=[]
    for i in range(2,len(c)-2):
        if h[i]>=h[i-1] and h[i]>=h[i+1]:highs.append((i,h[i]))
        if l[i]<=l[i-1] and l[i]<=l[i+1]:lows.append((i,l[i]))
    last=c[-1]
    recent_h=[v for _,v in highs[-5:]]; recent_l=[v for _,v in lows[-5:]]
    rh=max(recent_h) if recent_h else max(h[-10:])
    rl=min(recent_l) if recent_l else min(l[-10:])
    range_pct=(rh-rl)/(last or 1)*100
    breakout_up=last>rh*1.001
    breakout_dn=last<rl*.999
    # Sequence of raw swing points.
    hh=len(recent_h)>=2 and recent_h[-1]>recent_h[-2]
    hl=len(recent_l)>=2 and recent_l[-1]>recent_l[-2]
    lh=len(recent_h)>=2 and recent_h[-1]<recent_h[-2]
    ll=len(recent_l)>=2 and recent_l[-1]<recent_l[-2]
    bull=(hh+hl)*25; bear=(lh+ll)*25
    structure=_clamp(50+bull-bear)
    return {"price":last,"high":rh,"low":rl,"range_pct":range_pct,
            "breakout_up":breakout_up,"breakout_down":breakout_dn,
            "structure":structure,"hh":hh,"hl":hl,"lh":lh,"ll":ll}

def _liquidity(rows,book,flow):
    s=_structure(rows)
    if not s:return {}
    p=s["price"]; hi=s["high"]; lo=s["low"]
    sweep_up=max(float(x[2]) for x in rows[-5:])>hi and p<hi
    sweep_dn=min(float(x[3]) for x in rows[-5:])<lo and p>lo
    near_high=abs(p-hi)/(p or 1)*100
    near_low=abs(p-lo)/(p or 1)*100
    book_imb=book.get("imbalance",50)
    return {"sweep_up":sweep_up,"sweep_down":sweep_dn,"near_high":near_high,"near_low":near_low,
            "liquidity_score":_clamp(book_imb+(12 if sweep_dn else 0)-(12 if sweep_up else 0))}

def analyze_symbol(symbol,frame="15m",futures=False):
    started=_now()
    rows=raw_klines(symbol,frame,futures)
    if len(rows)<20:return None
    b=depth(symbol,futures); tr=trades(symbol,futures)
    book=_book_metrics(b); flow=_flow_metrics(tr)
    struct=_structure(rows); liq=_liquidity(rows,book,flow)
    deriv=derivatives(symbol) if futures else {}
    p=struct.get("price",0)
    # Seven large domains, each built from raw market observations.
    structure_score=struct.get("structure",50)
    flow_score=flow.get("pressure",50)
    liquidity_score=liq.get("liquidity_score",50)
    breakout_score=_clamp(50+(25 if struct.get("breakout_up") else 0)-(25 if struct.get("breakout_down") else 0))
    absorption=_clamp(50+(15 if book.get("near_bid",0)>book.get("near_ask",0)*1.25 else 0)-(15 if book.get("near_ask",0)>book.get("near_bid",0)*1.25 else 0))
    speed=_clamp(50+(float(rows[-1][4])-float(rows[-4][4]))/(p or 1)*1000)
    risk=_clamp(80-abs(float(rows[-1][4])-float(rows[-2][4]))/(p or 1)*1000)
    if futures:
        try:
            f=float(deriv.get("funding",{}).get("lastFundingRate",0))*10000
            oi=float(deriv.get("oi",{}).get("openInterest",0))
            ls=deriv.get("longshort",[])
            ratio=float(ls[-1].get("longShortRatio",1)) if ls else 1
        except: f=0;oi=0;ratio=1
    else:f=0;oi=0;ratio=1
    crowd=_clamp(50-(ratio-1)*18-f*.8)
    scores=[structure_score,flow_score,liquidity_score,breakout_score,absorption,speed,risk,crowd]
    weights=[.18,.18,.14,.10,.10,.08,.10,.12]
    composite=_clamp(sum(a*w for a,w in zip(scores,weights)))
    buy=sum(x>=60 for x in scores); sell=sum(x<=40 for x in scores)
    side="BUY" if buy>=sell else "SELL"
    confidence=round(_clamp(composite+max(buy,sell)*2+min(abs(buy-sell)*2,8)))
    # Targets are structural distances, not indicator distances.
    span=max(abs(struct.get("high",p)-struct.get("low",p)),p*.003)
    if side=="BUY": entry=p; tp=[p+span*.35,p+span*.70,p+span*1.05]; sl=min(struct.get("low",p-span*.45),p-span*.45)
    else: entry=p; tp=[p-span*.35,p-span*.70,p-span*1.05]; sl=max(struct.get("high",p+span*.45),p+span*.45)
    return {"symbol":symbol,"market":"futures" if futures else "spot","timeframe":frame,
            "side":side,"ai":confidence,"entry":entry,"tp1":tp[0],"tp2":tp[1],"tp3":tp[2],"sl":sl,
            "domains":{"structure":round(structure_score),"order_flow":round(flow_score),
                       "liquidity":round(liquidity_score),"breakout":round(breakout_score),
                       "absorption":round(absorption),"speed":round(speed),"risk":round(risk),"crowding":round(crowd)},
            "raw":{"price":p,"bid_ask_imbalance":round(book.get("imbalance",50),2),
                   "delta":round(flow.get("delta",0),5),"spread_pct":round(book.get("spread",0),5),
                   "funding_bps":round(f,3),"open_interest":oi,"long_short":round(ratio,3),
                   "sweep_up":liq.get("sweep_up",False),"sweep_down":liq.get("sweep_down",False)},
            "engine":"Mudarib Intelligence Engine V3","elapsed_ms":round((_now()-started)*1000)}

def scan(frame="15m",limit=50,futures=False):
    global LAST_RUN
    key=f"{futures}:{frame}:{limit}"
    with CACHE_LOCK:
        if key in SCAN_CACHE and _now()-SCAN_CACHE[key][0]<45:return SCAN_CACHE[key][1]
    syms=symbols(futures)
    out=[]; started=_now()
    workers=min(24,max(6,int(os.getenv("INTELLIGENCE_WORKERS","16"))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fs=[ex.submit(analyze_symbol,s,frame,futures) for s in syms]
        for f in as_completed(fs):
            try:
                x=f.result()
                if x:out.append(x)
            except Exception:pass
    out.sort(key=lambda x:(x["ai"],max(x["domains"].values())),reverse=True)
    result={"items":out[:limit],"scanned":len(syms),"returned":min(limit,len(out)),
            "frame":frame,"futures":futures,"engine":"Mudarib Intelligence Engine V3",
            "raw_analysis":True,"duration_ms":round((_now()-started)*1000),
            "stats":dict(STATS)}
    with CACHE_LOCK:SCAN_CACHE[key]=(_now(),result)
    LAST_RUN=_now(); STATS["cycles"]+=1; STATS["symbols"]+=len(syms); STATS["last_duration"]=result["duration_ms"]
    return result

def start_engine():
    global RUNNING
    if RUNNING:return
    RUNNING=True
    def loop():
        # Background warm-up. It never blocks FastAPI startup.
        while RUNNING:
            try:
                scan("15m",30,False)
                scan("15m",30,True)
            except Exception:pass
            time.sleep(int(os.getenv("INTELLIGENCE_SCAN_SECONDS","180")))
    threading.Thread(target=loop,name="intelligence-engine",daemon=True).start()

def status():
    return {"running":RUNNING,"last_run":LAST_RUN,"stats":dict(STATS),
            "cache_entries":len(CACHE),"scan_cache_entries":len(SCAN_CACHE),
            "workers":int(os.getenv("INTELLIGENCE_WORKERS","16")),
            "scan_seconds":int(os.getenv("INTELLIGENCE_SCAN_SECONDS","180"))}
