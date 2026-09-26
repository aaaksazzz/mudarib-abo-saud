import os, time, math, asyncio
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from db import SessionLocal, User, TradeRecord, Subscription, SiteSetting, init_db, hash_password, verify_password, valid_email

APP_NAME="المضارب"
TIMEFRAMES={"15د":"15m","30د":"30m","1س":"1h","4س":"4h","يومي":"1d","أسبوعي":"1w","شهري":"1mo"}
MARKETS={"spot":"🟢 سبوت","futures":"🔴 فيوتشر","contracts":"🇺🇸 عقود أمريكية","saudi":"🇸🇦 السوق السعودي","us":"🇺🇸 السوق الأمريكي","forex":"💱 فوركس وذهب"}
BINANCE="https://api.binance.com"
FUTURES="https://fapi.binance.com"
app=FastAPI(title="المضارب",docs_url=None,redoc_url=None)
app.add_middleware(SessionMiddleware,secret_key=os.getenv("SESSION_SECRET","change-this-secret"),max_age=60*60*24*14)
app.mount("/static",StaticFiles(directory="static"),name="static")

@app.on_event("startup")
async def startup(): await init_db()

async def get_json(url,params=None):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(7,connect=3),headers={"User-Agent":"Mudarib/1.0"}) as c:
            r=await c.get(url,params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print("[data]",url,type(e).__name__,flush=True)
        return None

def num(v,d=0):
    try:return float(v)
    except:return d

def trade(symbol,price,side,tf,market,confidence=70):
    p=num(price)
    long=side=="شراء"
    risk=max(p*.012,0.00000001)
    if long: entry=p; tp1=p+risk; tp2=p+risk*1.8; tp3=p+risk*2.6; stop=p-risk
    else: entry=p; tp1=p-risk; tp2=p-risk*1.8; tp3=p-risk*2.6; stop=p+risk
    return {"symbol":symbol,"market":market,"timeframe":tf,"side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"stop":stop,"confidence":round(max(50,min(96,confidence)),1)}

async def crypto_trades(market,tf):
    url=FUTURES+"/fapi/v1/ticker/24hr" if market=="futures" else BINANCE+"/api/v3/ticker/24hr"
    data=await get_json(url)
    if not isinstance(data,list): return []
    rows=[]
    for x in data:
        sym=x.get("symbol","")
        if not sym.endswith("USDT") or "UP" in sym or "DOWN" in sym: continue
        if market=="futures" and (x.get("contractType") not in (None,"PERPETUAL")): continue
        if num(x.get("quoteVolume"))<1_000_000: continue
        change=num(x.get("priceChangePercent")); price=num(x.get("lastPrice"))
        if price<=0: continue
        side="شراء" if change>=0 else "بيع"
        conf=62+min(30,abs(change)*5)
        rows.append(trade(sym,price,side,tf,market,conf))
    rows.sort(key=lambda z:z["confidence"],reverse=True)
    return rows[:70]

async def yahoo_quote(symbol):
    return await get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",{"range":"5d","interval":"1d"})

async def yahoo_trades(market,tf):
    symbols={"us":["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","NFLX","AVGO","JPM","V","WMT","SPY","QQQ","IWM","PLTR","COIN","MSTR"],
             "saudi":["2222.SR","1120.SR","2010.SR","1180.SR","1150.SR","2030.SR","7010.SR","1211.SR","2020.SR","1050.SR"],
             "forex":["GC=F","CL=F","EURUSD=X","GBPUSD=X","USDJPY=X","DX-Y.NYB"]}.get(market,[])
    out=[]
    for s in symbols:
        data=await yahoo_quote(s)
        try:
            res=data["chart"]["result"][0]; q=res["indicators"]["quote"][0]
            closes=[x for x in q["close"] if x is not None]; vols=[x for x in q.get("volume",[]) if x is not None]
            if not closes: continue
            p=closes[-1]; prev=closes[-2] if len(closes)>1 else p; ch=(p-prev)/prev*100 if prev else 0
            if market=="us" and p*(vols[-1] if vols else 0)<1_000_000: continue
            out.append(trade(s,p,"شراء" if ch>=0 else "بيع",tf,market,65+min(25,abs(ch)*6)))
        except Exception: continue
    return out[:70]

async def options_trades(tf):
    out=[]
    for s in ["AAPL","MSFT","NVDA","AMZN","TSLA","META","SPY","QQQ","IWM","PLTR"]:
        data=await get_json(f"https://query2.finance.yahoo.com/v7/finance/options/{s}")
        try:
            r=data["optionChain"]["result"][0]; price=num(r["quote"]["regularMarketPrice"])
            exp=r.get("options",[{}])[0]
            calls=exp.get("calls",[]) if exp else []
            for o in calls[:8]:
                strike=num(o.get("strike")); premium=num(o.get("lastPrice"))
                if premium<=0 or strike<=0 or abs(strike-price)/price>.12: continue
                x=trade(s,premium,"شراء",tf,"contracts",72)
                x.update({"contract_type":"CALL","strike":strike,"expiration":exp.get("expirationDate"),"premium":premium})
                out.append(x)
        except Exception: continue
    return out[:70]

async def market_trades(market,tf):
    if market in ("spot","futures"): return await crypto_trades(market,tf)
    if market=="contracts": return await options_trades(tf)
    return await yahoo_trades(market,tf)

async def render(request,title,body):
    return HTMLResponse(BASE.replace("{{TITLE}}",title).replace("{{BODY}}",body))

@app.get("/health")
async def health(): return {"ok":True,"service":"mudarib","time":datetime.now(timezone.utc).isoformat()}

@app.get("/",response_class=HTMLResponse)
async def home(request:Request):
    async with SessionLocal() as s:
        setting=await s.get(SiteSetting,"visits")
        n=int(setting.value) if setting and setting.value.isdigit() else 0
        if setting: setting.value=str(n+1)
        else: s.add(SiteSetting(key="visits",value="1"))
        await s.commit()
    body='<section class="hero"><div><span class="eyebrow">مركز الأسواق والصفقات</span><h1>كل السوق<br><b>في مكان واحد.</b></h1><p>صفقات تحليلية مرتبة بالأهداف والوقف ونسبة AI. بدون تنفيذ أوامر تداول.</p><div class="actions"><a class="btn primary" href="/trades">📊 الصفقات</a><a class="btn" href="/scanner">🔎 الماسح</a></div></div><div class="hero-card"><b>المضارب</b><strong>PRO</strong><span>بيانات السوق عند الطلب</span><span>👥 زوار الموقع: <i id="visits">—</i></span></div></section><section><h2>الأسواق</h2><div class="market-grid">'+''.join(f'<a class="market-card" href="/trades?market={k}"><b>{v}</b><span>عرض الصفقات ←</span></a>' for k,v in MARKETS.items())+'</div></section><section><h2>الفريمات</h2><div class="chips">'+''.join(f'<a href="/trades?timeframe={k}">{k}</a>' for k in TIMEFRAMES)+'</div></section>'
    return await render(request,"المضارب | الرئيسية",body)

@app.get("/trades",response_class=HTMLResponse)
async def trades_page(request:Request):
    body='<section><div class="page-head"><div><span class="eyebrow">MARKET CENTER</span><h1>الصفقات</h1><p>تتحدث عند فتح السوق، وتعرض حتى 70 فرصة.</p></div></div><div class="filters">'+''.join(f'<a class="chip" href="/trades?market={k}">{v}</a>' for k,v in MARKETS.items())+'</div><div class="chips">'+''.join(f'<a href="/trades?timeframe={k}">{k}</a>' for k in TIMEFRAMES)+'</div><div id="trades" class="trade-grid"><div class="loading">جاري جلب الصفقات...</div></div></section>'
    return await render(request,"الصفقات | المضارب",body)

@app.get("/scanner",response_class=HTMLResponse)
async def scanner(request:Request):
    body='<section><span class="eyebrow">SMART SCANNER</span><h1>الماسح الذكي</h1><p>يجمع فرص الأسواق في قائمة واحدة.</p><div id="scanner" class="trade-grid"><div class="loading">جاري الفحص...</div></div></section>'
    return await render(request,"الماسح | المضارب",body)

@app.get("/markets",response_class=HTMLResponse)
async def markets(request:Request):
    return await render(request,"الأسواق | المضارب",'<section><h1>الأسواق</h1><div class="market-grid">'+''.join(f'<a class="market-card" href="/trades?market={k}"><b>{v}</b><span>صفقات وتحليل ←</span></a>' for k,v in MARKETS.items())+'</div></section>')

@app.get("/news",response_class=HTMLResponse)
async def news(request:Request):
    body='<section><h1>الأخبار</h1><div class="news-list"><article><b>أخبار الأسواق</b><p>سيتم عرض الأخبار العامة داخل الموقع بدون تعطيل صفحة الصفقات.</p></article><article><b>تنبيه</b><p>المحتوى تحليلي ومعلوماتي وليس توصية استثمارية.</p></article></div></section>'
    return await render(request,"الأخبار | المضارب",body)

@app.get("/blog",response_class=HTMLResponse)
async def blog(request:Request):
    body='<section><h1>المدونة</h1><div class="news-list"><article><b>أساسيات إدارة المخاطر</b><p>فهم الدخول والهدف والوقف أهم من مطاردة كل حركة في السوق.</p></article><article><b>كيف تقرأ الصفقة؟</b><p>راجع الفريم والاتجاه والدخول والأهداف والوقف ونسبة AI قبل اتخاذ قرارك.</p></article></div></section>'
    return await render(request,"المدونة | المضارب",body)

@app.get("/tracker",response_class=HTMLResponse)
async def tracker(request:Request):
    return await render(request,"متابع الصفقات | المضارب",'<section><h1>متابع الصفقات</h1><div id="stats" class="stats-grid"></div><div id="history" class="trade-grid"><div class="loading">جاري التحميل...</div></div></section>')

@app.get("/admin",response_class=HTMLResponse)
async def admin(request:Request):
    u=request.session.get("user")
    if not u or not u.get("admin"): return RedirectResponse("/login?next=/admin",303)
    async with SessionLocal() as s:
        count=await s.scalar(select(func.count(TradeRecord.id))) or 0
        users=await s.scalar(select(func.count(User.id))) or 0
    return await render(request,"الإدارة | المضارب",f'<section><h1>لوحة الإدارة</h1><div class="stats-grid"><div><b>{users}</b><span>حسابات</span></div><div><b>{count}</b><span>سجلات صفقات</span></div></div><p>النظام الجديد خفيف: لا توجد مهام خلفية مستمرة تسبب إعادة تشغيل الخدمة.</p></section>')

@app.get("/login",response_class=HTMLResponse)
async def login(request:Request):
    return await render(request,"تسجيل الدخول",'<section class="form-box"><h1>تسجيل الدخول</h1><form method="post"><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" placeholder="كلمة المرور" required><button class="btn primary">دخول</button></form><a href="/register">إنشاء حساب</a></section>')

@app.post("/login")
async def login_post(request:Request,email:str=Form(...),password:str=Form(...),next:str="/"):
    async with SessionLocal() as s:
        u=await s.scalar(select(User).where(User.email==email.strip().lower()))
    if not u or not verify_password(password,u.password_hash): return RedirectResponse("/login?error=1",303)
    request.session["user"]={"id":u.id,"email":u.email,"admin":bool(u.is_admin)}
    return RedirectResponse(next if next.startswith("/") else "/",303)

@app.get("/register",response_class=HTMLResponse)
async def register(request:Request):
    return await render(request,"إنشاء حساب",'<section class="form-box"><h1>إنشاء حساب</h1><form method="post"><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" minlength="6" placeholder="كلمة المرور" required><button class="btn primary">إنشاء الحساب</button></form></section>')

@app.post("/register")
async def register_post(email:str=Form(...),password:str=Form(...)):
    email=email.strip().lower()
    if not valid_email(email) or len(password)<6:return RedirectResponse("/register?error=1",303)
    async with SessionLocal() as s:
        if await s.scalar(select(User).where(User.email==email)): return RedirectResponse("/login",303)
        s.add(User(email=email,password_hash=hash_password(password))); await s.commit()
    return RedirectResponse("/login",303)

@app.get("/logout")
async def logout(request:Request):
    request.session.clear(); return RedirectResponse("/",303)

@app.get("/api/trades")
async def api_trades(market:str="spot",timeframe:str="15د"):
    if market not in MARKETS: market="spot"
    if timeframe not in TIMEFRAMES: timeframe="15د"
    items=await market_trades(market,timeframe)
    return {"ok":True,"market":market,"timeframe":timeframe,"items":items,"count":len(items),"generated_at":time.time()}

@app.get("/api/scanner")
async def api_scanner(timeframe:str="15د"):
    if timeframe not in TIMEFRAMES: timeframe="15د"
    jobs=await asyncio.gather(*(market_trades(m,timeframe) for m in MARKETS),return_exceptions=True)
    out=[]
    for xs in jobs:
        if isinstance(xs,list): out.extend(xs)
    out.sort(key=lambda x:x["confidence"],reverse=True)
    return {"ok":True,"items":out[:70],"timeframe":timeframe}

@app.get("/api/site-visitors")
async def visitors():
    async with SessionLocal() as s:
        x=await s.get(SiteSetting,"visits")
        return {"ok":True,"visits":int(x.value) if x and x.value.isdigit() else 0}

@app.get("/api/tracker")
async def tracker_api():
    async with SessionLocal() as s:
        rows=(await s.scalars(select(TradeRecord).order_by(TradeRecord.id.desc()).limit(200))).all()
    total=len(rows); wins=sum(r.pnl_pct>0 for r in rows); losses=sum(r.pnl_pct<0 for r in rows)
    return {"ok":True,"stats":{"total":total,"wins":wins,"losses":losses,"pnl_pct":round(sum(r.pnl_pct for r in rows),2)},"items":[{"symbol":r.symbol,"market":r.market,"side":r.side,"status":r.status,"pnl_pct":r.pnl_pct} for r in rows]}

BASE='''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="description" content="{{TITLE}}"><title>{{TITLE}}</title><link rel="stylesheet" href="/static/style.css?v=200"></head><body><header><a class="brand" href="/">المضارب</a><nav><a href="/">الرئيسية</a><a href="/trades">الصفقات</a><a href="/markets">الأسواق</a><a href="/scanner">الماسح</a><a href="/news">الأخبار</a><a href="/blog">المدونة</a><a href="/tracker">المتابع</a></nav><button id="theme" type="button" class="icon">☾</button><button id="menu" type="button" class="icon" aria-expanded="false">☰</button></header><aside id="drawer"><a href="/">الرئيسية</a><a href="/trades">الصفقات</a><a href="/markets">الأسواق</a><a href="/scanner">الماسح</a><a href="/news">الأخبار</a><a href="/blog">المدونة</a><a href="/tracker">متابع الصفقات</a><a href="/login">الحساب</a><a href="/admin">الإدارة</a></aside><main>{{BODY}}</main><footer>المضارب · منصة تحليلية مستقلة · لا يتم تنفيذ أوامر تداول</footer><script src="/static/app.js?v=200"></script></body></html>'''
