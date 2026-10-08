import re, time, html, urllib.parse, urllib.request, xml.etree.ElementTree as ET, json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_AGE=24*3600
DISCOVER_CACHE={}
DISCOVER_TTL=300.0
FETCH_TIMEOUT=4.5
ARTICLE_TIMEOUT=3.5
UA="SMART-TRADING-PRO/3.2 external-feed"
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
MIN_STOCK_VOLUME=1_000_000.0
VOLUME_TTL=300.0
VOLUME_CACHE={"crypto":(0.0,set()),"stocks":(0.0,set())}
ARTICLE_CACHE={}

MARKET_QUERIES={
 "spot":[
  '"crypto signal" entry target stop','"crypto signal" entry tp sl','crypto trade setup entry target stop',
  'crypto signal buy entry target stop','crypto signal sell entry target stop',
  '"BTCUSDT" entry target stop','"ETHUSDT" entry target stop','"SOLUSDT" entry target stop',
  '"BTC" crypto signal entry TP SL','"ETH" crypto signal entry TP SL','"SOL" crypto signal entry TP SL',
  'altcoin signal entry target stop','Binance signal entry target stop','crypto setup entry take profit stop loss'
 ],
 "futures":[
  '"crypto futures" entry target stop','"crypto futures" long entry target stop','"crypto futures" short entry target stop',
  'Binance futures signal entry target stop','perpetual futures signal entry target stop',
  '"BTC futures" entry target stop','"ETH futures" entry target stop','futures trade setup entry TP SL'
 ],
 "us":[
  '"US stocks" trade setup entry target stop','US stock signal entry target stop','US stock trade idea entry target stop',
  'NASDAQ stock signal entry target stop','NYSE stock signal entry target stop','stock setup entry TP SL',
  '"$" stock signal entry target stop'
 ],
 "saudi":[
  '"TASI" توصية دخول هدف وقف','"تاسي" شراء دخول هدف وقف','"السوق السعودي" توصية دخول هدف وقف',
  'Saudi stock signal entry target stop','Tadawul trade setup entry target stop'
 ],
 "contracts":[
  '"XAUUSD" signal entry target stop','"gold" signal entry target stop','"XAUUSD" trade setup entry TP SL',
  '"oil" signal entry target stop','WTI trade setup entry target stop','silver signal entry target stop',
  'indices trade signal entry target stop'
 ],
 "forex":[
  '"forex signal" entry target stop','forex trade setup entry TP SL','"EURUSD" signal entry target stop',
  '"GBPUSD" signal entry target stop','"USDJPY" signal entry target stop','"AUDUSD" signal entry target stop',
  '"USDCAD" signal entry target stop','"USDCHF" signal entry target stop'
 ]
}

def _fetch(url,timeout=FETCH_TIMEOUT):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/rss+xml,text/xml,application/json,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()

def _news(q):
    url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
    try:root=ET.fromstring(_fetch(url))
    except Exception:return []
    out=[]
    for item in root.findall(".//item"):
        title=html.unescape(item.findtext("title") or "")
        desc=html.unescape(re.sub("<[^>]+>"," ",item.findtext("description") or ""))
        out.append({"title":title,"text":desc,"url":item.findtext("link") or "","published":item.findtext("pubDate") or ""})
    return out[:12]

def _article_text(url):
    if not url:return ""
    now=time.time()
    cached=ARTICLE_CACHE.get(url)
    if cached and now-cached[0]<1800:return cached[1]
    try:
        raw=_fetch(url,timeout=ARTICLE_TIMEOUT)
        s=raw.decode("utf-8","ignore")
        s=re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>"," ",s)
        s=re.sub(r"(?is)<[^>]+>"," ",s)
        s=html.unescape(s)
        s=re.sub(r"\s+"," ",s).strip()
        text=s[:30000]
    except Exception:
        text=""
    ARTICLE_CACHE[url]=(now,text)
    return text

def _num(s):
    try:return float(str(s).replace(",","").replace("$","").strip())
    except:return None

def _extract(text):
    t=text.replace(","," ")
    # Determine direction from an explicit trade instruction, not from incidental
    # words elsewhere in the article. This keeps external recommendations intact.
    dms=list(re.finditer(r"(?i)\b(BUY|LONG|CALL|BULLISH|شراء|صعود|صاعد|ارتفاع)\b",t))
    sms=list(re.finditer(r"(?i)\b(SELL|SHORT|PUT|BEARISH|بيع|هبوط|هابط|انخفاض)\b",t))
    def first_near(patterns):
        hits=[]
        for p in patterns:hits.extend(re.finditer(p,t,re.I))
        return min(hits,key=lambda m:m.start()) if hits else None
    # Prefer an explicit label close to entry/targets; only fall back to the first
    # directional instruction if one side is clearly dominant.
    direction=None
    dm=first_near([r"\b(BUY|LONG|CALL|BULLISH)\b",r"\b(شراء|صعود|صاعد|ارتفاع)\b"])
    sm=first_near([r"\b(SELL|SHORT|PUT|BEARISH)\b",r"\b(بيع|هبوط|هابط|انخفاض)\b"])
    if dm and sm and abs(dm.start()-sm.start())<180:
        return None,None,[],None
    if dm and (not sm or dm.start()<sm.start()):direction="BUY"
    elif sm:direction="SELL"
    else:return None,None,[],None

    entry_patterns=[
      r"(?i)\b(?:entry(?:\s+price)?|entry\s+zone|buy\s+at|sell\s+at|دخول|سعر\s+الدخول)\s*[:=@\-]?\s*(\d+(?:\.\d+)?)",
      r"(?i)\b(?:from|at)\s*(\d+(?:\.\d+)?)\b"
    ]
    entry=None
    for p in entry_patterns:
        m=re.search(p,t)
        if m:
            entry=_num(m.group(1));break
    target_patterns=[
      r"(?i)\b(?:take[- ]?profit|target|tp\s*\d*|tp|هدف(?:\s*\d+)?)\s*[:#=@\-]?\s*(\d+(?:\.\d+)?)",
      r"(?i)\b(?:t\s*p)\s*(?:\d+)?\s*[:#=@\-]?\s*(\d+(?:\.\d+)?)"
    ]
    targets=[_num(m.group(1)) for p in target_patterns for m in re.finditer(p,t)]
    targets=[x for x in targets if x is not None]
    slm=re.search(r"(?i)\b(?:stop[- ]?loss|stop\s+loss|sl|stop|وقف(?:\s+الخسارة)?)\s*[:#=@\-]?\s*(\d+(?:\.\d+)?)",t)
    sl=_num(slm.group(1)) if slm else None
    return direction,entry,targets,sl

def _symbol(text,market):
    t=text.upper()
    aliases={
      "BITCOIN":"BTCUSDT","BTC":"BTCUSDT","ETHEREUM":"ETHUSDT","ETH":"ETHUSDT",
      "SOLANA":"SOLUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","BINANCE COIN":"BNBUSDT",
      "BNB":"BNBUSDT","DOGE":"DOGEUSDT","DOGECOIN":"DOGEUSDT","CARDANO":"ADAUSDT",
      "ADA":"ADAUSDT","TRON":"TRXUSDT","TRX":"TRXUSDT","AVALANCHE":"AVAXUSDT","AVAX":"AVAXUSDT"
    }
    if market in ("spot","futures"):
        m=re.search(r"\b([A-Z0-9]{2,15})\s*(?:/|-)\s*USDT\b",t)
        if m:return m.group(1)+"USDT"
        m=re.search(r"\b([A-Z0-9]{2,15})USDT\b",t)
        if m:return m.group(1)+"USDT"
        for name,sym in aliases.items():
            if re.search(r"\b"+re.escape(name)+r"\b",t):return sym
        return None
    if market=="us":
        blocked={"BUY","SELL","LONG","SHORT","CALL","PUT","BULL","BEAR","SIGNAL","STOCK","NASDAQ","NYSE","ENTRY","TARGET","STOP","LOSS","TRADE","SETUP"}
        m=re.search(r"\$([A-Z]{1,5})\b",t)
        if m and m.group(1) not in blocked:return m.group(1)
        m=re.search(r"\b(?:NASDAQ|NYSE)[:\s]+([A-Z]{1,5})\b",t)
        if m and m.group(1) not in blocked:return m.group(1)
        return None
    pats={"saudi":r"\b(\d{4})\b","contracts":r"\b(XAUUSD|GOLD|WTI|USOIL|SPX|NDX|NAS100|US30)\b","forex":r"\b([A-Z]{3}/?[A-Z]{3})\b"}
    m=re.search(pats.get(market,r"\b[A-Z]{2,10}\b"),t)
    return m.group(1).upper() if m else None

def _fresh(pub):
    if not pub:return False
    try:
        from email.utils import parsedate_to_datetime
        dt=parsedate_to_datetime(pub)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        age=(datetime.now(timezone.utc)-dt).total_seconds()
        return 0<=age<=MAX_AGE
    except Exception:return False

def _crypto_symbols_over_volume():
    now=time.time();at,syms=VOLUME_CACHE["crypto"]
    if now-at<VOLUME_TTL:return syms
    data=None
    for url in ("https://api.binance.com/api/v3/ticker/24hr","https://api-gcp.binance.com/api/v3/ticker/24hr","https://data-api.binance.vision/api/v3/ticker/24hr"):
        try:data=json.loads(_fetch(url,timeout=3));break
        except Exception:continue
    if not isinstance(data,list):return syms
    result={str(x.get("symbol","")).upper() for x in data if str(x.get("symbol","")).upper().endswith("USDT") and float(x.get("quoteVolume") or 0)>=MIN_CRYPTO_QUOTE_VOLUME}
    VOLUME_CACHE["crypto"]=(now,result)
    return result

def _stock_symbols_over_volume(symbols):
    now=time.time();at,known=VOLUME_CACHE["stocks"]
    if now-at<VOLUME_TTL:return symbols & known
    if not symbols:return set()
    def check(sym):
        try:
            url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(sym)+"?range=1d&interval=1d"
            data=json.loads(_fetch(url,timeout=1.8))
            result=data.get("chart",{}).get("result") or []
            vol=((result[0].get("indicators",{}).get("quote") or [{}])[0].get("volume") or []) if result else []
            return sym if vol and float(vol[-1] or 0)>=MIN_STOCK_VOLUME else None
        except Exception:return None
    with ThreadPoolExecutor(max_workers=min(16,len(symbols))) as pool:
        checked=pool.map(check,symbols)
    good={x for x in checked if x};VOLUME_CACHE["stocks"]=(now,good)
    return symbols & good

def _complete_external_trade(hit,market):
    base=hit.get("title","")+" "+hit.get("text","")
    full=base+" "+_article_text(hit.get("url",""))
    direction,entry,tps,sl=_extract(full)
    if not direction or entry is None or not tps or sl is None:return None
    # Never invent levels. Reject geometrically invalid external trades.
    if direction=="BUY":
        valid=any(x>entry for x in tps) and sl<entry
    else:
        valid=any(x<entry for x in tps) and sl>entry
    if not valid:return None
    return direction,entry,tps[:3],sl,"صفقة خارجية مكتملة"

def discover(market):
    now=time.time()
    cached=DISCOVER_CACHE.get(market)
    if cached and now-cached[0]<DISCOVER_TTL:return list(cached[1])
    rows=[];queries=MARKET_QUERIES.get(market,[])
    crypto_allowed=_crypto_symbols_over_volume() if market in ("spot","futures") else None
    with ThreadPoolExecutor(max_workers=min(16,max(1,len(queries)))) as pool:
        futures=[pool.submit(_news,q) for q in queries]
        for fut in as_completed(futures):
            try:hits=fut.result()
            except Exception:hits=[]
            for hit in hits:
                if not _fresh(hit.get("published")):continue
                text=hit.get("title","")+" "+hit.get("text","")+" "+_article_text(hit.get("url",""))
                sym=_symbol(text,market)
                if not sym:continue
                if market in ("spot","futures") and (crypto_allowed is None or sym not in crypto_allowed):continue
                parsed=_complete_external_trade(hit,market)
                if not parsed:continue
                direction,entry,tps,sl,reason=parsed
                rows.append({"market":market,"symbol":sym,"direction":direction,"entry":entry,"targets":tps[:3],
                    "tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,"tp3":tps[2] if len(tps)>2 else None,
                    "sl":sl,"source":hit.get("url"),"source_title":hit.get("title"),
                    "source_published":hit.get("published"),"research_mode":True,"research_only":True,
                    "volume_filter":">=1M quote volume","reason":reason})
    if market=="us":
        allowed=_stock_symbols_over_volume({r["symbol"] for r in rows});rows=[r for r in rows if r["symbol"] in allowed]
    seen=set();clean=[]
    for r in rows:
        k=(r["symbol"],r["direction"],r.get("source"))
        if k in seen:continue
        seen.add(k);clean.append(r)
    DISCOVER_CACHE[market]=(now,list(clean))
    return clean

def decide(rows):
    groups={}
    for r in rows:groups.setdefault((r["market"],r["symbol"]),[]).append(r)
    out=[]
    for _,items in groups.items():
        buys=sum(x["direction"]=="BUY" for x in items);sells=sum(x["direction"]=="SELL" for x in items)
        direction="BUY" if buys>sells else ("SELL" if sells>buys else None)
        if not direction:continue
        chosen=[x for x in items if x["direction"]==direction]
        best=dict(chosen[0])
        sources={x.get("source") for x in chosen if x.get("source")}
        best["research_sources"]=len(sources)
        best["research_agreement"]=round(max(buys,sells)/max(1,len(items))*100)
        best["decision"]=direction
        # Ranking is based only on external agreement/source count; no technical AI score.
        best["recommendation_score"]=round(best["research_agreement"]+min(best["research_sources"],10)*2,1)
        best["source_count"]=best["research_sources"]
        best["external_agreement"]=best["research_agreement"]
        out.append(best)
    return sorted(out,key=lambda x:(x.get("source_count",0),x.get("external_agreement",0)),reverse=True)
