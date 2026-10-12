"""Public internet-sourced trade ideas, rolling 24h, read-only/paper display only."""
import json, os, sqlite3, threading, time
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter

router = APIRouter()
RETENTION = 172800
CACHE_TTL = 300
MARKETS = ("spot", "futures", "alpha", "contracts", "us", "saudi", "forex", "gold")
LABELS = {"spot":"سبوت","futures":"فيوتشر","contracts":"العقود الأمريكية","us":"الأسهم الأمريكية","saudi":"السوق السعودي","forex":"الفوركس","gold":"الذهب","alpha":"Binance Alpha"}
DATA_DIR = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
CACHE_FILE = os.path.join(DATA_DIR, "public_trades_24h.json")
_lock = threading.Lock()
_refreshing = False
_cache = {"ok": True, "trades": [], "updated": None, "refreshing": False, "markets": {}, "market_updated": {}}
try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    now = time.time()
    _cache["trades"] = [x for x in saved.get("trades", []) if float(x.get("expires_at") or 0) > now and now-float(x.get("created_at") or 0) <= RETENTION and (not x.get("scan_generated") or x.get("market")=="alpha")]
    _cache["updated"] = saved.get("updated")
    _cache["markets"] = saved.get("markets", {})
    _cache["market_updated"] = saved.get("market_updated", {})
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

def _prepare(engine, market, raw, ticker_maps, retention=86400):
    title = str(raw.get("source_title") or "").strip()
    body = str(raw.get("source_text") or title).strip()
    url = str(raw.get("source_url") or "").strip()
    published = str(raw.get("source_published") or "")
    published_at = _stamp(published)
    now = time.time()
    if not title or not url or not published_at or published_at > now + 300 or now - published_at > retention:
        return None
    symbol = str(raw.get("symbol") or "").upper().strip()
    direction = str(raw.get("direction") or "").upper().strip()
    if not symbol or direction not in ("BUY", "SELL"): return None
    # Crypto recommendations must match the actual exchange universe for that market.
    # This blocks stocks/ETFs/commodities mislabeled as synthetic *USDT futures pairs.
    if market in ("spot", "futures"):
        available = ticker_maps.get(market, {})
        if not available or symbol not in available:
            return None
    entry, targets, sl = engine._external_trade_fields(title + " " + body)
    # Do not treat generic market commentary as a precise actionable signal.
    title_direction = engine._direction(title)
    if title_direction and title_direction != direction:
        return None
    actionable = ("entry", "target", "take profit", "stop loss", "price target",
                  "target price", "price prediction", "forecast", "outlook",
                  "analyst", "buy recommendation", "sell recommendation",
                  "buy rating", "sell rating", "bullish", "bearish",
                  "buy signal", "sell signal", "long", "short", "upgrade",
                  "downgrade", "شراء", "بيع", "دخول", "هدف", "وقف الخسارة",
                  "توصية", "إشارة", "توقعات", "نظرة", "السعر المستهدف")
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
        "source_title":title,"source_url":url,"source_published":published,"created_at":published_at,"expires_at":published_at+retention,
        "level_type":level_type,"is_estimated":level_type!="مستويات منشورة بالمصدر","status":"نشطة","source_count":1,"mention_count":1,"source_domains_count":1,"source_domains":[urlparse(url).netloc.lower().removeprefix("www.")],"source_urls":[url], "risk_pct":round(abs(float(entry)-float(sl))/float(entry)*100,2), "tp1_pct":round(((targets[0]-float(entry)) if direction=="BUY" else (float(entry)-targets[0]))/float(entry)*100,2), "tp2_pct":round(((targets[1]-float(entry)) if direction=="BUY" else (float(entry)-targets[1]))/float(entry)*100,2), "tp3_pct":round(((targets[2]-float(entry)) if direction=="BUY" else (float(entry)-targets[2]))/float(entry)*100,2)}

def _fetch_market(engine, market, ticker_maps, retention=86400):
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
            item=_prepare(engine,market,raw,ticker_maps,retention)
            if item: out.append(item)
        if market=="alpha":
            # Supplement sparse external mentions with clearly labelled signals from real Binance Alpha candles.
            # These are technical scans, not claims that an analyst published the recommendation.
            try:
                scanned=engine._public_scan("alpha",[],"15m")
                now=time.time()
                for raw in scanned[:48]:
                    symbol=str(raw.get("symbol") or "").upper()
                    side=str(raw.get("direction") or raw.get("side") or "").upper()
                    try:
                        entry=float(raw.get("entry") or 0); sl=float(raw.get("sl") or 0)
                        targets=[float(raw.get(k) or 0) for k in ("tp1","tp2","tp3")]
                        candles=engine._alpha_klines(symbol,"15m",2)
                        live=float(candles[-1].get("close") or 0) if candles else 0
                    except Exception:
                        continue
                    if side not in ("BUY","SELL") or entry<=0 or sl<=0 or live<=0 or len(targets)!=3 or any(x<=0 for x in targets):
                        continue
                    if side=="BUY" and not (sl<entry<targets[0]<targets[1]<targets[2]): continue
                    if side=="SELL" and not (sl>entry>targets[0]>targets[1]>targets[2]): continue
                    out.append({
                        "market":"alpha","market_label":LABELS["alpha"],"symbol":symbol,"direction":side,
                        "live_price":round(live,10),"entry":round(entry,10),"tp1":round(targets[0],10),
                        "tp2":round(targets[1],10),"tp3":round(targets[2],10),"sl":round(sl,10),
                        "source_title":"مسح فني مباشر من شموع Binance Alpha","source_url":"https://www.binance.com/en/alpha",
                        "source_published":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime(now)),
                        "created_at":now,"expires_at":now+retention,"level_type":"مستويات محسوبة من الشموع الحقيقية",
                        "is_estimated":True,"status":"نشطة","source_count":0,"mention_count":0,
                        "source_domains_count":0,"source_domains":[],"source_urls":[],
                        "risk_pct":round(abs(entry-sl)/entry*100,2),
                        "tp1_pct":round(((targets[0]-entry) if side=="BUY" else (entry-targets[0]))/entry*100,2),
                        "tp2_pct":round(((targets[1]-entry) if side=="BUY" else (entry-targets[1]))/entry*100,2),
                        "tp3_pct":round(((targets[2]-entry) if side=="BUY" else (entry-targets[2]))/entry*100,2),
                        "recommendation_score":float(raw.get("recommendation_score") or raw.get("ai_pct") or 0),
                        "ai_pct":float(raw.get("ai_pct") or raw.get("recommendation_score") or 0),
                        "timeframe":"15m","scan_generated":True
                    })
            except Exception as exc:
                print("[PUBLIC-TRADES] Alpha candle scan failed",str(exc)[:140],flush=True)
        return market,out
    except Exception as exc:
        print("[PUBLIC-TRADES] source failed",market,str(exc)[:120],flush=True)
        return market,[]

def _build(only_market=None, hours=24):
    retention=max(1,int(hours))*3600
    import research_engine as engine
    if only_market in (None, "", "all"):
        scan_markets=list(MARKETS)
    elif only_market in ("forex", "gold"):
        scan_markets=[only_market]
    elif only_market in MARKETS:
        scan_markets=[only_market]
    else:
        scan_markets=list(MARKETS)
    ticker_maps={}
    for market,futures in (("spot",False),("futures",True)):
        if market not in scan_markets and not (market=="spot" and "alpha" in scan_markets): continue
        try:
            ticker_maps[market]={str(x.get("symbol") or "").upper():float(x.get("lastPrice") or x.get("price") or 0) for x in engine._binance24(futures)}
        except Exception: ticker_maps[market]={}
    combined=[]; counts={}
    # Bound concurrent source scans to protect the small web service.
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(_fetch_market,engine,m,ticker_maps,retention) for m in scan_markets]
        for job in as_completed(jobs):
            market,rows=job.result(); counts[market]=len(rows); combined.extend(rows)
    merged={}
    for row in sorted(combined,key=lambda x:x["created_at"],reverse=True):
        key=(row["market"],row["symbol"],row["direction"],bool(row.get("scan_generated")))
        if key not in merged: merged[key]=row
        else:
            old=merged[key]
            if row["source_url"] and row["source_url"] not in old["source_urls"]:
                old["source_urls"].append(row["source_url"])
                old["source_count"]=len(old["source_urls"])
                old["mention_count"]=old["source_count"]
                domain=urlparse(row["source_url"]).netloc.lower().removeprefix("www.")
                domains=old.setdefault("source_domains",[])
                if domain and domain not in domains: domains.append(domain)
                old["source_domains_count"]=len(domains)
    now=time.time()
    # Keep one unambiguous direction per asset and market. Prefer a real external
    # recommendation over a generated scan, then source agreement, confidence, and freshness.
    best_by_asset={}
    for row in merged.values():
        if float(row.get("expires_at") or 0) <= now:
            continue
        key=(row["market"],row["symbol"])
        row["mention_count"]=max(int(row.get("mention_count") or 0),int(row.get("source_count") or 0))
        row["source_domains_count"]=max(int(row.get("source_domains_count") or 0),len(row.get("source_domains") or []))
        row["rank_score"]=round(min(100,(float(row.get("source_quality") or row.get("ai_pct") or 45)*0.55)+min(10,int(row["mention_count"]))*3.0+min(8,int(row["source_domains_count"]))*2.5),1)
        quality=(0 if row.get("scan_generated") else 1,
                 int(row.get("mention_count") or 0),
                 int(row.get("source_domains_count") or 0),
                 int(row.get("source_quality") or 0),
                 float(row.get("ai_pct") or 0),
                 float(row.get("created_at") or 0))
        previous=best_by_asset.get(key)
        if previous is None or quality>(0 if previous.get("scan_generated") else 1,
                                         int(previous.get("mention_count") or previous.get("source_count") or 0),
                                         int(previous.get("source_domains_count") or 0),
                                         int(previous.get("source_quality") or 0),
                                         float(previous.get("ai_pct") or 0),
                                         float(previous.get("created_at") or 0)):
            best_by_asset[key]=row
    # Balance the feed so busy markets cannot crowd out quieter markets.
    rows=[]
    for market in MARKETS:
        market_rows=sorted((x for x in best_by_asset.values() if x["market"]==market),key=lambda x:(0 if x.get("scan_generated") else 1,int(x.get("mention_count") or x.get("source_count") or 0),int(x.get("source_domains_count") or 0),float(x.get("rank_score") or x.get("source_quality") or 0),x["created_at"]),reverse=True)
        rows.extend(market_rows[:100])
    rows=sorted(rows,key=lambda x:(x["created_at"],x["source_count"]),reverse=True)[:700]
    market_updated={}
    market_counts={}
    if only_market not in (None, "", "all"):
        with _lock:
            previous_trades=list(_cache.get("trades",[]))
            market_updated=dict(_cache.get("market_updated",{}))
            market_counts=dict(_cache.get("markets",{}))
        scanned=set(scan_markets)
        rows=[x for x in previous_trades if x.get("market") not in scanned and float(x.get("expires_at") or 0)>now and not x.get("scan_generated")]+rows
    for m in scan_markets:
        market_updated[m]=now
        market_counts[m]=counts.get(m,0)
    rows=[x for x in rows if float(x.get("expires_at") or 0)>now and now-float(x.get("created_at") or 0)<=retention and not x.get("scan_generated")]
    rows=sorted(rows,key=lambda x:(x["created_at"],x.get("source_count",0)),reverse=True)[:700]
    payload={"ok":True,"trades":rows,"updated":now,"refreshing":False,"markets":market_counts,"market_updated":market_updated,"window_hours":hours}
    try:
        with open(CACHE_FILE+".tmp","w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,separators=(",",":"))
        os.replace(CACHE_FILE+".tmp",CACHE_FILE)
    except Exception as exc: print("[PUBLIC-TRADES] cache save failed",str(exc)[:120],flush=True)
    return payload

def _worker(market=None, hours=24):
    global _refreshing,_cache
    try:
        payload=_build(market,hours)
        with _lock: _cache=payload
    except Exception as exc: print("[PUBLIC-TRADES] refresh failed",str(exc)[:160],flush=True)
    finally:
        with _lock: _refreshing=False

@router.get("/api/public-trades")
def public_trades(refresh: int = 0, market: str = "all", hours: int = 24):
    global _refreshing,_cache
    now=time.time()
    try: hours=int(hours)
    except Exception: hours=24
    if hours not in (12, 24, 48): hours=24
    with _lock:
        _cache["trades"]=[x for x in _cache.get("trades",[]) if float(x.get("expires_at") or 0)>now and now-float(x.get("created_at") or 0)<=hours*3600 and not x.get("scan_generated")]
        relevant=list(MARKETS) if market=="all" else [market]
        updated_map=_cache.get("market_updated",{})
        stale=(_cache.get("window_hours") != hours) or any(not updated_map.get(m) or now-float(updated_map.get(m) or 0)>=CACHE_TTL for m in relevant)
        if not _refreshing and (refresh==1 or stale):
            _refreshing=True
            threading.Thread(target=_worker,args=(market,hours),daemon=True,name="public-trades-"+str(market)).start()
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
        def market_enabled(row):
            key=str(row.get("market") or "")
            return enabled.get(key,True)
        filtered=[x for x in _cache["trades"] if float(x.get("created_at") or 0)>=cutoff and market_enabled(x) and (market=="all" or x.get("market")==market)]
        result=dict(_cache); result["trades"]=filtered; result["refreshing"]=_refreshing
        result["selected_market"]=market; result["window_hours"]=hours
        result["market_counts"]={m:sum(1 for x in _cache["trades"] if x.get("market")==m and market_enabled(x) and float(x.get("created_at") or 0)>=cutoff) for m in MARKETS}
        result["remaining_seconds"]=max(0,int(CACHE_TTL-(now-float(_cache.get("updated") or 0))))
        return result
