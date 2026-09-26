import os, time, asyncio, secrets, json, html, re
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select
from db import User, TradeRecord, SiteSetting, Subscription, SessionLocal, init_db, find_user, get_user, hash_password, verify_password, valid_email

APP_NAME="المضارب | منصة تحليل الأسواق"

# Primary + backup market-data endpoints.
# The app tries the primary first, then automatically fails over to the
# backup Binance gateways and Yahoo Finance query hosts.
BINANCE_HOSTS=[
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]
BINANCE_FUTURES_HOSTS=[
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]
YAHOO_HOSTS=[
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
BINANCE=BINANCE_HOSTS[0]

# Independent provider rotation per timeframe.
TIMEFRAME_PROVIDER_ROTATION={
    "5د": BINANCE_HOSTS,
    "15د": BINANCE_HOSTS[1:]+BINANCE_HOSTS[:1],
    "1س": BINANCE_HOSTS[2:]+BINANCE_HOSTS[:2],
    "4س": BINANCE_HOSTS[3:]+BINANCE_HOSTS[:3],
    "يومي": BINANCE_HOSTS[4:]+BINANCE_HOSTS[:4],
    "أسبوعي": BINANCE_HOSTS[1:]+BINANCE_HOSTS[:1],
    "شهري": BINANCE_HOSTS[2:]+BINANCE_HOSTS[:2],
}

app=FastAPI(title=APP_NAME,docs_url=None,redoc_url=None)
secret=os.getenv("SECRET_KEY","").strip()
# Keep the public site available even if the deployment forgot SECRET_KEY.
# Sessions become invalid after a restart until a permanent SECRET_KEY is configured.
if not secret:
    secret=secrets.token_urlsafe(48)
    print('[security] WARNING: SECRET_KEY is not configured; sessions reset after restart.')
app.add_middleware(SessionMiddleware,secret_key=secret,max_age=2592000,same_site="lax",https_only=os.getenv("COOKIE_SECURE","1")=="1")
app.mount("/static",StaticFiles(directory="static"),name="static")
LOGIN_BUCKET={}; LOGIN_LIMIT=8; LOGIN_WINDOW=600
HTTP_CLIENT=None
TRADE_BUILD_LOCK=asyncio.Lock()
TRADE_INTERVALS={"5د":"5m","15د":"15m","1س":"1h","4س":"4h","يومي":"1d","أسبوعي":"1w","شهري":"1M"}
TRADE_CACHE={"at":0,"items":[]}
# Precomputed market signals: pages read from this cache instead of waiting for analysis.
# Each market + timeframe has its own snapshot and is refreshed in the background every hour.
MARKET_TRADE_CACHE={}
MARKET_CACHE_LOCK=asyncio.Lock()
MARKET_CACHE_TTL=3600
TIMEFRAME_WORKERS={tf:asyncio.Lock() for tf in TRADE_INTERVALS}
TIMEFRAME_STAGGER={"5د":0,"15د":20,"1س":40,"4س":60,"يومي":80,"أسبوعي":100,"شهري":120}
TIMEFRAME_REFRESH={"5د":300,"15د":900,"1س":3600,"4س":14400,"يومي":86400,"أسبوعي":604800,"شهري":2592000}
MARKETS_TO_PRECOMPUTE=("spot","futures","contracts","us","saudi","forex")


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
    # Use the strategy direction as-is: bullish = BUY, bearish = SELL.
    # Do not invert the generated signal.
    side=raw_side
    entry=last["close"]
    stop=entry*(0.98 if side=="شراء" else 1.02)
    target=entry*(1.04 if side=="شراء" else 0.96)
    confidence=min(99,round(60+abs(rv-50)*0.7+min(15,abs(last["close"]/e20-1)*1000),1))
    risk=abs(entry-stop)
    tp1=entry + (risk*1.0 if side=="شراء" else -risk*1.0)
    tp2=entry + (risk*2.0 if side=="شراء" else -risk*2.0)
    tp3=entry + (risk*3.0 if side=="شراء" else -risk*3.0)
    return {"symbol":symbol,"timeframe":label,"interval":interval,"side":side,"entry":entry,"target":tp2,"tp1":tp1,"tp2":tp2,"tp3":tp3,"stop":stop,"rsi":round(rv,1),"confidence":confidence,"raw_side":raw_side,"reverse":True,"time":datetime.now(timezone.utc).isoformat(),"current_price":entry}

def timeframe_seconds(label):
    return {"5د":300,"15د":900,"1س":3600,"4س":14400,"يومي":86400,"أسبوعي":604800,"شهري":2592000}.get(label,900)

async def sync_trade_records(items):
    now=datetime.now(timezone.utc)
    price_map={x.get("symbol"):float(x.get("current_price") or x.get("entry") or 0) for x in items if x.get("symbol")}
    async with SessionLocal() as s:
        # Close open records when their signal timeframe expires, so old signals
        # never remain open forever and are replaced on the next scan.
        open_rows=(await s.execute(select(TradeRecord).where(TradeRecord.status=="open"))).scalars().all()
        for rec in open_rows:
            try:
                age=(now-rec.opened_at).total_seconds() if rec.opened_at else 0
                if age >= timeframe_seconds(rec.timeframe):
                    price=price_map.get(rec.symbol,rec.entry)
                    rec.status="closed"; rec.close_price=price; rec.closed_at=now
                    rec.pnl_pct=((price-rec.entry)/rec.entry*100) if rec.side=="شراء" else ((rec.entry-price)/rec.entry*100)
            except Exception:
                continue
        for x in items:
            try:
                market=x.get("market","spot"); symbol=x["symbol"]; tf=x["timeframe"]
                q=await s.execute(select(TradeRecord).where(TradeRecord.symbol==symbol,TradeRecord.market==market,TradeRecord.timeframe==tf,TradeRecord.status=="open").order_by(TradeRecord.id.desc()))
                rec=q.scalars().first()
                if rec is None:
                    rec=TradeRecord(symbol=symbol,market=market,timeframe=tf,side=x["side"],entry=float(x["entry"]),tp1=float(x["tp1"]),tp2=float(x["tp2"]),tp3=float(x["tp3"]),stop=float(x["stop"]),confidence=float(x.get("confidence",0)),rsi=float(x.get("rsi",0)),status="open",opened_at=now)
                    s.add(rec); await s.flush()
                price=float(x.get("current_price") or x.get("entry") or rec.entry)
                if rec.side=="شراء":
                    if price>=rec.tp1: rec.reached_tp1=True
                    if price>=rec.tp2: rec.reached_tp2=True
                    if price>=rec.tp3:
                        rec.reached_tp3=True; rec.status="closed"; rec.close_price=price; rec.closed_at=now
                    elif price<=rec.stop:
                        rec.status="closed"; rec.close_price=price; rec.closed_at=now
                else:
                    if price<=rec.tp1: rec.reached_tp1=True
                    if price<=rec.tp2: rec.reached_tp2=True
                    if price<=rec.tp3:
                        rec.reached_tp3=True; rec.status="closed"; rec.close_price=price; rec.closed_at=now
                    elif price>=rec.stop:
                        rec.status="closed"; rec.close_price=price; rec.closed_at=now
                if rec.status=="closed" and rec.close_price is not None:
                    rec.pnl_pct=((rec.close_price-rec.entry)/rec.entry*100) if rec.side=="شراء" else ((rec.entry-rec.close_price)/rec.entry*100)
            except Exception:
                continue
        await s.commit()

async def build_trades(timeframe=None):
    labels=[timeframe] if timeframe in TRADE_INTERVALS else list(TRADE_INTERVALS)
    now=time.time()
    if not hasattr(build_trades,"cache"):
        build_trades.cache={}
    cache=build_trades.cache
    if timeframe and timeframe in cache and now-cache[timeframe]["at"] < timeframe_seconds(timeframe):
        return cache[timeframe]["items"]
    async with TRADE_BUILD_LOCK:
        if timeframe and timeframe in cache and now-cache[timeframe]["at"] < timeframe_seconds(timeframe):
            return cache[timeframe]["items"]
        rows=await ticker()
        symbols=[x["symbol"] for x in rows]
        price_map={x["symbol"]:x["price"] for x in rows}
        if not symbols:
            return cache.get(timeframe,{"items":[]})["items"]
        sem=asyncio.Semaphore(8)
        async def one(sym,label,iv):
            async with sem:
                try:
                    return await trade_signal(sym,label,iv)
                except Exception:
                    return None
        jobs=[one(sym,label,TRADE_INTERVALS[label]) for label in labels for sym in symbols]
        results=await asyncio.gather(*jobs)
        items=[x for x in results if isinstance(x,dict)]
        for x in items:
            x.setdefault("market","spot")
            x["current_price"]=price_map.get(x["symbol"],x.get("entry"))
        await sync_trade_records(items)
        items.sort(key=lambda x:-x["confidence"])
        if timeframe:
            cache[timeframe]={"at":now,"items":items}
        else:
            for label in labels:
                cache[label]={"at":now,"items":[x for x in items if x["timeframe"]==label]}
        return items

async def refresh_timeframe_worker(timeframe):
    # Dedicated worker for one timeframe; staggered to avoid request bursts.
    await asyncio.sleep(TIMEFRAME_STAGGER.get(timeframe,0))
    while True:
        try:
            async with TIMEFRAME_WORKERS[timeframe]:
                for market in MARKETS_TO_PRECOMPUTE:
                    try:
                        result=await market_trades_api(market,timeframe)
                        items=result.get("items",[]) if isinstance(result,dict) else []
                        if items:
                            MARKET_TRADE_CACHE[(market,timeframe)]={"at":time.time(),"items":items,"provider_ok":True}
                        elif (market,timeframe) not in MARKET_TRADE_CACHE:
                            MARKET_TRADE_CACHE[(market,timeframe)]={"at":time.time(),"items":[],"provider_ok":False}
                    except Exception as exc:
                        print(f"[trade-cache] {timeframe}/{market}: {exc!r}")
                    await asyncio.sleep(2)
            await asyncio.sleep(TIMEFRAME_REFRESH.get(timeframe,MARKET_CACHE_TTL))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[trade-cache] worker {timeframe} failed: {exc!r}")
            await asyncio.sleep(60)

async def refresh_market_trade_cache():
    # Seven isolated workers: 5m, 15m, 1h, 4h, daily, weekly, monthly.
    for timeframe in TRADE_INTERVALS:
        asyncio.create_task(refresh_timeframe_worker(timeframe))
        await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    # A database problem must not take the whole public website offline.
    try:
        await init_db()
    except Exception as exc:
        print(f"[startup] database initialization failed: {exc!r}")
    # Start precomputation after the site is up. Users get the last snapshot
    # immediately instead of triggering a full market scan on every page load.
    asyncio.create_task(refresh_market_trade_cache())

async def _get_json(hosts,path,params=None,timeout=8):
    for _round in range(2):
        for host in hosts:
            try:
                async with httpx.AsyncClient(timeout=timeout,headers={"User-Agent":"Mudarib/1.0"}) as c:
                    r=await c.get(host+path,params=params)
                    r.raise_for_status()
                    return r.json()
            except Exception:
                continue
        await asyncio.sleep(0.25)
    return None

async def binance(path,params=None,timeframe=None):
    hosts=TIMEFRAME_PROVIDER_ROTATION.get(timeframe,BINANCE_HOSTS) if timeframe else BINANCE_HOSTS
    return await _get_json(hosts,path,params,8)

async def binance_futures(path,params=None):
    return await _get_json(BINANCE_FUTURES_HOSTS,path,params,8)

async def yahoo_chart(symbol,params):
    # Yahoo Finance backup host support.
    for host in YAHOO_HOSTS:
        try:
            async with httpx.AsyncClient(timeout=8,headers={"User-Agent":"Mozilla/5.0"}) as c:
                r=await c.get(host+"/v8/finance/chart/"+symbol,params=params)
                r.raise_for_status()
                return r.json()
        except Exception:
            continue
    return None

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
async def telegram_send(text):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat_id=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat_id:
        return False,"TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID غير مضبوطين"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True})
            data=r.json()
            if r.is_success and data.get("ok"):
                return True,"تم إرسال الرسالة إلى تيليجرام"
            return False,str(data.get("description") or "فشل إرسال الرسالة")
    except Exception as exc:
        return False,"تعذر الاتصال بتيليجرام"

def format_telegram_trade(x):
    side=html.escape(str(x.get("side","")))
    symbol=html.escape(str(x.get("symbol","")))
    tf=html.escape(str(x.get("timeframe","")))
    return (f"🚨 <b>صفقة جديدة | المضارب PRO</b>\n\n"
            f"📌 <b>{symbol}</b> · {tf}\n"
            f"📊 الاتجاه: <b>{side}</b>\n"
            f"💰 الدخول: <b>{x.get('entry')}</b>\n"
            f"🎯 TP1: <b>{x.get('tp1')}</b>\n"
            f"🎯 TP2: <b>{x.get('tp2')}</b>\n"
            f"🎯 TP3: <b>{x.get('tp3')}</b>\n"
            f"🛑 الوقف: <b>{x.get('stop')}</b>\n"
            f"🤖 AI: <b>{x.get('confidence',0)}%</b>\n\n"
            f"🔄 عكس الاستراتيجية: <b>مفعّل</b>\n"
            f"⚠️ تحليل معلوماتي وليس توصية مالية.")

def load_articles():
    try:
        with open("data/articles.json",encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def article_slug(text):
    return re.sub(r"[^\w\u0600-\u06FF-]+","-",text.lower()).strip("-")

@app.get("/blog",response_class=HTMLResponse)
async def blog():
    articles=load_articles()
    cards=[]
    for a in articles:
        cards.append(f'<article class="blog-card"><div class="blog-card-top"><span class="blog-icon">📚</span><span class="blog-tag">{html.escape(a["category"])}</span></div><h3>{html.escape(a["title"])}</h3><p>{html.escape(a["excerpt"])}</p><div class="blog-card-foot"><span>⏱ {a["minutes"]} دقائق</span><a href="/blog/{html.escape(a["slug"])}">اقرأ المقال ←</a></div></article>')
    out=page("blog.html","المدونة | المضارب PRO")
    return HTMLResponse(out.body.decode().replace("{{ARTICLE_CARDS}}","".join(cards)).replace("{{ARTICLE_COUNT}}",str(len(articles))))

@app.get("/blog/{slug}",response_class=HTMLResponse)
async def blog_article(slug:str):
    articles=load_articles()
    a=next((x for x in articles if x.get("slug")==slug),None)
    if not a:
        return HTMLResponse("<h1>المقال غير موجود</h1>",status_code=404)
    paras="".join(f"<p>{html.escape(p)}</p>" for p in a["content"])
    related=[x for x in articles if x["category"]==a["category"] and x["slug"]!=a["slug"]][:4]
    related_html="".join(f'<a class="admin-link" href="/blog/{html.escape(x["slug"])}"><b>{html.escape(x["title"])}</b><small>{html.escape(x["excerpt"])}</small></a>' for x in related)
    tpl=open("templates/article.html",encoding="utf-8").read()
    tpl=tpl.replace("{{TITLE}}",html.escape(a["title"]+" | المضارب PRO")).replace("{{DESCRIPTION}}",html.escape(a["excerpt"])).replace("{{SLUG}}",html.escape(a["slug"])).replace("{{CATEGORY}}",html.escape(a["category"])).replace("{{ARTICLE_TITLE}}",html.escape(a["title"])).replace("{{MINUTES}}",str(a["minutes"])).replace("{{CONTENT}}",paras).replace("{{RELATED}}",related_html)
    return HTMLResponse(tpl)
@app.get("/admin",response_class=HTMLResponse)
async def admin(request:Request):
    return page("admin.html","لوحة الإدارة | المضارب PRO")

@app.post("/api/admin/login")
async def api_admin_login(request:Request, username:str=Form(...), password:str=Form(...)):
    configured_user=os.getenv("ADMIN_USERNAME","").strip()
    configured_pass=os.getenv("ADMIN_PASSWORD","").strip()
    if not configured_user or not configured_pass:
        return JSONResponse({"ok":False,"error":"ADMIN_USERNAME و ADMIN_PASSWORD غير مضبوطين في إعدادات السيرفر"},status_code=503)
    if not username or not secrets.compare_digest(username,configured_user):
        return JSONResponse({"ok":False,"error":"اسم المستخدم غير صحيح"},status_code=401)
    if not password or not secrets.compare_digest(password,configured_pass):
        return JSONResponse({"ok":False,"error":"الرقم السري غير صحيح"},status_code=401)
    request.session["admin_access"]=True
    return {"ok":True}

async def admin_guard(request:Request):
    if not request.session.get("admin_access"):
        return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
    return None

async def setting_value(key, default=""):
    async with SessionLocal() as s:
        row=(await s.execute(select(SiteSetting).where(SiteSetting.key==key))).scalar_one_or_none()
        return row.value if row else default

async def set_setting(key,value):
    async with SessionLocal() as s:
        row=(await s.execute(select(SiteSetting).where(SiteSetting.key==key))).scalar_one_or_none()
        if row: row.value=str(value)
        else: s.add(SiteSetting(key=key,value=str(value)))
        await s.commit()

SUBSCRIPTION_PLANS={"10d":{"name":"10 أيام","price":"10 USDT"},"20d":{"name":"20 يوم","price":"30 USDT"},"30d":{"name":"30 يوم","price":"30 USDT"},"60d":{"name":"شهرين","price":"60 USDT"},"90d":{"name":"3 أشهر","price":"90 USDT"},"365d":{"name":"سنة","price":"خصم — تواصل مع الإدارة"}}

@app.get("/subscriptions",response_class=HTMLResponse)
async def subscriptions_page(request:Request):
    return HTMLResponse(page("subscriptions.html","الاشتراكات | المضارب PRO"))

@app.get("/api/subscription-plans")
async def subscription_plans():
    return {"ok":True,"plans":SUBSCRIPTION_PLANS,"binance_pay_id":os.getenv("BINANCE_PAY_ID","").strip(),"usdt_trc20":os.getenv("USDT_TRC20_ADDRESS","").strip()}

@app.get("/api/admin/subscriptions")
async def admin_subscriptions(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        users=(await s.execute(select(User).order_by(User.id.desc()).limit(500))).scalars().all()
        rows=(await s.execute(select(Subscription).order_by(Subscription.expires_at.desc()).limit(500))).scalars().all()
        return {"ok":True,"items":[{"id":x.id,"user_id":x.user_id,"user":next((u.name for u in users if u.id==x.user_id),""),"email":next((u.email for u in users if u.id==x.user_id),""),"plan":x.plan,"started_at":x.started_at.isoformat(),"expires_at":x.expires_at.isoformat(),"status":x.status} for x in rows]}

@app.post("/api/admin/subscriptions")
async def admin_create_subscription(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    body=await request.json()
    email=str(body.get("email","")).strip().lower()
    plan=str(body.get("plan","30d"))
    days={"7d":7,"15d":15,"30d":30,"90d":90,"365d":365}.get(plan)
    if not email or not days: return JSONResponse({"ok":False,"error":"بيانات الاشتراك غير صحيحة"},status_code=400)
    async with SessionLocal() as s:
        u=(await s.execute(select(User).where(User.email==email))).scalar_one_or_none()
        if not u: return JSONResponse({"ok":False,"error":"المستخدم غير موجود"},status_code=404)
        now=datetime.now(timezone.utc)
        active=(await s.execute(select(Subscription).where(Subscription.user_id==u.id,Subscription.status=="active").order_by(Subscription.expires_at.desc()))).scalars().first()
        start=active.expires_at if active and active.expires_at>now else now
        sub=Subscription(user_id=u.id,plan=plan,started_at=now,expires_at=start+__import__("datetime").timedelta(days=days),status="active")
        s.add(sub); await s.commit()
        return {"ok":True,"message":f"تم تفعيل اشتراك {plan} للمستخدم","expires_at":sub.expires_at.isoformat()}

@app.post("/api/admin/subscriptions/{sub_id}/cancel")
async def admin_cancel_subscription(request:Request,sub_id:int):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        sub=(await s.execute(select(Subscription).where(Subscription.id==sub_id))).scalar_one_or_none()
        if not sub: return JSONResponse({"ok":False,"error":"الاشتراك غير موجود"},status_code=404)
        sub.status="cancelled"; await s.commit()
        return {"ok":True}

@app.get("/api/admin/dashboard")
async def admin_dashboard(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        users=(await s.execute(select(User))).scalars().all()
        trades=(await s.execute(select(TradeRecord).order_by(TradeRecord.opened_at.desc()).limit(100))).scalars().all()
    closed=[x for x in trades if x.status=="closed"]
    wins=[x for x in closed if x.pnl_pct>0]
    return {"ok":True,"users":len(users),"active_users":sum(1 for x in users if x.is_active),"trades":len(trades),"open_trades":sum(1 for x in trades if x.status!="closed"),"closed_trades":len(closed),"wins":len(wins),"losses":len(closed)-len(wins),"win_rate":round(len(wins)/len(closed)*100,1) if closed else 0,"pnl_pct":round(sum(x.pnl_pct for x in closed),2),"telegram_configured":bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip() and os.getenv("TELEGRAM_CHAT_ID","").strip()),"reverse_strategy":(await setting_value("reverse_strategy","1"))=="1"}

@app.get("/api/admin/settings")
async def admin_settings(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    keys=["site_name","site_description","maintenance","reverse_strategy","telegram_auto_post","trade_refresh_minutes"]
    return {"ok":True,"settings":{k:await setting_value(k,{"site_name":"المضارب PRO","site_description":"منصة تحليل الأسواق والصفقات","maintenance":"0","reverse_strategy":"1","telegram_auto_post":"0","trade_refresh_minutes":"15"}[k]) for k in keys}}

@app.post("/api/admin/settings")
async def admin_save_settings(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    body=await request.json()
    allowed={"site_name","site_description","maintenance","reverse_strategy","telegram_auto_post","trade_refresh_minutes"}
    for k,v in body.items():
        if k in allowed: await set_setting(k,str(v))
    return {"ok":True,"message":"تم حفظ إعدادات الموقع"}

@app.get("/api/admin/users")
async def admin_users(request:Request):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        rows=(await s.execute(select(User).order_by(User.id.desc()).limit(500))).scalars().all()
        return {"ok":True,"items":[{"id":x.id,"name":x.name,"email":x.email,"is_admin":x.is_admin,"is_active":x.is_active,"created_at":x.created_at.isoformat() if x.created_at else None} for x in rows]}

@app.post("/api/admin/users/{user_id}/toggle")
async def admin_toggle_user(request:Request,user_id:int):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        u=(await s.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if not u: return JSONResponse({"ok":False,"error":"المستخدم غير موجود"},status_code=404)
        u.is_active=not u.is_active; await s.commit()
        return {"ok":True,"is_active":u.is_active}

@app.post("/api/admin/users/{user_id}/admin")
async def admin_toggle_admin(request:Request,user_id:int):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        u=(await s.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
        if not u: return JSONResponse({"ok":False,"error":"المستخدم غير موجود"},status_code=404)
        u.is_admin=not u.is_admin; await s.commit()
        return {"ok":True,"is_admin":u.is_admin}

@app.delete("/api/admin/trades/{trade_id}")
async def admin_delete_trade(request:Request,trade_id:int):
    guard=await admin_guard(request)
    if guard: return guard
    async with SessionLocal() as s:
        t=(await s.execute(select(TradeRecord).where(TradeRecord.id==trade_id))).scalar_one_or_none()
        if not t: return JSONResponse({"ok":False,"error":"الصفقة غير موجودة"},status_code=404)
        await s.delete(t); await s.commit()
        return {"ok":True}

@app.post("/api/admin/trades/{trade_id}/close")
async def admin_close_trade(request:Request,trade_id:int):
    guard=await admin_guard(request)
    if guard: return guard
    body=await request.json()
    price=float(body.get("price") or 0)
    async with SessionLocal() as s:
        t=(await s.execute(select(TradeRecord).where(TradeRecord.id==trade_id))).scalar_one_or_none()
        if not t: return JSONResponse({"ok":False,"error":"الصفقة غير موجودة"},status_code=404)
        if price<=0: price=t.entry
        t.status="closed"; t.close_price=price; t.closed_at=datetime.now(timezone.utc)
        t.pnl_pct=((price-t.entry)/t.entry*100) if t.side=="شراء" else ((t.entry-price)/t.entry*100)
        await s.commit()
        return {"ok":True,"pnl_pct":round(t.pnl_pct,2)}

@app.post("/api/admin/logout")
async def api_admin_logout(request:Request):
    request.session.pop("admin_access",None)
    return {"ok":True}
@app.get("/api/admin/status")
async def api_admin_status(request:Request):
    return {"ok":bool(request.session.get("admin_access"))}

@app.post("/api/admin/telegram/test")
async def admin_telegram_test(request:Request):
    if not request.session.get("admin_access"):
        return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
    ok,msg=await telegram_send("✅ <b>اختبار تيليجرام</b>\nالمضارب PRO متصل بنجاح.")
    return {"ok":ok,"message":msg}

@app.get("/api/admin/telegram/status")
async def admin_telegram_status(request:Request):
    if not request.session.get("admin_access"):
        return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
    return {"ok":True,"configured":bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip() and os.getenv("TELEGRAM_CHAT_ID","").strip())}

@app.post("/api/admin/telegram/post-trade")
async def admin_telegram_post_trade(request:Request):
    if not request.session.get("admin_access"):
        return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
    body=await request.json()
    ok,msg=await telegram_send(format_telegram_trade(body))
    return {"ok":ok,"message":msg}

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
    configs={"spot":"__ALL__","futures":"__ALL__","us":"__ALL__","saudi":"__ALL__","forex":"__ALL__","contracts":"__ALL__"}
    symbols=configs.get(market,[])
    if market=="spot":
        data=await binance("/api/v3/exchangeInfo")
        symbols=[x["symbol"] for x in (data or {}).get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed")]
    elif market in {"futures","contracts"}:
        data=await binance_futures("/fapi/v1/exchangeInfo")
        try:
            symbols=[x["symbol"] for x in (data or {}).get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"]
        except Exception:
            symbols=[]
    elif market=="us":
        symbols=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","NFLX","AMD","ADBE","CRM","ORCL","CSCO","INTC","QCOM","TXN","IBM","JPM","BAC","WFC","GS","V","MA","JNJ","PFE","MRK","LLY","UNH","XOM","CVX","CAT","GE","BA","HON","KO","PEP","WMT","COST","HD","LOW","DIS","NKE","MCD","SBUX","T","VZ","SPY","QQQ","IWM","DIA","PLTR","COIN","MSTR","ARM","MU","SMCI","RIVN","SOFI"]
    elif market=="saudi":
        symbols=["2222.SR","1120.SR","2010.SR","7010.SR","1180.SR","1211.SR","1010.SR","2020.SR","3030.SR","4001.SR","4030.SR","4090.SR","4100.SR","4200.SR","4261.SR","4262.SR","4263.SR","4280.SR","4290.SR","4300.SR","4310.SR","4320.SR","4321.SR","4322.SR","4330.SR","4340.SR","4003.SR","4004.SR","4005.SR","4007.SR","4008.SR","4009.SR","4013.SR","4015.SR","4020.SR","4021.SR","4023.SR","4025.SR","4031.SR","4050.SR","4051.SR","4052.SR","4061.SR","4070.SR","4080.SR","4110.SR","4130.SR","4141.SR","4142.SR","4150.SR","4160.SR","4170.SR","4180.SR","4190.SR","4210.SR","4220.SR","4230.SR","4240.SR","4250.SR","4270.SR","4342.SR","5110.SR","6004.SR","6010.SR","6040.SR","6050.SR","6060.SR","6090.SR","7020.SR","7030.SR","7040.SR","7200.SR","7201.SR","7202.SR","7203.SR","7204.SR"]
    elif market=="forex":
        symbols=["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","AUDUSD=X","NZDUSD=X","USDCAD=X","EURGBP=X","EURJPY=X","GBPJPY=X","AUDJPY=X","CHFJPY=X","EURAUD=X","EURCAD=X","GBPAUD=X","GBPCAD=X","AUDCAD=X","NZDJPY=X","USDSAR=X","USDTRY=X","GC=F","SI=F","CL=F","BZ=F","NG=F","HG=F"]
    intervals={"5د":"5m","15د":"15m","1س":"1h","4س":"4h","يومي":"1d","أسبوعي":"1w","شهري":"1M"}
    interval=intervals.get(timeframe,"15m")
    timeframe=timeframe if timeframe in intervals else "15د"
    out=[]
    if market in {"spot","futures","contracts"}:
        # Scan a bounded set concurrently so the page does not sit waiting on hundreds of sequential requests.
        symbols=symbols[:70]
        source="/fapi/v1/klines" if market in {"futures","contracts"} else "/api/v3/klines"
        base="https://fapi.binance.com" if market in {"futures","contracts"} else BINANCE
        sem=asyncio.Semaphore(12)
        async def scan_symbol(symbol):
            async with sem:
                try:
                    if market in {"futures","contracts"}:
                        data=await binance_futures("/fapi/v1/klines",{"symbol":symbol,"interval":interval,"limit":60})
                    else:
                        data=await binance("/api/v3/klines",{"symbol":symbol,"interval":interval,"limit":60},timeframe)
                    if data is None:
                        return None
                    if not isinstance(data,list) or len(data)<20: return None
                    rows=[{"close":float(x[4]),"high":float(x[2]),"low":float(x[3])} for x in data[:-1]]
                    closes=[x["close"] for x in rows]; entry=closes[-1]; prev=closes[-2]; e20=ema(closes[-20:],20); rv=rsi(closes)
                    raw="شراء" if entry>=e20 and entry>=prev else "بيع"
                    side="شراء" if market=="spot" else ("بيع" if raw=="شراء" else "شراء")
                    move=max(0.006,min(0.04,abs(entry/e20-1)*3+abs(rv-50)/1000))
                    stop=entry*(1-move*0.55) if side=="شراء" else entry*(1+move*0.55)
                    t1=entry*(1+move) if side=="شراء" else entry*(1-move)
                    t2=entry*(1+move*1.8) if side=="شراء" else entry*(1-move*1.8)
                    t3=entry*(1+move*2.6) if side=="شراء" else entry*(1-move*2.6)
                    confidence=round(min(99,60+abs(rv-50)*0.8+abs(entry/e20-1)*800),1)
                    return {"symbol":symbol,"market":market,"timeframe":timeframe,"side":side,"entry":entry,"tp1":t1,"tp2":t2,"tp3":t3,"stop":stop,"confidence":confidence,"rsi":round(rv,1),"movement":round(move*100,2),"time":datetime.now(timezone.utc).isoformat()}
                except Exception:
                    return None
        scanned=await asyncio.gather(*(scan_symbol(s) for s in symbols))
        out.extend(x for x in scanned if x)
    else:
        for symbol in symbols:
            try:
                q=await yahoo_chart(symbol,{"interval":interval,"range":"7d" if interval in {"5m","15m","1h"} else "1mo"})
                if q is None:
                    continue
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


async def trade_tracker_data(market="all", timeframe=None):
    """Read the persistent trade tracker and return rows + aggregate stats."""
    market=(market or "all").lower().strip()
    tf=timeframe if timeframe in TRADE_INTERVALS else None
    async with SessionLocal() as s:
        q=select(TradeRecord).order_by(TradeRecord.id.desc())
        if market not in {"", "all"}:
            q=q.where(TradeRecord.market==market)
        if tf:
            q=q.where(TradeRecord.timeframe==tf)
        rows=(await s.execute(q)).scalars().all()
        items=[]
        wins=losses=0
        pnl=0.0
        for rec in rows:
            item={
                "id":rec.id,"symbol":rec.symbol,"market":rec.market,
                "timeframe":rec.timeframe,"side":rec.side,"entry":rec.entry,
                "tp1":rec.tp1,"tp2":rec.tp2,"tp3":rec.tp3,"stop":rec.stop,
                "confidence":rec.confidence,"rsi":rec.rsi,"status":rec.status,
                "reached_tp1":bool(rec.reached_tp1),"reached_tp2":bool(rec.reached_tp2),
                "reached_tp3":bool(rec.reached_tp3),"opened_at":rec.opened_at.isoformat() if rec.opened_at else None,
                "closed_at":rec.closed_at.isoformat() if rec.closed_at else None,
                "close_price":rec.close_price,"pnl_pct":rec.pnl_pct or 0,
            }
            items.append(item)
            if rec.status=="closed":
                if (rec.pnl_pct or 0)>0: wins+=1
                else: losses+=1
                pnl+=float(rec.pnl_pct or 0)
        closed=wins+losses
        return items,{
            "total":len(rows),"open":sum(1 for x in rows if x.status=="open"),
            "closed":closed,"wins":wins,"losses":losses,
            "pnl_pct":round(pnl,2),"win_rate":round((wins/closed*100) if closed else 0,1)
        }

@app.get("/api/trades")
async def trades_api(timeframe:str|None=None, market:str|None=None):
    tf=timeframe if timeframe in TRADE_INTERVALS else "15د"
    mk=(market or "spot").lower().strip()
    if mk in MARKETS_TO_PRECOMPUTE:
        key=(mk,tf)
        cached=MARKET_TRADE_CACHE.get(key)
        if cached and time.time()-cached["at"] < timeframe_seconds(tf):
            live=cached["items"]
        else:
            # First request only: build once and save it. Future requests are instant.
            result=await market_trades_api(mk,tf)
            live=result.get("items",[]) if isinstance(result,dict) else []
            # Never erase a valid snapshot because one refresh returned zero items.
            if live:
                MARKET_TRADE_CACHE[key]={"at":time.time(),"items":live}
            elif cached:
                live=cached["items"]
        await sync_trade_records(live)
        items,stats=await trade_tracker_data(mk,timeframe)
        return {"ok":True,"items":items,"live":live,"stats":stats,"timeframes":list(TRADE_INTERVALS),"cached_at":MARKET_TRADE_CACHE.get(key,{}).get("at"),"updated":datetime.now(timezone.utc).isoformat()}
    await build_trades(timeframe if timeframe in TRADE_INTERVALS else None)
    items,stats=await trade_tracker_data("spot",timeframe)
    return {"ok":True,"items":items,"live":items,"stats":stats,"timeframes":list(TRADE_INTERVALS),"updated":datetime.now(timezone.utc).isoformat()}

@app.get("/api/trade-tracker")
async def trade_tracker_api(market:str="all", timeframe:str="الكل"):
    items,stats=await trade_tracker_data(market,timeframe)
    return {"ok":True,"items":items,"stats":stats,"updated":datetime.now(timezone.utc).isoformat()}

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
