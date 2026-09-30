import os,time,sqlite3,asyncio
from typing import Optional
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse

ROOT=Path(__file__).parent
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"

TFS=["5m","15m","1h","4h","1d","1w","1M"]
PIPELINE_TFS=["5m","15m","1h","4h","1d","1w","1M"]
EXCLUDE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","BUSDUSDT"}
MARKETS={
 "crypto_spot":{"name":"سبوت","provider":"binance","symbols":[]},
 "crypto_futures":{"name":"فيوتشر","provider":"binance_futures","symbols":[]},
 "us":{"name":"الأمريكي","provider":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","AMD","NFLX","JPM","WMT","COST","QQQ","SPY"]},
 "us_options":{"name":"الخيارات الأمريكية","provider":"yahoo_options","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","SPY","QQQ"]},
 "saudi":{"name":"السعودي","provider":"yahoo","symbols":["2222.SR","1120.SR","2010.SR","1180.SR","1150.SR","1211.SR","2082.SR","7010.SR","7020.SR","2380.SR"]},
 "forex":{"name":"الفوركس","provider":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F"]}
}

app=FastAPI(title="التداول الذكي PRO",version="9.0")

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT,symbol TEXT,tf TEXT,side TEXT,
      entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,
      status TEXT DEFAULT 'OPEN',pnl REAL DEFAULT 0,created INTEGER,closed INTEGER,source TEXT)""")
    c.commit(); return c


import secrets,hashlib,hmac,json,datetime

def now_ts(): return int(time.time())

def hash_password(password,salt=None):
    salt=salt or secrets.token_hex(16)
    dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000)
    return salt+":"+dk.hex()

def verify_password(password,stored):
    try:
        salt,_=stored.split(":",1)
        return hmac.compare_digest(hash_password(password,salt),stored)
    except Exception:return False

async def req(url,params=None):
    async with httpx.AsyncClient(timeout=15,headers={"User-Agent":"Mozilla/5.0"}) as x:
        r=await x.get(url,params=params); r.raise_for_status(); return r.json()

async def universe(futures=False):
    base="https://fapi.binance.com" if futures else "https://api.binance.com"
    path="/fapi/v1/ticker/24hr" if futures else "/api/v3/ticker/24hr"
    rows=await req(base+path)
    rows=[r for r in rows if r["symbol"].endswith("USDT") and r["symbol"] not in EXCLUDE and float(r.get("quoteVolume",0))>=1000000]
    return sorted(rows,key=lambda r:float(r.get("quoteVolume",0)),reverse=True)[:35]

def closes_volumes(raw,market):
    if market.startswith("crypto"):
        return [float(x[4]) for x in raw],[float(x[7]) for x in raw]
    q=raw.get("indicators",{}).get("quote",[{}])[0]
    return [float(x) for x in q.get("close",[]) if x is not None],[float(x or 0) for x in q.get("volume",[])]

async def market_candles(market,symbol,tf):
    if market=="crypto_spot":
        return await req("https://api.binance.com/api/v3/klines",{"symbol":symbol,"interval":tf,"limit":240})
    if market=="crypto_futures":
        return await req("https://fapi.binance.com/fapi/v1/klines",{"symbol":symbol,"interval":tf,"limit":240})
    sec={"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}[tf]
    now=int(time.time())
    period1=now-sec*240
    interval="1mo" if tf=="1M" else tf
    j=await req("https://query1.finance.yahoo.com/v8/finance/chart/"+symbol,{"period1":period1,"period2":now,"interval":interval})
    result=(j.get("chart",{}).get("result") or [None])[0]
    if not result: return {}
    return result

def ema(a,n):
    if len(a)<n:return None
    e=sum(a[:n])/n; k=2/(n+1)
    for v in a[n:]: e=v*k+e*(1-k)
    return e

def atr(h,l,c,n=14):
    if len(c)<n+1:return None
    tr=[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sum(tr[-n:])/n

def pivots(h,l,left=3,right=3):
    sh=[];sl=[]
    for i in range(left,len(h)-right):
        if h[i]==max(h[i-left:i+right+1]): sh.append(i)
        if l[i]==min(l[i-left:i+right+1]): sl.append(i)
    return sh,sl

def fvg_zone(h,l,bias):
    for i in range(len(h)-1,2,-1):
        if bias=="BUY" and l[i]>h[i-2]:
            return (h[i-2],l[i],"FVG")
        if bias=="SELL" and h[i]<l[i-2]:
            return (h[i],l[i-2],"FVG")
    return None

def structure_bias(c,h,l):
    e=ema(c,200) or ema(c,min(100,len(c)-1))
    sh,sl=pivots(h,l)
    last= c[-1]
    bullish=bool(e and last>e)
    bearish=bool(e and last<e)
    if len(sh)>=2 and len(sl)>=2:
        bullish=bullish and h[sh[-1]]>=h[sh[-2]] and l[sl[-1]]>=l[sl[-2]]
        bearish=bearish and h[sh[-1]]<=h[sh[-2]] and l[sl[-1]]<=l[sl[-2]]
    if bullish:return "BUY"
    if bearish:return "SELL"
    return "NEUTRAL"

def poi_from_structure(c,h,l,bias):
    if bias not in ("BUY","SELL"): return None
    sh,sl=pivots(h,l)
    if bias=="BUY" and sh:
        level=h[sh[-1]]
        if c[-1]>level:
            for i in range(sh[-1]-1,max(-1,sh[-1]-12),-1):
                if c[i]<o_for_index(c,h,l,i):
                    lo=min(l[i],h[i]); hi=max(c[i],o_for_index(c,h,l,i))
                    zone=(lo,hi,"OB")
                    f=fvg_zone(h,l,bias)
                    return f or zone
    if bias=="SELL" and sl:
        level=l[sl[-1]]
        if c[-1]<level:
            for i in range(sl[-1]-1,max(-1,sl[-1]-12),-1):
                if c[i]>o_for_index(c,h,l,i):
                    lo=min(o_for_index(c,h,l,i),c[i]); hi=max(h[i],o_for_index(c,h,l,i))
                    zone=(lo,hi,"OB")
                    f=fvg_zone(h,l,bias)
                    return f or zone
    return fvg_zone(h,l,bias)

def o_for_index(c,h,l,i):
    # Candle-open approximation when provider payload is normalized to closes/highs/lows.
    return c[i-1] if i>0 else c[i]

def inside_zone(price,zone):
    if not zone:return False
    lo,hi,_=zone
    return lo*0.997<=price<=hi*1.003

def choch(c,h,l,bias):
    sh,sl=pivots(h,l,2,2)
    if bias=="BUY" and sh:
        return c[-1]>h[sh[-1]]
    if bias=="SELL" and sl:
        return c[-1]<l[sl[-1]]
    return False

def sweep(c,h,l,bias,look=20):
    if len(c)<look+3:return False
    hi=max(h[-look-2:-2]); lo=min(l[-look-2:-2])
    return (min(l[-3:])<lo and c[-1]>lo) if bias=="BUY" else (max(h[-3:])>hi and c[-1]<hi)

async def candles_for(market,symbol,tfs):
    sem=asyncio.Semaphore(6)
    async def one(tf):
        async with sem:
            try:
                raw=await market_candles(market,symbol,tf)
                if market.startswith("crypto"):
                    c=[float(x[4]) for x in raw]; h=[float(x[2]) for x in raw]; l=[float(x[3]) for x in raw]
                    v=[float(x[7]) for x in raw]
                else:
                    q=raw.get("indicators",{}).get("quote",[{}])[0]
                    c=[float(x) for x in q.get("close",[]) if x is not None]
                    h=[float(x) for x in q.get("high",[]) if x is not None]
                    l=[float(x) for x in q.get("low",[]) if x is not None]
                    v=[float(x or 0) for x in q.get("volume",[])]
                return tf,(c,h,l,v)
            except Exception:return tf,None
    return dict(await asyncio.gather(*[one(tf) for tf in tfs]))

def rsi(c,n=14):
    if len(c)<n+1:return None
    gains=[];losses=[]
    for i in range(1,len(c)):
        d=c[i]-c[i-1];gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[-n:])/n; al=sum(losses[-n:])/n
    if al==0:return 100.0
    return 100-(100/(1+(ag/al)))

def candle_parts(c,h,l,i):
    o=c[i-1] if i>0 else c[i]
    body=abs(c[i]-o); rng=max(h[i]-l[i],1e-12)
    upper=h[i]-max(o,c[i]); lower=min(o,c[i])-l[i]
    return o,body,rng,upper,lower

def engulfing(c,h,l,buy=True):
    if len(c)<3:return False
    o1,_,_,_,_=candle_parts(c,h,l,-2)
    o2,b2,_,_,_=candle_parts(c,h,l,-1)
    if buy:
        return c[-2]<o1 and c[-1]>o2 and c[-1]>=o1 and o2<=c[-2]
    return c[-2]>o1 and c[-1]<o2 and c[-1]<=o1 and o2>=c[-2]

def pinbar(c,h,l,buy=True):
    if len(c)<2:return False
    o,b,r,u,lo=candle_parts(c,h,l,-1)
    if buy:return lo>=max(b*2,r*0.45) and c[-1]>=o
    return u>=max(b*2,r*0.45) and c[-1]<=o

def bos(c,h,l,buy=True,look=20):
    if len(c)<look+2:return False
    if buy:return c[-1]>max(h[-look-1:-1])
    return c[-1]<min(l[-look-1:-1])

def fvg_signal(h,l,buy=True):
    if len(h)<4:return None
    for i in range(len(h)-1,2,-1):
        if buy and l[i]>h[i-2] and l[i-1]>=h[i-2]:
            return (h[i-2],l[i])
        if not buy and h[i]<l[i-2] and h[i-1]<=l[i-2]:
            return (h[i],l[i-2])
    return None

def risk_targets(c,h,l,buy,risk_mult=2):
    entry=c[-1]; a=atr(h,l,c) or abs(entry*0.003)
    if buy:
        sl=min(min(l[-5:]),entry-a); risk=entry-sl
        if risk<=0:return None
        tp1=entry+risk*risk_mult;tp2=entry+risk*3;tp3=entry+risk*5
    else:
        sl=max(max(h[-5:]),entry+a); risk=sl-entry
        if risk<=0:return None
        tp1=entry-risk*risk_mult;tp2=entry-risk*3;tp3=entry-risk*5
    return entry,tp1,tp2,tp3,sl,abs(tp1-entry)/risk

def independent_signal(market,symbol,tf,data):
    c,h,l,v=data
    if len(c)<30:return None
    p=c[-1]; rr=None; side=None; strategy="";reason="";risk_pct=0.5
    # 1M: macro investment — monthly BOS + EMA200 + strong close.
    if tf=="1M":
        e=ema(c,200); e=e or ema(c,min(50,len(c)-1))
        side="BUY" if e and p>e and bos(c,h,l,True,12) else "SELL" if e and p<e and bos(c,h,l,False,12) else None
        if side:
            strategy="Monthly BOS + EMA"
            reason="كسر هيكل شهري وإغلاق مؤيد للاتجاه"
            risk_pct=3.0
    # 1W: weekly BOS + EMA200 + FVG retest.
    elif tf=="1w":
        e=ema(c,200); e=e or ema(c,min(50,len(c)-1)); z=fvg_signal(h,l,p>= (e or p))
        buy=bool(e and p>e and bos(c,h,l,True,20) and z)
        sell=bool(e and p<e and bos(c,h,l,False,20) and z)
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="Weekly BOS + EMA200 + FVG"
            reason="كسر أسبوعي مع EMA200 وإعادة اختبار فجوة سيولة"
            risk_pct=3.0
    # 1D: RSI + EMA50/200 + reversal candle.
    elif tf=="1d":
        e50=ema(c,50);e200=ema(c,200);r=rsi(c)
        buy=bool(e50 and e200 and r is not None and p>e50>e200 and r>=50 and (pinbar(c,h,l,True) or engulfing(c,h,l,True)))
        sell=bool(e50 and e200 and r is not None and p<e50<e200 and r<=50 and (pinbar(c,h,l,False) or engulfing(c,h,l,False)))
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="Daily EMA50/200 + RSI + Reversal"
            reason="اتجاه يومي وتصحيح للمتوسط مع شمعة انعكاسية"
            risk_pct=2.0
    # 4H: order-block proxy + liquidity sweep + retest.
    elif tf=="4h":
        e=ema(c,200); sw_buy=len(c)>22 and min(l[-3:])<min(l[-22:-3]) and p>c[-2]
        sw_sell=len(c)>22 and max(h[-3:])>max(h[-22:-3]) and p<c[-2]
        buy=bool((not e or p>e) and sw_buy and (pinbar(c,h,l,True) or engulfing(c,h,l,True)))
        sell=bool((not e or p<e) and sw_sell and (pinbar(c,h,l,False) or engulfing(c,h,l,False)))
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="4H Order Block + Liquidity Sweep"
            reason="سحب سيولة وإعادة اختبار منطقة أمر محتملة"
            risk_pct=1.5
    # 1H: Asia range sweep / CHoCH proxy. Exact exchange sessions are provider-dependent.
    elif tf=="1h":
        hi=max(h[-10:-2]);lo=min(l[-10:-2])
        buy=l[-1]<lo and p>lo
        sell=h[-1]>hi and p<hi
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="1H Liquidity Sweep + CHoCH"
            reason="سحب قمة/قاع النطاق ثم عودة داخل النطاق"
            risk_pct=1.0
    # 15M: FVG fill after momentum expansion.
    elif tf=="15m":
        z=fvg_signal(h,l,True);zs=fvg_signal(h,l,False)
        buy=bool(z and l[-1]<=z[1] and p>z[0] and (p/c[-4]-1)>0.003)
        sell=bool(zs and h[-1]>=zs[0] and p<zs[1] and (p/c[-4]-1)<-0.003)
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="15M FVG + Momentum"
            reason="ملء FVG بعد اندفاع سعري واضح"
            risk_pct=0.75
    # 5M: EMA9/21 + RSI50 + momentum candle.
    elif tf=="5m":
        e9=ema(c,9);e21=ema(c,21);r=rsi(c)
        prev_e9=ema(c[:-1],9);prev_e21=ema(c[:-1],21)
        buy=bool(e9 and e21 and prev_e9 and prev_e21 and r is not None and prev_e9<=prev_e21 and e9>e21 and r>50 and c[-1]>c[-2])
        sell=bool(e9 and e21 and prev_e9 and prev_e21 and r is not None and prev_e9>=prev_e21 and e9<e21 and r<50 and c[-1]<c[-2])
        side="BUY" if buy else "SELL" if sell else None
        if side:
            strategy="5M EMA9/21 + RSI50"
            reason="تقاطع متوسطات مع اختراق RSI50 وشمعة زخم"
            risk_pct=0.5
    else:return None
    if not side:return None
    rt=risk_targets(c,h,l,side=="BUY",2)
    if not rt:return None
    entry,tp1,tp2,tp3,sl,rr=rt
    if rr<2:return None
    return {
      "market":market,"market_name":MARKETS[market]["name"],"symbol":symbol,"tf":tf,
      "side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
      "confidence":min(99,70+int(min(rr,5)*4)),"rr":round(rr,2),
      "state":"ENTERED","stage":"إشارة مستقلة","strategy":strategy,"reason":reason,
      "risk_pct":risk_pct,"duration":{"1M":"أشهر إلى سنة","1w":"أسابيع","1d":"أيام إلى أسبوعين","4h":"1-3 أيام","1h":"ساعات","15m":"30 دقيقة-ساعتين","5m":"دقائق"}.get(tf,""),
      "execution":{"tf":tf,"trigger":True},"independent":True,"reverse_strategy":False,
      "rsi":round(rsi(c),2) if rsi(c) is not None else None,
      "change":round((p/c[-2]-1)*100,2),"time":int(time.time())
    }

async def independent_scan(market,symbol):
    d=await candles_for(market,symbol,TFS)
    out=[]
    for tf in TFS:
        x=d.get(tf)
        if x:
            try:
                z=independent_signal(market,symbol,tf,x)
                if z: out.append(z)
            except Exception:
                pass
    return out

async def scan_all():
    jobs=[]
    for market in MARKETS:
        if market=="crypto_spot":
            syms=[x["symbol"] for x in await universe(False)]
        elif market=="crypto_futures":
            syms=[x["symbol"] for x in await universe(True)]
        else: syms=MARKETS[market]["symbols"]
        for s in syms: jobs.append((market,s))
    sem=asyncio.Semaphore(8)
    async def one(m,s):
        async with sem:
            try:return await independent_scan(m,s)
            except Exception:return []
    groups=await asyncio.gather(*[one(m,s) for m,s in jobs])
    return sorted([x for g in groups for x in g],key=lambda x:(x["tf"]=="5m",x["confidence"],x.get("rr") or 0),reverse=True)

def save(items):
    c=db()
    for x in items:
        if x.get("state")=="ENTERED" and x["confidence"]>=90:
            exists=c.execute("SELECT id FROM trades WHERE market=? AND symbol=? AND tf=? AND status='OPEN'",(x["market"],x["symbol"],x["tf"])).fetchone()
            if not exists:
                c.execute("""INSERT INTO trades(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,confidence,created,source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(x["market"],x["symbol"],x["tf"],x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x["sl"],x["confidence"],int(time.time()),"INDEPENDENT_TIMEFRAME_STRATEGIES"))
    c.commit();c.close()

async def loop():
    while True:
        try:
            z=await scan_all(); save(z); app.state.data={"at":int(time.time()),"items":z}; app.state.error=""
        except Exception as e: app.state.error=str(e)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start():
    app.state.data={"at":0,"items":[]};app.state.error="";asyncio.create_task(loop())

@app.get("/health")
async def health():
    return {"ok":True,"version":"9.0","engine":"INDEPENDENT_TIMEFRAME_STRATEGIES","pipeline":"1M|1W|1D|4H|1H|15M|5M_INDEPENDENT","execution":"PAPER_SAFE","independent_timeframes":TFS}


@app.post("/api/auth/register")
async def register(payload: dict):
    email=str(payload.get("email","")).strip().lower(); password=str(payload.get("password",""))
    if len(email)<5 or len(password)<8:return JSONResponse({"error":"invalid_credentials"},400)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(email,password_hash,created) VALUES(?,?,?)",(email,hash_password(password),now_ts()))
        c.commit(); uid=cur.lastrowid
        token=secrets.token_urlsafe(32); c.execute("INSERT INTO sessions VALUES(?,?,?)",(token,uid,now_ts()+2592000));c.commit()
        return {"ok":True,"token":token,"user":{"id":uid,"email":email,"role":"USER"}}
    except sqlite3.IntegrityError:return JSONResponse({"error":"email_exists"},409)
    finally:c.close()

@app.post("/api/auth/login")
async def login(payload: dict):
    c=db();u=c.execute("SELECT * FROM users WHERE email=? AND active=1",(str(payload.get("email","")).strip().lower(),)).fetchone()
    if not u or not verify_password(str(payload.get("password","")),u["password_hash"]):c.close();return JSONResponse({"error":"invalid_login"},401)
    token=secrets.token_urlsafe(32);c.execute("INSERT INTO sessions VALUES(?,?,?)",(token,u["id"],now_ts()+2592000));c.execute("UPDATE users SET last_login=? WHERE id=?",(now_ts(),u["id"]));c.commit();c.close()
    return {"ok":True,"token":token,"user":{"id":u["id"],"email":u["email"],"role":u["role"]}}

@app.get("/api/me")
async def me(token: Optional[str]=None):
    u=auth_user(token)
    return {"authenticated":bool(u),"user":({"id":u["id"],"email":u["email"],"role":u["role"]} if u else None)}

@app.get("/api/admin/overview")
async def admin_overview(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db();users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"];subs=c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='ACTIVE'").fetchone()["n"];signals=c.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"];trades=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];c.close()
    return {"users":users,"active_subscriptions":subs,"signals":signals,"trades":trades}

@app.post("/api/admin/signal")
async def admin_signal(payload: dict, token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    required=["market","symbol","tf","side","entry","tp1","tp2","tp3","sl"]
    if any(k not in payload for k in required):return JSONResponse({"error":"missing_fields"},400)
    c=db();cur=c.execute("""INSERT INTO signals(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,risk_pct,source,created,updated)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(payload["market"],payload["symbol"],payload["tf"],payload["side"],payload["entry"],payload["tp1"],payload["tp2"],payload["tp3"],payload["sl"],payload.get("risk_pct",0),"ADMIN",now_ts(),now_ts()));sid=cur.lastrowid;c.execute("INSERT INTO admin_logs(action,actor,meta,created) VALUES(?,?,?,?)",("CREATE_SIGNAL","admin",json.dumps({"signal_id":sid}),now_ts()));c.commit();c.close()
    x=dict(payload);x["signal_id"]=sid
    sent=await telegram_send(signal_text(x))
    c=db();c.execute("UPDATE signals SET telegram_sent=? WHERE id=?",(1 if sent else 0,sid));c.commit();c.close()
    return {"ok":True,"signal_id":sid,"telegram_sent":sent}

@app.post("/api/webhook/tradingview")
async def tradingview(payload: dict):
    secret=os.getenv("TRADINGVIEW_WEBHOOK_SECRET","")
    supplied=str(payload.get("secret",""))
    if not secret or not hmac.compare_digest(supplied,secret):return JSONResponse({"error":"unauthorized"},401)
    required=["market","symbol","tf","side","entry","tp1","tp2","tp3","sl"]
    if any(k not in payload for k in required):return JSONResponse({"error":"missing_fields"},400)
    c=db();cur=c.execute("""INSERT INTO signals(market,symbol,tf,side,entry,tp1,tp2,tp3,sl,risk_pct,source,created,updated)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(payload["market"],payload["symbol"],payload["tf"],payload["side"],payload["entry"],payload["tp1"],payload["tp2"],payload["tp3"],payload["sl"],payload.get("risk_pct",0),"TRADINGVIEW",now_ts(),now_ts()));sid=cur.lastrowid;c.commit();c.close()
    x=dict(payload);sent=await telegram_send(signal_text(x))
    c=db();c.execute("UPDATE signals SET telegram_sent=? WHERE id=?",(1 if sent else 0,sid));c.commit();c.close()
    return {"ok":True,"signal_id":sid,"telegram_sent":sent}

@app.get("/api/admin/signals")
async def admin_signals(token: Optional[str]=None):
    if not admin_ok(token):return JSONResponse({"error":"forbidden"},403)
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 200")];c.close();return rows

@app.get("/api/plans")
async def plans():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM plans WHERE active=1 ORDER BY price")];c.close();return rows

@app.get("/api/news")
async def news():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM news WHERE active=1 ORDER BY published DESC LIMIT 50")];c.close();return rows

@app.get("/api/articles")
async def articles():
    c=db();rows=[dict(x) for x in c.execute("SELECT * FROM articles WHERE active=1 ORDER BY published DESC LIMIT 50")];c.close();return rows

@app.get("/api/options")
async def options(symbol: str="NVDA"):
    if symbol not in MARKETS["us_options"]["symbols"]: return JSONResponse({"error":"unsupported_symbol"},400)
    try:
        j=await req("https://query1.finance.yahoo.com/v7/finance/options/"+symbol)
        r=(j.get("optionChain",{}).get("result") or [None])[0]
        if not r:return {"symbol":symbol,"calls":[],"puts":[]}
        chain=(r.get("options") or [{}])[0]
        def clean(row):
            return [{k:x.get(k) for k in ("contractSymbol","strike","lastPrice","bid","ask","volume","openInterest","impliedVolatility","delta","gamma","theta")} for x in row]
        return {"symbol":symbol,"expiration":chain.get("expirationDate"),"calls":clean(chain.get("calls",[])),"puts":clean(chain.get("puts",[]))}
    except Exception as e:return JSONResponse({"error":"options_data_unavailable","detail":str(e)},502)

@app.get("/api/markets")
async def markets(): return MARKETS

@app.get("/api/signals")
async def signals(market: Optional[str]=None,state: Optional[str]=None):
    if not app.state.data["items"] or time.time()-app.state.data["at"]>180:
        z=await scan_all();save(z);app.state.data={"at":int(time.time()),"items":z}
    items=[x for x in app.state.data["items"] if (not market or x["market"]==market) and (not state or x["state"]==state)]
    return {"updated":app.state.data["at"],"items":items,"timeframes":TFS,"execution_timeframe":"5m","markets":MARKETS,"min_volume":1000000,"strategies":["1M","1W","1D","4H","1H","15M","5M"],"independent":True}

@app.get("/api/pipeline")
async def pipeline_api(market: Optional[str]=None):
    items=app.state.data.get("items",[])
    return {"updated":app.state.data.get("at",0),"items":[x for x in items if not market or x["market"]==market],"strategies":["1M","1W","1D","4H","1H","15M","5M"],"independent":True,"reverse_strategy":False}

@app.get("/api/trades")
async def trades():
    c=db();z=[dict(x) for x in c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 100")];c.close();return z

@app.get("/api/stats")
async def stats():
    c=db();a=c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"];o=c.execute("SELECT COUNT(*) n FROM trades WHERE status='OPEN'").fetchone()["n"];p=c.execute("SELECT COALESCE(SUM(pnl),0) p FROM trades WHERE status='CLOSED'").fetchone()["p"];c.close();return {"total":a,"open":o,"closed":a-o,"pnl":round(p,4)}

@app.get("/api/settings")
async def settings():
    return {"mode":os.getenv("TRADING_MODE","PAPER").upper(),"execution_ready":False,"engine":"INDEPENDENT_TIMEFRAME_STRATEGIES","live_orders":False,"modules":["accounts","subscriptions","admin","markets","strategies","signals","telegram","news","blog"]}

@app.get("/")
async def home(): return FileResponse(ROOT/"static/index.html")

@app.get("/static/{name}")
async def static(name): return FileResponse(ROOT/"static"/name)

@app.exception_handler(Exception)
async def err(request,e): return JSONResponse({"error":"server_error","detail":str(e)},500)
