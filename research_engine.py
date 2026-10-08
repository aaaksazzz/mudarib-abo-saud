import re, time, html, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_AGE=24*3600
DISCOVER_CACHE={}
DISCOVER_TTL=6*3600
FETCH_TIMEOUT=3.5
UA="SMART-TRADING-PRO/3.0 fast-external-feed"

MARKET_QUERIES={
 "spot":['"crypto signal" BUY entry target stop loss','"BTC" OR "ETH" BUY entry target stop loss','crypto trade signal entry take profit stop loss'],
 "futures":['"crypto futures" LONG SHORT entry target stop','"BTC futures" signal entry target stop loss','crypto futures trade signal entry take profit stop'],
 "us":['"US stocks" BUY entry target stop loss','"NASDAQ" OR "NYSE" signal entry target stop','US stock trade signal entry target stop loss'],
 "saudi":['"TASI" buy entry target stop loss','"Saudi stocks" signal buy sell entry target stop','"السوق السعودي" توصية شراء بيع دخول هدف وقف'],
 "contracts":['"gold" OR "XAUUSD" signal entry target stop loss','"oil" OR "WTI" signal entry target stop loss','gold oil trade signal entry target stop'],
 "forex":['"forex signal" buy sell entry target stop loss','"EURUSD" OR "GBPUSD" OR "USDJPY" signal entry target stop','forex trade signal entry take profit stop loss']
}

def _fetch(url,timeout=FETCH_TIMEOUT):
 req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/rss+xml,text/xml,*/*"})
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
  blocked={"BUY","SELL","LONG","SHORT","BULL","BEAR","SIGNAL","STOCK","NASDAQ","NYSE","ENTRY","TARGET","STOP"}
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
 with ThreadPoolExecutor(max_workers=max(1,len(queries))) as pool:
  futures=[pool.submit(_news,q) for q in queries]
  for fut in as_completed(futures):
   try:hits=fut.result()
   except Exception:hits=[]
   for hit in hits:
    if not _fresh(hit.get("published")):continue
    sym=_symbol(hit.get("title","")+" "+hit.get("text",""),market)
    if not sym:continue
    parsed=_complete_external_trade(hit,market)
    if not parsed:continue
    direction,entry,tps,sl,reason=parsed
    rows.append({"market":market,"symbol":sym,"direction":direction,"entry":entry,"targets":tps[:3],"tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,"tp3":tps[2] if len(tps)>2 else None,"sl":sl,"source":hit.get("url"),"source_title":hit.get("title"),"source_published":hit.get("published"),"research_mode":True,"research_only":True,"reason":reason})
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
  best["source_count"]=best["research_sources"]; best["external_agreement"]=best["research_agreement"]
  out.append(best)
 return sorted(out,key=lambda x:x.get("recommendation_score",0),reverse=True)
