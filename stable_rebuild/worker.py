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

def beat():
    try:_client.setex("worker:heartbeat",60,datetime.now(timezone.utc).isoformat())
    except Exception:pass

async def scan_one(market,interval):
    try:
        rows=await scan_market(market,interval,settings.max_signals)
        register_signals(rows)
        log.info("scan %s/%s: %s signals",market,interval,len(rows))
    except Exception as exc:
        log.exception("scan %s/%s failed: %s",market,interval,exc)

async def scan_loop():
    while True:
        started=time.monotonic()
        await asyncio.gather(*(scan_one(m,i) for m,i in MARKETS))
        beat()
        elapsed=time.monotonic()-started
        await asyncio.sleep(max(5,settings.scan_interval_seconds-elapsed))

async def review_one(row):
    try:
        candles=await (
            binance_candles(row["symbol"],row["interval"],5,row["market"])
            if row["market"] in ("crypto","futures")
            else yahoo_candles(row["symbol"],row["interval"])
        )
        if not candles:return
        # Use the newest candle for fast, bounded review. The signal expiry
        # prevents an old setup from remaining open forever.
        k=candles[-1]
        hi=float(k["high"]);lo=float(k["low"])
        entry=float(row["entry"]);hit=None;price=None
        if row["direction"]=="شراء":
            if lo<=float(row["sl"]):hit="sl";price=float(row["sl"])
            elif hi>=float(row["tp3"]):hit="tp3";price=float(row["tp3"])
            elif hi>=float(row["tp2"]):hit="tp2";price=float(row["tp2"])
            elif hi>=float(row["tp1"]):hit="tp1";price=float(row["tp1"])
        else:
            if hi>=float(row["sl"]):hit="sl";price=float(row["sl"])
            elif lo<=float(row["tp3"]):hit="tp3";price=float(row["tp3"])
            elif lo<=float(row["tp2"]):hit="tp2";price=float(row["tp2"])
            elif lo<=float(row["tp1"]):hit="tp1";price=float(row["tp1"])
        if hit:
            pnl=((price-entry)/entry*100) if row["direction"]=="شراء" else ((entry-price)/entry*100)
            with connection() as c:
                c.execute("UPDATE signals SET status='closed',result=%s,pnl_percent=%s,resolved_at=NOW() WHERE id=%s AND status='open'",(hit,round(pnl,4),row["id"]))
    except Exception as exc:
        log.warning("review %s/%s failed: %s",row["market"],row["symbol"],exc)

async def review_job():
    # Expire stale setups first, then review a bounded batch so one bad cycle
    # can never monopolize the worker.
    with connection() as c:
        c.execute("UPDATE signals SET status='closed',result='expired',resolved_at=NOW() WHERE status='open' AND candle_expires_at IS NOT NULL AND candle_expires_at<=NOW()")
        rows=c.execute("""SELECT id,market,interval,symbol,direction,entry,tp1,tp2,tp3,sl
                          FROM signals WHERE status='open' ORDER BY created_at ASC LIMIT 100""").fetchall()
    sem=asyncio.Semaphore(10)
    async def bounded(row):
        async with sem: await review_one(row)
    await asyncio.gather(*(bounded(r) for r in rows))

async def review_loop():
    interval=max(5,settings.trade_review_seconds)
    while True:
        started=time.monotonic()
        try: await review_job()
        except Exception as exc: log.exception("review cycle failed: %s",exc)
        beat()
        await asyncio.sleep(max(1,interval-(time.monotonic()-started)))

async def heartbeat_loop():
    while True:
        beat()
        await asyncio.sleep(20)

async def init_with_retry():
    for attempt in range(1,6):
        try:
            init_db();return
        except Exception as exc:
            log.exception("database init failed (attempt %s/5): %s",attempt,exc)
            if attempt==5:raise
            await asyncio.sleep(10)

async def main():
    if not settings.database_url:raise RuntimeError("DATABASE_URL غير مضبوط للعامل")
    await init_with_retry()
    await asyncio.gather(scan_loop(),review_loop(),heartbeat_loop())

if __name__=="__main__":asyncio.run(main())
