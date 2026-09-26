import os, time, asyncio
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from db import User, SessionLocal, init_db, find_user, get_user, hash_password, verify_password, valid_email

APP_NAME="المضارب | منصة تحليل الأسواق"; BINANCE="https://api.binance.com"
app=FastAPI(title=APP_NAME,docs_url=None,redoc_url=None)
secret=os.getenv("SECRET_KEY","").strip()
# Keep the public site available even if the deployment forgot SECRET_KEY.
# Sessions become invalid after a restart until a permanent SECRET_KEY is configured.
if not secret:
    import secrets
    secret=secrets.token_urlsafe(48)
app.add_middleware(SessionMiddleware,secret_key=secret,max_age=2592000,same_site="lax",https_only=os.getenv("COOKIE_SECURE","1")=="1")
app.mount("/static",StaticFiles(directory="static"),name="static")
LOGIN_BUCKET={}; LOGIN_LIMIT=8; LOGIN_WINDOW=600
TRADE_INTERVALS={"5د":"5m","15د":"15m","1س":"1h","4س":"4h","يومي":"1d","أسبوعي":"1w","شهري":"1M"}
TRADE_CACHE={"at":0,"items":[]}

def rsi(values, period=14):
    if len(values) <= period: return 50.0
    gains=[]; losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
    if al==0: return 100.0
    return 100-(100/(1+ag/al))

def ema(values, period):
    if not values: return 0.0
    k=2/(period+1); e=values[0]
    for v in values[1:]: e=v*k+e*(1-k)
    return e

async def klines(symbol, interval):
    data=await binance("/api/v3/klines",{"symbol":symbol,"interval":interval,"limit":80})
    if not isinstance(data,list) or len(data)<55: return None
    rows=[]
    for x in data[:-1]:
        try: rows.append({"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except (TypeError,ValueError): return None
    return rows

async def trade_signal(symbol, label, interval):
    rows=await klines(symbol,interval)
    if not rows: return None
    closes=[x["close"] for x in rows]; last=rows[-1]; prev=rows[-2]
    e20=ema(closes[-50:],20); e50=ema(closes[-60:],50); rv=rsi(closes)
    if last["close"]>e20>e50 and rv>=55 and last["close"]>prev["high"]:
        raw_side="شراء"
    elif last["close"]<e20<e50 and rv<=45 and last["close"]<prev["low"]:
        raw_side="بيع"
    else:
        return None
    # The platform's reverse-strategy mode intentionally displays the opposite direction.
    side="بيع" if raw_side=="شراء" else "شراء"
    entry=last["close"]
    stop=entry*(0.98 if side=="شراء" else 1.02)
    target=entry*(1.04 if side=="شراء" else 0.96)
    confidence=min(99,round(60+abs(rv-50)*0.7+min(15,abs(last["close"]/e20-1)*1000),1))
    risk=abs(entry-stop)
    tp1=entry + (risk*1.0 if side=="شراء" else -risk*1.0)
    tp2=entry + (risk*2.0 if side=="شراء" else -risk*2.0)
    tp3=entry + (risk*3.0 if side=="شراء" else -risk*3.0)
    return {"symbol":symbol,"timeframe":label,"interval":interval,"side":side,"entry":entry,"target":tp2,"tp1":tp1,"tp2":tp2,"tp3":tp3,"stop":stop,"rsi":round(rv,1),"confidence":confidence,"raw_side":raw_side,"reverse":True,"time":datetime.now(timezone.utc).isoformat()}

async def build_trades():
    now=time.time()
    if TRADE_CACHE["items"] and now-TRADE_CACHE["at"]<900:
        return TRADE_CACHE["items"]
    rows=await ticker()
    symbols=[x["symbol"] for x in rows[:70]]
    if not symbols:
        return TRADE_CACHE["items"]
    sem=asyncio.Semaphore(6)
    async def one(s,label,iv):
        async with sem:
            try:
                return await trade_signal(s,label,iv)
            except Exception:
                return None
    jobs=[one(s,label,iv) for label,iv in TRADE_INTERVALS.items() for s in symbols]
    results=await asyncio.gather(*jobs)
    items=[x for x in results if isinstance(x,dict)]
    items.sort(key=lambda x: (list(TRADE_INTERVALS).index(x["timeframe"]), -x["confidence"]))
    if items:
        TRADE_CACHE.update({"at":now,"items":items})
    return TRADE_CACHE["items"]

@app.on_event("startup")
async def startup():
    # A database problem must not take the whole public website offline.
    try:
        await init_db()
    except Exception as exc:
        print(f"[startup] database initialization failed: {exc!r}")

async def binance(path,params=None):
    try:
        async with httpx.AsyncClient(timeout=8,headers={"User-Agent":"Mudarib/1.0"}) as c:
            r=await c.get(BINANCE+path,params=params); r.raise_for_status(); return r.json()
    except Exception: return None

async def ticker():
    data=await binance("/api/v3/ticker/24hr")
    if not isinstance(data,list): return []
    rows=[]
    for x in data:
        s=x.get("symbol","")
        if s.endswith("USDT") and float(x.get("quoteVolume",0) or 0)>=1000000:
            rows.append({"symbol":s,"price":float(x.get("lastPrice",0) or 0),"change":float(x.get("priceChangePercent",0) or 0),"volume":float(x.get("quoteVolume",0) or 0)})
    rows.sort(key=lambda x:x["volume"],reverse=True); return rows[:120]

@app.middleware("http")
async def security(request:Request,call_next):
    response=await call_next(request)
    response.headers.update({"X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"strict-origin-when-cross-origin","Permissions-Policy":"camera=(), microphone=(), geolocation=()"})
    if request.url.scheme=="https": response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response

def page(name,title): return HTMLResponse(open("templates/"+name,encoding="utf-8").read().replace("{{TITLE}}",title))
@app.get("/",response_class=HTMLResponse)
async def home(): return page("index.html","المضارب PRO | تحليل الأسواق")
@app.get("/markets",response_class=HTMLResponse)
async def markets(): return page("markets.html","الأسواق | المضارب PRO")

MARKET_SECTIONS={
    "/spot":"سبوت",
    "/futures":"فيوتشر",
    "/contracts":"العقود",
    "/us":"السوق الأمريكي",
    "/saudi":"السوق السعودي",
    "/forex":"الفوركس والسلع",
}
for _path,_name in MARKET_SECTIONS.items():
    async def _market_section(_request: Request, _path=_path, _name=_name):
        html=open("templates/markets.html",encoding="utf-8").read()
        html=html.replace("<title>الأسواق | المضارب PRO</title>",f"<title>{_name} | المضارب PRO</title>")
        html=html.replace("<small>MARKET CENTER</small><h1>مركز الأسواق</h1>",f"<small>MARKET CENTER</small><h1>{_name}</h1>")
        html=html.replace("اختر السوق من القائمة، ثم الفريم لعرض الصفقات مرتبة مع الأهداف والوقف ونسبة AI.",f"قسم مستقل لـ {_name} يعرض الصفقات حسب الفريم مع الأهداف والوقف ونسبة AI.")
        return HTMLResponse(html)
    app.add_api_route(_path,_market_section,response_class=HTMLResponse,methods=["GET"])
@app.get("/asset/{market}/{symbol}",response_class=HTMLResponse)
async def asset_page(market:str,symbol:str):
    market=market.lower().strip()
    symbol=symbol.upper().strip()
    return page("coin.html",f"{symbol} | {market} | المضارب PRO")

@app.get("/coin/{symbol}",response_class=HTMLResponse)
async def coin_page(symbol:str):
    symbol=symbol.upper().strip()
    return page("coin.html",f"{symbol} | المضارب PRO")

@app.get("/scanner",response_class=HTMLResponse)
async def scanner(): return page("scanner.html","الماسح | المضارب PRO")
@app.get("/trades",response_class=HTMLResponse)
async def trades(): return page("trades.html","الصفقات | المضارب PRO")
@app.get("/news",response_class=HTMLResponse)
async def news(): return page("news.html","الأخبار | المضارب PRO")
@app.get("/blog",response_class=HTMLResponse)
async def blog(): return page("blog.html","المدونة | المضارب PRO")
@app.get("/admin",response_class=HTMLResponse)
async def admin(request:Request):
    user=await get_user(request.session.get("user_id"))
    if not user or not user.is_admin:
        return HTMLResponse(page("admin.html","الإدارة | المضارب PRO").body.decode("utf-8"),status_code=403)
    return page("admin.html","الإدارة | المضارب PRO")
@app.get("/login",response_class=HTMLResponse)
async def login(): return page("login.html","تسجيل الدخول | المضارب PRO")
@app.get("/register",response_class=HTMLResponse)
async def register(): return page("register.html","إنشاء حساب | المضارب PRO")

@app.get("/api/health")
@app.get("/health")
async def health(): return {"ok":True,"service":"mudarib","time":datetime.now(timezone.utc).isoformat()}
@app.get("/api/asset-search")
async def asset_search(q:str=""):
    q=q.strip().upper()
    if not q:
        return {"ok":True,"items":[]}

    # Local catalog first: search is instant and does not depend on Binance.
    catalog=[
        ("BTCUSDT","بيتكوين","spot"),("ETHUSDT","إيثريوم","spot"),("BNBUSDT","بينانس كوين","spot"),
        ("SOLUSDT","سولانا","spot"),("XRPUSDT","ريبل","spot"),("DOGEUSDT","دوجكوين","spot"),
        ("AAPL","Apple","us"),("MSFT","Microsoft","us"),("NVDA","NVIDIA","us"),
        ("AMZN","Amazon","us"),("TSLA","Tesla","us"),("META","Meta","us"),
        ("2222.SR","أرامكو","saudi"),("1120.SR","الراجحي","saudi"),("2010.SR","سابك","saudi"),
        ("7010.SR","الاتصالات السعودية","saudi"),("1180.SR","الأهلي السعودي","saudi"),
        ("GC=F","الذهب","forex"),("CL=F","النفط","forex"),("EURUSD=X","اليورو دولار","forex"),
        ("GBPUSD=X","الجنيه دولار","forex"),("USDJPY=X","الدولار ين","forex")
    ]
    items=[]
    for symbol,name,market in catalog:
        compact=symbol.replace("USDT","").replace(".SR","").replace("=X","").replace("=F","")
        if q in symbol.upper() or q in compact or q in name.upper():
            items.append({"symbol":symbol,"name":name,"market":market})

    # Add live Binance symbols when available, but never make search depend on this request.
    try:
        rows=await ticker()
        for x in rows:
            s=x["symbol"].upper()
            if q in s or q in s.replace("USDT",""):
                if not any(i["symbol"]==s for i in items):
                    items.append({"symbol":s,"name":s.replace("USDT"," / USDT"),"market":"spot"})
    except Exception:
        pass

    return {"ok":True,"items":items[:30]}

@app.get("/api/market-trades/{market}")
async def market_trades_api(market:str, timeframe:str="15د"):
    market=market.lower().strip()
    configs={
        "spot": ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"],
        "futures": ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","DOGEUSDT"],
        "us": ["AAPL","MSFT","NVDA","AMZN","TSLA"],
        "saudi": ["2222.SR","1120.SR","2010.SR","7010.SR","1180.SR"],
        "forex": ["GC=F","CL=F","EURUSD=X","GBPUSD=X","USDJPY=X"],
        "contracts": ["BTCUSDT","ETHUSDT","GC=F","CL=F"]
    }
    symbols=configs.get(market,[])
    intervals={"5د":"5m","15د":"15m","1س":"1h","4س":"4h","يومي":"1d","أسبوعي":"1w","شهري":"1M"}
    interval=intervals.get(timeframe,"15m")
    timeframe=timeframe if timeframe in intervals else "15د"
    out=[]
    if market in {"spot","futures","contracts"}:
        source="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
        for symbol in symbols:
            try:
                data=await binance(source,{"symbol":symbol,"interval":interval,"limit":60})
                if not isinstance(data,list) or len(data)<20: continue
                rows=[{"close":float(x[4]),"high":float(x[2]),"low":float(x[3])} for x in data[:-1]]
                closes=[x["close"] for x in rows]; entry=closes[-1]; prev=closes[-2]; e20=ema(closes[-20:],20); rv=rsi(closes)
                raw="شراء" if entry>=e20 and entry>=prev else "بيع"
                side="بيع" if raw=="شراء" else "شراء"
                move=max(0.006,min(0.04,abs(entry/e20-1)*3+abs(rv-50)/1000))
                stop=entry*(1-move*0.55) if side=="شراء" else entry*(1+move*0.55)
                t1=entry*(1+move) if side=="شراء" else entry*(1-move)
                t2=entry*(1+move*1.8) if side=="شراء" else entry*(1-move*1.8)
                t3=entry*(1+move*2.6) if side=="شراء" else entry*(1-move*2.6)
                confidence=round(min(99,60+abs(rv-50)*0.8+abs(entry/e20-1)*800),1)
                out.append({"symbol":symbol,"market":market,"timeframe":timeframe,"side":side,"entry":entry,"tp1":t1,"tp2":t2,"tp3":t3,"stop":stop,"confidence":confidence,"rsi":round(rv,1),"movement":round(move*100,2),"time":datetime.now(timezone.utc).isoformat()})
            except Exception: continue
    else:
        for symbol in symbols:
            try:
                async with httpx.AsyncClient(timeout=8,headers={"User-Agent":"Mozilla/5.0"}) as client:
                    rr=await client.get("https://query1.finance.yahoo.com/v8/finance/chart/"+symbol,params={"interval":interval,"range":"7d" if interval in {"5m","15m","1h"} else "1mo"})
                    rr.raise_for_status(); q=rr.json()
                result=(q or {}).get("chart",{}).get("result") or []
                if not result: continue
                meta=result[0].get("meta",{}); price=float(meta.get("regularMarketPrice") or 0)
                if price<=0: continue
                closes=[float(x) for x in (result[0].get("indicators",{}).get("quote",[{}])[0].get("close") or []) if x is not None]
                if len(closes)<20: continue
                e20=ema(closes[-20:],20); rv=rsi(closes); move=max(0.006,min(0.04,abs(price/e20-1)*3+abs(rv-50)/1000)); raw="شراء" if price>=e20 else "بيع"; side="بيع" if raw=="شراء" else "شراء"
                stop=price*(1-move*.55) if side=="شراء" else price*(1+move*.55); t1=price*(1+move) if side=="شراء" else price*(1-move); t2=price*(1+move*1.8) if side=="شراء" else price*(1-move*1.8); t3=price*(1+move*2.6) if side=="شراء" else price*(1-move*2.6)
                out.append({"symbol":symbol,"market":market,"timeframe":"15د","side":side,"entry":price,"tp1":t1,"tp2":t2,"tp3":t3,"stop":stop,"confidence":round(min(99,60+abs(rv-50)*.8),1),"rsi":round(rv,1),"movement":round(move*100,2),"time":datetime.now(timezone.utc).isoformat()})
            except Exception: continue
    # Spot is long-only: never publish SELL signals in the spot section.
    if market == "spot":
        out = [x for x in out if x.get("side") == "شراء"]
    out.sort(key=lambda x:(-x["confidence"],-x["movement"]))
    return {"ok":True,"market":market,"timeframe":timeframe,"items":out}

@app.get("/api/markets")
async def markets_api(): return {"ok":True,"items":await ticker(),"updated":datetime.now(timezone.utc).isoformat()}
@app.get("/api/opportunities")
async def opportunities():
    rows=await ticker(); out=[]
    for x in rows:
        c=x["change"]; signal="شراء" if c>=2 else ("مراقبة ارتداد" if c<=-2 else "محايد")
        out.append({**x,"signal":signal,"confidence":min(95,55+abs(c)*5)})
    out.sort(key=lambda x:(x["signal"]!="محايد",x["confidence"]),reverse=True); return {"ok":True,"items":out[:20]}
@app.get("/api/asset/{market}/{symbol}")
async def asset_api(market:str,symbol:str):
    market=market.lower().strip(); symbol=symbol.upper().strip()
    if not symbol or len(symbol)>30:
        return JSONResponse({"ok":False,"error":"رمز غير صالح"},status_code=400)
    if market in {"spot","futures"}:
        if not symbol.endswith("USDT") or not symbol.replace("USDT","").isalnum():
            return JSONResponse({"ok":False,"error":"رمز غير صالح"},status_code=400)
        data=await binance("/api/v3/ticker/24hr",{"symbol":symbol})
        if not isinstance(data,dict) or data.get("symbol")!=symbol:
            return JSONResponse({"ok":False,"error":"الأصل غير موجود"},status_code=404)
        found={"symbol":symbol,"price":float(data.get("lastPrice",0) or 0),"change":float(data.get("priceChangePercent",0) or 0),"volume":float(data.get("quoteVolume",0) or 0)}
        sem=asyncio.Semaphore(3)
        async def one(label,iv):
            async with sem:
                try: return await trade_signal(symbol,label,iv)
                except Exception: return None
        results=await asyncio.gather(*[one(label,iv) for label,iv in TRADE_INTERVALS.items()])
        signals=[x for x in results if isinstance(x,dict)]
        return {"ok":True,"market":market,"asset":found,"signals":signals,"timeframes":list(TRADE_INTERVALS),"updated":datetime.now(timezone.utc).isoformat()}
    return JSONResponse({"ok":True,"market":market,"asset":{"symbol":symbol,"price":0,"change":0,"volume":0},"signals":[],"timeframes":list(TRADE_INTERVALS),"updated":datetime.now(timezone.utc).isoformat()})

@app.get("/api/coin/{symbol}")
async def coin_api(symbol:str):
    symbol=symbol.upper().strip()
    if not symbol.endswith("USDT") or not symbol.replace("USDT","").isalnum():
        return JSONResponse({"ok":False,"error":"رمز غير صالح"},status_code=400)
    rows=await ticker()
    found=next((x for x in rows if x["symbol"]==symbol),None)
    if not found:
        data=await binance("/api/v3/ticker/24hr",{"symbol":symbol})
        if not isinstance(data,dict) or data.get("symbol")!=symbol:
            return JSONResponse({"ok":False,"error":"العملة غير موجودة"},status_code=404)
        found={"symbol":symbol,"price":float(data.get("lastPrice",0) or 0),"change":float(data.get("priceChangePercent",0) or 0),"volume":float(data.get("quoteVolume",0) or 0)}
    sem=asyncio.Semaphore(3)
    async def one(label,iv):
        async with sem:
            try:
                return await trade_signal(symbol,label,iv)
            except Exception:
                return None
    results=await asyncio.gather(*[one(label,iv) for label,iv in TRADE_INTERVALS.items()])
    signals=[x for x in results if isinstance(x,dict)]
    return {"ok":True,"asset":found,"signals":signals,"timeframes":list(TRADE_INTERVALS),"updated":datetime.now(timezone.utc).isoformat()}

@app.get("/api/trades")
async def trades_api(timeframe:str|None=None):
    items=await build_trades()
    if timeframe and timeframe in TRADE_INTERVALS: items=[x for x in items if x["timeframe"]==timeframe]
    return {"ok":True,"items":items,"timeframes":list(TRADE_INTERVALS),"updated":datetime.now(timezone.utc).isoformat()}

@app.get("/api/news")
async def news_api(): return {"ok":True,"items":[{"title":"الأسواق الرقمية تتحرك مع تغير السيولة والتقلب","source":"موجز المضارب","time":"الآن"},{"title":"تابع حجم التداول قبل اتخاذ أي قرار","source":"موجز المضارب","time":"اليوم"}]}

def limited(key):
    now=time.time(); bucket=LOGIN_BUCKET.setdefault(key,[]); bucket[:]=[x for x in bucket if now-x<LOGIN_WINDOW]
    if len(bucket)>=LOGIN_LIMIT:return False
    bucket.append(now); return True

@app.post("/api/register")
async def api_register(request:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...)):
    name=name.strip(); email=email.strip().lower(); key=request.client.host if request.client else "unknown"
    if len(name)<2 or len(name)>100 or not valid_email(email) or not 8<=len(password)<=128:return JSONResponse({"ok":False,"error":"تأكد من البيانات وكلمة المرور 8 أحرف على الأقل"},status_code=400)
    if not limited(key):return JSONResponse({"ok":False,"error":"محاولات كثيرة، حاول لاحقاً"},status_code=429)
    if await find_user(email):return JSONResponse({"ok":False,"error":"البريد مستخدم مسبقاً"},status_code=409)
    async with SessionLocal() as s:
        u=User(name=name,email=email,password_hash=hash_password(password)); s.add(u); await s.commit(); await s.refresh(u); request.session.clear(); request.session["user_id"]=u.id
    return {"ok":True,"user":{"id":u.id,"name":u.name,"email":u.email}}

@app.post("/api/login")
async def api_login(request:Request,email:str=Form(...),password:str=Form(...)):
    email=email.strip().lower(); key=request.client.host if request.client else "unknown"
    if not limited(key):return JSONResponse({"ok":False,"error":"محاولات كثيرة، حاول بعد 10 دقائق"},status_code=429)
    user=await find_user(email)
    if not user or not user.is_active or not verify_password(password,user.password_hash):return JSONResponse({"ok":False,"error":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
    request.session.clear(); request.session["user_id"]=user.id
    return {"ok":True,"user":{"id":user.id,"name":user.name,"email":user.email,"admin":user.is_admin}}

@app.post("/api/logout")
async def logout(request:Request): request.session.clear(); return {"ok":True}
@app.get("/api/me")
async def me(request:Request):
    user=await get_user(request.session.get("user_id"))
    return {"ok":True,"user":None if not user else {"id":user.id,"name":user.name,"email":user.email,"admin":user.is_admin}}

if __name__=="__main__":
    import uvicorn; uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")))
