from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import time

app=FastAPI(title="التداول الذكي PRO", version="1.0.1")
BASE=Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")

MARKETS={
 "spot":"السبوت","futures":"الفيوتشر","contracts":"العقود",
 "saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"
}
FRAMES={"5m":"5د","15m":"15د","1h":"1س","4h":"4س","1d":"يومي","1w":"أسبوعي","1M":"شهري"}

@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","time":time.time()}

@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES}

@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("15m")):
    # Demo-safe shell: no fabricated live prices. Real market adapters are added in the next layer.
    return {"market":market,"market_name":MARKETS.get(market,market),
            "timeframe":timeframe,"timeframe_name":FRAMES.get(timeframe,timeframe),
            "items":[],"message":"بانتظار ربط مصدر البيانات الحقيقي"}


@app.get("/api/scanner")
def scanner(): return {"items":[]}

@app.get("/api/tracker")
def tracker(): return {"open":[],"closed":[],"stats":{"wins":0,"losses":0,"total":0}}

@app.get("/api/account")
def account(): return {"authenticated":False}

@app.get("/api/admin")
def admin(): return {"ok":True}


NEWS=[
{"id":1,"title":"كيف تقرأ حركة السوق قبل اتخاذ قرار التداول","category":"تعليم التداول","date":"2026-09-28","summary":"منهج مبسط لقراءة الاتجاه والدعم والمقاومة وحجم التداول.","body":"ابدأ بتحديد الاتجاه على الفريمات الأكبر، ثم انتقل إلى فريم الدخول. راقب مناطق الدعم والمقاومة وسلوك السعر عندها وحجم التداول. إذا تعارضت الإشارات فلا تستعجل نشر صفقة."},
{"id":2,"title":"إدارة المخاطر: لماذا الوقف جزء من الخطة","category":"إدارة المخاطر","date":"2026-09-27","summary":"نقطة الإلغاء وحجم المخاطرة جزء أساسي من خطة التداول.","body":"حدد نقطة إلغاء الفكرة قبل الدخول، واجعل حجم الصفقة متناسباً مع المخاطرة التي تستطيع تحملها. لا تحرك الوقف بعيداً لمجرد أن السعر تحرك ضدك."},
{"id":3,"title":"الفرق بين الإشارة والتحليل","category":"تحليل","date":"2026-09-26","summary":"الإشارة المختصرة نتيجة للتحليل وليست بديلاً عنه.","body":"التحليل الجيد يجمع بيانات السعر والفريمات والسياق وحالة السوق. الإشارة هي خلاصة التحليل عندما تكون الشروط مكتملة."}
]
BLOG=[
{"id":1,"title":"دليل عملي لفهم الاتجاه على عدة فريمات","category":"دروس","date":"2026-09-28","summary":"طريقة منظمة للانتقال من الفريمات الكبيرة إلى فريم الصفقة.","body":"استخدم الفريمات الكبيرة لفهم السياق العام، ثم ضيق النطاق تدريجياً حتى تصل إلى فريم التنفيذ."},
{"id":2,"title":"الدعم والمقاومة بطريقة عملية","category":"دروس","date":"2026-09-27","summary":"كيف تميز المنطقة المهمة عن مستوى عشوائي على الرسم.","body":"المناطق التي تكررت عندها ردود فعل سعرية تكون أكثر أهمية من خط منفرد. تعامل معها كنطاقات وانتظر سلوك السعر."},
{"id":3,"title":"متى لا تكون هناك صفقة؟","category":"منهجية","date":"2026-09-26","summary":"عدم وجود إشارة قوية قرار تحليلي وليس نقصاً في الفرص.","body":"إذا كانت الاتجاهات متضاربة أو البيانات ناقصة أو المخاطرة للعائد غير مناسبة، فالنتيجة الصحيحة هي الانتظار."}
]
@app.get("/api/news")
def news(): return {"items":NEWS}
@app.get("/api/news/{item_id}")
def news_item(item_id:int): return next((x for x in NEWS if x["id"]==item_id),{"error":"not_found"})
@app.get("/api/blog")
def blog(): return {"items":BLOG}
@app.get("/api/blog/{item_id}")
def blog_item(item_id:int): return next((x for x in BLOG if x["id"]==item_id),{"error":"not_found"})
