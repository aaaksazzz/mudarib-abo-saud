import time, threading, requests, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BINANCE="https://api.binance.com"
FUTURES="https://fapi.binance.com"
YAHOO="https://query1.finance.yahoo.com"
MARKETS={
 "spot":{"name":"Binance Spot","kind":"crypto","base":BINANCE,"endpoint":"/api/v3"},
 "futures":{"name":"Binance Futures","kind":"futures","base":FUTURES,"endpoint":"/fapi/v1"},
 "us_stocks":{"name":"الأسهم الأمريكية","kind":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","AVGO","NFLX","PLTR","JPM","LLY","WMT","COST","ORCL","CRM","UBER","COIN","MSTR"]},
 "us_options":{"name":"عقود الخيارات الأمريكية","kind":"options","symbols":["SPY","QQQ","IWM","AAPL","NVDA","TSLA","AMD","MSFT"]},
 "saudi":{"name":"السوق السعودي","kind":"yahoo","symbols":["2222.SR","1120.SR","1180.SR","2010.SR","2082.SR","7010.SR","1211.SR","1150.SR","1010.SR","1050.SR","1060.SR","1080.SR","2280.SR","4190.SR","4001.SR","4002.SR","4003.SR","4004.SR","4005.SR","4007.SR"]},
 "forex":{"name":"الفوركس والذهب","kind":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F"]}
}
PERIOD={"15m":"60d","1h":"730d","4h":"6mo","1d":"2y","1w":"5y"}
INTERVAL={"15m":"15m","1h":"60m","4h":"60m","1d":"1d","1w":"1wk"}

class MarketEngine:
 def __init__(self):
  self.cache={}; self.lock=threading.RLock()
  self.headers={"User-Agent":"Mozilla/5.0 SMART-TRADING-PRO/2.1"}
 def get(self,url,params=None):
  r=requests.get(url,params=params,headers=self.headers,timeout=12); r.raise_for_status(); return r.json()
 def _cached(self,key,ttl,loader):
  now=time.time()
  with self.lock:
   item=self.cache.get(key)
   if item and now-item[0]<ttl: return item[1]
  value=loader()
  with self.lock: self.cache[key]=(now,value)
  return value
 def _binance_symbols(self,market):
  cfg=MARKETS[market]; base=cfg["base"]; ep=cfg["endpoint"]
  def load():
   info=self.get(base+ep+"/exchangeInfo"); ticks=self.get(base+ep+"/ticker/24hr")
   by={x["symbol"]:x for x in ticks}; out=[]
   excluded={"USDC","USDT","BUSD","FDUSD","TUSD","DAI","USDP","USDE","UST"}
   for s in info.get("symbols",[]):
    if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT": continue
    if s.get("baseAsset","").upper() in excluded: continue
    t=by.get(s["symbol"],{}); vol=float(t.get("quoteVolume",0) or 0)
    if vol>=1_000_000:
     out.append({"symbol":s["symbol"],"volume":vol,"price":float(t.get("lastPrice",0) or 0),"change":float(t.get("priceChangePercent",0) or 0)})
   return sorted(out,key=lambda x:x["volume"],reverse=True)
  return self._cached(("universe",market),120,load)
 def _yahoo_chart(self,symbol,tf):
  interval=INTERVAL[tf]; period=PERIOD[tf]
  data=self.get(f"{YAHOO}/v8/finance/chart/{symbol}",{"range":period,"interval":interval})
  chart=data.get("chart",{}); result=(chart.get("result") or [None])[0]
  if not result: raise ValueError("No chart data")
  q=result["indicators"]["quote"][0]; stamps=result.get("timestamp",[]); candles=[]
  for i,ts in enumerate(stamps):
   vals=[q.get(k,[None]*len(stamps))[i] for k in ("open","high","low","close","volume")]
   if vals[3] is not None and vals[0] is not None:
    candles.append({"t":ts,"o":float(vals[0]),"h":float(vals[1]),"l":float(vals[2]),"c":float(vals[3]),"v":float(vals[4] or 0)})
  if tf=="4h":
   # Aggregate sequential hourly candles; require complete 4-candle buckets.
   grouped=[]
   for i in range(0,len(candles)-3,4):
    chunk=candles[i:i+4]
    if len(chunk)==4:
     grouped.append({"t":chunk[0]["t"],"o":chunk[0]["o"],"h":max(x["h"] for x in chunk),"l":min(x["l"] for x in chunk),"c":chunk[-1]["c"],"v":sum(x["v"] for x in chunk)})
   candles=grouped
  return candles
 def _candles(self,market,symbol,tf):
  key=("candles",market,symbol,tf)
  def load():
   cfg=MARKETS[market]
   if cfg["kind"] in ("crypto","futures"):
    interval={"15m":"15m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}[tf]
    data=self.get(cfg["base"]+cfg["endpoint"]+"/klines",{"symbol":symbol,"interval":interval,"limit":300})
    return [{"t":int(x[0]/1000),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data]
   return self._yahoo_chart(symbol,tf)
  return self._cached(key,45 if tf=="15m" else 240,load)
 def _trend(self,c):
  # Need enough closed bars for the 200-period moving average.
  if len(c)<202: return "غير متاح"
  closed=c[:-1]; closes=[x["c"] for x in closed]
  if len(closes)<201: return "غير متاح"
  ma=sum(closes[-200:])/200; last=closes[-1]; prev=closes[-2]
  if last>ma and last>prev: return "صاعد"
  if last<ma and last<prev: return "هابط"
  return "محايد"
 def _signal(self,market,symbol,direction):
  c=self._candles(market,symbol,"15m")
  if len(c)<202: return None
  closed=c[:-1]; closes=[x["c"] for x in closed]; ma=sum(closes[-200:])/200; last=closed[-1]
  side="شراء" if direction=="صاعد" else "بيع"
  if side=="شراء" and not(last["c"]>ma and last["c"]>last["o"]): return None
  if side=="بيع" and not(last["c"]<ma and last["c"]<last["o"]): return None
  risk=max(abs(last["c"]-last["l"] if side=="شراء" else last["h"]-last["c"]),last["c"]*0.006)
  stop=last["c"]-risk if side=="شراء" else last["c"]+risk
  target=last["c"]+risk*3 if side=="شراء" else last["c"]-risk*3
  return {"symbol":symbol,"side":side,"entry":round(last["c"],8),"stop":round(stop,8),"target":round(target,8),"rr":"1:3","weekly":direction,"daily":direction,"h4":direction,"timeframe":"15m","closed_candle":True,"updated":datetime.now(timezone.utc).isoformat()}
 def _analyze(self,market,item):
  symbol=item["symbol"]
  try:
   w=self._trend(self._candles(market,symbol,"1w"))
   d=self._trend(self._candles(market,symbol,"1d"))
   h=self._trend(self._candles(market,symbol,"4h"))
   signal=self._signal(market,symbol,w) if w==d==h and w in ("صاعد","هابط") else None
   return {"symbol":symbol,"weekly":w,"daily":d,"h4":h,"signal":signal}
  except Exception as e:
   return {"symbol":symbol,"weekly":"غير متاح","daily":"غير متاح","h4":"غير متاح","signal":None}
 def scan(self,market,timeframe="15m"):
  if market not in MARKETS: raise ValueError("السوق غير معروف")
  key=("scan",market,"15m")
  with self.lock:
   old=self.cache.get(key)
   if old and time.time()-old[0]<90: return old[1]
  cfg=MARKETS[market]
  if cfg["kind"] in ("crypto","futures"): universe=self._binance_symbols(market)
  else: universe=[{"symbol":s,"volume":None,"price":None,"change":None} for s in cfg["symbols"]]
  results=[]
  with ThreadPoolExecutor(max_workers=16) as pool:
   futures=[pool.submit(self._analyze,market,x) for x in universe]
   for f in as_completed(futures): results.append(f.result())
  counts={}
  for tf,keyname in (("الأسبوعي","weekly"),("اليومي","daily"),("4 ساعات","h4")):
   counts[tf]={d:sum(x[keyname]==d for x in results) for d in ("صاعد","هابط","محايد","غير متاح")}
  signals=[x["signal"] for x in results if x["signal"]]
  signals.sort(key=lambda x:(x["weekly"]==x["daily"]==x["h4"]),reverse=True)
  payload={"market":market,"name":cfg["name"],"timeframe":"15m","universe":len(universe),"counts":counts,"signals":signals,"analyzed":len(results),"updated":datetime.now(timezone.utc).isoformat(),"method":"weekly → daily → 4h → 15m","note":"تُستخدم الشموع المغلقة فقط. قوائم الأسهم غير المشمولة بمصدر شامل تظهر كتغطية جزئية؛ لا تُفسر على أنها كامل السوق."}
  with self.lock: self.cache[key]=(time.time(),payload)
  return payload
 def market_overview(self):
  return {"markets":[{"id":k,"name":v["name"],"type":v["kind"]} for k,v in MARKETS.items()],"direction_method":"weekly → daily → 4h → 15m"}
 def news(self):
  feeds=["https://www.cnbc.com/id/100003114/device/rss/rss.html","https://feeds.bbci.co.uk/news/business/rss.xml"]
  items=[]
  for url in feeds:
   try:
    root=ET.fromstring(requests.get(url,headers=self.headers,timeout=8).text)
    for item in root.findall(".//item")[:15]:
     items.append({"title":item.findtext("title"),"url":item.findtext("link"),"published":item.findtext("pubDate"),"source":url.split("/")[2]})
   except Exception: continue
  return {"items":items,"note":"الأخبار المعروضة بعناوينها ومصادرها وتواريخها؛ لا يُنسب لها أثر سعري آلي قبل تحليل المحتوى."}
