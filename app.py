import json, os, re, time, hashlib, urllib.request, urllib.parse
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
DISCOVERY_FILE = DATA_DIR / "discovered_sources.json"

DISCOVERY_TTL = int(os.getenv("DISCOVERY_TTL", "900"))
SIGNAL_CACHE_TTL = int(os.getenv("SIGNAL_CACHE_TTL", "120"))
_discovery_cache = {"ts": 0, "sources": []}
_signal_cache = {"ts": 0, "signals": []}

app = FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "smart-trading-pro-local"))

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUT = "https://fapi.binance.com"
YAHOO = "https://query1.finance.yahoo.com"

# Public inputs are used as research feeds. The public UI intentionally presents
# normalized multi-source intelligence rather than exposing implementation details.
SOURCES = [
    {"id":"crypto_a","market":"crypto","url":"https://t.me/s/Fortunetradersofficial"},
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
FOREX = ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","GC=F","CL=F"]
SYMBOL_RE = re.compile(r"\b[A-Z0-9]{2,15}(?:USDT|USDC|USD)\b", re.I)
PLAIN_US_RE = re.compile(r"(?<![A-Z])\$?([A-Z]{1,5})(?![A-Z])")
SAUDI_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
FOREX_RE = re.compile(r"\b(?:EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|USDCHF|NZDUSD|XAUUSD|GOLD|GBPJPY|GBPAUD|EURGBP|US30|NAS100|US100|SPX|SP500|DJI)\b", re.I)
PRICE_RE = re.compile(r"(?<![A-Za-z])(?:\d{1,7}(?:[\.,]\d{1,8})?|0[\.,]\d{1,12})(?![A-Za-z])")

def now():
    return time.time()

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

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

def active_sources():
    discovered = _discovery_cache["sources"] if _discovery_cache["ts"] else read_json(DISCOVERY_FILE, [])
    return SOURCES + discovered[:30]

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

def parse_feed(html, market):
    blocks=re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',html,re.S|re.I)
    out=[]
    for b in blocks[-30:]:
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

def collect_external_signals():
    global _signal_cache
    if now() - _signal_cache["ts"] < SIGNAL_CACHE_TTL:
        return _signal_cache["signals"]
    discover_public_sources()
    results=[]
    for src in active_sources():
        try:
            html=http_get(src["url"],5)
            for x in parse_feed(html,src["market"])[-20:]:
                x["source_id"]=src["id"]; x["source_market"]=src["market"]
                results.append(x)
        except Exception:
            continue
    _signal_cache={"ts":now(),"signals":results}
    return results

def normalize_signal(x):
    market=x["source_market"]; sym=x["symbol"]
    if market=="saudi":
        if sym.isdigit(): sym=sym+".SR"
        if not re.fullmatch(r"\d{4}\.SR",sym): return None
    elif market=="us":
        sym=sym.replace("USDT","")
        if sym not in US and sym not in ("SPX","NDX","US30","NAS100","US100"): return None
    elif market=="forex":
        if sym not in FOREX and sym not in ("GC=F","CL=F"): return None
    elif market in ("crypto","futures"):
        if not sym.endswith("USDT"): return None
    try:
        price=market_price(sym, "futures" if market=="futures" else ("crypto" if market=="crypto" else market))
    except:
        return None
    tc=technical_confirmation(sym, "futures" if market=="futures" else ("crypto" if market=="crypto" else market))
    distance=abs(price-x["entry"])/max(abs(x["entry"]),1e-9)*100
    # Keep a source signal only while entry is realistically near current price.
    if distance>5: return None
    agreement=0
    if x["direction"]=="LONG": agreement=tc.get("score",0)
    else: agreement=100-tc.get("score",50)
    score=round(0.55*agreement+0.25*min(100,max(0,100-distance*20))+0.20*min(100,max(0,tc.get("score",0))),1)
    return {**x,"symbol":sym,"price":price,"technical":tc,"distance_pct":round(distance,2),"score":score}

def own_market_candidates():
    candidates=[]
    # A compact fallback scan keeps the home useful when public feeds are quiet.
    groups=[
        ("crypto",["BTCUSDT","ETHUSDT","SOLUSDT"]),
        ("futures",["BTCUSDT","ETHUSDT","SOLUSDT"]),
        ("us",["NVDA","AAPL","MSFT","TSLA","SPY","QQQ"]),
        ("saudi",["2222.SR","1120.SR","1180.SR","7010.SR","1211.SR"]),
        ("forex",["EURUSD=X","GBPUSD=X","USDJPY=X","GC=F"]),
    ]
    for market, symbols in groups:
        for sym in symbols:
            try:
                actual=sym
                feed_market=market
                tc=technical_confirmation(actual,feed_market)
                if tc.get("score",0)>=70:
                    p=market_price(actual,feed_market)
                    candidates.append({"symbol":actual,"direction":"LONG","price":p,"score":round(tc["score"],1),"technical":tc,"market":market,"kind":"تحليل داخلي","entry":p,"tps":[],"sl":None})
                elif tc.get("score",0)<=30 and market in ("futures","forex"):
                    p=market_price(actual,feed_market)
                    candidates.append({"symbol":actual,"direction":"SHORT","price":p,"score":round(100-tc["score"],1),"technical":tc,"market":market,"kind":"تحليل داخلي","entry":p,"tps":[],"sl":None})
            except: continue
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
    combined=out+internal
    combined.sort(key=lambda x:(x.get("sources_count",0),x.get("score",0)),reverse=True)
    # De-duplicate symbol/direction and cap load for the small server.
    seen=set(); final=[]
    for x in combined:
        k=(x["symbol"],x["direction"])
        if k in seen: continue
        seen.add(k); final.append(x)
        if len(final)>=18: break
    return final

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
    values=list(bykey.values())[-150:]
    write_json(TRADES_FILE,values)
    return values

@app.get("/health")
def health():
    return {"ok":True,"service":"smart-trading-pro","version":"rebuild-v2-telegram-radar"}

@app.get("/",response_class=HTMLResponse)
def home():
    return Path(BASE/"static/index.html").read_text(encoding="utf-8")

@app.get("/api/opportunities")
def opportunities():
    data=build_opportunities()
    trades=update_trades(data)
    signals=collect_external_signals()
    sources=active_sources()
    live_sources=len({x.get("source_id") for x in signals if x.get("source_id")})
    return {"updated_at":now(),"opportunities":data,"live_trades":trades,
            "markets":{"saudi":"السعودي","us":"الأمريكي","forex":"الفوركس والذهب","futures":"الفيوتشر","crypto":"الكريبتو"},
            "radar":{"sources_total":len(sources),"sources_live":live_sources,
                     "discovered_sources":max(0,len(sources)-len(SOURCES)),
                     "signals_found":len(signals)}}

@app.get("/api/trades")
def trades():
    t=read_json(TRADES_FILE,[])
    return {"updated_at":now(),"trades":t[-100:]}

@app.get("/api/market/{market}")
def market(market:str):
    data=build_opportunities()
    return {"market":market,"opportunities":[x for x in data if x.get("market")==market or x.get("source_market")==market]}

app.mount("/static", StaticFiles(directory=str(BASE/"static")), name="static")
