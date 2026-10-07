import time,requests,xml.etree.ElementTree as ET
from fastapi import APIRouter
router=APIRouter()
NEWS_SOURCES=[
 ("market_global","https://finance.yahoo.com/news/rssindex"),
 ("crypto_market","https://www.coindesk.com/arc/outboundfeeds/rss/"),
 ("digital_assets","https://cointelegraph.com/rss"),
 ("global_markets","https://news.google.com/rss/search?q=stock%20market%20OR%20crypto%20OR%20gold%20OR%20forex%20OR%20oil&hl=en-US&gl=US&ceid=US:en")
]
BLOG=[
 {"title":"كيف تقرأ صفقة بدون مطاردة السعر","text":"راقب الدخول والوقف والأهداف قبل اتخاذ القرار، ولا تدخل بعد حركة انفجارية."},
 {"title":"لماذا فصل الأسواق مهم؟","text":"لكل سوق مصدر بيانات وطبيعة حركة مختلفة؛ لذلك يعمل كل قسم في صفحة مستقلة."},
 {"title":"إدارة المخاطر أهم من نسبة الفوز","text":"حدد خسارتك المقبولة قبل الصفقة، ولا ترفع المخاطرة لتعويض خسارة سابقة."},
 {"title":"كيف نستخدم الأخبار مع التحليل؟","text":"الخبر سياق إضافي وليس بديلاً عن بيانات السعر والسيولة وبنية السوق."}
]
def _rss(url):
 try:
  r=requests.get(url,timeout=7,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
  if not r.ok:return []
  root=ET.fromstring(r.content);out=[]
  for item in root.findall(".//item")[:8]:
   title=(item.findtext("title") or "").strip();link=(item.findtext("link") or "").strip();date=(item.findtext("pubDate") or "").strip()
   if title:out.append({"title":title,"url":link,"published":date})
  return out
 except Exception:return []
def _news_arabic(title):
 t=str(title or "").strip()
 replacements=[
  ("Federal Reserve","الفيدرالي الأمريكي"),("Fed","الفيدرالي الأمريكي"),("interest rates","أسعار الفائدة"),
  ("interest rate","سعر الفائدة"),("inflation","التضخم"),("jobs","الوظائف"),("employment","التوظيف"),
  ("stocks","الأسهم"),("stock","السهم"),("shares","الأسهم"),("markets","الأسواق"),("market","السوق"),
  ("Bitcoin","بتكوين"),("Ethereum","إيثريوم"),("crypto","العملات الرقمية"),("cryptocurrency","العملات الرقمية"),
  ("gold","الذهب"),("oil","النفط"),("dollar","الدولار"),("euro","اليورو"),("China","الصين"),
  ("tariffs","الرسوم الجمركية"),("earnings","النتائج المالية"),("forecast","التوقعات"),
  ("rises","يرتفع"),("rising","ارتفاع"),("falls","ينخفض"),("falling","تراجع"),("surges","يقفز"),
  ("drops","يتراجع"),("cuts","يخفض"),("hikes","يرفع"),("warning","تحذير"),("ahead","قبل")
 ]
 for a,b in replacements:
  t=t.replace(a,b)
 # Keep the editorial voice clearly ours rather than exposing a copied headline.
 return "مستجدات الأسواق: "+t

def _news_impact(title):
 t=str(title or "").lower()
 if any(k in t for k in ("fed","interest","inflation","jobs","employment","tariff","oil","gold")):
  return "مرتفع"
 if any(k in t for k in ("bitcoin","crypto","ethereum","stocks","shares","market")):
  return "متوسط"
 return "متابعة"

@router.get("/api/news")
def news():
 items=[]
 seen=set()
 for _,url in NEWS_SOURCES:
  for x in _rss(url)[:8]:
   key=str(x.get("title","")).strip().lower()
   if not key or key in seen: continue
   seen.add(key)
   title=x.get("title","")
   items.append({
    "title":_news_arabic(title),
    "summary":"أبرز مستجدات السوق مع التركيز على ما قد يؤثر في حركة الأسعار والسيولة.",
    "impact":_news_impact(title),
    "published":x.get("published",""),
    "urgent":_news_impact(title)=="مرتفع"
   })
 items=items[:40]
 return {"ok":True,"items":items,"updated":time.time(),"brand":"التداول الذكي PRO"}
@router.get("/api/blog")
def blog():
 return {"ok":True,"items":BLOG,"updated":time.time()}
