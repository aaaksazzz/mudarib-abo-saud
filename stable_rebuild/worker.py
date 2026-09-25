import asyncio,time,logging
from datetime import datetime,timezone
from .db import init_db,connection
from .cache import _client
from .settings import settings
from .scanner import scan_market
from .trades import register_signals
from .market import binance_candles,yahoo_candles

logging.basicConfig(level=logging.INFO);log=logging.getLogger("mudarib-worker")
MARKETS=[("crypto","15m"),("futures","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]

NEWS_FEEDS = [
    ("العملات الرقمية", "https://news.google.com/rss/search?q=cryptocurrency%20bitcoin%20crypto%20when%3A1d&hl=ar&gl=SA&ceid=SA%3Aar"),
    ("الأسواق العالمية", "https://news.google.com/rss/search?q=stock%20market%20markets%20when%3A1d&hl=ar&gl=SA&ceid=SA%3Aar"),
    ("الاقتصاد", "https://news.google.com/rss/search?q=economy%20inflation%20interest%20rates%20when%3A1d&hl=ar&gl=SA&ceid=SA%3Aar"),
    ("النفط والذهب", "https://news.google.com/rss/search?q=oil%20gold%20markets%20when%3A1d&hl=ar&gl=SA&ceid=SA%3Aar"),
    ("السوق السعودي", "https://news.google.com/rss/search?q=السوق%20السعودي%20تداول%20when%3A1d&hl=ar&gl=SA&ceid=SA%3Aar"),
]
NEWS_REFRESH_SECONDS = 600

async def refresh_news():
    """Fetch public RSS headlines without blocking the worker or the homepage."""
    import hashlib, html as html_lib, re, xml.etree.ElementTree as ET
    import httpx
    from email.utils import parsedate_to_datetime

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=True,
        headers={"User-Agent": "MudaribAboSaud/1.0 news-reader"},
    ) as client:
        for category, url in NEWS_FEEDS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                with connection() as c:
                    for item in items[:25]:
                        title = (item.findtext("title") or "").strip()
                        link = (item.findtext("link") or "").strip()
                        description = (item.findtext("description") or "").strip()
                        pub = (item.findtext("pubDate") or "").strip()
                        source_el = item.find("source")
                        source = (source_el.text if source_el is not None else "") or "مصادر إخبارية عامة"
                        title = html_lib.unescape(re.sub(r"<[^>]+>", " ", title)).strip()
                        description = html_lib.unescape(re.sub(r"<[^>]+>", " ", description)).strip()
                        description = re.sub(r"\s+", " ", description)[:500]
                        if not title or not link:
                            continue
                        slug = "news-" + hashlib.sha1(link.encode("utf-8")).hexdigest()[:24]
                        published = None
                        if pub:
                            try: published = parsedate_to_datetime(pub)
                            except Exception: published = None
                        c.execute(
                            """INSERT INTO news(slug,title,content,description,source,category,link,published_at)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,NOW()))
                               ON CONFLICT(slug) DO UPDATE SET
                               title=EXCLUDED.title,description=EXCLUDED.description,source=EXCLUDED.source,
                               category=EXCLUDED.category,link=EXCLUDED.link,published_at=EXCLUDED.published_at""",
                            (slug,title,description,description,source,category,link,published),
                        )
                log.info("news refresh %s: %s items", category, min(len(items),25))
            except Exception as exc:
                log.warning("news feed failed (%s): %s", category, exc)

    # Keep the table small and fast for the homepage.
    try:
        with connection() as c:
            c.execute("""DELETE FROM news
                        WHERE id NOT IN (SELECT id FROM news ORDER BY published_at DESC, id DESC LIMIT 200)""")
    except Exception as exc:
        log.warning("news cleanup failed: %s", exc)

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

async def news_loop():
    while True:
        started=time.monotonic()
        try: await refresh_news()
        except Exception as exc: log.exception("news refresh failed: %s",exc)
        await asyncio.sleep(max(60, NEWS_REFRESH_SECONDS-(time.monotonic()-started)))

async def scan_loop():
    # Limit upstream/API concurrency so temporary rate limits do not take
    # down the whole scan cycle.
    sem=asyncio.Semaphore(2)
    async def bounded(market,interval):
        async with sem:
            await scan_one(market,interval)
    while True:
        started=time.monotonic()
        await asyncio.gather(*(bounded(m,i) for m,i in MARKETS))
        beat()
        elapsed=time.monotonic()-started
        await asyncio.sleep(max(5,settings.scan_interval_seconds-elapsed))

async def review_one(row):
    try:
        candles=await (
            binance_candles(row["symbol"],row["interval"],6,row["market"])
            if row["market"] in ("crypto","futures")
            else yahoo_candles(row["symbol"],row["interval"])
        )
        if not candles:return
        entry=float(row["entry"]);created=row.get("created_at")
        created_ts=created.timestamp() if created else 0
        hit=None;price=None
        # Review every candle that could have appeared since the signal was created.
        # This avoids missing a TP/SL hit when the worker/API was briefly unavailable.
        for k in candles:
            if int(k.get("time",0)) and int(k["time"]) < int(created_ts):
                continue
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
        rows=c.execute("""SELECT id,market,interval,symbol,direction,entry,tp1,tp2,tp3,sl,created_at
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
    # Never terminate the worker because PostgreSQL was briefly unavailable.
    # Retry with bounded backoff until the database is reachable.
    attempt=0
    while True:
        attempt+=1
        try:
            init_db();return
        except Exception as exc:
            delay=min(60,5*attempt)
            log.exception("database init failed (attempt %s); retrying in %ss: %s",attempt,delay,exc)
            await asyncio.sleep(delay)

async def main():
    if not settings.database_url:raise RuntimeError("DATABASE_URL غير مضبوط للعامل")
    await init_with_retry()
    await asyncio.gather(scan_loop(),review_loop(),heartbeat_loop())

if __name__=="__main__":asyncio.run(main())
