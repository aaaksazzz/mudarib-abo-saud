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
 {"slug":"risk-management-in-trading","title":"إدارة المخاطر في التداول: دليل عملي للمبتدئين","text":"تعلم تحديد حجم الصفقة ووقف الخسارة ونسبة العائد إلى المخاطرة قبل دخول السوق."},
 {"slug":"stop-loss-explained","title":"ما هو وقف الخسارة وكيف تختار مستواه؟","text":"شرح وقف الخسارة ومتى يستخدم وكيف تتجنب وضعه قريباً جداً من ضوضاء السوق."},
 {"slug":"risk-reward-ratio","title":"نسبة العائد إلى المخاطرة: كيف تحسبها؟","text":"طريقة حساب نسبة العائد إلى المخاطرة وفهم علاقتها بنسبة الفوز والنتيجة المتوقعة."},
 {"slug":"technical-analysis-basics","title":"أساسيات التحليل الفني للأسهم والعملات","text":"تعرف على الاتجاه والدعم والمقاومة وحركة السعر دون تعقيد المؤشرات."},
 {"slug":"support-and-resistance","title":"الدعم والمقاومة: طريقة تحديد المستويات","text":"شرح مناطق الدعم والمقاومة وكيفية التعامل مع الاختراقات والارتدادات."},
 {"slug":"trend-following-strategy","title":"استراتيجية تتبع الاتجاه: المزايا والمخاطر","text":"كيف تعمل استراتيجيات تتبع الاتجاه ولماذا تتعرض لخسائر في الأسواق العرضية."},
 {"slug":"breakout-trading-guide","title":"تداول الاختراقات: كيف تميز الاختراق الحقيقي؟","text":"دليل عملي لفهم الاختراقات وإعادة الاختبار ومخاطر الإشارات الكاذبة."},
 {"slug":"crypto-spot-trading","title":"تداول العملات الرقمية سبوت: دليل البداية","text":"تعرف على تداول السبوت والرموز والسيولة وأوامر السوق والحدود الأساسية للمخاطر."},
 {"slug":"crypto-futures-risks","title":"مخاطر عقود العملات الرقمية الآجلة والرافعة المالية","text":"شرح الهامش والتصفية والرافعة والانزلاق في تداول العقود الرقمية."},
 {"slug":"bitcoin-volatility","title":"تقلبات البيتكوين: كيف تتعامل معها؟","text":"ما أسباب تقلب البيتكوين وكيف يؤثر حجم الصفقة والسيولة والأخبار في المخاطر."},
 {"slug":"trading-timeframes","title":"اختيار الإطار الزمني المناسب للتداول","text":"مقارنة الفريمات القصيرة والطويلة وتأثيرها في عدد الصفقات والضوضاء والتكاليف."},
 {"slug":"trading-journal","title":"دفتر تداول: طريقة قياس تطور أدائك","text":"أنشئ سجل تداول يتضمن سبب الدخول والخروج والرسوم والالتزام بالخطة."},
 {"slug":"backtesting-trading-strategy","title":"الاختبار التاريخي للاستراتيجيات: أخطاء يجب تجنبها","text":"تعرف على الانزلاق والرسوم والانحياز للمستقبل والإفراط في ملاءمة البيانات."},
 {"slug":"trading-psychology","title":"سيكولوجية التداول: كيف تقلل القرارات العاطفية؟","text":"خطوات عملية للتعامل مع الخوف والطمع والانتقام من السوق بعد الخسارة."},
 {"slug":"saudi-stock-market-tasi","title":"مقدمة عن السوق السعودي وتداول تاسي","text":"تعرف على مؤشر تاسي ومواعيد السوق وأهمية الإفصاحات والسيولة عند متابعة الأسهم السعودية."},
 {"slug":"us-stock-market-basics","title":"أساسيات متابعة الأسهم الأمريكية","text":"كيف تدرس الأسهم الأمريكية باستخدام النتائج المالية والسيولة والأخبار والتقلب."}
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
