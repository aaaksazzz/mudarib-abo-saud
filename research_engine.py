import re, time, html, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone

MAX_AGE=24*3600
DISCOVER_CACHE={}
DISCOVER_TTL=300
UA="SMART-TRADING-PRO/2.1 external-research"

MARKET_QUERIES={
 "spot":[
  '"crypto signal" BUY SELL entry stop loss take profit',
  '"BTC" OR "ETH" BUY SELL entry stop loss take profit',
  'crypto signal entry target stop loss'
 ],
 "futures":[
  '"crypto futures" signal long short entry stop target',
  '"BTC futures" buy sell entry stop loss take profit',
  'crypto futures signal entry target stop loss'
 ],
 "us":[
  '"US stocks" BUY SELL entry target stop loss signal',
  '"NASDAQ" OR "NYSE" buy sell entry stop target',
  'US stocks signal entry target stop loss'
 ],
 "saudi":[
  '"TASI" buy sell entry target stop loss',
  '"Saudi stocks" signal buy sell entry target stop loss',
  '"السوق السعودي" توصية شراء بيع دخول هدف وقف',
  'Saudi stocks signal entry target stop loss'
 ],
 "contracts":[
  '"gold" OR "XAUUSD" signal entry take profit stop loss',
  '"oil" OR "WTI" signal entry target stop loss',
  'gold oil signal entry target stop loss'
 ],
 "forex":[
  '"forex signal" buy sell entry take profit stop loss',
  '"EURUSD" OR "GBPUSD" OR "USDJPY" signal entry stop loss target',
  'forex signal entry target stop loss'
 ]
}

class TextParser(HTMLParser):
 def __init__(self):
  super().__init__(); self.parts=[]
 def handle_data(self,d): self.parts.append(d)
 def text(self): return " ".join(self.parts)

def _fetch(url,timeout=7):
 req=urllib.request.Request(url,headers={"User-Agent":UA})
 with urllib.request.urlopen(req,timeout=timeout) as r:
  return r.read()

def _news(q):
 url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"})
 try:
  root=ET.fromstring(_fetch(url))
 except Exception:
  return []
 out=[]
 for item in root.findall(".//item"):
  title=item.findtext("title") or ""
  desc=item.findtext("description") or ""
  link=item.findtext("link") or ""
  pub=item.findtext("pubDate") or ""
  out.append({"title":html.unescape(title),"text":html.unescape(re.sub("<[^>]+>"," ",desc)),"url":link,"published":pub})
 return out[:12]

def _page(url):
 try:
  raw=_fetch(url,6)
  p=TextParser(); p.feed(raw.decode("utf-8","ignore"))
  return re.sub(r"\s+"," ",p.text())[:18000]
 except Exception: return ""

def _num(s):
 try:return float(str(s).replace(",","").strip())
 except:return None

def _numbers_near(text, keywords):
 out=[]
 for kw in keywords:
  for m in re.finditer(kw, text, re.I):
   chunk=text[max(0,m.start()-140):m.end()+260].replace(",","")
   for n in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])",chunk):
    v=_num(n)
    if v is not None and v>0: out.append(v)
 return out

def _extract(text):
 t=text.replace(",","")
 direction=None
 buy=list(re.finditer(r"\b(BUY|LONG|BULLISH|شراء|صعود|صاعد|ارتفاع)\b",t,re.I))
 sell=list(re.finditer(r"\b(SELL|SHORT|BEARISH|بيع|هبوط|هابط|انخفاض)\b",t,re.I))
 if buy and sell:
  # A source mentioning both directions is ambiguous; do not invent a side.
  return None,None,[],None
 if buy: direction="BUY"
 elif sell: direction="SELL"
 m=re.search(r"(?i)(?:entry|entry price|دخول|سعر الدخول)\s*[:=@-]?\s*(\d+(?:\.\d+)?)",t)
 entry=_num(m.group(1)) if m else None
 if entry is None:
  m=re.search(r"(?i)(?:entry|دخول)\s*(?:zone|range)?\s*[:=@-]?\s*(\d+(?:\.\d+)?)",t)
  entry=_num(m.group(1)) if m else None
 mtps=re.findall(r"(?i)(?:take[- ]?profit|target|tp\s*\d*|هدف)\s*[:#=@-]?\s*(\d+(?:\.\d+)?)",t)
 tsl=re.search(r"(?i)(?:stop[- ]?loss|stop loss|sl|وقف(?:\s+الخسارة)?)\s*[:#=@-]?\s*(\d+(?:\.\d+)?)",t)
 targets=[_num(x) for x in mtps if _num(x) is not None]
 sl=_num(tsl.group(1)) if tsl else None
 return direction,entry,targets,sl

def _symbol(text,market):
 t=text.upper()
 if market in ("spot","futures"):
  m=re.search(r"\b([A-Z0-9]{2,15})(?:USDT|/USDT)\b",t)
  return (m.group(1)+"USDT") if m else None
 if market=="us":
  blocked={"BUY","SELL","LONG","SHORT","BULL","BEAR","SIGNAL","STOCK","NASDAQ","NYSE","THE","AND","FOR","WITH","FROM","THIS","THAT"}
  for pat in (r"\$([A-Z]{1,5})\b",r"\b(?:NASDAQ|NYSE)[:\s]+([A-Z]{1,5})\b"):
   m=re.search(pat,t)
   if m and m.group(1) not in blocked:return m.group(1)
  for m in re.finditer(r"\b([A-Z]{2,5})\b",t):
   if m.group(1) not in blocked:return m.group(1)
  return None
 patterns={
  "saudi":r"\b(\d{4})\b",
  "contracts":r"\b(XAUUSD|GOLD|WTI|USOIL|SPX|NDX|NAS100|US30)\b",
  "forex":r"\b([A-Z]{3}/?[A-Z]{3})\b"
 }
 m=re.search(patterns.get(market,r"\b[A-Z]{2,10}\b"),t)
 if not m:return None
 return m.group(1).upper()

def _fresh(pub):
 if not pub:return False
 try:
  from email.utils import parsedate_to_datetime
  dt=parsedate_to_datetime(pub)
  if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
  return (datetime.now(timezone.utc)-dt).total_seconds()<=MAX_AGE
 except Exception:
  return False

def _complete_external_trade(hit,market):
 blob=hit["title"]+" "+hit["text"]
 direction,entry,tps,sl=_extract(blob)
 # External source must publish the complete trade itself.
 # Never derive entry, targets, stop, or timeframe inside this app.
 if not direction or entry is None or not tps or sl is None:
  return None
 return direction,entry,tps[:3],sl,"صفقة خارجية مكتملة"

def discover(market):
 now=time.time()
 cached=DISCOVER_CACHE.get(market)
 if cached and now-cached[0]<DISCOVER_TTL:return list(cached[1])
 rows=[]
 for q in MARKET_QUERIES.get(market,[]):
  for hit in _news(q):
   if not _fresh(hit["published"]):continue
   sym=_symbol(hit["title"]+" "+hit["text"],market)
   if not sym:continue
   parsed=_complete_external_trade(hit,market)
   if not parsed:continue
   direction,entry,tps,sl,reason=parsed
   rows.append({
    "market":market,"symbol":sym,"direction":direction,"entry":entry,
    "targets":tps[:3],"tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,
    "tp3":tps[2] if len(tps)>2 else None,"sl":sl,
    "source":hit["url"],"source_title":hit["title"],
    "source_published":hit["published"],"research_mode":True,
    "research_only":True,"reason":reason
   })
 seen=set(); clean=[]
 for r in rows:
  k=(r["symbol"],r["direction"],r["source"])
  if k in seen:continue
  seen.add(k);clean.append(r)
 DISCOVER_CACHE[market]=(now,list(clean))
 return clean

def decide(rows):
 groups={}
 for r in rows:
  groups.setdefault((r["market"],r["symbol"]),[]).append(r)
 out=[]
 for k,items in groups.items():
  buys=sum(1 for x in items if x["direction"]=="BUY")
  sells=sum(1 for x in items if x["direction"]=="SELL")
  direction="BUY" if buys>sells else ("SELL" if sells>buys else None)
  if not direction:continue
  chosen=[x for x in items if x["direction"]==direction]
  best=dict(chosen[0])
  best["direction"]=direction
  best["research_sources"]=len({x.get("source") for x in chosen})
  best["research_agreement"]=round(max(buys,sells)/max(1,len(items))*100)
  best["decision"]=direction
  best["recommendation_score"]=round(50+best["research_agreement"]*.35+min(best["research_sources"],5)*5,1)
  best["source_count"]=best["research_sources"]
  best["external_agreement"]=best["research_agreement"]
  out.append(best)
 return sorted(out,key=lambda x:x.get("recommendation_score",0),reverse=True)
