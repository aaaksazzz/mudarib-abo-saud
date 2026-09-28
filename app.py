from __future__ import annotations
from fastapi import FastAPI, Query, Request as FastAPIRequest
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.request import Request as URLRequest, urlopen
from urllib.parse import quote, urlencode
import os, hmac, hashlib, base64, secrets
import json, math, time
from concurrent.futures import ThreadPoolExecutor, as_completed

app=FastAPI(title="التداول الذكي PRO",version="3.0.0")
BASE=Path(__file__).parent
def _pick_data_dir():
    configured=os.getenv("DATA_DIR","").strip()
    candidates=[]
    if configured: candidates.append(Path(configured))
    # Northflank persistent volume (when attached) must take precedence over the container filesystem.
    candidates.extend([Path("/data"),BASE/"data",Path("/tmp/mudarib-abo-saud-data")])
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True,exist_ok=True)
            probe=candidate/".write_test"
            probe.write_text("ok",encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except (PermissionError,OSError):
            continue
    return BASE

DATA_DIR=_pick_data_dir()
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES={"5m":"5د","15m":"15د","1h":"1س","4h":"4س","1d":"يومي","1w":"أسبوعي","1M":"شهري"}
FRAME_SECONDS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800,"1M":2592000}
YI={"5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
CACHE={}; UCACHE={}
RESULT_CACHE={}
RESULT_TTL=120
ADMIN_USER=os.getenv("ADMIN_USER","aaaksazzz")
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","")
ADMIN_SECRET=os.getenv("ADMIN_SECRET","")
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","@tadol1")
SITE_STATE_PATH=DATA_DIR/"site_state.json"

\nSTORAGE_BACKEND="volume-filesystem"

def _load_site_state():
    default={"maintenance":False,"title":"التداول الذكي PRO","announcement":"","sections":{k:True for k in MARKETS}}
    try:
        saved=None
        if isinstance(saved,dict):
            default.update(saved)
            return default
        if SITE_STATE_PATH.exists():
            x=json.loads(SITE_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(x,dict):
                for k in ("maintenance","title","announcement"):
                    if k in x: default[k]=x[k]
                if isinstance(x.get("sections"),dict):
                    for k,v in x["sections"].items():
                        if k in MARKETS: default["sections"][k]=bool(v)
    except Exception: pass
    return default

SITE_STATE=_load_site_state()

def _save_site_state():
    try:
        SITE_STATE_PATH.write_text(json.dumps(SITE_STATE,ensure_ascii=False),encoding="utf-8")
    except Exception: pass

def _admin_token():
    raw=f"{ADMIN_USER}|{int(time.time()//86400)}".encode()
    return base64.urlsafe_b64encode(hmac.new((ADMIN_SECRET or "missing-secret").encode(),raw,hashlib.sha256).digest()).decode().rstrip("=")

def _admin_ok(request):
    token=request.cookies.get("admin_session","")
    return bool(ADMIN_SECRET and ADMIN_PASSWORD and token and hmac.compare_digest(token,_admin_token()))

def _telegram_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return False,"Telegram environment variables are missing"
    try:
        data=urlencode({"chat_id":TELEGRAM_CHAT_ID,"text":text}).encode()
        req=URLRequest(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data=data,headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
        out=json.loads(urlopen(req,timeout=10).read().decode())
        return bool(out.get("ok")),out.get("description","")
    except Exception as e: return False,str(e)


def get_json(url,timeout=8):
    req=URLRequest(url,headers={"User-Agent":"MudaribSmart/3.0"})
    with urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())

def f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except:return None

def norm(rows):
    out=[]
    for x in rows or []:
        if len(x)<6:continue
        vals=[f(x[i]) for i in (1,2,3,4,5)]
        if any(v is None for v in vals[:4]):continue
        out.append({"t":int(x[0]/1000),"o":vals[0],"h":vals[1],"l":vals[2],"c":vals[3],"v":vals[4] or 0})
    return out

def yahoo(symbol,interval):
    periods={"5m":59,"15m":179,"1h":179,"1d":1095,"1wk":2555,"1mo":4380}
    start=int(time.time())-periods.get(interval,179)*86400
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}?period1={start}&period2={int(time.time())}&interval={interval}&events=history"
    d=get_json(u).get("chart",{}).get("result")
    if not d:return []
    d=d[0]; q=d.get("indicators",{}).get("quote",[{}])[0]; out=[]
    for i,t in enumerate(d.get("timestamp",[])):
        a=[q.get(k,[None]*len(d.get("timestamp",[])))[i] for k in ("open","high","low","close","volume")]
        if all(f(x) is not None for x in a[:4]):
            out.append({"t":int(t),"o":float(a[0]),"h":float(a[1]),"l":float(a[2]),"c":float(a[3]),"v":float(a[4] or 0)})
    return out

def binance(symbol,interval,market):
    base={"spot":"https://api.binance.com/api/v3/klines","futures":"https://fapi.binance.com/fapi/v1/klines","contracts":"https://dapi.binance.com/dapi/v1/klines"}[market]
    return norm(get_json(f"{base}?symbol={quote(symbol,safe='')}&interval={interval}&limit=500"))

def agg(c,seconds):
    b={}
    for x in c:
        k=x["t"]//seconds*seconds
        z=b.setdefault(k,{"t":k,"o":x["o"],"h":x["h"],"l":x["l"],"c":x["c"],"v":0})
        z["h"]=max(z["h"],x["h"]); z["l"]=min(z["l"],x["l"]); z["c"]=x["c"]; z["v"]+=x["v"]
    return [b[k] for k in sorted(b)]

def candles(market,symbol,frame):
    key=(market,symbol,frame); now=time.time()
    if key in CACHE and now-CACHE[key][0]<60:return CACHE[key][1]
    try:
        if market in ("spot","futures","contracts"): c=binance(symbol,frame,market)
        else:
            c=yahoo(symbol,YI[frame])
            if frame=="4h":c=agg(c,14400)
        CACHE[key]=(now,c); return c
    except:return []

def universe(market):
    now=time.time()
    if market in UCACHE and now-UCACHE[market][0]<900:return UCACHE[market][1]
    try:
        if market=="spot":
            d=get_json("https://api.binance.com/api/v3/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed")]
        elif market=="futures":
            d=get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL"]
        elif market=="contracts":
            d=get_json("https://dapi.binance.com/dapi/v1/exchangeInfo")
            u=[(x["symbol"],x["symbol"]) for x in d["symbols"] if x.get("contractStatus")=="TRADING" and x.get("contractType")=="PERPETUAL"]
        elif market=="us":
            u=[(x,x) for x in ("AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","AMD","NFLX","JPM","AVGO","ORCL","COST","WMT","PLTR","CRM","ADBE","QCOM","MU","INTC")]
        elif market=="saudi":
            u=[(x,x+".SR") for x in ("2222","1120","2010","7010","1180","1150","1211","2050","2082","2380","4030","4003","4200","1212","2020")]
        else:
            u=[("Gold","GC=F"),("Oil","CL=F"),("EURUSD","EURUSD=X"),("GBPUSD","GBPUSD=X"),("USDJPY","JPY=X"),("USDCHF","CHF=X"),("AUDUSD","AUDUSD=X")]
        if market in ("spot","futures","contracts"):
            # Larger deterministic universe so the scanner can publish more valid setups.
            u=sorted(u,key=lambda x:x[0])[:200]
        UCACHE[market]=(now,u);return u
    except:return []



STRATEGY_NAME="استراتيجية المضارب الذكي الموحدة"

# استراتيجية واحدة تجمع في قراءة موحدة:
# الاتجاه + هيكل السوق + حركة السعر + السيولة + الاختراق + الدعم/المقاومة + إدارة المخاطر.
def unified_strategy(c):
    if len(c)<60:return None
    recent=c[-30:]
    price=c[-1]["c"]
    prev=c[-2]
    hi=max(x["h"] for x in c[-31:-1])
    lo=min(x["l"] for x in c[-31:-1])
    span=max(hi-lo,price*0.001)

    # 1) الاتجاه
    up=sum(c[i]["h"]>c[i-1]["h"] and c[i]["l"]>c[i-1]["l"] for i in range(max(1,len(c)-9),len(c)))
    dn=sum(c[i]["h"]<c[i-1]["h"] and c[i]["l"]<c[i-1]["l"] for i in range(max(1,len(c)-9),len(c)))
    trend=1 if up>=5 else -1 if dn>=5 else 0

    # 2) هيكل السوق
    mid=len(recent)//2
    old=recent[:mid]; new=recent[mid:]
    old_hi=max(x["h"] for x in old); new_hi=max(x["h"] for x in new)
    old_lo=min(x["l"] for x in old); new_lo=min(x["l"] for x in new)
    structure=1 if new_hi>old_hi and new_lo>=old_lo else -1 if new_lo<old_lo and new_hi<=old_hi else 0

    # 3) حركة السعر
    rng=max(prev["h"]-prev["l"],1e-12)
    close_pos=(price-prev["l"])/rng
    candle=1 if prev["c"]>prev["o"] and close_pos>.60 else -1 if prev["c"]<prev["o"] and close_pos<.40 else 0

    # 4) السيولة/الحجم النسبي
    avg_v=sum(x["v"] for x in c[-21:-1])/20
    volume_ratio=(prev["v"]/avg_v) if avg_v>0 else 1
    liquidity=1 if prev["c"]>prev["o"] and volume_ratio>=1.05 else -1 if prev["c"]<prev["o"] and volume_ratio>=1.05 else 0

    # 5) الاختراق/الرفض: لا نطلب 2% إضافية بعد المستوى، لأن ذلك كان يمنع معظم الإشارات.
    breakout=1 if price>hi and prev["c"]>=prev["o"] else -1 if price<lo and prev["c"]<=prev["o"] else 0

    # 6) الدعم والمقاومة
    near_support=abs(price-lo)<=span*.15
    near_resistance=abs(price-hi)<=span*.15
    sr=1 if near_support and price>=prev["o"] else -1 if near_resistance and price<=prev["o"] else 0

    # قرار واحد من العناصر الستة + إدارة المخاطر كعامل حاسم سابع.
    signals=[trend,structure,candle,liquidity,breakout,sr]
    bull=sum(x==1 for x in signals); bear=sum(x==-1 for x in signals)
    if bull==bear:return None
    side="BUY" if bull>bear else "SELL"
    evidence=max(bull,bear)
    opposing=min(bull,bear)

    # الصفقة لا تصدر إلا مع توافق واضح وعدم وجود تعارض قوي.
    if evidence<3 or opposing>=3:return None

    if side=="BUY":
        sl=min(lo,price*.992)
        risk=price-sl
        tps=[price+risk*x for x in (1,1.8,2.6)]
    else:
        sl=max(hi,price*1.008)
        risk=sl-price
        tps=[price-risk*x for x in (1,1.8,2.6)]

    risk_pct=risk/max(price,1e-12)*100
    if risk<=0 or risk_pct>4.0:return None

    # إدارة المخاطر تدخل في جودة الإشارة، وليس كصوت وهمي يرفع العدد.
    risk_quality=1 if risk_pct<=2.0 else 0
    confidence=round(((evidence + risk_quality)/7)*100)
    return {
        "side":side,
        "strategy":STRATEGY_NAME,
        "confidence":confidence,
        "evidence":evidence,
        "analysts_agree":evidence + risk_quality,
        "analysts_total":7,
        "entry":price,
        "tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl
    }

def trade(c,market,frame,symbol):
    s=unified_strategy(c)
    if not s:return None
    if market in ("spot","saudi","us") and s["side"]!="BUY":return None
    return {
        "asset":symbol,"market":market,"timeframe":frame,"timeframe_name":FRAMES[frame],
        "side":s["side"],"ai_percent":s["confidence"],
        "analysts_agree":s.get("analysts_agree",s["evidence"]),"analysts_total":7,
        "entry":s["entry"],"tp1":s["tp1"],"tp2":s["tp2"],"tp3":s["tp3"],"sl":s["sl"],
        "created_at":int(time.time()),"strategy":STRATEGY_NAME,
        "evidence":s["evidence"],"evidence_total":7
    }


@app.get("/")
def home():return FileResponse(BASE/"static/index.html")

USER_STORE_PATH=DATA_DIR/"users_state.json"
USER_SESSION_COOKIE="user_session"

def _load_users():
    try:
        saved=None
        if isinstance(saved,dict) and isinstance(saved.get("users"),dict):
            return saved
        if USER_STORE_PATH.exists():
            x=json.loads(USER_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(x,dict) and isinstance(x.get("users"),dict):
                return x
    except Exception:
        pass
    return {"users":{}}

USERS=_load_users()

def _save_users():
    try:
        tmp=USER_STORE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(USERS,ensure_ascii=False),encoding="utf-8")
            tmp.replace(USER_STORE_PATH)
    except Exception:
        pass

def _password_hash(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,210000)
    return base64.urlsafe_b64encode(salt).decode()+"$"+base64.urlsafe_b64encode(digest).decode()

def _password_ok(password,stored):
    try:
        s,d=stored.split("$",1)
        salt=base64.urlsafe_b64decode(s.encode())
        got=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,210000)
        return hmac.compare_digest(base64.urlsafe_b64encode(got).decode(),d)
    except Exception:
        return False

def _user_token(user_id):
    raw=f"{user_id}|{int(time.time()//86400)}".encode()
    return base64.urlsafe_b64encode(hmac.new((ADMIN_SECRET or "missing-secret").encode(),raw,hashlib.sha256).digest()).decode().rstrip("=")

def _current_user(request):
    token=request.cookies.get(USER_SESSION_COOKIE,"")
    if not token or not ADMIN_SECRET:
        return None
    for user_id in USERS["users"]:
        if hmac.compare_digest(token,_user_token(user_id)):
            return USERS["users"][user_id]
    return None

@app.post("/api/account/register")
def account_register(payload:dict):
    name=str(payload.get("name","")).strip()[:80]
    email=str(payload.get("email","")).strip().lower()[:160]
    password=str(payload.get("password",""))
    if len(name)<2 or len(email)<5 or "@" not in email:
        return JSONResponse({"ok":False,"error":"أدخل الاسم والبريد بشكل صحيح"},status_code=400)
    if len(password)<8:
        return JSONResponse({"ok":False,"error":"كلمة المرور يجب أن تكون 8 أحرف على الأقل"},status_code=400)
    if not ADMIN_SECRET:
        return JSONResponse({"ok":False,"error":"ADMIN_SECRET غير مضبوط في السيرفر"},status_code=503)
    if any(u.get("email")==email for u in USERS["users"].values()):
        return JSONResponse({"ok":False,"error":"البريد مستخدم مسبقاً"},status_code=409)
    user_id=secrets.token_hex(12)
    USERS["users"][user_id]={"id":user_id,"name":name,"email":email,"password_hash":_password_hash(password),"created_at":int(time.time())}
    _save_users()
    r=JSONResponse({"ok":True,"user":{"id":user_id,"name":name,"email":email}})
    r.set_cookie(USER_SESSION_COOKIE,_user_token(user_id),httponly=True,samesite="lax",secure=True,max_age=86400,path="/")
    return r

@app.post("/api/account/login")
def account_login(payload:dict):
    email=str(payload.get("email","")).strip().lower()
    password=str(payload.get("password",""))
    if not ADMIN_SECRET:
        return JSONResponse({"ok":False,"error":"ADMIN_SECRET غير مضبوط في السيرفر"},status_code=503)
    user=next((u for u in USERS["users"].values() if u.get("email")==email),None)
    if not user or not _password_ok(password,user.get("password_hash","")):
        return JSONResponse({"ok":False,"error":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
    r=JSONResponse({"ok":True,"user":{"id":user["id"],"name":user["name"],"email":user["email"]}})
    r.set_cookie(USER_SESSION_COOKIE,_user_token(user["id"]),httponly=True,samesite="lax",secure=True,max_age=86400,path="/")
    return r

@app.post("/api/account/logout")
def account_logout():
    r=JSONResponse({"ok":True}); r.delete_cookie(USER_SESSION_COOKIE,path="/"); return r

@app.get("/api/account/me")
def account_me(request:FastAPIRequest):
    u=_current_user(request)
    if not u:
        return JSONResponse({"authenticated":False},status_code=401)
    return {"authenticated":True,"user":{"id":u["id"],"name":u["name"],"email":u["email"]}}

@app.post("/api/admin/login")
def admin_login(payload:dict):
    user=str(payload.get("username","")); password=str(payload.get("password",""))
    if not ADMIN_PASSWORD or not ADMIN_SECRET:
        return JSONResponse({"ok":False,"error":"ADMIN_PASSWORD و ADMIN_SECRET غير مضبوطين في Northflank"},status_code=503)
    if not hmac.compare_digest(user,ADMIN_USER) or not hmac.compare_digest(password,ADMIN_PASSWORD):
        return JSONResponse({"ok":False,"error":"بيانات الدخول غير صحيحة"},status_code=401)
    r=JSONResponse({"ok":True,"user":ADMIN_USER})
    r.set_cookie("admin_session",_admin_token(),httponly=True,samesite="lax",secure=True,max_age=86400,path="/")
    return r

@app.post("/api/admin/logout")
def admin_logout():
    r=JSONResponse({"ok":True}); r.delete_cookie("admin_session",path="/"); return r

@app.get("/api/admin/overview")
def admin_overview(request):
    if not _admin_ok(request): return JSONResponse({"ok":False,"error":"unauthorized"},status_code=401)
    return {"ok":True,"system":{"status":"ok","engine":"unified-price-action-strategy","storage_dir":str(DATA_DIR)},"settings":SITE_STATE,
            "sections":{"markets":list(MARKETS.values()),"timeframes":list(FRAMES.values()),"news":len(NEWS),"blog":len(BLOG)}}

@app.post("/api/admin/settings")
def admin_settings(request,payload:dict):
    if not _admin_ok(request): return JSONResponse({"ok":False,"error":"unauthorized"},status_code=401)
    for k in ("maintenance","title","announcement"):
        if k in payload: SITE_STATE[k]=bool(payload[k]) if k=="maintenance" else str(payload[k])[:500]
    if isinstance(payload.get("sections"),dict):
        for k,v in payload["sections"].items():
            if k in MARKETS: SITE_STATE["sections"][k]=bool(v)
    _save_site_state(); return {"ok":True,"settings":SITE_STATE}

@app.post("/api/admin/telegram/test")
def admin_telegram_test(request):
    if not _admin_ok(request): return JSONResponse({"ok":False,"error":"unauthorized"},status_code=401)
    ok,msg=_telegram_send("✅ اختبار Telegram من لوحة إدارة التداول الذكي PRO")
    return JSONResponse({"ok":ok,"message":msg},status_code=200 if ok else 503)

@app.post("/api/admin/telegram/publish")
def admin_telegram_publish(request,payload:dict):
    if not _admin_ok(request): return JSONResponse({"ok":False,"error":"unauthorized"},status_code=401)
    text=str(payload.get("text","")).strip()
    if not text: return JSONResponse({"ok":False,"error":"اكتب نص الرسالة"},status_code=400)
    ok,msg=_telegram_send(text[:4096])
    return JSONResponse({"ok":ok,"message":msg},status_code=200 if ok else 503)

@app.get("/api/site-config")
def site_config():
    return {"title":SITE_STATE["title"],"maintenance":SITE_STATE["maintenance"],"announcement":SITE_STATE["announcement"],"sections":SITE_STATE["sections"]}

@app.get("/health")
def health():return {"status":"ok","service":"mudarib-abo-saud","engine":"7-analysts-unified-no-indicators","storage_backend":STORAGE_BACKEND,"database_configured":db_enabled(),"storage_dir":str(DATA_DIR),"time":time.time()}

@app.get("/api/markets")
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"strategy":STRATEGY_NAME,"indicators":False}


@app.get("/api/trades")
def trades(market:str=Query("spot"),timeframe:str=Query("5m")):
    if market not in MARKETS or timeframe not in FRAMES:
        return {"items":[],"error":"invalid_market_or_timeframe"}

    cache_key=("trades",market,timeframe)
    cached=RESULT_CACHE.get(cache_key)
    if cached and time.time()-cached[0]<min(RESULT_TTL,FRAME_SECONDS.get(timeframe,RESULT_TTL)):
        return cached[1]

    items=[];checked=0;ok=0;errors=0
    stored=_stored_trades(market,timeframe)
    symbols=universe(market)
    checked=len(symbols)

    def scan_one(pair):
        name,symbol=pair
        try:
            c=candles(market,symbol,timeframe)
            if len(c)<60:return None
            ok_trade=trade(c,market,timeframe,name)
            return ok_trade
        except Exception:
            return None

    # فحص متوازي حتى لا ينتظر الموقع عشرات طلبات Binance واحداً بعد الآخر.
    with ThreadPoolExecutor(max_workers=20) as pool:
        results=list(pool.map(scan_one,symbols))

    for t in results:
        if not t:continue
        existing=next((x for x in stored if _trade_store_key(x)==_trade_store_key(t)),None)
        if existing:
            t=existing
        else:
            t=_store_trade_until_frame_end(t)
        items.append(t)
        _register_trade(t)
        ok+=1

    items.sort(key=lambda x:x.get("ai_percent",0),reverse=True)
    payload={
        "market":market,"market_name":MARKETS[market],"timeframe":timeframe,
        "timeframe_name":FRAMES[timeframe],"items":items[:30],
        "checked":checked,"data_ok":checked,"signals_found":len(items),
        "errors":errors,"generated_at":int(time.time()),"indicators":False,
        "engine":"7 محللين في الخلفية ← تحليل واحد موحد",
        "storage":"محفوظ في سجل الصفقات والمتابع"
    }
    RESULT_CACHE[cache_key]=(time.time(),payload)
    return payload

@app.get("/api/analysis")
def smart_analysis(market:str=Query("spot"),timeframe:str=Query("5m")):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid_market_or_timeframe"}
    cache_key=("analysis",market,timeframe)
    cached=RESULT_CACHE.get(cache_key)
    if cached and time.time()-cached[0]<min(RESULT_TTL,FRAME_SECONDS.get(timeframe,RESULT_TTL)):return cached[1]
    items=[];checked=0;errors=0
    for name,symbol in universe(market):
        checked+=1
        try:
            c=candles(market,symbol,timeframe)
            if len(c)<60:continue
            st=unified_strategy(c)
            if not st:continue
            if market in ("spot","saudi","us") and st["side"]!="BUY":continue
            items.append({"asset":name,"symbol":symbol,"side":st["side"],"strategy":STRATEGY_NAME,"confidence":st["confidence"],"analysts_agree":st.get("analysts_agree",st["evidence"]),"analysts_total":7,"entry":st["entry"],"tp1":st["tp1"],"tp2":st["tp2"],"tp3":st["tp3"],"sl":st["sl"]})
        except Exception:errors+=1
    items.sort(key=lambda x:(x["confidence"],x["asset"]),reverse=True)
    payload={"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"timeframe_name":FRAMES[timeframe],"strategy":STRATEGY_NAME,"items":items[:30],"checked":checked,"errors":errors,"indicators":False,"engine":"7 محللين في الخلفية ← تحليل واحد موحد"}
    RESULT_CACHE[cache_key]=(time.time(),payload)
    return payload


@app.get("/api/scanner")
def scanner(timeframe:str=Query("5m")):
    if timeframe not in FRAMES:
        timeframe="5m"
    def get_market(m):
        try:
            return trades(m,timeframe)
        except Exception:
            return {"items":[]}
    items=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(get_market,MARKETS.keys()))
    for d in results:
        for x in d.get("items",[]):
            y=dict(x)
            y["confidence"]=x.get("ai_percent",0)
            y["market_name"]=MARKETS.get(x.get("market"),x.get("market"))
            items.append(y)
    items.sort(key=lambda x:(x.get("confidence",0),x.get("analysts_agree",0)),reverse=True)
    return {"timeframe":timeframe,"timeframe_name":FRAMES[timeframe],
            "items":items[:50],"checked":sum(int(d.get("checked",0)) for d in results),
            "signals_found":len(items),"engine":"7 محللين في الخلفية ← تحليل واحد موحد"}

TRACKER={"open":{},"closed":[]}
TRACKER_PATH=DATA_DIR/"tracker_state.json"
TRADE_STORE_PATH=DATA_DIR/"trade_state.json"

def _load_tracker_store():
    try:
        saved=None
        if isinstance(saved,dict) and isinstance(saved.get("open"),dict) and isinstance(saved.get("closed"),list):
            return saved
        if TRACKER_PATH.exists():
            data=json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
            if isinstance(data,dict) and isinstance(data.get("open"),dict) and isinstance(data.get("closed"),list):
                return data
    except Exception:
        pass
    return {"open":{},"closed":[]}

TRACKER=_load_tracker_store()

def _save_tracker_store():
    try:
        tmp=TRACKER_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(TRACKER,ensure_ascii=False),encoding="utf-8")
            tmp.replace(TRACKER_PATH)
    except Exception:
        pass

def _load_trade_store():
    try:
        saved=None
        if isinstance(saved,dict) and isinstance(saved.get("active"),dict):
            saved.setdefault("history",[])
            return saved
        if TRADE_STORE_PATH.exists():
            data=json.loads(TRADE_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data,dict) and isinstance(data.get("active"),dict):
                data.setdefault("history",[])
                return data
    except Exception:
        pass
    return {"active":{},"history":[]}

TRADE_STORE=_load_trade_store()

def _save_trade_store():
    try:
        tmp=TRADE_STORE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(TRADE_STORE,ensure_ascii=False),encoding="utf-8")
            tmp.replace(TRADE_STORE_PATH)
    except Exception:
        pass

def _trade_store_key(x):
    return f"{x.get('market')}:{x.get('asset')}:{x.get('timeframe')}"

def _purge_expired_trades(now=None):
    now=int(now or time.time())
    changed=False
    for k,x in list(TRADE_STORE["active"].items()):
        if int(x.get("expires_at",0))<=now:
            del TRADE_STORE["active"][k]
            changed=True
    if changed:_save_trade_store()

def _store_trade_until_frame_end(x):
    now=int(time.time())
    key=_trade_store_key(x)
    _purge_expired_trades(now)
    existing=TRADE_STORE["active"].get(key)
    if existing and int(existing.get("expires_at",0))>now:
        return existing

    stored=dict(x)
    stored["stored_at"]=now
    stored["expires_at"]=now+FRAME_SECONDS.get(x["timeframe"],900)
    stored["storage"]="active_until_frame_end"

    # سجل دائم للصفقة المنشورة؛ انتهاء الفريم لا يحذف تاريخها.
    hist_key=f"{key}:{stored['stored_at']}"
    if not any(h.get("_id")==hist_key for h in TRADE_STORE["history"][-500:]):
        stored["_id"]=hist_key
        TRADE_STORE["history"].append(dict(stored))
        TRADE_STORE["history"]=TRADE_STORE["history"][-1000:]

    TRADE_STORE["active"][key]=stored
    _save_trade_store()
    return stored

def _stored_trades(market,frame):
    _purge_expired_trades()
    return [x for x in TRADE_STORE["active"].values() if x.get("market")==market and x.get("timeframe")==frame]

def _tracker_key(x):
    return f"{x.get('market')}:{x.get('asset')}:{x.get('timeframe')}"

def _register_trade(x):
    k=_tracker_key(x)
    if k not in TRACKER["open"]:
        TRACKER["open"][k]=dict(x,status="OPEN",result=None,hit=None,checked_at=int(time.time()))
        _save_tracker_store()

def _tracker_symbol(x):
    if x["market"]=="saudi":
        return x["asset"]+".SR"
    return x["asset"]

def _evaluate_tracker_trade(x):
    try:
        c=candles(x["market"],_tracker_symbol(x),x["timeframe"])
        if not c:
            return None
        for bar in c:
            if bar["t"]<=int(x.get("created_at",0)):
                continue
            if x["side"]=="BUY":
                if bar["l"]<=x["sl"]:
                    return "LOSS","SL"
                if bar["h"]>=x["tp3"]:
                    return "WIN","TP3"
                if bar["h"]>=x["tp2"]:
                    return "WIN","TP2"
                if bar["h"]>=x["tp1"]:
                    return "WIN","TP1"
            else:
                if bar["h"]>=x["sl"]:
                    return "LOSS","SL"
                if bar["l"]<=x["tp3"]:
                    return "WIN","TP3"
                if bar["l"]<=x["tp2"]:
                    return "WIN","TP2"
                if bar["l"]<=x["tp1"]:
                    return "WIN","TP1"
    except Exception:
        return None
    return None

@app.get("/api/tracker")
def tracker():
    for k,x in list(TRACKER["open"].items()):
        result=_evaluate_tracker_trade(x)
        if result:
            status,hit=result
            TRACKER["closed"].append(dict(x,status="CLOSED",result=status,hit=hit,closed_at=int(time.time())))
            del TRACKER["open"][k]
            _save_tracker_store()
    wins=sum(1 for x in TRACKER["closed"] if x["result"]=="WIN")
    losses=sum(1 for x in TRACKER["closed"] if x["result"]=="LOSS")
    total=wins+losses
    return {"open":list(TRACKER["open"].values())[-100:],"closed":TRACKER["closed"][-100:],
            "history":TRADE_STORE.get("history",[])[-100:],
            "stats":{"wins":wins,"losses":losses,"total":total,"win_rate":round(wins/total*100,2) if total else 0}}


@app.get("/api/account")
def account(request:FastAPIRequest):
    u=_current_user(request)
    return {"authenticated":bool(u),"user":({"id":u["id"],"name":u["name"],"email":u["email"]} if u else None)}

@app.get("/api/admin")
def admin():return {"ok":True}

NEWS=[
{"id":1,"title":"ملخص الأسواق: لماذا تختلف حركة السعر من فريم إلى آخر؟","category":"أسواق","date":"2026-09-28","summary":"قراءة مستقلة للفريمات تساعد على فصل الحركة القصيرة عن السياق الأكبر.","body":"كل فريم يعرض جزءاً مختلفاً من حركة السوق. لذلك لا يفترض أن تتطابق الإشارة في 5 دقائق مع اليومية. في المنصة يتم التعامل مع كل فريم كقراءة مستقلة."},
{"id":2,"title":"الأمريكي: متابعة حركة الأسهم والسيولة","category":"الأمريكي","date":"2026-09-28","summary":"متابعة الأسهم الأمريكية المتاحة من مصدر البيانات قبل نشر أي إشارة.","body":"البيانات المتاحة هي الأساس. إذا لم تتوفر بيانات موثوقة أو كانت ناقصة، لا يتم اختلاق صفقة. أي نتيجة منشورة تعتمد على السعر الخام المتاح وقت التحليل."},
{"id":3,"title":"السعودي: قراءة حركة السوق بدون مؤشرات","category":"السعودي","date":"2026-09-28","summary":"التركيز على القمم والقيعان والإغلاق ومناطق التفاعل.","body":"التحليل هنا يعتمد على حركة السعر الخام وسلوك الإغلاق والمناطق السعرية، وليس على RSI أو MACD أو المتوسطات."},
{"id":4,"title":"السبوت والفيوتشر: اختلاف طبيعة السوق يغيّر القراءة","category":"كريبتو","date":"2026-09-28","summary":"الأسواق المختلفة تحتاج بياناتها ومصدرها الخاص قبل المقارنة.","body":"لا ينبغي استخدام مصدر بيانات واحد لجميع الأسواق. لذلك يتم فصل بيانات السبوت عن الفيوتشر والعقود حتى تكون قراءة كل قسم مستقلة."},
{"id":5,"title":"إدارة المخاطر في الأسواق السريعة","category":"مخاطر","date":"2026-09-28","summary":"الوقف والأهداف جزء من الخطة وليسا ضماناً للنتيجة.","body":"في الأسواق السريعة قد يحدث انزلاق سعري وتنفيذ مختلف عن السعر المتوقع. لذلك يجب التعامل مع كل صفقة كمعلومة تحليلية وليست وعداً بالربح."},
{"id":6,"title":"متى نوقف نشر الإشارات؟","category":"منهجية","date":"2026-09-28","summary":"جودة البيانات أهم من كثرة الصفقات.","body":"عند تعطل المصدر أو نقص الشموع أو وجود بيانات غير صالحة، الأفضل إيقاف الإشارة مؤقتاً بدلاً من نشر نتيجة غير موثوقة."}
]

BLOG=[
{"id":1,"title":"كيف تقرأ حركة السعر قبل الدخول في الصفقة","category":"أساسيات التداول","date":"2026-09-28","summary":"منهج عملي لفهم الاتجاه والقوة والرفض من السعر الخام.","body":"ابدأ بقراءة القمم والقيعان والإغلاقات ومناطق التفاعل. لا تحتاج إلى مؤشرات حتى تعرف هل الحركة مستمرة أم تفقد قوتها. راقب أين يغلق السعر بالنسبة إلى نطاقه، وهل يحافظ على القمم والقيعان الجديدة."},
{"id":2,"title":"الدعم والمقاومة: كيف تحدد المنطقة وليس الخط","category":"حركة السعر","date":"2026-09-28","summary":"لماذا تتعامل مع الدعم والمقاومة كمناطق تفاعل.","body":"السعر لا يحترم دائماً رقماً واحداً. ابحث عن مناطق تكرر عندها الرفض أو القبول، ثم راقب ما يحدث عندما يعود السعر إليها. تحول المقاومة إلى دعم أو العكس يصبح أكثر أهمية عندما يؤكده سلوك السعر."},
{"id":3,"title":"الاختراق الحقيقي والاختراق الكاذب","category":"اختراقات","date":"2026-09-28","summary":"علامات تساعدك على التفريق بين الاختراق والاستدراج.","body":"لا يكفي أن يلمس السعر مستوى سابقاً. راقب الإغلاق خارج المنطقة، ثم سلوك السعر عند إعادة الاختبار. العودة السريعة داخل النطاق بعد الاختراق قد تكون علامة على فشل الحركة، بينما الثبات خارج المنطقة يعطي سياقاً مختلفاً."},
{"id":4,"title":"السيولة وسحب السيولة في حركة السعر","category":"السيولة","date":"2026-09-28","summary":"فهم مناطق القمم والقيعان التي قد يتجمع حولها الطلب والعرض.","body":"القمم والقيعان الواضحة تجذب الانتباه لأنها مناطق يتوقع عندها المتداولون أوامر ووقفات. عندما يخترق السعر قمة أو قاعاً ثم يعود ويغلق داخل المنطقة، راقب ذلك كسلوك رفض وليس كاختراق مؤكد."},
{"id":5,"title":"هيكل السوق: القمم والقيعان أهم من الضوضاء","category":"هيكل السوق","date":"2026-09-28","summary":"طريقة بسيطة لفهم استمرار الاتجاه أو تغيره.","body":"قارن مجموعات القمم والقيعان بدلاً من التركيز على شمعة واحدة. ارتفاع القمم والقيعان يشير إلى بنية صاعدة، وانخفاضها يشير إلى بنية هابطة، أما التداخل الكبير فيعني أن السوق قد يكون في مرحلة تذبذب."},
{"id":6,"title":"إدارة المخاطر: أين تضع نقطة إلغاء الفكرة؟","category":"إدارة المخاطر","date":"2026-09-28","summary":"الوقف ليس رقماً عشوائياً بل نقطة يصبح عندها سيناريو الصفقة غير صالح.","body":"قبل الدخول حدد المستوى الذي إذا وصل إليه السعر تصبح فكرتك غير صحيحة. لا تجعل الهدف هو العامل الوحيد في القرار. أوامر الوقف قد تنفذ بسعر مختلف عن سعر الوقف في الأسواق السريعة، لذلك يجب فهم مخاطر التنفيذ والسيولة."},
{"id":7,"title":"لماذا لا توجد صفقة أحياناً؟","category":"منهجية","date":"2026-09-28","summary":"عدم التداول قرار صحيح عندما تكون البيانات متضاربة أو ناقصة.","body":"ليس مطلوباً أن ينتج السوق صفقة كل دقيقة. عندما تختلف قراءات حركة السعر أو لا تتوفر بيانات كافية، الانتظار أفضل من اختراع إشارة. التداول قصير الأجل يحمل مخاطر مرتفعة، خصوصاً مع الرافعة المالية."},
{"id":8,"title":"كيف تقرأ الشمعة بدون مؤشرات","category":"الشموع","date":"2026-09-28","summary":"الجسم والظلال والإغلاق تعطي معلومات عن سلوك السعر.","body":"قارن حجم جسم الشمعة بنطاقها، وانظر إلى مكان الإغلاق والظلال. شمعة ذات إغلاق قوي قرب أحد طرفي النطاق تختلف عن شمعة أغلقت بعد رفض واضح من مستوى سعري."},
{"id":9,"title":"من الفريم الكبير إلى الفريم الصغير","category":"الفريمات","date":"2026-09-28","summary":"تنظيم القراءة بين الشهري والأسبوعي واليومي والفريمات الأقصر.","body":"ابدأ بالسياق العام ثم انتقل للفريم الذي تريد التداول عليه. لا تجعل حركة صغيرة تلغي السياق الأكبر مباشرة؛ ابحث عن نقطة واضحة تتغير عندها بنية السوق."},
{"id":10,"title":"كيف تقيس جودة الصفقة بدون وعود بالربح","category":"منهجية","date":"2026-09-28","summary":"تقييم الصفقة بناءً على وضوح الفكرة والمخاطرة وليس ضمان النتيجة.","body":"جودة التحليل لا تعني ضمان الربح. قيّم وضوح الاتجاه، نقطة إلغاء الفكرة، المسافة إلى الأهداف، وسلوك السعر بعد الدخول. كل استثمار يحمل درجة من المخاطرة."}
]

@app.get("/api/news")
def news():return {"items":NEWS}
@app.get("/api/news/{item_id}")
def news_item(item_id:int):return next((x for x in NEWS if x["id"]==item_id),{"error":"not_found"})
@app.get("/api/blog")
def blog():return {"items":BLOG}
@app.get("/api/blog/{item_id}")
def blog_item(item_id:int):return next((x for x in BLOG if x["id"]==item_id),{"error":"not_found"})

# Northflank deployment sync marker
