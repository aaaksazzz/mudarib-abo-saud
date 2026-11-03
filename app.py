import os, re, secrets, hashlib, hmac, time, json, math
from datetime import datetime, timedelta, timezone
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, request, jsonify, send_from_directory, session, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from apscheduler.schedulers.background import BackgroundScheduler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///smart_trading_pro.db").replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
db=SQLAlchemy(app)
limiter=Limiter(get_remote_address,app=app,default_limits=["300 per hour"],storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI","memory://"))
MARKETS=("spot","futures","alpha","us-stocks","us-contracts","saudi","forex")
SECTION_DEFAULTS={k:True for k in ("overview",)+MARKETS+("strategies","journal","blog","news")}
BINANCE_SPOT="https://api.binance.com"
BINANCE_FUTURES="https://fapi.binance.com"
STABLES={"USDT","USDC","BUSD","FDUSD","TUSD","USDP","DAI","USDE","USDS","USTC"}

class User(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    email=db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash=db.Column(db.String(255), nullable=False)
    role=db.Column(db.String(20), nullable=False, default="user")
    active=db.Column(db.Boolean, nullable=False, default=True)
    created_at=db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    subscription_until=db.Column(db.DateTime)
    subscription_plan=db.Column(db.String(40), default="free")

class Setting(db.Model):
    key=db.Column(db.String(100), primary_key=True)
    value=db.Column(db.Text, nullable=False)

class Trade(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    market=db.Column(db.String(30), nullable=False, index=True)
    symbol=db.Column(db.String(40), nullable=False)
    side=db.Column(db.String(8), nullable=False)
    entry=db.Column(db.Float, nullable=False)
    stop=db.Column(db.Float, nullable=False)
    tp1=db.Column(db.Float, nullable=False)
    tp2=db.Column(db.Float, nullable=False)
    tp3=db.Column(db.Float, nullable=False)
    score=db.Column(db.Float, nullable=False)
    timeframe=db.Column(db.String(10), nullable=False, default="15m")
    reason=db.Column(db.Text, nullable=False, default="")
    status=db.Column(db.String(20), nullable=False, default="active", index=True)
    created_at=db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at=db.Column(db.DateTime, nullable=False)
    result_pct=db.Column(db.Float)

class Article(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    kind=db.Column(db.String(10), nullable=False, default="blog")
    title=db.Column(db.String(220), nullable=False)
    slug=db.Column(db.String(240), unique=True, nullable=False)
    summary=db.Column(db.String(500), nullable=False, default="")
    body=db.Column(db.Text, nullable=False, default="")
    published=db.Column(db.Boolean, nullable=False, default=False)
    created_at=db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class Audit(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    actor_id=db.Column(db.Integer)
    action=db.Column(db.String(100), nullable=False)
    target=db.Column(db.String(200), default="")
    created_at=db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

def utcnow(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat() if dt else None
def aware(dt): return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt
def json_error(message, code=400): return jsonify({"ok":False,"error":message}),code
def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(32)
    return session["csrf"]
@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response
@app.before_request
def security_and_identity():
    g.user=db.session.get(User, session.get("uid")) if session.get("uid") else None
    if request.method in ("POST","PUT","PATCH","DELETE") and request.path.startswith("/api/"):
        token=request.headers.get("X-CSRF-Token","")
        if not token or not hmac.compare_digest(token, session.get("csrf","")):
            return json_error("CSRF token invalid; refresh the page", 403)
def login_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not g.user or not g.user.active: return json_error("تسجيل الدخول مطلوب",401)
        
        return fn(*a,**kw)
    return inner
def subscriber_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not g.user or not g.user.active: return json_error("تسجيل الدخول مطلوب",401)
        if g.user.role!="admin" and (not g.user.subscription_until or aware(g.user.subscription_until)<=utcnow()): return json_error("يلزم اشتراك فعال للوصول إلى الصفقات",403)
        return fn(*a,**kw)
    return inner
def admin_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not g.user or g.user.role!="admin": return json_error("صلاحية الإدارة مطلوبة",403)
        return fn(*a,**kw)
    return inner
def audit(action,target=""):
    db.session.add(Audit(actor_id=g.user.id if g.user else None,action=action,target=str(target)[:200]))
def section_enabled(name):
    row=db.session.get(Setting,"section:"+name)
    return json.loads(row.value) if row else SECTION_DEFAULTS.get(name,True)
def gate_section(name):
    if not section_enabled(name): return json_error("هذا القسم متوقف حالياً",404)
    return None
def user_json(u):
    return {"id":u.id,"email":u.email,"role":u.role,"active":u.active,"plan":u.subscription_plan,"subscription_until":iso(u.subscription_until),"subscribed":bool(u.role=="admin" or (u.subscription_until and aware(u.subscription_until)>utcnow()))}
def public_article(a):
    return {"id":a.id,"kind":a.kind,"title":a.title,"slug":a.slug,"summary":a.summary,"body":a.body,"created_at":iso(a.created_at)}
@app.get("/")
def home(): return send_from_directory(".", "index.html")
@app.get("/styles.css")
def styles(): return send_from_directory(".", "styles.css")
@app.get("/platform.js")
def platform_script(): return send_from_directory(".", "platform.js")
@app.get("/pro-theme.css")
def pro_theme(): return send_from_directory(".", "pro-theme.css")
@app.get("/health")
def health(): return jsonify({"ok":True,"service":"SMART TRADING PRO","time":iso(utcnow())})
@app.get("/api/bootstrap")
def bootstrap():
    return jsonify({"ok":True,"csrf":csrf_token(),"user":user_json(g.user) if g.user else None,"sections":{k:section_enabled(k) for k in SECTION_DEFAULTS},"markets":MARKETS})
@app.post("/api/auth/register")
@limiter.limit("5 per minute")
def register():
    data=request.get_json(silent=True) or {}; email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email): return json_error("البريد الإلكتروني غير صحيح")
    if len(password)<12 or not re.search(r"[A-Za-z]",password) or not re.search(r"\d",password): return json_error("كلمة المرور يجب أن تكون 12 خانة على الأقل وتحتوي حروفاً وأرقاماً")
    if User.query.filter_by(email=email).first(): return json_error("البريد مسجل مسبقاً",409)
    u=User(email=email,password_hash=generate_password_hash(password),role="user")
    db.session.add(u); db.session.commit(); session.clear(); session["uid"]=u.id; session.permanent=True; csrf_token()
    return jsonify({"ok":True,"user":user_json(u),"csrf":session["csrf"]}),201
@app.post("/api/auth/login")
@limiter.limit("5 per minute")
def login():
    data=request.get_json(silent=True) or {}; email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
    u=User.query.filter_by(email=email).first()
    if not u or not check_password_hash(u.password_hash,password) or not u.active: return json_error("بيانات الدخول غير صحيحة",401)
    session.clear(); session["uid"]=u.id; session.permanent=True; csrf_token()
    return jsonify({"ok":True,"user":user_json(u),"csrf":session["csrf"]})
@app.post("/api/auth/logout")
@login_required
def logout():
    session.clear(); return jsonify({"ok":True})
@app.get("/api/me")
@login_required
def me(): return jsonify({"ok":True,"user":user_json(g.user)})
@app.get("/api/markets")
def market_list():
    return jsonify({"ok":True,"markets":[{"id":m,"enabled":section_enabled(m),"provider":provider_status(m)} for m in MARKETS]})
def provider_status(m):
    if m in ("spot","futures"): return {"ready":True,"source":"Binance public market API"}
    if m in ("us-stocks","us-contracts","saudi","forex"):
        key={"us-stocks":"FINNHUB_API_KEY","us-contracts":"FINNHUB_API_KEY","saudi":"SAUDI_DATA_API_KEY","forex":"TWELVEDATA_API_KEY"}[m]
        return {"ready":False,"configured":bool(os.environ.get(key)),"source":key,"message":"الموصل البرمجي لهذا المزود لم يكتمل بعد"}
    return {"ready":False,"source":"Alpha universe adapter not configured"}
def fetch_json(url,params=None):
    r=requests.get(url,params=params,timeout=12,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
    r.raise_for_status(); return r.json()
def market_tickers(market):
    if market=="spot":
        info=fetch_json(BINANCE_SPOT+"/api/v3/exchangeInfo")
        tickers=fetch_json(BINANCE_SPOT+"/api/v3/ticker/24hr")
        valid={x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True) and x.get("baseAsset") not in STABLES}
    elif market=="futures":
        info=fetch_json(BINANCE_FUTURES+"/fapi/v1/exchangeInfo")
        tickers=fetch_json(BINANCE_FUTURES+"/fapi/v1/ticker/24hr")
        valid={x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL"}
    else: return None
    out=[]
    for t in tickers:
        if t.get("symbol") not in valid: continue
        try:
            vol=float(t.get("quoteVolume",0)); change=float(t.get("priceChangePercent",0)); price=float(t.get("lastPrice",0))
            if vol<1_000_000 or price<=0: continue
            out.append({"symbol":t["symbol"],"price":price,"change_pct":change,"quote_volume":vol})
        except (ValueError,TypeError): continue
    return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
@app.get("/api/markets/<market>/snapshot")
def snapshot(market):
    if market not in MARKETS: return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked: return blocked
    if market not in ("spot","futures"): return jsonify({"ok":True,"market":market,"ready":provider_status(market)["ready"],"provider":provider_status(market),"direction":"غير متاح","up":None,"down":None,"assets":[],"message":"مصدر البيانات غير مربوط؛ لن نعرض أرقاماً تقديرية."})
    try:
        rows=market_tickers(market); up=sum(1 for x in rows if x["change_pct"]>0); down=sum(1 for x in rows if x["change_pct"]<0)
        return jsonify({"ok":True,"market":market,"direction":"صاعد" if up>down else "هابط" if down>up else "متعادل","up":up,"down":down,"total":len(rows),"assets":rows[:40],"updated_at":iso(utcnow())})
    except Exception as e:
        app.logger.exception("snapshot failed"); return json_error("تعذر جلب بيانات السوق من المصدر حالياً",502)
def klines(market,symbol,interval,limit=120):
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    return fetch_json(base+path,{"symbol":symbol,"interval":interval,"limit":limit})
def ema(values,period):
    if len(values)<period: return None
    k=2/(period+1); v=sum(values[:period])/period
    for x in values[period:]: v=x*k+v*(1-k)
    return v
def build_signal(market,item):
    symbol=item["symbol"]
    k15=klines(market,symbol,"15m",100); k4=klines(market,symbol,"4h",80); kd=klines(market,symbol,"1d",60)
    c15=[float(x[4]) for x in k15[:-1]]; h15=[float(x[2]) for x in k15[:-1]]; l15=[float(x[3]) for x in k15[:-1]]; v15=[float(x[5]) for x in k15[:-1]]
    c4=[float(x[4]) for x in k4[:-1]]; cd=[float(x[4]) for x in kd[:-1]]
    e20,e50=ema(c15,20),ema(c15,50); e4=ema(c4,20); ed=ema(cd,20)
    if not all((e20,e50,e4,ed)) or len(c15)<25: return None
    side="BUY" if c4[-1]>e4 and cd[-1]>ed else "SELL" if c4[-1]<e4 and cd[-1]<ed else None
    if not side: return None
    momentum=(c15[-1]/c15[-5]-1)*100 if c15[-5] else 0
    if (side=="BUY" and (e20<=e50 or momentum<=0)) or (side=="SELL" and (e20>=e50 or momentum>=0)): return None
    tr=[]
    for i in range(1,len(c15)):
        tr.append(max(h15[i]-l15[i],abs(h15[i]-c15[i-1]),abs(l15[i]-c15[i-1])))
    atr=sum(tr[-14:])/14 if len(tr)>=14 else 0
    entry=c15[-1]; risk=max(atr*1.5,entry*0.003)
    stop=entry-risk if side=="BUY" else entry+risk
    sign=1 if side=="BUY" else -1
    score=min(95,60+abs(momentum)*3+min(item["quote_volume"]/20_000_000,10))
    return {"market":market,"symbol":symbol,"side":side,"entry":entry,"stop":stop,"tp1":entry+sign*risk,"tp2":entry+sign*risk*2,"tp3":entry+sign*risk*3,"score":round(score,1),"timeframe":"15m","reason":"اتجاه 4س واليومي متوافق، مع تأكيد EMA20/50 وزخم 15 دقيقة وحجم تداول.","status":"active","change_pct":item["change_pct"],"quote_volume":item["quote_volume"]}
def run_market_scan(market):
    now=utcnow()
    scan_key="scan:"+market
    scan_row=db.session.get(Setting,scan_key)
    if scan_row:
        try:
            last=datetime.fromisoformat(scan_row.value)
            if aware(last)>now-timedelta(minutes=15):
                active=Trade.query.filter_by(market=market,status="active").filter(Trade.expires_at>now).order_by(Trade.score.desc()).limit(10).all()
                return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":scan_row.value,"cached":True}
        except ValueError: pass
    movers=sorted(market_tickers(market),key=lambda x:abs(x["change_pct"]),reverse=True)[:18]
    found=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs=[pool.submit(build_signal,market,x) for x in movers]
        for job in as_completed(jobs):
            try:
                signal=job.result()
                if signal: found.append(signal)
            except Exception: continue
    found.sort(key=lambda x:(x["score"],abs(x["change_pct"])),reverse=True)
    Trade.query.filter(Trade.market==market,Trade.status=="active",Trade.created_at<now-timedelta(hours=24)).update({"status":"expired"})
    for signal in found[:10]:
        exists=Trade.query.filter_by(market=market,symbol=signal["symbol"],status="active").first()
        if exists and aware(exists.created_at)>now-timedelta(minutes=15): continue
        if exists: exists.status="superseded"
        db.session.add(Trade(market=market,symbol=signal["symbol"],side=signal["side"],entry=signal["entry"],stop=signal["stop"],tp1=signal["tp1"],tp2=signal["tp2"],tp3=signal["tp3"],score=signal["score"],timeframe="15m",reason=signal["reason"],expires_at=now+timedelta(hours=24)))
    if not scan_row: scan_row=Setting(key=scan_key,value=iso(now)); db.session.add(scan_row)
    else: scan_row.value=iso(now)
    db.session.commit()
    active=Trade.query.filter_by(market=market,status="active").filter(Trade.expires_at>now).order_by(Trade.score.desc()).limit(10).all()
    return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":iso(now),"scan_universe":len(movers)}
@app.get("/api/markets/<market>/signals")
def signals(market):
    if market not in MARKETS: return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked: return blocked
    if market not in ("spot","futures"): return jsonify({"ok":True,"market":market,"signals":[],"message":"مصدر بيانات هذا السوق غير مربوط بعد."})
    try: return jsonify(run_market_scan(market))
    except Exception:
        app.logger.exception("signal scan failed")
        return json_error("تعذر إكمال الفحص حالياً؛ تحقق من مصدر البيانات وحاول لاحقاً",502)
def trade_json(t):
    return {"id":t.id,"market":t.market,"symbol":t.symbol,"side":t.side,"entry":t.entry,"stop":t.stop,"tp1":t.tp1,"tp2":t.tp2,"tp3":t.tp3,"score":t.score,"timeframe":t.timeframe,"reason":t.reason,"status":t.status,"created_at":iso(t.created_at),"expires_at":iso(t.expires_at)}
@app.get("/api/trades")
def trade_history():
    q=Trade.query.order_by(Trade.created_at.desc()).limit(200)
    return jsonify({"ok":True,"trades":[trade_json(x) for x in q.all()]})
@app.get("/api/strategies")
def strategies():
    if not section_enabled("strategies"): return json_error("قسم الاستراتيجيات متوقف",404)
    return jsonify({"ok":True,"strategies":[{"id":"trend-momentum-v1","name":"اتجاه متعدد الأطر + زخم","markets":["spot","futures"],"frames":["15m","4h","1d"],"rules":["اتجاه 4 ساعات واليومي متوافق","EMA20/EMA50 على 15 دقيقة","زخم 15 دقيقة يؤكد الاتجاه","وقف مبني على ATR وأهداف 1R/2R/3R"],"status":"active","note":"نسخة أولية قابلة للاختبار؛ لا يوجد ادعاء بنسبة نجاح قبل اختبار تاريخي مستقل."}]})
@app.get("/api/content/<kind>")
def content_list(kind):
    if kind not in ("blog","news"): return json_error("نوع المحتوى غير معروف",404)
    if not section_enabled(kind): return json_error("القسم متوقف",404)
    rows=Article.query.filter_by(kind=kind,published=True).order_by(Article.created_at.desc()).limit(50).all()
    return jsonify({"ok":True,"items":[public_article(x) for x in rows]})
@app.post("/api/admin/login-bootstrap")
@limiter.limit("3 per hour")
def admin_bootstrap():
    # One-time bootstrap protected by an out-of-band secret; disabled after first admin exists.
    secret=os.environ.get("ADMIN_BOOTSTRAP_TOKEN","")
    if not secret or User.query.filter_by(role="admin").first(): return json_error("تهيئة المدير غير متاحة",404)
    data=request.get_json(silent=True) or {}
    if not hmac.compare_digest(str(data.get("token","")),secret): return json_error("رمز التهيئة غير صحيح",403)
    email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(password)<14: return json_error("بيانات المدير غير مستوفية لشروط الأمان")
    u=User(email=email,password_hash=generate_password_hash(password),role="admin",subscription_plan="admin")
    db.session.add(u); db.session.commit(); session.clear(); session["uid"]=u.id; session.permanent=True; csrf_token()
    return jsonify({"ok":True,"user":user_json(u),"csrf":session["csrf"]}),201
@app.get("/api/admin/overview")
@login_required
@admin_required
def admin_overview():
    return jsonify({"ok":True,"users":User.query.count(),"active_trades":Trade.query.filter_by(status="active").count(),"articles":Article.query.count(),"sections":{k:section_enabled(k) for k in SECTION_DEFAULTS},"recent_audit":[{"action":x.action,"target":x.target,"at":iso(x.created_at)} for x in Audit.query.order_by(Audit.created_at.desc()).limit(30).all()]})
@app.get("/api/admin/users")
@login_required
@admin_required
def admin_users():
    return jsonify({"ok":True,"users":[user_json(x) for x in User.query.order_by(User.created_at.desc()).limit(500).all()]})
@app.post("/api/admin/users/<int:user_id>/subscription")
@login_required
@admin_required
def grant_subscription(user_id):
    u=db.session.get(User,user_id)
    if not u: return json_error("المستخدم غير موجود",404)
    data=request.get_json(silent=True) or {}
    try: days=int(data.get("days",0))
    except (TypeError,ValueError): return json_error("مدة الاشتراك غير صحيحة")
    if days<1 or days>3650: return json_error("مدة الاشتراك يجب أن تكون من يوم إلى 10 سنوات")
    base=max(aware(u.subscription_until) or utcnow(),utcnow()); u.subscription_until=base+timedelta(days=days); u.subscription_plan=str(data.get("plan","pro"))[:40]; audit("subscription_granted",f"{u.email}:{days}d"); db.session.commit()
    return jsonify({"ok":True,"user":user_json(u)})
@app.patch("/api/admin/users/<int:user_id>")
@login_required
@admin_required
def update_user(user_id):
    u=db.session.get(User,user_id)
    if not u: return json_error("المستخدم غير موجود",404)
    data=request.get_json(silent=True) or {}
    if "active" in data: u.active=bool(data["active"])
    if "role" in data and data["role"] in ("user","admin") and u.id!=g.user.id: u.role=data["role"]
    audit("user_updated",u.email); db.session.commit(); return jsonify({"ok":True,"user":user_json(u)})
@app.put("/api/admin/sections/<name>")
@login_required
@admin_required
def update_section(name):
    if name not in SECTION_DEFAULTS: return json_error("القسم غير معروف",404)
    enabled=bool((request.get_json(silent=True) or {}).get("enabled"))
    row=db.session.get(Setting,"section:"+name)
    if not row: row=Setting(key="section:"+name,value=json.dumps(enabled)); db.session.add(row)
    else: row.value=json.dumps(enabled)
    audit("section_toggled",f"{name}:{enabled}"); db.session.commit(); return jsonify({"ok":True,"section":name,"enabled":enabled})
@app.post("/api/admin/content")
@login_required
@admin_required
def create_content():
    data=request.get_json(silent=True) or {}; kind=data.get("kind","blog"); title=str(data.get("title","")).strip(); body=str(data.get("body","")).strip()
    if kind not in ("blog","news") or not title or not body: return json_error("العنوان والمحتوى مطلوبان")
    slug=re.sub(r"[^a-z0-9\u0600-\u06ff]+","-",title.lower()).strip("-")[:200] or secrets.token_hex(8)
    if Article.query.filter_by(slug=slug).first(): slug+="-"+secrets.token_hex(3)
    a=Article(kind=kind,title=title[:220],slug=slug,summary=str(data.get("summary",""))[:500],body=body,published=bool(data.get("published",False)))
    db.session.add(a); audit("content_created",slug); db.session.commit(); return jsonify({"ok":True,"item":public_article(a)}),201
@app.delete("/api/admin/content/<int:item_id>")
@login_required
@admin_required
def delete_content(item_id):
    a=db.session.get(Article,item_id)
    if not a: return json_error("المحتوى غير موجود",404)
    db.session.delete(a); audit("content_deleted",item_id); db.session.commit(); return jsonify({"ok":True})
@app.get("/api/admin/providers")
@login_required
@admin_required
def providers(): return jsonify({"ok":True,"providers":{m:provider_status(m) for m in MARKETS}})
@app.errorhandler(413)
def too_large(_): return json_error("حجم الطلب أكبر من المسموح",413)
@app.errorhandler(429)
def limited(_): return json_error("طلبات كثيرة؛ حاول بعد قليل",429)
with app.app_context():
    db.create_all()
    # Optional first administrator provisioning from deployment secrets.
    admin_email=os.environ.get("ADMIN_EMAIL","").strip().lower(); admin_password=os.environ.get("ADMIN_PASSWORD","")
    if admin_email and admin_password and not User.query.filter_by(role="admin").first():
        if len(admin_password)>=14 and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",admin_email):
            db.session.add(User(email=admin_email,password_hash=generate_password_hash(admin_password),role="admin",subscription_plan="admin")); db.session.commit()

def scheduled_market_scan():
    with app.app_context():
        for market in ("spot","futures"):
            try:
                run_market_scan(market)
                app.logger.info("scheduled scan completed: %s",market)
            except Exception:
                app.logger.exception("scheduled scan failed: %s",market)

if os.environ.get("ENABLE_AUTO_SCAN","true").lower()=="true":
    scheduler=BackgroundScheduler(timezone="UTC")
    scheduler.add_job(scheduled_market_scan,"interval",minutes=15,id="market-scan-15m",max_instances=1,coalesce=True,next_run_time=utcnow()+timedelta(seconds=30))
    scheduler.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","8080")))
