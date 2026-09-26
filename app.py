import os, time, math, asyncio, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
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

_CACHE={}
async def get_json(url,params=None,ttl=20):
    key=url+"?"+str(sorted((params or {}).items()))
    hit=_CACHE.get(key); now=time.time()
    if hit and now-hit[0]<ttl: return hit[1]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5,connect=2),headers={"User-Agent":"Mudarib/1.0"}) as c:
            r=await c.get(url,params=params); r.raise_for_status()
            data=r.json(); _CACHE[key]=(now,data); return data
    except Exception as e:
        print("[data]",url,type(e).__name__,flush=True)
        return hit[1] if hit else None

async def get_text(url,ttl=60):
    key="TXT:"+url; hit=_CACHE.get(key); now=time.time()
    if hit and now-hit[0]<ttl: return hit[1]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6,connect=2),headers={"User-Agent":"Mudarib/1.0"}) as c:
            r=await c.get(url); r.raise_for_status(); data=r.text; _CACHE[key]=(now,data); return data
    except Exception as e:
        print("[news]",type(e).__name__,flush=True)
        return hit[1] if hit else ""

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
    results=await asyncio.gather(*(yahoo_quote(s) for s in symbols),return_exceptions=True)
    for s,data in zip(symbols,results):
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
    symbols=["AAPL","MSFT","NVDA","AMZN","TSLA","META","SPY","QQQ","IWM","PLTR"]
    results=await asyncio.gather(*(get_json(f"https://query2.finance.yahoo.com/v7/finance/options/{s}") for s in symbols),return_exceptions=True)
    for s,data in zip(symbols,results):
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
    cards=''.join(f'<a class="market-card" href="/trades?market={k}"><span class="market-icon">{v.split(" ")[0]}</span><b>{v.split(" ",1)[1]}</b><small>الصفقات والتحليل <i>←</i></small></a>' for k,v in MARKETS.items())
    body='<section class="home-hero"><div class="home-copy"><span class="eyebrow">مركز التداول والتحليل</span><h1>راقب السوق.<br><em>اعرف الفرصة.</em></h1><p>صفقات واضحة بدخول وأهداف ووقف، مرتبة حسب الفريم والسوق.</p><div class="actions"><a class="btn primary" href="/trades">شاهد الصفقات</a><a class="btn" href="/scanner">🔎 الماسح الذكي</a></div><div class="home-stats"><div><b>7</b><span>فريمات</span></div><div><b>6</b><span>أسواق</span></div><div><b id="visits">—</b><span>زيارة</span></div></div></div><div class="signal-preview"><div class="preview-head"><span>📡 السوق الآن</span><strong>AI</strong></div><div class="preview-row"><div><b>أفضل الفرص</b><small>تُرتب حسب قوة الإشارة</small></div><span class="live-dot">● مباشر</span></div><div class="preview-levels"><div><small>دخول</small><b>Entry</b></div><div><small>الأهداف</small><b>TP1 · TP2 · TP3</b></div><div><small>الحماية</small><b>SL</b></div></div><a class="preview-link" href="/scanner">فتح الماسح ←</a></div></section><section class="home-section"><div class="section-head"><div><span class="eyebrow">MARKETS</span><h2>اختر سوقك</h2></div><a href="/markets">عرض الكل ←</a></div><div class="market-grid home-markets">'+cards+'</div></section><section class="home-section"><div class="section-head"><div><span class="eyebrow">LIVE TRADE DESK</span><h2>🔥 صفقات التداول</h2></div><a href="/trades">كل الصفقات ←</a></div><div id="home-trades" class="trade-grid"><div class="loading">جاري استخراج الصفقات...</div></div></section><section class="home-section"><div class="section-head"><div><span class="eyebrow">AI MARKET RADAR</span><h2>🎯 أفضل الفرص الآن</h2></div><a href="/scanner">فتح الماسح ←</a></div><div id="home-radar" class="trade-grid"><div class="loading">جاري تحليل الفرص...</div></div></section><section class="home-section"><div class="section-head"><div><span class="eyebrow">TRADE PERFORMANCE</span><h2>📊 أداء الصفقات</h2></div><a href="/tracker">متابعة كاملة ←</a></div><div id="home-performance" class="stats-grid"><div><b>—</b><span>مفتوحة</span></div><div><b>—</b><span>مغلقة</span></div><div><b>—</b><span>رابحة</span></div><div><b>—</b><span>خاسرة</span></div></div></section><section class="home-section timeframe-section"><div class="section-head"><div><span class="eyebrow">TIMEFRAME</span><h2>الفريمات</h2></div></div><div class="chips">'+''.join(f'<a href="/trades?timeframe={k}">{k}</a>' for k in TIMEFRAMES)+'</div></section>'
    return await render(request,"المضارب | الرئيسية",body)

@app.get("/spot",response_class=HTMLResponse)
async def spot(request:Request): return await trades_page(request)

@app.get("/futures",response_class=HTMLResponse)
async def futures(request:Request): return await trades_page(request)

@app.get("/contracts",response_class=HTMLResponse)
async def contracts(request:Request): return await trades_page(request)

@app.get("/saudi",response_class=HTMLResponse)
async def saudi(request:Request): return await trades_page(request)

@app.get("/us",response_class=HTMLResponse)
async def us(request:Request): return await trades_page(request)

@app.get("/forex",response_class=HTMLResponse)
async def forex(request:Request): return await trades_page(request)

@app.get("/trades",response_class=HTMLResponse)
async def trades_page(request:Request):
    market=request.query_params.get("market","spot")
    tf=request.query_params.get("timeframe","15د")
    if market not in MARKETS: market="spot"
    if tf not in TIMEFRAMES: tf="15د"
    body=f'''<section class="tracker-page"><div class="page-head"><span class="eyebrow">LIVE TRADE DESK</span><h1>🔥 صفقات التداول</h1><p>الصفقات الحالية حسب السوق والفريم — دخول، أهداف، وقف وAI%.</p></div><div class="chips">{"".join(f'<a class="chip" href="/trades?market={k}&timeframe={tf}">{v}</a>' for k,v in MARKETS.items())}</div><div class="chips">{"".join(f'<a class="chip" href="/trades?market={market}&timeframe={k}">{k}</a>' for k in TIMEFRAMES)}</div><div id="reverse-control"><button id="reverse" class="chip" type="button">🔄 عكس الاستراتيجية: <b>متوقف</b></button></div><div id="trades" class="trade-grid"><div class="loading">جاري استخراج الصفقات...</div></div></section>'''
    return await render(request,"الصفقات | المضارب",body)

@app.get("/scanner",response_class=HTMLResponse)
async def scanner(request:Request):
    body='<section class="scanner-page"><div class="scanner-head"><div><span class="eyebrow">SMART SCANNER</span><h1>الماسح الذكي</h1><p>يفحص الأسواق ويجمع أقوى الفرص حسب الاتجاه والسيولة والزخم.</p></div><span class="scanner-live">● مباشر</span></div><div class="scanner-controls"><div class="chips">'+''.join(f'<a class="chip" href="/scanner?timeframe={k}">{k}</a>' for k in TIMEFRAMES)+'</div></div><div id="scanner-summary" class="scanner-summary"><div>جاري التحليل...</div></div><div id="scanner" class="trade-grid"><div class="loading">جاري فحص الأسواق...</div></div></section>'
    return await render(request,"الماسح الذكي | المضارب",body)

@app.get("/markets",response_class=HTMLResponse)
async def markets(request:Request):
    return await render(request,"الأسواق | المضارب",'<section><h1>الأسواق</h1><div class="market-grid">'+''.join(f'<a class="market-card" href="/trades?market={k}"><b>{v}</b><span>صفقات وتحليل ←</span></a>' for k,v in MARKETS.items())+'</div></section>')

@app.get("/news",response_class=HTMLResponse)
async def news(request:Request):
    body="""<section class="news-page"><div class="news-hero"><div><span class="eyebrow">MARKET NEWS</span><h1>أخبار الأسواق</h1><p>آخر الأخبار الاقتصادية والمالية مرتبة من الأحدث إلى الأقدم.</p></div><span class="news-live">● مباشر</span></div><div class="news-toolbar"><a class="chip active" href="/news?type=news">كل الأخبار</a><a class="chip" href="/news?type=saudi">السعودية</a><a class="chip" href="/news?type=global">العالمية</a><a class="chip" href="/news?type=gold">الذهب</a><a class="chip" href="/news?type=oil">النفط</a></div><div id="news-feed" class="news-feed"><div class="loading">جاري جلب أحدث الأخبار...</div></div></section><script>document.addEventListener("DOMContentLoaded",async()=>{const b=document.getElementById("news-feed");try{const r=await fetch("/api/news?type="+encodeURIComponent(new URLSearchParams(location.search).get("type")||"news"),{cache:"no-store"});const d=await r.json();b.innerHTML=d.items?.length?d.items.map((x,i)=>'<article class="news-card '+(i===0?"featured":"")+'"><div class="news-card-top"><span>'+x.source+'</span><time>'+x.time+'</time></div><h2>'+x.title+'</h2><p>'+x.summary+'</p><div class="news-footer"><b>'+x.category+'</b><span>قراءة الخبر ←</span></div></article>').join(""):'<div class="empty">لا توجد أخبار حالياً.</div>'}catch(e){b.innerHTML="<div class=\"empty\">تعذر جلب الأخبار حالياً.</div>"}})</script>"""
    return await render(request,"أخبار الأسواق | المضارب",body)

@app.get("/blog",response_class=HTMLResponse)
async def blog(request:Request):
    body='<section><h1>المدونة</h1><div class="news-list"><article><b>أساسيات إدارة المخاطر</b><p>فهم الدخول والهدف والوقف أهم من مطاردة كل حركة في السوق.</p></article><article><b>كيف تقرأ الصفقة؟</b><p>راجع الفريم والاتجاه والدخول والأهداف والوقف ونسبة AI قبل اتخاذ قرارك.</p></article></div></section>'
    return await render(request,"المدونة | المضارب",body)

@app.get("/tracker",response_class=HTMLResponse)
async def tracker(request:Request):
    return await render(request,"متابع الصفقات | المضارب",'<section><h1>متابع الصفقات</h1><div id="stats" class="stats-grid"></div><div id="history" class="trade-grid"><div class="loading">جاري التحميل...</div></div></section>')

@app.get("/subscriptions",response_class=HTMLResponse)
async def subscriptions(request:Request):
    plans=[("7 أيام","10"),("15 يوم","20"),("30 يوم","30")]
    cards=''.join(f'<article class="plan-card"><span>مضارب PRO</span><h2>{name}</h2><strong>{price} USDT</strong><small>صلاحية الوصول للصفقات والتحليل</small><form method="post" action="/subscriptions"><input type="hidden" name="plan" value="{name}"><input type="hidden" name="price" value="{price}"><button class="btn primary" type="submit">طلب الاشتراك</button></form></article>' for name,price in plans)
    body=f'<section class="subscriptions-page"><div class="page-head"><span class="eyebrow">SUBSCRIPTIONS</span><h1>الاشتراكات</h1><p>اختر الباقة المناسبة ثم أرسل طلب الاشتراك للمراجعة.</p></div><div class="plans-grid">{cards}</div><div class="subscription-note">💳 الدفع يتم تأكيده من الإدارة بعد إرسال الطلب.</div></section>'
    return await render(request,"الاشتراكات | المضارب",body)

@app.post("/subscriptions")
async def subscriptions_post(request:Request,plan:str=Form(...),price:str=Form(...)):
    allowed={"7 أيام":"10","15 يوم":"20","30 يوم":"30"}
    if plan not in allowed or allowed[plan]!=price:
        return RedirectResponse("/subscriptions?error=1",303)
    u=request.session.get("user")
    email=(u or {}).get("email")
    if not email:
        return RedirectResponse("/login?next=/subscriptions",303)
    try:
        async with SessionLocal() as s:
            s.add(Subscription(email=email,plan=f"{plan} | {price} USDT",status="pending"))
            await s.commit()
        return RedirectResponse("/subscriptions?submitted=1",303)
    except Exception as e:
        print("[subscriptions]",type(e).__name__,flush=True)
        return RedirectResponse("/subscriptions?error=db",303)

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
async def api_trades(market:str="spot",timeframe:str="15د",reverse:int=0):
    if market not in MARKETS: market="spot"
    if timeframe not in TIMEFRAMES: timeframe="15د"
    items=await market_trades(market,timeframe)
    if reverse:
        for x in items: x["side"]="بيع" if x["side"]=="شراء" else "شراء"; x["reversed"]=True
    return {"ok":True,"market":market,"timeframe":timeframe,"reverse":bool(reverse),"items":items,"count":len(items),"generated_at":time.time()}

@app.get("/api/scanner")
async def api_scanner(timeframe:str="15د"):
    if timeframe not in TIMEFRAMES: timeframe="15د"
    jobs=await asyncio.gather(*(market_trades(m,timeframe) for m in MARKETS),return_exceptions=True)
    out=[]
    for xs in jobs:
        if isinstance(xs,list): out.extend(xs)
    for x in out:
        change=abs(num(x.get("confidence"),0)-62)
        x["score"]=round(min(99,max(50,num(x.get("confidence"),50)+change*.45)),1)
        x["rank_label"]="قوي جداً" if x["score"]>=88 else "قوي" if x["score"]>=78 else "مراقبة"
    out.sort(key=lambda x:(x["score"],x["confidence"]),reverse=True)
    for i,x in enumerate(out): x["rank"]=i+1
    return {"ok":True,"timeframe":timeframe,"items":out[:70],"count":len(out),"generated_at":time.time()}

@app.get("/api/news")
async def api_news(type:str="news"):
    feeds={"news":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL,MSFT,NVDA,GC=F,CL=F&region=US&lang=en-US","global":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,DIA&region=US&lang=en-US","gold":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US","oil":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F&region=US&lang=en-US","saudi":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=2222.SR,1120.SR&region=US&lang=en-US"}
    raw=await get_text(feeds.get(type,feeds["news"]),ttl=120)
    items=[]
    try:
        root=ET.fromstring(raw)
        for it in root.findall(".//item")[:15]:
            title=(it.findtext("title") or "").strip()
            if title: items.append({"title":title,"summary":(it.findtext("description") or "")[:240],"source":"Yahoo Finance","time":(it.findtext("pubDate") or "").strip(),"category":type})
    except Exception: pass
    return {"ok":True,"items":items,"count":len(items),"updated_at":time.time()}

@app.get("/api/home")
async def api_home():
    jobs=await asyncio.gather(*(market_trades(m,"15د") for m in MARKETS),return_exceptions=True)
    items=[x for xs in jobs if isinstance(xs,list) for x in xs]
    items.sort(key=lambda x:x.get("confidence",0),reverse=True)
    return {"ok":True,"trades":items[:12],"count":len(items),"markets":len(MARKETS),"timeframes":len(TIMEFRAMES),"updated_at":time.time()}

@app.get("/api/site-visitors")
async def visitors():
    async with SessionLocal() as s:
        x=await s.get(SiteSetting,"visits")
        return {"ok":True,"visits":int(x.value) if x and x.value.isdigit() else 0}

@app.get("/api/tracker")
async def tracker_api():
    now=datetime.now(timezone.utc)
    day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    week_start=day_start-timedelta(days=now.weekday())
    month_start=now.replace(day=1)
    async with SessionLocal() as s:
        rows=(await s.scalars(select(TradeRecord).where(TradeRecord.status!="open").order_by(TradeRecord.closed_at.desc().nullslast(),TradeRecord.id.desc()).limit(500))).all()
    def in_period(r,start):
        d=r.closed_at or r.created_at
        return bool(d and d>=start)
    def stats(rs):
        wins=sum(1 for r in rs if r.pnl_pct>0); losses=sum(1 for r in rs if r.pnl_pct<0)
        pnl=round(sum(r.pnl_pct for r in rs),2)
        total=len(rs); winrate=round((wins/total*100),2) if total else 0
        return {"trades":total,"wins":wins,"losses":losses,"pnl_pct":pnl,"winrate":winrate}
    periods={"اليوم":stats([r for r in rows if in_period(r,day_start)]),"الأسبوع":stats([r for r in rows if in_period(r,week_start)]),"1 ساعة":stats([r for r in rows if r.closed_at and r.closed_at>=now-timedelta(hours=1)]),"4 ساعات":stats([r for r in rows if r.closed_at and r.closed_at>=now-timedelta(hours=4)]),"الشهر":stats([r for r in rows if in_period(r,month_start)]),"كل السجل":stats(rows)}
    ranking=sorted(rows,key=lambda r:r.pnl_pct,reverse=True)[:30]
    return {"ok":True,"periods":periods,"ranking":[{"rank":i+1,"symbol":r.symbol,"market":r.market,"timeframe":r.timeframe,"side":r.side,"status":r.status,"pnl_pct":round(r.pnl_pct,2),"confidence":round(r.confidence,1)} for i,r in enumerate(ranking)]}



BASE='''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="description" content="{{TITLE}}"><title>{{TITLE}}</title><link rel="stylesheet" href="/static/style.css?v=200"></head><body><header><a class="brand" href="/">المضارب</a><nav><a href="/">الرئيسية</a><a href="/trades">الصفقات</a><a href="/markets">الأسواق</a><a href="/scanner">الماسح</a><a href="/news">الأخبار</a><a href="/blog">المدونة</a><a href="/tracker">المتابع</a><a href="/subscriptions">الاشتراكات</a></nav><button id="menu" type="button" class="icon" aria-expanded="false">☰</button></header><aside id="drawer"><a href="/">الرئيسية</a><a href="/trades">الصفقات</a><a href="/markets">الأسواق</a><a href="/scanner">الماسح</a><a href="/news">الأخبار</a><a href="/blog">المدونة</a><a href="/tracker">متابع الصفقات</a><a href="/subscriptions">الاشتراكات</a><a href="/login">الحساب</a><a href="/admin">الإدارة</a></aside><main>{{BODY}}</main><footer>المضارب · منصة تحليلية مستقلة · لا يتم تنفيذ أوامر تداول</footer><script src="/static/app.js?v=200"></script></body></html>'''
