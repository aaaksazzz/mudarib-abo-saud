import re,time,math,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET,json
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor,as_completed

UA="SMART-TRADING-PRO/6.0 pure-method-hybrid"
DISCOVER_TTL=45.0
FETCH_TIMEOUT=5.0
MAX_SOURCE_AGE=48*60*60
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
CACHE={}
ACTIVE_SIGNALS={}

# Persistent opportunity store. Northflank mounts /data as the durable volume.
# Keep a small per-market snapshot so detected trades survive refreshes/restarts.
PERSIST_DIR="/data"
try:
    import os
    if not os.path.isdir(PERSIST_DIR):
        PERSIST_DIR=os.path.join(os.path.dirname(__file__),"data")
        os.makedirs(PERSIST_DIR,exist_ok=True)
except Exception:
    PERSIST_DIR="data"
    try: os.makedirs(PERSIST_DIR,exist_ok=True)
    except Exception: pass

PERSIST_LIMIT=200

def _persist_path(market):
    safe=re.sub(r"[^a-z0-9_-]","_",str(market).lower())
    return os.path.join(PERSIST_DIR,"opportunities_"+safe+".json")

def _load_persisted(market):
    """Load only snapshots that are no older than the 24-hour retention window."""
    try:
        with open(_persist_path(market),"r",encoding="utf-8") as f:
            rows=json.load(f)
        if not isinstance(rows,list):
            return []
        now=time.time()
        fresh=[]
        for row in rows:
            if not isinstance(row,dict):
                continue
            try:
                stamp=float(row.get("persisted_at") or row.get("detected_at") or 0)
            except (TypeError,ValueError):
                stamp=0
            if stamp>0 and stamp<=now+300 and now-stamp<=MAX_SOURCE_AGE:
                fresh.append(row)
        return fresh
    except Exception:
        return []

def _save_persisted(market,rows):
    try:
        existing=_load_persisted(market)
        merged={}
        now=time.time()
        for r in existing+list(rows or []):
            if not isinstance(r,dict): continue
            k=(str(r.get("symbol") or "").upper(),str(r.get("direction") or r.get("side") or "").upper())
            if not k[0] or k[1] not in {"BUY","SELL"}: continue
            item=dict(r)
            try:
                stamp=float(item.get("persisted_at") or item.get("detected_at") or 0)
            except (TypeError,ValueError):
                stamp=0
            if stamp<=0 or stamp>now+300:
                stamp=now
            item["persisted_at"]=stamp
            merged[k]=item
        out=list(merged.values())[-PERSIST_LIMIT:]
        tmp=_persist_path(market)+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(out,f,ensure_ascii=False,separators=(",",":"))
        os.replace(tmp,_persist_path(market))
    except Exception as exc:
        print("[PERSIST] save failed",market,str(exc)[:160],flush=True)



MARKET_QUERIES={
 "spot":["crypto trading signal entry take profit stop loss","crypto buy signal entry tp sl","crypto signal BUY SELL LONG SHORT today","BTC ETH SOL XRP trading signal entry target stop loss","BTCUSDT ETHUSDT altcoin signal entry take profit stop loss","Binance crypto signal today","altcoin buy sell signal today","site:tradingview.com/ideas crypto buy sell signal today","site:reddit.com crypto trading signal entry target stop loss today","site:stocktwits.com crypto bullish bearish signal today","site:cointelegraph.com crypto price prediction buy sell today","site:investing.com/analysis cryptocurrency buy sell today"],
 "futures":["crypto futures recommendation LONG SHORT today","Binance futures recommendation today","BTC ETH futures long short signal","crypto futures signal entry take profit stop loss","Binance futures LONG SHORT signal today","altcoin futures signal today","site:tradingview.com/ideas BTCUSDT LONG SHORT futures today","site:reddit.com/r/binancefutures futures signal LONG SHORT today","site:coinglass.com crypto futures long short signal today"],
 "us":["US stock recommendation BUY SELL today","US stock picks today buy sell","NASDAQ stock recommendation today","NYSE stock recommendation today","US stocks trading signal entry target stop loss","AAPL NVDA TSLA AMD stock signal today","site:tradingview.com/ideas stocks buy sell today","site:reddit.com/r/stocks stock pick BUY SELL today","site:stocktwits.com market bullish bearish stock today","site:investing.com/analysis stocks buy sell today","site:seekingalpha.com stock buy sell rating today"],
 "saudi":["توصية تداول تاسي شراء بيع اليوم","السوق السعودي توصيات أسهم اليوم","توصيات تداول السوق السعودي اليوم","توصيات أسهم سعودية شراء بيع اليوم","توصيات تاسي دخول هدف وقف اليوم","أفضل توصيات الأسهم السعودية اليوم","site:tradingview.com/ideas السعودية تاسي سهم شراء بيع","site:argaam.com توصيات أسهم السعودية اليوم","site:sa.investing.com توصيات الأسهم السعودية شراء بيع"],
 "contracts":["ES=F","NQ=F","YM=F","RTY=F","CL=F","NG=F","ZB=F","ZN=F","S&P 500 futures LONG SHORT signal today","Nasdaq futures trading signal entry target stop loss","gold crude oil futures BUY SELL signal today","site:tradingview.com/ideas ES1! NQ1! futures today","site:reddit.com futures trading signal ES NQ today"],
 "forex":["forex recommendation BUY SELL today","forex trading signal entry target stop loss today","EURUSD GBPUSD USDJPY recommendation today","EURUSD signal today","GBPUSD signal today","USDJPY signal today","XAUUSD gold signal BUY SELL today","site:tradingview.com/ideas forex signal today","site:fxstreet.com forex forecast buy sell today","site:investing.com/analysis forex buy sell today","site:reddit.com/r/Forex trading signal EURUSD today"],
 "gold":["XAUUSD gold trading signal today buy sell","gold price forecast entry target stop loss today","gold futures GC=F LONG SHORT signal today","XAUUSD buy sell signal entry target stop loss","site:tradingview.com/ideas XAUUSD gold signal today","site:investing.com/analysis gold price forecast today","site:fxstreet.com gold price forecast XAUUSD today","site:reddit.com gold trading signal XAUUSD today"],
 "alpha":["Binance Alpha token buy sell signal today","Binance Alpha token recommendation entry target stop loss","Binance Alpha new token analysis today","site:binance.com/en/alpha token listing today"]
}

# Expanded source discovery for broader coverage across market-specific communities and publishers.
MARKET_QUERIES["spot"] += [
 "altcoin market analysis today volume breakout cryptocurrency",
 "crypto analyst picks today BTC ETH SOL XRP",
 "site:cryptopanic.com crypto bullish bearish market today",
 "site:coinmarketcap.com/community crypto token analysis today"
]
MARKET_QUERIES["futures"] += [
 "perpetual futures open interest funding rate trading setup today",
 "BTC ETH SOL perpetual futures analysis long short today",
 "site:cryptoslate.com crypto futures market analysis",
 "site:coingape.com crypto price prediction today"
]
MARKET_QUERIES["us"] += [
 "large cap US stocks analyst upgrades downgrades today",
 "US stocks unusual volume breakout analysis today",
 "site:marketwatch.com investing stocks analyst rating today",
 "site:finance.yahoo.com/news stock analyst price target today"
]
MARKET_QUERIES["saudi"] += [
 "تحليل فني أسهم تاسي اليوم دعم مقاومة",
 "السوق السعودي أسهم نشاط تداول اليوم تحليل",
 "site:aleqt.com الأسهم السعودية تحليل اليوم",
 "site:argaam.com السوق السعودي نتائج الشركات اليوم"
]
MARKET_QUERIES["contracts"] += [
 "E-mini Nasdaq S&P futures market outlook today",
 "WTI crude oil natural gas futures outlook today",
 "Treasury futures trading analysis today",
 "site:cmegroup.com market commentary futures today"
]
MARKET_QUERIES["forex"] += [
 "forex market outlook economic calendar currency pairs today",
 "EURUSD GBPUSD USDJPY technical outlook today",
 "site:dailyfx.com forex technical analysis today",
 "site:forexlive.com currency market analysis today"
]
MARKET_QUERIES["gold"] += [
 "XAUUSD gold price technical outlook today",
 "gold market analysis support resistance today",
 "site:kitco.com gold price analysis today",
 "site:gold.org gold market commentary"
]
MARKET_QUERIES["alpha"] += [
 "Binance Alpha new listings token ecosystem analysis",
 "Binance Alpha token volume price action today"
]

# Syntax-checked baseline universes: external recommendations confirm the setup, but do not decide
# which instruments are eligible for analysis. This prevents empty markets when news has no ticker.
BASE_UNIVERSE={
 "us":["AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","AVGO","AMD","NFLX","JPM","V","MA","COST","WMT","ORCL","CRM","PLTR","INTC","QCOM","MU","AMAT","ADBE","CSCO","IBM","GE","CAT","BA","DIS","UBER","COIN","MSTR","BAC","GS","MS","XOM","CVX","LLY","JNJ","PFE","ABBV","UNH","HD","LOW","TMO","LIN","NKE","PEP","KO","SMCI","ARM","MELI","CRWD","PANW","NOW","SNOW","SHOP","PYPL","SQ","SOFI","HOOD","RBLX","ABNB","DASH","PDD","BABA","JD","NIO","LI","XPEV","MRVL","ON","LRCX","KLAC","TXN","ADI","INTU","ISRG","VRTX","AMGN","GILD","MRK","BMY","CVS","T","VZ","CMCSA","COP","SLB","EOG","OXY","DE","MMM","HON","RTX","LMT","GM","F","TGT","SBUX","MCD","HD","LOW","BKNG","SPOT","ROKU","RIVN"],
 "saudi":["2222","1120","2010","1180","1150","1211","2020","7010","7020","2280","2050","3030","4003","4190","4261","4280","4300","4321","4331","2223","2082","2083","2084","2081","2080","2082","2083","2084","2081","2080","4001","4002","4005","4007","4008","4009","4013","4014","4015","4017","4018","4020","4030","4031","4040","4050","4061","4071","4081","4090","4100","4110","4130","4140","4150","4160","4170","4180","4200","4210","4220","4230","4240","4250","4260","4270","4290","4310","4322","4330","4340","4342","4344","4345","4346","4347","4348","4349","4350","5110","6001","6010","6020","6040","6050","6060","6070","6090","7010","7020","7030","7040","7200","7201","7202","7203","7204","7207","7208","7209","7210","7211","8010","8012","8020","8030","8040","8050","8060","8070","8100","8120","8150","8160","8170","8180","8190","8200","8210","8230","8240","8250","8260","8270","8280","8300","8310","8311","8312","9510","9512","9513","9514","9515","9516","9517","9518","9520","9521","9522","9523","9524","9525","9526","9527","9528","9529","9530","9531","9532","9533","9534","9535","9536","9537","9538","9539","9540","9541","9542","9543","9544","9545","9546","9547","9548","9549"],
 "contracts":["ES=F","NQ=F","YM=F","RTY=F","CL=F","NG=F","GC=F","SI=F","HG=F","ZB=F","ZN=F","ZF=F","ZC=F","ZS=F","ZW=F","6E=F","6B=F","6J=F","6A=F","6C=F"],
 "forex":["XAUUSD","XAGUSD","EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","EURGBP","EURJPY","GBPJPY","EURAUD","EURCAD","EURNZD","EURCHF","GBPCHF","GBPAUD","GBPCAD","GBPNZD","AUDJPY","AUDCAD","AUDNZD","CADJPY","CHFJPY","NZDJPY","USDSEK","USDNOK","USDZAR","USDMXN","USDTRY","USDPLN","USDHUF","USDHKD","USDSGD","USDCNH"]
}
BINANCE_SPOT="https://api.binance.com"; BINANCE_FUTURES="https://fapi.binance.com"; YAHOO="https://query1.finance.yahoo.com"

def _fetch(url,timeout=FETCH_TIMEOUT):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json,application/rss+xml,text/xml,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()
def _json(url,timeout=FETCH_TIMEOUT): return json.loads(_fetch(url,timeout).decode("utf-8","ignore"))

def _parse_news_xml(raw):
    try:root=ET.fromstring(raw)
    except Exception:return []
    out=[]
    for x in root.findall(".//item"):
        out.append({"title":html.unescape(x.findtext("title") or ""),"text":html.unescape(re.sub("<[^>]+>"," ",x.findtext("description") or "")),"url":x.findtext("link") or "","published":x.findtext("pubDate") or ""})
    return out[:60]

def _news(q):
    # Strict 24-hour search window. Merge all providers instead of returning
    # the first non-empty feed, so recommendation coverage is broad.
    # Search two indexes and a second regional Google News feed; merge/dedupe below.
    # Multi-region discovery: Google News US/UK/Canada/Australia + Saudi Arabic and Bing.
    # Results are deduplicated by article URL and filtered to the recent research window below.
    urls=[
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:2d","hl":"en-US","gl":"US","ceid":"US:en"}),
        "https://www.bing.com/news/search?"+urllib.parse.urlencode({"q":q,"format":"rss","freshness":"Week"}),
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:2d","hl":"en-GB","gl":"GB","ceid":"GB:en"}),
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:2d","hl":"en-CA","gl":"CA","ceid":"CA:en"}),
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:2d","hl":"en-AU","gl":"AU","ceid":"AU:en"}),
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:2d","hl":"ar","gl":"SA","ceid":"SA:ar"})
    ]
    cutoff=time.time()-MAX_SOURCE_AGE
    merged=[]; seen=set(); now=time.time()
    # Query regional indexes concurrently to keep the loading state short while
    # retaining multiple independent news/search sources.
    def fetch_feed(url):
        try:return _parse_news_xml(_fetch(url))
        except Exception:return []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for hits in pool.map(fetch_feed,urls):
            for h in hits:
                published=h.get("published") or ""
                try:ts=parsedate_to_datetime(published).timestamp()
                except Exception:continue
                if ts < cutoff or ts > now+300:continue
                h=dict(h); h["published_ts"]=ts
                key=(h.get("url") or "").strip().lower() or re.sub(r"\s+"," ",str(h.get("title") or "").strip().lower())
                if not key or key in seen:continue
                seen.add(key); merged.append(h)
    merged.sort(key=lambda x:float(x.get("published_ts") or 0),reverse=True)
    return merged[:100]

def _article(url):
    if not url:return ""
    key="article:"+url; now=time.time(); c=CACHE.get(key)
    if c and now-c[0]<1800:return c[1]
    try:
        s=_fetch(url,4).decode("utf-8","ignore")
        s=re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>"," ",s)
        s=re.sub(r"(?is)<[^>]+>"," ",s); s=html.unescape(s); s=re.sub(r"\s+"," ",s).strip()[:25000]
    except Exception:s=""
    CACHE[key]=(now,s); return s

def _symbol(text,market):
    t=str(text or "").upper()

    if market in ("spot","futures"):
        aliases={
            "BITCOIN":"BTCUSDT","BTC":"BTCUSDT","ETHEREUM":"ETHUSDT","ETH":"ETHUSDT",
            "SOLANA":"SOLUSDT","SOL":"SOLUSDT","RIPPLE":"XRPUSDT","XRP":"XRPUSDT",
            "BINANCE COIN":"BNBUSDT","BNB":"BNBUSDT","DOGECOIN":"DOGEUSDT","DOGE":"DOGEUSDT",
            "CARDANO":"ADAUSDT","ADA":"ADAUSDT","AVALANCHE":"AVAXUSDT","AVAX":"AVAXUSDT",
            "TRON":"TRXUSDT","TRX":"TRXUSDT","CHAINLINK":"LINKUSDT","LINK":"LINKUSDT",
            "POLKADOT":"DOTUSDT","DOT":"DOTUSDT","LITECOIN":"LTCUSDT","LTC":"LTCUSDT",
            "BITCOIN CASH":"BCHUSDT","BCH":"BCHUSDT","UNISWAP":"UNIUSDT","UNI":"UNIUSDT",
            "COSMOS":"ATOMUSDT","ATOM":"ATOMUSDT","NEAR PROTOCOL":"NEARUSDT","NEAR":"NEARUSDT",
            "FILECOIN":"FILUSDT","FIL":"FILUSDT","APTOS":"APTUSDT","APT":"APTUSDT",
            "ARBITRUM":"ARBUSDT","ARB":"ARBUSDT","OPTIMISM":"OPUSDT","OP":"OPUSDT",
            "SUI":"SUIUSDT","PEPE":"PEPEUSDT","SHIBA INU":"SHIBUSDT","SHIB":"SHIBUSDT",
            "STELLAR":"XLMUSDT","XLM":"XLMUSDT","ALGORAND":"ALGOUSDT","ALGO":"ALGOUSDT",
            "INJECTIVE":"INJUSDT","INJ":"INJUSDT","RENDER":"RENDERUSDT","SEI":"SEIUSDT","TON":"TONUSDT",
            "HYPERLIQUID":"HYPEUSDT","HYPE":"HYPEUSDT","BONK":"BONKUSDT","WIF":"WIFUSDT",
            "FLOKI":"FLOKIUSDT","FET":"FETUSDT","TAO":"TAOUSDT","IMX":"IMXUSDT"
        }
        # Accept BTCUSDT, BTC/USDT, BTC-USDT, and $BTC. The previous version
        # accidentally used a literal "\b", so normal ticker text was missed.
        m=re.search(r"\b([A-Z0-9]{2,20})\s*(?:/|-)\s*USDT\b",t) or re.search(r"\b([A-Z0-9]{2,20})USDT\b",t)
        if m:return m.group(1)+"USDT"
        m=re.search(r"\$([A-Z0-9]{2,20})\b",t)
        if m and m.group(1) not in {"USDT","USD"}:return m.group(1)+"USDT"
        for name,sym in sorted(aliases.items(),key=lambda z:-len(z[0])):
            if re.search(r"\b"+re.escape(name)+r"\b",t):return sym

    if market=="us":
        aliases={
            "APPLE":"AAPL","MICROSOFT":"MSFT","NVIDIA":"NVDA","AMAZON":"AMZN","ALPHABET":"GOOGL",
            "GOOGLE":"GOOGL","META":"META","FACEBOOK":"META","TESLA":"TSLA","BROADCOM":"AVGO",
            "NETFLIX":"NFLX","PALANTIR":"PLTR","COINBASE":"COIN","MICROSTRATEGY":"MSTR",
            "JPMORGAN":"JPM","BANK OF AMERICA":"BAC","WALMART":"WMT","COSTCO":"COST",
            "ORACLE":"ORCL","SALESFORCE":"CRM","INTEL":"INTC","QUALCOMM":"QCOM","DISNEY":"DIS","UBER":"UBER"
        }
        for name,sym in aliases.items():
            if re.search(r"\b"+re.escape(name)+r"\b",t):return sym
        m=re.search(r"\$([A-Z]{1,5})\b",t) or re.search(r"\b(?:NASDAQ|NYSE|NYSEARCA)[:\s]+([A-Z]{1,5})\b",t)
        if m and m.group(1) not in {"BUY","SELL","LONG","SHORT","CALL","PUT","STOCK","SIGNAL","TODAY"}:
            return m.group(1)
        for sym in BASE_UNIVERSE.get("us",[]):
            if re.search(r"\b"+re.escape(sym)+r"\b",t):return sym
        return None

    if market=="saudi":
        aliases={
            "الراجحي":"1120","الراجحيه":"1120","أرامكو":"2222","ارامكو":"2222","سابك":"2010",
            "الأهلي":"1180","الاهلي":"1180","الإنماء":"1150","الانماء":"1150","معادن":"1211",
            "STC":"7010","اس تي سي":"7010","المراعي":"2280","جرير":"4190","دار الأركان":"4300"
        }
        for name,sym in aliases.items():
            if re.search(re.escape(name),t,re.I):return sym
        m=re.search(r"\b(\d{4})\b",t)
        return m.group(1) if m else None

    if market=="contracts":
        aliases={"E-MINI S&P":"ES","S&P 500 FUTURES":"ES","ES=F":"ES","ES":"ES","NASDAQ 100 FUTURES":"NQ","NASDAQ FUTURES":"NQ","NQ=F":"NQ","NQ":"NQ","NAS100":"NQ","DOW JONES FUTURES":"YM","DOW FUTURES":"YM","YM=F":"YM","YM":"YM","US30":"YM","RUSSELL 2000 FUTURES":"RTY","RUSSELL FUTURES":"RTY","RTY=F":"RTY","RTY":"RTY","WTI":"WTI","USOIL":"WTI","CRUDE OIL":"WTI","OIL":"WTI","نفط":"WTI","CL=F":"WTI","NATURAL GAS":"NG","NAT GAS":"NG","NG=F":"NG","NG":"NG","GOLD FUTURES":"GC","GC=F":"GC","GC":"GC","SILVER FUTURES":"SI","SI=F":"SI","SI":"SI","COPPER FUTURES":"HG","HG=F":"HG","HG":"HG","30 YEAR TREASURY":"ZB","TREASURY BOND FUTURES":"ZB","ZB=F":"ZB","ZB":"ZB","10 YEAR TREASURY":"ZN","10Y TREASURY":"ZN","ZN=F":"ZN","ZN":"ZN","5 YEAR TREASURY":"ZF","ZF=F":"ZF","ZF":"ZF","CORN FUTURES":"ZC","ZC=F":"ZC","ZC":"ZC","SOYBEAN FUTURES":"ZS","ZS=F":"ZS","ZS":"ZS","WHEAT FUTURES":"ZW","ZW=F":"ZW","ZW":"ZW","EURO FX":"6E","6E=F":"6E","6E":"6E","BRITISH POUND":"6B","6B=F":"6B","6B":"6B","JAPANESE YEN":"6J","6J=F":"6J","6J":"6J","AUSTRALIAN DOLLAR":"6A","6A=F":"6A","6A":"6A","CANADIAN DOLLAR":"6C","6C=F":"6C","6C":"6C"}
        for name,sym in sorted(aliases.items(),key=lambda z:-len(z[0])):
            if re.search(re.escape(name),t,re.I):return sym
        return None

    if market in ("forex","gold"):
        aliases={"الذهب":"XAUUSD","ذهب":"XAUUSD","GOLD":"XAUUSD","XAUUSD":"XAUUSD","اليورو دولار":"EURUSD","يورو دولار":"EURUSD","الباوند دولار":"GBPUSD","جنيه دولار":"GBPUSD","دولار ين":"USDJPY"}
        for name,sym in aliases.items():
            if name in t:return sym
        m=re.search(r"\b([A-Z]{3}\s*/?\s*[A-Z]{3})\b",t)
        return m.group(1).replace(" ","").replace("/","") if m else None
    return None

def _direction(text):
    t=text.upper()
    b=re.findall(r"\b(BUY|LONG|BULLISH|UPGRADE|OUTPERFORM|OVERWEIGHT|BUYING|RALLY|RALLIES|SURGE|SURGES|RISE|RISES|RISING|GAINS|GAINING|HIGHER|UPSIDE|POSITIVE|شراء|صعود|صاعد|يرتفع|ارتفاع|إيجابي|إيجابية)\b",t); s=re.findall(r"\b(SELL|SHORT|BEARISH|DOWNGRADE|UNDERPERFORM|UNDERWEIGHT|SELLING|SLUMP|SLUMPS|DROP|DROPS|FALL|FALLS|FALLING|DECLINE|DECLINES|DECLINING|LOWER|DOWNSIDE|NEGATIVE|بيع|هبوط|هابط|ينخفض|انخفاض|سلبي|سلبية)\b",t)
    return "BUY" if b and not s else "SELL" if s and not b else None

def _internet(market):
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as p:
        fs=[p.submit(_news,q) for q in MARKET_QUERIES.get(market,[])]
        for f in as_completed(fs):
            try:hits=f.result()
            except Exception:hits=[]
            for h in hits:
                # Do not download every article: that can block the API when a feed
                # returns many stories. Fetch the article only for likely trade signals.
                base=(h["title"]+" "+h["text"]).strip()
                signal_words=("entry","tp","take profit","stop loss","target","targets","sl","buy","sell","long","short","bullish","bearish","forecast","outlook","analyst","upgrade","downgrade","price prediction","price target","شراء","بيع","دخول","هدف","وقف","توقعات","نظرة","السعر المستهدف")
                full=base
                if any(w in base.lower() for w in signal_words):
                    full=base+" "+_article(h["url"])
                sym=_symbol(full,market) or _symbol(base,market)
                # Headlines are usually more directional than article text, which may
                # discuss both outcomes. Fall back to the summary, then full article.
                d=_direction(h.get("title","")) or _direction(h.get("text","")) or _direction(full)
                if sym and d:rows.append({"symbol":sym,"direction":d,"source_title":h["title"],"source_published":h["published"],"source_url":h["url"],"source_text":full})
    seen=set(); out=[]
    for r in rows:
        k=(r["symbol"],r["direction"],(r.get("source_url") or "").strip().lower() or r.get("source_title","").strip().lower())
        if k not in seen:
            seen.add(k);out.append(r)
    return out

def _binance24(futures=False):
    u=(BINANCE_FUTURES+"/fapi/v1/ticker/24hr") if futures else (BINANCE_SPOT+"/api/v3/ticker/24hr")
    try:return _json(u,5)
    except Exception:return []

def _crypto_universe(market):
    out=[]
    for x in _binance24(market=="futures"):
        s=str(x.get("symbol","")).upper()
        if not s.endswith("USDT") or s in {"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","BUSDUSDT"}:continue
        try:v=float(x.get("quoteVolume") or 0)
        except:v=0
        if v>=MIN_CRYPTO_QUOTE_VOLUME:out.append((s,v))
    return sorted(out,key=lambda z:z[1],reverse=True)

def _crypto_klines(symbol,market,interval="15m",limit=260):
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    try:return _json(base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":limit}),6)
    except Exception:return []

def _yahoo(symbol,market,interval="15m",limit=260):
    # Map weekly/monthly native intervals and synthesize intraday frames where needed.
    if interval=="3m":
        one_minute=_yahoo(symbol,market,"1m",min(1000,limit*3))
        out=[]
        for i in range(0,len(one_minute)-2,3):
            group=one_minute[i:i+3]
            if len(group)==3:
                out.append({"open":group[0]["open"],"high":max(z["high"] for z in group),"low":min(z["low"] for z in group),"close":group[-1]["close"],"volume":sum(z["volume"] for z in group)})
        return out[-limit:]
    if interval=="4h":
        hourly=_yahoo(symbol,market,"1h",min(240,limit*4))
        out=[]
        for i in range(0,len(hourly)-3,4):
            group=hourly[i:i+4]
            if len(group)==4:
                out.append({"open":group[0]["open"],"high":max(z["high"] for z in group),"low":min(z["low"] for z in group),"close":group[-1]["close"],"volume":sum(z["volume"] for z in group)})
        return out[-limit:]
    api_interval={"1w":"1wk","1M":"1mo"}.get(interval,interval)
    # Yahoo symbol mapping + redundant hosts/ranges.
    y={
        "us":symbol,
        "saudi":("^TASI" if str(symbol).upper() in {"TASI","^TASI"} else (symbol[:-3] if str(symbol).upper().endswith(".SR") else str(symbol))+".SR"),
        "contracts":{"ES":"ES=F","NQ":"NQ=F","YM":"YM=F","RTY":"RTY=F","WTI":"CL=F","NG":"NG=F","GC":"GC=F","SI":"SI=F","HG":"HG=F","ZB":"ZB=F","ZN":"ZN=F","ZF":"ZF=F","ZC":"ZC=F","ZS":"ZS=F","ZW":"ZW=F","6E":"6E=F","6B":"6B=F","6J":"6J=F","6A":"6A=F","6C":"6C=F"}.get(symbol,symbol),
        "forex":("GC=F" if str(symbol).upper()=="XAUUSD" else "SI=F" if str(symbol).upper()=="XAGUSD" else symbol[:3]+symbol[3:]+"=X"),
        "gold":"GC=F" if str(symbol).upper() in {"XAUUSD","GOLD","GC"} else symbol[:3]+symbol[3:]+"=X"
    }.get(market,symbol)
    hosts=("https://query1.finance.yahoo.com","https://query2.finance.yahoo.com")
    ranges=("10y","5y","2y") if interval=="1M" else ("5y","2y","1y") if interval=="1w" else ("7d","5d","1d") if interval=="1m" else ("60d","30d","10d")
    for host in hosts:
        for rg in ranges:
            try:
                url=host+"/v8/finance/chart/"+urllib.parse.quote(y,safe="")+"?"+urllib.parse.urlencode({"interval":api_interval,"range":rg})
                d=_json(url,6)
                r=(d.get("chart",{}).get("result") or [None])[0]
                if not r: continue
                q=((r.get("indicators",{}).get("quote") or [{}])[0])
                out=[]
                for o,h,l,cl,v in zip(q.get("open",[]),q.get("high",[]),q.get("low",[]),q.get("close",[]),q.get("volume",[])):
                    if None not in (o,h,l,cl):
                        out.append({"open":float(o),"high":float(h),"low":float(l),"close":float(cl),"volume":float(v or 0)})
                if out: return out[-limit:]
            except Exception:
                continue
    return []

def _candles(raw):
    out=[]
    for x in raw:
        try:
            out.append(x if isinstance(x,dict) else {"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except Exception:pass
    return out

# ============================================================
# PURE ANALYSIS METHODS — NO EMA / RSI / MACD / STOCH / OTHER INDICATORS
# ============================================================
def _valid_ohlcv(c, min_count=32):
    """Reject incomplete, non-finite, or internally inconsistent OHLCV candles."""
    if not isinstance(c, (list, tuple)) or len(c) < min_count:
        return False
    try:
        for row in c:
            if not isinstance(row, dict):
                return False
            o, h, l, close, volume = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))
            if not all(math.isfinite(v) for v in (o, h, l, close, volume)):
                return False
            if l <= 0 or h <= 0 or volume < 0 or h < l:
                return False
            # Small tolerance permits floating-point rounding from providers.
            tol = max(abs(h), abs(l), 1.0) * 1e-10
            if o < l - tol or o > h + tol or close < l - tol or close > h + tol:
                return False
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return True


def _method_analysis(c):
    if not _valid_ohlcv(c):return None
    c=[{k:float(row[k]) for k in ("open","high","low","close","volume")} for row in c]
    price=c[-1]["close"]; highs=[x["high"] for x in c]; lows=[x["low"] for x in c]; closes=[x["close"] for x in c]
    vols=[x["volume"] for x in c]

    # Pure chart-method engine: no RSI, MACD, EMA, MA, Stoch or other indicators.
    # Each methodology reads only price, candles, swings, ranges and raw volume.
    def sign(x): return 1 if x>0 else -1 if x<0 else 0

    # 1) Dow / market structure: HH+HL vs LH+LL.
    sh=[]; sl=[]
    for i in range(2,len(c)-2):
        if highs[i]>=max(highs[i-2:i+3]): sh.append((i,highs[i]))
        if lows[i]<=min(lows[i-2:i+3]): sl.append((i,lows[i]))
    dow=1 if len(sh)>=2 and len(sl)>=2 and sh[-1][1]>sh[-2][1] and sl[-1][1]>sl[-2][1] else -1 if len(sh)>=2 and len(sl)>=2 and sh[-1][1]<sh[-2][1] and sl[-1][1]<sl[-2][1] else 0

    # 2) Price action / swing displacement.
    pa=sign(price-closes[-8])

    # 3) Support / resistance reaction.
    support=min(lows[-30:]); resistance=max(highs[-30:])
    span=max(resistance-support,price*0.0001)
    near_support=abs(price-support)/span<.18
    near_resistance=abs(price-resistance)/span<.18
    cur=c[-1]; prev=c[-2]
    body=abs(cur["close"]-cur["open"]); rng=max(cur["high"]-cur["low"],1e-12)
    upper=cur["high"]-max(cur["open"],cur["close"]); lower=min(cur["open"],cur["close"])-cur["low"]
    sr=1 if near_support and (cur["close"]>=cur["open"] or lower>body*1.5) else -1 if near_resistance and (cur["close"]<=cur["open"] or upper>body*1.5) else 0

    # 4) Candlestick methodology: rejection + engulfing.
    bull_eng=prev["close"]<prev["open"] and cur["close"]>cur["open"] and cur["close"]>=prev["open"] and cur["open"]<=prev["close"]
    bear_eng=prev["close"]>prev["open"] and cur["close"]<cur["open"] and cur["close"]<=prev["open"] and cur["open"]>=prev["close"]
    candle=1 if bull_eng or (cur["close"]>cur["open"] and (body/rng>=.55 or lower>body*2)) else -1 if bear_eng or (cur["close"]<cur["open"] and (body/rng>=.55 or upper>body*2)) else 0

    # 5) Breakout / breakdown.
    prior_hi=max(highs[-21:-1]); prior_lo=min(lows[-21:-1])
    breakout=1 if price>prior_hi else -1 if price<prior_lo else 0

    # 6) Breakout-retest / failed-break.
    retest=0
    old_hi=max(highs[-24:-4]); old_lo=min(lows[-24:-4])
    if max(highs[-4:])>old_hi and abs(price-old_hi)/max(price,1)<.008: retest=1
    elif min(lows[-4:])<old_lo and abs(price-old_lo)/max(price,1)<.008: retest=-1
    elif max(highs[-4:])>old_hi and price<old_hi: retest=-1
    elif min(lows[-4:])<old_lo and price>old_lo: retest=1

    # 7) Wyckoff-style accumulation/distribution: range, spring/upthrust, effort/result.
    range_hi=max(highs[-25:-5]); range_lo=min(lows[-25:-5])
    spring=min(lows[-5:])<range_lo and price>range_lo
    upthrust=max(highs[-5:])>range_hi and price<range_hi
    avg_vol=sum(vols[-21:-1])/max(1,len(vols[-21:-1]))
    effort=vols[-1]>avg_vol*1.25
    wyckoff=1 if spring and (effort or lower>body) else -1 if upthrust and (effort or upper>body) else 0

    # 8) Elliott-style wave structure: recent impulse has directional higher/lower swings.
    e_up=sum(1 for i in range(-5,0) if closes[i]>closes[i-1])
    e_dn=sum(1 for i in range(-5,0) if closes[i]<closes[i-1])
    elliott=1 if e_up>=4 and price>closes[-6] else -1 if e_dn>=4 and price<closes[-6] else 0

    # 9) Smart Money / market-structure break (BOS/CHoCH), raw swings only.
    bos_hi=max(highs[-12:-2]); bos_lo=min(lows[-12:-2])
    smc=1 if price>bos_hi else -1 if price<bos_lo else 0

    # 10) ICT-style liquidity sweep: take prior equal extreme then reclaim.
    liq_tol=max(price*.0015,span*.025)
    equal_hi=abs(max(highs[-8:-1])-max(highs[-16:-8]))<=liq_tol
    equal_lo=abs(min(lows[-8:-1])-min(lows[-16:-8]))<=liq_tol
    ict=1 if equal_lo and lows[-1]<min(lows[-8:-1]) and price>min(lows[-8:-1]) else -1 if equal_hi and highs[-1]>max(highs[-8:-1]) and price<max(highs[-8:-1]) else 0

    # 11) Fibonacci-style retracement/extension zones from the latest raw swing.
    swing_hi=max(highs[-30:]); swing_lo=min(lows[-30:]); fib_range=max(swing_hi-swing_lo,price*.0001)
    fib38=swing_hi-fib_range*.382; fib62=swing_hi-fib_range*.618
    fib_up38=swing_lo+fib_range*.382; fib_up62=swing_lo+fib_range*.618
    fib=1 if fib62<=price<=fib38 and price>closes[-3] else -1 if fib_up38<=price<=fib_up62 and price<closes[-3] else 0

    # 12) Classical chart pattern / channel pressure using raw highs and lows.
    first_hi=max(highs[-16:-8]); second_hi=max(highs[-8:])
    first_lo=min(lows[-16:-8]); second_lo=min(lows[-8:])
    pattern=1 if second_hi>first_hi and second_lo>first_lo else -1 if second_hi<first_hi and second_lo<first_lo else 0

    # 13) Raw volume / effort-result confirmation (volume itself, not an indicator).
    volume_confirm=1 if effort and candle>=0 else -1 if effort and candle<0 else 0

    # 14) Approximate Volume Profile from candle close x volume (not tick-level traded volume).
    # Use a fixed histogram over recent typical closes and identify the point-of-control bin.
    vp_n=min(100,len(c))
    vp_lows=lows[-vp_n:]; vp_highs=highs[-vp_n:]; vp_closes=closes[-vp_n:]; vp_vols=vols[-vp_n:]
    vp_min=min(vp_lows); vp_max=max(vp_highs); vp_span=max(vp_max-vp_min,price*.0001)
    vp_bins=24; vp_hist=[0.0]*vp_bins
    for px,v in zip(vp_closes,vp_vols):
        bi=max(0,min(vp_bins-1,int((px-vp_min)/vp_span*vp_bins)))
        vp_hist[bi]+=max(0.0,float(v))
    vp_poc=vp_min+(vp_hist.index(max(vp_hist))+.5)*vp_span/vp_bins
    volume_profile=1 if price>vp_poc and price>closes[-4] else -1 if price<vp_poc and price<closes[-4] else 0

    # 15) Market regime: efficiency ratio separates directional movement from noisy/ranging action.
    regime_n=min(20,len(closes)-1)
    path=sum(abs(closes[-i]-closes[-i-1]) for i in range(1,regime_n+1))
    net=closes[-1]-closes[-regime_n-1]
    efficiency=abs(net)/max(path,1e-12)
    market_regime=1 if efficiency>=0.38 and net>0 else -1 if efficiency>=0.38 and net<0 else 0

    # 16) Ichimoku cloud direction using raw highs/lows; only available with 52+ candles.
    ichimoku=0
    if len(c)>=52:
        tenkan=(max(highs[-9:])+min(lows[-9:]))/2
        kijun=(max(highs[-26:])+min(lows[-26:]))/2
        span_a=(tenkan+kijun)/2
        span_b=(max(highs[-52:])+min(lows[-52:]))/2
        cloud_top=max(span_a,span_b); cloud_bottom=min(span_a,span_b)
        ichimoku=1 if price>cloud_top and tenkan>kijun else -1 if price<cloud_bottom and tenkan<kijun else 0

    votes=[dow,pa,sr,candle,breakout,retest,wyckoff,elliott,smc,ict,fib,pattern,volume_confirm,volume_profile,market_regime,ichimoku]
    bull=sum(v>0 for v in votes); bear=sum(v<0 for v in votes)
    side="BUY" if bull>bear and bull>=4 else "SELL" if bear>bull and bear>=4 else "WAIT"
    agreement=max(bull,bear)/len(votes)*100
    risk=max(price*.008,abs(price-(support if side=="BUY" else resistance))*.45 if side!="WAIT" else price*.008)
    if side=="BUY": sl=price-risk; tp1=price+risk; tp2=price+risk*2; tp3=price+risk*3
    elif side=="SELL": sl=price+risk; tp1=price-risk; tp2=price-risk*2; tp3=price-risk*3
    else: sl=tp1=tp2=tp3=price
    return {"side":side,"price":price,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
            "targets":[tp1,tp2,tp3],"site_score":round(agreement,1),"trend":"صاعد" if dow>0 else "هابط" if dow<0 else "عرضي",
            "support":support,"resistance":resistance,
            "methods":{"dow":dow,"price_action":pa,"support_resistance":sr,"candlestick":candle,"breakout":breakout,
            "retest":retest,"wyckoff":wyckoff,"elliott":elliott,"smc":smc,"ict_liquidity":ict,"fibonacci":fib,
            "chart_pattern":pattern,"raw_volume":volume_confirm,"volume_profile":volume_profile,"market_regime":market_regime,"ichimoku":ichimoku}}
def _ict_sma20_gate(c):
    """Same-timeframe MA20/MA200 trend gate; stronger structure raises signal grade."""
    if len(c)<200:return None
    closes=[float(x["close"]) for x in c]
    highs=[float(x["high"]) for x in c]
    lows=[float(x["low"]) for x in c]
    opens=[float(x["open"]) for x in c]
    price=closes[-1]
    sma20=sum(closes[-20:])/20.0
    sma200=sum(closes[-200:])/200.0
    prior_sma20=sum(closes[-25:-5])/20.0
    slope_up=sma20>prior_sma20
    slope_down=sma20<prior_sma20
    recent_up=closes[-1]>closes[-2] and closes[-2]>=closes[-3]
    recent_down=closes[-1]<closes[-2] and closes[-2]<=closes[-3]
    higher_lows=min(lows[-3:])>min(lows[-6:-3])
    lower_highs=max(highs[-3:])<max(highs[-6:-3])
    prior_high=max(highs[-12:-2]); prior_low=min(lows[-12:-2])
    bull_bos=price>prior_high
    bear_bos=price<prior_low
    bull_fvg=lows[-1]>highs[-3]
    bear_fvg=highs[-1]<lows[-3]
    bull_sweep=lows[-1]<min(lows[-8:-1]) and price>min(lows[-8:-1])
    bear_sweep=highs[-1]>max(highs[-8:-1]) and price<max(highs[-8:-1])
    bull_ob=closes[-2]<opens[-2] and price>highs[-2] and price>closes[-2]
    bear_ob=closes[-2]>opens[-2] and price<lows[-2] and price<closes[-2]
    bull_ict=sum((bull_bos,bull_fvg,bull_sweep,bull_ob))
    bear_ict=sum((bear_bos,bear_fvg,bear_sweep,bear_ob))
    bull_momentum=sum((slope_up,recent_up,higher_lows))
    bear_momentum=sum((slope_down,recent_down,lower_highs))
    # Direction requires price to be on the matching side of BOTH averages.
    # Structure/momentum only grades the signal as regular or strong.
    if price>sma20 and price>sma200:
        strength=min(98,62+bull_ict*5+bull_momentum*5+(6 if bull_bos else 0)+(4 if bull_sweep else 0))
        return {"side":"BUY","sma20":sma20,"sma200":sma200,"ict_votes":bull_ict,"momentum_votes":bull_momentum,"strength":strength}
    if price<sma20 and price<sma200:
        strength=min(98,62+bear_ict*5+bear_momentum*5+(6 if bear_bos else 0)+(4 if bear_sweep else 0))
        return {"side":"SELL","sma20":sma20,"sma200":sma200,"ict_votes":bear_ict,"momentum_votes":bear_momentum,"strength":strength}
    return None

def _analyze_symbol(symbol,market,timeframe="15m"):
    def get(interval):
        return _candles(_crypto_klines(symbol,market,interval)) if market in ("spot","futures") else _yahoo(symbol,market,interval)
    candles=get(timeframe)
    if not _valid_ohlcv(candles, min_count=52):return None
    candles=[{k:float(row[k]) for k in ("open","high","low","close","volume")} for row in candles]
    a=_method_analysis(candles)
    if not a:return None

    # Strong-confluence engine: structure/liquidity are primary, while
    # price action, regime, volume and cloud are confirmations, not equal votes.
    methods=a.get("methods") or {}
    weights={
        "smc":2.2,"ict_liquidity":2.2,"market_regime":1.6,
        "price_action":1.4,"dow":1.3,"breakout":1.2,"retest":1.2,
        "raw_volume":1.1,"volume_profile":0.9,"ichimoku":0.9,
        "support_resistance":0.9,"wyckoff":1.0,"candlestick":0.7,
        "chart_pattern":0.7,"fibonacci":0.6,"elliott":0.5
    }
    # Hourly self-improver can adjust method influence only within a bounded range.
    try:
        from strategy_feedback import get_method_weights
        learned_weights=get_method_weights(market,timeframe)
        weights={k:weights.get(k,0.5)*learned_weights.get(k,1.0) for k in set(weights)|set(learned_weights)}
    except Exception:
        pass
    weighted=sum(weights.get(k,0.5)*max(-1,min(1,float(v or 0))) for k,v in methods.items())
    total=sum(weights.get(k,0.5) for k,v in methods.items())
    strength=abs(weighted)/max(total,1e-9)*100.0
    method_side="BUY" if weighted>0 else "SELL" if weighted<0 else "WAIT"
    bull=sum(1 for v in methods.values() if float(v or 0)>0)
    bear=sum(1 for v in methods.values() if float(v or 0)<0)

    # Keep the same-timeframe MA20/MA200 + structure/momentum gate as a trend filter.
    gate=_ict_sma20_gate(candles)
    if not gate or method_side=="WAIT":return None
    if method_side!=gate["side"]:return None

    # Require actual structure/liquidity evidence plus broad confluence.
    core=sum(1 for k in ("smc","ict_liquidity","breakout","retest") if float(methods.get(k) or 0)==(1 if method_side=="BUY" else -1))
    aligned=bull if method_side=="BUY" else bear
    opposing=bear if method_side=="BUY" else bull
    # Publish regular-grade setups when three or more independent candle methods align.
    # Stronger setups naturally rank higher; requiring five votes was suppressing nearly every live candidate.
    if core<1 or aligned<3 or aligned<=opposing:return None

    # Score is an evidence score, not a probability of winning.
    score=max(0.0,min(98.0,0.55*strength+0.30*float(gate.get("strength") or 0)+min(12,aligned*1.2)))
    # Expose distinct, explicitly approximate price/volume method votes for the method pages.
    # These are candle-derived proxies, not exchange order-book/tick data or a claim of exact pattern detection.
    extra_methods=dict(methods)
    sign=lambda x: 1 if x>0 else -1 if x<0 else 0
    # Momentum and channel pressure from raw closes/highs/lows.
    extra_methods["indicators"]=1 if price>float(gate.get("sma20") or 0) and price>float(gate.get("sma200") or 0) else -1 if price<float(gate.get("sma20") or 0) and price<float(gate.get("sma200") or 0) else 0
    extra_methods["momentum"]=sign(price-float(candles[-6]["close"]))
    ch_hi=max(float(x["high"]) for x in candles[-21:-1]); ch_lo=min(float(x["low"]) for x in candles[-21:-1])
    extra_methods["channels"]=1 if price>ch_hi else -1 if price<ch_lo else sign((price-ch_lo)-(ch_hi-price)) if abs((price-ch_lo)-(ch_hi-price))>0 else 0
    # BOS/CHOCH and liquidity reuse the engine's explicit swing/sweep detections.
    extra_methods["bos_choch"]=int(methods.get("smc") or 0) if int(methods.get("smc") or 0)!=0 else int(methods.get("dow") or 0)
    extra_methods["liquidity"]=int(methods.get("ict_liquidity") or 0)
    # FVG is a three-candle imbalance proxy.
    fvg_bull=float(candles[-1]["low"])>float(candles[-3]["high"])
    fvg_bear=float(candles[-1]["high"])<float(candles[-3]["low"])
    extra_methods["fvg"]=1 if fvg_bull else -1 if fvg_bear else 0
    # Candle-volume pressure proxy; true bid/ask delta requires trade-level data.
    cur=candles[-1]; cr=max(float(cur["high"])-float(cur["low"]),1e-12)
    pressure=((float(cur["close"])-float(cur["low"]))-(float(cur["high"])-float(cur["close"])))/cr
    extra_methods["order_flow"]=sign(pressure) if float(cur["volume"])>=sum(float(x["volume"]) for x in candles[-21:-1])/20.0 else 0
    # Candle-weighted VWAP approximation, not session VWAP.
    recent=candles[-30:]; vtot=sum(max(0,float(x["volume"])) for x in recent)
    vw=sum(((float(x["high"])+float(x["low"])+float(x["close"]))/3)*max(0,float(x["volume"])) for x in recent)/max(vtot,1e-12)
    extra_methods["vwap"]=sign(price-vw)
    # Quantitative consistency proxy: direction of net return versus path efficiency.
    q_path=sum(abs(float(candles[-i]["close"])-float(candles[-i-1]["close"])) for i in range(1,11))
    q_net=price-float(candles[-11]["close"])
    extra_methods["quant"]=sign(q_net) if abs(q_net)/max(q_path,1e-12)>=0.25 else 0
    # Trendline/Gann proxy uses two separated raw-price anchors; it is not a time-cycle forecast.
    extra_methods["gann"]=sign(float(candles[-1]["close"])-float(candles[-21]["close"]))
    # Approximate divergence: price makes a new short swing extreme while closes fail to confirm.
    p_old=candles[-10:-5]; p_new=candles[-5:]
    old_lo=min(float(x["low"]) for x in p_old); new_lo=min(float(x["low"]) for x in p_new)
    old_hi=max(float(x["high"]) for x in p_old); new_hi=max(float(x["high"]) for x in p_new)
    old_close=float(p_old[-1]["close"]); new_close=float(p_new[-1]["close"])
    extra_methods["divergence"]=1 if new_lo<old_lo and new_close>old_close else -1 if new_hi>old_hi and new_close<old_close else 0
    # Harmonic structure is only a coarse swing-ratio hint, not a confirmed named pattern.
    swing_range=max(float(x["high"]) for x in candles[-20:])-min(float(x["low"]) for x in candles[-20:])
    retr=(price-min(float(x["low"]) for x in candles[-20:])/1.0)/max(swing_range,price*1e-9)
    extra_methods["harmonic"]=1 if 0.58<=retr<=0.66 and price>float(candles[-3]["close"]) else -1 if 0.34<=retr<=0.42 and price<float(candles[-3]["close"]) else 0
    # No independent historical outcome model exists here; quant is a live structure proxy, not a backtest.
    a["methods"]=extra_methods
    a["side"]=method_side
    a["site_score"]=round(score,1)
    a["ai_pct"]=round(score,1)
    a["recommendation_score"]=round(score,1)
    a["sma20"]=gate["sma20"]
    a["ict_votes"]=gate["ict_votes"]
    a["momentum_votes"]=gate.get("momentum_votes",0)
    a["confluence"]={"weighted_alignment":round(strength,1),"aligned_methods":aligned,"opposing_methods":opposing,"structure_liquidity_confirmations":core}
    a["signal_label"]=("شراء قوي" if method_side=="BUY" else "بيع قوي") if score>=78 else ("شراء توافق" if method_side=="BUY" else "بيع توافق")
    price=float(a["price"])
    ref=a.get("support") if method_side=="BUY" else a.get("resistance")
    # Conservative bounded risk levels; validate again before publishing.
    risk=min(price*.03,max(price*.005,abs(price-float(ref or price))*.35))
    if method_side=="BUY":
        a["sl"]=price-risk; a["tp1"]=price+risk; a["tp2"]=price+risk*2; a["tp3"]=price+risk*3
    else:
        a["sl"]=price+risk; a["tp1"]=max(price-risk,price*.01); a["tp2"]=max(price-risk*2,price*.005); a["tp3"]=max(price-risk*3,price*.001)
        a["tp1"],a["tp2"],a["tp3"]=sorted([a["tp1"],a["tp2"],a["tp3"]],reverse=True)
    a["targets"]=[a["tp1"],a["tp2"],a["tp3"]]
    a["timeframe"]=timeframe
    a["price_fresh"]=True
    return a


# Independent technical-method scanner. It intentionally bypasses the shared
# confluence gate and external-recommendation ranking used by _analyze_symbol.
TECHNICAL_METHOD_KEYS = {
    "all": ("__all__",),
    "price-action": ("price_action",), "smc": ("smc",), "ict": ("ict_liquidity",),
    "classical": ("dow", "support_resistance", "breakout", "retest"),
    "candles": ("candlestick",), "patterns": ("chart_pattern",),
    "indicators": ("indicators",), "fibonacci": ("fibonacci",), "harmonic": ("harmonic",),
    "elliott": ("elliott",), "wyckoff": ("wyckoff",), "volume": ("raw_volume",),
    "order-flow": ("order_flow",), "ichimoku": ("ichimoku",), "dow-mtf": ("dow",),
    "quant": ("quant",), "gann": ("gann",), "bos-choch": ("bos_choch",),
    "fvg": ("fvg",), "liquidity": ("liquidity",), "retest": ("retest",),
    "divergence": ("divergence",), "momentum": ("momentum",), "vwap": ("vwap",),
    "channels": ("channels",), "volume-profile": ("volume_profile",),
    "market-regime": ("market_regime",)
}
def _expanded_method_votes(candles, base_methods):
    """Compute explicit per-method votes from OHLCV; approximations are labeled as such."""
    import math
    c=candles; closes=[float(x["close"]) for x in c]
    highs=[float(x["high"]) for x in c]; lows=[float(x["low"]) for x in c]
    opens=[float(x["open"]) for x in c]; vols=[max(0.0,float(x["volume"])) for x in c]
    price=closes[-1]
    def sign(x): return 1 if x>0 else -1 if x<0 else 0
    def sma(n): return sum(closes[-n:])/n if len(closes)>=n else None
    votes=dict(base_methods or {})
    # Indicator family: SMA20/50 and RSI/MACD-like momentum proxies from closes.
    s20=sma(20); s50=sma(50); s200=sma(200)
    indicator_votes=[]
    if s20 is not None and s50 is not None:
        indicator_votes.append(sign(s20-s50))
    if s20 is not None: indicator_votes.append(sign(price-s20))
    changes=[closes[i]-closes[i-1] for i in range(max(1,len(closes)-15),len(closes))]
    gains=sum(x for x in changes if x>0); losses=-sum(x for x in changes if x<0)
    if gains+losses>0:
        rsi=100*gains/(gains+losses)
        indicator_votes.append(1 if rsi>=55 else -1 if rsi<=45 else 0)
    fast=sum(closes[-12:])/12 if len(closes)>=12 else price
    slow=sum(closes[-26:])/26 if len(closes)>=26 else price
    prior_fast=sum(closes[-15:-3])/12 if len(closes)>=15 else fast
    prior_slow=sum(closes[-29:-3])/26 if len(closes)>=29 else slow
    macd_proxy=(fast-slow)-(prior_fast-prior_slow)
    indicator_votes.append(sign(macd_proxy))
    votes["indicators"]=sign(sum(indicator_votes)) if indicator_votes else 0
    # Harmonic ratio hint: explicitly a coarse retracement proxy, not named-pattern confirmation.
    hi=max(highs[-30:]); lo=min(lows[-30:]); span=max(hi-lo,abs(price)*1e-9)
    retr=(price-lo)/span
    votes["harmonic"]=1 if .58<=retr<=.66 and price>closes[-3] else -1 if .34<=retr<=.42 and price<closes[-3] else 0
    # Candle-volume pressure approximation, not real bid/ask order flow.
    cur=c[-1]; rng=max(highs[-1]-lows[-1],1e-12)
    pressure=((price-lows[-1])-(highs[-1]-price))/rng
    avgvol=sum(vols[-21:-1])/max(1,len(vols[-21:-1]))
    votes["order_flow"]=sign(pressure) if vols[-1]>=avgvol else 0
    # Efficiency-ratio quantitative direction; not a historical backtest.
    path=sum(abs(closes[i]-closes[i-1]) for i in range(max(1,len(closes)-10),len(closes)))
    net=price-closes[max(0,len(closes)-11)]
    votes["quant"]=sign(net) if path>0 and abs(net)/path>=.25 else 0
    # Gann-labelled price-cycle proxy only; not true Gann angles/time-cycle forecasting.
    votes["gann"]=sign(price-closes[max(0,len(closes)-21)])
    # Divergence approximation using swing extremes and closing-price confirmation.
    old=c[-10:-5]; new=c[-5:]
    if old and new:
        old_lo=min(x["low"] for x in old); new_lo=min(x["low"] for x in new)
        old_hi=max(x["high"] for x in old); new_hi=max(x["high"] for x in new)
        old_close=float(old[-1]["close"]); new_close=float(new[-1]["close"])
        votes["divergence"]=1 if new_lo<old_lo and new_close>old_close else -1 if new_hi>old_hi and new_close<old_close else 0
    else: votes["divergence"]=0
    votes["momentum"]=sign(price-closes[max(0,len(closes)-6)])
    recent=c[-30:]; vtot=sum(max(0.0,float(x["volume"])) for x in recent)
    vw=sum(((float(x["high"])+float(x["low"])+float(x["close"]))/3)*max(0.0,float(x["volume"])) for x in recent)/max(vtot,1e-12)
    votes["vwap"]=sign(price-vw)
    ch_hi=max(highs[-21:-1]); ch_lo=min(lows[-21:-1])
    votes["channels"]=1 if price>ch_hi else -1 if price<ch_lo else sign((price-ch_lo)-(ch_hi-price))
    votes["fvg"]=1 if lows[-1]>highs[-3] else -1 if highs[-1]<lows[-3] else 0
    votes["bos_choch"]=int(votes.get("smc") or votes.get("dow") or 0)
    votes["liquidity"]=int(votes.get("ict_liquidity") or 0)
    return votes

def _analyze_symbol_method(symbol, market, timeframe, method_id):
    keys=TECHNICAL_METHOD_KEYS.get(method_id)
    if not keys:return None
    candles=_candles(_crypto_klines(symbol,market,timeframe)) if market in ("spot","futures") else _yahoo(symbol,market,timeframe)
    if not _valid_ohlcv(candles,min_count=52):return None
    candles=[{k:float(row[k]) for k in ("open","high","low","close","volume")} for row in candles]
    analysis=_method_analysis(candles)
    if not analysis:return None
    votes=_expanded_method_votes(candles,analysis.get("methods") or {})
    if method_id=="all":
        # One independent combined-method signal; it does not use the legacy SMA200 gate.
        weights={"smc":1.5,"ict_liquidity":1.5,"price_action":1.2,"dow":1.2,
                 "breakout":1.2,"retest":1.0,"support_resistance":1.0,"candlestick":.8,
                 "chart_pattern":.8,"fibonacci":.7,"elliott":.6,"wyckoff":1.0,
                 "raw_volume":.8,"ichimoku":.8,"market_regime":1.0,"indicators":.8,
                 "harmonic":.5,"order_flow":.5,"quant":.7,"gann":.4,"divergence":.7,
                 "momentum":.7,"vwap":.6,"channels":.6,"volume_profile":.7,"fvg":.8}
        score=sum(weights.get(k,.5)*float(v or 0) for k,v in votes.items())
        side="BUY" if score>0 else "SELL" if score<0 else "WAIT"
        aligned=sum(1 for v in votes.values() if (float(v or 0)>0 if side=="BUY" else float(v or 0)<0)) if side!="WAIT" else 0
        opposing=sum(1 for v in votes.values() if (float(v or 0)<0 if side=="BUY" else float(v or 0)>0)) if side!="WAIT" else 0
        if side=="WAIT" or aligned<4 or aligned<=opposing:return None
        used_votes=len([v for v in votes.values() if float(v or 0)!=0])
        confidence=round(min(95,50+abs(score)/max(sum(weights.values()),1)*45),1)
    else:
        vals=[float(votes.get(k) or 0) for k in keys]
        total=sum(1 if v>0 else -1 if v<0 else 0 for v in vals)
        if not total:return None
        side="BUY" if total>0 else "SELL"
        aligned=sum(1 for v in vals if (v>0 if side=="BUY" else v<0))
        opposing=sum(1 for v in vals if (v<0 if side=="BUY" else v>0))
        if aligned<=opposing:return None
        confidence=round(abs(total)/max(1,len(vals))*100,1)
    entry=float(candles[-1]["close"])
    support=float(analysis.get("support") or min(x["low"] for x in candles[-30:]))
    resistance=float(analysis.get("resistance") or max(x["high"] for x in candles[-30:]))
    risk=min(entry*.03,max(entry*.005,abs(entry-(support if side=="BUY" else resistance))*.35))
    if side=="BUY":sl=entry-risk;tps=[entry+risk,entry+2*risk,entry+3*risk]
    else:sl=entry+risk;tps=sorted([max(entry-risk,entry*.01),max(entry-2*risk,entry*.005),max(entry-3*risk,entry*.001)],reverse=True)
    # Final fail-closed gate: never publish malformed prices or targets on the wrong side.
    levels=[entry,sl,*tps]
    if not all(math.isfinite(float(v)) and float(v)>0 for v in levels):
        return None
    if len(tps)!=3:
        return None
    if side=="BUY":
        if not (sl < entry < tps[0] < tps[1] < tps[2]):
            return None
    elif side=="SELL":
        if not (tps[2] < tps[1] < tps[0] < entry < sl):
            return None
    else:
        return None
    if not math.isfinite(float(confidence)) or confidence<=0 or confidence>100:
        return None
    return {"symbol":symbol,"market":market,"direction":side,"side":side,"timeframe":timeframe,
            "technical_only":True,"research_only":False,"technical_method_key":method_id,
            "technical_method_vote":confidence,"methods":votes,"entry":entry,"price":entry,"current_price":entry,
            "sl":sl,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"targets":tps,
            "ai_pct":confidence,"confidence_type":"method_agreement_score_not_win_probability","recommendation_score":confidence,
            "site_score":confidence,
            "signal_label":("شراء" if side=="BUY" else "بيع")+" · "+method_id,
            "support":support,"resistance":resistance,"price_source":"public market data",
            "reason":"إشارة من المنهج المحدد وقواعد OHLCV؛ بعض القياسات تقريبية ولا تمثل احتمال ربح."}

def discover_method(market, timeframe, method_id):
    if method_id not in TECHNICAL_METHOD_KEYS:
        return []
    if timeframe not in {"1m","3m","5m","15m","30m","1h","4h","1d","1w","1M"}:
        return []
    symbols=_symbols_for_market(market,[])
    if market in ("spot","futures"):symbols=[s for s in symbols if str(s).upper().endswith("USDT")]
    caps={"spot":120,"futures":120,"us":80,"saudi":160,"contracts":20,"forex":34}
    symbols=symbols[:caps.get(market,40)]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(_analyze_symbol_method,s,market,timeframe,method_id):s for s in symbols}
        for fut in as_completed(jobs):
            try:
                row=fut.result()
                if row:rows.append(row)
            except Exception:pass
    rows.sort(key=lambda r:float(r.get("recommendation_score") or 0),reverse=True)
    print("[TECHNICAL-METHOD]",market,timeframe,method_id,"rows",len(rows),flush=True)
    return rows[:100]

SAUDI_UNIVERSE_CACHE={}
US_UNIVERSE_CACHE={}

def _rotating_batch(symbols, size, market):
    """Cycle through the full eligible universe between refreshes instead of ignoring its tail."""
    symbols=list(dict.fromkeys(str(s).strip() for s in (symbols or []) if str(s).strip()))
    if not symbols:return []
    size=min(len(symbols),max(1,int(size)))
    # Use the 15-minute refresh slot so one cache refresh scans a stable batch.
    slot=int(time.time()//900)
    offset=(slot*size)%len(symbols)
    return (symbols[offset:offset+size] + symbols[:max(0,offset+size-len(symbols))])

def _us_universe(min_volume=1_000_000):
    """Discover US-listed equities and retain those with >1M shares traded in the latest session."""
    key="all_us_equities_over_1m"; now=time.time(); cached=US_UNIVERSE_CACHE.get(key)
    if cached and now-cached[0]<900:return list(cached[1])
    symbols=[]; seen=set()
    try:
        for offset in range(0,5000,250):
            body={"offset":offset,"size":250,"sortField":"dayvolume","sortType":"DESC","quoteType":"EQUITY","query":{"operator":"EQ","operands":["region","us"]}}
            req=urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener",data=json.dumps(body).encode(),headers={"User-Agent":UA,"Content-Type":"application/json"},method="POST")
            raw=json.loads(urllib.request.urlopen(req,timeout=8).read().decode("utf-8","ignore"))
            quotes=(((raw.get("finance") or {}).get("result") or [{}])[0]).get("quotes") or []
            if not quotes:break
            for q in quotes:
                sym=str(q.get("symbol") or "").strip()
                volume=q.get("regularMarketVolume",q.get("dayVolume",q.get("volume",0)))
                try:volume=float(volume or 0)
                except (TypeError,ValueError):volume=0
                if sym and sym not in seen and volume>float(min_volume):
                    seen.add(sym);symbols.append(sym)
            if len(quotes)<250:break
    except Exception as exc:
        print("[UNIVERSE] US screener fallback",str(exc)[:100],flush=True)
    # Keep the known baseline as a fallback, but do not pretend it is a full universe.
    if not symbols:
        symbols=list(BASE_UNIVERSE.get("us",[]))
    US_UNIVERSE_CACHE[key]=(now,symbols)
    print("[UNIVERSE] US eligible stocks >1M shares",len(symbols),flush=True)
    return list(symbols)

def _saudi_universe(min_volume=0):
    """Discover Saudi-listed equities without any daily-volume threshold."""
    key="all_saudi_equities"; now=time.time(); cached=SAUDI_UNIVERSE_CACHE.get(key)
    if cached and now-cached[0]<900:return list(cached[1])
    symbols=[]; seen=set()
    try:
        for offset in range(0,5000,250):
            # Deliberately filter by Saudi region only; zero/missing volume must not exclude a listing.
            body={"offset":offset,"size":250,"sortField":"dayvolume","sortType":"DESC","quoteType":"EQUITY","query":{"operator":"EQ","operands":["region","sa"]}}
            req=urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener",data=json.dumps(body).encode(),headers={"User-Agent":UA,"Content-Type":"application/json"},method="POST")
            raw=json.loads(urllib.request.urlopen(req,timeout=8).read().decode("utf-8","ignore"))
            quotes=(((raw.get("finance") or {}).get("result") or [{}])[0]).get("quotes") or []
            if not quotes:break
            for q in quotes:
                sym=str(q.get("symbol") or "").strip()
                # Yahoo screener returns Saudi tickers with .SR; store the canonical bare symbol.
                if sym.upper().endswith(".SR"): sym=sym[:-3]
                if sym and sym not in seen:
                    seen.add(sym); symbols.append(sym)
            if len(quotes)<250:break
    except Exception:pass
    if not symbols:symbols=list(BASE_UNIVERSE.get("saudi",[]))
    SAUDI_UNIVERSE_CACHE[key]=(now,symbols)
    return list(symbols)

def _symbols_for_market(market,internet):
    if market in ("spot","futures"):
        s=[x[0] for x in _crypto_universe(market)]
        for r in internet:
            if r["symbol"].endswith("USDT") and r["symbol"] not in s:s.append(r["symbol"])
        return s
    if market=="saudi":
        # Include TASI index analysis alongside Saudi-listed equities.
        base=["TASI"] + _saudi_universe(0)
    else:
        base=BASE_UNIVERSE.get(market,[])
    seen=[]
    for s in [r["symbol"] for r in internet]+base:
        if s not in seen:seen.append(s)
    return seen


def _public_scan(market,internet,timeframe="15m"):
    """Market-data scan: recommendations support ranking, never market coverage."""
    symbols=_symbols_for_market(market,internet)
    if market in ("us","saudi"):
        symbols=[s for s in symbols if _passes_volume_filter(s,market)]
    if market in ("spot","futures"):
        symbols=[s for s in symbols if str(s).upper().endswith("USDT")]
    # Keep refreshes fast on the small service; the next refresh continues from
    # the liquid universe rather than requiring external headlines.
    # Keep the 512 MB / 0.2 vCPU service responsive. Non-crypto feeds are slower,
    # so scan a focused liquid shortlist first and expand only after the cache is warm.
    caps={"spot":240,"futures":180,"us":60,"saudi":28,"contracts":16,"forex":36}
    cap=caps.get(market,24)
    if len(symbols)>cap:
        if market in ("spot","futures"):
            q=dict(_crypto_universe(market))
            symbols=sorted(symbols,key=lambda s:q.get(s,0),reverse=True)[:cap]
        else:
            symbols=symbols[:cap]
    out=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(_analyze_symbol,s,market,timeframe):s for s in symbols}
        for fut in as_completed(jobs):
            try:a=fut.result()
            except Exception:a=None
            # Some non-crypto markets were returning zero cards because the strict
            # multi-method gate rejected every candidate. Use a separately labeled
            # classical price/structure read as a fallback, still requiring real candles.
            if not a and market not in {"spot"}:
                try:
                    a=_analyze_symbol_method(jobs[fut],market,timeframe,"classical")
                    if a:
                        a["signal_label"]="شراء · كلاسيكي (بديل)" if a.get("side")=="BUY" else "بيع · كلاسيكي (بديل)"
                        a["fallback_scan"]=True
                        a["reason"]="قراءة فنية كلاسيكية من بيانات الشموع الفعلية؛ لا تعني ضمان الربح."
                except Exception:
                    a=None
            if not a or a.get("side") not in {"BUY","SELL"}:continue
            # Validate published levels: never expose negative targets or a stop on the wrong side.
            entry=float(a.get("entry") or a.get("price") or 0)
            side=str(a.get("side") or "").upper()
            if not (entry>0):continue
            sl=float(a.get("sl") or 0)
            tps=[float(a.get(k) or 0) for k in ("tp1","tp2","tp3")]
            valid=(sl>entry and all(tps[i]>tps[i+1]>0 for i in range(2)) and tps[2]<entry) if side=="SELL" else (0<sl<entry and all(0<tps[i]<tps[i+1] for i in range(2)) and tps[0]>entry)
            if not valid:
                support=float(a.get("support") or entry); resistance=float(a.get("resistance") or entry)
                raw_risk=abs(entry-(support if side=="BUY" else resistance))*.45
                risk=min(entry*.03,max(entry*.005,raw_risk))
                if side=="BUY":
                    sl=entry-risk; tps=[entry+risk,entry+2*risk,entry+3*risk]
                else:
                    sl=entry+risk; tps=[max(entry-risk,entry*.01),max(entry-2*risk,entry*.005),max(entry-3*risk,entry*.001)]
                    tps=sorted(tps,reverse=True)
                a["entry"]=entry; a["sl"]=sl; a["tp1"],a["tp2"],a["tp3"]=tps; a["targets"]=tps
            sym=jobs[fut]; tech=float(a.get("site_score") or 0)
            people=[r for r in internet if r.get("symbol")==sym]
            buy=sum(1 for r in people if r.get("direction")=="BUY")
            sell=sum(1 for r in people if r.get("direction")=="SELL")
            people_side="BUY" if buy>sell else "SELL" if sell>buy else None
            mentions=max(buy,sell)
            people_agreement=(mentions/max(1,buy+sell))*100 if (buy+sell) else 0
            final_score=tech
            if people_side:
                final_score += min(15.0,mentions*3.0)
                if people_side != a["side"]:
                    final_score -= min(10.0,mentions*2.0)
            final_score=max(0.0,min(100.0,final_score))
            out.append({
                "symbol":sym,"direction":a["side"],"side":a["side"],"timeframe":timeframe,"signal_label":a.get("signal_label"),
                "entry":a.get("entry"),"targets":a.get("targets"),
                "tp1":a.get("tp1"),"tp2":a.get("tp2"),"tp3":a.get("tp3"),"sl":a.get("sl"),
                "ai_pct":round(final_score,1),
                "recommendation_score":round(final_score,1),
                "site_score":tech,"timeframe":timeframe,"signal_label":a.get("signal_label"),"sma20":a.get("sma20"),"ict_votes":a.get("ict_votes"),
                "methods":a.get("methods") or {}, "support":a.get("support"), "resistance":a.get("resistance"),
                "external_agreement":round(people_agreement,1),"research_agreement":round(people_agreement,1),
                "source_count":mentions,"research_sources":mentions,"internet_sources":mentions,
                "source_titles":[r.get("source_title") for r in people[:10] if r.get("source_title")],
                "source_published":people[0].get("source_published") if people else None,
                "source_url":people[0].get("source_url") if people else None,
                "research_mode":True,"research_only":False,
                "people_direction":people_side,"people_mentions":mentions,
                "price_source":"public market data",
                "reason":"توجه الناس والتوصيات أولاً، ثم تجميع مناهج التحليل السعري بدون مؤشرات فنية"
            })
    return out


def _update_active_signals(market, fresh):
    """Keep published trades visible until TP3 or SL is reached."""
    key="active:"+str(market)
    active=ACTIVE_SIGNALS.get(key,{})
    for r in fresh:
        s=r.get("symbol")
        if s:
            old=active.get(s)
            if not old or old.get("side")==r.get("side") or float(r.get("ai_pct") or 0)>=float(old.get("ai_pct") or 0):
                r=dict(r)
                r.setdefault("published_at",time.time())
                active[s]=r
    keep={}
    for s,r in active.items():
        try:
            sl=float(r.get("sl"))
            tps=[float(x) for x in (r.get("targets") or []) if x is not None]
            tp3=float(tps[-1]) if tps else float(r.get("tp3"))
            side=str(r.get("side") or r.get("direction") or "").upper()
            cur=float(r.get("entry") or r.get("price"))
            if market in ("spot","futures"):
                q=_binance24(market=="futures")
                row=next((x for x in q if str(x.get("symbol","")).upper()==s.upper()),None)
                if row:
                    cur=float(row.get("lastPrice") or row.get("price") or cur)
            hit=(cur<=sl or cur>=tp3) if side=="BUY" else (cur>=sl or cur<=tp3) if side=="SELL" else False
            if not hit:
                r["current_price"]=cur
                r["active_trade"]=True
                keep[s]=r
        except Exception:
            keep[s]=r
    ACTIVE_SIGNALS[key]=keep
    return list(keep.values())

def _external_trade_fields(text):
    """Extract every explicitly published Entry/TP/SL level from an external recommendation."""
    import re
    s=str(text or "")
    def nums(patterns):
        out=[]
        for ptn in patterns:
            for m in re.finditer(ptn,s,re.I):
                try: out.append(float(m.group(1).replace(",","")))
                except Exception: pass
        return out
    entries=nums([r"\bentry\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)",r"\bentries?\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)",r"الدخول\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"])
    targets=[]
    for label,pat in [
        ("tp",r"\btp\s*([0-9]+)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"),
        ("take",r"take\s*profit\s*([0-9]+)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"),
        ("هدف",r"هدف\s*([0-9]+)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)")
    ]:
        for m in re.finditer(pat,s,re.I):
            try: targets.append((int(m.group(1)),float(m.group(2).replace(",",""))))
            except Exception: pass
    # Also accept plain "targets: 1, 2, 3..." lists.
    for ptn in [r"(?:targets?|الأهداف)\s*[:=]\s*([^\n\r]+)"]:
        for m in re.finditer(ptn,s,re.I):
            for v in re.findall(r"[0-9]+(?:\.[0-9]+)?",m.group(1)):
                try: targets.append((999,float(v)))
                except Exception: pass
    targets=sorted(set(targets),key=lambda x:(x[0],targets.index(x) if x in targets else 0))
    sl=nums([r"\bsl\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)",r"stop\s*loss\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)",r"وقف\s*(?:الخسارة)?\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"])
    return (entries[0] if entries else None),[v for _,v in targets],(sl[0] if sl else None)


def _passes_volume_filter(symbol, market):
    """Keep liquid instruments above 1M daily traded volume where applicable."""
    try:
        if market=="saudi":
            # Saudi market: do not exclude valid setups by daily-volume threshold.
            return True
        if market=="us":
            q=_yahoo(symbol,market,"1d") or []
            if not q: return False
            return float(q[-1].get("volume") or 0) > 1000000
        if market=="spot":
            q=_binance24(False) or []
            row=next((x for x in q if str(x.get("symbol","")).upper()==str(symbol).upper()),None)
            return float((row or {}).get("quoteVolume") or (row or {}).get("volume") or 0) > 1000000
        return True
    except Exception:
        return False

def discover(market,timeframe="15m"):
    """Combine per-timeframe public analysis with external recommendation coverage."""
    if timeframe not in {"1m","3m","5m","15m","30m","1h","4h","1d","1w","1M"}: timeframe="15m"
    now=time.time(); key="external:"+market+":"+timeframe; cached=CACHE.get(key)
    if cached and now-cached[0]<DISCOVER_TTL:
        return list(cached[1])

    persisted=[r for r in _load_persisted(market) if str(r.get("timeframe") or "")==timeframe]
    internet=_internet(market)
    public_rows=_public_scan(market,internet,timeframe)

    if market=="contracts":
        allowed={"ES","NQ","YM","RTY","WTI","NG","ZB","ZN"}
        internet=[r for r in internet if str(r.get("symbol") or "").upper() in allowed]

    # Build external recommendations only from the external feed.
    external_results=[]
    for r in internet:
        full=str(r.get("source_title",""))+" "+str(r.get("source_text",""))+" "+str(r.get("source_url",""))
        entry,targets,sl=_external_trade_fields(full)
        direction=r.get("direction")
        if market in {"us","saudi","spot"} and not _passes_volume_filter(r.get("symbol"), market):
            continue

        px=entry
        if px is None:
            try:
                if market in ("spot","futures"):
                    q=_binance24(market=="futures")
                    row=next((x for x in q if str(x.get("symbol","")).upper()==str(r.get("symbol","")).upper()),None)
                    px=float((row or {}).get("lastPrice") or 0) or None
                else:
                    cc=_yahoo(str(r.get("symbol")),market,"15m")
                    px=float(cc[-1]["close"]) if cc else None
            except Exception:
                px=None

        if px:
            entry=entry or px
            if not targets:
                risk=px*0.01
                targets=[px+risk,px+risk*2,px+risk*3] if direction=="BUY" else [px-risk,px-risk*2,px-risk*3]
            if sl is None:
                sl=px*(0.995 if direction=="BUY" else 1.005)

        external_results.append({
            "symbol":r.get("symbol"),"market":market,
            "direction":direction,"side":direction,
            "entry":entry,"targets":targets,
            "tp1":targets[0] if len(targets)>0 else None,
            "tp2":targets[1] if len(targets)>1 else None,
            "tp3":targets[2] if len(targets)>2 else None,
            "sl":sl,"ai_pct":100.0,
            "recommendation_score":100.0,
            "external_agreement":100.0,"research_agreement":100.0,
            "internet_score":100.0,"site_score":0.0,
            "source_count":1,"research_sources":1,"internet_sources":1,
            "source_titles":[r.get("source_title")],
            "source_published":r.get("source_published"),
            "source_url":r.get("source_url"),
            "research_mode":False,"research_only":True,
            "price_source":"public market price" if not (entry and targets and sl) else "external recommendation",
            "reason":"توصية عامة من مصدر مفتوح؛ المستويات غير المنشورة أُكملت من السعر العام الحالي"
        })

    # External coverage map: used only to rank/confirm public analysis.
    coverage={}
    for r in internet:
        k=(r.get("symbol"),r.get("direction"))
        z=coverage.setdefault(k,{"count":0,"titles":[],"published":None,"url":None})
        z["count"]+=1
        if r.get("source_title") and len(z["titles"])<10:z["titles"].append(r.get("source_title"))
        if not z["published"] and r.get("source_published"):z["published"]=r.get("source_published")
        if not z["url"] and r.get("source_url"):z["url"]=r.get("source_url")

    # Public rows are first-class trades. Never send them through the external
    # volume filter again: Spot/Futures liquidity was already enforced by Binance
    # universe selection, while US/Saudi liquidity was checked in _public_scan.
    public_results=[]
    for r in public_rows:
        x=dict(r)
        x["market"]=market
        k=(x.get("symbol"),x.get("direction"))
        z=coverage.get(k,{"count":0,"titles":[],"published":None,"url":None})
        mentions=int(z.get("count") or 0)
        x["external_mentions"]=mentions
        x["source_count"]=mentions
        x["research_sources"]=mentions
        x["internet_sources"]=mentions
        x["external_agreement"]=round((mentions/max(1,mentions))*100,1) if mentions else 0.0
        x["research_agreement"]=x["external_agreement"]
        if z.get("titles"):x["source_titles"]=z["titles"]
        if z.get("published"):x["source_published"]=z["published"]
        if z.get("url"):x["source_url"]=z["url"]
        x["research_mode"]=True
        x["research_only"]=False
        x["price_source"]="public market data"
        public_results.append(x)

    # If an external recommendation exists for the exact same symbol/direction,
    # keep the stronger public trade levels while adding the external coverage.
    ext_map={(x.get("symbol"),x.get("direction")):x for x in external_results}
    merged=[]
    for x in public_results:
        e=ext_map.get((x.get("symbol"),x.get("direction")))
        if e:
            y=dict(x)
            y["external_recommendation"]=True
            y["external_entry"]=e.get("entry")
            y["external_targets"]=e.get("targets")
            y["external_sl"]=e.get("sl")
            y["external_rank_score"]=e.get("recommendation_score")
            merged.append(y)
        else:
            merged.append(x)

    # Keep external-only recommendations too, but never let them erase public
    # market coverage when both describe the same instrument.
    public_keys={(x.get("symbol"),x.get("direction")) for x in public_results}
    for e in external_results:
        if (e.get("symbol"),e.get("direction")) not in public_keys:
            merged.append(e)

    # الترتيب يكون حسب قوة التوصية الفعلية، وليس لأن الاتجاه BUY قبل SELL.
    # كثرة المصادر المستقلة ترفع الصفقة أولاً، ثم درجة التحليل.
    merged.sort(key=lambda x:(
        -int(x.get("source_count") or 0),
        -float(x.get("recommendation_score") or x.get("ai_pct") or 0),
        -(1 if x.get("source_published") else 0)
    ))
    for i,x in enumerate(merged,1):
        x["external_rank"]=i

    # Save every successful discovery. Do not erase the last good snapshot
    # when a temporary feed/API failure produces zero rows.
    if merged:
        _save_persisted(market,merged[:500])
    elif persisted:
        merged=list(persisted)
        merged.sort(key=lambda x:(
            -int(x.get("source_count") or 0),
            -float(x.get("recommendation_score") or x.get("ai_pct") or 0),
            -(1 if x.get("source_published") else 0)
        ))
        print("[PERSIST] using saved snapshot",market,len(merged),flush=True)

    CACHE[key]=(now,merged[:500])
    print("[PUBLIC+EXTERNAL]",market,"public",len(public_results),"external",len(external_results),"total",len(merged),flush=True)
    return merged[:500]

def decide(rows):
    # Keep BUY and SELL as separate trade candidates for the same symbol.
    # Grouping only by market+symbol silently discarded one direction, which
    # caused sell cards to disappear whenever a buy candidate ranked first.
    groups={}
    for r in rows:
        market=str(r.get("market") or "").lower()
        symbol=str(r.get("symbol") or "").upper()
        side=str(r.get("direction") or r.get("side") or "").upper()
        if not symbol or side not in {"BUY","SELL"}: continue
        groups.setdefault((market,symbol,side),[]).append(r)
    return sorted((dict(max(v,key=lambda x:float(x.get("ai_pct") or x.get("recommendation_score") or 0))) for v in groups.values()),key=lambda x:float(x.get("ai_pct") or x.get("recommendation_score") or 0),reverse=True)
