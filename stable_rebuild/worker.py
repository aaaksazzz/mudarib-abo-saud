import asyncio,time,logging
from datetime import datetime,timezone
from .db import init_db,connection
from .cache import _client
from .settings import settings
from .scanner import scan_market
from .trades import register_signals
from .market import binance_candles,yahoo_candles

logging.basicConfig(level=logging.INFO);log=logging.getLogger("mudarib-worker")
MARKETS=[("crypto","15m"),("futures","15m"),("contracts","1D"),("saudi","1D"),("usmarket","1D"),("forex","1H")]

async def scan_one(market,interval):
    try:
        rows=await scan_market(market,interval,settings.max_signals);register_signals(rows)
        log.info("scan %s/%s: %s signals",market,interval,len(rows))
    except Exception as exc:log.exception("scan %s failed: %s",market,exc)

async def scan_job():
    await asyncio.gather(*(scan_one(m,i) for m,i in MARKETS))

async def review_job():
    with connection() as c:
        rows=c.execute("""SELECT id,market,interval,symbol,direction,entry,tp1,tp2,tp3,sl
                          FROM signals WHERE status='open' LIMIT 1000""").fetchall()
    async def review(row):
        try:
            candles=await (binance_candles(row["symbol"],row["interval"],5,row["market"]) if row["market"] in ("crypto","futures")
                           else yahoo_candles(row["symbol"],row["interval"]))
            if not candles:return
            hit=None;price=None
            for k in candles:
                hi=float(k["high"]);lo=float(k["low"])
                if row["direction"]=="شراء":
                    if lo<=float(row["sl"]):hit="sl";price=float(row["sl"]);break
                    if hi>=float(row["tp3"]):hit="tp3";price=float(row["tp3"]);break
                    if hi>=float(row["tp2"]):hit="tp2";price=float(row["tp2"]);break
                    if hi>=float(row["tp1"]):hit="tp1";price=float(row["tp1"]);break
                else:
                    if hi>=float(row["sl"]):hit="sl";price=float(row["sl"]);break
                    if lo<=float(row["tp3"]):hit="tp3";price=float(row["tp3"]);break
                    if lo<=float(row["tp2"]):hit="tp2";price=float(row["tp2"]);break
                    if lo<=float(row["tp1"]):hit="tp1";price=float(row["tp1"]);break
            if hit:
                entry=float(row["entry"]);pnl=((price-entry)/entry*100) if row["direction"]=="شراء" else ((entry-price)/entry*100)
                with connection() as c:c.execute("UPDATE signals SET status='closed',result=%s,pnl_percent=%s,resolved_at=NOW() WHERE id=%s AND status='open'",(hit,round(pnl,4),row["id"]))
        except Exception as exc:log.warning("review %s/%s failed: %s",row["market"],row["symbol"],exc)
    await asyncio.gather(*(review(r) for r in rows))

async def main():
    if not settings.database_url:raise RuntimeError("DATABASE_URL غير مضبوط للعامل")
    init_db()
    while True:
        started=time.time()
        await scan_job()
        await review_job()
        try:_client.setex("worker:heartbeat",90,datetime.now(timezone.utc).isoformat())
        except Exception:pass
        elapsed=time.time()-started
        await asyncio.sleep(max(15,settings.scan_interval_seconds-elapsed))

if __name__=="__main__":asyncio.run(main())
