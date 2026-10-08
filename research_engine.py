import re, time, html, urllib.parse, urllib.request, xml.etree.ElementTree as ET, json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_AGE=24*3600
DISCOVER_CACHE={}
DISCOVER_TTL=6*3600
FETCH_TIMEOUT=3.5
UA="SMART-TRADING-PRO/3.1 external-feed"
MIN_CRYPTO_QUOTE_VOLUME=1_000_000.0
MIN_STOCK_VOLUME=1_000_000.0
VOLUME_TTL=300.0
VOLUME_CACHE={"crypto":(0.0,set()),"stocks":(0.0,set())}

# Broad external discovery. These are search routes, not falsely counted as independent providers.
MARKET_QUERIES={
 "spot":[
  '"crypto signal" BUY entry target stop loss','"crypto signal" SELL entry target stop loss',
  '"BTC" OR "ETH" BUY entry target stop loss','"SOL" OR "XRP" BUY entry target stop loss',
  '"BNB" OR "DOGE" BUY entry target stop loss','"crypto" "trade signal" entry target stop',
  '"altcoin" signal BUY entry target stop','"altcoin" signal SELL entry target stop',
  '"Binance" signal BUY entry target stop','"Binance" signal SELL entry target stop',
  '"USDT" crypto signal entry take profit stop loss','crypto trade signal entry take profit stop loss',
  'cryptocurrency trading signal entry target stop loss','crypto setup BUY entry TP SL',
  'crypto setup SELL entry TP SL','coin signal entry target stop loss',
  '"BTCUSDT" signal entry target stop','"ETHUSDT" signal entry target stop',
  '"SOLUSDT" signal entry target stop','"XRPUSDT" signal entry target stop'
 ],
 "futures":[
  '"crypto futures" LONG entry target stop','"crypto futures" SHORT entry target stop',
  '"BTC futures" LONG entry target stop','"BTC futures" SHORT entry target stop',
  '"ETH futures" LONG entry target stop','"ETH futures" SHORT entry target stop',
  'futures crypto signal entry take profit stop','Binance futures signal LONG entry target stop',
  'Binance futures signal SHORT entry target stop','crypto perpetual signal entry target stop',
  'futures trading signal entry TP SL','perpetual futures trade signal entry target stop'
 ],
 "us":[
  '"US stocks" BUY entry target stop loss','"US stocks" SELL entry target stop loss',
  '"NASDAQ" signal BUY entry target stop','"NASDAQ" signal SELL entry target stop',
  '"NYSE" signal BUY entry target stop','"NYSE" signal SELL entry target stop',
  'US stock trade signal entry target stop loss','stock trading signal BUY entry TP SL',
  'stock trading signal SELL entry TP SL','NYSE trade idea entry target stop',
  'NASDAQ trade idea entry target stop','US equity signal entry target stop',
  'US stocks trade setup BUY entry target stop','US stocks trade setup SELL entry target stop',
  'Wall Street stock signal entry target stop','American stock signal entry target stop',
  'large cap stock BUY signal entry target stop','large cap stock SELL signal entry target stop'
 ],
 "saudi":[
  '"TASI" buy entry target stop loss','"TASI" sell entry target stop loss',
  '"Saudi stocks" BUY entry target stop','"Saudi stocks" SELL entry target stop',
  '"السوق السعودي" توصية شراء بيع دخول هدف وقف','"تاسي" شراء بيع دخول هدف وقف',
  '"Saudi stock" trade signal entry target stop','Saudi shares BUY entry target stop',
  'Saudi shares SELL entry target stop','Tadawul trade idea entry target stop'
 ],
 "contracts":[
  '"gold" OR "XAUUSD" BUY entry target stop loss','"gold" OR "XAUUSD" SELL entry target stop loss',
  '"oil" OR "WTI" BUY entry target stop loss','"oil" OR "WTI" SELL entry target stop loss',
  'gold trade signal entry target stop','oil trade signal entry target stop',
  'silver trade signal entry target stop','indices trade signal entry target stop'
 ],
 "forex":[
  '"forex signal" BUY entry target stop loss','"forex signal" SELL entry target stop loss',
  '"EURUSD" signal entry target stop','"GBPUSD" signal entry target stop',
  '"USDJPY" signal entry target stop','"AUDUSD" signal entry target stop',
  '"USDCAD" signal entry target stop','"USDCHF" signal entry target stop',
  'forex trade signal entry take profit stop loss','forex setup BUY entry TP SL',
  'forex setup SELL entry TP SL'
 ]
}

def _fetch(url,timeout=FETCH_TIMEOUT):
 req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/rss+xml,text/xml,application/json,*/*"})
 with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()

def _news(q):
 url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
 try:root=ET.fromstring(_fetch(url))
 except Exception:return []
 out=[]
 for item in root.findall(".//item"):
  title=item.findtext("title") or ""
  desc=item.findtext("description") or ""
  out.append({"title":html.unescape(title),"text":html.unescape(re.sub("<[^>]+>"," ",desc)),"url":item.findtext("link") or "","published":item.findtext("pubDate") or ""})
 return out[:10]

def _num(s):
 try:return float(str(s).replace(",","").strip())
 except:return None

def _extract(text):
 t=text.replace(","," ")
 buy=list(re.finditer(r"\b(BUY|LONG|BULLISH|شراء|صعود|صاعد|ارتفاع)\b",t,re.I))
 sell=list(re.finditer(r"\b(SELL|SHORT|BEARISH|بيع|هبوط|هابط|انخفاض)\b",t,re.I))
 if buy and sell:return None,None,[],None
 direction="BUY" if buy else ("SELL" if sell else None)
 if not direction:return None,None,[],None
 m=re.search(r"(?i)\b(?:entry(?:\s+price)?|entry\s+zone|دخول|سعر\s+الدخول)\s*[:=@-]?\s*(\d+(?:\.\d+)?)",t)
 entry=_num(m.group(1)) if m else None
 targets=[_num(m.group(1)) for m in re.finditer(r"(?i)\b(?:take[- ]?profit|target|tp\s*\d*|هدف(?:\s*\d+)?)\s*[:#=@-]?\s*(\d+(?:\.\d+)?)",t)]
 targets=[x for x in targets if x is not None]
 m=re.search(r"(?i)\b(?:stop[- ]?loss|stop\s+loss|sl|وقف(?:\s+الخسارة)?)\s*[:#=@-]?\s*(\d+(?:\.\d+)?)",t)
 sl=_num(m.group(1)) if m else None
 return direction,entry,targets,sl

def _symbol(text,market):
 t=text.upper()
 if market in ("spot","futures"):
  m=re.search(r"\b([A-Z0-9]{2,15})\s*(?:/|-)\s*USDT\b",t)
  if m:return m.group(1)+"USDT"
  m=re.search(r"\b([A-Z0-9]{2,15})USDT\b",t)
  return (m.group(1)+"USDT") if m else None
 if market=="us":
  blocked={"BUY","SELL","LONG","SHORT","BULL","BEAR","SIGNAL","STOCK","NASDAQ","NYSE","ENTRY","TARGET","STOP","LOSS","TRADE","SETUP"}
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
 now=time.time()
 at,syms=VOLUME_CACHE["crypto"]
 if now-at<VOLUME_TTL:return syms
 urls=[
  "https://api.binance.com/api/v3/ticker/24hr",
  "https://api-gcp.binance.com/api/v3/ticker/24hr",
  "https://data-api.binance.vision/api/v3/ticker/24hr"
 ]
 data=None
 for url in urls:
  try:data=json.loads(_fetch(url,timeout=2.5));break
  except Exception:continue
 if not isinstance(data,list):
  return syms
 result={str(x.get("symbol","")).upper() for x in data
         if str(x.get("symbol","")).upper().endswith("USDT")
         and float(x.get("quoteVolume") or 0)>=MIN_CRYPTO_QUOTE_VOLUME}
 VOLUME_CACHE["crypto"]=(now,result)
 return result

def _stock_symbols_over_volume(symbols):
 # Volume is a market-universe filter only; recommendation values remain external.
 now=time.time()
 at,known=VOLUME_CACHE["stocks"]
 if now-at<VOLUME_TTL:
  return symbols & known
 if not symbols:
  return set()
 def check(sym):
  try:
   url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(sym)+"?range=1d&interval=1d"
   data=json.loads(_fetch(url,timeout=1.2))
   result=data.get("chart",{}).get("result") or []
   vol=((result[0].get("indicators",{}).get("quote") or [{}])[0].get("volume") or []) if result else []
   return sym if vol and float(vol[-1] or 0)>=MIN_STOCK_VOLUME else None
  except Exception:
   return None
 with ThreadPoolExecutor(max_workers=min(16,len(symbols))) as pool:
  checked=pool.map(check,symbols)
 good={x for x in checked if x}
 VOLUME_CACHE["stocks"]=(now,good)
 return symbols & good

def _complete_external_trade(hit,market):
 direction,entry,tps,sl=_extract(hit["title"]+" "+hit["text"])
 if not direction or entry is None or not tps or sl is None:return None
 return direction,entry,tps[:3],sl,"صفقة خارجية مكتملة"

def discover(market):
 now=time.time()
 cached=DISCOVER_CACHE.get(market)
 if cached and now-cached[0]<DISCOVER_TTL:return list(cached[1])
 rows=[]
 queries=MARKET_QUERIES.get(market,[])
 crypto_allowed=_crypto_symbols_over_volume() if market in ("spot","futures") else None
 with ThreadPoolExecutor(max_workers=min(24,max(1,len(queries)))) as pool:
  futures=[pool.submit(_news,q) for q in queries]
  for fut in as_completed(futures):
   try:hits=fut.result()
   except Exception:hits=[]
   for hit in hits:
    if not _fresh(hit.get("published")):continue
    text=hit.get("title","")+" "+hit.get("text","")
    sym=_symbol(text,market)
    if not sym:continue
    if market in ("spot","futures") and sym not in crypto_allowed:continue
    parsed=_complete_external_trade(hit,market)
    if not parsed:continue
    direction,entry,tps,sl,reason=parsed
    rows.append({"market":market,"symbol":sym,"direction":direction,"entry":entry,"targets":tps[:3],
                 "tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,"tp3":tps[2] if len(tps)>2 else None,
                 "sl":sl,"source":hit.get("url"),"source_title":hit.get("title"),
                 "source_published":hit.get("published"),"research_mode":True,"research_only":True,
                 "volume_filter":">=1M quote volume","reason":reason})
 # US stock volume filter after symbols are discovered, so no internal recommendation is created.
 if market=="us":
  allowed=_stock_symbols_over_volume({r["symbol"] for r in rows})
  rows=[r for r in rows if r["symbol"] in allowed]
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
  buys=sum(x["direction"]=="BUY" for x in items); sells=sum(x["direction"]=="SELL" for x in items)
  direction="BUY" if buys>sells else ("SELL" if sells>buys else None)
  if not direction:continue
  chosen=[x for x in items if x["direction"]==direction]
  best=dict(chosen[0])
  best["research_sources"]=len({x.get("source") for x in chosen if x.get("source")})
  best["research_agreement"]=round(max(buys,sells)/max(1,len(items))*100)
  best["decision"]=direction
  best["recommendation_score"]=round(50+best["research_agreement"]*.35+min(best["research_sources"],5)*5,1)
  best["source_count"]=best["research_sources"]
  best["external_agreement"]=best["research_agreement"]
  out.append(best)
 return sorted(out,key=lambda x:x.get("recommendation_score",0),reverse=True)
