import asyncio,time,logging
from datetime import datetime,timezone
from .db import init_db,connection
from .cache import _client
from .settings import settings
from .scanner import scan_market
from .trades import register_signals
from .market import binance_candles

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("mudarib-worker")

async def scan_job():
    rows=await scan_market("crypto","15m",settings.max_signals)
    register_signals(rows)
    log.info("scan: %s signals",len(rows))

async def review_job():
    with connection() as c:
        rows=c.execute("SELECT id,symbol,direction,entry,tp1,tp2,tp3,sl FROM signals WHERE status='open' AND market='crypto' LIMIT 500").fetchall()
    for row in rows:
        try:
            candles=await binance_candles(row["symbol"],"15m",80)
            hit=None;price=None
            for k in candles:
                if row["direction"]=="شراء":
                    if float(k["low"])<=float(row["sl"]): hit="sl";price=float(row["sl"]);break
                    if float(k["high"])>=float(row["tp3"]): hit="tp3";price=float(row["tp3"]);break
                    if float(k["high"])>=float(row["tp2"]): hit="tp2";price=float(row["tp2"]);break
                    if float(k["high"])>=float(row["tp1"]): hit="tp1";price=float(row["tp1"]);break
                else:
                    if float(k["high"])>=float(row["sl"]): hit="sl";price=float(row["sl"]);break
                    if float(k["low"])<=float(row["tp3"]): hit="tp3";price=float(row["tp3"]);break
                    if float(k["low"])<=float(row["tp2"]): hit="tp2";price=float(row["tp2"]);break
                    if float(k["low"])<=float(row["tp1"]): hit="tp1";price=float(row["tp1"]);break
            if hit:
                entry=float(row["entry"])
                pnl=((price-entry)/entry*100) if row["direction"]=="شراء" else ((entry-price)/entry*100)
                with connection() as c:
                    c.execute("UPDATE signals SET status='closed',result=%s,pnl_percent=%s,resolved_at=NOW() WHERE id=%s AND status='open'",(hit,round(pnl,4),row["id"]))
        except Exception as exc:
            log.warning("review %s failed: %s",row["symbol"],exc)

async def main():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL غير مضبوط للعامل")
    init_db()
    while True:
        started=time.time()
        try:
            await scan_job()
        except Exception as exc: log.exception("scan failed: %s",exc)
        try:
            await review_job()
        except Exception as exc: log.exception("review failed: %s",exc)
        try:_client.setex("worker:heartbeat",90,datetime.now(timezone.utc).isoformat())
        except Exception:pass
        await asyncio.sleep(max(15,settings.scan_interval_seconds-(time.time()-started)))

if __name__=="__main__":asyncio.run(main())
