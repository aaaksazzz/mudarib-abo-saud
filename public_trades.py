"""Public internet-sourced trade ideas, rolling 24h, read-only/paper display only."""
import json, os, sqlite3, threading, time
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter

router = APIRouter()
RETENTION = 86400
CACHE_TTL = 900
MARKETS = ("spot", "futures", "alpha", "contracts", "us", "saudi", "forex", "gold")
LABELS = {"spot":"سبوت","futures":"فيوتشر","contracts":"العقود الأمريكية","us":"الأسهم الأمريكية","saudi":"السوق السعودي","forex":"الفوركس","gold":"الذهب","alpha":"Binance Alpha"}
DATA_DIR = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
CACHE_FILE = os.path.join(DATA_DIR, "public_trades_24h.json")
_lock = threading.Lock()
_refreshing = False
_cache = {"ok": True, "trades": [], "updated": None, "refreshing": False, "markets": {}}
try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    now = time.time()
    _cache["trades"] = [x for x in saved.get("trades", []) if float(x.get("expires_at") or 0) > now and now-float(x.get("created_at") or 0) <= RETENTION]
    _cache["updated"] = saved.get("updated")
except Exception:
    pass

def _stamp(value):
    """Accept RFC 822 news dates and ISO-8601 timestamps from public feeds."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return parsedate_to_datetime(text).timestamp()
    except Exception:
        pass
    try:
        from datetime import datetime
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0

def _last_price(engine, market, symbol, ticker_maps):
    try:
        if market in ("spot", "alpha", "futures"):
            key = "futures" if market == "futures" else "spot"
            return float(ticker_maps.get(key, {}).get(str(symbol).upper(), 0) or 0)
        candles = engine._yahoo(str(symbol), market, "15m", 2)
        return float(candles[-1].get("close") or 0) if candles else 0.0
    except Exception:
        return 0.0

def _prepare(engine, market, raw, ticker_maps):
    title = str(raw.get("source_title") or "").strip()
    body = str(raw.get("source_text") or title).strip()
    url = str(raw.get("source_url") or "").strip()
    published = str(raw.get("source_published") or "")
    published_at = _stamp(published)
    now = time.time()
    if not title or not url or not published_at or published_at > now + 300 or now - published_at > RETENTION:
        return None
    symbol = str(raw.get("symbol") or "").upper().strip()
    direction = str(raw.get("direction") or "").upper().strip()
    if not symbol or direction not in ("BUY", "SELL"): return None
    entry, targets, sl = engine._external_trade_fields(title + " " + body)
    # Do not treat generic market commentary as a precise actionable signal.
    title_direction = engine._direction(title)
    if title_direction and title_direction != direction:
        return None
    actionable = ("entry", "target", "take profit", "stop loss", "price target",
                  "buy signal", "sell signal", "long", "short", "upgrade",
                  "downgrade", "شراء", "بيع", "دخول", "هدف", "وقف الخسارة",
                  "توصية", "إشارة", "السعر المستهدف")
    if not any(term in (title + " " + body).lower() for term in actionable):
        return None
    level_type = "مستويات منشورة بالمصدر"
    price = _last_price(engine, market, symbol, ticker_maps)
    explicit_levels = bool(entry and targets and sl)
    if not entry or not targets or not sl:
        if not price: return None
        entry = float(entry or price)
        risk = abs(entry * 0.01)
        if risk <= 0: return None
        if direction == "BUY":
            sl = float(sl or entry-risk); generated = [entry+risk, entry+2*risk, entry+3*risk]
        else:
            sl = float(sl or entry+risk); generated = [entry-risk, entry-2*risk, entry-3*risk]
        targets = list(targets or [])
        for value in generated:
            if len(targets) >= 3: break
            targets.append(value)
        targets = targets[:3]
        level_type = "مستويات تقديرية محسوبة من السعر العام"
    targets = [float(v) for v in (targets or []) if v is not None]
    if not entry or not sl or float(entry) <= 0 or float(sl) <= 0: return None
    risk = abs(float(entry)-float(sl))
    if risk <= 0: return None
    while len(targets) < 3:
        n = len(targets)+1
        targets.append(float(entry)+(risk*n if direction=="BUY" else -risk*n))
        level_type = "مستويات تقديرية محسوبة من السعر العام"
    targets = targets[:3]
    if direction == "BUY" and not (float(sl) < float(entry) < targets[0] <= targets[1] <= targets[2]): return None
    if direction == "SELL" and not (targets[2] <= targets[1] <= targets[0] < float(entry) < float(sl)): return None
    # Discard published entries that are already materially away from live price.
    # The limits are intentionally wider for crypto than for FX/indices.
    if price and explicit_levels:
        drift = abs(float(price) - float(entry)) / max(float(entry), 1e-12) * 100
        max_drift = 8.0 if market in ("spot", "futures", "alpha") else 3.0 if market in ("forex", "gold", "contracts") else 5.0
        if drift > max_drift:
            return None
    title_upper = title.upper()
    text_lower = (title + " " + body).lower()
    direct_level_score = 35 if explicit_levels else 0
    title_signal_score = 25 if engine._direction(title) == direction else 0
    actionable_score = 20 if any(term in text_lower for term in ("entry", "take profit", "stop loss", "price target", "توصية", "دخول", "هدف", "وقف")) else 10
    source_quality = min(100, direct_level_score + title_signal_score + actionable_score + 20)
    return {"market":market,"market_label":LABELS[market],"symbol":symbol,"direction":direction,"source_quality":source_quality,"live_price":round(float(price),8) if price else None,
        "entry":round(float(entry),8),"tp1":round(targets[0],8),"tp2":round(targets[1],8),"tp3":round(targets[2],8),"sl":round(float(sl),8),
        "source_title":title,"source_url":url,"source_published":published,"created_at":published_at,"expires_at":published_at+RETENTION,
        "level_type":level_type,"is_estimated":level_type!="مستويات منشورة بالمصدر","status":"نشطة","source_count":1,"source_urls":[url]}

def _scan_fallback(engine, market):
    """Multi-timeframe confirmation scan; never promote a single-candle guess as high confidence."""
    if market in ("gold", "alpha"):
        return []
    try:
        if market in ("spot", "futures"):
            # Full Binance USDT universe filtered by >$1M quote volume; rotate batches
            # so low-priced and less-liquid eligible coins are not permanently skipped.
            eligible = [s for s, _ in engine._crypto_universe(market)]
            symbols = engine._rotating_batch(eligible, 32, market)
            print("[UNIVERSE]", market, "eligible quote-volume >1M:", len(eligible), "batch:", len(symbols), flush=True)
        elif market == "us":
            # Discover US-listed stocks with >1M shares traded in the latest session.
            eligible = engine._us_universe(1_000_000)
            symbols = engine._rotating_batch(eligible, 24, market)
            print("[UNIVERSE] us eligible stocks >1M shares:", len(eligible), "batch:", len(symbols), flush=True)
        elif market == "saudi":
            # All Saudi-listed TASI equities across sectors; never apply a daily-volume cutoff.
            eligible = ["TASI"] + engine._saudi_universe(0)
            symbols = engine._rotating_batch(eligible, 24, market)
            print("[UNIVERSE] saudi TASI + all listed equities:", len(eligible), "batch:", len(symbols), flush=True)
        else:
            symbols = list(engine.BASE_UNIVERSE.get(market, []))[:14]
        if not symbols:
            return []

        primary_tf = "1d" if market == "saudi" else "15m"
        confirm_tf = "1w" if market == "saudi" else "1h"
        out = []

        def analyse(sym, tf):
            try:
                result = engine._analyze_symbol(sym, market, tf)
                if isinstance(result, dict) and result.get("side") in ("BUY", "SELL"):
                    return result
            except Exception:
                pass
            return None

        # Keep concurrency bounded for the small production service.
        with ThreadPoolExecutor(max_workers=4) as pool:
            primary_jobs = {pool.submit(analyse, sym, primary_tf): sym for sym in symbols}
            for future in as_completed(primary_jobs):
                sym = primary_jobs[future]
                try:
                    primary = future.result()
                except Exception:
                    primary = None
                if not primary:
                    continue

                primary_score = float(primary.get("ai_pct") or primary.get("recommendation_score") or 0)
                if primary_score < 65:
                    continue
                # Higher-timeframe agreement is mandatory for these candidates.
                try:
                    confirm = analyse(sym, confirm_tf)
                except Exception:
                    confirm = None
                if not confirm or confirm.get("side") != primary.get("side"):
                    continue
                confirm_score = float(confirm.get("ai_pct") or confirm.get("recommendation_score") or 0)
                if confirm_score < 58:
                    continue

                side = str(primary.get("side") or "").upper()
                entry = float(primary.get("entry") or primary.get("price") or 0)
                sl = float(primary.get("sl") or 0)
                raw_targets = primary.get("targets") or [primary.get("tp1"), primary.get("tp2"), primary.get("tp3")]
                try:
                    targets = [float(v) for v in raw_targets if v is not None]
                except Exception:
                    continue
                if side not in ("BUY", "SELL") or entry <= 0 or sl <= 0 or len(targets) < 3:
                    continue
                risk = abs(entry - sl)
                if risk <= 0 or risk / entry > 0.04:
                    continue
                if side == "BUY" and not (sl < entry < targets[0] <= targets[1] <= targets[2]):
                    continue
                if side == "SELL" and not (targets[2] <= targets[1] <= targets[0] < entry < sl):
                    continue

                # This is a confluence score, not a claimed win probability.
                confidence = round(min(96.0, primary_score * 0.65 + confirm_score * 0.35), 1)
                out.append({
                    "market": market, "market_label": LABELS.get(market, market),
                    "symbol": sym, "direction": side,
                    "entry": round(entry, 8), "tp1": round(targets[0], 8),
                    "tp2": round(targets[1], 8), "tp3": round(targets[2], 8),
                    "sl": round(sl, 8), "source_title": "مسح فني متعدد الأطر",
                    "source_url": "", "source_published": None,
                    "created_at": time.time(), "expires_at": time.time() + RETENTION,
                    "level_type": "مستويات محسوبة من بيانات السوق",
                    "is_estimated": True, "status": "نشطة", "source_count": 0,
                    "source_urls": [], "scan_generated": True, "ai_pct": confidence,
                    "timeframe": primary_tf, "confirmation_timeframe": confirm_tf,
                    "primary_score": round(primary_score, 1),
                    "confirmation_score": round(confirm_score, 1),
                    "reason": "توافق إطار " + primary_tf + " مع " + confirm_tf + "؛ الدرجة تقيس توافق الأدلة وليست نسبة ربح مضمونة"
                })
        # Highest multi-timeframe confluence first; tie-break by fresh generation time.
        out.sort(key=lambda x: (float(x.get("ai_pct") or 0), float(x.get("primary_score") or 0), x["created_at"]), reverse=True)
        return out[:12]
    except Exception as exc:
        print("[PUBLIC-TRADES] multi-timeframe scan failed", market, str(exc)[:120], flush=True)
        return []

def _fetch_market(engine, market, ticker_maps):
    try:
        if market == "alpha":
            rows = []
            for query in ("Binance Alpha token buy sell signal today","Binance Alpha token recommendation entry target stop loss"):
                for hit in engine._news(query):
                    full = (str(hit.get("title") or "")+" "+str(hit.get("text") or ""))
                    symbol = engine._symbol(full,"spot")
                    direction = engine._direction(full)
                    if symbol and direction:
                        rows.append({"symbol":symbol,"direction":direction,"source_title":hit.get("title"),"source_text":full,"source_url":hit.get("url"),"source_published":hit.get("published")})
        else:
            rows = engine._internet(market)
        out=[]
        for raw in rows:
            item=_prepare(engine,market,raw,ticker_maps)
            if item: out.append(item)
        # External recommendations stay first. If the source feed is sparse, add a
        # small separately labeled technical scan so the market page is not empty.
        if len(out)<3:
            existing={(x["symbol"],x["direction"]) for x in out}
            for x in _scan_fallback(engine,market):
                key=(x["symbol"],x["direction"])
                if key not in existing:
                    out.append(x); existing.add(key)
                if len(out)>=12: break
        return market,out
    except Exception as exc:
        print("[PUBLIC-TRADES] source failed",market,str(exc)[:120],flush=True)
        return market,[]

def _build():
    import research_engine as engine
    ticker_maps={}
    for market,futures in (("spot",False),("futures",True)):
        try:
            ticker_maps[market]={str(x.get("symbol") or "").upper():float(x.get("lastPrice") or x.get("price") or 0) for x in engine._binance24(futures)}
        except Exception: ticker_maps[market]={}
    combined=[]; counts={}
    # Bound concurrent source scans to protect the small web service.
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(_fetch_market,engine,m,ticker_maps) for m in MARKETS]
        for job in as_completed(jobs):
            market,rows=job.result(); counts[market]=len(rows); combined.extend(rows)
    merged={}
    for row in sorted(combined,key=lambda x:x["created_at"],reverse=True):
        key=(row["market"],row["symbol"],row["direction"],bool(row.get("scan_generated")))
        if key not in merged: merged[key]=row
        else:
            old=merged[key]
            if row["source_url"] and row["source_url"] not in old["source_urls"]:
                old["source_urls"].append(row["source_url"]); old["source_count"]=len(old["source_urls"])
    now=time.time()
    # Keep one unambiguous direction per asset and market. Prefer a real external
    # recommendation over a generated scan, then source agreement, confidence, and freshness.
    best_by_asset={}
    for row in merged.values():
        if float(row.get("expires_at") or 0) <= now:
            continue
        key=(row["market"],row["symbol"])
        quality=(0 if row.get("scan_generated") else 1,
                 int(row.get("source_quality") or 0),
                 int(row.get("source_count") or 0),
                 float(row.get("ai_pct") or 0),
                 float(row.get("created_at") or 0))
        previous=best_by_asset.get(key)
        if previous is None or quality>(0 if previous.get("scan_generated") else 1,
                                         int(previous.get("source_quality") or 0),
                                         int(previous.get("source_count") or 0),
                                         float(previous.get("ai_pct") or 0),
                                         float(previous.get("created_at") or 0)):
            best_by_asset[key]=row
    # Balance the feed so busy markets cannot crowd out quieter markets.
    rows=[]
    for market in MARKETS:
        market_rows=sorted((x for x in best_by_asset.values() if x["market"]==market),key=lambda x:(0 if x.get("scan_generated") else 1,int(x.get("source_quality") or 0),x["source_count"],float(x.get("ai_pct") or 0),x["created_at"]),reverse=True)
        rows.extend(market_rows[:100])
    rows=sorted(rows,key=lambda x:(x["created_at"],x["source_count"]),reverse=True)[:700]
    payload={"ok":True,"trades":rows,"updated":now,"refreshing":False,"markets":counts}
    try:
        with open(CACHE_FILE+".tmp","w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,separators=(",",":"))
        os.replace(CACHE_FILE+".tmp",CACHE_FILE)
    except Exception as exc: print("[PUBLIC-TRADES] cache save failed",str(exc)[:120],flush=True)
    return payload

def _worker():
    global _refreshing,_cache
    try:
        payload=_build()
        with _lock: _cache=payload
    except Exception as exc: print("[PUBLIC-TRADES] refresh failed",str(exc)[:160],flush=True)
    finally:
        with _lock: _refreshing=False

@router.get("/api/public-trades")
def public_trades(refresh: int = 0, market: str = "all", hours: int = 48):
    global _refreshing,_cache
    now=time.time()
    with _lock:
        _cache["trades"]=[x for x in _cache.get("trades",[]) if float(x.get("expires_at") or 0)>now and now-float(x.get("created_at") or 0)<=RETENTION]
        stale=not _cache.get("updated") or now-float(_cache.get("updated") or 0)>=CACHE_TTL
        if not _refreshing and (refresh==1 or stale):
            _refreshing=True
            threading.Thread(target=_worker,daemon=True,name="public-trades-24h").start()
        try: hours=int(hours)
        except Exception: hours=48
        if hours not in (12,24,48): hours=48
        if market not in ("all",)+MARKETS: market="all"
        cutoff=now-hours*3600
        # Admin switches affect both individual market pages and the all-markets feed.
        enabled={m:True for m in MARKETS}
        try:
            from app import DB_PATH
            con=sqlite3.connect(DB_PATH,timeout=2)
            for key,value in con.execute("SELECT key,enabled FROM section_access").fetchall():
                if key in enabled: enabled[key]=bool(value)
            con.close()
        except Exception:
            pass
        if market=="gold": market="forex"
        def market_enabled(row):
            key=str(row.get("market") or "")
            if key=="gold": key="forex"
            return enabled.get(key,True)
        filtered=[x for x in _cache["trades"] if float(x.get("created_at") or 0)>=cutoff and market_enabled(x) and (market=="all" or x.get("market")==market or (market=="forex" and x.get("market")=="gold"))]
        result=dict(_cache); result["trades"]=filtered; result["refreshing"]=_refreshing
        result["selected_market"]=market; result["window_hours"]=hours
        result["market_counts"]={m:sum(1 for x in _cache["trades"] if x.get("market")==m and market_enabled(x) and float(x.get("created_at") or 0)>=cutoff) for m in MARKETS}
        result["remaining_seconds"]=max(0,int(CACHE_TTL-(now-float(_cache.get("updated") or 0))))
        return result
