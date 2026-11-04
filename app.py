import os, re, secrets, hashlib, hmac, time, json, math
from datetime import datetime, timedelta, timezone
from functools import wraps, lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import market_adapters
import market_strategies
from flask import Flask, request, jsonify, send_from_directory, session, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, text, inspect, or_
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
OPEN_TRADE_STATUSES=("active","tp1_hit","tp2_hit")
PAYMENT_PLANS=[
    {"id":"monthly","name":"شهري","months":1,"price_usd":30.0,"discount_pct":0,"total_usd":30.0},
    {"id":"six_months","name":"6 أشهر","months":6,"price_usd":171.0,"discount_pct":5,"total_usd":171.0,"regular_usd":180.0},
    {"id":"yearly","name":"سنوي","months":12,"price_usd":324.0,"discount_pct":10,"total_usd":324.0,"regular_usd":360.0},
]
PAYMENT_METHODS={
    "usdt_trc20":{"label":"USDT · TRC20","address":"TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6"},
    "sol":{"label":"Solana · SOL","address":"8mUuMV7WFNTsFEmGsw3t5EpTWGUzw5618Mjgh1svugaH"},
    "binance_uid":{"label":"معرّف حساب Binance","value":"28191866"},
}

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
    change_15m_pct=db.Column(db.Float)

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
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store, private, max-age=0"
        response.headers["Pragma"]="no-cache"
        response.headers["Vary"]="Cookie"
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
def subscription_is_active(user):
    if not user or not user.active: return False
    if user.role=="admin": return True
    if user.subscription_plan=="lifetime" and user.subscription_until is None: return True
    return bool(user.subscription_until and aware(user.subscription_until)>utcnow())

def subscriber_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not g.user or not g.user.active: return json_error("تسجيل الدخول مطلوب",401)
        if not subscription_is_active(g.user): return json_error("يلزم اشتراك فعال للوصول إلى الصفقات",403)
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
    return {"id":u.id,"email":u.email,"role":u.role,"active":u.active,"plan":u.subscription_plan,"subscription_until":iso(u.subscription_until),"subscribed":subscription_is_active(u),"lifetime":bool(u.subscription_plan=="lifetime" and u.subscription_until is None)}
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
def health():
    return jsonify({"ok":True,"service":"SMART TRADING PRO","time":iso(utcnow())})

@app.get("/ready")
def readiness():
    checks={"database":False,"persistent_database":False,"persistent_secret":bool(os.environ.get("SECRET_KEY")),"market_scheduler":False}
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"]=True
        checks["persistent_database"]=db.engine.dialect.name=="postgresql"
    except Exception:
        db.session.rollback()
        app.logger.exception("readiness database check failed")
    active_scheduler=globals().get("scheduler")
    checks["market_scheduler"]=bool(active_scheduler and active_scheduler.running)
    ready=all(checks.values())
    return jsonify({"ok":ready,"checks":checks,"time":iso(utcnow())}),200 if ready else 503
@app.get("/api/bootstrap")
def bootstrap():
    return jsonify({"ok":True,"csrf":csrf_token(),"user":user_json(g.user) if g.user else None,"sections":{k:section_enabled(k) for k in SECTION_DEFAULTS},"markets":MARKETS})
@app.post("/api/auth/register")
@limiter.limit("5 per minute")
def register():
    data=request.get_json(silent=True) or {}; email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email): return json_error("البريد الإلكتروني غير صحيح")
    if len(password)<12 or not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password): return json_error("كلمة المرور يجب أن تكون 12 خانة على الأقل وتحتوي حروفاً وأرقاماً")
    if User.query.filter_by(email=email).first(): return json_error("البريد مسجل مسبقاً",409)
    u=User(email=email,password_hash=generate_password_hash(password),role="user")
    db.session.add(u); db.session.commit(); session.clear(); session["uid"]=u.id; session.permanent=True; csrf_token()
    return jsonify({"ok":True,"user":user_json(u),"csrf":session["csrf"]}),201
@app.post("/api/auth/login")
@limiter.limit("5 per minute")
def login():
    data=request.get_json(silent=True) or {}; login_id=str(data.get("email",data.get("username",""))).strip().lower(); password=str(data.get("password",""))
    u=User.query.filter_by(email=login_id).first()
    admin_username=os.environ.get("ADMIN_USERNAME","").strip().casefold()
    configured_admin_email=os.environ.get("ADMIN_EMAIL","").strip().casefold()
    admin_aliases={value for value in (admin_username, configured_admin_email.partition("@")[0] if "@" in configured_admin_email else "") if value}
    if not u and any(hmac.compare_digest(login_id,alias) for alias in admin_aliases):
        u=User.query.filter_by(role="admin").first()
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
def admin_contact_url():
    row=db.session.get(Setting,"admin_contact_url")
    return (row.value if row else os.environ.get("ADMIN_CONTACT_URL","")).strip()

@app.get("/api/plans")
def public_plans():
    return jsonify({"ok":True,"currency":"USD","plans":PAYMENT_PLANS,"payment_methods":PAYMENT_METHODS,"contact_url":admin_contact_url(),"contact_label":"تواصل مع الإدارة"})

@app.put("/api/admin/contact")
@login_required
@admin_required
def update_admin_contact():
    url=str((request.get_json(silent=True) or {}).get("url","")).strip()
    if url and (not url.startswith("https://") or len(url)>500):
        return json_error("رابط التواصل يجب أن يبدأ بـ https://")
    row=db.session.get(Setting,"admin_contact_url")
    if not row:
        row=Setting(key="admin_contact_url",value=url)
        db.session.add(row)
    else:
        row.value=url
    audit("admin_contact_updated","configured" if url else "cleared")
    db.session.commit()
    return jsonify({"ok":True,"contact_url":admin_contact_url()})

@app.get("/api/markets")
def market_list():
    return jsonify({"ok":True,"markets":[{"id":m,"enabled":section_enabled(m),"provider":provider_status(m)} for m in MARKETS]})
def provider_status(m):
    sources={"spot":"Binance Spot public API","futures":"Binance USD-M Futures public API","alpha":"Binance Alpha public market API","us-stocks":"Yahoo Finance US equity screener","us-contracts":"Yahoo Finance US futures quotes","saudi":"Yahoo Finance Saudi-listed shares screener","forex":"Yahoo Finance FX and metals quotes"}
    return {"ready":m in sources,"source":sources.get(m,"غير معروف"),"timeframe":"15m","requires_api_key":False,"access":"public_no_key"}
def fetch_json(url,params=None):
    last_error=None
    for attempt in range(3):
        try:
            response=requests.get(url,params=params,timeout=(3.05,8),headers={"User-Agent":"SMART-TRADING-PRO/1.1"})
            if response.status_code==429 or response.status_code>=500:
                response.raise_for_status()
            response.raise_for_status()
            payload=response.json()
            if not isinstance(payload,(dict,list)):
                raise ValueError("Unexpected market-data response")
            return payload
        except (requests.Timeout,requests.ConnectionError,requests.HTTPError,ValueError) as exc:
            last_error=exc
            status=getattr(getattr(exc,"response",None),"status_code",None)
            if attempt==2 or (status is not None and status<500 and status!=429):
                raise
            time.sleep(0.25*(attempt+1))
    raise last_error
@lru_cache(maxsize=2)
def market_symbols(market):
    if market=="spot":
        info=fetch_json(BINANCE_SPOT+"/api/v3/exchangeInfo")
        return {x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True) and x.get("baseAsset") not in STABLES}
    if market=="futures":
        info=fetch_json(BINANCE_FUTURES+"/fapi/v1/exchangeInfo")
        return {x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL" and x.get("baseAsset") not in STABLES}
    return market_adapters.market_symbols(market)

def market_tickers(market):
    if market not in ("spot","futures"):
        return market_adapters.market_tickers(market)
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    endpoint="/fapi/v1/ticker/24hr" if market=="futures" else "/api/v3/ticker/24hr"
    valid=market_symbols(market)
    tickers=fetch_json(base+endpoint)
    out=[]
    for t in tickers:
        if t.get("symbol") not in valid: continue
        try:
            vol=float(t.get("quoteVolume",0)); change=float(t.get("priceChangePercent",0)); price=float(t.get("lastPrice",0))
            if not all(math.isfinite(value) for value in (vol,change,price)): continue
            if vol<1_000_000 or price<=0: continue
            out.append({"symbol":t["symbol"],"price":price,"change_pct":change,"quote_volume":vol})
        except (ValueError,TypeError): continue
    return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
@app.get("/api/markets/<market>/snapshot")
def snapshot(market):
    if market not in MARKETS: return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked: return blocked
    try:
        rows=market_tickers(market); up=sum(1 for x in rows if x["change_pct"]>0); down=sum(1 for x in rows if x["change_pct"]<0)
        return jsonify({"ok":True,"market":market,"direction":"صاعد" if up>down else "هابط" if down>up else "متعادل","direction_basis":"تغير السعر خلال 24 ساعة","up":up,"down":down,"total":len(rows),"assets":rows[:40],"updated_at":iso(utcnow())})
    except Exception as e:
        app.logger.exception("snapshot failed"); return json_error("تعذر جلب بيانات السوق من المصدر حالياً",502)
def klines(market,symbol,interval,limit=120):
    if market not in ("spot","futures"):
        return market_adapters.klines(market,symbol,interval,limit)
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    return fetch_json(base+path,{"symbol":symbol,"interval":interval,"limit":limit})
TIMEFRAMES=("15m",)
BINANCE_INTERVALS={"15m":"15m"}

def build_signal(market,item,timeframe):
    symbol=item["symbol"]
    try:
        rows=klines(market,symbol,"15m",120)
        setup=market_strategies.analyze(market,symbol,rows,include_micro=item.get("include_microstructure",False))
        if not setup:
            return None
        setup.update({"market":market,"symbol":symbol,"quote_volume":item.get("quote_volume",0),
                      "status":"active","timeframe":"15m"})
        return setup
    except Exception:
        app.logger.exception("VOLUME IMPULSE analysis failed for %s %s",market,symbol)
        return None

def expire_stale_trades(market=None):
    now=utcnow()
    query=Trade.query.filter(Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at<=now)
    if market:
        query=query.filter(Trade.market==market)
    changed=query.update({"status":"expired"},synchronize_session=False)
    if changed:
        db.session.commit()
    return changed

def update_trade_outcomes(market,tickers):
    prices={item["symbol"]:float(item["price"]) for item in tickers if item.get("symbol") and float(item.get("price") or 0)>0}
    trades=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES)).all()
    changed=0
    for trade in trades:
        price=prices.get(trade.symbol)
        if price is None or trade.entry<=0:
            continue
        direction=1 if trade.side=="BUY" else -1
        trade.result_pct=round((price/trade.entry-1)*direction*100,4)
        stop_hit=price<=trade.stop if trade.side=="BUY" else price>=trade.stop
        tp1_hit=price>=trade.tp1 if trade.side=="BUY" else price<=trade.tp1
        tp2_hit=price>=trade.tp2 if trade.side=="BUY" else price<=trade.tp2
        tp3_hit=price>=trade.tp3 if trade.side=="BUY" else price<=trade.tp3
        previous=trade.status
        if stop_hit:
            trade.status="stopped_after_tp2" if previous=="tp2_hit" else "stopped_after_tp1" if previous=="tp1_hit" else "stopped"
        elif tp3_hit:
            trade.status="tp3_hit"
        elif tp2_hit:
            trade.status="tp2_hit"
        elif tp1_hit and previous=="active":
            trade.status="tp1_hit"
        if trade.status!=previous:
            changed+=1
    if trades:
        db.session.commit()
    return changed

def run_market_scan(market,force=False):
    if market not in MARKETS:
        raise ValueError("Unknown market "+str(market))
    now=utcnow()
    expire_stale_trades(market)
    scan_key="scan:"+market
    scan_row=db.session.get(Setting,scan_key)
    if scan_row and not force:
        try:
            last=aware(datetime.fromisoformat(scan_row.value))
            if last>now-timedelta(minutes=15):
                active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at>now,Trade.reason.like("VOLUME IMPULSE%")).order_by(Trade.score.desc()).limit(3).all()
                meta_row=db.session.get(Setting,"scan-meta:"+market)
                try:
                    meta=json.loads(meta_row.value) if meta_row else {}
                except (ValueError,TypeError):
                    meta={}
                return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":scan_row.value,"cached":True,**meta}
        except (ValueError,TypeError):
            app.logger.warning("Invalid scan timestamp for %s; forcing a fresh scan",market)
    universe=market_tickers(market)
    if not universe:
        raise RuntimeError("Market provider returned an empty eligible universe")
    market_up=sum(1 for item in universe if item.get("change_pct",0)>0)
    market_down=sum(1 for item in universe if item.get("change_pct",0)<0)
    market_bias="BUY" if market_up>market_down else "SELL" if market_down>market_up else None
    # Update outcomes first, then keep the previous signal batch visible until
    # this scan has successfully analysed enough fresh candles.
    update_trade_outcomes(market,universe)
    # Scan liquid candidates on the single 15-minute timeframe.
    # Prioritize fast movers first; use traded value as the liquidity tie-breaker.
    # Scan a wider candidate set so the volume-only cutoff does not hide movers.
    candidates=sorted(universe,key=lambda x:(abs(float(x.get("change_pct") or 0)),float(x.get("quote_volume") or 0)),reverse=True)[:60]
    for index,item in enumerate(candidates):
        item["include_microstructure"]=(market=="futures" and index<12)
    jobs=[]
    found=[]
    completed=0
    failed=0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(build_signal,market,item,frame) for item in candidates for frame in TIMEFRAMES]
        for future in as_completed(futures):
            try:
                signal=future.result()
                completed+=1
                if signal:
                    found.append(signal)
            except Exception:
                failed+=1
                app.logger.exception("15-minute signal analysis failed for %s",market)
    if completed<max(1,math.ceil(len(futures)*0.8)):
        raise RuntimeError(f"Insufficient candle data: {completed}/{len(futures)} analyses completed")
    # Only publish signals aligned with the market-wide direction.
    found=[x for x in found if market_bias and x["side"]==market_bias]
    # A successful 15m scan replaces the complete previous signal batch.
    # Keep historical rows, but never let old coins remain in the live feed.
    Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES)).update(
        {"status":"superseded"},synchronize_session=False
    )
    # Ranking is by consensus confidence, then traded value.
    for frame in TIMEFRAMES:
        frame_signals=sorted((x for x in found if x["timeframe"]==frame),key=lambda x:(x["score"],x.get("quote_volume",0)),reverse=True)
        for signal in frame_signals[:3]:
            db.session.add(Trade(market=market,symbol=signal["symbol"],side=signal["side"],entry=signal["entry"],stop=signal["stop"],tp1=signal["tp1"],tp2=signal["tp2"],tp3=signal["tp3"],score=signal["score"],change_15m_pct=signal["change_pct"],timeframe=frame,reason=signal["reason"],expires_at=now+timedelta(hours=24)))
    if not scan_row:
        scan_row=Setting(key=scan_key,value=iso(now)); db.session.add(scan_row)
    else:
        scan_row.value=iso(now)
    meta_key="scan-meta:"+market
    meta_row=db.session.get(Setting,meta_key)
    meta_value=json.dumps({"scan_universe":len(candidates),"analysis_completed":completed,"analysis_failed":failed,"market_bias":market_bias,"timeframes":list(TIMEFRAMES)},ensure_ascii=False)
    if not meta_row:
        db.session.add(Setting(key=meta_key,value=meta_value))
    else:
        meta_row.value=meta_value
    db.session.commit()
    active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at>now).order_by(Trade.score.desc()).limit(3).all()
    return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":iso(now),"scan_universe":len(candidates),"analysis_completed":completed,"analysis_failed":failed,"market_bias":market_bias,"timeframes":list(TIMEFRAMES)}
@app.get("/api/markets/<market>/signals")
def signals(market):
    if market not in MARKETS:
        return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked:
        return blocked
    try:
        # Keep web requests fast: the scheduler owns scans; page loads only read the latest committed result.
        expire_stale_trades(market)
        row=db.session.get(Setting,"scan:"+market)
        active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at>utcnow(),Trade.reason.like("VOLUME IMPULSE%")).order_by(func.abs(Trade.change_15m_pct).desc()).limit(60).all()
        updated=row.value if row else None
        meta_row=db.session.get(Setting,"scan-meta:"+market)
        try:
            meta=json.loads(meta_row.value) if meta_row else {}
        except (ValueError,TypeError):
            meta={}
        stale=True
        if updated:
            try:
                stale=aware(datetime.fromisoformat(updated))<utcnow()-timedelta(minutes=20)
            except (ValueError,TypeError):
                stale=True
        # Never present an old batch as current opportunities when the
        # 15-minute scanner has stopped or fallen behind.
        return jsonify({"ok":True,"market":market,"signals":[trade_json(x) for x in active] if not stale else [],"updated_at":updated,"cached":True,"stale":stale,"scan_ready":bool(updated),**meta})
    except Exception:
        app.logger.exception("signal retrieval failed")
        return json_error("تعذر قراءة نتائج الفحص المحفوظة حالياً",503)
def trade_json(t):
    # Public trade payload contains execution levels and status only; never disclose strategy rationale.
    return {"id":t.id,"market":t.market,"symbol":t.symbol,"side":t.side,"entry":t.entry,"stop":t.stop,"tp1":t.tp1,"tp2":t.tp2,"tp3":t.tp3,"score":t.score,"change_15m_pct":t.change_15m_pct,"change_pct":t.change_15m_pct,"timeframe":t.timeframe,"status":t.status,"result_pct":t.result_pct,"created_at":iso(t.created_at),"expires_at":iso(t.expires_at)}
@app.get("/api/trades")
def trade_history():
    expire_stale_trades()
    q=Trade.query.order_by(Trade.created_at.desc()).limit(200)
    return jsonify({"ok":True,"trades":[trade_json(x) for x in q.all()]})
@app.get("/api/strategies")
def strategies():
    # Strategy documentation is private operational logic, not a customer-facing endpoint.
    return json_error("غير متاح",404)
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
    return jsonify({"ok":True,"users":User.query.count(),"active_trades":Trade.query.filter(Trade.status.in_(OPEN_TRADE_STATUSES)).count(),"articles":Article.query.count(),"sections":{k:section_enabled(k) for k in SECTION_DEFAULTS},"recent_audit":[{"action":x.action,"target":x.target,"at":iso(x.created_at)} for x in Audit.query.order_by(Audit.created_at.desc()).limit(30).all()]})
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
    if data.get("lifetime") is True:
        u.subscription_until=None
        u.subscription_plan="lifetime"
        audit("lifetime_subscription_granted",u.email)
        db.session.commit()
        return jsonify({"ok":True,"user":user_json(u)})
    try: days=int(data.get("days",0))
    except (TypeError,ValueError): return json_error("مدة الاشتراك غير صحيحة")
    if days<1 or days>3650: return json_error("مدة الاشتراك يجب أن تكون من يوم إلى 10 سنوات")
    base=max(aware(u.subscription_until) or utcnow(),utcnow()); u.subscription_until=base+timedelta(days=days); u.subscription_plan=str(data.get("plan","pro"))[:40]; audit("subscription_granted",f"{u.email}:{days}d"); db.session.commit()
    return jsonify({"ok":True,"user":user_json(u)})

@app.post("/api/admin/users/subscription-by-email")
@login_required
@admin_required
def grant_subscription_by_email():
    data=request.get_json(silent=True) or {}
    email=str(data.get("email","")).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email):
        return json_error("البريد الإلكتروني غير صحيح")
    u=User.query.filter_by(email=email).first()
    if not u: return json_error("الحساب غير مسجل بعد؛ يجب إنشاء الحساب أولاً",404)
    if data.get("lifetime") is not True: return json_error("نوع الاشتراك غير صحيح")
    u.subscription_until=None
    u.subscription_plan="lifetime"
    audit("lifetime_subscription_granted",u.email)
    db.session.commit()
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
def provision_admin_from_env():
    """Create the first admin or synchronize configured admin credentials on restart."""
    admin_email=os.environ.get("ADMIN_EMAIL","").strip().lower()
    admin_password=os.environ.get("ADMIN_PASSWORD","")
    if not admin_email or not admin_password:
        return
    if len(admin_password)<14 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",admin_email):
        app.logger.error("ADMIN_EMAIL/ADMIN_PASSWORD are invalid; admin credentials were not changed")
        return
    admin=User.query.filter_by(role="admin").order_by(User.id.asc()).first()
    email_owner=User.query.filter_by(email=admin_email).first()
    if admin is None:
        if email_owner is not None:
            app.logger.error("Configured ADMIN_EMAIL belongs to a non-admin account; refusing automatic role escalation")
            return
        db.session.add(User(email=admin_email,password_hash=generate_password_hash(admin_password),role="admin",subscription_plan="admin"))
        db.session.commit()
        app.logger.info("Initial administrator provisioned from deployment environment")
        return
    if email_owner is not None and email_owner.id!=admin.id:
        app.logger.error("Configured ADMIN_EMAIL is already used by another account; admin email was not changed")
    else:
        admin.email=admin_email
    admin.password_hash=generate_password_hash(admin_password)
    admin.active=True
    admin.subscription_plan="admin"
    db.session.commit()
    app.logger.info("Existing administrator credentials synchronized from deployment environment")

with app.app_context():
    db.create_all()
    # Forward-only schema migration for existing production databases.
    trade_columns={column["name"] for column in inspect(db.engine).get_columns(Trade.__tablename__)}
    if "change_15m_pct" not in trade_columns:
        with db.engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {Trade.__tablename__} ADD COLUMN change_15m_pct FLOAT"))
    provision_admin_from_env()


def scheduled_market_scan():
    with app.app_context():
        expire_stale_trades()
        for market in MARKETS:
            try:
                result=run_market_scan(market,force=True)
                app.logger.info("scheduled scan completed: market=%s signals=%s universe=%s failures=%s",market,len(result.get("signals",[])),result.get("scan_universe"),result.get("analysis_failed",0))
            except Exception:
                db.session.rollback()
                app.logger.exception("scheduled scan failed: %s",market)

if os.environ.get("ENABLE_AUTO_SCAN","true").lower()=="true":
    scheduler=BackgroundScheduler(timezone="UTC")
    scheduler.add_job(scheduled_market_scan,"interval",minutes=15,id="market-scan-15m",max_instances=1,coalesce=True,next_run_time=utcnow()+timedelta(seconds=30))
    scheduler.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","8080")))