from fastapi import FastAPI,HTTPException,Request,Response,Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import httpx,asyncio,os,hashlib,hmac,secrets,base64,time,json,xml.etree.ElementTree as ET
from urllib.parse import quote,urlencode,urlparse
from cryptography.fernet import Fernet,InvalidToken
from db import init_db,rows,one,execute
from strategy import signal_from_klines
from strategy_lab import candidates,evaluate,quality

app=FastAPI(title="التداول الذكي PRO",version="4.0")
DATA_SEM=asyncio.Semaphore(8)
DATA_CACHE={}
SCAN_CACHE={}
CACHE_TTL=180
SCAN_TTL=90
HTTP_CLIENT=None
BASE=Path(__file__).parent
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
SECRET=os.getenv("APP_SECRET","").strip()
ADMIN_USERNAME=os.getenv("ADMIN_USERNAME","admin").strip().lower()
ADMIN_EMAIL=os.getenv("ADMIN_EMAIL","").strip().lower()
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","").strip()
SESSION_TTL=60*60*24*7

class AuthIn(BaseModel): email:str; password:str
class NewsIn(BaseModel): title:str; body:str=""; source:str="النظام"
class TradeIn(BaseModel):
    market:str; symbol:str; timeframe:str="15m"; side:str; entry:float; tp1:float; tp2:float; tp3:float; sl:float; ai:float=0
class RoleIn(BaseModel): role:str
class SettingIn(BaseModel): key:str; value:str
class BinanceConnectIn(BaseModel):
    api_key:str
    api_secret:str
class ExecuteIn(BaseModel):
    market:str
    symbol:str
    side:str
    amount:float
    leverage:float=1
    timeframe:str="15m"
    tp1:float|None=None
    tp2:float|None=None
    tp3:float|None=None
    sl:float|None=None

def hash_pw(p):
    salt=secrets.token_bytes(16); key=hashlib.pbkdf2_hmac("sha256",p.encode(),salt,180000)
    return base64.urlsafe_b64encode(salt+key).decode()
def verify_pw(p,s):
    try:
        raw=base64.urlsafe_b64decode(s.encode())
        return hmac.compare_digest(raw[16:],hashlib.pbkdf2_hmac("sha256",p.encode(),raw[:16],180000))
    except Exception:return False

def _session_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_session(user_id):
    token=secrets.token_urlsafe(48)
    execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",(_session_hash(token),int(user_id),int(time.time())+SESSION_TTL))
    return token

def set_session(response,user_id,request=None):
    token=create_session(user_id)
    forwarded=(request.headers.get("x-forwarded-proto","") if request else "").split(",")[0].strip().lower()
    secure=(request.url.scheme=="https" if request else True) or forwarded=="https"
    response.set_cookie("session",token,httponly=True,secure=secure,samesite="lax",max_age=SESSION_TTL,expires=int(time.time())+SESSION_TTL,path="/")

def get_user(request):
    token=request.cookies.get("session","").strip()
    if not token:return None
    s=one("SELECT user_id,expires_at FROM sessions WHERE token_hash=? AND expires_at>?",(_session_hash(token),int(time.time())))
    if not s:return None
    u=one("SELECT id,email,role,created_at FROM users WHERE id=?",(s["user_id"],))
    if not u:
        execute("DELETE FROM sessions WHERE token_hash=?",(_session_hash(token),))
        return None
    # Sliding session: keep an active logged-in admin/user session alive.
    new_expiry=int(time.time())+SESSION_TTL
    if int(s["expires_at"]) < int(time.time())+SESSION_TTL//2:
        execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",(new_expiry,_session_hash(token)))
    return u

def user_required(request):
    u=get_user(request)
    if not u:raise HTTPException(401,"يجب تسجيل الدخول")
    return u
def admin_required(request):
    u=user_required(request)
    if u["role"]!="admin":raise HTTPException(403,"صلاحية الإدارة مطلوبة")
    return u

def check_browser_origin(request:Request):
    origin=request.headers.get("origin")
    if not origin:return
    try:
        origin_host=(urlparse(origin).hostname or "").lower()
        host=(request.headers.get("host") or "").split(":",1)[0].lower()
        forwarded=(request.headers.get("x-forwarded-host") or "").split(",")[0].strip().split(":",1)[0].lower()
        if origin_host not in {x for x in (host,forwarded) if x}:
            raise HTTPException(403,"طلب غير مصرح به")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(403,"طلب غير مصرح به")

def binance_fernet():
    key=os.getenv("BINANCE_ENCRYPTION_KEY","").strip()
    if not key:raise HTTPException(503,"ربط Binance غير مفعّل: ضع BINANCE_ENCRYPTION_KEY في Northflank")
    try:return Fernet(key.encode())
    except Exception:raise HTTPException(503,"BINANCE_ENCRYPTION_KEY غير صالح")

def enc_secret(value:str)->str:return binance_fernet().encrypt(value.strip().encode()).decode()
def dec_secret(value:str)->str:
    try:return binance_fernet().decrypt(value.encode()).decode()
    except Exception:raise HTTPException(503,"تعذر قراءة بيانات Binance")

async def binance_signed(user_id:int,method:str,path:str,params=None,futures=False):
    c=one("SELECT * FROM binance_connections WHERE user_id=?",(user_id,))
    if not c:raise HTTPException(400,"اربط حساب Binance أولاً")
    key=dec_secret(c["api_key_enc"]); secret=dec_secret(c["api_secret_enc"])
    p=dict(params or {});p.setdefault("timestamp",int(time.time()*1000));p.setdefault("recvWindow",5000)
    payload=urlencode(p,doseq=True)
    p["signature"]=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    base="https://fapi.binance.com" if futures else "https://api.binance.com"
    r=await (HTTP_CLIENT or httpx.AsyncClient(timeout=20)).request(method,base+path,params=p,headers={"X-MBX-APIKEY":key})
    if r.status_code>=400:
        try:msg=r.json().get("msg","Binance رفض الطلب")
        except Exception:msg="Binance رفض الطلب"
        raise HTTPException(r.status_code,msg)
    return r.json()

async def binance_public(path,params=None,futures=False):
    base="https://fapi.binance.com" if futures else "https://api.binance.com"
    c=HTTP_CLIENT or httpx.AsyncClient(timeout=15)
    try:
        r=await c.get(base+path,params=params);r.raise_for_status();return r.json()
    finally:
        if c is not HTTP_CLIENT:await c.aclose()

def order_entry_price(data):
    q=float(data.get("cummulativeQuoteQty") or 0);qty=float(data.get("executedQty") or 0)
    if q and qty:return q/qty
    return float(data.get("avgPrice") or 0) or None

@app.on_event("startup")
async def startup():
    global HTTP_CLIENT
    init_db()
    HTTP_CLIENT=httpx.AsyncClient(timeout=25,headers={"User-Agent":"Trading-Pro/4.0"})
    execute("DELETE FROM sessions WHERE expires_at<=?",(int(time.time()),))
    admin_email=ADMIN_EMAIL or (ADMIN_USERNAME+"@admin.local")
    existing=one("SELECT id FROM users WHERE lower(email)=?",(admin_email.lower(),))
    if existing:
        execute("UPDATE users SET role='admin' WHERE id=?",(existing["id"],))
        if ADMIN_PASSWORD:
            execute("UPDATE users SET password_hash=? WHERE id=?",(hash_pw(ADMIN_PASSWORD),existing["id"]))
    elif ADMIN_PASSWORD:
        execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",(admin_email,hash_pw(ADMIN_PASSWORD),"admin"))
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
@app.get("/login")
@app.get("/register")
@app.get("/admin")
def page():return FileResponse(BASE/"static/index.html")

@app.post("/api/auth/register")
def register(data:AuthIn,response:Response,request:Request):
    check_browser_origin(request)
    email=data.email.strip().lower()
    if len(email)<5 or "@" not in email or " " in email:raise HTTPException(400,"اكتب بريد إلكتروني صحيح")
    if len(data.password)<6:raise HTTPException(400,"كلمة المرور 6 أحرف على الأقل")
    if len(data.password)>128:raise HTTPException(400,"كلمة المرور طويلة جداً")
    if one("SELECT id FROM users WHERE lower(email)=?",(email,)):raise HTTPException(409,"الحساب موجود بالفعل")
    uid=execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",(email,hash_pw(data.password),"user"))
    return {"ok":True,"email":email,"role":"user","message":"تم إنشاء الحساب، سجّل الدخول الآن"}

@app.post("/api/auth/login")
def login(data:AuthIn,response:Response,request:Request):
    check_browser_origin(request)
    identifier=data.email.strip().lower()
    if not identifier or not data.password:raise HTTPException(400,"أدخل بيانات الدخول")
    admin_email=ADMIN_EMAIL or (ADMIN_USERNAME+"@admin.local")
    if identifier in {ADMIN_USERNAME, "admin", admin_email.lower()}:
        identifier=admin_email.lower()
    u=one("SELECT * FROM users WHERE lower(email)=?",(identifier,))
    if not u or not verify_pw(data.password,u["password_hash"]):raise HTTPException(401,"بيانات الدخول غير صحيحة")
    set_session(response,u["id"],request)
    return {"ok":True,"email":u["email"],"role":u["role"]}

@app.post("/api/auth/logout")
def logout(request:Request,response:Response):
    check_browser_origin(request)
    token=request.cookies.get("session","").strip()
    if token:execute("DELETE FROM sessions WHERE token_hash=?",(_session_hash(token),))
    response.delete_cookie("session",path="/")
    return {"ok":True}

@app.get("/api/auth/me")
def me(request:Request):
    u=get_user(request)
    return {"authenticated":bool(u),"user":u}

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
    im={"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    rm={"15m":"10d","30m":"10d","1h":"1mo","4h":"3mo","1d":"1y","1w":"5y","1M":"10y"}
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
def strategy_feedback():
    closed=one("SELECT COUNT(*) n FROM trades WHERE status='closed'")["n"]
    wins=one("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl>0")["n"]
    losses=closed-wins
    pnl=one("SELECT COALESCE(SUM(pnl),0) n FROM trades WHERE status='closed'")["n"]
    return {"closed":closed,"wins":wins,"losses":losses,"win_rate":round(wins/closed*100,2) if closed else 0,"pnl":round(float(pnl or 0),4)}

async def run_strategy_lab():
    # Research only: hourly walk-forward optimization. It never fabricates or writes live trades.
    markets=list(MARKETS.keys())
    tfs=("15m","1h")
    for market in markets:
        symbols=MARKETS[market]["symbols"][:2]
        for tf in tfs:
            try:
                datasets={}
                for symbol in symbols:
                    k=await backtest_history(market,symbol,tf,30)
                    if len(k)>=240:
                        datasets[symbol]=k
                if not datasets: continue
                scored=[]
                for p in candidates():
                    trains=[];tests=[]
                    for symbol,k in datasets.items():
                        cut=max(120,int(len(k)*0.70))
                        tr=evaluate(k[:cut],p);te=evaluate(k[cut-120:],p)
                        if tr["trades"] or te["trades"]:
                            trains.append(tr);tests.append(te)
                    if not tests: continue
                    def agg(items):
                        n=sum(x["trades"] for x in items);w=sum(x["wins"] for x in items);r=sum(x["r"] for x in items)
                        gp=sum(max(x["r"],0) for x in items);gl=abs(sum(min(x["r"],0) for x in items))
                        return {"trades":n,"wins":w,"losses":sum(x["losses"] for x in items),"win_rate":round(w/n*100,2) if n else None,"r":round(r,3),"profit_factor":round(gp/gl,3) if gl else None,"max_drawdown_r":round(sum(x["max_drawdown_r"] for x in items),3)}
                    train=agg(trains);test=agg(tests);q=quality(train,test)
                    scored.append((q,p,train,test))
                if not scored: continue
                scored.sort(key=lambda x:x[0],reverse=True)
                best_q,best,btr,bte=scored[0]
                for q,p,tr,te in scored:
                    execute("INSERT INTO strategy_lab_results(market,symbol,timeframe,strategy_name,params_json,train_json,test_json,quality,promoted) VALUES(?,?,?,?,?,?,?,?,0)",
                            (market,",".join(datasets.keys()),tf,p["name"],json.dumps(p,ensure_ascii=False),json.dumps(tr),json.dumps(te),q))
                # Promotion is deliberately strict: out-of-sample positive R, PF >= 1.15 and >=15 OOS trades.
                if best_q>-999 and bte["r"]>0 and (bte["profit_factor"] or 0)>=1.15 and bte["trades"]>=15:
                    execute("UPDATE strategy_active SET strategy_name=?,params_json=?,test_json=?,quality=?,updated_at=CURRENT_TIMESTAMP WHERE market=? AND timeframe=?",
                            (best["name"],json.dumps(best,ensure_ascii=False),json.dumps(bte),best_q,market,tf))
                    if not one("SELECT 1 FROM strategy_active WHERE market=? AND timeframe=?",(market,tf)):
                        execute("INSERT INTO strategy_active(market,timeframe,strategy_name,params_json,test_json,quality) VALUES(?,?,?,?,?,?)",
                                (market,tf,best["name"],json.dumps(best,ensure_ascii=False),json.dumps(bte),best_q))
                    execute("UPDATE strategy_lab_results SET promoted=1 WHERE market=? AND timeframe=? AND strategy_name=? AND created_at=(SELECT MAX(created_at) FROM strategy_lab_results WHERE market=? AND timeframe=?)",(market,tf,best["name"],market,tf))
            except Exception as e:
                print(f"strategy_lab {market}/{tf}: {e}")

@app.get("/api/strategy-lab")
def strategy_lab_api():
    active=rows("SELECT * FROM strategy_active ORDER BY market,timeframe")
    latest=rows("SELECT * FROM strategy_lab_results ORDER BY id DESC LIMIT 100")
    for x in active:
        try:x["params"]=json.loads(x.pop("params_json") or "{}");x["test"]=json.loads(x.pop("test_json") or "{}")
        except Exception:pass
    return {"active":active,"latest":latest,"note":"مرشح بحثي فقط؛ لا يوجد ضمان للربح، والترقية تعتمد على اختبار خارج العينة."}

def make_signal(k,m):
    x=signal_from_klines(k,reverse=True,feedback=strategy_feedback())
    # Saudi market is long-only: only شراء signals are allowed.
    if m in ("spot","saudi") and x and x["side"]!="شراء":return None
    return x

@app.get("/api/markets")
def markets():return {k:{"label":v["label"],"icon":v["icon"],"provider":v["provider"],"symbols":v["symbols"]} for k,v in MARKETS.items()}
MARKET_KEYS=tuple(MARKETS.keys())
VALID_TFS=("5m","15m","30m","1h","4h","1d","1w","1M")
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
            return {"market":market,"symbol":symbol,"price":float(k[-1][4]),"timeframe":timeframe,"candle_open_ms":int(k[-1][0]) if k[-1] and k[-1][0] else None,"signal":x} if x else None
        except Exception:return None
    found=[x for x in await asyncio.gather(*(check(s) for s in MARKETS[market]["symbols"])) if x]
    result=sorted(found,key=lambda x:float((x.get("signal") or {}).get("ai") or 0),reverse=True)
    SCAN_CACHE[key]=(time.monotonic(),result)
    return result
@app.get("/api/section/{market}/trades")
def section_trades(market:str,timeframe="15m",limit:int=100):
    market=require_market(market); timeframe=require_tf(timeframe)
    if market=="saudi":
        return rows("SELECT * FROM trades WHERE market=? AND timeframe=? AND side=? ORDER BY id DESC LIMIT ?",(market,timeframe,"شراء",min(limit,200)))
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


async def binance_spot_backtest_symbols(min_daily_usdt=1_000_000):
    """Return all currently trading USDT spot pairs above the daily quote-volume threshold.
    Stablecoin base assets are excluded so the historical test focuses on volatile assets.
    """
    stable={
        "USDT","USDC","FDUSD","TUSD","DAI","USDP","PYUSD","BUSD","USDE","USDS",
        "EUR","EURI","USD1","USTC","FRAX","LUSD","GUSD","RLUSD"
    }
    url="https://api.binance.com/api/v3/ticker/24hr"
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=25)
        try:
            r=await c.get(url)
            r.raise_for_status()
            data=r.json()
        finally:
            if c is not HTTP_CLIENT: await c.aclose()
    symbols=[]
    for x in data if isinstance(data,list) else []:
        symbol=str(x.get("symbol") or "").upper()
        if not symbol.endswith("USDT"): continue
        base=symbol[:-4]
        if not base or base in stable: continue
        try: volume=float(x.get("quoteVolume") or 0)
        except Exception: continue
        if volume>=float(min_daily_usdt):
            symbols.append((symbol,volume))
    return sorted(symbols,key=lambda x:x[1],reverse=True)


async def backtest_history(market,symbol,timeframe,days=30):
    """Fetch exactly the requested historical window; never writes tracker trades."""
    market=require_market(market); timeframe=require_tf(timeframe)
    if symbol not in MARKETS[market]["symbols"] and not (market=="spot" and symbol.endswith("USDT") and len(symbol)>4):
        raise HTTPException(400,"الرمز غير متاح في هذا السوق")
    days=max(1,min(int(days),3650))
    end_ms=int(time.time()*1000)
    start_ms=end_ms-days*86400000
    if MARKETS[market]["provider"]=="binance":
        base_url="https://fapi.binance.com/fapi/v1/klines" if market=="futures" else "https://api.binance.com/api/v3/klines"
        out=[]; cursor=start_ms
        step_ms={"5m":5*60_000,"15m":15*60_000,"30m":30*60_000,"1h":3600_000,"4h":4*3600_000,"1d":86400_000,"1w":7*86400_000,"1M":31*86400_000}[timeframe]
        while cursor < end_ms and len(out) < 120000:
            params={"symbol":symbol,"interval":timeframe,"limit":1000,"startTime":cursor,"endTime":end_ms}
            async with DATA_SEM:
                c=HTTP_CLIENT or httpx.AsyncClient(timeout=25)
                try:
                    r=await c.get(base_url,params=params); r.raise_for_status(); batch=r.json()
                finally:
                    if c is not HTTP_CLIENT: await c.aclose()
            if not batch: break
            out.extend(batch)
            last=int(batch[-1][0])
            nxt=last+step_ms
            if nxt<=cursor: break
            cursor=nxt
            if len(batch)<1000: break
            await asyncio.sleep(0.03)
        seen=set(); clean=[]
        for k in out:
            ts=int(k[0])
            if start_ms<=ts<=end_ms and ts not in seen:
                seen.add(ts); clean.append(k)
        return sorted(clean,key=lambda x:int(x[0]))
    if timeframe in ("5m","15m","30m") and days>60:
        raise HTTPException(400,"هذا الفريم على Yahoo متاح تاريخياً حتى 60 يوم فقط.")
    im={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    p1=start_ms//1000; p2=end_ms//1000
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=25,headers={"User-Agent":"Mozilla/5.0"})
        try:
            r=await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",params={"interval":im[timeframe],"period1":p1,"period2":p2})
            r.raise_for_status(); payload=r.json()
        finally:
            if c is not HTTP_CLIENT: await c.aclose()
    result=(payload.get("chart") or {}).get("result") or []
    if not result: return []
    q=((result[0].get("indicators") or {}).get("quote") or [{}])[0] or {}
    ts=result[0].get("timestamp") or []
    cl=q.get("close",[]) or []; hi=q.get("high",[]) or []; lo=q.get("low",[]) or []; op=q.get("open",[]) or []; vol=q.get("volume",[]) or []
    out=[]
    for i,t in enumerate(ts):
        if i<len(cl) and cl[i] is not None:
            out.append([int(t)*1000,op[i] if i<len(op) else cl[i],hi[i] if i<len(hi) else cl[i],lo[i] if i<len(lo) else cl[i],cl[i],vol[i] if i<len(vol) and vol[i] else 0])
    if timeframe=="4h":
        grouped={}
        for k in out:
            bucket=(k[0]//(4*3600_000))*(4*3600_000)
            grouped.setdefault(bucket,[]).append(k)
        out=[]
        for bucket,grp in sorted(grouped.items()):
            out.append([bucket,grp[0][1],max(float(x[2]) for x in grp),min(float(x[3]) for x in grp),grp[-1][4],sum(float(x[5] or 0) for x in grp)])
    return out

def historical_test(klines):
    """Walk-forward backtest with no look-ahead and conservative OHLC execution."""
    trades=[]; i=25
    while i < len(klines)-1:
        sig=signal_from_klines(klines[max(0,i-199):i+1],reverse=True,feedback=None)
        if not sig: i+=1; continue
        try:
            entry=float(sig["entry"]); sl=float(sig["sl"]); tp=float(sig["tp3"])
        except Exception:
            i+=1; continue
        risk=abs(entry-sl)
        if entry<=0 or sl<=0 or tp<=0 or risk<=0:
            i+=1; continue
        side=sig["side"]; outcome=None; exit_i=None; exit_price=None
        for j in range(i+1,len(klines)):
            high=float(klines[j][2]); low=float(klines[j][3])
            if side=="شراء": hit_sl=low<=sl; hit_tp=high>=tp
            else: hit_sl=high>=sl; hit_tp=low<=tp
            if hit_sl and hit_tp:
                outcome="loss"; exit_price=sl; exit_i=j; break
            if hit_sl:
                outcome="loss"; exit_price=sl; exit_i=j; break
            if hit_tp:
                outcome="win"; exit_price=tp; exit_i=j; break
        if outcome is None: break
        rr=(abs(exit_price-entry)/risk) if outcome=="win" else -1.0
        trades.append({"side":side,"entry":entry,"sl":sl,"tp":tp,"ai":sig.get("ai"),"outcome":outcome,"r":round(rr,4),"entry_time":int(klines[i][0]),"exit_time":int(klines[exit_i][0])})
        i=exit_i+1
    return trades
@app.get("/api/backtest")
async def backtest(market="spot",timeframe="15m",symbol="",days=30,max_symbols=40):
    market=require_market(market); timeframe=require_tf(timeframe)
    try: days=max(1,min(int(days),3650))
    except Exception: raise HTTPException(400,"عدد الأيام غير صالح")
    requested=symbol.upper().strip()
    try: max_symbols=max(1,min(int(max_symbols),100))
    except Exception: raise HTTPException(400,"عدد العملات غير صالح")
    if requested:
        symbols=[requested]
        volume_map={}
        if market=="spot":
            try:
                eligible=await binance_spot_backtest_symbols(1_000_000)
                volume_map=dict(eligible)
            except Exception:
                volume_map={}
    elif market=="spot":
        eligible=await binance_spot_backtest_symbols(1_000_000)
        symbols=[s for s,v in eligible]
        volume_map=dict(eligible)
    else:
        symbols=MARKETS[market]["symbols"]
        volume_map={}
    symbols=[s for s in symbols if s in MARKETS[market]["symbols"]] if requested else symbols
    if not symbols: raise HTTPException(400,"لا توجد عملات مطابقة لحجم التداول اليومي المطلوب")
    async def one_symbol(s):
        try:
            k=await backtest_history(market,s,timeframe,days)
            t=historical_test(k)
            wins=sum(1 for x in t if x["outcome"]=="win"); losses=sum(1 for x in t if x["outcome"]=="loss"); r=sum(float(x["r"]) for x in t)
            return {"symbol":s,"daily_volume_usdt":round(volume_map.get(s,0),2) if s in volume_map else None,"candles":len(k),"trades":len(t),"wins":wins,"losses":losses,"win_rate":round(wins/len(t)*100,2) if t else None,"r":round(r,2)}
        except Exception as e:
            return {"symbol":s,"daily_volume_usdt":round(volume_map.get(s,0),2) if s in volume_map else None,"candles":0,"trades":0,"wins":0,"losses":0,"win_rate":None,"r":0,"error":str(e)}
    per_symbol=[]
    for batch_start in range(0,len(symbols),2):
        batch=await asyncio.gather(*(one_symbol(s) for s in symbols[batch_start:batch_start+2]))
        per_symbol.extend(batch)
    all_trades_count=sum(x["trades"] for x in per_symbol)
    wins=sum(x["wins"] for x in per_symbol); losses=sum(x["losses"] for x in per_symbol)
    r=sum(float(x["r"]) for x in per_symbol)
    gross_profit=sum(max(float(x["r"]),0) for x in per_symbol)
    gross_loss=abs(sum(min(float(x["r"]),0) for x in per_symbol))
    pf=round(gross_profit/gross_loss,2) if gross_loss else None
    avg_r=round(r/all_trades_count,3) if all_trades_count else None
    return {"ok":True,"market":market,"timeframe":timeframe,"days":days,"min_daily_volume_usdt":1_000_000 if market=="spot" else None,"symbols":len(symbols),"symbol_limit":max_symbols if not requested else 1,"candles":sum(x["candles"] for x in per_symbol),"trades":all_trades_count,"wins":wins,"losses":losses,"win_rate":round(wins/all_trades_count*100,2) if all_trades_count else None,"r":round(r,2),"avg_r":avg_r,"profit_factor":pf,"per_symbol":sorted(per_symbol,key=lambda x:(x["win_rate"] if x["win_rate"] is not None else -1),reverse=True),"method":"walk-forward OHLC, no look-ahead, conservative same-candle handling","note":"Historical test only; results are not written to the trade ledger."}

@app.get("/api/tracker")
async def tracker():
    # Legacy live-trade tracker is intentionally disabled. Historical results use /api/backtest only.
    raise HTTPException(410,"تم إيقاف متابع الصفقات القديم. استخدم النتائج التاريخية /api/backtest.")

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
async def save_signal(m,s,tf,x,candle_open_ms=None):
    if not x:return
    # One active published signal per market/symbol/timeframe.
    # Historical backtests never call this function and never touch the DB.
    existing=one("SELECT id,candle_open_ms FROM trades WHERE market=? AND symbol=? AND timeframe=? AND status='open' ORDER BY id DESC LIMIT 1",(m,s,tf))
    if existing:
        old_ms=int(existing.get("candle_open_ms") or 0)
        new_ms=int(candle_open_ms or 0)
        if new_ms and old_ms==new_ms:
            return
        execute("UPDATE trades SET status='closed',closed_at=CURRENT_TIMESTAMP,pnl=0 WHERE id=? AND status='open'",(existing["id"],))
    execute("INSERT INTO trades(market,symbol,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status,candle_open_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(m,s,tf,x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x["sl"],x["ai"],"open",int(candle_open_ms) if candle_open_ms else None))

async def cleanup_trade_storage():
    # Keep the published trade journal useful without letting scanner history grow forever.
    # Personal Binance orders and historical backtests are separate and are not touched.
    execute("DELETE FROM trades WHERE status='closed' AND closed_at IS NOT NULL AND closed_at < datetime('now','-30 days')")
    execute("""DELETE FROM trades
               WHERE status='closed'
                 AND id IN (
                   SELECT id FROM trades
                   WHERE status='closed'
                   ORDER BY id DESC
                   LIMIT -1 OFFSET 20000
                 )""")

async def scan_store():
    # Store live opportunities across every supported timeframe.
    # Each symbol/timeframe has its own active signal and expires with its candle.
    timeframes=("15m","30m","1h","4h","1d","1w","1M")
    for m in MARKETS:
        for tf in timeframes:
            try:
                result=await scanner(m,tf)
                for x in result[:20]:
                    await save_signal(m,x["symbol"],tf,x["signal"],x.get("candle_open_ms"))
            except Exception as e:
                print(f"scan_store {m}/{tf}: {e}")
    await cleanup_trade_storage()
async def monitor():
    trades=rows("SELECT * FROM trades WHERE status='open' ORDER BY id DESC LIMIT 300")
    async def check(t):
        try:
            k=await candles(t["market"],t["symbol"],t["timeframe"])
            if not k:return
            candle=k[-1]
            close=float(candle[4]); high=float(candle[2]); low=float(candle[3])
            current_candle_ms=int(candle[0]) if candle and candle[0] else 0
            stored_candle_ms=int(t.get("candle_open_ms") or 0)
            if stored_candle_ms and current_candle_ms and current_candle_ms > stored_candle_ms:
                execute("UPDATE trades SET status='closed',closed_at=CURRENT_TIMESTAMP,pnl=0 WHERE id=? AND status='open'",(t["id"],))
                return
            entry=float(t["entry"] or 0); sl=float(t["sl"] or 0); tp1=float(t["tp1"] or 0)
            if entry<=0 or sl<=0 or tp1<=0:return
            buy=t["side"]=="شراء"
            # Use candle high/low, not only the closing price, so overnight
            # TP/SL touches are recorded even when the candle closes back inside.
            if buy:
                if low<=sl:
                    pnl=-abs((sl-entry)/entry*100); col="sl_hit_at"
                elif high>=tp1:
                    pnl=abs((tp1-entry)/entry*100); col="tp1_hit_at"
                else:return
            else:
                if high>=sl:
                    pnl=-abs((sl-entry)/entry*100); col="sl_hit_at"
                elif low<=tp1:
                    pnl=abs((entry-tp1)/entry*100); col="tp1_hit_at"
                else:return
            execute(
                f"UPDATE trades SET {col}=COALESCE({col},CURRENT_TIMESTAMP),"
                "status='closed',closed_at=CURRENT_TIMESTAMP,pnl=? WHERE id=? AND status='open'",
                (round(pnl,4),t["id"])
            )
        except Exception:
            return
    await asyncio.gather(*(check(t) for t in trades))
async def scanner_worker():
    await asyncio.sleep(3)
    while True:
        try:
            await scan_store()
        except Exception as e:
            print(f"scanner_worker: {e}")
        await asyncio.sleep(900)

async def monitor_worker():
    await asyncio.sleep(10)
    while True:
        try:
            await monitor()
        except Exception as e:
            print(f"monitor_worker: {e}")
        # Check open trades frequently so TP/SL touches are recorded overnight.
        await asyncio.sleep(60)

async def strategy_lab_worker():
    await asyncio.sleep(120)
    while True:
        try:
            await run_strategy_lab()
        except Exception as e:
            print(f"strategy_lab_worker: {e}")
        await asyncio.sleep(3600)

async def worker():
    await asyncio.gather(scanner_worker(),monitor_worker(),strategy_lab_worker())
NEWS_QUERIES=[
    ("أسواق المال","financial markets stocks trading"),
    ("العملات الرقمية","Bitcoin crypto markets"),
    ("السوق السعودي","Saudi stocks Tadawul"),
    ("الأسواق الأمريكية","US stocks Nasdaq S&P 500"),
    ("الفوركس والسلع","forex gold oil markets"),
]
async def refresh_news():
    if not HTTP_CLIENT:return
    for source,query in NEWS_QUERIES:
        try:
            url="https://news.google.com/rss/search?q="+quote(query)+"&hl=ar&gl=SA&ceid=SA:ar"
            r=await HTTP_CLIENT.get(url,timeout=12)
            r.raise_for_status()
            root=ET.fromstring(r.text)
            for item in root.findall(".//item")[:5]:
                title=(item.findtext("title") or "").strip()
                desc=(item.findtext("description") or "").strip()
                pub=(item.findtext("pubDate") or "").strip()
                if not title:continue
                if one("SELECT id FROM news WHERE title=?",(title,)):continue
                if len(desc)>1200:desc=desc[:1200]
                execute("INSERT INTO news(title,body,source,created_at) VALUES(?,?,?,COALESCE(?,CURRENT_TIMESTAMP))",(title,desc,source,pub))
        except Exception:
            continue
    execute("DELETE FROM news WHERE id NOT IN (SELECT id FROM news ORDER BY id DESC LIMIT 100)")

@app.get("/api/news")
async def news():
    data=rows("SELECT * FROM news ORDER BY id DESC LIMIT 50")
    if len(data)<10:
        await refresh_news()
        data=rows("SELECT * FROM news ORDER BY id DESC LIMIT 50")
    return data

@app.get("/api/binance/status")
def binance_status(request:Request):
    u=user_required(request);c=one("SELECT id,created_at,updated_at FROM binance_connections WHERE user_id=?",(u["id"],))
    return {"connected":bool(c),"created_at":c["created_at"] if c else None}

@app.post("/api/binance/connect")
async def binance_connect(data:BinanceConnectIn,request:Request):
    check_browser_origin(request)
    u=user_required(request);key=data.api_key.strip();secret=data.api_secret.strip()
    if len(key)<10 or len(secret)<10:raise HTTPException(400,"مفتاح Binance غير صالح")
    p={"timestamp":int(time.time()*1000),"recvWindow":5000};payload=urlencode(p)
    sig=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    c=HTTP_CLIENT or httpx.AsyncClient(timeout=20)
    try:
        r=await c.get("https://api.binance.com/api/v3/account",params={**p,"signature":sig},headers={"X-MBX-APIKEY":key})
        if r.status_code>=400:
            try:msg=r.json().get("msg","بيانات Binance غير صحيحة")
            except Exception:msg="بيانات Binance غير صحيحة"
            raise HTTPException(r.status_code,msg)
    finally:
        if c is not HTTP_CLIENT:await c.aclose()
    # Never accept a credential that can withdraw from the Binance account.
    p2={"timestamp":int(time.time()*1000),"recvWindow":5000};payload2=urlencode(p2)
    sig2=hmac.new(secret.encode(),payload2.encode(),hashlib.sha256).hexdigest()
    c2=HTTP_CLIENT or httpx.AsyncClient(timeout=20)
    try:
        rr=await c2.get("https://api.binance.com/sapi/v1/account/apiRestrictions",params={**p2,"signature":sig2},headers={"X-MBX-APIKEY":key})
        if rr.status_code>=400:raise HTTPException(rr.status_code,"تعذر قراءة صلاحيات مفتاح Binance")
        perms=rr.json()
        if perms.get("enableWithdrawals"):raise HTTPException(400,"اربط مفتاح Binance بدون صلاحية السحب")
    finally:
        if c2 is not HTTP_CLIENT:await c2.aclose()
    execute("INSERT INTO binance_connections(user_id,api_key_enc,api_secret_enc,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET api_key_enc=excluded.api_key_enc,api_secret_enc=excluded.api_secret_enc,updated_at=CURRENT_TIMESTAMP",(u["id"],enc_secret(key),enc_secret(secret)))
    return {"ok":True,"connected":True}

@app.delete("/api/binance/connect")
def binance_disconnect(request:Request):
    check_browser_origin(request)
    u=user_required(request);execute("DELETE FROM binance_connections WHERE user_id=?",(u["id"],));return {"ok":True,"connected":False}

@app.post("/api/binance/execute")
async def binance_execute(data:ExecuteIn,request:Request):
    check_browser_origin(request)
    u=user_required(request);market=require_market(data.market)
    if market not in {"spot","futures"}:raise HTTPException(400,"التنفيذ متاح للسبوت والفيوتشر فقط")
    if data.side not in {"شراء","بيع"}:raise HTTPException(400,"الاتجاه غير صالح")
    if data.amount<=0 or data.amount>1000000:raise HTTPException(400,"المبلغ غير صالح")
    tf=require_tf(data.timeframe);symbol=data.symbol.upper().strip()
    if symbol not in MARKETS[market]["symbols"]:raise HTTPException(400,"الرمز غير متاح للتنفيذ")
    futures=market=="futures"
    current=float((await binance_public("/fapi/v1/ticker/price" if futures else "/api/v3/ticker/price",{"symbol":symbol},futures=futures)).get("price") or 0)
    if current<=0:raise HTTPException(502,"تعذر معرفة السعر الحالي")
    leverage=max(1,min(125,float(data.leverage))) if futures else 1
    qty=0
    if futures:
        await binance_signed(u["id"],"POST","/fapi/v1/leverage",{"symbol":symbol,"leverage":int(leverage)},True)
        info=await binance_public("/fapi/v1/exchangeInfo",futures=True);sym=next((x for x in info.get("symbols",[]) if x.get("symbol")==symbol),None)
        step=min_qty=0
        for f in (sym or {}).get("filters",[]):
            if f.get("filterType")=="LOT_SIZE":step=float(f.get("stepSize") or 0);min_qty=float(f.get("minQty") or 0)
        raw=data.amount*leverage/current;qty=(int(raw/step)*step) if step else raw
        if qty<min_qty or qty<=0:raise HTTPException(400,"المبلغ أقل من الحد الأدنى لـ Binance")
        params={"symbol":symbol,"side":"BUY" if data.side=="شراء" else "SELL","type":"MARKET","quantity":f"{qty:.12f}","newOrderRespType":"RESULT"}
        result=await binance_signed(u["id"],"POST","/fapi/v1/order",params,True)
    else:
        if data.side!="شراء":raise HTTPException(400,"السبوت في المنصة يدعم الشراء فقط حالياً")
        params={"symbol":symbol,"side":"BUY","type":"MARKET","quoteOrderQty":f"{data.amount:.8f}","newOrderRespType":"FULL"}
        result=await binance_signed(u["id"],"POST","/api/v3/order",params,False)
        qty=float(result.get("executedQty") or 0)
    entry=order_entry_price(result) or current;oid=str(result.get("orderId") or "");status=result.get("status","NEW")
    tid=execute("INSERT INTO user_orders(user_id,market,symbol,side,order_type,quantity,quote_amount,leverage,entry_price,binance_order_id,status,timeframe,tp1,tp2,tp3,sl) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(u["id"],market,symbol,data.side,"MARKET",qty,data.amount,leverage,entry,oid,status,tf,data.tp1,data.tp2,data.tp3,data.sl))
    return {"ok":True,"id":tid,"binance_order_id":oid,"status":status,"entry":entry,"quantity":qty,"leverage":leverage}

@app.get("/api/binance/orders")
async def binance_orders(request:Request,limit:int=100):
    u=user_required(request);data=rows("SELECT * FROM user_orders WHERE user_id=? ORDER BY id DESC LIMIT ?",(u["id"],min(limit,200)))
    async def enrich(o):
        x=dict(o)
        try:
            price=float((await binance_public("/fapi/v1/ticker/price" if x["market"]=="futures" else "/api/v3/ticker/price",{"symbol":x["symbol"]},futures=x["market"]=="futures")).get("price") or x["entry_price"])
            entry=float(x["entry_price"] or price);raw=((price-entry)/entry*100) if x["side"]=="شراء" else ((entry-price)/entry*100)
            x["price"]=price;x["pnl"]=round(raw*(float(x["leverage"] or 1) if x["market"]=="futures" else 1),3)
        except Exception:x["price"]=x["entry_price"]
        return x
    return await asyncio.gather(*(enrich(x) for x in data))

@app.post("/api/binance/orders/{order_id}/close")
async def binance_close(order_id:int,request:Request):
    check_browser_origin(request)
    u=user_required(request);o=one("SELECT * FROM user_orders WHERE id=? AND user_id=?",(order_id,u["id"]))
    if not o:raise HTTPException(404,"الصفقة غير موجودة")
    if o["status"] in {"CLOSED","CANCELED"}:return {"ok":True,"status":o["status"]}
    qty=float(o["quantity"] or 0)
    if qty<=0:raise HTTPException(400,"كمية الإغلاق غير صالحة")
    futures=o["market"]=="futures";side="SELL" if o["side"]=="شراء" else "BUY"
    params={"symbol":o["symbol"],"side":side,"type":"MARKET","quantity":f"{qty:.12f}","newOrderRespType":"RESULT"}
    if futures:params["reduceOnly"]="true"
    result=await binance_signed(u["id"],"POST","/fapi/v1/order" if futures else "/api/v3/order",params,futures)
    price=order_entry_price(result)
    if not price:price=float((await binance_public("/fapi/v1/ticker/price" if futures else "/api/v3/ticker/price",{"symbol":o["symbol"]},futures=futures)).get("price") or o["entry_price"])
    entry=float(o["entry_price"] or price);pnl=((price-entry)/entry*100) if o["side"]=="شراء" else ((entry-price)/entry*100)
    if futures:pnl*=float(o["leverage"] or 1)
    execute("UPDATE user_orders SET status='CLOSED',pnl=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",(round(pnl,4),order_id,u["id"]))
    return {"ok":True,"status":"CLOSED","price":price,"pnl":round(pnl,4)}

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
    if int(user["id"])==user_id and data.role!="admin": raise HTTPException(400,"لا يمكن خفض صلاحية المدير الحالي")
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

@app.post("/api/admin/tracker/reset")
def admin_reset_tracker(user=Depends(admin_required)):
    # Reset the platform strategy journal only. Accounts, sessions, Binance connections,
    # and personal Binance orders are intentionally left untouched.
    execute("DELETE FROM trades")
    return {"ok":True,"message":"تمت إعادة نتائج المتابعة للصفر"}

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