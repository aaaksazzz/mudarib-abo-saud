import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET,json
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed

MAX_AGE=24*3600
DISCOVER_TTL=180.0
FETCH_TIMEOUT=6.0
ARTICLE_TIMEOUT=4.0
UA="SMART-TRADING-PRO/4.0 external-sources"
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
MIN_STOCK_VOLUME=1_000_000.0
VOLUME_TTL=300.0
DISCOVER_CACHE={}
VOLUME_CACHE={"crypto":(0.0,set()),"stocks":(0.0,set())}
ARTICLE_CACHE={}
PROVIDER_CACHE={}

MARKET_QUERIES={
 "spot":['crypto signal entry target stop','crypto trade setup entry TP SL','BTCUSDT signal entry target stop','ETHUSDT signal entry target stop','SOLUSDT signal entry target stop','altcoin signal entry target stop'],
 "futures":['crypto futures signal entry target stop','Binance futures signal entry TP SL','BTC futures signal entry target stop','ETH futures signal entry target stop','perpetual futures signal entry target stop'],
 "us":['US stock signal entry target stop','NASDAQ stock trade idea entry target stop','NYSE stock signal entry TP SL','US equity trade setup entry target stop'],
 "saudi":['TASI توصية دخول هدف وقف','تاسي شراء دخول هدف وقف','السوق السعودي توصية دخول هدف وقف','Saudi stock signal entry target stop','Tadawul trade setup entry target stop'],
 "contracts":['XAUUSD signal entry target stop','gold trade setup entry TP SL','oil signal entry target stop','WTI trade setup entry target stop','silver signal entry target stop','indices trade signal entry target stop'],
 "forex":['forex signal entry target stop','forex trade setup entry TP SL','EURUSD signal entry target stop','GBPUSD signal entry target stop','USDJPY signal entry target stop']
}

def _fetch(url,timeout=FETCH_TIMEOUT):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json,application/rss+xml,text/xml,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()

def _json(url,timeout=FETCH_TIMEOUT):
    return json.loads(_fetch(url,timeout).decode("utf-8","ignore"))

def _news(q):
    u="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
    try:root=ET.fromstring(_fetch(u))
    except Exception:return []
    out=[]
    for x in root.findall(".//item"):
        out.append({"title":html.unescape(x.findtext("title") or ""),"text":html.unescape(re.sub("<[^>]+>"," ",x.findtext("description") or "")),"url":x.findtext("link") or "","published":x.findtext("pubDate") or ""})
    return out[:15]

def _article(url):
    if not url:return ""
    c=ARTICLE_CACHE.get(url);now=time.time()
    if c and now-c[0]<1800:return c[1]
    try:
        s=_fetch(url,ARTICLE_TIMEOUT).decode("utf-8","ignore")
        s=re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\\1>"," ",s)
        s=re.sub(r"(?is)<[^>]+>"," ",s);s=html.unescape(s);s=re.sub(r"\\s+"," ",s).strip()[:40000]
    except Exception:s=""
    ARTICLE_CACHE[url]=(now,s);return s

def _num(v):
    try:return float(str(v).replace(",","").replace("$","").strip())
    except:return None

def _fresh(v):
    if not v:return True
    try:
        from email.utils import parsedate_to_datetime
        d=parsedate_to_datetime(str(v))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return 0<=(datetime.now(timezone.utc)-d).total_seconds()<=MAX_AGE
    except:return True

def _symbol(text,market):
    t=text.upper()
    if market in ("spot","futures"):
        for p in (r"\\b([A-Z0-9]{2,15})\\s*(?:/|-)\\s*USDT\\b",r"\\b([A-Z0-9]{2,15})USDT\\b"):
            m=re.search(p,t)
            if m:return m.group(1)+"USDT"
        aliases={"BITCOIN":"BTCUSDT","BTC":"BTCUSDT","ETHEREUM":"ETHUSDT","ETH":"ETHUSDT","SOLANA":"SOLUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","BNB":"BNBUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","TRX":"TRXUSDT","LINK":"LINKUSDT"}
        for a,s in aliases.items():
            if re.search(r"\\b"+a+r"\\b",t):return s
        return None
    if market=="us":
        blocked={"BUY","SELL","LONG","SHORT","CALL","PUT","STOCK","SIGNAL","ENTRY","TARGET","STOP","LOSS","TRADE","SETUP","NASDAQ","NYSE"}
        m=re.search(r"\\$([A-Z]{1,5})\\b",t)
        if m and m.group(1) not in blocked:return m.group(1)
        m=re.search(r"\\b(?:NASDAQ|NYSE)[:\\s]+([A-Z]{1,5})\\b",t)
        return m.group(1) if m and m.group(1) not in blocked else None
    pats={"saudi":r"\\b(\\d{4})\\b","contracts":r"\\b(XAUUSD|GOLD|WTI|USOIL|SPX|NDX|NAS100|US30)\\b","forex":r"\\b([A-Z]{3}/?[A-Z]{3})\\b"}
    m=re.search(pats.get(market,r"\\b[A-Z]{2,10}\\b"),t)
    return m.group(1).upper() if m else None

def _extract_text(text):
    t=text.replace(","," ")
    dm=re.search(r"(?i)\\b(BUY|LONG|CALL|BULLISH|شراء|صعود|صاعد)\\b",t)
    sm=re.search(r"(?i)\\b(SELL|SHORT|PUT|BEARISH|بيع|هبوط|هابط)\\b",t)
    if dm and sm and abs(dm.start()-sm.start())<250:return None,None,[],None
    direction="BUY" if dm and (not sm or dm.start()<sm.start()) else "SELL" if sm else None
    if not direction:return None,None,[],None
    entry=None
    for p in [r"(?i)\\b(?:entry(?:\\s+price)?|entry\\s+zone|buy\\s+at|sell\\s+at|دخول|سعر\\s+الدخول)\\s*[:=@\\-]?\\s*(\\d+(?:\\.\\d+)?)",r"(?i)\\b(?:from|at)\\s*(\\d+(?:\\.\\d+)?)\\b"]:
        m=re.search(p,t)
        if m:entry=_num(m.group(1));break
    targets=[_num(m.group(1)) for p in [r"(?i)\\b(?:take[- ]?profit|target|tp\\s*\\d*|tp|هدف(?:\\s*\\d+)?)\\s*[:#=@\\-]?\\s*(\\d+(?:\\.\\d+)?)"] for m in re.finditer(p,t)]
    m=re.search(r"(?i)\\b(?:stop[- ]?loss|stop|sl|وقف(?:\\s+الخسارة)?)\\s*[:#=@\\-]?\\s*(\\d+(?:\\.\\d+)?)",t)
    return direction,entry,[x for x in targets if x is not None],_num(m.group(1)) if m else None

def _valid(direction,entry,tps,sl):
    if direction not in ("BUY","SELL") or entry is None or not tps or sl is None:return False
    return (sl<entry and any(x>entry for x in tps)) if direction=="BUY" else (sl>entry and any(x<entry for x in tps))

def _trade_from_text(symbol,text,source,title="",published=None,url=""):
    d,e,t,s=_extract_text(text)
    if not _valid(d,e,t,s):return None
    return {"symbol":symbol,"direction":d,"entry":e,"targets":t[:3],"tp1":t[0],"tp2":t[1] if len(t)>1 else None,"tp3":t[2] if len(t)>2 else None,"sl":s,"source":source,"source_title":title,"source_published":published,"source_url":url,"research_mode":True,"research_only":True,"reason":"صفقة خارجية مكتملة"}

def _walk(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():yield from _walk(v)
    elif isinstance(obj,list):
        for v in obj:yield from _walk(v)

def _provider_value(o,*names):
    low={str(k).lower():v for k,v in o.items()}
    for n in names:
        v=low.get(n.lower())
        if v not in (None,"",[]):return v
    return None

def _external_crypto_signals():
    now=time.time();c=PROVIDER_CACHE.get("crypto_cv")
    if c and now-c[0]<120:return c[1]
    try:
        data=_json("https://cryptocurrency.cv/api/signals",timeout=8)
    except Exception:return []
    out=[]
    for o in _walk(data):
        if not isinstance(o,dict):continue
        sym=_provider_value(o,"symbol","asset","ticker","coin")
        direction=_provider_value(o,"direction","side","signal","bias")
        entry=_num(_provider_value(o,"entry","entry_price","entryPrice","buy_price","sell_price"))
        sl=_num(_provider_value(o,"stop","stop_loss","stopLoss","sl","stop_price"))
        rawtp=_provider_value(o,"targets","take_profit","take_profits","takeProfit","tp","target","target_price")
        if isinstance(rawtp,list):tps=[_num(x) if not isinstance(x,dict) else _num(_provider_value(x,"price","value","target")) for x in rawtp]
        else:tps=[_num(rawtp)]
        tps=[x for x in tps if x is not None]
        if not sym or not direction or entry is None or sl is None or not tps:continue
        sym=str(sym).upper().replace("/USDT","USDT").replace("-USDT","USDT")
        if not sym.endswith("USDT"):sym+="USDT"
        ds=str(direction).upper()
        d="BUY" if any(x in ds for x in ("BUY","LONG","BULL")) else "SELL" if any(x in ds for x in ("SELL","SHORT","BEAR")) else None
        if not _valid(d,entry,tps,sl):continue
        out.append({"symbol":sym,"direction":d,"entry":entry,"targets":tps[:3],"tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,"tp3":tps[2] if len(tps)>2 else None,"sl":sl,"source":"cryptocurrency.cv","source_title":"External trading signal provider","source_published":_provider_value(o,"timestamp","created_at","published_at","published"),"source_url":"https://cryptocurrency.cv/api/signals","research_mode":True,"research_only":True,"reason":"إشارة خارجية مكتملة"})
    PROVIDER_CACHE["crypto_cv"]=(now,out)
    return out

def _crypto_symbols_over_volume():
    now=time.time();at,syms=VOLUME_CACHE["crypto"]
    if now-at<VOLUME_TTL:return syms
    data=None
    for u in ("https://api.binance.com/api/v3/ticker/24hr","https://api-gcp.binance.com/api/v3/ticker/24hr","https://data-api.binance.vision/api/v3/ticker/24hr"):
        try:data=_json(u,3);break
        except Exception:pass
    if not isinstance(data,list):return syms
    good={str(x.get("symbol","")).upper() for x in data if str(x.get("symbol","")).upper().endswith("USDT") and float(x.get("quoteVolume") or 0)>=MIN_CRYPTO_QUOTE_VOLUME}
    VOLUME_CACHE["crypto"]=(now,good);return good

def _stock_symbols_over_volume(symbols):
    now=time.time();at,known=VOLUME_CACHE["stocks"]
    if now-at<VOLUME_TTL:return symbols&known
    if not symbols:return set()
    def check(s):
        try:
            d=_json("https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(s)+"?range=1d&interval=1d",2)
            r=(d.get("chart",{}).get("result") or [None])[0]
            v=(((r.get("indicators",{}).get("quote") or [{}])[0].get("volume") or []) if r else [])
            return s if v and float(v[-1] or 0)>=MIN_STOCK_VOLUME else None
        except Exception:return None
    with ThreadPoolExecutor(max_workers=min(12,len(symbols))) as p:good={x for x in p.map(check,symbols) if x}
    VOLUME_CACHE["stocks"]=(now,good);return symbols&good

def _news_trades(market):
    rows=[];qs=MARKET_QUERIES.get(market,[])
    crypto_allowed=_crypto_symbols_over_volume() if market in ("spot","futures") else None
    with ThreadPoolExecutor(max_workers=min(10,max(1,len(qs)))) as p:
        fs=[p.submit(_news,q) for q in qs]
        for f in as_completed(fs):
            try:hits=f.result()
            except Exception:hits=[]
            for h in hits:
                if not _fresh(h.get("published")):continue
                full=h.get("title","")+" "+h.get("text","")+" "+_article(h.get("url",""))
                sym=_symbol(full,market)
                if not sym or (crypto_allowed is not None and sym not in crypto_allowed):continue
                r=_trade_from_text(sym,full,"Google News / original article",h.get("title"),h.get("published"),h.get("url"))
                if r:rows.append(r)
    if market=="us":rows=[r for r in rows if r["symbol"] in _stock_symbols_over_volume({x["symbol"] for x in rows})]
    return rows

def discover(market):
    now=time.time()
    c=DISCOVER_CACHE.get(market)
    if c and now-c[0]<DISCOVER_TTL:return list(c[1])
    rows=[]
    if market in ("spot","futures"):
        rows.extend(_external_crypto_signals())
    rows.extend(_news_trades(market))
    # Deduplicate exact repeats, while preserving genuinely different providers.
    seen=set();clean=[]
    for r in rows:
        k=(r.get("market",market),r["symbol"],r["direction"],r["entry"],r["sl"],r.get("source"))
        if k in seen:continue
        r["market"]=market;r["volume_filter"]=">=1M quote volume" if market in ("spot","futures") else None
        seen.add(k);clean.append(r)
    DISCOVER_CACHE[market]=(now,clean)
    return clean

def decide(rows):
    groups={}
    for r in rows:groups.setdefault((r.get("market"),r.get("symbol")),[]).append(r)
    out=[]
    for key,items in groups.items():
        buys=sum(x.get("direction")=="BUY" for x in items);sells=sum(x.get("direction")=="SELL" for x in items)
        if buys==sells:continue
        direction="BUY" if buys>sells else "SELL"
        chosen=[x for x in items if x.get("direction")==direction]
        sources={x.get("source") for x in chosen if x.get("source")}
        agreement=round(max(buys,sells)/len(items)*100)
        # A single complete external signal is publishable; multiple independent
        # providers are ranked higher. No internal technical score is generated.
        best=dict(chosen[0])
        best["research_sources"]=len(sources)
        best["source_count"]=len(sources)
        best["research_agreement"]=agreement
        best["external_agreement"]=agreement
        best["recommendation_score"]=round(agreement+min(len(sources),10)*2,1)
        best["decision"]=direction
        out.append(best)
    return sorted(out,key=lambda x:(x["source_count"],x["external_agreement"]),reverse=True)
