from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
import json, math, time

app=FastAPI(title="التداول الذكي PRO",version="3.0.0")
BASE=Path(__file__).parent
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES={"5m":"5د","15m":"15د","1h":"1س","4h":"4س","1d":"يومي","1w":"أسبوعي","1M":"شهري"}
YI={"5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
CACHE={}; UCACHE={}

ANALYSTS=[
 {"name":"George Soros","school":"السياق والماكرو وحركة السعر"},
 {"name":"Stanley Druckenmiller","school":"الاتجاه والزخم وإدارة المخاطر"},
 {"name":"Paul Tudor Jones","school":"حركة السعر ونقاط التحول"},
 {"name":"Jesse Livermore","school":"الاختراقات والسلوك السعري"},
 {"name":"Jim Simons","school":"اكتشاف الأنماط من البيانات الخام"},
 {"name":"Richard Dennis","school":"Trend Following والاختراق"},
 {"name":"Ed Seykota","school":"الاتجاه والانضباط وإدارة المخاطر"}
]

def get_json(url,timeout=8):
    req=Request(url,headers={"User-Agent":"MudaribSmart/3.0"})
    with urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())

def f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except:return None

def norm(rows):
    out=[]
    for x in rows or []:
        if len(x)<6:continue
        vals=[f(x[i]) for i in (1,2,3,4,5)]
        if any(v is None for v in vals[:4]):continue
        out.append({"t":int(x[0]/1000),"o":vals[0],"h":vals[1],"l":vals[2],"c":vals[3],"v":vals[4] or 0})
    return out

def yahoo(symbol,interval):
    periods={"5m":59,"15m":179,"1h":179,"1d":1095,"1wk":2555,"1mo":4380}
    start=int(time.time())-periods.get(interval,179)*86400
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}?period1={start}&period2={int(time.time())}&interval={interval}&events=history"
    d=get_json(u).get("chart",{}).get("result")
    if not d:return []
    d=d[0]; q=d.get("indicators",{}).get("quote",[{}])[0]; out=[]
    for i,t in enumerate(d.get("timestamp",[])):
        a=[q.get(k,[None]*len(d.get("timestamp",[])))[i] for k in ("open","high","low","close","volume")]
        if all(f(x) is not None for x in a[:4]):
            out.append({"t":int(t),"o":float(a[0]),"h":float(a[1]),"l":float(a[2]),"c":float(a[3]),"v":float(a[4] or 0)})
    return out

def binance(symbol,interval,market):
    base={"spot":"https://api.binance.com/api/v3/klines","futures":"https://fapi.binance.com/fapi/v1/klines","contracts":"https://dapi.binance.com/dapi/v1/klines"}[market]
    return norm(get_json(f"{base}?symbol={quote(symbol,safe='')}&interval={interval}&limit=500"))

def agg(c,seconds):
    b={}
    for x in c:
        k=x["t"]//seconds*seconds
        z=b.setdefault(k,{"t":k,"o":x["o"],"h":x["h"],"l":x["l"],"c":x["c"],"v":0})
        z["h"]=max(z["h"],x["h"]); z["l"]=min(z["l"],x["l"]); z["c"]=x["c"]; z["v"]+=x["v"]
    return [b[k] for k in sorted(b)]

def candles(market,symbol,frame):
    key=(market,symbol,frame); now=time.time()
    if key in CACHE and now-CACHE[key][0]<180:return CACHE[key][1]
    try:
        if market in ("spot","futures","contracts"): c=binance(symbol,frame,market)
        else:
            c=yahoo(symbol,YI[frame])
            if frame=="4h":c=agg(c,14400)
        CACHE[key]=(now,c); return c
    except:return []

def universe(market):
    now=time.time()
    if market in UCACHE and now-UCACHE[market][0]<900:return UCACHE[market][1]
    try:
        if market=="spot":
            d=get_json("https://api.binance.com/api/v3/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed")]
        elif market=="futures":
            d=get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL"]
        elif market=="contracts":
            d=get_json("https://dapi.binance.com/dapi/v1/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("contractStatus")=="TRADING" and x.get("contractType")=="PERPETUAL"]
        elif market=="us":
            u=[(x,x) for x in ("AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","NFLX","JPM","AVGO","ORCL","COST","WMT","PLTR","CRM","ADBE","QCOM","MU","INTC")]
        elif market=="saudi":
            u=[(x,x+".SR") for x in ("2222","1120","2010","7010","1180","1150","1211","2050","2082","2380","4030","4003","4200","1212","2020")]
        else:
            u=[("Gold","GC=F"),("Oil","CL=F"),("EURUSD","EURUSD=X"),("GBPUSD","GBPUSD=X"),("USDJPY","JPY=X"),("USDCHF","CHF=X"),("AUDUSD","AUDUSD=X")]
        UCACHE[market]=(now,u);return u
    except:return []

def ph(c):return max(x["h"] for x in c)
def pl(c):return min(x["l"] for x in c)
def move(a,b):return (a-b)/(b or 1)*100
def body(x):return x["c"]-x["o"]

def a1(c):
    if len(c)<40:return "NEUTRAL"
    hs=[x["h"] for x in c];ls=[x["l"] for x in c]; cs=[x["c"] for x in c]
    up=sum(hs[i]>hs[i-1] and ls[i]>ls[i-1] for i in range(-8,0))
    dn=sum(hs[i]<hs[i-1] and ls[i]<ls[i-1] for i in range(-8,0))
    m=move(cs[-1],cs[-8])
    return "BUY" if up>=5 and m>.4 else "SELL" if dn>=5 and m<-.4 else "NEUTRAL"

def a2(c):
    if len(c)<30:return "NEUTRAL"
    x,p=c[-1],c[-2];r=max(x["h"]-x["l"],1e-12);pos=(x["c"]-x["l"])/r;b=abs(body(x))/r
    uw=x["h"]-max(x["o"],x["c"]);lw=min(x["o"],x["c"])-x["l"]
    if pos>.72 and body(x)>0 and b>.45:return "BUY"
    if pos<.28 and body(x)<0 and b>.45:return "SELL"
    if lw>abs(body(x))*1.8 and x["c"]>x["o"]:return "BUY"
    if uw>abs(body(x))*1.8 and x["c"]<x["o"]:return "SELL"
    return "NEUTRAL"

def a3(c):
    if len(c)<50:return "NEUTRAL"
    p=c[-1]["c"];hi=ph(c[-32:-2]);lo=pl(c[-32:-2]);band=max(p*.003,(hi-lo)*.03)
    if p>hi and p-hi>band*.25:return "BUY"
    if p<lo and lo-p>band*.25:return "SELL"
    if abs(p-lo)<=band and c[-1]["c"]>c[-1]["o"]:return "BUY"
    if abs(p-hi)<=band and c[-1]["c"]<c[-1]["o"]:return "SELL"
    return "NEUTRAL"

def a4(c):
    if len(c)<45:return "NEUTRAL"
    x=c[-1];hi=ph(c[-21:-1]);lo=pl(c[-21:-1])
    if x["l"]<lo and x["c"]>lo:return "BUY"
    if x["h"]>hi and x["c"]<hi:return "SELL"
    return "NEUTRAL"

def a5(c):
    if len(c)<60:return "NEUTRAL"
    a,b=c[-30:-15],c[-15:];ah,al=ph(a),pl(a);bh,bl=ph(b),pl(b)
    if bh>ah and bl>al and b[-1]["c"]>ah:return "BUY"
    if bh<ah and bl<al and b[-1]["c"]<al:return "SELL"
    return "NEUTRAL"

def a6(c):
    if len(c)<55:return "NEUTRAL"
    prior=c[-26:-6];hi=ph(prior);lo=pl(prior);last=c[-1]
    touched_hi=min(abs(x["l"]-hi) for x in c[-6:])<=max(hi*.002,1e-12)
    touched_lo=min(abs(x["h"]-lo) for x in c[-6:])<=max(lo*.002,1e-12)
    if last["c"]>hi and touched_hi:return "BUY"
    if last["c"]<lo and touched_lo:return "SELL"
    return "NEUTRAL"

def a7(c):
    if len(c)<45:return "NEUTRAL"
    p=c[-1]["c"];hi=ph(c[-21:-1]);lo=pl(c[-21:-1]);span=max(hi-lo,p*.002)
    up=hi-p;dn=p-lo
    return "BUY" if up>span*.55 and dn<span*.45 else "SELL" if dn>span*.55 and up<span*.45 else "NEUTRAL"

ANALYZE=(a1,a2,a3,a4,a5,a6,a7)

def trade(c,market,frame,symbol):
    if len(c)<40:return None
    votes=[fn(c) for fn in ANALYZE]; buy=votes.count("BUY");sell=votes.count("SELL")
    if buy==0 and sell==0:return None
    side,agree=("BUY",buy) if buy>sell else ("SELL",sell) if sell>buy else (None,0)
    if not side:return None
    if market in ("spot","saudi","us") and side!="BUY":return None
    p=c[-1]["c"];hi=ph(c[:-1][-20:]);lo=pl(c[:-1][-20:])
    if side=="BUY":sl=min(lo,p*.992);risk=p-sl;tps=[p+risk*x for x in (1,1.8,2.6)]
    else:sl=max(hi,p*1.008);risk=sl-p;tps=[p-risk*x for x in (1,1.8,2.6)]
    if risk<=0:return None
    return {"asset":symbol,"market":market,"timeframe":frame,"timeframe_name":FRAMES[frame],"side":side,
            "ai_percent":round(agree/7*100),"analysts_agree":agree,"analysts_total":7,"entry":p,
            "tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"created_at":int(time.time()),
            "analysts":[ANALYSTS[i]["name"] for i in range(7)],
            "analyst_votes":[{"name":ANALYSTS[i]["name"],"school":ANALYSTS[i]["school"],"vote":votes[i]} for i in range(7)]}

@app.get("/")
def home():return FileResponse(BASE/"static/index.html")

@app.get("/health")
def health():return {"status":"ok","service":"mudarib-abo-saud","engine":"7-independent-experts-no-indicators","time":time.time()}

@app.get("/api/markets")
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"analysts":ANALYSTS,"indicators":False}

@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("15m")):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid_market_or_timeframe"}
    items=[];checked=ok=errors=0
    for name,symbol in universe(market):
        checked+=1
        try:
            c=candles(market,symbol,timeframe)
            if len(c)<40:continue
            ok+=1
            t=trade(c,market,timeframe,name)
            if t:items.append(t)
        except:errors+=1
    items.sort(key=lambda x:(x["analysts_agree"],x["ai_percent"]),reverse=True)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"timeframe_name":FRAMES[timeframe],
            "items":items[:30],"checked":checked,"data_ok":ok,"signals_found":len(items),"errors":errors,
            "indicators":False,"engine":"7 محللين مستقلين بدون مؤشرات"}

@app.get("/api/scanner")
def scanner():return {"items":[],"message":"الماسح يعتمد على محرك الأسواق"}

TRACKER={"open":{},"closed":[]}

def _tracker_key(x):
    return f"{x.get('market')}:{x.get('asset')}:{x.get('timeframe')}"

def _register_trade(x):
    k=_tracker_key(x)
    if k not in TRACKER["open"]:
        TRACKER["open"][k]=dict(x, status="OPEN", result=None, checked_at=int(time.time()))

def _evaluate_tracker_trade(x):
    try:
        c=candles(x["market"],x["asset"] if x["market"]!="us" and x["market"]!="saudi" else (x["asset"] if x["market"]=="us" else x["asset"]+".SR"),x["timeframe"])
        if not c:return None
        start=max(0,next((i for i,v in enumerate(c) if v["t"]>=x["created_at"]),len(c)-1))
        for bar in c[start:]:
            if x["side"]=="BUY":
                if bar["l"]<=x["sl"]:
                    return "LOSS","SL"
                if bar["h"]>=x["tp3"]:
                    return "WIN","TP3"
                if bar["h"]>=x["tp2"]:
                    return "WIN","TP2"
                if bar["h"]>=x["tp1"]:
                    return "WIN","TP1"
            else:
                if bar["h"]>=x["sl"]:
                    return "LOSS","SL"
                if bar["l"]<=x["tp3"]:
                    return "WIN","TP3"
                if bar["l"]<=x["tp2"]:
                    return "WIN","TP2"
                if bar["l"]<=x["tp1"]:
                    return "WIN","TP1"
    except Exception:
        return None
    return None

@app.get("/api/tracker")
def tracker():
    # The tracker follows real generated signals and evaluates them against subsequent market candles.
    for k,x in list(TRACKER["open"].items()):
        result=_evaluate_tracker_trade(x)
        if result:
            status,hit=result
            closed=dict(x,status="CLOSED",result=status,hit=hit,closed_at=int(time.time()))
            TRACKER["closed"].append(closed)
            del TRACKER["open"][k]
    wins=sum(1 for x in TRACKER["closed"] if x["result"]=="WIN")
    losses=sum(1 for x in TRACKER["closed"] if x["result"]=="LOSS")
    total=wins+losses
    return {"open":list(TRACKER["open"].values())[-100:],"closed":TRACKER["closed"][-100:],"stats":{"wins":wins,"losses":losses,"total":total,"win_rate":round(wins/total*100,2) if total else 0}}


@app.get("/api/account")
def account():return {"authenticated":False}

@app.get("/api/admin")
def admin():return {"ok":True}

NEWS=[{"id":1,"title":"كيف تقرأ حركة السوق قبل اتخاذ قرار التداول","category":"تعليم التداول","date":"2026-09-28","summary":"قراءة الاتجاه والمناطق والسلوك السعري.","body":"ابدأ بحركة السعر والمناطق المهمة وسلوك السيولة."},{"id":2,"title":"إدارة المخاطر","category":"إدارة المخاطر","date":"2026-09-27","summary":"الوقف جزء من الخطة.","body":"حدد نقطة إلغاء الفكرة قبل الدخول."},{"id":3,"title":"الفرق بين الإشارة والتحليل","category":"تحليل","date":"2026-09-26","summary":"الإشارة ليست ضماناً.","body":"عندما تختلف القراءات تظهر النسبة كما هي."}]
BLOG=[{"id":1,"title":"دليل عملي لفهم الاتجاه على عدة فريمات","category":"دروس","date":"2026-09-28","summary":"قراءة حركة السعر من أكثر من فريم.","body":"ابدأ بالسياق الأكبر ثم الفريم المطلوب."},{"id":2,"title":"الدعم والمقاومة بطريقة عملية","category":"دروس","date":"2026-09-27","summary":"تمييز مناطق تفاعل السعر.","body":"المناطق المتكررة أهم من خط منفرد."},{"id":3,"title":"متى لا تكون هناك صفقة؟","category":"منهجية","date":"2026-09-26","summary":"الانتظار عندما لا تتوفر بيانات كافية.","body":"لا تختلق صفقة عند نقص البيانات."}]

@app.get("/api/news")
def news():return {"items":NEWS}
@app.get("/api/news/{item_id}")
def news_item(item_id:int):return next((x for x in NEWS if x["id"]==item_id),{"error":"not_found"})
@app.get("/api/blog")
def blog():return {"items":BLOG}
@app.get("/api/blog/{item_id}")
def blog_item(item_id:int):return next((x for x in BLOG if x["id"]==item_id),{"error":"not_found"})
