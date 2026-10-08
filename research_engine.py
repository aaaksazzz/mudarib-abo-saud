import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET,json
from concurrent.futures import ThreadPoolExecutor,as_completed

UA="SMART-TRADING-PRO/6.0 pure-method-hybrid"
DISCOVER_TTL=45.0
FETCH_TIMEOUT=5.0
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
CACHE={}
ACTIVE_SIGNALS={}

MARKET_QUERIES={
 "spot":["crypto trading recommendation BUY SELL","crypto market recommendation today","BTC ETH SOL altcoin recommendation"],
 "futures":["crypto futures recommendation LONG SHORT","Binance futures recommendation","BTC ETH futures long short"],
 "us":["US stock recommendation BUY SELL today","NASDAQ stock recommendation","NYSE stock recommendation"],
 "saudi":["توصية تداول تاسي شراء بيع","السوق السعودي توصيات أسهم اليوم","توصيات تداول السوق السعودي"],
 "contracts":["gold oil index trading recommendation BUY SELL","XAUUSD recommendation","US30 NAS100 SPX recommendation"],
 "forex":["forex recommendation BUY SELL today","EURUSD GBPUSD USDJPY recommendation"]
}

# Liquid baseline universes: external recommendations confirm the setup, but do not decide
# which instruments are eligible for analysis. This prevents empty markets when news has no ticker.
BASE_UNIVERSE={
 "us":["AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","AVGO","AMD","NFLX","JPM","V","MA","COST","WMT","ORCL","CRM","PLTR","INTC","QCOM","MU","AMAT","ADBE","CSCO","IBM","GE","CAT","BA","DIS","UBER","COIN","MSTR","BAC","GS","MS","XOM","CVX","LLY","JNJ","PFE","ABBV","UNH","HD","LOW","TMO","LIN","NKE","PEP","KO"],
 "saudi":["2222","1120","2010","1180","2380","1150","1211","2020","7010","7020","2280","2050","3030","4003","4190","4261","4280","4300","4321","4331"],
 "contracts":["XAUUSD","WTI","SPX","NDX","NAS100","US30","BRENT","SILVER"],
 "forex":["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","EURGBP","EURJPY","GBPJPY","USDSEK","USDNOK"]
}
BINANCE_SPOT="https://api.binance.com"; BINANCE_FUTURES="https://fapi.binance.com"; YAHOO="https://query1.finance.yahoo.com"

def _fetch(url,timeout=FETCH_TIMEOUT):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json,application/rss+xml,text/xml,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()
def _json(url,timeout=FETCH_TIMEOUT): return json.loads(_fetch(url,timeout).decode("utf-8","ignore"))

def _news(q):
    u="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
    try:root=ET.fromstring(_fetch(u))
    except Exception:return []
    return [{"title":html.unescape(x.findtext("title") or ""),"text":html.unescape(re.sub("<[^>]+>"," ",x.findtext("description") or "")),"url":x.findtext("link") or "","published":x.findtext("pubDate") or ""} for x in root.findall(".//item")][:20]

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
        aliases={"APPLE":"AAPL","MICROSOFT":"MSFT","NVIDIA":"NVDA","AMAZON":"AMZN","ALPHABET":"GOOGL","GOOGLE":"GOOGL","META":"META","FACEBOOK":"META","TESLA":"TSLA","BROADCOM":"AVGO","NETFLIX":"NFLX","PALANTIR":"PLTR","COINBASE":"COIN","MICROSTRATEGY":"MSTR","JPMORGAN":"JPM","BANK OF AMERICA":"BAC","WALMART":"WMT","COSTCO":"COST","ORACLE":"ORCL","SALESFORCE":"CRM","INTEL":"INTC","QUALCOMM":"QCOM","DISNEY":"DIS","UBER":"UBER"}
        for name,sym in aliases.items():
            if re.search(r"\b"+re.escape(name)+r"\b",t):return sym
        m=re.search(r"\$([A-Z]{1,5})\b",t) or re.search(r"\b(?:NASDAQ|NYSE|NYSEARCA)[:\s]+([A-Z]{1,5})\b",t)
        return m.group(1) if m and m.group(1) not in {"BUY","SELL","LONG","SHORT","CALL","PUT","STOCK","SIGNAL"} else None
    if market=="saudi":
        m=re.search(r"\b(\d{4})\b",t); return m.group(1) if m else None
    if market=="contracts":
        m=re.search(r"\b(XAUUSD|GOLD|WTI|USOIL|SPX|SP500|NDX|NAS100|US30|DOW)\b",t)
        return {"GOLD":"XAUUSD","WTI":"WTI","USOIL":"WTI","SP500":"SPX","DOW":"US30"}.get(m.group(1),m.group(1)) if m else None
    if market=="forex":
        m=re.search(r"\b([A-Z]{3}\s*/?\s*[A-Z]{3})\b",t); return m.group(1).replace(" ","").replace("/","") if m else None
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
                full=h["title"]+" "+h["text"]+" "+_article(h["url"])
                sym=_symbol(full,market); d=_direction(full)
                if sym and d:rows.append({"symbol":sym,"direction":d,"source_title":h["title"],"source_published":h["published"],"source_url":h["url"],"source_text":full})
    seen=set(); out=[]
    for r in rows:
        k=(r["symbol"],r["direction"],r["source_title"])
        if k not in seen:seen.add(k);out.append(r)
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
        "saudi":symbol+".SR",
        "contracts":{"XAUUSD":"GC=F","WTI":"CL=F","BRENT":"BZ=F","SILVER":"SI=F","SPX":"^GSPC","NDX":"^NDX","NAS100":"NQ=F","US30":"YM=F"}.get(symbol,symbol),
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
    # 1) Market structure: higher-high/higher-low vs lower-high/lower-low.
    rh=[max(highs[i-2:i+3]) for i in range(2,len(c)-2)]
    rl=[min(lows[i-2:i+3]) for i in range(2,len(c)-2)]
    trend="عرضي"; trend_score=0
    if len(rh)>=2 and len(rl)>=2:
        if rh[-1]>rh[-2] and rl[-1]>rl[-2]:trend="صاعد";trend_score=1
        elif rh[-1]<rh[-2] and rl[-1]<rl[-2]:trend="هابط";trend_score=-1

    # 2) Support / resistance from repeated swing areas.
    support=min(lows[-30:]); resistance=max(highs[-30:])
    span=max(resistance-support,price*0.0001)
    near_support=abs(price-support)/span<0.18; near_resistance=abs(price-resistance)/span<0.18

    # 3) Price action: last sequence of closes and swing displacement.
    move=price-closes[-8]
    pa=1 if move>0 and trend_score>=0 else -1 if move<0 and trend_score<=0 else 0

    # 4) Candlestick behavior: body/wicks, engulfing, rejection.
    cur=c[-1]; prev=c[-2]; body=abs(cur["close"]-cur["open"]); rng=max(cur["high"]-cur["low"],1e-12)
    upper=cur["high"]-max(cur["open"],cur["close"]); lower=min(cur["open"],cur["close"])-cur["low"]
    bull_candle=cur["close"]>cur["open"] and (body/rng>=.45 or lower>body*2)
    bear_candle=cur["close"]<cur["open"] and (body/rng>=.45 or upper>body*2)
    bull_eng=prev["close"]<prev["open"] and cur["close"]>cur["open"] and cur["close"]>=prev["open"] and cur["open"]<=prev["close"]
    bear_eng=prev["close"]>prev["open"] and cur["close"]<cur["open"] and cur["close"]<=prev["open"] and cur["open"]>=prev["close"]
    candle=1 if bull_candle or bull_eng else -1 if bear_candle or bear_eng else 0

    # 5) Breakout / breakdown using raw closing price vs prior range.
    prior_hi=max(highs[-21:-1]); prior_lo=min(lows[-21:-1])
    breakout=1 if price>prior_hi else -1 if price<prior_lo else 0

    # 6) Retest: price breaks a prior range then returns near the broken level.
    retest=0
    if len(c)>=24:
        level_hi=max(highs[-24:-4]); level_lo=min(lows[-24:-4])
        if max(highs[-4:])>level_hi and abs(price-level_hi)/max(price,1)<.006:retest=1
        if min(lows[-4:])<level_lo and abs(price-level_lo)/max(price,1)<.006:retest=-1

    # 7) Liquidity / equal highs-lows.
    tol=max(price*.002,span*.04)
    equal_hi=abs(highs[-1]-max(highs[-8:-1]))<=tol
    equal_lo=abs(lows[-1]-min(lows[-8:-1]))<=tol
    liquidity=1 if equal_hi and price>=highs[-1] else -1 if equal_lo and price<=lows[-1] else 0

    # 8) Raw volume confirmation — volume itself, not a technical indicator.
    vols=[x["volume"] for x in c]; avg=sum(vols[-21:-1])/max(1,len(vols[-21:-1])); volume_confirm=1 if vols[-1]>avg*1.25 and candle>=0 else -1 if vols[-1]>avg*1.25 and candle<0 else 0

    # 9) Multi-timeframe structure is added by _analyze_symbol.
    # Support/resistance is a full methodology vote: rejection from support favors BUY,
    # rejection from resistance favors SELL; otherwise it stays neutral.
    sr = 1 if near_support and candle >= 0 else -1 if near_resistance and candle <= 0 else 0
    votes=[trend_score,sr,pa,candle,breakout,retest,liquidity,volume_confirm]
    bull=sum(v>0 for v in votes); bear=sum(v<0 for v in votes)
    side="BUY" if bull>bear and bull>=4 else "SELL" if bear>bull and bear>=4 else "WAIT"
    agreement=max(bull,bear)/len(votes)*100
    risk=max(price*0.012,abs(price-(support if side=="BUY" else resistance))*0.55 if side!="WAIT" else price*.012)
    if side=="BUY":sl=price-risk;tp1=price+risk;tp2=price+risk*2;tp3=price+risk*3
    elif side=="SELL":sl=price+risk;tp1=price-risk;tp2=price-risk*2;tp3=price-risk*3
    else:sl=tp1=tp2=tp3=price
    return {"side":side,"price":price,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"targets":[tp1,tp2,tp3],"site_score":round(agreement,1),"trend":trend,"support":support,"resistance":resistance,"methods":{"market_structure":trend_score,"support_resistance":1 if near_support else -1 if near_resistance else 0,"price_action":pa,"candlestick":candle,"breakout":breakout,"retest":retest,"liquidity":liquidity,"raw_volume":volume_confirm}}

def _analyze_symbol(symbol,market):
    def get(interval):
        return _candles(_crypto_klines(symbol,market,interval)) if market in ("spot","futures") else _yahoo(symbol,market,interval)
    c15=get("15m")
    if len(c15)<32 and market not in ("spot","futures"):
        c15=get("30m")
    a=_method_analysis(c15)
    if not a or a["side"]=="WAIT":return None
    # Multi-timeframe confirmation uses price structure only, no indicators.
    mt=[]
    for tf in ("1h","4h"):
        cc=get(tf); m=_method_analysis(cc) if len(cc)>=32 else None
        if m:mt.append(m["side"])
    if mt:
        agree=sum(x==a["side"] for x in mt)
        if agree==0:return None
        a["site_score"]=round((a["site_score"]*.70)+(agree/len(mt)*100*.30),1)
        a["multi_timeframe"]=mt
    a["timeframe"]="15m"; a["price_fresh"]=True
    return a

def _symbols_for_market(market,internet):
    if market in ("spot","futures"):
        s=[x[0] for x in _crypto_universe(market)[:80]]
        for r in internet:
            if r["symbol"].endswith("USDT") and r["symbol"] not in s:s.append(r["symbol"])
        return s[:100]
    base=BASE_UNIVERSE.get(market,[])
    seen=[]
    for s in [r["symbol"] for r in internet]+base:
        if s not in seen: seen.append(s)
    return seen[:60]


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


def discover(market):
    """External recommendations only. No site analysis, no internally calculated levels."""
    now=time.time(); key="external:"+market; cached=CACHE.get(key)
    if cached and now-cached[0]<DISCOVER_TTL:return list(cached[1])
    internet=_internet(market)
    results=[]
    for r in internet:
        full=str(r.get("source_title",""))+" "+str(r.get("source_text",""))+" "+str(r.get("source_url",""))
        entry,targets,sl=_external_trade_fields(full)
        # The external article parser must have explicit published trade levels.
        # Never manufacture Entry/TP/SL from market price.
        if entry is None or not targets or sl is None:
            continue
        direction=r.get("direction")
        results.append({
            "symbol":r.get("symbol"),"market":market,
            "direction":direction,"side":direction,
            "entry":entry,"targets":targets[:3],
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
            "price_source":"external recommendation",
            "reason":"توصية خارجية فقط — بدون تحليل أو حساب داخلي"
        })
    results.sort(key=lambda x:x.get("source_published") or "",reverse=True)
    CACHE[key]=(now,results[:50])
    print("[EXTERNAL-ONLY]",market,"internet",len(internet),"complete_external",len(results),flush=True)
    return results[:50]

def decide(rows):
    groups={}
    for r in rows:groups.setdefault((r.get("market"),r.get("symbol")),[]).append(r)
    return sorted((dict(max(v,key=lambda x:float(x.get("ai_pct") or 0))) for v in groups.values()),key=lambda x:float(x.get("ai_pct") or 0),reverse=True)
