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
FRAME_SECONDS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}
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
    # A published signal is stored and remains visible until its own timeframe expires.
    stored=_stored_trades(market,timeframe)
    stored_keys={_trade_store_key(x) for x in stored}
    for name,symbol in universe(market):
        checked+=1
        try:
            c=candles(market,symbol,timeframe)
            if len(c)<40:continue
            ok+=1
            key=f"{market}:{name}:{timeframe}"
            if key in stored_keys:
                t=next(x for x in stored if _trade_store_key(x)==key)
            else:
                t=trade(c,market,timeframe,name)
                if t:t=_store_trade_until_frame_end(t)
            if t:
                items.append(t)
                _register_trade(t)
        except Exception:
            errors+=1
    items.sort(key=lambda x:(x["analysts_agree"],x["ai_percent"]),reverse=True)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"timeframe_name":FRAMES[timeframe],
            "items":items[:30],"checked":checked,"data_ok":ok,"signals_found":len(items),"errors":errors,
            "indicators":False,"engine":"7 محللين مستقلين بدون مؤشرات","storage":"الصفقة محفوظة حتى انتهاء الفريم"}


@app.get("/api/scanner")
def scanner():return {"items":[],"message":"الماسح يعتمد على محرك الأسواق"}

TRACKER={"open":{},"closed":[]}
TRADE_STORE_PATH=BASE/"trade_state.json"

def _load_trade_store():
    try:
        if TRADE_STORE_PATH.exists():
            data=json.loads(TRADE_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data,dict) and isinstance(data.get("active"),dict):
                return data
    except Exception:
        pass
    return {"active":{}}

TRADE_STORE=_load_trade_store()

def _save_trade_store():
    try:
        tmp=TRADE_STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(TRADE_STORE,ensure_ascii=False),encoding="utf-8")
        tmp.replace(TRADE_STORE_PATH)
    except Exception:
        pass

def _trade_store_key(x):
    return f"{x.get('market')}:{x.get('asset')}:{x.get('timeframe')}"

def _purge_expired_trades(now=None):
    now=int(now or time.time())
    changed=False
    for k,x in list(TRADE_STORE["active"].items()):
        if int(x.get("expires_at",0))<=now:
            del TRADE_STORE["active"][k]
            changed=True
    if changed:_save_trade_store()

def _store_trade_until_frame_end(x):
    now=int(time.time())
    key=_trade_store_key(x)
    _purge_expired_trades(now)
    existing=TRADE_STORE["active"].get(key)
    if existing and int(existing.get("expires_at",0))>now:
        return existing
    stored=dict(x)
    stored["stored_at"]=now
    stored["expires_at"]=now+FRAME_SECONDS.get(x["timeframe"],900)
    stored["storage"]="until_timeframe_end"
    TRADE_STORE["active"][key]=stored
    _save_trade_store()
    return stored

def _stored_trades(market,frame):
    _purge_expired_trades()
    return [x for x in TRADE_STORE["active"].values() if x.get("market")==market and x.get("timeframe")==frame]

def _tracker_key(x):
    return f"{x.get('market')}:{x.get('asset')}:{x.get('timeframe')}"

def _register_trade(x):
    k=_tracker_key(x)
    if k not in TRACKER["open"]:
        TRACKER["open"][k]=dict(x,status="OPEN",result=None,hit=None,checked_at=int(time.time()))

def _tracker_symbol(x):
    if x["market"]=="saudi": return x["asset"]+".SR"
    return x["asset"]

def _evaluate_tracker_trade(x):
    try:
        c=candles(x["market"],_tracker_symbol(x),x["timeframe"])
        if not c:return None
        for bar in c:
            if bar["t"]<=x["created_at"]: continue
            if x["side"]=="BUY":
                if bar["l"]<=x["sl"]: return ("LOSS","SL")
                if bar["h"]>=x["tp3"]: return ("WIN","TP3")
                if bar["h"]>=x["tp2"]: return ("WIN","TP2")
                if bar["h"]>=x["tp1"]: return ("WIN","TP1")
            else:
                if bar["h"]>=x["sl"]: return ("LOSS","SL")
                if bar["l"]<=x["tp3"]: return ("WIN","TP3")
                if bar["l"]<=x["tp2"]: return ("WIN","TP2")
                if bar["l"]<=x["tp1"]: return ("WIN","TP1")
    except Exception:
        return None
    return None


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
    for k,x in list(TRACKER["open"].items()):
        result=_evaluate_tracker_trade(x)
        if result:
            status,hit=result
            TRACKER["closed"].append(dict(x,status="CLOSED",result=status,hit=hit,closed_at=int(time.time())))
            del TRACKER["open"][k]
    wins=sum(1 for x in TRACKER["closed"] if x["result"]=="WIN")
    losses=sum(1 for x in TRACKER["closed"] if x["result"]=="LOSS")
    total=wins+losses
    return {"open":list(TRACKER["open"].values())[-100:],"closed":TRACKER["closed"][-100:],
            "stats":{"wins":wins,"losses":losses,"total":total,"win_rate":round(wins/total*100,2) if total else 0}}


@app.get("/api/account")
def account():return {"authenticated":False}

@app.get("/api/admin")
def admin():return {"ok":True}

NEWS=[
{"id":1,"title":"ملخص الأسواق: لماذا تختلف حركة السعر من فريم إلى آخر؟","category":"أسواق","date":"2026-09-28","summary":"قراءة مستقلة للفريمات تساعد على فصل الحركة القصيرة عن السياق الأكبر.","body":"كل فريم يعرض جزءاً مختلفاً من حركة السوق. لذلك لا يفترض أن تتطابق الإشارة في 5 دقائق مع اليومية. في المنصة يتم التعامل مع كل فريم كقراءة مستقلة."},
{"id":2,"title":"الأمريكي: متابعة حركة الأسهم والسيولة","category":"الأمريكي","date":"2026-09-28","summary":"متابعة الأسهم الأمريكية المتاحة من مصدر البيانات قبل نشر أي إشارة.","body":"البيانات المتاحة هي الأساس. إذا لم تتوفر بيانات موثوقة أو كانت ناقصة، لا يتم اختلاق صفقة. أي نتيجة منشورة تعتمد على السعر الخام المتاح وقت التحليل."},
{"id":3,"title":"السعودي: قراءة حركة السوق بدون مؤشرات","category":"السعودي","date":"2026-09-28","summary":"التركيز على القمم والقيعان والإغلاق ومناطق التفاعل.","body":"التحليل هنا يعتمد على حركة السعر الخام وسلوك الإغلاق والمناطق السعرية، وليس على RSI أو MACD أو المتوسطات."},
{"id":4,"title":"السبوت والفيوتشر: اختلاف طبيعة السوق يغيّر القراءة","category":"كريبتو","date":"2026-09-28","summary":"الأسواق المختلفة تحتاج بياناتها ومصدرها الخاص قبل المقارنة.","body":"لا ينبغي استخدام مصدر بيانات واحد لجميع الأسواق. لذلك يتم فصل بيانات السبوت عن الفيوتشر والعقود حتى تكون قراءة كل قسم مستقلة."},
{"id":5,"title":"إدارة المخاطر في الأسواق السريعة","category":"مخاطر","date":"2026-09-28","summary":"الوقف والأهداف جزء من الخطة وليسا ضماناً للنتيجة.","body":"في الأسواق السريعة قد يحدث انزلاق سعري وتنفيذ مختلف عن السعر المتوقع. لذلك يجب التعامل مع كل صفقة كمعلومة تحليلية وليست وعداً بالربح."},
{"id":6,"title":"متى نوقف نشر الإشارات؟","category":"منهجية","date":"2026-09-28","summary":"جودة البيانات أهم من كثرة الصفقات.","body":"عند تعطل المصدر أو نقص الشموع أو وجود بيانات غير صالحة، الأفضل إيقاف الإشارة مؤقتاً بدلاً من نشر نتيجة غير موثوقة."}
]

BLOG=[
{"id":1,"title":"كيف تقرأ حركة السعر قبل الدخول في الصفقة","category":"أساسيات التداول","date":"2026-09-28","summary":"منهج عملي لفهم الاتجاه والقوة والرفض من السعر الخام.","body":"ابدأ بقراءة القمم والقيعان والإغلاقات ومناطق التفاعل. لا تحتاج إلى مؤشرات حتى تعرف هل الحركة مستمرة أم تفقد قوتها. راقب أين يغلق السعر بالنسبة إلى نطاقه، وهل يحافظ على القمم والقيعان الجديدة."},
{"id":2,"title":"الدعم والمقاومة: كيف تحدد المنطقة وليس الخط","category":"حركة السعر","date":"2026-09-28","summary":"لماذا تتعامل مع الدعم والمقاومة كمناطق تفاعل.","body":"السعر لا يحترم دائماً رقماً واحداً. ابحث عن مناطق تكرر عندها الرفض أو القبول، ثم راقب ما يحدث عندما يعود السعر إليها. تحول المقاومة إلى دعم أو العكس يصبح أكثر أهمية عندما يؤكده سلوك السعر."},
{"id":3,"title":"الاختراق الحقيقي والاختراق الكاذب","category":"اختراقات","date":"2026-09-28","summary":"علامات تساعدك على التفريق بين الاختراق والاستدراج.","body":"لا يكفي أن يلمس السعر مستوى سابقاً. راقب الإغلاق خارج المنطقة، ثم سلوك السعر عند إعادة الاختبار. العودة السريعة داخل النطاق بعد الاختراق قد تكون علامة على فشل الحركة، بينما الثبات خارج المنطقة يعطي سياقاً مختلفاً."},
{"id":4,"title":"السيولة وسحب السيولة في حركة السعر","category":"السيولة","date":"2026-09-28","summary":"فهم مناطق القمم والقيعان التي قد يتجمع حولها الطلب والعرض.","body":"القمم والقيعان الواضحة تجذب الانتباه لأنها مناطق يتوقع عندها المتداولون أوامر ووقفات. عندما يخترق السعر قمة أو قاعاً ثم يعود ويغلق داخل المنطقة، راقب ذلك كسلوك رفض وليس كاختراق مؤكد."},
{"id":5,"title":"هيكل السوق: القمم والقيعان أهم من الضوضاء","category":"هيكل السوق","date":"2026-09-28","summary":"طريقة بسيطة لفهم استمرار الاتجاه أو تغيره.","body":"قارن مجموعات القمم والقيعان بدلاً من التركيز على شمعة واحدة. ارتفاع القمم والقيعان يشير إلى بنية صاعدة، وانخفاضها يشير إلى بنية هابطة، أما التداخل الكبير فيعني أن السوق قد يكون في مرحلة تذبذب."},
{"id":6,"title":"إدارة المخاطر: أين تضع نقطة إلغاء الفكرة؟","category":"إدارة المخاطر","date":"2026-09-28","summary":"الوقف ليس رقماً عشوائياً بل نقطة يصبح عندها سيناريو الصفقة غير صالح.","body":"قبل الدخول حدد المستوى الذي إذا وصل إليه السعر تصبح فكرتك غير صحيحة. لا تجعل الهدف هو العامل الوحيد في القرار. أوامر الوقف قد تنفذ بسعر مختلف عن سعر الوقف في الأسواق السريعة، لذلك يجب فهم مخاطر التنفيذ والسيولة."},
{"id":7,"title":"لماذا لا توجد صفقة أحياناً؟","category":"منهجية","date":"2026-09-28","summary":"عدم التداول قرار صحيح عندما تكون البيانات متضاربة أو ناقصة.","body":"ليس مطلوباً أن ينتج السوق صفقة كل دقيقة. عندما تختلف قراءات حركة السعر أو لا تتوفر بيانات كافية، الانتظار أفضل من اختراع إشارة. التداول قصير الأجل يحمل مخاطر مرتفعة، خصوصاً مع الرافعة المالية."},
{"id":8,"title":"كيف تقرأ الشمعة بدون مؤشرات","category":"الشموع","date":"2026-09-28","summary":"الجسم والظلال والإغلاق تعطي معلومات عن سلوك السعر.","body":"قارن حجم جسم الشمعة بنطاقها، وانظر إلى مكان الإغلاق والظلال. شمعة ذات إغلاق قوي قرب أحد طرفي النطاق تختلف عن شمعة أغلقت بعد رفض واضح من مستوى سعري."},
{"id":9,"title":"من الفريم الكبير إلى الفريم الصغير","category":"الفريمات","date":"2026-09-28","summary":"تنظيم القراءة بين الشهري والأسبوعي واليومي والفريمات الأقصر.","body":"ابدأ بالسياق العام ثم انتقل للفريم الذي تريد التداول عليه. لا تجعل حركة صغيرة تلغي السياق الأكبر مباشرة؛ ابحث عن نقطة واضحة تتغير عندها بنية السوق."},
{"id":10,"title":"كيف تقيس جودة الصفقة بدون وعود بالربح","category":"منهجية","date":"2026-09-28","summary":"تقييم الصفقة بناءً على وضوح الفكرة والمخاطرة وليس ضمان النتيجة.","body":"جودة التحليل لا تعني ضمان الربح. قيّم وضوح الاتجاه، نقطة إلغاء الفكرة، المسافة إلى الأهداف، وسلوك السعر بعد الدخول. كل استثمار يحمل درجة من المخاطرة."}
]

@app.get("/api/news")
def news():return {"items":NEWS}
@app.get("/api/news/{item_id}")
def news_item(item_id:int):return next((x for x in NEWS if x["id"]==item_id),{"error":"not_found"})
@app.get("/api/blog")
def blog():return {"items":BLOG}
@app.get("/api/blog/{item_id}")
def blog_item(item_id:int):return next((x for x in BLOG if x["id"]==item_id),{"error":"not_found"})
