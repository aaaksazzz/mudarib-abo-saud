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
 "us_options":{"name":"العقود الأمريكية","kind":"options","symbols":["SPY","QQQ","IWM","AAPL","NVDA","TSLA","AMD","MSFT"]},
 "saudi":{"name":"السوق السعودي","kind":"yahoo","symbols":["2222.SR","1120.SR","1180.SR","2010.SR","2082.SR","7010.SR","1211.SR","1150.SR","1010.SR","1050.SR","1060.SR","1080.SR","2280.SR","4190.SR","4001.SR","4002.SR","4003.SR","4004.SR","4005.SR","4007.SR"]},
 "forex":{"name":"الفوركس والذهب","kind":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F"]}
}
INTERVAL={"15m":"15m","1h":"60m","4h":"60m","1d":"1d","1w":"1wk"}
PERIOD={"15m":"5d","1h":"1mo","4h":"3mo","1d":"1y","1w":"5y"}
class MarketEngine:
 def __init__(self):
  self.cache={}; self.lock=threading.Lock(); self.session=requests.Session(); self.session.headers.update({"User-Agent":"SMART-TRADING-PRO/2.0"})
 def get(self,url,params=None):
  r=self.session.get(url,params=params,timeout=12); r.raise_for_status(); return r.json()
 def _binance_symbols(self,market):
  cfg=MARKETS[market]; base=cfg["base"]; ep=cfg["endpoint"]
  info=self.get(base+ep+"/exchangeInfo"); ticks=self.get(base+ep+"/ticker/24hr")
  by={x["symbol"]:x for x in ticks}
  out=[]
  for s in info.get("symbols",[]):
   if s.get("status")!="TRADING" or s.get("quoteAsset")!="USDT": continue
   if s.get("baseAsset","").upper() in {"USDC","USDT","BUSD","FDUSD","TUSD","DAI","USDP"}: continue
   t=by.get(s["symbol"],{}); vol=float(t.get("quoteVolume",0) or 0)
   if vol>=1_000_000: out.append({"symbol":s["symbol"],"volume":vol,"price":float(t.get("lastPrice",0) or 0),"change":float(t.get("priceChangePercent",0) or 0)})
  return sorted(out,key=lambda x:x["volume"],reverse=True)[:120]
 def _yahoo_chart(self,symbol,tf):
  period=PERIOD[tf]; interval=INTERVAL[tf]
  if tf=="4h": interval="60m"
  data=self.get(f"{YAHOO}/v8/finance/chart/{symbol}",{"range":period,"interval":interval})
  result=data["chart"]["result"][0]; q=result["indicators"]["quote"][0]
  candles=[]
  for i,ts in enumerate(result.get("timestamp",[])):
   vals=[q.get(k,[None]*len(result["timestamp"]))[i] for k in ("open","high","low","close","volume")]
   if vals[3] is not None: candles.append({"t":ts,"o":vals[0],"h":vals[1],"l":vals[2],"c":vals[3],"v":vals[4]})
  if tf=="4h":
   grouped=[]
   for i in range(0,len(candles)-3,4):
    chunk=candles[i:i+4]
    if len(chunk)==4: grouped.append({"t":chunk[0]["t"],"o":chunk[0]["o"],"h":max(x["h"] for x in chunk),"l":min(x["l"] for x in chunk),"c":chunk[-1]["c"],"v":sum(x["v"] or 0 for x in chunk)})
   candles=grouped
  return candles
 def _candles(self,market,symbol,tf):
  cfg=MARKETS[market]
  if cfg["kind"] in ("crypto","futures"):
   base=cfg["base"]; ep=cfg["endpoint"]
   interval={"15m":"15m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}[tf]
   data=self.get(base+ep+"/klines",{"symbol":symbol,"interval":interval,"limit":240})
   return [{"t":int(x[0]/1000),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data]
  return self._yahoo_chart(symbol,tf)
 def _trend(self,c):
  if len(c)<205: return "غير متاح"
  closes=[x["c"] for x in c]
  # Confirm only completed candles; discard latest forming candle for intraday frames.
  closes=closes[:-1]
  if len(closes)<201: return "غير متاح"
  ma=sum(closes[-200:])/200; last=closes[-1]
  if last>ma and closes[-1]>closes[-2]: return "صاعد"
  if last<ma and closes[-1]<closes[-2]: return "هابط"
  return "محايد"
 def _signal(self,market,symbol,weekly,daily,h4):
  if "غير متاح" in (weekly,daily,h4) or "محايد" in (weekly,daily,h4): return None
  if not (weekly==daily==h4): return None
  c=self._candles(market,symbol,"15m")
  if len(c)<205: return None
  c=c[:-1]; closes=[x["c"] for x in c]; ma=sum(closes[-200:])/200; last=c[-1]
  side="شراء" if weekly=="صاعد" else "بيع"
  if side=="شراء" and not (last["c"]>ma and last["c"]>last["o"]): return None
  if side=="بيع" and not (last["c"]<ma and last["c"]<last["o"]): return None
  risk=abs(last["c"]-last["l"] if side=="شراء" else last["h"]-last["c"])
  risk=max(risk,last["c"]*0.006)
  stop=last["c"]-risk if side=="شراء" else last["c"]+risk
  target=last["c"]+risk*3 if side=="شراء" else last["c"]-risk*3
  return {"symbol":symbol,"side":side,"entry":round(last["c"],8),"stop":round(stop,8),"target":round(target,8),"rr":"1:3","weekly":weekly,"daily":daily,"h4":h4,"timeframe":"15m","closed_candle":True,"updated":datetime.now(timezone.utc).isoformat()}
 def _analyze(self,market,item):
  s=item["symbol"]
  try:
   w=self._trend(self._candles(market,s,"1w")); d=self._trend(self._candles(market,s,"1d")); h=self._trend(self._candles(market,s,"4h"))
   sig=self._signal(market,s,w,d,h)
   return {"symbol":s,"weekly":w,"daily":d,"h4":h,"signal":sig}
  except Exception: return {"symbol":s,"weekly":"غير متاح","daily":"غير متاح","h4":"غير متاح","signal":None}
 def scan(self,market,timeframe="15m"):
  if market not in MARKETS: raise ValueError("السوق غير معروف")
  key=("scan",market,timeframe)
  with self.lock:
   old=self.cache.get(key)
   if old and time.time()-old[0]<180: return old[1]
  cfg=MARKETS[market]
  if cfg["kind"] in ("crypto","futures"): universe=self._binance_symbols(market)
  else: universe=[{"symbol":s,"volume":None,"price":None,"change":None} for s in cfg["symbols"]]
  # Bounded concurrency protects public providers and keeps page loads responsive.
  results=[]
  with ThreadPoolExecutor(max_workers=8) as pool:
   futures=[pool.submit(self._analyze,market,x) for x in universe]
   for f in as_completed(futures): results.append(f.result())
  counts={"صاعد":sum(x["weekly"]=="صاعد" for x in results),"هابط":sum(x["weekly"]=="هابط" for x in results),"محايد":sum(x["weekly"]=="محايد" for x in results),"غير متاح":sum(x["weekly"]=="غير متاح" for x in results)}
  signals=[x["signal"] for x in results if x["signal"]]
  signals.sort(key=lambda x: (x["weekly"]==x["daily"]==x["h4"]),reverse=True)
  payload={"market":market,"name":cfg["name"],"timeframe":timeframe,"universe":len(universe),"counts":counts,"signals":signals,"analyzed":len(results),"updated":datetime.now(timezone.utc).isoformat(),"method":"weekly → daily → 4h → 15m","note":"الاتجاه من آخر شمعة مكتملة. الأصول غير المدعومة أو بياناتها الناقصة تظهر غير متاحة ولا تُحسب كتأكيد."}
  with self.lock: self.cache[key]=(time.time(),payload)
  return payload
 def market_overview(self):
  out=[]
  for key,cfg in MARKETS.items():
   out.append({"id":key,"name":cfg["name"],"type":cfg["kind"]})
  return {"markets":out,"direction_method":"weekly → daily → 4h → 15m"}
 def news(self):
  feeds=["https://feeds.reuters.com/reuters/businessNews","https://www.cnbc.com/id/100003114/device/rss/rss.html"]
  items=[]
  for url in feeds:
   try:
    root=ET.fromstring(self.session.get(url,timeout=8).text)
    for item in root.findall(".//item")[:12]:
     items.append({"title":item.findtext("title"),"url":item.findtext("link"),"published":item.findtext("pubDate"),"source":url.split("/")[2]})
   except Exception: continue
  return {"items":items,"note":"الأخبار من خلاصات RSS؛ التصنيف يحتاج قراءة الخبر ولا يتم اختلاق أثر سعري."}
