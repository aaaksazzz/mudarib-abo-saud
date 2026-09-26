from fastapi import FastAPI,HTTPException,Request,Response,Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import httpx,asyncio,os,hashlib,hmac,secrets,base64,time
from db import init_db,rows,one,execute
from strategy import signal_from_klines

app=FastAPI(title="التداول الذكي PRO",version="4.0")
DATA_SEM=asyncio.Semaphore(8)
DATA_CACHE={}
SCAN_CACHE={}
CACHE_TTL=180
SCAN_TTL=90
HTTP_CLIENT=None
BASE=Path(__file__).parent
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
SECRET=os.getenv("APP_SECRET") or secrets.token_urlsafe(48)
ADMIN_EMAIL=os.getenv("ADMIN_EMAIL","admin@example.com").lower()
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","change-me-now")

class AuthIn(BaseModel): email:str; password:str
class NewsIn(BaseModel): title:str; body:str=""; source:str="النظام"
class TradeIn(BaseModel):
    market:str; symbol:str; timeframe:str="15m"; side:str; entry:float; tp1:float; tp2:float; tp3:float; sl:float; ai:float=0
class RoleIn(BaseModel):
    role:str
class SettingIn(BaseModel):
    key:str; value:str

def hash_pw(p):
    salt=secrets.token_bytes(16); key=hashlib.pbkdf2_hmac("sha256",p.encode(),salt,120000)
    return base64.urlsafe_b64encode(salt+key).decode()
def verify_pw(p,s):
    try:
        raw=base64.urlsafe_b64decode(s.encode())
        return hmac.compare_digest(raw[16:],hashlib.pbkdf2_hmac("sha256",p.encode(),raw[:16],120000))
    except:return False
def make_token(uid,role):
    raw=f"{uid}:{role}:{int(time.time())}".encode()
    return base64.urlsafe_b64encode(raw).decode()+"."+hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()
def get_user(request):
    t=request.cookies.get("session")
    if not t or "." not in t:return None
    try:
        a,s=t.split(".",1);raw=base64.urlsafe_b64decode(a.encode());p=raw.decode().split(":")
        if len(p)!=3 or time.time()-int(p[2])>604800:return None
        if not hmac.compare_digest(hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest(),s):return None
        return one("SELECT id,email,role,created_at FROM users WHERE id=?",(int(p[0]),))
    except:return None
def user_required(request):
    u=get_user(request)
    if not u:raise HTTPException(401,"يجب تسجيل الدخول")
    return u
def admin_required(request):
    u=user_required(request)
    if u["role"]!="admin":raise HTTPException(403,"صلاحية الإدارة مطلوبة")
    return u

@app.on_event("startup")
async def startup():
    global HTTP_CLIENT
    init_db()
    HTTP_CLIENT=httpx.AsyncClient(timeout=12,headers={"User-Agent":"Trading-Pro/4.0"})
    if not one("SELECT id FROM users WHERE email=?",(ADMIN_EMAIL,)):
        execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",(ADMIN_EMAIL,hash_pw(ADMIN_PASSWORD),"admin"))
    asyncio.create_task(worker())

@app.on_event("shutdown")
async def shutdown():
    global HTTP_CLIENT
    if HTTP_CLIENT:
        await HTTP_CLIENT.aclose()
        HTTP_CLIENT=None

@app.get("/health")
def health():return {"status":"ok","service":"trading-pro","version":"4.0"}

@app.get("/")
@app.get("/spot")
@app.get("/futures")
@app.get("/contracts")
@app.get("/scanner")
@app.get("/saudi")
@app.get("/us")
@app.get("/forex")
@app.get("/trades")
@app.get("/tracker")
@app.get("/news")
@app.get("/blog")
@app.get("/account")
@app.get("/admin")
def page():return FileResponse(BASE/"static/index.html")

@app.post("/api/auth/register")
def register(data:AuthIn,response:Response):
    email=data.email.strip().lower()
    if len(data.password)<6:raise HTTPException(400,"كلمة المرور 6 أحرف على الأقل")
    if one("SELECT id FROM users WHERE email=?",(email,)):raise HTTPException(409,"الحساب موجود")
    uid=execute("INSERT INTO users(email,password_hash) VALUES(?,?)",(email,hash_pw(data.password)))
    response.set_cookie("session",make_token(uid,"user"),httponly=True,samesite="lax",max_age=604800)
    return {"ok":True,"email":email,"role":"user"}
@app.post("/api/auth/login")
def login(data:AuthIn,response:Response):
    u=one("SELECT * FROM users WHERE email=?",(data.email.strip().lower(),))
    if not u or not verify_pw(data.password,u["password_hash"]):raise HTTPException(401,"بيانات الدخول غير صحيحة")
    response.set_cookie("session",make_token(u["id"],u["role"]),httponly=True,samesite="lax",max_age=604800)
    return {"ok":True,"email":u["email"],"role":u["role"]}
@app.post("/api/auth/logout")
def logout(response:Response):response.delete_cookie("session");return {"ok":True}
@app.get("/api/auth/me")
def me(request:Request):
    u=get_user(request);return {"authenticated":bool(u),"user":u}

MARKETS={
"spot":{"label":"سبوت","icon":"🟢","provider":"binance","symbols":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","SUIUSDT","TRXUSDT","DOTUSDT","LTCUSDT","BCHUSDT","UNIUSDT","ATOMUSDT","NEARUSDT","APTUSDT","FILUSDT","ETCUSDT"]},
"futures":{"label":"فيوتشر","icon":"🔴","provider":"binance","symbols":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","SUIUSDT"]},
"contracts":{"label":"العقود","icon":"📈","provider":"yahoo","symbols":["ES=F","NQ=F","YM=F","RTY=F","GC=F","CL=F"]},
"us":{"label":"أمريكي","icon":"🇺🇸","provider":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","NFLX","AVGO"]},
"saudi":{"label":"السعودي","icon":"🇸🇦","provider":"yahoo","symbols":["2222.SR","1120.SR","2010.SR","1180.SR","2380.SR","7010.SR","2280.SR","1150.SR"]},
"forex":{"label":"فوركس وذهب","icon":"💱","provider":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","GC=F","SI=F","CL=F"]}}

async def get_binance(s,tf,futures=False):
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=12)
        try:
            r=await c.get(("https://fapi.binance.com/fapi/v1/klines" if futures else "https://api.binance.com/api/v3/klines"),params={"symbol":s,"interval":tf,"limit":250})
            r.raise_for_status()
            return r.json()
        finally:
            if c is not HTTP_CLIENT:
                await c.aclose()
async def get_yahoo(s,tf):
    im={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    rm={"15m":"10d","30m":"60d","1h":"1mo","4h":"3mo","1d":"1y","1w":"5y","1M":"10y"}
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=12,headers={"User-Agent":"Mozilla/5.0"})
        try:
            r=await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}",params={"interval":im.get(tf,"15m"),"range":rm.get(tf,"1mo")})
            r.raise_for_status()
            payload=r.json()
        finally:
            if c is not HTTP_CLIENT:
                await c.aclose()
        result=(payload.get("chart") or {}).get("result") or []
        if not result:return []
        quote=((result[0].get("indicators") or {}).get("quote") or [])
        if not quote:return []
        q=quote[0] or {}
    out=[];cl=q.get("close",[]) or [];vol=q.get("volume",[]) or []
    for i,v in enumerate(cl):
        if v is not None:out.append([0,0,0,0,v,(vol[i] if i<len(vol) and vol[i] else 0)])
    return out
async def candles(m,s,tf):
    key=(m,s,tf); now=time.monotonic()
    hit=DATA_CACHE.get(key)
    if hit and now-hit[0] < CACHE_TTL:return hit[1]
    data=await (get_binance(s,tf,m=="futures") if MARKETS[m]["provider"]=="binance" else get_yahoo(s,tf))
    DATA_CACHE[key]=(now,data)
    if len(DATA_CACHE)>600:
        for k in sorted(DATA_CACHE,key=lambda k:DATA_CACHE[k][0])[:100]: DATA_CACHE.pop(k,None)
    return data
def make_signal(k,m):
    x=signal_from_klines(k,reverse=True)
    if m=="spot" and x and x["side"]!="شراء":return None
    return x

@app.get("/api/markets")
def markets():return {k:{"label":v["label"],"icon":v["icon"],"provider":v["provider"],"symbols":v["symbols"]} for k,v in MARKETS.items()}
MARKET_KEYS=tuple(MARKETS.keys())
VALID_TFS=("15m","30m","1h","4h","1d","1w","1M")
def require_market(market):
    market=market.lower().strip()
    if market not in MARKETS: raise HTTPException(404,"القسم غير موجود")
    return market
def require_tf(timeframe):
    if timeframe not in VALID_TFS: raise HTTPException(400,"الفريم غير صالح")
    return timeframe
async def scan_one_market(market,timeframe):
    market=require_market(market); timeframe=require_tf(timeframe)
    key=(market,timeframe); now=time.monotonic()
    hit=SCAN_CACHE.get(key)
    if hit and now-hit[0] < SCAN_TTL:
        return hit[1]
    async def check(symbol):
        try:
            k=await candles(market,symbol,timeframe)
            if not k or len(k)<25:return None
            x=make_signal(k,market)
            return {"market":market,"symbol":symbol,"price":float(k[-1][4]),"timeframe":timeframe,"signal":x} if x else None
        except Exception:return None
    found=[x for x in await asyncio.gather(*(check(s) for s in MARKETS[market]["symbols"])) if x]
    result=sorted(found,key=lambda x:float((x.get("signal") or {}).get("ai") or 0),reverse=True)
    SCAN_CACHE[key]=(time.monotonic(),result)
    return result
@app.get("/api/section/{market}/trades")
def section_trades(market:str,timeframe="15m",limit:int=100):
    market=require_market(market); timeframe=require_tf(timeframe)
    return rows("SELECT * FROM trades WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT ?",(market,timeframe,min(limit,200)))
@app.get("/api/section/{market}/stats")
def section_stats(market:str,period="all"):
    market=require_market(market)
    if period not in {"all","day","week","month","year"}: raise HTTPException(400,"الفترة غير صالحة")
    where=" WHERE market=?"; args=[market]
    if period!="all":
        days={"day":1,"week":7,"month":30,"year":365}[period]
        where+=" AND created_at >= datetime('now', ?)"; args.append(f"-{days} days")
    total=one("SELECT COUNT(*) n FROM trades"+where,tuple(args))["n"]
    closed=one("SELECT COUNT(*) n FROM trades"+where+" AND status='closed'",tuple(args))["n"]
    wins=one("SELECT COUNT(*) n FROM trades"+where+" AND status='closed' AND pnl>0",tuple(args))["n"]
    pnl=one("SELECT COALESCE(SUM(pnl),0) n FROM trades"+where+" AND status='closed'",tuple(args))["n"]
    return {"market":market,"period":period,"open":total-closed,"closed":closed,"wins":wins,"losses":closed-wins,"win_rate":round(wins/closed*100,2) if closed else None,"pnl":round(pnl,4)}
@app.get("/api/section/{market}/scanner")
async def section_scanner(market:str,timeframe="15m"):
    return await scan_one_market(market,timeframe)

@app.get("/api/scanner")
async def scanner(market="spot",timeframe="15m"):
    return await scan_one_market(market,timeframe)

@app.get("/api/trades")
def trades(market="spot",timeframe="15m",limit:int=100):return rows("SELECT * FROM trades WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT ?",(market,timeframe,min(limit,200)))
@app.get("/api/all-trades")
def all_trades(timeframe="15m",limit:int=100):return rows("SELECT * FROM trades WHERE timeframe=? ORDER BY id DESC LIMIT ?",(timeframe,min(limit,200)))
@app.get("/api/platform/summary")
def platform_summary():
    total=one("SELECT COUNT(*) n FROM trades")["n"]
    closed=one("SELECT COUNT(*) n FROM trades WHERE status='closed'")["n"]
    wins=one("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl>0")["n"]
    return {"open":total-closed,"closed":closed,"win_rate":round(wins/closed*100,2) if closed else None}

def trade_live_state(t,p):
    entry=float(t["entry"] or 0); sl=float(t["sl"] or 0); tp1=float(t["tp1"] or 0); tp2=float(t["tp2"] or 0); tp3=float(t["tp3"] or 0)
    buy=t["side"]=="شراء"
    if not entry:return {"state":"open","progress":0,"live_pnl":0}
    live=((p-entry)/entry*100) if buy else ((entry-p)/entry*100)
    if buy:
        progress=max(0,min(100,((p-entry)/(tp3-entry))*100)) if tp3>entry else 0
        state="SL" if p<=sl else ("TP3" if p>=tp3 else ("TP2" if p>=tp2 else ("TP1" if p>=tp1 else "مفتوحة")))
    else:
        progress=max(0,min(100,((entry-p)/(entry-tp3))*100)) if tp3<entry else 0
        state="SL" if p>=sl else ("TP3" if p<=tp3 else ("TP2" if p<=tp2 else ("TP1" if p<=tp1 else "مفتوحة")))
    return {"state":state,"progress":round(progress,1),"live_pnl":round(live,3),"price":p}

@app.get("/api/tracker")
async def tracker(period="all",market="all"):
    if period not in {"all","day","week","month","year"}: raise HTTPException(400,"الفترة غير صالحة")
    if market!="all": market=require_market(market)
    where=[]; args=[]
    if market!="all": where.append("market=?"); args.append(market)
    if period!="all":
        days={"day":1,"week":7,"month":30,"year":365}[period]
        where.append("created_at >= datetime('now', ?)"); args.append(f"-{days} days")
    clause=(" WHERE "+" AND ".join(where)) if where else ""
    data=rows("SELECT * FROM trades"+clause+" ORDER BY id DESC LIMIT 100",tuple(args))
    async def enrich(t):
        x=dict(t)
        if x["status"]=="open":
            try:
                k=await candles(x["market"],x["symbol"],x["timeframe"])
                p=float(k[-1][4])
                x.update(trade_live_state(x,p))
            except:
                x.update({"state":"بانتظار السعر","progress":0,"live_pnl":0,"price":x["entry"]})
        else:
            x.update({"state":"مغلقة","progress":100 if (x["pnl"] or 0)>0 else 0,"live_pnl":x["pnl"] or 0,"price":None})
        return x
    enriched=await asyncio.gather(*(enrich(t) for t in data))
    closed=[x for x in enriched if x["status"]=="closed"]
    wins=sum(1 for x in closed if (x["pnl"] or 0)>0)
    pnl=sum(float(x["pnl"] or 0) for x in closed)
    live=sum(float(x.get("live_pnl") or 0) for x in enriched if x["status"]=="open")
    market_pnl={}
    tf_pnl={}
    for x in closed:
        market_pnl[x["market"]]=market_pnl.get(x["market"],0)+float(x["pnl"] or 0)
        tf_pnl[x["timeframe"]]=tf_pnl.get(x["timeframe"],0)+float(x["pnl"] or 0)
    best_trade=max(closed,key=lambda x:float(x["pnl"] or 0),default=None)
    avg_ai=sum(float(x["ai"] or 0) for x in enriched)/len(enriched) if enriched else 0
    best_market=max(market_pnl,key=market_pnl.get,default=None)
    best_tf=max(tf_pnl,key=tf_pnl.get,default=None)
    return {"items":enriched,"stats":{"total":len(enriched),"open":sum(x["status"]=="open" for x in enriched),"closed":len(closed),"wins":wins,"losses":len(closed)-wins,"win_rate":round(wins/len(closed)*100,2) if closed else None,"pnl":round(pnl,3),"live_pnl":round(live,3),"avg_ai":round(avg_ai,1),"best_market":best_market,"best_tf":best_tf,"best_trade":({"symbol":best_trade["symbol"],"pnl":best_trade["pnl"]} if best_trade else None)}}

@app.get("/api/stats")
def stats(period="all"):
    where=""
    args=()
    if period in {"day","week","month","year"}:
        days={"day":1,"week":7,"month":30,"year":365}[period]
        where=" WHERE created_at >= datetime('now', ?)"
        args=(f"-{days} days",)
    total=one("SELECT COUNT(*) n FROM trades"+where,args)["n"]
    closed=one("SELECT COUNT(*) n FROM trades"+(where+" AND status='closed'" if where else " WHERE status='closed'"),args)["n"]
    wins=one("SELECT COUNT(*) n FROM trades"+(where+" AND status='closed' AND pnl>0" if where else " WHERE status='closed' AND pnl>0"),args)["n"]
    pnl=one("SELECT COALESCE(SUM(pnl),0) n FROM trades"+(where+" AND status='closed'" if where else " WHERE status='closed'"),args)["n"]
    return {"period":period,"open":total-closed,"closed":closed,"wins":wins,"losses":closed-wins,"win_rate":round(wins/closed*100,2) if closed else None,"pnl":round(pnl,4)}
@app.get("/api/market/{symbol}")
async def market(symbol:str,market="spot",timeframe="15m"):
    market=require_market(market); timeframe=require_tf(timeframe)
    try:
        k=await candles(market,symbol.upper(),timeframe)
        if not k or len(k)<2: raise HTTPException(502,"لا توجد بيانات كافية للسوق")
        return {"market":market,"symbol":symbol.upper(),"timeframe":timeframe,"price":float(k[-1][4]),"signal":make_signal(k,market)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"تعذر جلب بيانات السوق حالياً")
async def save_signal(m,s,tf,x):
    if not x:return
    if one("SELECT id FROM trades WHERE market=? AND symbol=? AND timeframe=? AND status='open'",(m,s,tf)):return
    execute("INSERT INTO trades(market,symbol,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(m,s,tf,x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x["sl"],x["ai"],"open"))
async def scan_store():
    for m in MARKETS:
        try:
            result=await scanner(m,"15m")
            for x in result[:20]:await save_signal(m,x["symbol"],"15m",x["signal"])
        except:pass
async def monitor():
    trades=rows("SELECT * FROM trades WHERE status='open' ORDER BY id DESC LIMIT 150")
    async def check(t):
        try:
            k=await candles(t["market"],t["symbol"],t["timeframe"])
            if not k:return
            p=float(k[-1][4]); buy=t["side"]=="شراء"; hit=None
            if buy:
                if p<=float(t["sl"]):
                    hit=-2; col="sl_hit_at"
                elif p>=float(t["tp1"]):
                    hit=2; col="tp1_hit_at"
                else:return
            else:
                if p>=float(t["sl"]):
                    hit=-2; col="sl_hit_at"
                elif p<=float(t["tp1"]):
                    hit=2; col="tp1_hit_at"
                else:return
            execute(f"UPDATE trades SET {col}=COALESCE({col},CURRENT_TIMESTAMP),status='closed',closed_at=CURRENT_TIMESTAMP,pnl=? WHERE id=?",(hit,t["id"]))
        except Exception:
            return
    await asyncio.gather(*(check(t) for t in trades))
async def worker():
    await asyncio.sleep(3)
    while True:
        try:await scan_store();await monitor()
        except:pass
        await asyncio.sleep(900)
@app.get("/api/news")
def news():return rows("SELECT * FROM news ORDER BY id DESC LIMIT 50")
@app.post("/api/admin/news")
def add_news(data:NewsIn,user=Depends(admin_required)):return {"id":execute("INSERT INTO news(title,body,source) VALUES(?,?,?)",(data.title,data.body,data.source))}
@app.get("/api/admin/trades")
def admin_trades(user=Depends(admin_required)):
    return rows("SELECT * FROM trades ORDER BY id DESC LIMIT 300")

@app.post("/api/admin/trades")
def admin_create_trade(data:TradeIn,user=Depends(admin_required)):
    market=require_market(data.market); timeframe=require_tf(data.timeframe)
    if data.side not in {"شراء","بيع"}: raise HTTPException(400,"الاتجاه غير صالح")
    tid=execute("INSERT INTO trades(market,symbol,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(market,data.symbol.upper(),timeframe,data.side,data.entry,data.tp1,data.tp2,data.tp3,data.sl,data.ai,"open","admin"))
    return {"ok":True,"id":tid}

@app.delete("/api/admin/trades/{trade_id}")
def admin_delete_trade(trade_id:int,user=Depends(admin_required)):
    if not one("SELECT id FROM trades WHERE id=?",(trade_id,)): raise HTTPException(404,"الصفقة غير موجودة")
    execute("DELETE FROM trades WHERE id=?",(trade_id,))
    return {"ok":True}

@app.post("/api/admin/trades/{trade_id}/close")
def admin_close_trade(trade_id:int,user=Depends(admin_required)):
    if not one("SELECT id FROM trades WHERE id=?",(trade_id,)): raise HTTPException(404,"الصفقة غير موجودة")
    execute("UPDATE trades SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=?",(trade_id,))
    return {"ok":True}

@app.post("/api/admin/users/{user_id}/role")
def admin_set_role(user_id:int,data:RoleIn,user=Depends(admin_required)):
    if data.role not in {"user","admin"}: raise HTTPException(400,"الدور غير صالح")
    if not one("SELECT id FROM users WHERE id=?",(user_id,)): raise HTTPException(404,"المستخدم غير موجود")
    execute("UPDATE users SET role=? WHERE id=?",(data.role,user_id))
    return {"ok":True}

@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id:int,user=Depends(admin_required)):
    if int(user["id"])==user_id: raise HTTPException(400,"لا يمكن حذف المدير الحالي")
    if not one("SELECT id FROM users WHERE id=?",(user_id,)): raise HTTPException(404,"المستخدم غير موجود")
    execute("DELETE FROM users WHERE id=?",(user_id,))
    return {"ok":True}

@app.delete("/api/admin/news/{news_id}")
def admin_delete_news(news_id:int,user=Depends(admin_required)):
    if not one("SELECT id FROM news WHERE id=?",(news_id,)): raise HTTPException(404,"الخبر غير موجود")
    execute("DELETE FROM news WHERE id=?",(news_id,))
    return {"ok":True}

@app.get("/api/admin/settings")
def admin_settings(user=Depends(admin_required)):
    return rows("SELECT key,value FROM settings ORDER BY key")

@app.post("/api/admin/settings")
def admin_save_setting(data:SettingIn,user=Depends(admin_required)):
    if not data.key.strip(): raise HTTPException(400,"المفتاح مطلوب")
    execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(data.key.strip(),data.value))
    return {"ok":True}

@app.get("/api/admin/summary")
def admin_summary(user=Depends(admin_required)):return {"users":one("SELECT COUNT(*) n FROM users")["n"],"trades":one("SELECT COUNT(*) n FROM trades")["n"],"open":one("SELECT COUNT(*) n FROM trades WHERE status='open'")["n"],"closed":one("SELECT COUNT(*) n FROM trades WHERE status='closed'")["n"]}
@app.get("/api/admin/users")
def admin_users(user=Depends(admin_required)):return rows("SELECT id,email,role,created_at FROM users ORDER BY id DESC LIMIT 200")
@app.post("/api/admin/telegram-test")
async def telegram_test(user=Depends(admin_required)):
    token=os.getenv("TELEGRAM_BOT_TOKEN");chat=os.getenv("TELEGRAM_CHAT_ID","@tadol1")
    if not token:return {"ok":False,"message":"ضع TELEGRAM_BOT_TOKEN في متغيرات البيئة"}
    async with httpx.AsyncClient(timeout=10) as c:r=await c.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":"✅ اختبار Telegram من التداول الذكي PRO"})
    return {"ok":r.is_success}
@app.post("/api/admin/publish-trade/{trade_id}")
async def publish_trade(trade_id:int,user=Depends(admin_required)):
    t=one("SELECT * FROM trades WHERE id=?",(trade_id,))
    if not t:raise HTTPException(404,"الصفقة غير موجودة")
    token=os.getenv("TELEGRAM_BOT_TOKEN");chat=os.getenv("TELEGRAM_CHAT_ID","@tadol1")
    if not token:raise HTTPException(503,"Telegram غير مضبوط")
    msg=f"📊 {t['symbol']} · {t['market']}\n{t['side']} · {t['timeframe']}\nالدخول: {t['entry']}\nTP1: {t['tp1']}\nTP2: {t['tp2']}\nTP3: {t['tp3']}\nSL: {t['sl']}\nAI: {t['ai']}%\n⚡ تحديث مباشر"
    async with httpx.AsyncClient(timeout=10) as c:r=await c.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg})
    if r.is_success:execute("UPDATE trades SET telegram_sent=1 WHERE id=?",(trade_id,))
    return {"ok":r.is_success}