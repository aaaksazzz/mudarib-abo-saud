import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET,json
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor,as_completed

UA="SMART-TRADING-PRO/6.0 pure-method-hybrid"
DISCOVER_TTL=45.0
FETCH_TIMEOUT=5.0
MAX_SOURCE_AGE=24*60*60
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
    try:
        with open(_persist_path(market),"r",encoding="utf-8") as f:
            rows=json.load(f)
        return rows if isinstance(rows,list) else []
    except Exception:
        return []

def _save_persisted(market,rows):
    try:
        existing=_load_persisted(market)
        merged={}
        for r in existing+list(rows or []):
            if not isinstance(r,dict): continue
            k=(str(r.get("symbol") or "").upper(),str(r.get("direction") or r.get("side") or "").upper())
            if not k[0] or k[1] not in {"BUY","SELL"}: continue
            merged[k]=dict(r)
        out=list(merged.values())[-PERSIST_LIMIT:]
        tmp=_persist_path(market)+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(out,f,ensure_ascii=False,separators=(",",":"))
        os.replace(tmp,_persist_path(market))
    except Exception as exc:
        print("[PERSIST] save failed",market,str(exc)[:160],flush=True)



MARKET_QUERIES={
 "spot":["crypto trading signal entry take profit stop loss","crypto buy signal entry tp sl","crypto signal BUY SELL LONG SHORT today","BTC ETH SOL XRP trading signal entry target stop loss","BTCUSDT ETHUSDT altcoin signal entry take profit stop loss","Binance crypto signal today","altcoin buy sell signal today"],
 "futures":["crypto futures recommendation LONG SHORT today","Binance futures recommendation today","BTC ETH futures long short signal","crypto futures signal entry take profit stop loss","Binance futures LONG SHORT signal today","altcoin futures signal today"],
 "us":["US stock recommendation BUY SELL today","US stock picks today buy sell","NASDAQ stock recommendation today","NYSE stock recommendation today","US stocks trading signal entry target stop loss","AAPL NVDA TSLA AMD stock signal today"],
 "saudi":["توصية تداول تاسي شراء بيع اليوم","السوق السعودي توصيات أسهم اليوم","توصيات تداول السوق السعودي اليوم","توصيات أسهم سعودية شراء بيع اليوم","توصيات تاسي دخول هدف وقف اليوم","أفضل توصيات الأسهم السعودية اليوم"],
 "contracts":["ES=F","NQ=F","YM=F","RTY=F","CL=F","NG=F","ZB=F","ZN=F"],
 "forex":["forex recommendation BUY SELL today","forex trading signal entry target stop loss today","EURUSD GBPUSD USDJPY recommendation today","EURUSD signal today","GBPUSD signal today","USDJPY signal today"]
}

# Liquid baseline universes: external recommendations confirm the setup, but do not decide
# which instruments are eligible for analysis. This prevents empty markets when news has no ticker.
BASE_UNIVERSE={
 "us":["AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","AVGO","AMD","NFLX","JPM","V","MA","COST","WMT","ORCL","CRM","PLTR","INTC","QCOM","MU","AMAT","ADBE","CSCO","IBM","GE","CAT","BA","DIS","UBER","COIN","MSTR","BAC","GS","MS","XOM","CVX","LLY","JNJ","PFE","ABBV","UNH","HD","LOW","TMO","LIN","NKE","PEP","KO","SMCI","ARM","MELI","CRWD","PANW","NOW","SNOW","SHOP","PYPL","SQ","SOFI","HOOD","RBLX","ABNB","DASH","PDD","BABA","JD","NIO","LI","XPEV","MRVL","ON","LRCX","KLAC","TXN","ADI","INTU","ISRG","VRTX","AMGN","GILD","MRK","BMY","CVS","T","VZ","CMCSA","COP","SLB","EOG","OXY","DE","MMM","HON","RTX","LMT","GM","F","TGT","SBUX","MCD","HD","LOW","BKNG","SPOT","ROKU","RIVN"],
 "saudi":["2222","1120","2010","1180","1150","1211","2020","7010","7020","2280","2050","3030","4003","4190","4261","4280","4300","4321","4331","2223","2082","2083","2084","2081","2080","2082","2083","2084","2081","2080","4001","4002","4005","4007","4008","4009","4013","4014","4015","4017","4018","4020","4030","4031","4040","4050","4061","4071","4081","4090","4100","4110","4130","4140","4150","4160","4170","4180","4200","4210","4220","4230","4240","4250","4260","4270","4290","4310","4322","4330","4340","4342","4344","4345","4346","4347","4348","4349","4350","5110","6001","6010","6020","6040","6050","6060","6070","6090","7010","7020","7030","7040","7200","7201","7202","7203","7204","7207","7208","7209","7210","7211","8010","8012","8020","8030","8040","8050","8060","8070","8100","8120","8150","8160","8170","8180","8190","8200","8210","8230","8240","8250","8260","8270","8280","8300","8310","8311","8312","9510","9512","9513","9514","9515","9516","9517","9518","9520","9521","9522","9523","9524","9525","9526","9527","9528","9529","9530","9531","9532","9533","9534","9535","9536","9537","9538","9539","9540","9541","9542","9543","9544","9545","9546","9547","9548","9549"];
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
    return out[:20]

def _news(q):
    # Strict 24-hour search window. Merge all providers instead of returning
    # the first non-empty feed, so recommendation coverage is broad.
    urls=[
        "https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"}),
        "https://www.bing.com/news/search?"+urllib.parse.urlencode({"q":q,"format":"rss","freshness":"Day"})
    ]
    cutoff=time.time()-MAX_SOURCE_AGE
    merged=[]; seen=set(); now=time.time()
    for u in urls:
        try:hits=_parse_news_xml(_fetch(u))
        except Exception:hits=[]
        for h in hits:
            published=h.get("published") or ""
            try:ts=parsedate_to_datetime(published).timestamp()
            except Exception:continue
            if ts < cutoff or ts > now+300:continue
            h=dict(h); h["published_ts"]=ts
            key=(h.get("url") or "").strip().lower() or re.sub(r"\\s+"," ",str(h.get("title") or "").strip().lower())
            if not key or key in seen:continue
            seen.add(key); merged.append(h)
    merged.sort(key=lambda x:float(x.get("published_ts") or 0),reverse=True)
    return merged[:40]

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
        m=re.search(r"\b([A-Z0-9]{2,20})\\s*(?:/|-)\\s*USDT\b",t) or re.search(r"\b([A-Z0-9]{2,20})USDT\b",t)
        if m:return m.group(1)+"USDT"
        m=re.search(r"\\$([A-Z0-9]{2,20})\b",t)
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
        m=re.search(r"\\$([A-Z]{1,5})\b",t) or re.search(r"\b(?:NASDAQ|NYSE|NYSEARCA)[:\\s]+([A-Z]{1,5})\b",t)
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

    if market=="forex":
        aliases={"اليورو دولار":"EURUSD","يورو دولار":"EURUSD","الباوند دولار":"GBPUSD","جنيه دولار":"GBPUSD","دولار ين":"USDJPY"}
        for name,sym in aliases.items():
            if name in t:return sym
        m=re.search(r"\b([A-Z]{3}\\s*/?\\s*[A-Z]{3})\b",t)
        return m.group(1).replace(" ","").replace("/","") if m else None
    return None

def _direction(text):
    t=text.upper()
    b=re.findall(r"\b(BUY|LONG|BULLISH|UPGRADE|OUTPERFORM|OVERWEIGHT|BUYING|شراء|صعود|صاعد|يرتفع|ارتفاع|إيجابي|إيجابية)\b",t); s=re.findall(r"\b(SELL|SHORT|BEARISH|DOWNGRADE|UNDERPERFORM|UNDERWEIGHT|SELLING|بيع|هبوط|هابط|ينخفض|انخفاض|سلبي|سلبية)\b",t)
    return "BUY" if b and not s else "SELL" if s and not b else None

def _internet(market):
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as p:
        fs=[p.submit(_news,q) for q in MARKET_QUERIES.get(market,[])]
        for f in as_completed(fs):
            try:hits=f.result()
            except Exception:hits=[]
            for h in hits:
                # Do not download every article: that can block the API when a feed
                # returns many stories. Fetch the article only for likely trade signals.
                base=(h["title"]+" "+h["text"]).strip()
                signal_words=("entry","tp","take profit","stop loss","target","targets","sl","شراء","بيع","دخول","هدف","وقف")
                full=base
                if any(w in base.lower() for w in signal_words):
                    full=base+" "+_article(h["url"])
                sym=_symbol(full,market); d=_direction(full)
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

def _crypto_klines(symbol,market,interval="15m",limit=120):
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    try:return _json(base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":limit}),6)
    except Exception:return []

def _yahoo(symbol,market,interval="15m",limit=120):
    # Yahoo symbol mapping + redundant hosts/ranges. Some markets reject 60d intraday
    # on one host, so retry without changing the analysis methodology.
    y={
        "us":symbol,
        "saudi":(symbol[:-3] if str(symbol).upper().endswith(".SR") else str(symbol))+".SR",
        "contracts":{"ES":"ES=F","NQ":"NQ=F","YM":"YM=F","RTY":"RTY=F","WTI":"CL=F","NG":"NG=F","GC":"GC=F","SI":"SI=F","HG":"HG=F","ZB":"ZB=F","ZN":"ZN=F","ZF":"ZF=F","ZC":"ZC=F","ZS":"ZS=F","ZW":"ZW=F","6E":"6E=F","6B":"6B=F","6J":"6J=F","6A":"6A=F","6C":"6C=F"}.get(symbol,symbol),
        "forex":symbol[:3]+symbol[3:]+"=X"
    }.get(market,symbol)
    hosts=("https://query1.finance.yahoo.com","https://query2.finance.yahoo.com")
    ranges=("60d","30d","10d")
    for host in hosts:
        for rg in ranges:
            try:
                url=host+"/v8/finance/chart/"+urllib.parse.quote(y,safe="")+"?"+urllib.parse.urlencode({"interval":interval,"range":rg})
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
def _method_analysis(c):
    if len(c)<32:return None
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
    fib=1 if fib62<=price<=fib38 and price>closes[-3] else -1 if fib38<=price<=fib62 and price<closes[-3] else 0

    # 12) Classical chart pattern / channel pressure using raw highs and lows.
    first_hi=max(highs[-16:-8]); second_hi=max(highs[-8:])
    first_lo=min(lows[-16:-8]); second_lo=min(lows[-8:])
    pattern=1 if second_hi>first_hi and second_lo>first_lo else -1 if second_hi<first_hi and second_lo<first_lo else 0

    # 13) Raw volume / effort-result confirmation (volume itself, not an indicator).
    volume_confirm=1 if effort and candle>=0 else -1 if effort and candle<0 else 0

    votes=[dow,pa,sr,candle,breakout,retest,wyckoff,elliott,smc,ict,fib,pattern,volume_confirm]
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
            "chart_pattern":pattern,"raw_volume":volume_confirm}}
def _analyze_symbol(symbol,market):
    def get(interval):
        return _candles(_crypto_klines(symbol,market,interval)) if market in ("spot","futures") else _yahoo(symbol,market,interval)
    c15=get("15m")
    if len(c15)<32 and market not in ("spot","futures"):
        c15=get("30m")
    a=_method_analysis(c15)
    # Forex is a larger, liquid universe. Keep valid 3-vote price-action setups
    # instead of allowing the strict 4-vote gate to collapse the page to one pair.
    if a and a["side"]=="WAIT" and market=="forex":
        methods=a.get("methods") or {}
        bull=sum(1 for v in methods.values() if float(v)>0)
        bear=sum(1 for v in methods.values() if float(v)<0)
        if max(bull,bear)>=3 and bull!=bear:
            a["side"]="BUY" if bull>bear else "SELL"
            price=float(a.get("price") or 0)
            risk=max(price*.008,abs(price-(a.get("support") if a["side"]=="BUY" else a.get("resistance")))*.45)
            if a["side"]=="BUY":
                a["sl"]=price-risk; a["tp1"]=price+risk; a["tp2"]=price+risk*2; a["tp3"]=price+risk*3
            else:
                a["sl"]=price+risk; a["tp1"]=price-risk; a["tp2"]=price-risk*2; a["tp3"]=price-risk*3
            a["targets"]=[a["tp1"],a["tp2"],a["tp3"]]
            a["site_score"]=round(max(bull,bear)/max(1,len(methods))*100,1)
    # العقود الأمريكية: لا نخلي شرط 4/13 الصارم يخنق الصفحة.
    # نحتاج توافق 3 مناهج على الأقل حتى تُنشر فرصة عقد حقيقية.
    # Saudi market: publish only when at least 3 independent price-action
    # methods agree, so the scan does not collapse to just one or two symbols.
    if a and a["side"]=="WAIT" and market=="saudi":
        methods=a.get("methods") or {}
        bull=sum(1 for v in methods.values() if float(v)>0)
        bear=sum(1 for v in methods.values() if float(v)<0)
        if max(bull,bear)>=3 and bull!=bear:
            a["side"]="BUY" if bull>bear else "SELL"
            price=float(a.get("price") or 0)
            ref=a.get("support") if a["side"]=="BUY" else a.get("resistance")
            risk=max(price*.006,abs(price-float(ref or price))*.35)
            if a["side"]=="BUY":
                a["sl"]=price-risk; a["tp1"]=price+risk; a["tp2"]=price+risk*2; a["tp3"]=price+risk*3
            else:
                a["sl"]=price+risk; a["tp1"]=price-risk; a["tp2"]=price-risk*2; a["tp3"]=price-risk*3
            a["targets"]=[a["tp1"],a["tp2"],a["tp3"]]
            a["site_score"]=round(max(bull,bear)/max(1,len(methods))*100,1)
    if not a or a["side"]=="WAIT":return None
    # Multi-timeframe confirmation uses price structure only, no indicators.
    mt=[]
    for tf in ("1h","4h"):
        cc=get(tf); m=_method_analysis(cc) if len(cc)>=32 else None
        if m:mt.append(m["side"])
    if mt:
        agree=sum(x==a["side"] for x in mt)
        # A disagreement on 1h/4h lowers confidence but must not erase a valid
        # 15m opportunity. Otherwise a single higher timeframe can wipe out an
        # entire market and leave only BTC or one external recommendation.
        a["site_score"]=round((a["site_score"]*.70)+(agree/len(mt)*100*.30),1)
        a["multi_timeframe"]=mt
    a["timeframe"]="15m"; a["price_fresh"]=True
    return a

SAUDI_UNIVERSE_CACHE={}

def _saudi_universe(min_volume=1000000):
    key=str(min_volume); now=time.time(); cached=SAUDI_UNIVERSE_CACHE.get(key)
    if cached and now-cached[0]<900:return list(cached[1])
    symbols=[]; seen=set()
    try:
        for offset in range(0,5000,250):
            body={"offset":offset,"size":250,"sortField":"dayvolume","sortType":"DESC","quoteType":"EQUITY","query":{"operator":"AND","operands":[{"operator":"EQ","operands":["region","sa"]},{"operator":"GT","operands":["dayvolume",int(min_volume)]}]}}
            req=urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener",data=json.dumps(body).encode(),headers={"User-Agent":UA,"Content-Type":"application/json"},method="POST")
            raw=json.loads(urllib.request.urlopen(req,timeout=8).read().decode("utf-8","ignore"))
            quotes=(((raw.get("finance") or {}).get("result") or [{}])[0]).get("quotes") or []
            if not quotes:break
            for q in quotes:
                sym=str(q.get("symbol") or "").strip()
                # Yahoo screener already returns Saudi tickers with .SR; store the
                # canonical bare TASI/Nomu symbol because the analysis layer adds .SR.
                if sym.upper().endswith(".SR"): sym=sym[:-3]
                vol=float(q.get("regularMarketVolume") or q.get("dayvolume") or 0)
                if sym and vol>min_volume and sym not in seen:seen.add(sym);symbols.append(sym)
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
        base=_saudi_universe(1000000)
    else:
        base=BASE_UNIVERSE.get(market,[])
    seen=[]
    for s in [r["symbol"] for r in internet]+base:
        if s not in seen:seen.append(s)
    return seen


def _public_scan(market,internet):
    """Market-data scan: recommendations support ranking, never market coverage."""
    symbols=_symbols_for_market(market,internet)
    if market in ("us","saudi"):
        symbols=[s for s in symbols if _passes_volume_filter(s,market)]
    if market in ("spot","futures"):
        symbols=[s for s in symbols if str(s).upper().endswith("USDT")]
    # Keep refreshes fast on the small service; the next refresh continues from
    # the liquid universe rather than requiring external headlines.
    caps={"spot":120,"futures":120,"us":80,"saudi":160,"contracts":20,"forex":34}
    cap=caps.get(market,40)
    if len(symbols)>cap:
        if market in ("spot","futures"):
            q=dict(_crypto_universe(market))
            symbols=sorted(symbols,key=lambda s:q.get(s,0),reverse=True)[:cap]
        else:
            symbols=symbols[:cap]
    out=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(_analyze_symbol,s,market):s for s in symbols}
        for fut in as_completed(jobs):
            try:a=fut.result()
            except Exception:a=None
            if not a or a.get("side") not in {"BUY","SELL"}:continue
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
                "symbol":sym,"direction":a["side"],"side":a["side"],
                "entry":a.get("entry"),"targets":a.get("targets"),
                "tp1":a.get("tp1"),"tp2":a.get("tp2"),"tp3":a.get("tp3"),"sl":a.get("sl"),
                "ai_pct":round(final_score,1),
                "recommendation_score":round(final_score,1),
                "site_score":tech,
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
        if market in ("us", "saudi"):
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

def discover(market):
    """Combine broad public market-data analysis with external recommendation coverage.
    Public analysis is primary for market coverage; external recommendations only
    improve ranking/confirmation. Public rows are never re-filtered as external news.
    """
    now=time.time(); key="external:"+market; cached=CACHE.get(key)
    if cached and now-cached[0]<DISCOVER_TTL:
        return list(cached[1])

    persisted=_load_persisted(market)
    internet=_internet(market)
    public_rows=_public_scan(market,internet)

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
    groups={}
    for r in rows:groups.setdefault((r.get("market"),r.get("symbol")),[]).append(r)
    return sorted((dict(max(v,key=lambda x:float(x.get("ai_pct") or 0))) for v in groups.values()),key=lambda x:float(x.get("ai_pct") or 0),reverse=True)
