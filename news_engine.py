import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET

UA="SMART-TRADING-PRO/NEWS"; TTL=300
_cache={"at":0,"items":[]}
MARKETS={
 "TASI":"السوق السعودي / تاسي","US":"الأسهم الأمريكية","CRYPTO":"الكريبتو","GOLD":"الذهب","OIL":"النفط","FOREX":"الفوركس"
}
QUERIES=[
 "السوق السعودي تداول تاسي أسهم شركات اقتصاد السعودية","الأسهم الأمريكية ناسداك داو S&P شركات اقتصاد أمريكا","بيتكوين إيثريوم العملات الرقمية كريبتو","الذهب الفائدة الدولار أسعار الذهب","النفط أوبك أسعار النفط","الدولار اليورو الجنيه الين فوركس"
]
POS=["ارتفاع","يرتفع","صعود","صاعد","نمو","تحسن","قوي","دعم","يدعم","إيجابي","قفزة","مكاسب","خفض الفائدة","خفض أسعار الفائدة","تباطؤ التضخم","تراجع التضخم"]
NEG=["هبوط","ينخفض","تراجع","ضعف","خسائر","ضغط","يضغط","سلبي","انخفاض الطلب","رفع الفائدة","رفع أسعار الفائدة","تحذير","ركود","تضخم مرتفع"]

def _fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":UA})
 with urllib.request.urlopen(req,timeout=7) as r:return r.read()

def _rss(q):
 url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q+" when:1d","hl":"ar","gl":"SA","ceid":"SA:ar"})
 try: root=ET.fromstring(_fetch(url))
 except Exception:return []
 out=[]
 for it in root.findall(".//item"):
  title=html.unescape(it.findtext("title") or "")
  desc=html.unescape(re.sub("<[^>]+>"," ",it.findtext("description") or ""))
  pub=it.findtext("pubDate") or ""
  if title: out.append({"title":title,"text":desc,"published":pub})
 return out[:10]

def _clean(s): return re.sub(r"\s+"," ",s or "").strip()[:300]
def _norm(s): return re.sub(r"[^\w\u0600-\u06ff]","",s.lower())

def _score(blob):
 p=sum(1 for w in POS if w in blob); n=sum(1 for w in NEG if w in blob)
 return p,n

def _impact(blob,market):
 p,n=_score(blob); direction="شراء" if p>n else ("بيع" if n>p else "محايد")
 # Market-specific interpretation for macro/news relationships.
 macro=any(k in blob for k in ["الفائدة","الفيدرالي","التضخم","وظائف","الدولار","سعر الفائدة","الفائدة الأمريكية"])
 if market=="GOLD" and macro:
  if any(k in blob for k in ["رفع الفائدة","رفع أسعار الفائدة","الدولار يرتفع","قوة الدولار","تضخم مرتفع"]): direction="بيع"
  elif any(k in blob for k in ["خفض الفائدة","خفض أسعار الفائدة","الدولار يهبط","ضعف الدولار","تراجع التضخم"]): direction="شراء"
 if market=="FOREX" and macro:
  if any(k in blob for k in ["رفع الفائدة","رفع أسعار الفائدة","الفيدرالي يرفع","قوة الدولار"]): direction="شراء"
  elif any(k in blob for k in ["خفض الفائدة","خفض أسعار الفائدة","الفيدرالي يخفض","ضعف الدولار"]): direction="بيع"
 if market=="CRYPTO" and macro:
  if any(k in blob for k in ["رفع الفائدة","رفع أسعار الفائدة","تشديد","الدولار يرتفع"]): direction="بيع"
  elif any(k in blob for k in ["خفض الفائدة","خفض أسعار الفائدة","تيسير","الدولار يهبط"]): direction="شراء"
 if market=="OIL" and any(k in blob for k in ["أوبك","خفض الإنتاج","خفض انتاج","الإنتاج","إمدادات","طلب النفط"]):
  if any(k in blob for k in ["خفض الإنتاج","خفض انتاج","نقص الإمدادات","ارتفاع الطلب"]): direction="شراء"
  elif any(k in blob for k in ["زيادة الإنتاج","زيادة انتاج","فائض","انخفاض الطلب"]): direction="بيع"
 if market in ("US","TASI") and macro:
  if any(k in blob for k in ["خفض الفائدة","خفض أسعار الفائدة","تراجع التضخم"]): direction="شراء"
  elif any(k in blob for k in ["رفع الفائدة","رفع أسعار الفائدة","تضخم مرتفع","ركود"]): direction="بيع"
 strength=abs(p-n)
 impact="مرتفع" if strength>=2 or any(k in blob for k in ["الفيدرالي","أوبك","قرار الفائدة","حرب","عقوبات","نتائج","أرباح"] ) else ("متوسط" if strength else "منخفض")
 return direction,impact

def _symbol(blob,market,title):
 if market=="CRYPTO":
  if re.search(r"\b(bitcoin|btc|بيتكوين)\b",blob): return "بيتكوين BTC"
  if re.search(r"\b(ethereum|eth|إيثريوم)\b",blob): return "إيثريوم ETH"
  return "الكريبتو"
 if market=="GOLD": return "الذهب XAUUSD"
 if market=="OIL": return "النفط WTI"
 if market=="FOREX": return "الدولار / الفوركس"
 if market=="US":
  for s in ["NVDA","TSLA","AAPL","MSFT","AMZN","META","GOOGL","SPY","QQQ"]:
   if s.lower() in blob:return s
  return "الأسهم الأمريكية"
 m=re.search(r"\b(\d{4})\b",title)
 return m.group(1) if m else "تاسي"

def _why(direction,market,symbol,blob):
 if direction=="محايد": return "الأثر على هذا السوق غير حاسم حالياً؛ تتم مراقبة حركة السعر."
 return (f"الخبر يدعم الطلب على {symbol} في {MARKETS[market]}." if direction=="شراء" else f"الخبر يزيد ضغوط البيع والمخاطر على {symbol} في {MARKETS[market]}.")

def _impacts(title,text):
 blob=(title+" "+text).lower(); impacts=[]
 keys={
  "TASI":["تاسي","السوق السعودي","الأسهم السعودية","السعودية","أرامكو","سابك"],
  "US":["الأسهم الأمريكية","ناسداك","داو","s&p","ستاندرد","وول ستريت","الفيدرالي الأمريكي"],
  "CRYPTO":["بيتكوين","إيثريوم","كريبتو","العملات الرقمية","العملات المشفرة","btc","eth"],
  "GOLD":["الذهب","المعادن الثمينة","xau","الدولار","الفائدة","الفيدرالي","التضخم"],
  "OIL":["النفط","أوبك","خام","الإمدادات","إنتاج النفط"],
  "FOREX":["الدولار","اليورو","الجنيه","الين","الفوركس","العملات","الفائدة","الفيدرالي","التضخم"]}
 for m,ks in keys.items():
  if any(k.lower() in blob for k in ks):
   d,impact=_impact(blob,m); sym=_symbol(blob,m,title)
   impacts.append({"market":m,"market_name":MARKETS[m],"symbol":sym,"direction":d,"impact":impact,"action":("فرصة شراء" if d=="شراء" else "فرصة بيع" if d=="بيع" else "مراقبة"),"why":_why(d,m,sym,blob)})
 # Macro headlines can affect multiple markets even if only one was named.
 if any(k in blob for k in ["الفيدرالي","قرار الفائدة","أسعار الفائدة","التضخم الأمريكي","الوظائف الأمريكية"]):
  existing={x["market"] for x in impacts}
  for m in ["US","GOLD","CRYPTO","FOREX"]:
   if m not in existing:
    d,impact=_impact(blob,m); sym=_symbol(blob,m,title); impacts.append({"market":m,"market_name":MARKETS[m],"symbol":sym,"direction":d,"impact":impact,"action":("فرصة شراء" if d=="شراء" else "فرصة بيع" if d=="بيع" else "مراقبة"),"why":_why(d,m,sym,blob)})
 return impacts

def get_news():
 now=time.time()
 if now-_cache["at"]<TTL:return _cache["items"]
 grouped={}
 for q in QUERIES:
  for x in _rss(q):
   key=_norm(x["title"])
   if not key: continue
   if key not in grouped: grouped[key]={"title":_clean(x["title"]),"text":_clean(x["text"]),"published":x["published"],"impacts":[]}
   g=grouped[key]
   for imp in _impacts(g["title"],g["text"]):
    if not any(i["market"]==imp["market"] for i in g["impacts"]): g["impacts"].append(imp)
 items=[]
 for g in grouped.values():
  if not g["impacts"]: continue
  strength=max({"مرتفع":3,"متوسط":2,"منخفض":1}.get(i["impact"],0) for i in g["impacts"])
  items.append({"title":g["title"],"summary":_clean("تحليل الخبر على الأسواق: "+"، ".join(i["market_name"] for i in g["impacts"])),"published":g["published"],"impacts":g["impacts"],"markets_count":len(g["impacts"]),"max_impact":strength,"fresh":True})
 items.sort(key=lambda x:(x["max_impact"],x["markets_count"],x["published"]),reverse=True)
 _cache["at"]=now; _cache["items"]=items[:40]; return _cache["items"]

def install(app):
 if getattr(app,"_NEWS_INTELLIGENCE_PATCHED",False): return True
 try:
  from fastapi.responses import JSONResponse
  @app.get("/api/news")
  def news_api(): return JSONResponse({"items":get_news(),"generated_at":time.time(),"mode":"arabic multi-market intelligence","sources_hidden":True})
  app._NEWS_INTELLIGENCE_PATCHED=True; return True
 except Exception:return False
