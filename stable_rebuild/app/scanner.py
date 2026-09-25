import asyncio
from .cache import get_json,set_json
from .market import binance_candles,binance_usdt_symbols,yahoo_candles,local_signal
from .settings import settings
STATIC={"saudi":[("2222.SR","أرامكو السعودية"),("1120.SR","الراجحي"),("2010.SR","سابك"),("7010.SR","stc"),("1180.SR","الأهلي السعودي"),("1050.SR","الإنماء"),("1211.SR","معادن"),("2082.SR","أكوا باور"),("2280.SR","المراعي"),("2310.SR","سبكيم"),("2290.SR","ينساب"),("4001.SR","أسواق العثيم"),("4013.SR","سليمان الحبيب"),("4030.SR","البحري"),("4040.SR","جرير")],
"usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("GOOGL","Alphabet"),("TSLA","Tesla"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],
"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("XAUUSD=X","Gold"),("XAGUSD=X","Silver")],
"contracts":[("ES=F","S&P 500 E-mini"),("NQ=F","Nasdaq 100 E-mini"),("YM=F","Dow Jones E-mini"),("RTY=F","Russell 2000 E-mini"),("CL=F","Crude Oil WTI"),("GC=F","Gold Futures"),("SI=F","Silver Futures")]}
async def scan_binance(market,interval,universe_limit=100):
    symbols=(await binance_usdt_symbols(market))[:universe_limit]
    sem=asyncio.Semaphore(8)
    async def one(s):
        async with sem:
            try:return local_signal(await binance_candles(s,interval,250,market),s,market,interval)
            except Exception:return None
    rows=await asyncio.gather(*(one(s) for s in symbols))
    return [x for x in rows if x and x.get("direction") in ("شراء","بيع") and float(x.get("confidence",0))>=70]
async def scan_yahoo(market,interval,universe_limit=100):
    universe=STATIC.get(market,[])[:universe_limit];sem=asyncio.Semaphore(6)
    async def one(item):
        s,n=item
        async with sem:
            try:return local_signal(await yahoo_candles(s,interval),s,market,interval,n)
            except Exception:return None
    rows=await asyncio.gather(*(one(x) for x in universe))
    return [x for x in rows if x and x.get("direction") in ("شراء","بيع") and float(x.get("confidence",0))>=70]
async def scan_market(market,interval="15m",limit=70,universe_limit=100):
    key=f"signals:{market}:{interval}";cached=get_json(key)
    if cached: return cached[:limit]
    rows=await (scan_binance(market,interval,universe_limit) if market in ("crypto","futures") else scan_yahoo(market,interval,universe_limit))
    rows=sorted(rows,key=lambda x:float(x.get("confidence",0)),reverse=True)[:settings.max_signals]
    for x in rows:x["market"]=market;x["interval"]=interval
    set_json(key,rows,120)
    return rows[:limit]
