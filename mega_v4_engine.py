"""
Mudarib Mega Signal Engine V4
WebSocket-first multi-timeframe market scanner for live signal generation.
Analysis only: it does not place exchange orders.
"""
from __future__ import annotations
import json, os, time, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import websocket
except Exception:
    websocket = None

SPOT="https://api.binance.com"; FUT="https://fapi.binance.com"
WS_SPOT="wss://stream.binance.com:9443/stream"; WS_FUT="wss://fstream.binance.com/stream"
LOCK=threading.RLock(); RUNNING=False; THREADS=[]
STATE={"spot":{}, "futures":{}}; SYMBOLS={"spot":[], "futures":[]}
LAST_SCAN=0
STATS={"ws_connections":0,"ws_reconnects":0,"events":0,"symbols":0,"deep_scans":0,"signals":0,"errors":0,"last_scan_ms":0}
WORKERS=int(os.getenv("MEGA_V4_WORKERS","24")); MIN_AI=int(os.getenv("MEGA_V4_MIN_AI","58"))
CANDIDATES=int(os.getenv("MEGA_V4_CANDIDATES","160"))

def _get(url,timeout=8):
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"MudaribMegaV4/4.0"})
        with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read())
    except Exception:
        STATS["errors"]+=1; return None

def _symbols(futures):
    base=FUT if futures else SPOT; path="/fapi/v1/exchangeInfo" if futures else "/api/v3/exchangeInfo"
    d=_get(base+path,10) or {}; out=[]
    for s in d.get("symbols",[]):
        if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT":continue
        if futures and s.get("contractType") not in ("PERPETUAL","CURRENT_QUARTER","NEXT_QUARTER"):continue
        out.append(s["symbol"])
    if not futures:
        t=_get(SPOT+"/api/v3/ticker/24hr",10) or []
        allowed=set(out); liquid={x.get("symbol") for x in t if x.get("symbol") in allowed and float(x.get("quoteVolume",0) or 0)>=1000000}
        if liquid:out=sorted(liquid)
    return sorted(set(out))

def _seed():
    for market,fut in (("spot",False),("futures",True)):
        s=_symbols(fut)
        with LOCK:
            SYMBOLS[market]=s
            for x in s:STATE[market].setdefault(x,{})
    STATS["symbols"]=sum(len(x) for x in SYMBOLS.values())

def _handle(msg,market):
    try:
        d=msg.get("data",msg)
        if d.get("e")!="kline":return
        k=d.get("k",{}); sym=k.get("s")
        if not sym:return
        with LOCK:
            STATE[market].setdefault(sym,{}).update({
                "price":float(k.get("c",0) or 0),"open":float(k.get("o",0) or 0),
                "high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),
                "volume":float(k.get("q",0) or 0),"trades":int(k.get("n",0) or 0),
                "closed":bool(k.get("x")),"event":int(d.get("E",0) or 0),"interval":k.get("i")})
            STATS["events"]+=1
    except Exception:STATS["errors"]+=1

def _ws_worker(market,interval,shard):
    if websocket is None:return
    base=WS_FUT if market=="futures" else WS_SPOT
    streams="/".join(f"{s.lower()}@kline_{interval}" for s in shard); url=base+"?streams="+streams
    while RUNNING:
        try:
            STATS["ws_connections"]+=1
            def on_message(ws,message):
                try:_handle(json.loads(message),market)
                except Exception:STATS["errors"]+=1
            def on_error(ws,error):STATS["errors"]+=1
            def on_close(ws,*args):STATS["ws_reconnects"]+=1
            websocket.WebSocketApp(url,on_message=on_message,on_error=on_error,on_close=on_close).run_forever(ping_interval=120,ping_timeout=30)
        except Exception:STATS["errors"]+=1
        if RUNNING:time.sleep(2)

def _start_ws():
    if websocket is None:return
    for market in ("spot","futures"):
        syms=SYMBOLS[market]
        for i in range(0,len(syms),450):
            shard=syms[i:i+450]
            for interval in ("5m","15m"):
                t=threading.Thread(target=_ws_worker,args=(market,interval,shard),name=f"mega-v4-{market}-{interval}-{i}",daemon=True)
                THREADS.append(t);t.start()

def _klines(symbol,frame,futures):
    base=FUT if futures else SPOT; path="/fapi/v1/klines" if futures else "/api/v3/klines"
    q=urllib.parse.urlencode({"symbol":symbol,"interval":frame,"limit":80})
    return _get(base+path+"?"+q,6) or []

def _features(rows):
    if len(rows)<25:return None
    c=[float(r[4]) for r in rows];h=[float(r[2]) for r in rows];l=[float(r[3]) for r in rows];v=[float(r[7]) for r in rows];p=c[-1]
    def ema(vals,n):
        e=sum(vals[:n])/n;a=2/(n+1)
        for z in vals[n:]:e=z*a+e*(1-a)
        return e
    e20=ema(c,20);e50=ema(c,50)
    gains=[max(c[i]-c[i-1],0) for i in range(1,len(c))];losses=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag=sum(gains[-14:])/14;al=sum(losses[-14:])/14;rsi=100 if al==0 else 100-100/(1+ag/al)
    avgv=sum(v[-21:-1])/20 if len(v)>21 else max(sum(v[:-1])/max(1,len(v)-1),1);vr=v[-1]/avgv if avgv else 1
    rng=(max(h[-20:])-min(l[-20:]))/p*100 if p else 0;move=(c[-1]/c[-4]-1)*100 if c[-4] else 0
    return {"price":p,"ema20":e20,"ema50":e50,"rsi":rsi,"vr":vr,"range_pct":rng,"move":move,
            "breakout_up":p>max(h[-21:-1]),"breakout_dn":p<min(l[-21:-1])}

def _score(symbol,market,frame):
    fut=market=="futures";r5=_klines(symbol,"5m",fut);r15=_klines(symbol,"15m",fut);r1=_klines(symbol,"1h",fut)
    rf=r5 if frame=="5m" else r15 if frame=="15m" else _klines(symbol,frame,fut)
    f5=_features(r5);f15=_features(r15);f1=_features(r1);ff=_features(rf)
    if not all((f5,f15,f1,ff)):return None
    bull=sum([f5["price"]>f5["ema20"],f15["price"]>f15["ema20"],f1["price"]>f1["ema20"],f1["price"]>f1["ema50"],f15["rsi"]>50,f5["move"]>0,f15["vr"]>=1.15])
    bear=sum([f5["price"]<f5["ema20"],f15["price"]<f15["ema20"],f1["price"]<f1["ema20"],f1["price"]<f1["ema50"],f15["rsi"]<50,f5["move"]<0,f15["vr"]>=1.15])
    original="BUY" if bull>=bear else "SELL"
    if market=="spot":original="BUY"
    agreement=max(bull,bear);trend=50+agreement*6;direction=50+abs(bull-bear)*8
    momentum=50+min(abs(f5["move"])*8,25);volume=50+min(max(f15["vr"]-1,0)*35,35)
    breakout=75 if f5["breakout_up"] or f5["breakout_dn"] else 50
    risk=max(45,82-min(abs(f15["move"])*6,30)-max(0,f15["range_pct"]-8)*2)
    ai=round(min(99,max(0,trend*.22+direction*.18+momentum*.16+volume*.14+breakout*.12+risk*.18)))
    if agreement<4:ai=min(ai,57)
    p=ff["price"];span=max(p*f15["range_pct"]/100*.45,p*.003)
    if original=="BUY":tp=[p+span,p+span*1.8,p+span*2.6];sl=p-span*.85
    else:tp=[p-span,p-span*1.8,p-span*2.6];sl=p+span*.85
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":original,"original_side":original,"ai":ai,
            "agreement":agreement,"entry":p,"tp1":tp[0],"tp2":tp[1],"tp3":tp[2],"sl":sl,
            "move":round(f5["move"],3),"volume_ratio":round(f15["vr"],2),
            "trend_5m":round(f5["price"]/f5["ema20"]*100-100,3),"trend_1h":round(f1["price"]/f1["ema50"]*100-100,3),
            "engine":"Mudarib Mega Signal Engine V4"}

def scan(market="spot",frame="15m",limit=120):
    global LAST_SCAN
    started=time.time()
    with LOCK:syms=list(SYMBOLS.get(market,[]));fast=dict(STATE.get(market,{}))
    ranked=[]
    for s in syms:
        x=fast.get(s,{});p=float(x.get("price",0) or 0)
        if p<=0:continue
        move=abs((p/float(x.get("open",p) or p)-1)*100);ranked.append((move,float(x.get("volume",0) or 0),s))
    ranked.sort(reverse=True);selected=[s for _,_,s in ranked[:CANDIDATES]];out=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fs=[ex.submit(_score,s,market,frame) for s in selected]
        for f in as_completed(fs):
            try:
                x=f.result()
                if x:out.append(x)
            except Exception:STATS["errors"]+=1
    out.sort(key=lambda z:(z["ai"],z["agreement"],abs(z["move"]),z["volume_ratio"]),reverse=True)
    out=[x for x in out if x["ai"]>=MIN_AI]
    LAST_SCAN=int(time.time());STATS["deep_scans"]+=len(selected);STATS["signals"]=len(out);STATS["last_scan_ms"]=round((time.time()-started)*1000)
    return {"items":out[:limit],"scanned":len(syms),"candidates":len(selected),"engine":"Mudarib Mega Signal Engine V4","min_ai":MIN_AI,"live_websocket":websocket is not None,"stats":dict(STATS)}

def get_signals(market="spot",frame="15m",limit=120):return scan(market,frame,limit)

def latest_price(symbol,market="spot"):
    with LOCK:
        x=STATE.get(market,{}).get(symbol,{})
        return float(x.get("price",0) or 0)

def start():
    global RUNNING
    if RUNNING:return
    RUNNING=True;_seed();_start_ws()
    def refresh():
        while RUNNING:
            try:_seed()
            except Exception:STATS["errors"]+=1
            time.sleep(900)
    t=threading.Thread(target=refresh,name="mega-v4-symbol-refresh",daemon=True);THREADS.append(t);t.start()

def status():
    with LOCK:return {"running":RUNNING,"engine":"Mudarib Mega Signal Engine V4","websocket":websocket is not None,
        "markets":{k:len(v) for k,v in SYMBOLS.items()},"workers":WORKERS,"min_ai":MIN_AI,"candidates":CANDIDATES,
        "last_scan":LAST_SCAN,"stats":dict(STATS)}
