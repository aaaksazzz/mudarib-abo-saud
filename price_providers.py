import time, requests, threading, csv, io

_LOCK=threading.RLock()
_HEALTH={}
_HEALTH_TTL=20
_HEADERS={"User-Agent":"SMART-TRADING-PRO/1.0"}

def _ok(name):
    now=time.time()
    with _LOCK:
        return now-_HEALTH.get(name,0)>=_HEALTH_TTL

def _mark(name,good):
    if good: return
    with _LOCK: _HEALTH[name]=time.time()

def _get(name,url,params=None,timeout=2):
    if not _ok(name): return None
    try:
        r=requests.get(url,params=params,timeout=timeout,headers=_HEADERS)
        if r.ok:
            return r
    except Exception:
        pass
    _mark(name,False)
    return None

def _num(v):
    try:
        x=float(v)
        return x if x>0 else 0
    except Exception: return 0

def crypto_price(sym,market):
    s=str(sym).upper().replace("/","").replace("-","").replace("_","")
    if market=="spot":
        providers=[
            ("binance", "https://api.binance.com/api/v3/ticker/price", {"symbol":s}),
            ("binance1","https://api1.binance.com/api/v3/ticker/price", {"symbol":s}),
            ("okx", "https://www.okx.com/api/v5/market/ticker", {"instId":s[:-4]+"-USDT" if s.endswith("USDT") else s}),
            ("bybit","https://api.bybit.com/v5/market/tickers", {"category":"spot","symbol":s}),
        ]
    else:
        providers=[
            ("binance_f","https://fapi.binance.com/fapi/v1/ticker/price", {"symbol":s}),
            ("binance_f1","https://fapi1.binance.com/fapi/v1/ticker/price", {"symbol":s}),
            ("okx_f","https://www.okx.com/api/v5/market/ticker", {"instId":s[:-4]+"-USDT-SWAP" if s.endswith("USDT") else s}),
            ("bybit_f","https://api.bybit.com/v5/market/tickers", {"category":"linear","symbol":s}),
        ]
    for name,url,p in providers:
        r=_get(name,url,p,1.8)
        if not r: continue
        try:
            j=r.json()
            if name.startswith("okx"):
                arr=(j.get("data") or [])
                v=_num(arr[0].get("last")) if arr else 0
            elif name.startswith("bybit"):
                arr=(j.get("result",{}).get("list") or [])
                v=_num(arr[0].get("lastPrice")) if arr else 0
            else:
                v=_num(j.get("price"))
            if v: return v,name
        except Exception: continue
    return 0,None

def _binance_klines(sym,market,tf,n):
    base=("https://fapi.binance.com/fapi/v1/klines" if market=="futures" else "https://api.binance.com/api/v3/klines")
    alt=("https://fapi1.binance.com/fapi/v1/klines" if market=="futures" else "https://api1.binance.com/api/v3/klines")
    for name,url in (("binance_k",base),("binance_k1",alt)):
        r=_get(name,url,{"symbol":sym,"interval":tf,"limit":n},5)
        if r:
            try:
                d=r.json()
                if isinstance(d,list) and len(d)>=20: return d,name
            except Exception: pass
    return None,None

def _okx_klines(sym,market,tf,n):
    bar={"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1H","4h":"4H","1d":"1D","1w":"1W","1M":"1M"}.get(tf,tf)
    inst=sym[:-4]+"-USDT"+("-SWAP" if market=="futures" else "")
    r=_get("okx_k", "https://www.okx.com/api/v5/market/candles",
           {"instId":inst,"bar":bar,"limit":str(min(n,300))},5)
    if not r:return None,None
    try:
        rows=[]
        for x in reversed(r.json().get("data") or []):
            if len(x)>=6:
                rows.append([int(float(x[0])),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])])
        return (rows if len(rows)>=20 else None),"okx_k"
    except Exception:return None,None

def _bybit_klines(sym,market,tf,n):
    interval={"1m":"1","5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","1d":"D","1w":"W","1M":"M"}.get(tf,tf)
    r=_get("bybit_k","https://api.bybit.com/v5/market/kline",
           {"category":"linear" if market=="futures" else "spot","symbol":sym,"interval":interval,"limit":str(min(n,200))},5)
    if not r:return None,None
    try:
        rows=[]
        for x in reversed(r.json().get("result",{}).get("list") or []):
            rows.append([int(float(x[0])),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])])
        return (rows if len(rows)>=20 else None),"bybit_k"
    except Exception:return None,None

def crypto_klines(sym,market,tf,n):
    for fn in (_binance_klines,_okx_klines,_bybit_klines):
        d,p=fn(sym,market,tf,n)
        if d:return d,p
    return [],None

def _yahoo_symbols(sym,market):
    s=str(sym)
    if market=="saudi": return [s+".SR" if s.isdigit() else s]
    if market=="forex" and s=="XAUUSD=X": return ["XAUUSD=X","GC=F"]
    return [s]

def _yahoo_klines(sym,market,tf,n):
    interval=tf
    for ysym in _yahoo_symbols(sym,market):
        for host,name in (("query1.finance.yahoo.com","yahoo1"),("query2.finance.yahoo.com","yahoo2")):
            r=_get(name,"https://"+host+"/v8/finance/chart/"+ysym,
                   {"range":"10d","interval":interval,"includePrePost":"false"},8)
            if not r: continue
            try:
                j=r.json().get("chart",{})
                result=(j.get("result") or [])
                if not result: continue
                q=(result[0].get("indicators",{}).get("quote") or [{}])[0]
                ts=result[0].get("timestamp") or []
                rows=[]
                for i,t in enumerate(ts):
                    opens=q.get("open") or []; highs=q.get("high") or []; lows=q.get("low") or []; closes=q.get("close") or []; volumes=q.get("volume") or []
                    if i>=len(opens) or i>=len(highs) or i>=len(lows) or i>=len(closes): continue
                    o,h,l,c=opens[i],highs[i],lows[i],closes[i]
                    v=volumes[i] if i<len(volumes) and volumes[i] is not None else 0
                    if None not in (o,h,l,c): rows.append([t,o,h,l,c,v or 0])
                if len(rows)>=20:return rows[-n:],"yahoo"
            except Exception: continue
    return None,None

def _stooq_klines(sym,market,tf,n):
    # Stooq is a daily/intraday fallback for listed assets where supported.
    raw=str(sym).upper()
    if market=="us": s=raw.lower()+".us"
    elif market=="saudi": s=(raw.lower()+".sa") if raw.isdigit() else raw.lower()
    elif market=="forex": s={"XAUUSD=X":"xauusd","EURUSD=X":"eurusd","GBPUSD=X":"gbpusd","USDJPY=X":"usdjpy","AUDUSD=X":"audusd","USDCHF=X":"usdchf","USDCAD=X":"usdcad","NZDUSD=X":"nzdusd"}.get(raw,raw.lower())
    else: s={"GC=F":"gc.f","CL=F":"cl.f","SI=F":"si.f","NG=F":"ng.f","ES=F":"es.f","NQ=F":"nq.f","YM=F":"ym.f","RTY=F":"rty.f"}.get(raw,raw.lower())
    r=_get("stooq_k","https://stooq.com/q/d/l/",{"s":s,"i":"d"},5)
    if not r:return None,None
    try:
        rows=[]
        for row in csv.DictReader(io.StringIO(r.text)):
            rows.append([int(time.mktime(time.strptime(row.get("Date",""),"%Y-%m-%d"))),float(row["Open"]),float(row["High"]),float(row["Low"]),float(row["Close"]),_num(row.get("Volume",0))])
        return (rows[-n:] if len(rows)>=20 else None),"stooq"
    except Exception:return None,None

def noncrypto_klines(sym,market,tf,n):
    for fn in (_yahoo_klines,_stooq_klines):
        d,p=fn(sym,market,tf,n)
        if d:return d,p
    return [],None

def market_klines(sym,market,tf,n):
    return crypto_klines(sym,market,tf,n) if market in ("spot","futures") else noncrypto_klines(sym,market,tf,n)

def _crypto_universe_binance(market):
    urls=(("https://api.binance.com/api/v3/ticker/24hr","binance_u"),
          ("https://api1.binance.com/api/v3/ticker/24hr","binance_u1")) if market=="spot" else (("https://fapi.binance.com/fapi/v1/ticker/24hr","binance_fu"),("https://fapi1.binance.com/fapi/v1/ticker/24hr","binance_fu1"))
    for name,url in urls:
        r=_get(name,url,timeout=8)
        if not r:continue
        try:
            d=r.json()
            if isinstance(d,list) and d:return d,name
        except Exception:pass
    return None,None

def _crypto_universe_okx(market):
    instType="SWAP" if market=="futures" else "SPOT"
    r=_get("okx_u","https://www.okx.com/api/v5/public/instruments",{"instType":instType},8)
    if not r:return None,None
    try:
        out=[]
        for x in r.json().get("data") or []:
            if x.get("quoteCcy")=="USDT" and x.get("state")=="live":
                inst=str(x.get("instId","")).upper()
                sym=inst.replace("-USDT-SWAP","USDT").replace("-USDT","USDT")
                out.append({"symbol":sym,"quoteAsset":"USDT","quoteVolume":0})
        return (out if out else None),"okx_u"
    except Exception:return None,None

def _crypto_universe_bybit(market):
    r=_get("bybit_u","https://api.bybit.com/v5/market/instruments-info",
           {"category":"linear" if market=="futures" else "spot","limit":"1000"},8)
    if not r:return None,None
    try:
        out=[]
        for x in r.json().get("result",{}).get("list") or []:
            if x.get("quoteCoin")=="USDT" and x.get("status") in ("Trading","1"):
                out.append({"symbol":x.get("symbol"),"quoteAsset":"USDT","quoteVolume":0})
        return (out if out else None),"bybit_u"
    except Exception:return None,None

def crypto_universe(market):
    for fn in (_crypto_universe_binance,_crypto_universe_okx,_crypto_universe_bybit):
        d,p=fn(market)
        if d:return d,p
    return [],None

def provider_status():
    with _LOCK:
        return {"unhealthy_until":dict(_HEALTH),"ttl":_HEALTH_TTL}
