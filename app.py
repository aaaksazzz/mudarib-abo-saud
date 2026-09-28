from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
import json, math, time, statistics

app=FastAPI(title="التداول الذكي PRO", version="2.0.0")
BASE=Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")

MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES={"5m":"5د","15m":"15د","1h":"1س","4h":"4س","1d":"يومي","1w":"أسبوعي","1M":"شهري"}
FRAME_SECONDS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}

def get_json(url, timeout=7):
    req=Request(url,headers={"User-Agent":"MudaribSmart/2.0"})
    with urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def yahoo(symbol, interval):
    period=90*86400 if interval in ("5m","15m","1h","4h") else 370*86400
    end=int(time.time()); start=end-period
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}?period1={start}&period2={end}&interval={interval}"
    d=get_json(u)["chart"]["result"][0]
    q=d["indicators"]["quote"][0]; out=[]
    for i,ts in enumerate(d.get("timestamp",[])):
        vals=[q[k][i] if i<len(q[k]) else None for k in ("open","high","low","close","volume")]
        if all(v is not None and math.isfinite(float(v)) for v in vals[:4]):
            out.append({"t":ts,"o":float(vals[0]),"h":float(vals[1]),"l":float(vals[2]),"c":float(vals[3]),"v":float(vals[4] or 0)})
    return out

def binance(symbol, interval):
    limit=300
    u=f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    rows=get_json(u); return [{"t":int(x[0]/1000),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in rows]

def universe(market):
    if market in ("spot","futures","contracts"):
        try:
            info=get_json("https://api.binance.com/api/v3/exchangeInfo")
            syms=[x["symbol"] for x in info["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed")]
            return [(s,s) for s in syms[:120]]
        except Exception:
            return []
    if market=="us":
        return [("AAPL","AAPL"),("MSFT","MSFT"),("NVDA","NVDA"),("AMZN","AMZN"),("META","META"),("TSLA","TSLA"),("GOOGL","GOOGL"),("AMD","AMD"),("NFLX","NFLX"),("JPM","JPM")]
    if market=="saudi":
        return [(x,x+".SR") for x in ("2222","1120","2010","7010","1180","1150","1211","2050","2082","2380")]
    return [("Gold","GC=F"),("Oil","CL=F"),("EURUSD","EURUSD=X"),("GBPUSD","GBPUSD=X"),("USDJPY","JPY=X")]

def candles(market,symbol,frame):
    if market in ("spot","futures","contracts"):
        return binance(symbol,frame)
    interval={"5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}[frame]
    return yahoo(symbol,interval)

def direction(c):
    if len(c)<35: return "NEUTRAL"
    closes=[x["c"] for x in c]; highs=[x["h"] for x in c]; lows=[x["l"] for x in c]; vols=[x["v"] for x in c]
    last=closes[-1]; prev=closes[-6]
    recent_high=max(highs[-21:-1]); recent_low=min(lows[-21:-1])
    body=(closes[-1]-closes[-2])/(closes[-2] or 1)*100
    slope=(last-prev)/(prev or 1)*100
    rng=max(highs[-20:])-min(lows[-20:])
    pos=(last-min(lows[-20:]))/(rng or last)
    vol=statistics.mean(vols[-20:]) if any(vols[-20:]) else 0
    vratio=(vols[-1]/vol) if vol else 1
    votes=[]
    # 1 الاتجاه
    votes.append("BUY" if slope>0.25 else "SELL" if slope<-0.25 else "NEUTRAL")
    # 2 مناطق السعر
    votes.append("BUY" if last>recent_high*1.002 else "SELL" if last<recent_low*0.998 else ("BUY" if pos>0.62 else "SELL" if pos<0.38 else "NEUTRAL"))
    # 3 حركة السعر
    votes.append("BUY" if body>0.35 and closes[-1]>closes[-2] else "SELL" if body<-0.35 else "NEUTRAL")
    # 4 الاختراق
    votes.append("BUY" if last>recent_high*1.001 else "SELL" if last<recent_low*0.999 else "NEUTRAL")
    # 5 السيولة والحجم الخام
    votes.append("BUY" if vratio>=1.15 and body>0 else "SELL" if vratio>=1.15 and body<0 else "NEUTRAL")
    # 6 سلوك السوق
    votes.append("BUY" if sum(1 for i in range(-5,0) if closes[i]>closes[i-1])>=4 else "SELL" if sum(1 for i in range(-5,0) if closes[i]<closes[i-1])>=4 else "NEUTRAL")
    # 7 المخاطرة/المسافة
    risk=max(last-recent_low, recent_high-last, last*0.006)
    up=recent_high-last; down=last-recent_low
    votes.append("BUY" if up>risk*1.2 and down>risk*0.5 else "SELL" if down>risk*1.2 and up>risk*0.5 else "NEUTRAL")
    return votes

def trade_from(c,market,frame,symbol):
    if len(c)<35:return None
    votes=direction(c)
    buy=votes.count("BUY"); sell=votes.count("SELL")
    side="BUY" if buy>sell else "SELL" if sell>buy else None
    agree=max(buy,sell)
    if not side or agree==0:return None
    price=c[-1]["c"]; recent_high=max(x["h"] for x in c[-21:-1]); recent_low=min(x["l"] for x in c[-21:-1])
    if side=="BUY":
        sl=min(recent_low,price*0.985); risk=price-sl
        if risk<=0:return None
        tps=[price+risk*x for x in (1.0,1.7,2.4)]
    else:
        sl=max(recent_high,price*1.015); risk=sl-price
        if risk<=0:return None
        tps=[price-risk*x for x in (1.0,1.7,2.4)]
    if market in ("spot","saudi","us") and side!="BUY": return None
    return {"asset":symbol,"market":market,"timeframe":frame,"timeframe_name":FRAMES[frame],"side":side,"ai_percent":round(agree/7*100),"analysts_agree":agree,"analysts_total":7,"entry":price,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"created_at":int(time.time()),"analysts":["الاتجاه","الدعم والمقاومة","حركة السعر","الاختراق","السيولة والحجم","سلوك السوق","المخاطرة"]}

@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","time":time.time(),"engine":"7-analysts-no-indicators"}

@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES}

@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("15m")):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid_market_or_timeframe"}
    items=[]
    for name,symbol in universe(market):
        try:
            t=trade_from(candles(market,symbol,timeframe),market,timeframe,name)
            if t: items.append(t)
        except Exception: continue
    items.sort(key=lambda x:(x["analysts_agree"],x["ai_percent"],x["created_at"]),reverse=True)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"timeframe_name":FRAMES[timeframe],"items":items[:30],"engine":"7 محللين متخصصين بدون مؤشرات"}

@app.get("/api/scanner")
def scanner():
    return {"items":[],"message":"استخدم صفحات الأسواق لاستخراج الصفقات حسب الفريم"}

@app.get("/api/tracker")
def tracker(): return {"open":[],"closed":[],"stats":{"wins":0,"losses":0,"total":0}}

@app.get("/api/account")
def account(): return {"authenticated":False}

@app.get("/api/admin")
def admin(): return {"ok":True}

NEWS=[{"id":1,"title":"كيف تقرأ حركة السوق قبل اتخاذ قرار التداول","category":"تعليم التداول","date":"2026-09-28","summary":"منهج مبسط لقراءة الاتجاه والدعم والمقاومة وحجم التداول.","body":"ابدأ بحركة السعر والمناطق المهمة وسلوك السيولة. لا تعتمد على مؤشر فني لاتخاذ القرار."},{"id":2,"title":"إدارة المخاطر: لماذا الوقف جزء من الخطة","category":"إدارة المخاطر","date":"2026-09-27","summary":"نقطة الإلغاء وحجم المخاطرة جزء أساسي من خطة التداول.","body":"حدد نقطة إلغاء الفكرة قبل الدخول واجعل حجم الصفقة متناسباً مع المخاطرة."},{"id":3,"title":"الفرق بين الإشارة والتحليل","category":"تحليل","date":"2026-09-26","summary":"الإشارة خلاصة تحليل متعدد المصادر وليست ضماناً للنتيجة.","body":"عندما تختلف قراءات المحللين، تظهر النسبة كما هي بدلاً من إخفاء الاختلاف."}]
BLOG=[{"id":1,"title":"دليل عملي لفهم الاتجاه على عدة فريمات","category":"دروس","date":"2026-09-28","summary":"طريقة منظمة لقراءة حركة السعر من أكثر من فريم.","body":"ابدأ بالسياق الأكبر ثم راقب الحركة في الفريم المطلوب."},{"id":2,"title":"الدعم والمقاومة بطريقة عملية","category":"دروس","date":"2026-09-27","summary":"تمييز المناطق التي تكرر عندها رد فعل السعر.","body":"المناطق السعرية المتكررة أهم من خط منفرد."},{"id":3,"title":"متى لا تكون هناك صفقة؟","category":"منهجية","date":"2026-09-26","summary":"الانتظار نتيجة صحيحة عندما لا تتوفر قراءة واضحة.","body":"إذا كانت البيانات ناقصة أو القراءات متضاربة، لا تختلق صفقة."}]
@app.get("/api/news")
def news(): return {"items":NEWS}
@app.get("/api/news/{item_id}")
def news_item(item_id:int): return next((x for x in NEWS if x["id"]==item_id),{"error":"not_found"})
@app.get("/api/blog")
def blog(): return {"items":BLOG}
@app.get("/api/blog/{item_id}")
def blog_item(item_id:int): return next((x for x in BLOG if x["id"]==item_id),{"error":"not_found"})
