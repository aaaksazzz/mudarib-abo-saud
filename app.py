import os, time, asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

APP_NAME="المضارب | منصة تحليل الأسواق"
BINANCE="https://api.binance.com"
app=FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY") or "set-a-real-secret-in-production", max_age=60*60*24*30, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory="static"), name="static")

async def binance(path, params=None):
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent":"Mudarib/1.0"}) as c:
            r=await c.get(BINANCE+path, params=params)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None

async def ticker():
    data=await binance("/api/v3/ticker/24hr")
    if not isinstance(data,list): return []
    rows=[]
    for x in data:
        s=x.get("symbol","")
        if s.endswith("USDT") and float(x.get("quoteVolume",0) or 0)>=1_000_000:
            rows.append({"symbol":s,"price":float(x.get("lastPrice",0) or 0),"change":float(x.get("priceChangePercent",0) or 0),"volume":float(x.get("quoteVolume",0) or 0)})
    rows.sort(key=lambda x:x["volume"], reverse=True)
    return rows[:120]

@app.middleware("http")
async def security(request: Request, call_next):
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    if request.url.scheme=="https": response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return HTMLResponse(open("templates/index.html",encoding="utf-8").read())

@app.get("/markets", response_class=HTMLResponse)
async def markets(): return HTMLResponse(open("templates/markets.html",encoding="utf-8").read())

@app.get("/scanner", response_class=HTMLResponse)
async def scanner(): return HTMLResponse(open("templates/scanner.html",encoding="utf-8").read())

@app.get("/news", response_class=HTMLResponse)
async def news(): return HTMLResponse(open("templates/news.html",encoding="utf-8").read())

@app.get("/login", response_class=HTMLResponse)
async def login(): return HTMLResponse(open("templates/login.html",encoding="utf-8").read())

@app.get("/api/health")
async def health(): return {"ok":True,"service":"mudarib","time":datetime.now(timezone.utc).isoformat()}

@app.get("/api/markets")
async def markets_api():
    rows=await ticker()
    return {"ok":True,"items":rows,"updated":datetime.now(timezone.utc).isoformat()}

@app.get("/api/opportunities")
async def opportunities():
    rows=await ticker()
    out=[]
    for x in rows:
        c=x["change"]
        if c>=2: signal="شراء"
        elif c<=-2: signal="مراقبة ارتداد"
        else: signal="محايد"
        out.append({**x,"signal":signal,"confidence":min(95,55+abs(c)*5)})
    out.sort(key=lambda x:(x["signal"]!="محايد", x["confidence"]), reverse=True)
    return {"ok":True,"items":out[:20]}

@app.get("/api/news")
async def news_api():
    return {"ok":True,"items":[
      {"title":"الأسواق الرقمية تتحرك مع تغير السيولة والتقلب","source":"موجز المضارب","time":"الآن"},
      {"title":"تابع حجم التداول قبل اتخاذ أي قرار","source":"موجز المضارب","time":"اليوم"},
      {"title":"الإشارات الفنية تحتاج تأكيداً من أكثر من إطار زمني","source":"موجز المضارب","time":"اليوم"}]}

@app.post("/api/login")
async def api_login(request: Request, email: str=Form(...), password: str=Form(...)):
    email=email.strip().lower()
    if not email or len(password)<6:
        return JSONResponse({"ok":False,"error":"بيانات الدخول غير صحيحة"},status_code=400)
    # Authentication storage is intentionally isolated for the clean rebuild.
    request.session["user"]={"email":email}
    return {"ok":True,"user":{"email":email}}

@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear(); return {"ok":True}

@app.get("/api/me")
async def me(request: Request): return {"ok":True,"user":request.session.get("user")}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")))
