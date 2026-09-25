import asyncio,httpx,urllib.parse
from .settings import settings
from .strategy import analyze

BINANCE_INTERVALS={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"4h","1D":"1d","1W":"1w"}
_TIMEOUT=httpx.Timeout(connect=4.0,read=8.0,write=4.0,pool=4.0)
_LIMITS=httpx.Limits(max_connections=20,max_keepalive_connections=10)

async def _get(path,params=None):
    async with httpx.AsyncClient(timeout=_TIMEOUT,limits=_LIMITS) as c:
        r=await c.get(settings.binance_base_url+path,params=params);r.raise_for_status();return r.json()

async def binance_candles(symbol,interval,limit=250,market="crypto"):
    endpoint="/api/v3/klines" if market!="futures" else "/fapi/v1/klines"
    data=await _get(endpoint,{"symbol":symbol,"interval":BINANCE_INTERVALS.get(interval,interval),"limit":limit})
    return [{"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])} for x in data]

async def binance_usdt_symbols(market="crypto"):
    endpoint="/api/v3/exchangeInfo" if market!="futures" else "/fapi/v1/exchangeInfo"
    tick="/api/v3/ticker/24hr" if market!="futures" else "/fapi/v1/ticker/24hr"
    info,tickers=await asyncio.gather(_get(endpoint),_get(tick))
    active={x["symbol"] for x in info["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"}
    tv={x["symbol"]:float(x.get("quoteVolume",0) or 0) for x in tickers}
    return sorted((s for s in active if s in tv),key=lambda s:tv[s],reverse=True)

async def yahoo_candles(symbol,interval):
    iv={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d","1W":"1wk"}.get(interval,"1d")
    rg="5d" if iv=="5m" else "1mo" if iv in ("15m","30m") else "1y"
    sym={"XAUUSD=X":"GC=F","XAGUSD=X":"SI=F"}.get(symbol,symbol)
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(sym,safe="")
    async with httpx.AsyncClient(timeout=_TIMEOUT,limits=_LIMITS) as c:
        r=await c.get(url,params={"interval":iv,"range":rg,"includePrePost":"true"});r.raise_for_status()
        z=(r.json().get("chart") or {}).get("result",[None])[0]
        if not z:raise RuntimeError("Yahoo returned no data")
        q=z["indicators"]["quote"][0];out=[]
        for i,t in enumerate(z.get("timestamp",[])):
            try:
                o,h,l,cl=q["open"][i],q["high"][i],q["low"][i],q["close"][i]
                if None in (o,h,l,cl):continue
                out.append({"time":int(t),"open":float(o),"high":float(h),"low":float(l),"close":float(cl),"volume":float((q.get("volume") or [0])[i] or 0)})
            except Exception:pass
        if len(out)<12:raise RuntimeError("Yahoo insufficient candles")
        return out

def local_signal(candles,symbol,market="crypto",interval="15m",name=None):
    return analyze(candles,symbol,market,interval,name)