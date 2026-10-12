"""Public internet-sourced trade ideas, rolling 24h, read-only/paper display only."""
import json, os, threading, time
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter

router = APIRouter()
RETENTION = 172800
CACHE_TTL = 900
MARKETS = ("spot", "futures", "contracts", "us", "saudi", "forex", "alpha")
LABELS = {"spot":"سبوت","futures":"فيوتشر","contracts":"العقود الأمريكية","us":"الأسهم الأمريكية","saudi":"السوق السعودي","forex":"الفوركس والذهب","alpha":"Binance Alpha"}
DATA_DIR = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
CACHE_FILE = os.path.join(DATA_DIR, "public_trades_24h.json")
_lock = threading.Lock()
_refreshing = False
_cache = {"ok": True, "trades": [], "updated": None, "refreshing": False, "markets": {}}
try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    now = time.time()
    _cache["trades"] = [x for x in saved.get("trades", []) if float(x.get("expires_at") or 0) > now]
    _cache["updated"] = saved.get("updated")
except Exception:
    pass

def _stamp(value):
    try: return parsedate_to_datetime(str(value)).timestamp()
    except Exception: return 0.0

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
    level_type = "مستويات منشورة بالمصدر"
    price = 0.0
    if not entry or not targets or not sl:
        price = _last_price(engine, market, symbol, ticker_maps)
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
    return {"market":market,"market_label":LABELS[market],"symbol":symbol,"direction":direction,
        "entry":round(float(entry),8),"tp1":round(targets[0],8),"tp2":round(targets[1],8),"tp3":round(targets[2],8),"sl":round(float(sl),8),
        "source_title":title,"source_url":url,"source_published":published,"created_at":published_at,"expires_at":published_at+RETENTION,
        "level_type":level_type,"is_estimated":level_type!="مستويات منشورة بالمصدر","status":"نشطة","source_count":1,"source_urls":[url]}

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
        key=(row["market"],row["symbol"],row["direction"])
        if key not in merged: merged[key]=row
        else:
            old=merged[key]
            if row["source_url"] not in old["source_urls"]:
                old["source_urls"].append(row["source_url"]); old["source_count"]=len(old["source_urls"])
    now=time.time()
    # Balance the feed so busy markets cannot crowd out quieter markets.
    rows=[]
    for market in MARKETS:
        market_rows=sorted((x for x in merged.values() if x["market"]==market and x["expires_at"]>now),key=lambda x:(x["source_count"],x["created_at"]),reverse=True)
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
        _cache["trades"]=[x for x in _cache.get("trades",[]) if float(x.get("expires_at") or 0)>now]
        stale=not _cache.get("updated") or now-float(_cache.get("updated") or 0)>=CACHE_TTL
        if not _refreshing and (refresh==1 or stale):
            _refreshing=True
            threading.Thread(target=_worker,daemon=True,name="public-trades-24h").start()
        try: hours=int(hours)
        except Exception: hours=48
        if hours not in (12,24,48): hours=48
        if market not in ("all",)+MARKETS: market="all"
        cutoff=now-hours*3600
        filtered=[x for x in _cache["trades"] if float(x.get("created_at") or 0)>=cutoff and (market=="all" or x.get("market")==market)]
        result=dict(_cache); result["trades"]=filtered; result["refreshing"]=_refreshing
        result["selected_market"]=market; result["window_hours"]=hours
        result["market_counts"]={m:sum(1 for x in _cache["trades"] if x.get("market")==m and float(x.get("created_at") or 0)>=cutoff) for m in MARKETS}
        result["remaining_seconds"]=max(0,int(CACHE_TTL-(now-float(_cache.get("updated") or 0))))
        return result
