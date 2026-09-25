import os, time
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from db import User, SessionLocal, init_db, find_user, get_user, hash_password, verify_password, valid_email

APP_NAME="المضارب | منصة تحليل الأسواق"; BINANCE="https://api.binance.com"
app=FastAPI(title=APP_NAME,docs_url=None,redoc_url=None)
secret=os.getenv("SECRET_KEY")
if not secret: raise RuntimeError("SECRET_KEY is required")
app.add_middleware(SessionMiddleware,secret_key=secret,max_age=2592000,same_site="lax",https_only=os.getenv("COOKIE_SECURE","1")=="1")
app.mount("/static",StaticFiles(directory="static"),name="static")
LOGIN_BUCKET={}; LOGIN_LIMIT=8; LOGIN_WINDOW=600

@app.on_event("startup")
async def startup(): await init_db()

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
@app.get("/news",response_class=HTMLResponse)
async def news(): return page("news.html","الأخبار | المضارب PRO")
@app.get("/login",response_class=HTMLResponse)
async def login(): return page("login.html","تسجيل الدخول | المضارب PRO")
@app.get("/register",response_class=HTMLResponse)
async def register(): return page("register.html","إنشاء حساب | المضارب PRO")

@app.get("/api/health")
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
