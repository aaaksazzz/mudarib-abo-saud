import asyncio, httpx
from .settings import settings
BINANCE_INTERVALS={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"4h","1D":"1d","1W":"1w"}
async def binance_candles(symbol,interval,limit=250):
    iv=BINANCE_INTERVALS.get(interval,interval)
    async with httpx.AsyncClient(timeout=12) as c:
        r=await c.get(settings.binance_base_url+"/api/v3/klines",params={"symbol":symbol,"interval":iv,"limit":limit})
        r.raise_for_status()
        return [{"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])} for x in r.json()]
async def binance_usdt_symbols():
    async with httpx.AsyncClient(timeout=15) as c:
        info,tickers=await asyncio.gather(c.get(settings.binance_base_url+"/api/v3/exchangeInfo"),c.get(settings.binance_base_url+"/api/v3/ticker/24hr"))
        info.raise_for_status();tickers.raise_for_status()
        active={x["symbol"] for x in info.json()["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"}
        tv={x["symbol"]:float(x.get("quoteVolume",0) or 0) for x in tickers.json()}
        return sorted((s for s in active if s in tv),key=lambda s:tv[s],reverse=True)
def local_signal(candles,symbol,market="crypto",interval="15m"):
    if len(candles)<25:return None
    last,prev=candles[-1],candles[-2]; entry=float(last["close"]); pc=float(prev["close"] or entry)
    change=((entry/pc)-1)*100 if pc else 0
    direction="شراء" if change>0 else "بيع" if change<0 else "حيادي"; conf=min(99,60+abs(change)*10)
    if direction=="شراء": sl=entry*.99; risk=entry-sl; tps=[entry+risk,entry+2*risk,entry+3*risk]
    elif direction=="بيع": sl=entry*1.01; risk=sl-entry; tps=[entry-risk,entry-2*risk,entry-3*risk]
    else: sl=0;tps=[0,0,0]
    return {"symbol":symbol,"displayName":symbol,"market":market,"interval":interval,"signal":"شراء قوي" if direction=="شراء" and conf>=80 else "بيع قوي" if direction=="بيع" and conf>=80 else direction,"direction":direction,"tradeReady":direction!="حيادي" and conf>=75,"confidence":round(conf,1),"price":entry,"entry":entry,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"rr":3.0,"reason":"تحليل حركة السعر الحالية","change":round(change,2),"volume":float(last.get("volume",0) or 0),"high":float(last["high"]),"low":float(last["low"]),"indicators":{},"ai":True}
