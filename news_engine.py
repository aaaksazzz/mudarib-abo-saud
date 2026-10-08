import re,time,html,urllib.parse,urllib.request,xml.etree.ElementTree as ET

UA="SMART-TRADING-PRO/NEWS"
TTL=300
_cache={"at":0,"items":[]}

QUERIES=[
 ("السعودي","السوق السعودي تداول تاسي أسهم نتائج شركات","TASI"),
 ("الأمريكي","الأسهم الأمريكية ناسداك داو S&P شركات","US"),
 ("الكريبتو","بيتكوين إيثريوم العملات الرقمية كريبتو","CRYPTO"),
 ("الذهب","الذهب أسعار الذهب الفائدة الدولار","GOLD"),
 ("النفط","النفط الخام أوبك أسعار النفط","OIL"),
 ("الفوركس","الدولار اليورو الجنيه الين فوركس","FOREX"),
]

POS=["ارتفاع","يرتفع","صعود","صاعد","نمو","تحسن","قوي","دعم","يدعم","إيجابي","قفزة","مكاسب","ارتفاع الطلب","خفض الفائدة","خفض أسعار الفائدة"]
NEG=["هبوط","ينخفض","تراجع","هبوط","ضعف","خسائر","ضغط","يضغط","سلبي","انخفاض الطلب","رفع الفائدة","رفع أسعار الفائدة","تحذير","ركود"]

def _fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=6) as r:return r.read()

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
    return out[:8]

def _clean(s):
    s=re.sub(r"\s+"," ",s or "").strip()
    return s[:260]

def _analyze(title,text,market):
    blob=(title+" "+text).lower()
    p=sum(1 for w in POS if w.lower() in blob)
    n=sum(1 for w in NEG if w.lower() in blob)
    direction="شراء" if p>n else ("بيع" if n>p else "محايد")
    impact="مرتفع" if abs(p-n)>=2 else ("متوسط" if abs(p-n)==1 else "منخفض")
    symbol="السوق"
    if market=="CRYPTO":
        if re.search(r"\b(bitcoin|btc|بيتكوين)\b",blob): symbol="بيتكوين BTC"
        elif re.search(r"\b(ethereum|eth|إيثريوم)\b",blob): symbol="إيثريوم ETH"
        else:symbol="الكريبتو"
    elif market=="GOLD": symbol="الذهب XAUUSD"
    elif market=="OIL": symbol="النفط WTI"
    elif market=="FOREX": symbol="الدولار / الفوركس"
    elif market=="US":
        for s in ["NVDA","TSLA","AAPL","MSFT","AMZN","META","GOOGL"]:
            if s.lower() in blob:symbol=s;break
        else:symbol="الأسهم الأمريكية"
    elif market=="TASI":
        m=re.search(r"\b(\d{4})\b",title+" "+text); symbol=m.group(1) if m else "تاسي"
    if direction=="شراء":
        why="يدعم الصعود والطلب على "+symbol
    elif direction=="بيع":
        why="يزيد ضغوط البيع والمخاطر على "+symbol
    else:
        why="الأثر غير واضح ويحتاج متابعة حركة السعر"
    summary=_clean(title)
    return {"title":summary,"summary":_clean("الخبر يشير إلى "+why+". "+(text[:180] if text else "")),
            "market":market,"market_name":{"TASI":"السوق السعودي / تاسي","US":"الأسهم الأمريكية","CRYPTO":"الكريبتو","GOLD":"الذهب","OIL":"النفط","FOREX":"الفوركس"}[market],
            "symbol":symbol,"direction":direction,"impact":impact,
            "action":("فرصة شراء" if direction=="شراء" else "فرصة بيع" if direction=="بيع" else "مراقبة"),
            "why":why,"published":pub if False else "حديث","fresh":True}

def get_news():
    now=time.time()
    if now-_cache["at"]<TTL:return _cache["items"]
    rows=[];seen=set()
    for name,q,market in QUERIES:
        for x in _rss(q):
            key=re.sub(r"\W","",x["title"].lower())
            if not key or key in seen:continue
            seen.add(key)
            item=_analyze(x["title"],x["text"],market)
            item["published"]=x["published"]
            rows.append(item)
    rows.sort(key=lambda x:({"مرتفع":3,"متوسط":2,"منخفض":1}.get(x["impact"],0), x["direction"]!="محايد"),reverse=True)
    _cache["at"]=now;_cache["items"]=rows[:40]
    return _cache["items"]

def install(app):
    if getattr(app,"_NEWS_INTELLIGENCE_PATCHED",False): return True
    try:
        from fastapi.responses import JSONResponse
        @app.get("/api/news")
        def news_api():
            return JSONResponse({"items":get_news(),"generated_at":time.time(),"mode":"arabic market intelligence","sources_hidden":True})
        app._NEWS_INTELLIGENCE_PATCHED=True
        return True
    except Exception:return False
