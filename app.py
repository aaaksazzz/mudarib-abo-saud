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
    return {"symbol":symbol,"timeframe":label,"interval":interval,"side":side,"entry":entry,"target":target,"stop":stop,"rsi":round(rv,1),"confidence":confidence,"raw_side":raw_side,"reverse":True,"time":datetime.now(timezone.utc).isoformat()}

async def build_trades():
    now=time.time()
    if now-TRADE_CACHE["at"]<900: return TRADE_CACHE["items"]
    rows=await ticker()
    symbols=[x["symbol"] for x in rows[:30]]
    sem=asyncio.Semaphore(8)
    async def one(s,label,iv):
        async with sem:
            return await trade_signal(s,label,iv)
    jobs=[one(s,label,iv) for label,iv in TRADE_INTERVALS.items() for s in symbols]
    results=await asyncio.gather(*jobs,return_exceptions=True)
    items=[x for x in results if isinstance(x,dict)]
    items.sort(key=lambda x: (list(TRADE_INTERVALS).index(x["timeframe"]), x["symbol"]))
    TRADE_CACHE.update({"at":now,"items":items})
    return items

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
@app.get("/scanner",response_class=HTMLResponse)
async def scanner(): return page("scanner.html","الماسح | المضارب PRO")
@app.get("/trades",response_class=HTMLResponse)
async def trades(): return page("trades.html","الصفقات | المضارب PRO")
@app.get("/news",response_class=HTMLResponse)
async def news(): return page("news.html","الأخبار | المضارب PRO")
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
@app.get("/api/markets")
async def markets_api(): return {"ok":True,"items":await ticker(),"updated":datetime.now(timezone.utc).isoformat()}
@app.get("/api/opportunities")
async def opportunities():
    rows=await ticker(); out=[]
    for x in rows:
        c=x["change"]; signal="شراء" if c>=2 else ("مراقبة ارتداد" if c<=-2 else "محايد")
        out.append({**x,"signal":signal,"confidence":min(95,55+abs(c)*5)})
    out.sort(key=lambda x:(x["signal"]!="محايد",x["confidence"]),reverse=True); return {"ok":True,"items":out[:20]}
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
