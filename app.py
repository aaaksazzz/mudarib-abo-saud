import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, os, re, time, hashlib, secrets, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    DATA_DIR = BASE / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "signals.json"
TRADES_FILE = DATA_DIR / "live_trades.json"
USERS_FILE = DATA_DIR / "users.json"
DISCOVERY_FILE = DATA_DIR / "discovered_sources.json"
WEB_DISCOVERY_FILE = DATA_DIR / "discovered_web_sources.json"

DISCOVERY_TTL = int(os.getenv("DISCOVERY_TTL", "900"))
SIGNAL_CACHE_TTL = int(os.getenv("SIGNAL_CACHE_TTL", "120"))
TALK_CACHE_TTL = int(os.getenv("TALK_CACHE_TTL", "120"))
_discovery_cache = {"ts": 0, "sources": []}
_signal_cache = {"ts": 0, "signals": []}
_web_discovery_cache = {"ts": 0, "sources": []}
_talk_cache = {"ts": 0, "items": []}
_scan_cache = {"ts": 0, "candidates": []}
SCAN_CACHE_TTL = int(os.getenv("SCAN_CACHE_TTL", "180"))
BINANCE_SCAN_LIMIT = int(os.getenv("BINANCE_SCAN_LIMIT", "120"))
TRADE_RETENTION_SECONDS = 24 * 60 * 60
MEMORY_RETENTION_SECONDS = 24 * 60 * 60

app = FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "smart-trading-pro-local"))

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUT = "https://fapi.binance.com"
YAHOO = "https://query1.finance.yahoo.com"

# Public inputs are used as research feeds. The public UI intentionally presents
# normalized multi-source intelligence rather than exposing implementation details.
SOURCES = [
    {"id":"fortune_traders","market":"crypto","url":"https://t.me/s/Fortunetradersofficial","app_url":"https://play.google.com/store/apps/details?id=com.tradoku.fortune_traders"},
    {"id":"fortune_scalping","market":"crypto","url":"https://t.me/s/FORTUNESCALPING","app_url":"https://play.google.com/store/apps/details?id=com.tradoku.fortune_traders"},
    {"id":"crypto_b","market":"futures","url":"https://t.me/s/binancefuturesignal"},
    {"id":"crypto_c","market":"crypto","url":"https://t.me/s/Saudicryptochannel"},
    {"id":"crypto_d","market":"crypto","url":"https://t.me/s/ta_trading1"},
    {"id":"us_a","market":"us","url":"https://t.me/s/ssfindices"},
    {"id":"us_b","market":"us","url":"https://t.me/s/trial_smarttrader"},
    {"id":"fx_a","market":"forex","url":"https://t.me/s/sureshot_fx"},
    {"id":"fx_b","market":"forex","url":"https://t.me/s/arabicfxadvisors"},
    {"id":"fx_c","market":"forex","url":"https://t.me/s/fxtradingvision"},
    {"id":"fx_d","market":"forex","url":"https://t.me/s/el_sayaadex"},
    {"id":"sa_a","market":"saudi","url":"https://t.me/s/smartwyckofftrading"},
    {"id":"sa_b","market":"saudi","url":"https://t.me/s/SaudiMarketExpert"},
    {"id":"sa_c","market":"saudi","url":"https://t.me/s/stockmaker"},
    {"id":"sa_d","market":"saudi","url":"https://t.me/s/altamimiAm"},
    {"id":"sa_e","market":"saudi","url":"https://t.me/s/smarttrading2030"},
    {"id":"all_a","market":"multi","url":"https://t.me/s/FatPigSignals"},
]

SAUDI = {
    "2222.SR":"أرامكو","1120.SR":"الراجحي","1180.SR":"الأهلي السعودي","2010.SR":"سابك",
    "7010.SR":"stc","1211.SR":"معادن","1150.SR":"الإنماء","2280.SR":"المراعي",
    "4030.SR":"البحري","2082.SR":"أكوا باور","4003.SR":"إكسترا","5110.SR":"كهرباء السعودية"
}
US = {
    "NVDA":"NVIDIA","AAPL":"Apple","MSFT":"Microsoft","AMZN":"Amazon","META":"Meta",
    "TSLA":"Tesla","GOOGL":"Alphabet","AMD":"AMD","AVGO":"Broadcom","NFLX":"Netflix",
    "SPY":"S&P 500 ETF","QQQ":"Nasdaq 100 ETF","IWM":"Russell 2000 ETF"
}
FOREX = ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X"]

# Hard market ownership: a symbol can belong to exactly one section.
MARKET_SYMBOLS = {
    "contracts": {"ES=F","NQ=F","YM=F","GC=F"},
    "us": set(US.keys()),
    "saudi": set(SAUDI.keys()),
    "forex": set(FOREX),
}

def symbol_belongs_to_market(symbol, market):
    symbol = str(symbol or "").upper()
    if market in ("crypto","futures"):
        return bool(re.fullmatch(r"[A-Z0-9]{2,15}USDT", symbol))
    return symbol in MARKET_SYMBOLS.get(market, set())

def canonical_market_for_symbol(symbol):
    symbol = str(symbol or "").upper()
    if symbol in MARKET_SYMBOLS["contracts"]: return "contracts"
    if symbol in MARKET_SYMBOLS["us"]: return "us"
    if symbol in MARKET_SYMBOLS["saudi"]: return "saudi"
    if symbol in MARKET_SYMBOLS["forex"]: return "forex"
    if symbol.endswith("USDT"): return None
    return None
SYMBOL_RE = re.compile(r"\b[A-Z0-9]{2,15}(?:USDT|USDC|USD)\b", re.I)
PLAIN_US_RE = re.compile(r"(?<![A-Z])\$?([A-Z]{1,5})(?![A-Z])")
SAUDI_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
FOREX_RE = re.compile(r"\b(?:EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|USDCHF|NZDUSD|XAUUSD|GOLD|GBPJPY|GBPAUD|EURGBP|US30|NAS100|US100|SPX|SP500|DJI)\b", re.I)
PRICE_RE = re.compile(r"(?<![A-Za-z])(?:\d{1,7}(?:[\.,]\d{1,8})?|0[\.,]\d{1,12})(?![A-Za-z])")

def now():
    return time.time()

def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 180000).hex()
    return salt, digest

def _verify_password(password, salt, digest):
    _, value = _hash_password(password, salt)
    return secrets.compare_digest(value, digest)

def _current_user(request):
    uid = request.session.get("user_id")
    if not uid: return None
    users = read_json(USERS_FILE, {})
    u = users.get(uid)
    if not u: return None
    return {"id":uid,"name":u.get("name",""),"email":u.get("email",""),"created_at":u.get("created_at")}

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def prune_expired_memory():
    """Keep persisted discovery/research memory limited to the latest 24 hours."""
    cutoff=now()-MEMORY_RETENTION_SECONDS
    for path in (DISCOVERY_FILE, WEB_DISCOVERY_FILE):
        try:
            items=read_json(path,[])
            if not isinstance(items,list):
                continue
            fresh=[x for x in items if float(x.get("discovered_at",0) or 0)>=cutoff]
            if len(fresh)!=len(items):
                write_json(path,fresh)
        except Exception:
            continue

def http_get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 SmartTradingPRO/2.0","Accept":"text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def discover_public_sources():
    """Discover bounded public Telegram channels; private/VIP areas are never accessed."""
    global _discovery_cache
    if now() - _discovery_cache["ts"] < DISCOVERY_TTL:
        return _discovery_cache["sources"]
    queries = {
        "crypto": ["site:t.me/s crypto signal BTC ETH USDT trading signal", "site:t.me/s binance futures signal"],
        "futures": ["site:t.me/s futures signal BTC ETH SOL long short"],
        "us": ["site:t.me/s US stock signal NVDA AAPL SPY NASDAQ", "site:t.me/s US indices trading signals"],
        "saudi": ["site:t.me/s Saudi stocks signal تداول الاسهم السعودية", "site:t.me/s توصيات الاسهم السعودية"],
        "forex": ["site:t.me/s forex signal gold XAUUSD EURUSD GBPUSD", "site:t.me/s توصيات فوركس ذهب"],
    }
    found, seen = [], {s["url"] for s in SOURCES}
    for market, qs in queries.items():
        for q in qs:
            try:
                html = http_get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q}), 5)
                urls = re.findall(r'https?://t\\.me/(?:s/)?([A-Za-z0-9_]{4,64})', html)
                for channel in urls:
                    url = "https://t.me/s/" + channel
                    if url in seen: continue
                    seen.add(url)
                    found.append({"id":"disc_"+hashlib.sha1(url.encode()).hexdigest()[:10],
                                  "market":market,"url":url,"discovered_at":now()})
                    if len(found) >= 30: break
            except Exception:
                continue
    _discovery_cache = {"ts": now(), "sources": found}
    try: write_json(DISCOVERY_FILE, found)
    except Exception: pass
    return found

def discover_public_web_sources():
    """Discover public market-research pages/news feeds outside Telegram."""
    global _web_discovery_cache
    if now() - _web_discovery_cache["ts"] < DISCOVERY_TTL:
        return _web_discovery_cache["sources"]
    queries = {
        "crypto": ["crypto trading signals BTC ETH SOL", "bitcoin buy sell signal analysis"],
        "futures": ["crypto futures long short signals", "futures trading signals BTC ETH"],
        "us": ["US stocks buy sell signals NVDA AAPL TSLA", "NASDAQ S&P stock trade ideas"],
        "saudi": ["Saudi stocks trading signals تداول الأسهم السعودية", "Tadawul stock recommendations"],
        "forex": ["forex gold XAUUSD trading signals", "EURUSD GBPUSD trading ideas"],
    }
    found, seen = [], set()
    for market, qs in queries.items():
        for q in qs:
            try:
                html = http_get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q}), 5)
                links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', html, re.I)
                for raw in links:
                    url = urllib.parse.unquote(raw)
                    if not url.startswith(("http://","https://")): continue
                    host = urllib.parse.urlparse(url).netloc.lower()
                    if not host or "duckduckgo." in host or "t.me" in host: continue
                    if any(x in host for x in ("facebook.com","instagram.com","x.com","twitter.com")): continue
                    if url in seen: continue
                    seen.add(url)
                    found.append({"id":"web_"+hashlib.sha1(url.encode()).hexdigest()[:10],
                                  "market":market,"url":url,"discovered_at":now()})
                    if len(found) >= 40: break
            except Exception:
                continue
    for market, q in queries.items():
        rss = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q":q[0],"hl":"en-US","gl":"US","ceid":"US:en"})
        found.append({"id":"news_"+market,"market":market,"url":rss,"kind":"rss","discovered_at":now()})
    _web_discovery_cache={"ts":now(),"sources":found}
    try: write_json(WEB_DISCOVERY_FILE, found)
    except Exception: pass
    return found

def active_sources():
    prune_expired_memory()
    cutoff=now()-MEMORY_RETENTION_SECONDS
    discovered = _discovery_cache["sources"] if _discovery_cache["ts"] else read_json(DISCOVERY_FILE, [])
    discovered=[x for x in discovered if float(x.get("discovered_at",0) or 0)>=cutoff]
    return SOURCES + discovered[:30]

def active_web_sources():
    prune_expired_memory()
    cutoff=now()-MEMORY_RETENTION_SECONDS
    strong=[
        {"id":"binance_research","market":"crypto","url":"https://www.binance.com/en/research/analysis","kind":"web","discovered_at":now()},
        {"id":"coinmarketcap_news","market":"crypto","url":"https://coinmarketcap.com/top-stories/","kind":"web","discovered_at":now()},
        {"id":"tradingview_crypto_news","market":"crypto","url":"https://www.tradingview.com/markets/cryptocurrencies/news/","kind":"web","discovered_at":now()},
        {"id":"coingecko_binance","market":"crypto","url":"https://www.coingecko.com/en/exchanges/binance","kind":"web","discovered_at":now()},
    ]
    discovered = _web_discovery_cache["sources"] if _web_discovery_cache["ts"] else read_json(WEB_DISCOVERY_FILE, [])
    discovered=[x for x in discovered if float(x.get("discovered_at",0) or 0)>=cutoff]
    seen={x["url"] for x in strong}
    return strong + [x for x in discovered if x.get("url") not in seen][:45]

def json_get(url, timeout=7):
    req = urllib.request.Request(url, headers={"User-Agent":"SmartTradingPRO/2.0","Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8","replace"))

def binance_klines(symbol, interval="15m", limit=120, futures=False):
    base = BINANCE_FUT if futures else BINANCE_SPOT
    path = "/fapi/v1/klines" if futures else "/api/v3/klines"
    return json_get(base + path + "?" + urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":limit}), 7)

def yahoo_chart(symbol, interval="1d", range_="3mo"):
    u = YAHOO + "/v8/finance/chart/" + urllib.parse.quote(symbol) + "?" + urllib.parse.urlencode({"interval":interval,"range":range_})
    return json_get(u, 8)

def ema(values, period):
    if len(values) < period: return values[-1] if values else 0
    k = 2/(period+1)
    e = sum(values[:period])/period
    for v in values[period:]: e = v*k + e*(1-k)
    return e

def rsi(values, period=14):
    if len(values) <= period: return 50
    gains=[]; losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for g,l in zip(gains[period:],losses[period:]):
        ag=(ag*(period-1)+g)/period; al=(al*(period-1)+l)/period
    return 100 if al == 0 else 100-(100/(1+ag/al))

def market_price(symbol, market):
    if market in ("crypto","futures"):
        d=json_get((BINANCE_FUT if market=="futures" else BINANCE_SPOT) + ("/fapi/v1/ticker/price" if market=="futures" else "/api/v3/ticker/price") + "?" + urllib.parse.urlencode({"symbol":symbol}), 5)
        return float(d["price"])
    d=yahoo_chart(symbol, "1d", "5d")
    return float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])

def technical_confirmation(symbol, market):
    try:
        if market in ("crypto","futures"):
            raw=binance_klines(symbol,"15m",120,market=="futures")
            closes=[float(x[4]) for x in raw]; vols=[float(x[5]) for x in raw]
        else:
            raw=yahoo_chart(symbol,"1d","6mo")["chart"]["result"][0]
            closes=[float(x) for x in raw["indicators"]["quote"][0]["close"] if x is not None]
            vols=[float(x or 0) for x in raw["indicators"]["quote"][0].get("volume",[])]
        if len(closes)<30:return {"score":0,"trend":"غير كافٍ"}
        e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes)
        price=closes[-1]; avgvol=sum(vols[-20:])/20 if len(vols)>=20 else 0
        vol=(vols[-1]/avgvol) if avgvol else 1
        score=0
        score += 25 if price>e20 else -25
        score += 25 if e20>e50 else -25
        score += 25 if rr>52 else (-25 if rr<48 else 0)
        score += 15 if vol>=1.1 else 0
        score += 10 if price>max(closes[-10:-1]) else 0
        return {"score":max(0,min(100,50+score/2)),"trend":"صاعد" if price>e20 and e20>e50 else ("هابط" if price<e20 and e20<e50 else "محايد"),"rsi":round(rr,1),"volume_ratio":round(vol,2)}
    except Exception as e:
        return {"score":0,"trend":"غير متاح","error":str(e)[:100]}

def clean_html(s):
    s=re.sub(r"<br\s*/?>","\n",s,flags=re.I)
    s=re.sub(r"<[^>]+>"," ",s)
    s=re.sub(r"&nbsp;"," ",s,flags=re.I)
    s=re.sub(r"&amp;","&",s)
    return re.sub(r"\s+"," ",s).strip()

def parse_direction_only_feed(html, market):
    """Read public direction-only signals (notably Fortune Traders) without requiring VIP levels."""
    blocks=re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',html,re.S|re.I)
    out=[]
    for b in blocks[-60:]:
        text=clean_html(b); upper=text.upper()
        direction="LONG" if any(x in upper for x in ("LONG","BUY","شراء","CALL")) else ("SHORT" if any(x in upper for x in ("SHORT","SELL","بيع","PUT")) else "")
        if not direction: continue
        symbol=None
        m=SYMBOL_RE.search(upper)
        if m: symbol=m.group(0).upper()
        if not symbol and market in ("saudi","multi"):
            sm=SAUDI_RE.search(upper)
            if sm: symbol=sm.group(1)
        if not symbol and market in ("us","multi"):
            for pm in PLAIN_US_RE.finditer(upper):
                if pm.group(1) in US: symbol=pm.group(1); break
        fm=FOREX_RE.search(upper)
        if fm:
            symbol=fm.group(0).upper()
            if symbol in ("XAUUSD","GOLD"): symbol="GC=F"
            elif symbol in ("US30","NAS100","US100","SPX","SP500","DJI"):
                symbol={"US30":"^DJI","NAS100":"^NDX","US100":"^NDX","SPX":"^GSPC","SP500":"^GSPC","DJI":"^DJI"}[symbol]
            elif not symbol.endswith("=X"): symbol += "=X"
        if not symbol: continue
        out.append({"symbol":symbol,"direction":direction,"entry":None,"tps":[],"sl":None,"text":text[:600],"ts":now()})
    return out

def parse_feed(html, market):
    blocks=re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',html,re.S|re.I)
    out=[]
    for b in blocks[-60:]:
        text=clean_html(b)
        upper=text.upper()
        direction="LONG" if any(x in upper for x in ("LONG","BUY","شراء","CALL")) else ("SHORT" if any(x in upper for x in ("SHORT","SELL","بيع","PUT")) else "")
        if not direction: continue
        symbol=None
        m=SYMBOL_RE.search(upper)
        if m: symbol=m.group(0).upper()
        if not symbol and market in ("saudi","multi"):
            sm=SAUDI_RE.search(upper)
            if sm: symbol=sm.group(1)
        fm=FOREX_RE.search(upper)
        if fm:
            symbol=fm.group(0).upper()
            if symbol in ("XAUUSD","GOLD"): symbol="GC=F"
            elif symbol in ("US30","NAS100","US100","SPX","SP500","DJI"):
                symbol={"US30":"^DJI","NAS100":"^NDX","US100":"^NDX","SPX":"^GSPC","SP500":"^GSPC","DJI":"^DJI"}[symbol]
            elif not symbol.endswith("=X"): symbol += "=X"
        if not symbol and market in ("us","multi"):
            for pm in PLAIN_US_RE.finditer(upper):
                if pm.group(1) in US:
                    symbol=pm.group(1); break
        if not symbol: continue
        nums=[]
        for x in PRICE_RE.findall(text):
            try:
                n=float(x.replace(",",".")); 
                if n>0: nums.append(n)
            except: pass
        if len(nums)<3: continue
        # Heuristic: entry first, targets/stop are selected from the remaining values.
        entry=nums[0]
        rest=nums[1:]
        stop=None; tps=[]
        if "SL" in upper or "STOP" in upper or "وقف" in text:
            stop=rest[-1]
            tps=rest[:-1]
        else:
            tps=rest
        tps=tps[:3]
        if not tps: continue
        out.append({"symbol":symbol,"direction":direction,"entry":entry,"tps":tps,"sl":stop,"text":text[:600],"ts":now()})
    return out


def parse_talk_feed(html, market):
    """Extract what people are talking about, even without an explicit trade call."""
    blocks=re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',html,re.S|re.I)
    if not blocks: blocks=[html]
    # Only count public posts from the last 24 hours when the source exposes a timestamp.
    cutoff=now()-24*60*60
    times=re.findall(r'<time[^>]+datetime=["\\\']([^"\\\']+)["\\\'][^>]*>',html,re.S|re.I)
    counts={}
    recent_blocks=blocks[-60:]
    for i,b in enumerate(recent_blocks):
        if times and len(times)>=len(recent_blocks):
            try:
                raw_ts=times[-len(recent_blocks)+i].replace("Z","+00:00")
                if datetime.fromisoformat(raw_ts).timestamp() < cutoff:
                    continue
            except Exception:
                pass
        text=clean_html(b); upper=text.upper(); syms=[]
        syms += [m.group(0).upper() for m in SYMBOL_RE.finditer(upper)]
        if market in ("us","multi"): syms += [m.group(1) for m in PLAIN_US_RE.finditer(upper) if m.group(1) in US]
        if market in ("saudi","multi"): syms += [m.group(1)+".SR" for m in SAUDI_RE.finditer(upper)]
        fm=FOREX_RE.search(upper)
        if fm:
            s=fm.group(0).upper(); syms.append("GC=F" if s in ("XAUUSD","GOLD") else s)
        for sym in dict.fromkeys(syms):
            positive=sum(upper.count(x) for x in ("BUY","LONG","BULLISH","شراء","صاعد","إيجابي","CALL","TARGET","اختراق"))
            negative=sum(upper.count(x) for x in ("SELL","SHORT","BEARISH","بيع","هابط","سلبي","PUT","BREAKDOWN"))
            d=counts.setdefault(sym,{"mentions":0,"positive":0,"negative":0})
            d["mentions"]+=1; d["positive"]+=positive; d["negative"]+=negative
    out=[]
    for sym,v in counts.items():
        total=v["positive"]+v["negative"]
        sentiment=round((v["positive"]-v["negative"])/max(1,total)*100) if total else 0
        out.append({"symbol":sym,"market":market,"mentions":v["mentions"],"sentiment":sentiment})
    return out

def collect_talk():
    prune_expired_memory()
    global _talk_cache
    if now()-_talk_cache["ts"] < TALK_CACHE_TTL: return _talk_cache["items"]
    discover_public_sources(); discover_public_web_sources()
    buckets={}
    for src in active_sources():
        try:
            html=http_get(src["url"],5)
            for x in parse_talk_feed(html,src["market"]):
                k=(x["symbol"],x["market"]); d=buckets.setdefault(k,{**x,"sources":set()})
                d["mentions"]+=x["mentions"]; d["sources"].add(src["id"])
        except Exception: continue
    for src in active_web_sources():
        try:
            html=http_get(src["url"],5)
            for x in parse_talk_feed(html,src["market"]):
                k=(x["symbol"],x["market"]); d=buckets.setdefault(k,{**x,"sources":set()})
                d["mentions"]+=x["mentions"]; d["sources"].add(src["id"])
        except Exception: continue
    items=[]
    for d in buckets.values():
        d["sources_count"]=len(d.pop("sources"))
        d["trend_score"]=round(min(99,d["mentions"]*8+d["sources_count"]*10+abs(d["sentiment"])*0.15),1)
        items.append(d)
    items.sort(key=lambda x:(x["trend_score"],x["mentions"]),reverse=True)
    _talk_cache={"ts":now(),"items":items[:30]}
    return _talk_cache["items"]

def parse_web_feed(html, market):
    text = clean_html(html)
    upper = text.upper()
    direction = "LONG" if any(x in upper for x in ("BUY","LONG","BULLISH","شراء","CALL","UPSIDE")) else (
        "SHORT" if any(x in upper for x in ("SELL","SHORT","BEARISH","بيع","PUT","DOWNSIDE")) else "")
    if not direction: return []
    symbols=[]
    for m in SYMBOL_RE.finditer(upper): symbols.append(m.group(0).upper())
    if market in ("us","multi"):
        symbols += [m.group(1) for m in PLAIN_US_RE.finditer(upper) if m.group(1) in US]
    if market=="saudi":
        symbols += [m.group(1)+".SR" for m in SAUDI_RE.finditer(upper)]
    fm=FOREX_RE.search(upper)
    if fm:
        s=fm.group(0).upper()
        symbols.append("GC=F" if s in ("XAUUSD","GOLD") else s)
    symbols=list(dict.fromkeys(symbols))
    nums=[]
    for x in PRICE_RE.findall(text):
        try:
            n=float(x.replace(",",".")); 
            if n>0: nums.append(n)
        except Exception: pass
    if not symbols: return []
    out=[]
    for sym in symbols[:6]:
        out.append({"symbol":sym,"direction":direction,"entry":nums[0] if nums else 0,
                    "tps":nums[1:4] if len(nums)>1 else [],"sl":nums[4] if len(nums)>4 else None,
                    "text":text[:800],"ts":now()})
    return out

def collect_external_signals():
    prune_expired_memory()
    global _signal_cache
    # Keep public trade signals available on the site for up to 24 hours.
    fresh_cutoff=now()-24*60*60
    if now() - _signal_cache["ts"] < SIGNAL_CACHE_TTL:
        return [x for x in _signal_cache["signals"] if float(x.get("ts",0) or 0)>=fresh_cutoff]
    discover_public_sources()
    discover_public_web_sources()
    results=[]
    cutoff=now()-24*60*60
    for src in active_sources()[:25]:
        try:
            html=http_get(src["url"],3)
            parsed=parse_feed(html,src["market"])
            if src["id"] in ("fortune_traders","fortune_scalping"):
                # Fortune is used as a direction input only; our own engine supplies levels.
                parsed = parsed + parse_direction_only_feed(html,src["market"])
            for x in parsed[-20:]:
                x["source_id"]=src["id"]; x["source_market"]=src["market"]
                if float(x.get("ts",now()) or now()) >= cutoff:
                    results.append(x)
        except Exception:
            continue
    for src in active_web_sources()[:18]:
        try:
            html=http_get(src["url"],3)
            for x in parse_web_feed(html,src["market"])[-8:]:
                x["source_id"]=src["id"]; x["source_market"]=src["market"]
                if float(x.get("ts",now()) or now()) >= cutoff:
                    results.append(x)
        except Exception:
            continue
    # Keep public trade signals available for one day.
    results=[x for x in results if float(x.get("ts",now()) or now())>=now()-24*60*60]
    _signal_cache={"ts":now(),"signals":results}
    return results

def normalize_signal(x):
    market=x.get("source_market") or x.get("market")
    sym=str(x.get("symbol") or "").upper()
    # Multi-source feeds are not allowed to leak into a market section.
    # Only a symbol with an unambiguous canonical owner may be promoted.
    if market=="multi":
        market=canonical_market_for_symbol(sym)
        if not market: return None
    if market=="saudi":
        if sym.isdigit(): sym=sym+".SR"
        if not re.fullmatch(r"\d{4}\.SR",sym): return None
    elif market=="us":
        sym=sym.replace("USDT","")
        if sym not in US and sym not in ("SPX","NDX","US30","NAS100","US100"): return None
    elif market=="forex":
        if sym not in MARKET_SYMBOLS["forex"]: return None
    elif market=="contracts":
        if sym not in MARKET_SYMBOLS["contracts"]: return None
    elif market in ("crypto","futures"):
        if not sym.endswith("USDT"): return None
    try:
        price=market_price(sym, "futures" if market=="futures" else ("crypto" if market=="crypto" else market))
    except:
        return None
    tc=technical_confirmation(sym, "futures" if market=="futures" else ("crypto" if market=="crypto" else market))
    # Direction-only sources (Fortune) are validated against live technicals and get levels from our engine.
    source_entry=x.get("entry")
    entry_for_distance=float(source_entry) if source_entry not in (None,"",0) else price
    distance=abs(price-entry_for_distance)/max(abs(entry_for_distance),1e-9)*100
    # Do not discard a valid public signal just because the market already moved.
    # Distance is a confidence input only; the UI should still show the opportunity.
    agreement=0
    if x["direction"]=="LONG": agreement=tc.get("score",0)
    else: agreement=100-tc.get("score",50)
    score=round(0.55*agreement+0.25*min(100,max(0,100-distance*20))+0.20*min(100,max(0,tc.get("score",0))),1)
    return {**x,"symbol":sym,"price":price,"entry":(float(source_entry) if source_entry not in (None,"",0) else price),"technical":tc,"distance_pct":round(distance,2),"score":score}

def tv_scan_universe(market, limit=300):
    """Broad public TradingView scanner universe; used to discover active/liquid names."""
    endpoints={"us":"https://scanner.tradingview.com/america/scan","saudi":"https://scanner.tradingview.com/sa/scan","forex":"https://scanner.tradingview.com/forex/scan","contracts":"https://scanner.tradingview.com/futures/scan","crypto":"https://scanner.tradingview.com/crypto/scan"}
    url=endpoints.get(market)
    if not url: return []
    try:
        payload={"filter":[],"options":{"lang":"en"},"symbols":{"query":{"types":[]},"tickers":[]},"columns":["name","description","close","volume","relative_volume_10d_calc","change","change_abs"],"sort":{"sortBy":"volume","sortOrder":"desc"},"range":[0,limit]}
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=10) as r: d=json.loads(r.read().decode("utf-8","replace"))
        out=[]
        for row in d.get("data",[]):
            raw=str(row.get("s","")).upper().split(":",1)[-1]
            if market=="us": sym=raw
            elif market=="saudi": sym=raw.split(".")[0]+".SR"
            elif market=="forex": sym=raw.replace("=X","")+"=X"
            elif market=="contracts": sym={"ES1!":"ES=F","NQ1!":"NQ=F","YM1!":"YM=F","GC1!":"GC=F"}.get(raw,"")
            elif market=="crypto": sym=raw if raw.endswith("USDT") else ""
            else: sym=""
            if sym and symbol_belongs_to_market(sym,market): out.append(sym)
        return list(dict.fromkeys(out))
    except Exception: return []

def chatter_ranked_universe(market, fallback):
    """Put symbols with the strongest public discussion first."""
    try:
        items=collect_talk(); hot=[]
        for x in items:
            if x.get("market")!=market: continue
            sym=str(x.get("symbol","")).upper()
            if market=="saudi" and sym.isdigit(): sym += ".SR"
            if symbol_belongs_to_market(sym,market): hot.append((float(x.get("trend_score",0) or 0),sym))
        hot=[s for _,s in sorted(hot,reverse=True)]
        return list(dict.fromkeys(hot+fallback))
    except Exception: return fallback

def binance_scan_universe(market):
    """Build a large live universe from Binance instead of scanning 3 hand-picked coins."""
    try:
        base=BINANCE_FUT if market=="futures" else BINANCE_SPOT
        info=json_get(base+("/fapi/v1/exchangeInfo" if market=="futures" else "/api/v3/exchangeInfo"),8)
        symbols=[]
        for s in info.get("symbols",[]):
            if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT": continue
            sym=s.get("symbol","").upper()
            if not re.fullmatch(r"[A-Z0-9]{2,15}USDT",sym): continue
            # Keep the scanner focused on tradeable coins, not stablecoins/leveraged tokens.
            base_asset=s.get("baseAsset","").upper()
            if base_asset.endswith(("UP","DOWN","BULL","BEAR")) or base_asset in {"USDT","USDC","BUSD","FDUSD","TUSD","DAI","USDE","USDS","EUR","TRY"}: continue
            symbols.append(sym)
        tick=json_get(base+("/fapi/v1/ticker/24hr" if market=="futures" else "/api/v3/ticker/24hr"),8)
        by={x.get("symbol"):float(x.get("quoteVolume",0) or 0) for x in tick if x.get("symbol") in symbols}
        symbols=sorted(symbols,key=lambda s:by.get(s,0),reverse=True)[:BINANCE_SCAN_LIMIT]
        return symbols
    except Exception:
        return ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","SUIUSDT"]

def social_interest_score(symbol, market):
    """Measure public discussion and recover targets/stop published in those signals."""
    score=0; mentions=0; best=None
    try:
        for item in collect_external_signals():
            if str(item.get("symbol") or "").upper()!=str(symbol).upper(): continue
            mentions += 1
            score += 1
            if item.get("direction") in ("LONG","SHORT"): score += 2
            tps=item.get("tps") or []
            sl=item.get("sl")
            # Prefer a source signal that actually contains entry + targets + stop.
            if item.get("entry") is not None and tps and sl is not None:
                if best is None or len(tps)>len(best.get("tps") or []):
                    best=item
    except Exception: pass
    return mentions, score, best

def own_market_candidates():
    global _scan_cache
    if now()-_scan_cache["ts"] < SCAN_CACHE_TTL:
        return _scan_cache["candidates"]
    candidates=[]
    # Fortune direction-only signals are fed into the same technical confirmation engine.
    fortune_by_symbol={}
    try:
        for s in collect_external_signals():
            if s.get("source_id") in ("fortune_traders","fortune_scalping"):
                k=(str(s.get("symbol") or "").upper(),str(s.get("direction") or "").upper())
                fortune_by_symbol[k]=s
    except Exception:
        fortune_by_symbol={}
    groups=[
        ("crypto",tv_scan_universe("crypto",220) or binance_scan_universe("crypto")),
        ("futures",binance_scan_universe("futures")),
        ("us",tv_scan_universe("us",220) or list(US.keys())),
        ("saudi",tv_scan_universe("saudi",220) or list(SAUDI.keys())),
        ("contracts",["ES=F","NQ=F","YM=F","GC=F"]),
        ("forex",tv_scan_universe("forex",180) or list(FOREX)),
    ]
    groups=[(m,chatter_ranked_universe(m,syms)) for m,syms in groups]
    def scan_one(job):
        market,sym=job
        try:
            tc=technical_confirmation(sym,market)
            score=tc.get("score",0)
            if not (score>=70 or (score<=30 and market in ("futures","contracts","forex"))): return None
            p=market_price(sym,market)
            direction="LONG" if score>=70 else "SHORT"
            fortune=fortune_by_symbol.get((str(sym).upper(),direction))
            if fortune:
                direction=str(fortune.get("direction") or direction).upper()
            mentions,social,best_signal=social_interest_score(sym,market)
            # Public discussion boosts confidence but is NOT a hard gate.
            final_score=min(100,round(score*0.70 + min(30,social*5),1))
            # Prefer source levels; otherwise use live price and transparent fallback levels.
            entry=float(best_signal.get("entry") or p) if best_signal else float(p)
            if fortune and not best_signal: entry=float(p)
            tps=[float(x) for x in ((best_signal or {}).get("tps") or [])[:3] if x is not None]
            sl=(best_signal or {}).get("sl")
            sl=float(sl) if sl is not None else None
            direction=str((best_signal or {}).get("direction") or direction).upper()
            return {"symbol":sym,"direction":direction,"price":p,"score":final_score,"technical":tc,"market":market,"source_market":market,"kind":("Fortune + تحليل فني" if fortune else "فرصة عليها كلام فعلي"),"entry":entry,"tps":tps,"sl":sl,"mentions":mentions,"social_score":social,"fortune_source":bool(fortune)}
        except Exception:
            return None
    scan_caps={"crypto":90,"futures":90,"us":80,"saudi":80,"contracts":4,"forex":60}
    jobs=[(m,s) for m,syms in groups for s in syms[:scan_caps.get(m,100)]]
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures=[pool.submit(scan_one,j) for j in jobs]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x: candidates.append(x)
            except Exception: pass
    candidates.sort(key=lambda x:(x.get("score",0),x.get("mentions",0),x.get("social_score",0)),reverse=True)
    _scan_cache={"ts":now(),"candidates":candidates}
    return candidates

def build_opportunities():
    external=[]
    for x in collect_external_signals():
        y=normalize_signal(x)
        if y: external.append(y)
    # Consensus by symbol/direction.
    buckets={}
    for x in external:
        k=(x["symbol"],x["direction"])
        buckets.setdefault(k,[]).append(x)
    out=[]
    for (sym,direction),items in buckets.items():
        distinct_sources=len({i.get("source_id") for i in items})
        mentions=len(items)
        score=min(99.9,max(i["score"] for i in items)+min(20,(distinct_sources-1)*6)+min(8,max(0,mentions-distinct_sources)*1.5))
        best=max(items,key=lambda z:z["score"])
        out.append({**best,"sources_count":distinct_sources,"mentions":mentions,
                    "consensus":round(100*distinct_sources/max(1,len(SOURCES)),1),
                    "kind":"إجماع مصادر عامة + تحقق مستقل"})
    internal=own_market_candidates()
    talk_by={(str(t.get("symbol","")).upper(),t.get("market")):t for t in collect_talk()}
    for x in out+internal:
        t=talk_by.get((str(x.get("symbol","")).upper(),x.get("market")),{})
        x["talk_mentions"]=int(t.get("mentions",0) or 0)
        x["talk_sources"]=int(t.get("sources_count",0) or 0)
        x["talk_score"]=float(t.get("trend_score",0) or 0)
        x["score"]=round(min(99.9,x.get("score",0)+min(15,x["talk_score"]*0.12)),1)
    combined=out+internal
    combined.sort(key=lambda x:(x.get("talk_mentions",0),x.get("talk_sources",0),x.get("sources_count",0),x.get("score",0)),reverse=True)
    # Keep market ownership and deduplication, but do not use a strict quality gate.
    seen=set(); final=[]; per_market={}
    market_limits={"saudi":12,"us":12,"contracts":12,"crypto":15,"futures":15,"forex":12}
    for x in combined:
        market=x.get("market") or x.get("source_market")
        sym=str(x.get("symbol") or "").upper()
        if market=="multi":
            market=canonical_market_for_symbol(sym)
        if not market or market not in market_limits: continue
        if not symbol_belongs_to_market(sym, market): continue
        k=(market,sym,x.get("direction"))
        if k in seen: continue
        if per_market.get(market,0)>=market_limits[market]: continue
        x["market"]=market
        x["source_market"]=market
        x["symbol"]=sym
        x=ensure_trade_levels(x)
        seen.add(k); final.append(x); per_market[market]=per_market.get(market,0)+1
    return final

def ensure_trade_levels(x):
    """Guarantee every visible opportunity card has entry, 3 targets and a stop."""
    try:
        entry=float(x.get("entry") or x.get("price") or 0)
    except Exception:
        entry=0
    if entry<=0:
        return x
    direction=str(x.get("direction") or "LONG").upper()
    tps=x.get("tps") if isinstance(x.get("tps"),list) else []
    tps=[float(v) for v in tps if str(v).replace(".","",1).isdigit() and float(v)>0]
    sl=x.get("sl")
    try: sl=float(sl) if sl is not None else 0
    except Exception: sl=0
    # Keep source-provided levels; fill only missing levels from a simple 1/2/3% ladder.
    if direction in ("SHORT","SELL","بيع"):
        defaults=[entry*0.99,entry*0.98,entry*0.97]; default_sl=entry*1.01
    else:
        defaults=[entry*1.01,entry*1.02,entry*1.03]; default_sl=entry*0.99
    tps=(tps+[v for v in defaults if v not in tps])[:3]
    if len(tps)<3: tps=defaults[:3]
    if not sl or sl<=0: sl=default_sl
    x["entry"]=entry
    x["tps"]=tps
    x["sl"]=sl
    return x

def update_trades(opps):
    trades=read_json(TRADES_FILE,[])
    bykey={t["id"]:t for t in trades if isinstance(t,dict)}
    for o in opps:
        if not o.get("tps") or not o.get("sl"): continue
        tid=hashlib.sha1((o["symbol"]+o["direction"]+str(o["entry"])+str(o.get("ts",0))).encode()).hexdigest()[:14]
        if tid not in bykey:
            bykey[tid]={"id":tid,"symbol":o["symbol"],"direction":o["direction"],"entry":o["entry"],"tps":o["tps"],"sl":o["sl"],"status":"OPEN","opened_at":now(),"market":o.get("source_market","crypto")}
        t=bykey[tid]
        try:
            p=market_price(t["symbol"],"futures" if t["market"]=="futures" else ("crypto" if t["market"]=="crypto" else t["market"]))
            t["current"]=p
            if t["direction"]=="LONG":
                if t.get("sl") and p<=t["sl"]: t["status"]="SL"
                elif len(t["tps"])>=3 and p>=t["tps"][2]: t["status"]="TP3"
                elif len(t["tps"])>=2 and p>=t["tps"][1]: t["status"]="TP2"
                elif len(t["tps"])>=1 and p>=t["tps"][0]: t["status"]="TP1"
            else:
                if t.get("sl") and p>=t["sl"]: t["status"]="SL"
                elif len(t["tps"])>=3 and p<=t["tps"][2]: t["status"]="TP3"
                elif len(t["tps"])>=2 and p<=t["tps"][1]: t["status"]="TP2"
                elif len(t["tps"])>=1 and p<=t["tps"][0]: t["status"]="TP1"
            sign=1 if t["direction"]=="LONG" else -1
            t["pnl_pct"]=round((p-t["entry"])/t["entry"]*100*sign,2)
            t["updated_at"]=now()
        except: pass
    cutoff=now()-TRADE_RETENTION_SECONDS
    values=[t for t in bykey.values() if float(t.get("opened_at",t.get("created_at",0)) or 0)>=cutoff]
    values.sort(key=lambda t: float(t.get("opened_at",0) or 0))
    write_json(TRADES_FILE,values)
    return values

@app.post("/api/auth/register")
async def register(request: Request):
    body=await request.json()
    name=str(body.get("name","")).strip()
    email=str(body.get("email","")).strip().lower()
    password=str(body.get("password",""))
    if len(name)<2 or len(email)<5 or "@" not in email or len(password)<6:
        return JSONResponse({"ok":False,"error":"بيانات التسجيل غير مكتملة أو كلمة المرور أقل من 6 أحرف"},status_code=400)
    users=read_json(USERS_FILE,{})
    if any(u.get("email")==email for u in users.values()):
        return JSONResponse({"ok":False,"error":"البريد مسجل مسبقًا"},status_code=409)
    uid=secrets.token_hex(12); salt,digest=_hash_password(password)
    users[uid]={"name":name,"email":email,"salt":salt,"password":digest,"created_at":now()}
    write_json(USERS_FILE,users)
    request.session["user_id"]=uid
    return {"ok":True,"user":{"id":uid,"name":name,"email":email}}

@app.post("/api/auth/login")
async def login(request: Request):
    body=await request.json(); email=str(body.get("email","")).strip().lower(); password=str(body.get("password",""))
    users=read_json(USERS_FILE,{})
    for uid,u in users.items():
        if u.get("email")==email and _verify_password(password,u.get("salt",""),u.get("password","")):
            request.session["user_id"]=uid
            return {"ok":True,"user":{"id":uid,"name":u.get("name",""),"email":email}}
    return JSONResponse({"ok":False,"error":"البريد أو كلمة المرور غير صحيحة"},status_code=401)

@app.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear(); return {"ok":True}

@app.get("/api/auth/me")
def me(request: Request):
    return {"ok":True,"user":_current_user(request)}

@app.get("/api/dashboard")
def dashboard(request: Request):
    u=_current_user(request)
    if not u: return JSONResponse({"ok":False,"error":"تسجيل الدخول مطلوب"},status_code=401)
    trades=read_json(TRADES_FILE,[])
    return {"ok":True,"user":u,"stats":{"tracked":len(trades),"open":sum(1 for t in trades if t.get("status")=="OPEN"),"tp":sum(1 for t in trades if str(t.get("status","")).startswith("TP")),"sl":sum(1 for t in trades if t.get("status")=="SL")}}

@app.get("/health")
def health():
    return {"ok":True,"service":"smart-trading-pro","version":"rebuild-v3-market-chatter"}

@app.get("/",response_class=HTMLResponse)
def home():
    return Path(BASE/"static/index.html").read_text(encoding="utf-8")

HOME_ASSETS = [
    {"key":"tasi","symbol":"^TASI","label":"تاسي","market":"home_index","icon":"🇸🇦"},
    {"key":"apple","symbol":"AAPL","label":"أبل","market":"us","icon":"🍎"},
    {"key":"gold","symbol":"GC=F","label":"الذهب","market":"contracts","icon":"🥇"},
    {"key":"bitcoin","symbol":"BTCUSDT","label":"البتكوين","market":"crypto","icon":"₿"},
    {"key":"ethereum","symbol":"ETHUSDT","label":"الإيثريوم","market":"crypto","icon":"Ξ"},
]

def home_asset_analysis(asset):
    sym=asset["symbol"]; market=asset["market"]
    try:
        real_market = "crypto" if market=="crypto" else ("contracts" if market=="contracts" else "us")
        price=market_price(sym, real_market)
        tc=technical_confirmation(sym, real_market)
    except Exception:
        return {**asset,"price":None,"trend":"غير متاح","ai_score":0,"people_mentions":0,"people_score":0,"summary":"تعذر جلب البيانات الآن"}
    talk_symbol=sym.upper()
    if sym=="^TASI": talk_symbol="TASI"
    talks=[x for x in collect_talk() if str(x.get("symbol","")).upper() in (talk_symbol, sym.upper())]
    mentions=sum(int(x.get("mentions",0) or 0) for x in talks)
    people_score=round(min(100, mentions*15 + sum(max(0,float(x.get("trend_score",0) or 0)) for x in talks)))
    ai_score=round(float(tc.get("score",0) or 0))
    trend=tc.get("trend","محايد")
    if people_score>=60 and ai_score>=70: verdict="إيجابي"
    elif people_score>=60 and ai_score<=30: verdict="متضارب"
    elif people_score<30: verdict="لا يوجد كلام كافٍ"
    else: verdict="محايد"
    return {**asset,"price":price,"trend":trend,"ai_score":ai_score,
            "people_mentions":mentions,"people_score":people_score,"verdict":verdict,
            "rsi":tc.get("rsi"),"summary":"تحليل الناس أولاً + تحقق AI خفيف"}

@app.get("/api/home-analysis")
def home_analysis():
    discover_public_sources()
    discover_public_web_sources()
    return {"updated_at":now(),"free":True,"assets":[home_asset_analysis(a) for a in HOME_ASSETS]}

HOME_ANALYSIS = [
    {"symbol":"^TASI","label":"تاسي","market":"saudi","icon":"🇸🇦"},
    {"symbol":"AAPL","label":"Apple","market":"us","icon":"🍎"},
    {"symbol":"GC=F","label":"الذهب","market":"contracts","icon":"🥇"},
    {"symbol":"BTCUSDT","label":"Bitcoin","market":"crypto","icon":"₿"},
    {"symbol":"ETHUSDT","label":"Ethereum","market":"crypto","icon":"Ξ"},
]

def homepage_market_analysis():
    """Free homepage snapshot: public discussion is primary; AI only validates it."""
    try:
        signals=collect_external_signals()
    except Exception:
        signals=[]
    out=[]
    for item in HOME_ANALYSIS:
        sym=item["symbol"]
        matched=[]
        for s in signals or []:
            ss=str(s.get("symbol") or s.get("ticker") or "").upper()
            if ss==sym.upper() or ss.replace(":","").endswith(sym.upper()):
                matched.append(s)
        mentions=sum(int(s.get("mentions",1) or 1) for s in matched)
        sources=len({str(s.get("source") or s.get("provider") or "") for s in matched if s.get("source") or s.get("provider")})
        dirs=[str(s.get("direction") or "").upper() for s in matched]
        long_n=sum(1 for d in dirs if d in ("BUY","LONG","BULLISH","UP"))
        short_n=sum(1 for d in dirs if d in ("SELL","SHORT","BEARISH","DOWN"))
        direction="شراء" if long_n>short_n else ("بيع" if short_n>long_n else "محايد")
        best=max(matched,key=lambda s: float(s.get("score",0) or 0),default={})
        out.append({**item,"direction":direction,"mentions":mentions,"sources":sources,"score":round(float(best.get("score",0) or 0)) if best else 0,"entry":best.get("entry") if best else None,"tps":best.get("tps") if best else [],"sl":best.get("sl") if best else None,"updated_at":now(),"free":True})
    return out

@app.get("/api/opportunities")
def opportunities():
    data=build_opportunities()
    trades=update_trades(data)
    signals=collect_external_signals()
    talk=collect_talk()
    sources=active_sources()
    live_sources=len({x.get("source_id") for x in signals if x.get("source_id")})
    market_data={m:[] for m in ("saudi","us","contracts","crypto","futures","forex")}
    for item in data:
        m=item.get("market")
        if m in market_data: market_data[m].append(item)
    return {"updated_at":now(),"opportunities":data,"market_data":market_data,"live_trades":trades,"trending":talk[:12],
            "markets":{"saudi":"السعودي","us":"الأمريكي","contracts":"العقود الأمريكية","forex":"الفوركس","futures":"الفيوتشر","crypto":"الكريبتو"},
            "radar":{"sources_total":len(sources),"sources_live":live_sources,
                     "discovered_sources":max(0,len(sources)-len(SOURCES)),
                     "web_sources":len(active_web_sources()),"signals_found":len(signals),"talking_about":len(talk),"trending":talk[:12]}}

@app.get("/api/trades")
def trades():
    t=read_json(TRADES_FILE,[])
    return {"updated_at":now(),"trades":t[-100:]}

@app.get("/api/market/{market}")
def market(market:str):
    data=build_opportunities()
    return {"market":market,"opportunities":[x for x in data if x.get("market")==market or x.get("source_market")==market]}

app.mount("/static", StaticFiles(directory=str(BASE/"static")), name="static")