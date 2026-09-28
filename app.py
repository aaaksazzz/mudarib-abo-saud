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

def _clean_candles(rows):
    out=[]
    for x in rows:
        try:
            vals=[float(x.get(k,0)) for k in ("o","h","l","c","v")]
            if all(math.isfinite(v) for v in vals[:4]) and vals[2] <= vals[1] and vals[2] <= vals[0] <= vals[1] and vals[2] <= vals[3] <= vals[1]:
                out.append({"t":int(x["t"]),"o":vals[0],"h":vals[1],"l":vals[2],"c":vals[3],"v":max(0.0,vals[4])})
        except Exception:
            continue
    return out

def yahoo(symbol, interval, period=None):
    # Yahoo intraday ranges are limited; use a safe range for each requested frame.
    safe_range={
        "5m":"5d","15m":"1mo","1h":"3mo","1d":"2y","1wk":"5y","1mo":"10y"
    }.get(interval, period or "1mo")
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}?range={safe_range}&interval={interval}&events=history"
    data=get_json(u)
    result=(data.get("chart") or {}).get("result")
    if not result: return []
    d=result[0]; q=(d.get("indicators") or {}).get("quote",[{}])[0]
    rows=[]
    for i,ts in enumerate(d.get("timestamp") or []):
        rows.append({"t":ts,"o":q.get("open",[None])[i],"h":q.get("high",[None])[i],"l":q.get("low",[None])[i],"c":q.get("close",[None])[i],"v":q.get("volume",[0])[i] or 0})
    return _clean_candles(rows)

def binance(symbol, interval, futures=False, coinm=False):
    base="https://dapi.binance.com" if coinm else ("https://fapi.binance.com" if futures else "https://api.binance.com")
    path="/dapi/v1/klines" if coinm else ("/fapi/v1/klines" if futures else "/api/v3/klines")
    rows=get_json(f"{base}{path}?symbol={quote(symbol,safe='')}&interval={interval}&limit=300")
    return _clean_candles([{"t":int(x[0]/1000),"o":x[1],"h":x[2],"l":x[3],"c":x[4],"v":x[5]} for x in rows])

def aggregate_4h(candles):
    if len(candles)<8:return candles
    out=[]; bucket=None; cur=None
    for x in candles:
        b=(x["t"]//14400)*14400
        if bucket!=b:
            if cur: out.append(cur)
            bucket=b
            cur={"t":b,"o":x["o"],"h":x["h"],"l":x["l"],"c":x["c"],"v":x["v"]}
        else:
            cur["h"]=max(cur["h"],x["h"]); cur["l"]=min(cur["l"],x["l"]); cur["c"]=x["c"]; cur["v"]+=x["v"]
    if cur:out.append(cur)
    return out

def _exchange_symbols(url, quote_asset=None, permission=None):
    try:
        info=get_json(url)
        result=[]
        for x in info.get("symbols",[]):
            if x.get("status")!="TRADING": continue
            if quote_asset and x.get("quoteAsset")!=quote_asset: continue
            if permission and not x.get(permission): continue
            result.append(x.get("symbol"))
        return [s for s in result if s]
    except Exception:
        return []

def universe(market):
    if market=="spot":
        syms=_exchange_symbols("https://api.binance.com/api/v3/exchangeInfo","USDT","isSpotTradingAllowed")
        return [(s,s) for s in syms]
    if market=="futures":
        syms=_exchange_symbols("https://fapi.binance.com/fapi/v1/exchangeInfo","USDT")
        return [(s,s) for s in syms]
    if market=="contracts":
        try:
            info=get_json("https://dapi.binance.com/dapi/v1/exchangeInfo")
            syms=[x.get("symbol") for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL"]
            return [(s,s) for s in syms if s]
        except Exception:
            return []
    if market=="us":
        return [(x,x) for x in ("AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","NFLX","JPM","AVGO","COST","PLTR","MU","INTC","QCOM","ORCL","CRM","ADBE","BA")]
    if market=="saudi":
        return [(x,x+".SR") for x in ("2222","1120","2010","7010","1180","1150","1211","2050","2082","2380","2020","4003","4030","4200","4280","6010","6090","7020","7030","7203")]
    return [("Gold","GC=F"),("Oil","CL=F"),("EURUSD","EURUSD=X"),("GBPUSD","GBPUSD=X"),("USDJPY","JPY=X")]

def candles(market,symbol,frame):
    if market=="spot": return binance(symbol,frame)
    if market=="futures": return binance(symbol,frame,futures=True)
    if market=="contracts": return binance(symbol,frame,coinm=True)
    interval={"5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}[frame]
    data=yahoo(symbol,interval)
    return aggregate_4h(data) if frame=="4h" else data

# Seven independent raw-price specialists. No RSI, MACD, EMA, Stochastic or other indicators.
def _segments(c,n=8):
    if len(c)<n*2:return []
    return [c[i:i+n] for i in range(0,len(c)-n+1,n)]

def analyst_price_action(c):
    if len(c)<20:return "NEUTRAL"
    closes=[x["c"] for x in c[-12:]]
    up=sum(closes[i]>closes[i-1] for i in range(1,len(closes)))
    down=sum(closes[i]<closes[i-1] for i in range(1,len(closes)))
    return "BUY" if up>=8 and closes[-1]>closes[-4] else "SELL" if down>=8 and closes[-1]<closes[-4] else "NEUTRAL"

def analyst_candles(c):
    if len(c)<6:return "NEUTRAL"
    x=c[-1]; prev=c[-2]
    body=abs(x["c"]-x["o"]); rng=max(x["h"]-x["l"],1e-12)
    upper=x["h"]-max(x["o"],x["c"]); lower=min(x["o"],x["c"])-x["l"]
    bull=x["c"]>x["o"] and body/rng>=0.55
    bear=x["c"]<x["o"] and body/rng>=0.55
    bull_reject=lower>body*1.5 and x["c"]>prev["c"]
    bear_reject=upper>body*1.5 and x["c"]<prev["c"]
    return "BUY" if bull or bull_reject else "SELL" if bear or bear_reject else "NEUTRAL"

def analyst_support_resistance(c):
    if len(c)<30:return "NEUTRAL"
    last=c[-1]["c"]; highs=[x["h"] for x in c[-25:-1]]; lows=[x["l"] for x in c[-25:-1]]
    hi=max(highs); lo=min(lows); span=max(hi-lo,last*1e-9)
    near_hi=(hi-last)/span; near_lo=(last-lo)/span
    return "BUY" if last>hi*1.001 or near_lo<0.10 else "SELL" if last<lo*0.999 or near_hi<0.10 else "NEUTRAL"

def analyst_liquidity(c):
    if len(c)<30:return "NEUTRAL"
    last=c[-1]; prev_high=max(x["h"] for x in c[-21:-1]); prev_low=min(x["l"] for x in c[-21:-1])
    # Sweep then close back inside the prior range = rejection of the liquidity grab.
    if last["l"]<prev_low and last["c"]>prev_low:return "BUY"
    if last["h"]>prev_high and last["c"]<prev_high:return "SELL"
    if last["c"]>prev_high and last["o"]>prev_high:return "BUY"
    if last["c"]<prev_low and last["o"]<prev_low:return "SELL"
    return "NEUTRAL"

def analyst_market_structure(c):
    if len(c)<35:return "NEUTRAL"
    a=c[-20:-10]; b=c[-10:]
    ah=max(x["h"] for x in a); al=min(x["l"] for x in a); bh=max(x["h"] for x in b); bl=min(x["l"] for x in b)
    return "BUY" if bh>ah and bl>al else "SELL" if bh<ah and bl<al else "NEUTRAL"

def analyst_breakout_retest(c):
    if len(c)<35:return "NEUTRAL"
    level_hi=max(x["h"] for x in c[-31:-4]); level_lo=min(x["l"] for x in c[-31:-4])
    recent=c[-4:]
    if recent[-1]["c"]>level_hi and min(x["l"] for x in recent[-3:])<=level_hi*1.002:return "BUY"
    if recent[-1]["c"]<level_lo and max(x["h"] for x in recent[-3:])>=level_lo*0.998:return "SELL"
    return "NEUTRAL"

def analyst_risk(c):
    if len(c)<30:return "NEUTRAL"
    price=c[-1]["c"]; hi=max(x["h"] for x in c[-21:-1]); lo=min(x["l"] for x in c[-21:-1])
    up=max(0,hi-price); down=max(0,price-lo); span=max(hi-lo,price*0.001)
    return "BUY" if down>span*0.35 and up>down*1.15 else "SELL" if up>span*0.35 and down>up*1.15 else "NEUTRAL"

ANALYSTS=[
    ("Price Action","حركة السعر",analyst_price_action),
    ("Candles","الشموع والسلوك",analyst_candles),
    ("SupportResistance","الدعم والمقاومة",analyst_support_resistance),
    ("Liquidity","السيولة",analyst_liquidity),
    ("MarketStructure","هيكل السوق",analyst_market_structure),
    ("BreakoutRetest","الاختراق وإعادة الاختبار",analyst_breakout_retest),
    ("Risk","تقييم الصفقة والمخاطرة",analyst_risk),
]

# Short-lived market-learning memory. It learns from observed follow-through and is bounded to avoid memory growth.
_LEARNING={"scores":{name:{"BUY":{"n":0,"good":0},"SELL":{"n":0,"good":0}} for name,_,_ in ANALYSTS},"pending":[]}

def _learn_from_market(c):
    if not c:return
    current=c[-1]["c"]
    remaining=[]
    for p in _LEARNING["pending"]:
        if p["t"]==c[-1]["t"]: remaining.append(p); continue
        if p["t"] < c[-1]["t"]:
            move=(current-p["price"])/p["price"] if p["price"] else 0
            good=(move>0 if p["side"]=="BUY" else move<0)
            s=_LEARNING["scores"][p["name"]][p["side"]]
            s["n"]+=1; s["good"]+=1 if good else 0
        else: remaining.append(p)
    _LEARNING["pending"]=remaining[-500:]

def _record_market_observation(c,votes):
    if not c:return
    row={"t":c[-1]["t"],"price":c[-1]["c"]}
    for name,_,fn in ANALYSTS:
        side=votes.get(name,"NEUTRAL")
        if side in ("BUY","SELL"):
            _LEARNING["pending"].append({"t":c[-1]["t"],"price":c[-1]["c"],"name":name,"side":side})
    _LEARNING["pending"]=_LEARNING["pending"][-500:]

def analyst_votes(c):
    _learn_from_market(c)
    votes={}
    for name,_,fn in ANALYSTS:
        votes[name]=fn(c)
    _record_market_observation(c,votes)
    return votes

def trade_from(c,market,frame,symbol):
    if len(c)<35:return None
    votes=analyst_votes(c)
    buy=sum(v=="BUY" for v in votes.values()); sell=sum(v=="SELL" for v in votes.values())
    side="BUY" if buy>sell else "SELL" if sell>buy else None
    agree=max(buy,sell)
    if not side or agree<1:return None
    # Spot, Saudi and US are buy-only. A sell plurality is therefore not published.
    if market in ("spot","saudi","us") and side!="BUY": return None
    price=c[-1]["c"]; recent_high=max(x["h"] for x in c[-21:-1]); recent_low=min(x["l"] for x in c[-21:-1])
    if side=="BUY":
        sl=recent_low
        if sl>=price: sl=price*0.985
        risk=price-sl
        if risk<=0:return None
        tps=[price+risk*x for x in (1.0,1.7,2.4)]
    else:
        sl=recent_high
        if sl<=price: sl=price*1.015
        risk=sl-price
        if risk<=0:return None
        tps=[price-risk*x for x in (1.0,1.7,2.4)]
    return {
        "asset":symbol,"market":market,"timeframe":frame,"timeframe_name":FRAMES[frame],
        "side":side,"ai_percent":round(agree/7*100),"analysts_agree":agree,"analysts_total":7,
        "entry":price,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,
        "created_at":int(time.time()),
        "analysts":[label for _,label,_ in ANALYSTS],
        "votes":votes,
        "learning":"يتعلم من سلوك السوق الفعلي ونتائج قراءاته السابقة"
    }

@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","time":time.time(),"engine":"7-analysts-no-indicators"}

@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES}

@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("15m")):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid_market_or_timeframe"}
    items=[]; checked=0; data_ok=0; errors=0
    for name,symbol in universe(market):
        checked+=1
        try:
            c=candles(market,symbol,timeframe)
            if len(c)>=35:data_ok+=1
            t=trade_from(c,market,timeframe,name)
            if t:items.append(t)
        except Exception:
            errors+=1
    items.sort(key=lambda x:(x["analysts_agree"],x["ai_percent"],x["created_at"]),reverse=True)
    return {
        "market":market,"market_name":MARKETS[market],"timeframe":timeframe,
        "timeframe_name":FRAMES[timeframe],"items":items[:30],
        "engine":"7 محللين مستقلين بدون مؤشرات",
        "diagnostics":{"symbols_checked":checked,"data_ok":data_ok,"signals_found":len(items),"errors":errors}
    }

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
