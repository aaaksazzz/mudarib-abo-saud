from fastapi import FastAPI,HTTPException,Request,Response,Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import httpx,asyncio,os,hashlib,hmac,secrets,base64,time,json,xml.etree.ElementTree as ET
from urllib.parse import quote,urlencode,urlparse
from cryptography.fernet import Fernet,InvalidToken
from db import init_db,rows,one,execute
from intelligence_core import intelligence_signal,record_ai_outcome
from strategy_lab import candidates,candidate_signal,evaluate,quality

app=FastAPI(title="التداول الذكي PRO",version="4.0")
DATA_SEM=asyncio.Semaphore(16)
DATA_CACHE={}
SCAN_CACHE={}
SCAN_LOCKS={}
MONTHLY_DIRECTION_CACHE={}
SPOT_UNIVERSE_CACHE=(0,[])
CACHE_TTL=180
SCAN_TTL=45
SPOT_UNIVERSE_TTL=900
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
    market:str; symbol:str; timeframe:str="15m"; side:str; entry:float; tp1:float; tp2:float; tp3:float; tp4:float|None=None; sl:float; ai:float=0
class RoleIn(BaseModel): role:str
class SettingIn(BaseModel): key:str; value:str
class SubscriptionIn(BaseModel): plan:str
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
    tp4:float|None=None
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
@app.get("/news")
@app.get("/blog")
@app.get("/account")
@app.get("/login")
@app.get("/register")
@app.get("/binance")
@app.get("/subscriptions")
@app.get("/binance-subscriptions")
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
async def get_twelve_data(s,tf,market=None):
    """Secondary market-data provider. Returns [] when not configured/unavailable."""
    api_key=os.getenv("TWELVE_DATA_API_KEY","").strip()
    if not api_key:return []
    interval={"5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h","1d":"1day","1w":"1week","1M":"1month"}.get(tf)
    if not interval:return []
    symbol=str(s).upper()
    params={"symbol":symbol,"interval":interval,"outputsize":250,"apikey":api_key}
    if market=="saudi":
        params["symbol"]=symbol.replace(".SR","");params["exchange"]="XSAU"
    elif market=="forex":
        params["symbol"]={"EURUSD=X":"EUR/USD","GBPUSD=X":"GBP/USD","USDJPY=X":"USD/JPY","AUDUSD=X":"AUD/USD","GC=F":"XAU/USD","SI=F":"XAG/USD","CL=F":"WTI"}.get(s,s)
    elif market in ("spot","futures") and symbol.endswith("USDT"):
        params["symbol"]=symbol[:-4]+"/USD"
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=15)
        try:
            r=await c.get("https://api.twelvedata.com/time_series",params=params)
            if r.status_code>=400:return []
            payload=r.json()
        except Exception as e:
            print(f"twelve_data {market}/{s}/{tf}: {e}");return []
        finally:
            if c is not HTTP_CLIENT: await c.aclose()
    out=[]
    for v in reversed(payload.get("values") or []):
        try:
            dt=str(v.get("datetime") or "").replace("Z","+00:00")
            import datetime as _dt
            ts=int(v.get("timestamp") or 0)*1000
            if not ts and dt: ts=int(_dt.datetime.fromisoformat(dt).timestamp()*1000)
            out.append([ts,float(v["open"]),float(v["high"]),float(v["low"]),float(v["close"]),float(v.get("volume") or 0)])
        except Exception: continue
    return out

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
    out=[]
    cl=q.get("close",[]) or []; hi=q.get("high",[]) or []; lo=q.get("low",[]) or []; op=q.get("open",[]) or []; vol=q.get("volume",[]) or []
    timestamps=(payload.get("chart") or {}).get("result",[{}])[0].get("timestamp",[]) or []
    for i,v in enumerate(cl):
        if v is None: continue
        o=op[i] if i<len(op) and op[i] is not None else v
        h=hi[i] if i<len(hi) and hi[i] is not None else v
        l=lo[i] if i<len(lo) and lo[i] is not None else v
        ts=int(timestamps[i])*1000 if i<len(timestamps) and timestamps[i] is not None else 0
        out.append([ts,o,h,l,v,(vol[i] if i<len(vol) and vol[i] else 0)])
    if tf=="4h":
        grouped={}
        for k in out:
            bucket=(k[0]//(4*3600_000))*(4*3600_000)
            grouped.setdefault(bucket,[]).append(k)
        out=[]
        for bucket,grp in sorted(grouped.items()):
            out.append([bucket,grp[0][1],max(float(x[2]) for x in grp),min(float(x[3]) for x in grp),grp[-1][4],sum(float(x[5] or 0) for x in grp)])
    return out
async def get_bybit(s,tf,market):
    """Independent crypto fallback for Binance outages/rate limits."""
    if market not in ("spot","futures") or not str(s).upper().endswith("USDT"): return []
    interval={"5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","1d":"D","1w":"W","1M":"M"}.get(tf)
    if not interval:return []
    category="linear" if market=="futures" else "spot"
    c=HTTP_CLIENT or httpx.AsyncClient(timeout=12,headers={"User-Agent":"Trading-Pro/4.0"})
    try:
        r=await c.get("https://api.bybit.com/v5/market/kline",params={"category":category,"symbol":s.upper(),"interval":interval,"limit":250})
        r.raise_for_status(); payload=r.json()
        if int(payload.get("retCode",0) or 0)!=0:return []
        rows=((payload.get("result") or {}).get("list") or [])
        out=[]
        for v in reversed(rows):
            try: out.append([int(v[0]),float(v[1]),float(v[2]),float(v[3]),float(v[4]),float(v[5] or 0)])
            except Exception: continue
        return out
    except Exception as e:
        print(f"failover bybit {market}/{s}/{tf}: {e}"); return []
    finally:
        if c is not HTTP_CLIENT: await c.aclose()

async def get_stooq(s,tf):
    """Independent low-frequency fallback for Yahoo-listed instruments."""
    if tf not in ("1d","1w","1M"): return []
    symbol=str(s).lower().replace("=f","").replace(".sr","")
    if symbol.endswith("=x"): return []
    url="https://stooq.com/q/d/l/"
    period={"1d":"d","1w":"w","1M":"m"}[tf]
    c=HTTP_CLIENT or httpx.AsyncClient(timeout=12,headers={"User-Agent":"Trading-Pro/4.0"})
    try:
        r=await c.get(url,params={"s":symbol,"d1":"20000101","i":period}); r.raise_for_status()
        lines=r.text.strip().splitlines()
        if len(lines)<2:return []
        out=[]
        import csv,datetime as _dt
        for row in csv.DictReader(lines):
            try:
                ts=int(_dt.datetime.fromisoformat(row["Date"]).timestamp()*1000)
                out.append([ts,float(row["Open"]),float(row["High"]),float(row["Low"]),float(row["Close"]),float(row.get("Volume") or 0)])
            except Exception: continue
        return out[-250:]
    except Exception as e:
        print(f"failover stooq {s}/{tf}: {e}"); return []
    finally:
        if c is not HTTP_CLIENT: await c.aclose()

async def candles(m,s,tf):
    """Provider failover: primary -> independent secondary -> cache."""
    key=(m,s,tf); now=time.monotonic()
    hit=DATA_CACHE.get(key)
    if hit and now-hit[0] < CACHE_TTL:return hit[1]
    providers=[]
    if MARKETS[m]["provider"]=="binance":
        providers=[("Binance",lambda:get_binance(s,tf,m=="futures")),
                   ("Bybit",lambda:get_bybit(s,tf,m))]
    else:
        providers=[("Yahoo",lambda:get_yahoo(s,tf)),
                   ("Twelve Data",lambda:get_twelve_data(s,tf,m)),
                   ("Stooq",lambda:get_stooq(s,tf))]
    data=[]
    for name,loader in providers:
        try:
            candidate=await loader()
            # The monthly master needs a long raw-price history. If a provider
            # returns too little monthly data, continue to the next provider.
            minimum_required=40 if tf=="1M" else 2
            if candidate and len(candidate)>=minimum_required:
                data=candidate
                if name!="Binance" and MARKETS[m]["provider"]=="binance":
                    print(f"failover {m}/{s}/{tf}: using {name}")
                elif name!="Yahoo" and MARKETS[m]["provider"]!="binance":
                    print(f"failover {m}/{s}/{tf}: using {name}")
                break
        except Exception as e:
            print(f"provider {name} failed {m}/{s}/{tf}: {e}")
    if not data and hit:
        data=hit[1]
        if data: print(f"failover {m}/{s}/{tf}: using cached data")
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

def make_signal(k,m,symbol=None,timeframe="unknown"):
    # Autonomous raw-market brain: no fixed indicators or hardcoded trading strategy.
    x=intelligence_signal(k,reverse=False,feedback=None,symbol=symbol,market=m,timeframe=timeframe)
    if m in ("spot","saudi") and x and x["side"]!="شراء":
        return None
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
async def binance_futures_scan_symbols(min_daily_usdt=1_000_000):
    """Live Binance USDT-M futures universe above daily quote volume threshold."""
    stable={"USDT","USDC","FDUSD","TUSD","DAI","USDP","PYUSD","BUSD","USDE","USDS","EUR","EURI","USD1","USTC","FRAX","LUSD","GUSD","RLUSD"}
    async with DATA_SEM:
        c=HTTP_CLIENT or httpx.AsyncClient(timeout=25)
        try:
            info=(await c.get("https://fapi.binance.com/fapi/v1/exchangeInfo")).json()
            tick=(await c.get("https://fapi.binance.com/fapi/v1/ticker/24hr")).json()
        finally:
            if c is not HTTP_CLIENT: await c.aclose()
    active={x.get("symbol") for x in (info.get("symbols") or []) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL"}
    out=[]
    for x in tick if isinstance(tick,list) else []:
        s=str(x.get("symbol") or "").upper()
        if s not in active: continue
        base=s[:-4] if s.endswith("USDT") else ""
        if not base or base in stable: continue
        try:qv=float(x.get("quoteVolume") or 0)
        except Exception:continue
        if qv>=float(min_daily_usdt): out.append((s,qv))
    return [s for s,_ in sorted(out,key=lambda z:z[1],reverse=True)]

async def futures_scan_symbols():
    try:
        symbols=await binance_futures_scan_symbols(1_000_000)
        return symbols or MARKETS["futures"]["symbols"]
    except Exception as e:
        print(f"futures_universe: {e}")
        return MARKETS["futures"]["symbols"]

async def yahoo_screener_symbols(region="us",quote_type="EQUITY",min_volume=1_000_000):
    """Discover a broad live universe from Yahoo's public screener endpoint."""
    cache_key=("yahoo_universe",region,quote_type)
    now=time.monotonic()
    cached=DATA_CACHE.get(cache_key)
    if cached and now-cached[0] < 1800:return cached[1]
    url="https://query1.finance.yahoo.com/v1/finance/screener"
    payload={"size":250,"offset":0,"sortField":"dayvolume","sortType":"DESC","quoteType":quote_type,
             "query":{"operator":"AND","operands":[{"operator":"EQ","operands":["region",region]}]}}
    symbols=[]
    try:
        async with DATA_SEM:
            c=HTTP_CLIENT or httpx.AsyncClient(timeout=25,headers={"User-Agent":"Mozilla/5.0"})
            try:
                r=await c.post(url,json=payload,headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Origin":"https://finance.yahoo.com","Referer":"https://finance.yahoo.com/"}); r.raise_for_status(); data=r.json()
            finally:
                if c is not HTTP_CLIENT: await c.aclose()
        result=((data.get("finance") or {}).get("result") or [])
        quotes=(result[0].get("quotes") or []) if result else []
        for q in quotes:
            s=q.get("symbol"); vol=float(q.get("regularMarketVolume") or q.get("averageDailyVolume3Month") or 0)
            if s and vol>=min_volume:symbols.append(s)
    except Exception:
        DATA_CACHE[cache_key]=(now,[])
    if symbols: DATA_CACHE[cache_key]=(now,symbols)
    return symbols

async def broad_market_symbols(market):
    if market=="us":
        return await yahoo_screener_symbols("us","EQUITY",1_000_000) or MARKETS["us"]["symbols"]
    if market=="saudi":
        return await yahoo_screener_symbols("sa","EQUITY",100_000) or MARKETS["saudi"]["symbols"]
    if market=="contracts":
        return await yahoo_screener_symbols("us","FUTURE",1) or MARKETS["contracts"]["symbols"]
    if market=="forex":
        return await yahoo_screener_symbols("us","CURRENCY",1) or MARKETS["forex"]["symbols"]
    return MARKETS[market]["symbols"]

async def spot_scan_symbols():
    """Live Binance Spot universe: every USDT pair with >= 1M USDT 24h quote volume, excluding stable/fiat-like bases."""
    global SPOT_UNIVERSE_CACHE
    now=time.monotonic()
    if SPOT_UNIVERSE_CACHE[1] and now-SPOT_UNIVERSE_CACHE[0] < SPOT_UNIVERSE_TTL:
        return SPOT_UNIVERSE_CACHE[1]
    try:
        pairs=await binance_spot_backtest_symbols(1_000_000)
        symbols=[s for s,_ in pairs]
        SPOT_UNIVERSE_CACHE=(now,symbols)
        return symbols
    except Exception as e:
        print(f"spot_universe: {e}")
        return SPOT_UNIVERSE_CACHE[1] or MARKETS["spot"]["symbols"]

async def scan_one_market(market,timeframe,max_symbols=None):
    """
    Independent timeframe-only opportunity engine.
    Every timeframe calculates its own direction, change, SL and TP.
    No monthly gate, no 30m master direction, and no cross-timeframe dependency.
    """
    market=require_market(market); timeframe=require_tf(timeframe)
    key=("timeframe-only-change",market,timeframe)
    now=time.monotonic()
    hit=SCAN_CACHE.get(key)
    if hit and now-hit[0] < SCAN_TTL:
        return hit[1]

    lock=SCAN_LOCKS.setdefault(key,asyncio.Lock())
    async with lock:
        now=time.monotonic()
        hit=SCAN_CACHE.get(key)
        if hit and now-hit[0] < SCAN_TTL:
            return hit[1]

        if market=="spot":
            symbols=await spot_scan_symbols()
        elif market=="futures":
            symbols=await futures_scan_symbols()
        else:
            symbols=await broad_market_symbols(market)

        scan_limit=max(1,min(int(max_symbols or 25),70))
        symbols=symbols[:scan_limit]

        async def check(symbol):
            try:
                k=await asyncio.wait_for(candles(market,symbol,timeframe),timeout=8.0)
                if not k or len(k)<2:
                    return None

                current=float(k[-1][4] or 0)
                previous=float(k[-2][4] or 0)
                if current<=0 or previous<=0:
                    return None

                change_pct=(current-previous)/abs(previous)*100.0
                if change_pct==0:
                    return None

                side="شراء" if change_pct>0 else "بيع"
                magnitude=abs(change_pct)

                lows=[float(x[3]) for x in k[-16:] if float(x[3] or 0)>0]
                highs=[float(x[2]) for x in k[-16:] if float(x[2] or 0)>0]

                if side=="شراء":
                    sl=min(lows) if lows else current*(1-0.01)
                    if sl>=current: sl=current*(1-0.01)
                    risk=(current-sl)/current
                    if risk<=0: risk=0.01
                    if risk>0.15:
                        sl=current*(1-0.05); risk=0.05
                    tp1=current*(1+risk); tp2=current*(1+risk*2); tp3=current*(1+risk*3); tp4=current*(1+risk*4)
                else:
                    sl=max(highs) if highs else current*(1+0.01)
                    if sl<=current: sl=current*(1+0.01)
                    risk=(sl-current)/current
                    if risk<=0: risk=0.01
                    if risk>0.15:
                        sl=current*(1+0.05); risk=0.05
                    tp1=current*(1-risk); tp2=current*(1-risk*2); tp3=current*(1-risk*3); tp4=current*(1-risk*4)

                ai=round(max(55.0,min(95.0,55.0+min(magnitude*10.0,40.0))),2)

                signal={
                    "side":side,
                    "recommendation":side,
                    "entry":current,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"sl":sl,
                    "ai":ai,
                    "rank_score":round(magnitude,6),
                    "timeframe_rank_key":round(magnitude,6),
                    "strategy_mode":"TIMEFRAME_ONLY_CHANGE",
                    "model_version":"SIMPLE_CHANGE_V3",
                    "reverse":False,"reverse_applied":False,"original_side":side,
                    "analysis_order":"selected timeframe only",
                    "timeframe_change_pct":round(change_pct,6),
                    "directional_change_pct":round(magnitude,6),
                    "ranking_basis":"timeframe_change_pct",
                    "timeframe_independent":True,
                    "analysis":{"indicators_used":False,"method":"selected timeframe raw price change only"}
                }

                return {
                    "market":market,"symbol":symbol,"price":current,
                    "change_pct":round(change_pct,6),
                    "directional_change_pct":round(magnitude,6),
                    "timeframe":timeframe,
                    "candle_open_ms":int(k[-1][0]) if k[-1] and k[-1][0] else None,
                    "signal":signal
                }
            except Exception as e:
                print(f"timeframe scan {market}/{symbol}/{timeframe}: {e}")
                return None

        found=[]
        for start_i in range(0,len(symbols),10):
            batch=symbols[start_i:start_i+10]
            batch_results=await asyncio.gather(*(check(s) for s in batch),return_exceptions=False)
            found.extend(x for x in batch_results if x)

        found.sort(key=lambda x:(
            float(x.get("directional_change_pct") or 0),
            float((x.get("signal") or {}).get("ai") or 0)
        ),reverse=True)

        for i,item in enumerate(found,1):
            item["rank"]=i
            item["crown"]=(i==1)
            sig=item.get("signal") or {}
            sig["rank"]=i
            sig["crown"]=(i==1)
            item["signal"]=sig

        SCAN_CACHE[key]=(time.monotonic(),found)
        return found

async def section_scanner(market:str,timeframe="15m",limit:int=40):
    try:
        return await scan_one_market(market,timeframe,max_symbols=min(max(int(limit or 25),1),40))
    except Exception as e:
        print(f"section scanner {market}/{timeframe}: {e}")
        return []

@app.get("/api/scanner")
async def scanner(market="spot",timeframe="15m",limit:int=100):
    try:
        return await scan_one_market(market,timeframe,max_symbols=min(max(int(limit or 25),1),40))
    except Exception as e:
        print(f"scanner {market}/{timeframe}: {e}")
        return []

@app.get("/api/section/{market}/trades")
async def section_trades_api(market:str,timeframe="15m",limit:int=100):
    market=require_market(market); timeframe=require_tf(timeframe)
    return await scan_one_market(market,timeframe,max_symbols=min(max(int(limit or 25),1),70))

@app.get("/api/section/{market}/scanner")
async def section_scanner_api(market:str,timeframe="15m",limit:int=40):
    market=require_market(market); timeframe=require_tf(timeframe)
    return await scan_one_market(market,timeframe,max_symbols=min(max(int(limit or 40),1),70))

@app.get("/api/section/{market}/stats")
def section_stats_api(market:str,timeframe="15m",period="all"):
    market=require_market(market); timeframe=require_tf(timeframe)
    return stats(period=period)

@app.get("/api/platform/summary")
def platform_summary_api():
    return {
        "markets":len(MARKETS),
        "market_keys":list(MARKETS.keys()),
        "trades":int(one("SELECT COUNT(*) n FROM trades")["n"] or 0),
        "open_trades":int(one("SELECT COUNT(*) n FROM trades WHERE status='open'")["n"] or 0),
        "health":"ok"
    }


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

def _lab_trades(klines,p):
    """Walk-forward trade simulation for one research candidate; no look-ahead."""
    trades=[]; i=max(120,p["ma"]+5)
    while i < len(klines)-1:
        sig=candidate_signal(klines[:i+1],p)
        if not sig:
            i+=1; continue
        side,entry,sl,tp=sig
        risk=abs(entry-sl)
        if entry<=0 or risk<=0:
            i+=1; continue
        outcome=None; exit_i=None; exit_price=None
        for j in range(i+1,len(klines)):
            high=float(klines[j][2]); low=float(klines[j][3])
            hit_sl=(low<=sl) if side=="شراء" else (high>=sl)
            hit_tp=(high>=tp) if side=="شراء" else (low<=tp)
            # Conservative rule: if both occur in one candle, count SL first.
            if hit_sl:
                outcome="loss"; exit_price=sl; exit_i=j; break
            if hit_tp:
                outcome="win"; exit_price=tp; exit_i=j; break
        if outcome is None: break
        rr=(abs(exit_price-entry)/risk) if outcome=="win" else -1.0
        trades.append({"side":side,"entry":entry,"sl":sl,"tp":tp,"ai":None,
                       "outcome":outcome,"r":round(rr,4),
                       "entry_time":int(klines[i][0]),"exit_time":int(klines[exit_i][0])})
        i=exit_i+1
    return trades

def historical_test(klines):
    """Honest walk-forward test of the reversed research candidates.
    Candidate selection uses only the training segment; reported trades are OOS."""
    if len(klines)<240:return []
    cut=max(120,int(len(klines)*0.70))
    train=klines[:cut]
    test=klines[max(0,cut-120):]
    scored=[]
    for p in candidates():
        tr=evaluate(train,p)
        if tr["trades"]>=10 and tr["profit_factor"] is not None:
            scored.append((quality(tr,tr),p,tr))
    if not scored:
        return []
    # Select only from the training segment, then run the chosen setup on unseen data.
    scored.sort(key=lambda x:x[0],reverse=True)
    best=scored[0][1]
    return _lab_trades(test,best)

@app.get("/api/backtest")
async def backtest(market="spot",timeframe="15m",symbol="",days=30,max_symbols=40):
    market=require_market(market); timeframe=require_tf(timeframe)
    try: days=max(1,min(int(days),3650))
    except Exception: raise HTTPException(400,"عدد الأيام غير صالح")
    requested=symbol.upper().strip()
    try: max_symbols=max(1,min(int(max_symbols),100))
    except Exception: raise HTTPException(400,"عدد العملات غير صالح")
    # Protect the small production server from an accidental full-universe scan.
    # The caller's max_symbols is now actually enforced for spot backtests.
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
    if not requested:
        symbols=symbols[:max_symbols]
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

@app.get("/api/stats")
def stats(period="all"):
    # Tracker starts fresh with the current AI model; legacy tracker results
    # remain stored for learning/admin history but do not inflate the new counter.
    where_parts=["ai_model_version=?"]
    args=[MODEL_VERSION]
    if period in {"day","week","month","year"}:
        days={"day":1,"week":7,"month":30,"year":365}[period]
        where_parts.append("created_at >= datetime('now', ?)")
        args.append(f"-{days} days")
    where=" WHERE "+" AND ".join(where_parts)
    total=one("SELECT COUNT(*) n FROM trades"+where,tuple(args))["n"]
    closed=one("SELECT COUNT(*) n FROM trades"+where+" AND status='closed'",tuple(args))["n"]
    wins=one("SELECT COUNT(*) n FROM trades"+where+" AND status='closed' AND pnl>0",tuple(args))["n"]
    pnl=one("SELECT COALESCE(SUM(pnl),0) n FROM trades"+where+" AND status='closed'",tuple(args))["n"]
    return {"period":period,"open":total-closed,"closed":closed,"wins":wins,"losses":closed-wins,"win_rate":round(wins/closed*100,2) if closed else 0,"pnl":round(float(pnl or 0),4)}

@app.get("/api/market/{symbol}")
async def market(symbol:str,market="spot",timeframe="15m"):
    market=require_market(market); timeframe=require_tf(timeframe)
    try:
        k=await candles(market,symbol.upper(),timeframe)
        if not k or len(k)<2: raise HTTPException(502,"لا توجد بيانات كافية للسوق")
        return {"market":market,"symbol":symbol.upper(),"timeframe":timeframe,"price":float(k[-1][4]),"signal":make_signal(k,market,symbol.upper(),timeframe)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"تعذر جلب بيانات السوق حالياً")
async def save_signal(m,s,tf,x,candle_open_ms=None):
    if not x:
        return
    # Publish/store each new candle signal only. No tracker and no automatic closing.
    # A previous signal must never block the next candle.
    if candle_open_ms:
        existing=one(
            "SELECT id FROM trades WHERE market=? AND symbol=? AND timeframe=? AND candle_open_ms=? LIMIT 1",
            (m,s,tf,int(candle_open_ms))
        )
    else:
        existing=one(
            "SELECT id FROM trades WHERE market=? AND symbol=? AND timeframe=? "
            "AND created_at>=datetime('now','-20 minutes') LIMIT 1",
            (m,s,tf)
        )
    if existing:
        return
    execute(
        "INSERT INTO trades(market,symbol,timeframe,side,entry,tp1,tp2,tp3,tp4,sl,ai,status,source,candle_open_ms,reverse_applied,ai_context_json,ai_model_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m,s,tf,x["side"],x["entry"],x["tp1"],x["tp2"],x["tp3"],x.get("tp4"),x["sl"],x["ai"],"open","ai",int(candle_open_ms) if candle_open_ms else None,0,json.dumps(x.get("context") or {},ensure_ascii=False,separators=(",",":")),x.get("model_version","RAW_BRAIN_SELF_DISCOVERY_V7_LIVE_SIGNAL"))
    )

async def scan_store():
    """Publish only the best current 15m opportunity per market."""
    total=0
    for market in MARKETS:
        try:
            result=await scan_one_market(market,"15m",max_symbols=20)
            if not result:
                continue

            # The candle timestamp is the lifecycle key. When a new 15m candle
            # starts, remove the previous automatic signal for this market/timeframe.
            current_candle=result[0].get("candle_open_ms")
            if current_candle:
                execute(
                    "DELETE FROM trades WHERE market=? AND timeframe=? AND source='ai' "
                    "AND (candle_open_ms IS NULL OR candle_open_ms<>?)",
                    (market,"15m",int(current_candle))
                )

            item=result[0]
            signal=item.get("signal")
            if signal:
                await save_signal(
                    market,item.get("symbol","").upper(),"15m",signal,item.get("candle_open_ms")
                )
                total+=1
        except Exception as e:
            print(f"scan_store {market}: {e}")
    return total

async def scanner_worker():
    await asyncio.sleep(3)
    while True:
        try:
            await scan_store()
        except Exception as e:
            print(f"scanner_worker: {e}")
        await asyncio.sleep(900)

async def strategy_lab_worker():
    # Research must never starve the live scanner on the 0.2 vCPU production tier.
    await asyncio.sleep(180)
    while True:
        started=time.monotonic()
        try:
            await asyncio.wait_for(run_strategy_lab(), timeout=20*60)
        except asyncio.TimeoutError:
            print("strategy_lab_worker: timed out after 20 minutes; live services remain active")
        except Exception as e:
            print(f"strategy_lab_worker: {e}")
        elapsed=time.monotonic()-started
        await asyncio.sleep(max(1800, 6*3600-elapsed))

async def news_worker():
    # Keep the news database warm on the server; the browser is not responsible for fetching RSS.
    await asyncio.sleep(8)
    while True:
        try:
            await refresh_news()
        except Exception as e:
            print(f"news_worker: {e}")
        await asyncio.sleep(600)

async def worker():
    # Live production uses the autonomous raw-market brain only.
    # The legacy strategy lab remains available for historical research endpoints,
    # but it is never executed as a live decision engine.
    await asyncio.gather(scanner_worker(),news_worker())

NEWS_QUERIES=[
    ("أسواق المال","financial markets stocks trading OR stock market"),
    ("العملات الرقمية","Bitcoin crypto markets OR cryptocurrency"),
    ("السوق السعودي","Saudi stocks Tadawul OR Saudi market"),
    ("الأسواق الأمريكية","US stocks Nasdaq S&P 500 OR Wall Street"),
    ("الفوركس والسلع","forex gold oil markets OR commodities"),
]
async def refresh_news():
    if not HTTP_CLIENT:
        return 0
    inserted=0
    for source,query in NEWS_QUERIES:
        try:
            url="https://news.google.com/rss/search?q="+quote(query)+"&hl=ar&gl=SA&ceid=SA:ar"
            r=await HTTP_CLIENT.get(
                url,
                timeout=15,
                headers={"User-Agent":"Mozilla/5.0 (compatible; TradingSmart/4.0; +https://news.google.com/)"}
            )
            r.raise_for_status()
            root=ET.fromstring(r.content)
            items=root.findall(".//item")
            for item in items[:8]:
                title=(item.findtext("title") or "").strip()
                desc=(item.findtext("description") or "").strip()
                pub=(item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                if one("SELECT id FROM news WHERE title=?",(title,)):
                    continue
                if len(desc)>1200:
                    desc=desc[:1200]
                execute(
                    "INSERT INTO news(title,body,source,created_at) VALUES(?,?,?,COALESCE(?,CURRENT_TIMESTAMP))",
                    (title,desc,source,pub)
                )
                inserted+=1
        except Exception as e:
            print(f"news source {source}: {e}")
    execute("DELETE FROM news WHERE id NOT IN (SELECT id FROM news ORDER BY id DESC LIMIT 100)")
    return inserted

@app.get("/api/news")
async def news():
    # The server worker refreshes the feed every 10 minutes.
    # Only bootstrap an empty database here so page loads stay fast.
    data=rows("SELECT * FROM news ORDER BY id DESC LIMIT 50")
    if len(data)<10:
        try:
            await asyncio.wait_for(refresh_news(),timeout=20)
        except asyncio.TimeoutError:
            print("news: bootstrap refresh timed out")
        except Exception as e:
            print(f"news: bootstrap refresh failed: {e}")
        data=rows("SELECT * FROM news ORDER BY id DESC LIMIT 50")
    return data

SUBSCRIPTION_PLANS={"7d":(10,7),"15d":(20,15),"30d":(30,30)}

@app.post("/api/subscriptions/request")
def subscription_request(data:SubscriptionIn,request:Request):
    check_browser_origin(request)
    u=user_required(request)
    plan=data.plan.strip().lower()
    if plan not in SUBSCRIPTION_PLANS: raise HTTPException(400,"الباقة غير صالحة")
    amount,days=SUBSCRIPTION_PLANS[plan]
    active=one("SELECT id FROM subscriptions WHERE user_id=? AND status='pending'",(u["id"],))
    if active: raise HTTPException(409,"لديك طلب اشتراك قيد المراجعة")
    sid=execute("INSERT INTO subscriptions(user_id,plan,amount,status) VALUES(?,?,?,'pending')",(u["id"],plan,amount))
    return {"ok":True,"id":sid,"plan":plan,"amount":amount,"status":"pending","days":days}

@app.get("/api/subscriptions/me")
def subscriptions_me(request:Request):
    u=user_required(request)
    return rows("SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 20",(u["id"],))

@app.get("/api/admin/subscriptions")
def admin_subscriptions(user=Depends(admin_required)):
    return rows("SELECT s.*,u.email FROM subscriptions s JOIN users u ON u.id=s.user_id ORDER BY s.id DESC LIMIT 200")

@app.post("/api/admin/subscriptions/{subscription_id}/approve")
def admin_approve_subscription(subscription_id:int,user=Depends(admin_required)):
    s=one("SELECT * FROM subscriptions WHERE id=?",(subscription_id,))
    if not s: raise HTTPException(404,"طلب الاشتراك غير موجود")
    if s["status"]!="pending": return {"ok":True,"status":s["status"]}
    days=SUBSCRIPTION_PLANS.get(s["plan"],(s["amount"],0))[1]
    execute("UPDATE subscriptions SET status='approved',approved_at=CURRENT_TIMESTAMP,expires_at=datetime('now',?) WHERE id=?",(f"+{days} days",subscription_id))
    return {"ok":True,"status":"approved","days":days}

@app.post("/api/admin/subscriptions/{subscription_id}/reject")
def admin_reject_subscription(subscription_id:int,user=Depends(admin_required)):
    if not one("SELECT id FROM subscriptions WHERE id=?",(subscription_id,)): raise HTTPException(404,"طلب الاشتراك غير موجود")
    execute("UPDATE subscriptions SET status='rejected' WHERE id=? AND status='pending'",(subscription_id,))
    return {"ok":True,"status":"rejected"}


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
    if market in {"spot","futures"}:
        try:
            info=await binance_public("/fapi/v1/exchangeInfo" if market=="futures" else "/api/v3/exchangeInfo",{"symbol":symbol},futures=market=="futures")
            listed=info.get("symbols") or []
            item=next((x for x in listed if x.get("symbol")==symbol),None)
            if not item or item.get("status")!="TRADING" or item.get("quoteAsset")!="USDT":
                raise HTTPException(400,"الرمز غير متاح للتنفيذ حالياً")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502,"تعذر التحقق من رمز Binance")
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
    tid=execute("INSERT INTO user_orders(user_id,market,symbol,side,order_type,quantity,quote_amount,leverage,entry_price,binance_order_id,status,timeframe,tp1,tp2,tp3,tp4,sl) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(u["id"],market,symbol,data.side,"MARKET",qty,data.amount,leverage,entry,oid,status,tf,data.tp1,data.tp2,data.tp3,data.tp4,data.sl))
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
    tid=execute("INSERT INTO trades(market,symbol,timeframe,side,entry,tp1,tp2,tp3,tp4,sl,ai,status,source,reverse_applied) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(market,data.symbol.upper(),timeframe,data.side,data.entry,data.tp1,data.tp2,data.tp3,data.tp4,data.sl,data.ai,"open","admin",0))
    return {"ok":True,"id":tid}

@app.delete("/api/admin/trades/{trade_id}")
def admin_delete_trade(trade_id:int,user=Depends(admin_required)):
    if not one("SELECT id FROM trades WHERE id=?",(trade_id,)): raise HTTPException(404,"الصفقة غير موجودة")
    execute("DELETE FROM trades WHERE id=?",(trade_id,))
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
    msg=f"📊 {t['symbol']} · {t['market']}\n{t['side']} · {t['timeframe']}\nالدخول: {t['entry']}\nTP1: {t['tp1']}\nTP2: {t['tp2']}\nTP3: {t['tp3']}\nTP4: {t.get("tp4")}\nSL: {t['sl']}\nAI: {t['ai']}%\n⚡ تحديث مباشر"
    async with httpx.AsyncClient(timeout=10) as c:r=await c.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg})
    if r.is_success:execute("UPDATE trades SET telegram_sent=1 WHERE id=?",(trade_id,))
    return {"ok":r.is_success}