import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET,json,math
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed

UA="SMART-TRADING-PRO/5.0 hybrid-analysis"
DISCOVER_TTL=45.0
FETCH_TIMEOUT=5.0
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
MIN_STOCK_VOLUME=1_000_000.0
CACHE={}

MARKET_QUERIES={
 "spot":["crypto trading recommendation BUY SELL","crypto market recommendation today","BTC ETH SOL altcoin recommendation"],
 "futures":["crypto futures recommendation LONG SHORT","Binance futures recommendation","BTC ETH futures long short"],
 "us":["US stock recommendation BUY SELL today","NASDAQ stock recommendation","NYSE stock recommendation"],
 "saudi":["توصية تداول تاسي شراء بيع","السوق السعودي توصيات أسهم اليوم","توصيات تداول السوق السعودي"],
 "contracts":["gold oil index trading recommendation BUY SELL","XAUUSD recommendation","US30 NAS100 SPX recommendation"],
 "forex":["forex recommendation BUY SELL today","EURUSD GBPUSD USDJPY recommendation"]
}

BINANCE_SPOT="https://api.binance.com"
BINANCE_FUTURES="https://fapi.binance.com"
YAHOO="https://query1.finance.yahoo.com"

def _fetch(url,timeout=FETCH_TIMEOUT):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json,application/rss+xml,text/xml,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()

def _json(url,timeout=FETCH_TIMEOUT):
    return json.loads(_fetch(url,timeout).decode("utf-8","ignore"))

def _num(v):
    try:return float(str(v).replace(",","").replace("$","").strip())
    except:return None

def _news(q):
    u="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
    try:root=ET.fromstring(_fetch(u))
    except Exception:return []
    out=[]
    for x in root.findall(".//item"):
        out.append({"title":html.unescape(x.findtext("title") or ""),"text":html.unescape(re.sub("<[^>]+>"," ",x.findtext("description") or "")),"url":x.findtext("link") or "","published":x.findtext("pubDate") or ""})
    return out[:20]

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
    t=text.upper()
    if market in ("spot","futures"):
        aliases={"BITCOIN":"BTCUSDT","BTC":"BTCUSDT","ETHEREUM":"ETHUSDT","ETH":"ETHUSDT","SOLANA":"SOLUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","BNB":"BNBUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","TRX":"TRXUSDT","LINK":"LINKUSDT"}
        m=re.search(r"\b([A-Z0-9]{2,15})\s*(?:/|-)\s*USDT\b",t) or re.search(r"\b([A-Z0-9]{2,15})USDT\b",t)
        if m:return m.group(1)+"USDT"
        for a,s in aliases.items():
            if re.search(r"\b"+a+r"\b",t):return s
    if market=="us":
        m=re.search(r"\$([A-Z]{1,5})\b",t) or re.search(r"\b(?:NASDAQ|NYSE)[:\s]+([A-Z]{1,5})\b",t)
        if m and m.group(1) not in {"BUY","SELL","LONG","SHORT","CALL","PUT","STOCK","SIGNAL"}:return m.group(1)
    if market=="saudi":
        m=re.search(r"\b(\d{4})\b",t)
        return m.group(1) if m else None
    if market=="contracts":
        m=re.search(r"\b(XAUUSD|GOLD|WTI|USOIL|SPX|SP500|NDX|NAS100|US30|DOW)\b",t)
        return {"GOLD":"XAUUSD","WTI":"WTI","USOIL":"WTI","SP500":"SPX","DOW":"US30"}.get(m.group(1),m.group(1)) if m else None
    if market=="forex":
        m=re.search(r"\b([A-Z]{3}\s*/?\s*[A-Z]{3})\b",t)
        return m.group(1).replace(" ","").replace("/","") if m else None
    return None

def _direction(text):
    t=text.upper()
    buys=re.findall(r"\b(BUY|LONG|BULLISH|شراء|صعود|صاعد)\b",t)
    sells=re.findall(r"\b(SELL|SHORT|BEARISH|بيع|هبوط|هابط)\b",t)
    if buys and not sells:return "BUY"
    if sells and not buys:return "SELL"
    return None

def _internet(market):
    rows=[]
    with ThreadPoolExecutor(max_workers=min(8,len(MARKET_QUERIES.get(market,[])))) as p:
        fs=[p.submit(_news,q) for q in MARKET_QUERIES.get(market,[])]
        for f in as_completed(fs):
            try:hits=f.result()
            except Exception:hits=[]
            for h in hits:
                full=h["title"]+" "+h["text"]+" "+_article(h["url"])
                sym=_symbol(full,market); d=_direction(full)
                if sym and d:
                    rows.append({"symbol":sym,"direction":d,"source":"internet","source_title":h["title"],"source_published":h["published"],"source_url":h["url"]})
    # One article is one vote; cap duplicates from the same headline.
    seen=set(); out=[]
    for r in rows:
        k=(r["symbol"],r["direction"],r["source_title"])
        if k not in seen:seen.add(k);out.append(r)
    return out

def _binance24(futures=False):
    url=(BINANCE_FUTURES if futures else BINANCE_SPOT)+"/fapi/v1/ticker/24hr" if futures else BINANCE_SPOT+"/api/v3/ticker/24hr"
    try:return _json(url,5)
    except Exception:return []

def _crypto_universe(market):
    data=_binance24(market=="futures")
    out=[]
    for x in data:
        s=str(x.get("symbol","")).upper()
        if not s.endswith("USDT") or s in {"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","BUSDUSDT"}:continue
        try:v=float(x.get("quoteVolume") or 0)
        except:v=0
        if v>=MIN_CRYPTO_QUOTE_VOLUME:out.append((s,v))
    return sorted(out,key=lambda z:z[1],reverse=True)

def _crypto_klines(symbol,market,limit=120):
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    u=base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":"15m","limit":limit})
    try:return _json(u,6)
    except Exception:return []

def _yahoo(symbol,market,limit=120):
    maps={"us":symbol,"saudi":symbol+".SR","contracts":{"XAUUSD":"GC=F","WTI":"CL=F","SPX":"^GSPC","NDX":"^NDX","NAS100":"NQ=F","US30":"YM=F"}.get(symbol,symbol),"forex":symbol[:3]+"="+symbol[3:]+"%3DX"}
    y=maps.get(market,symbol)
    interval="15m" if market in ("us","saudi","contracts","forex") else "15m"
    rng="60d" if interval=="15m" else "1y"
    try:
        d=_json(YAHOO+"/v8/finance/chart/"+urllib.parse.quote(y,safe="")+"?interval="+interval+"&range="+rng,6)
        r=(d.get("chart",{}).get("result") or [None])[0]
        q=((r or {}).get("indicators",{}).get("quote") or [{}])[0]
        o,h,l,c,v=q.get("open",[]),q.get("high",[]),q.get("low",[]),q.get("close",[]),q.get("volume",[])
        out=[]
        for a,b,lo,cl,vol in zip(o,h,l,c,v):
            if None not in (a,b,lo,cl):out.append({"open":float(a),"high":float(b),"low":float(lo),"close":float(cl),"volume":float(vol or 0)})
        return out[-limit:]
    except Exception:return []

def _candles(raw):
    out=[]
    for x in raw:
        try:
            if isinstance(x,dict):out.append(x)
            else:out.append({"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except Exception:pass
    return out

def _ema(vals,n):
    if len(vals)<n:return None
    k=2/(n+1);e=sum(vals[:n])/n
    for v in vals[n:]:e=v*k+e*(1-k)
    return e

def _rsi(vals,n=14):
    if len(vals)<n+1:return 50.0
    gains=[];loss=[]
    for a,b in zip(vals[-n-1:-1],vals[-n:]):
        d=b-a;gains.append(max(d,0));loss.append(max(-d,0))
    ag=sum(gains)/n; al=sum(loss)/n
    return 100 if al==0 else 100-(100/(1+ag/al))

def _technical(c):
    if len(c)<50:return None
    closes=[x["close"] for x in c]; highs=[x["high"] for x in c]; lows=[x["low"] for x in c]; vols=[x["volume"] for x in c]
    price=closes[-1]; ema20=_ema(closes,20); ema50=_ema(closes,50); rsi=_rsi(closes)
    avgvol=sum(vols[-21:-1])/max(1,len(vols[-21:-1])); vr=vols[-1]/max(avgvol,1)
    support=min(lows[-30:]); resistance=max(highs[-30:])
    prev=c[-2]; cur=c[-1]; body=abs(cur["close"]-cur["open"]); rng=max(cur["high"]-cur["low"],1e-12)
    bullish_candle=(cur["close"]>cur["open"] and body/rng>=.45)
    bearish_candle=(cur["close"]<cur["open"] and body/rng>=.45)
    breakout_up=cur["close"]>max(highs[-21:-1])
    breakout_dn=cur["close"]<min(lows[-21:-1])
    retest_up=price>ema20 and abs(price-resistance)/max(price,1)<.006
    retest_dn=price<ema20 and abs(price-support)/max(price,1)<.006
    # 8 independent methods, 0..100 each side.
    bull=bear=0.0
    bull += 1 if price>ema20 else 0; bear += 1 if price<ema20 else 0
    bull += 1 if ema20 and ema50 and ema20>ema50 else 0; bear += 1 if ema20 and ema50 and ema20<ema50 else 0
    bull += 1 if rsi>52 else 0; bear += 1 if rsi<48 else 0
    bull += 1 if vr>=1.05 and cur["close"]>cur["open"] else 0; bear += 1 if vr>=1.05 and cur["close"]<cur["open"] else 0
    bull += 1 if bullish_candle else 0; bear += 1 if bearish_candle else 0
    bull += 2 if breakout_up else 0; bear += 2 if breakout_dn else 0
    bull += 1 if retest_up else 0; bear += 1 if retest_dn else 0
    bull += 1 if price>closes[-8] else 0; bear += 1 if price<closes[-8] else 0
    total=10.0
    site_score=round(max(bull,bear)/total*100,1)
    side="BUY" if bull>bear and bull>=5.5 else "SELL" if bear>bull and bear>=5.5 else "WAIT"
    risk=max(price*0.012,abs(price-(support if side=="BUY" else resistance))*0.75 if side!="WAIT" else price*0.012)
    if side=="BUY":sl=price-risk;tp1=price+risk;tp2=price+risk*2;tp3=price+risk*3
    elif side=="SELL":sl=price+risk;tp1=price-risk;tp2=price-risk*2;tp3=price-risk*3
    else:sl=tp1=tp2=tp3=price
    return {"side":side,"price":price,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"site_score":site_score,"trend":"صاعد" if bull>bear else "هابط" if bear>bull else "عرضي","rsi":round(rsi,1),"volume_ratio":round(vr,2),"support":support,"resistance":resistance,"methods":{"trend":round((1 if price>ema20 else 0 if price==ema20 else -1),2),"ema":round((1 if ema20 and ema50 and ema20>ema50 else -1 if ema20 and ema50 and ema20<ema50 else 0),2),"momentum":round((rsi-50)/50,2),"volume":round(min(vr/2,1),2),"candles":1 if bullish_candle else -1 if bearish_candle else 0,"breakout":1 if breakout_up else -1 if breakout_dn else 0,"retest":1 if retest_up else -1 if retest_dn else 0,"price_action":1 if price>closes[-8] else -1 if price<closes[-8] else 0}}

def _symbols_for_market(market,internet):
    if market in ("spot","futures"):
        uni=_crypto_universe(market)
        # Always include internet-mentioned symbols, then highest-volume symbols.
        s=[x[0] for x in uni[:80]]
        for r in internet:
            if r["symbol"].endswith("USDT") and r["symbol"] not in s:s.append(r["symbol"])
        return s[:100]
    return list(dict.fromkeys([r["symbol"] for r in internet]))[:50]

def _analyze_symbol(symbol,market):
    c=_candles(_crypto_klines(symbol,market)) if market in ("spot","futures") else _yahoo(symbol,market)
    return _technical(c) if c else None

def discover(market):
    now=time.time(); key="discover:"+market
    cached=CACHE.get(key)
    if cached and now-cached[0]<DISCOVER_TTL:return list(cached[1])
    internet=_internet(market)
    # Internet recommendations are a separate 50% vote, never the source of prices or levels.
    votes={}
    for r in internet:
        k=r["symbol"]; votes.setdefault(k,[]).append(r["direction"])
    symbols=_symbols_for_market(market,internet)
    results=[]
    def work(s):
        try:return s,_analyze_symbol(s,market)
        except Exception:return s,None
    with ThreadPoolExecutor(max_workers=8) as p:
        fs=[p.submit(work,s) for s in symbols]
        for f in as_completed(fs):
            s,a=f.result()
            if not a or a["side"]=="WAIT":continue
            v=votes.get(s,[])
            b=sum(x=="BUY" for x in v); se=sum(x=="SELL" for x in v)
            web_side="BUY" if b>se else "SELL" if se>b else "WAIT"
            web_score=round(max(b,se)/max(1,len(v))*100,1) if v else 50.0
            # Exactly 50% site analysis + 50% internet recommendations.
            # With no internet evidence the web half is neutral, not a fabricated vote.
            agreement=100.0 if web_side==a["side"] and web_side!="WAIT" else 0.0 if web_side in ("BUY","SELL") else 50.0
            combined=round(a["site_score"]*0.50+agreement*0.50,1)
            if combined<65:continue
            r={**a,"symbol":s,"market":market,"direction":a["side"],"side":a["side"],"timeframe":"15m","ai_pct":combined,"site_score":a["site_score"],"internet_score":agreement,"internet_sources":len(v),"internet_direction":web_side,"research_sources":len(v),"source_count":len(v),"research_agreement":agreement,"external_agreement":agreement,"recommendation_score":combined,"decision":a["side"],"research_mode":True,"research_only":False,"price_fresh":True,"price_source":"Binance 15m" if market in ("spot","futures") else "Yahoo 15m","reason":"50% تحليل الموقع + 50% توصيات الإنترنت"}
            if v:r["source_titles"]=[x["source_title"] for x in internet if x["symbol"]==s][:5]
            results.append(r)
    results.sort(key=lambda x:(x["ai_pct"],x["internet_sources"],x["site_score"]),reverse=True)
    CACHE[key]=(now,results[:50])
    print("[HYBRID]",market,"symbols",len(symbols),"internet",len(internet),"signals",len(results),flush=True)
    return results[:50]

def decide(rows):
    groups={}
    for r in rows:groups.setdefault((r.get("market"),r.get("symbol")),[]).append(r)
    out=[]
    for _,items in groups.items():
        best=max(items,key=lambda x:float(x.get("ai_pct") or 0))
        out.append(dict(best))
    return sorted(out,key=lambda x:float(x.get("ai_pct") or 0),reverse=True)
