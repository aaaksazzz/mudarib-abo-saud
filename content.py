import time,requests,xml.etree.ElementTree as ET
from fastapi import APIRouter
router=APIRouter()
NEWS_SOURCES=[
 ("Yahoo Finance","https://finance.yahoo.com/news/rssindex"),
 ("CoinDesk","https://www.coindesk.com/arc/outboundfeeds/rss/"),
 ("Cointelegraph","https://cointelegraph.com/rss"),
 ("Google News Markets","https://news.google.com/rss/search?q=stock%20market%20OR%20crypto%20OR%20gold&hl=en-US&gl=US&ceid=US:en")
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
@router.get("/api/news")
def news():
 out=[]
 for source,url in NEWS_SOURCES:
  for x in _rss(url)[:6]:
   x["source"]=source;out.append(x)
 return {"ok":True,"items":out[:30],"updated":time.time()}
@router.get("/api/blog")
def blog():
 return {"ok":True,"items":BLOG,"updated":time.time()}
