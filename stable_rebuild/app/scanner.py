import asyncio
from .cache import get_json,set_json
from .market import binance_candles,binance_usdt_symbols,local_signal
from .settings import settings
async def scan_crypto(interval="15m",limit=70):
    key=f"signals:crypto:{interval}"; cached=get_json(key)
    if cached:return cached[:limit]
    symbols=(await binance_usdt_symbols())[:1000]; sem=asyncio.Semaphore(8)
    async def one(s):
        async with sem:
            try:return local_signal(await binance_candles(s,interval),s,"crypto",interval)
            except Exception:return None
    rows=await asyncio.gather(*(one(s) for s in symbols))
    out=sorted([x for x in rows if x and x["tradeReady"]],key=lambda x:x["confidence"],reverse=True)[:settings.max_signals]
    set_json(key,out,120);return out
async def scan_market(market,interval="15m",limit=70):
    if market=="crypto":return await scan_crypto(interval,limit)
    return get_json(f"signals:{market}:{interval}") or []
