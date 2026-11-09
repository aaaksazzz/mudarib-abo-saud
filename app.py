import os, re, secrets, hashlib, hmac, time, json, math, shutil
from datetime import datetime, timedelta, timezone
from functools import wraps, lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import xml.etree.ElementTree as ET
import html
import market_adapters
import market_strategies
from flask import Flask, request, jsonify, send_from_directory, session, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, text, inspect, or_, event
from sqlalchemy.exc import IntegrityError
from apscheduler.schedulers.background import BackgroundScheduler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__, static_folder=None)
database_url=os.environ.get("DATABASE_URL")
if not database_url:
    data_dir=os.environ.get("DATA_DIR","").strip()
    if data_dir:
        os.makedirs(data_dir,exist_ok=True)
        durable_db=os.path.join(data_dir,"smart_trading_pro.db")
        legacy_db=os.path.join(app.instance_path,"smart_trading_pro.db")
        if os.path.isfile(legacy_db) and not os.path.exists(durable_db):
            shutil.copy2(legacy_db,durable_db)
            app.logger.info("Migrated existing SQLite database to DATA_DIR volume")
        database_url="sqlite:///"+durable_db
    else:
        database_url="sqlite:///smart_trading_pro.db"
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=database_url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
db=SQLAlchemy(app)

SQLITE_DATABASE=database_url.startswith("sqlite:")

def configure_sqlite_connection(dbapi_connection, connection_record):
    if not SQLITE_DATABASE:
        return
    cursor=dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

with app.app_context():
    event.listen(db.engine,"connect",configure_sqlite_connection)
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
    language=db.Column(db.String(8), nullable=False, default="ar", index=True)
    meta_title=db.Column(db.String(70), nullable=False, default="")
    meta_description=db.Column(db.String(170), nullable=False, default="")
    canonical_slug=db.Column(db.String(240), nullable=False, default="", index=True)
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

def valid_email(value):
    if not isinstance(value,str):
        return False
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value.strip()))

def valid_password(value,minimum=12):
    return (
        isinstance(value,str)
        and len(value)>=minimum
        and any(char.isalpha() for char in value)
        and any(char.isdigit() for char in value)
    )

def establish_user_session(user):
    # Rotate the session ID and CSRF token after every successful authentication.
    session.clear()
    session["uid"]=user.id
    session.permanent=True
    return csrf_token()
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
    return {"id":a.id,"kind":a.kind,"title":a.title,"slug":a.slug,"summary":a.summary,"body":a.body,
            "language":a.language or "ar","meta_title":a.meta_title or a.title,
            "meta_description":a.meta_description or a.summary,"canonical_slug":a.canonical_slug or a.slug,
            "created_at":iso(a.created_at)}
@app.get("/")
def home(): return send_from_directory(".", "index.html")
@app.get("/market/<market>")
def market_page_route(market):
    if market not in MARKETS: return json_error("السوق غير معروف",404)
    return send_from_directory(".", "index.html")

@app.get("/signal-lab")
def signal_lab_page():
    return send_from_directory(".", "signal-lab.html")

@app.get("/signal-lab.js")
def signal_lab_script():
    return send_from_directory(".", "signal-lab.js")

@app.get("/signal-lab.css")
def signal_lab_stylesheet():
    return send_from_directory(".", "signal-lab.css")

@app.get("/api/signal-lab/scan")
@limiter.limit("6 per minute")
def signal_lab_scan():
    """Paper-only 15m liquidity-sweep scanner across every eligible USD-M perpetual."""
    started=time.monotonic()
    try:
        # market_tickers already enforces active USD-M perpetuals and >= 1M USDT
        # 24h quote volume, sorted from highest liquidity to lowest.
        universe=market_tickers("futures")
        if not universe:
            return jsonify({
                "ok":True,"strategy":"LIQUIDITY_SWEEP_15M_V1","timeframe":"15m",
                "universe_checked":0,"universe_attempted":0,"universe_eligible":0,
                "analysis_failed":0,"insufficient_data":0,"signals":[],
                "checked_at":iso(utcnow()),"scan_duration_seconds":round(time.monotonic()-started,2)
            })

        def inspect_symbol(item):
            symbol=item["symbol"]
            try:
                rows=fetch_json(BINANCE_FUTURES+"/fapi/v1/klines",{
                    "symbol":symbol,"interval":"15m","limit":40
                })
                if not isinstance(rows,list) or len(rows)<23:
                    return {"status":"insufficient_data","signal":None}
                # Ignore the live candle. A sweep candle must precede a separate,
                # fully closed confirmation candle; neither can repaint intrabar.
                sweep=rows[-3]
                confirm=rows[-2]
                sop,shi,slo,scl=float(sweep[1]),float(sweep[2]),float(sweep[3]),float(sweep[4])
                op,hi,lo,cl=float(confirm[1]),float(confirm[2]),float(confirm[3]),float(confirm[4])
                quote_vol=float(confirm[7])
                prior=rows[-23:-3]
                if len(prior)!=20 or min(sop,shi,slo,scl,op,hi,lo,cl)<=0 or shi<=slo or hi<=lo:
                    return {"status":"insufficient_data","signal":None}
                prior_high=max(float(x[2]) for x in prior)
                prior_low=min(float(x[3]) for x in prior)
                avg_quote=sum(float(x[7]) for x in prior)/20
                if avg_quote<=0:
                    return {"status":"insufficient_data","signal":None}
                vol_ratio=quote_vol/avg_quote
                body_ratio=abs(cl-op)/(hi-lo)
                long_sweep=slo<prior_low and scl>prior_low
                short_sweep=shi>prior_high and scl<prior_high
                long_confirm=cl>op and cl>scl
                short_confirm=cl<op and cl<scl
                is_long=long_sweep and long_confirm
                is_short=short_sweep and short_confirm
                if vol_ratio<1.20 or body_ratio<0.45 or not (is_long or is_short):
                    return {"status":"checked","signal":None}
                side="BUY" if is_long else "SELL"
                entry=cl
                stop=slo if side=="BUY" else shi
                risk=abs(entry-stop)
                risk_pct=(risk/entry)*100
                if risk<=0 or risk_pct<0.05 or risk_pct>1.80:
                    return {"status":"checked","signal":None}
                sign=1 if side=="BUY" else -1
                score=min(99,round(55+min(vol_ratio-1.2,2.0)*9+min(body_ratio,1)*15-max(0,risk_pct-0.8)*8))
                signal={
                    "symbol":symbol,"side":side,"entry":round(entry,12),
                    "stop":round(stop,12),"tp1":round(entry+sign*risk*1.5,12),
                    "tp2":round(entry+sign*risk*2.0,12),"tp3":round(entry+sign*risk*3.0,12),
                    "risk_pct":round(risk_pct,3),"volume_ratio":round(vol_ratio,2),
                    "body_ratio":round(body_ratio,2),"score":score,
                    "quote_volume_24h":round(float(item["quote_volume"]),2),
                    "sweep_time":int(sweep[0]),"candle_time":int(confirm[0]),"timeframe":"15m",
                    "reason":"سحب سيولة أسفل قاع 20 شمعة، ثم شمعة تأكيد صاعدة بحجم تداول مؤكد" if side=="BUY" else "سحب سيولة أعلى قمة 20 شمعة، ثم شمعة تأكيد هابطة بحجم تداول مؤكد"
                }
                return {"status":"checked","signal":signal}
            except Exception:
                app.logger.warning("signal lab scan failed for %s",symbol,exc_info=True)
                return {"status":"failed","signal":None}

        found=[]
        checked=failed=insufficient=0
        # Scan the complete eligible universe with bounded concurrency to avoid
        # burst traffic against Binance and keep the single-worker service stable.
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures=[pool.submit(inspect_symbol,item) for item in universe]
            for future in as_completed(futures):
                result=future.result()
                if result["status"]=="checked":
                    checked+=1
                    if result["signal"]:
                        found.append(result["signal"])
                elif result["status"]=="insufficient_data":
                    insufficient+=1
                else:
                    failed+=1
        found.sort(key=lambda x:(x["score"],x["quote_volume_24h"]),reverse=True)
        return jsonify({
            "ok":True,"strategy":"LIQUIDITY_SWEEP_15M_V1","timeframe":"15m",
            "universe_checked":checked,"universe_attempted":len(universe),
            "universe_eligible":len(universe),"analysis_failed":failed,
            "insufficient_data":insufficient,"signals":found[:3],
            "signals_found_total":len(found),"checked_at":iso(utcnow()),
            "scan_duration_seconds":round(time.monotonic()-started,2),
            "rules":{"lookback":20,"volume_ratio_min":1.2,"body_ratio_min":0.45,"max_risk_pct":1.8}
        })
    except Exception:
        app.logger.exception("signal lab strategy scan failed")
        return json_error("تعذر فحص عقود Binance Futures حالياً؛ حاول بعد قليل",502)


@app.get("/api/signal-lab/klines")
@limiter.limit("60 per minute")
def signal_lab_klines():
    symbol=str(request.args.get("symbol","")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,26}USDT",symbol):
        return json_error("رمز العملة غير صحيح")
    try:
        start_ms=int(request.args.get("startTime",""))
    except (TypeError,ValueError):
        return json_error("وقت بداية التوصية غير صحيح")
    now_ms=int(utcnow().timestamp()*1000)
    if start_ms<now_ms-10*24*60*60*1000 or start_ms>now_ms:
        return json_error("المتابعة متاحة للتوصيات التي وصلتنا خلال آخر 10 أيام فقط")
    try:
        if symbol not in market_symbols("futures"):
            return json_error("العملة غير مدرجة في عقود Binance USD-M",404)
        rows=fetch_json(BINANCE_FUTURES+"/fapi/v1/klines",{
            "symbol":symbol,"interval":"15m","startTime":start_ms,"limit":1000
        })
        candles=[]
        for row in rows:
            try:
                opened=int(row[0]); high=float(row[2]); low=float(row[3]); closed=int(row[6])
                if not all(math.isfinite(value) for value in (high,low)) or high<=0 or low<=0 or high<low:
                    continue
                candles.append([opened,high,low,closed])
            except (TypeError,ValueError,IndexError,OverflowError):
                continue
        return jsonify({"ok":True,"symbol":symbol,"timeframe":"15m","candles":candles,"source":"Binance USD-M public klines","checked_at":iso(utcnow())})
    except Exception:
        app.logger.exception("signal lab candle fetch failed: %s",symbol)
        return json_error("تعذر جلب شموع Binance الآن؛ ستتم إعادة المحاولة لاحقاً",502)


@app.get("/blog/<slug>")
def public_article_page(slug):
    article=Article.query.filter_by(kind="blog",slug=slug,published=True).first()
    if not article:
        return json_error("المقال غير موجود",404)
    title=html.escape(article.meta_title or article.title)
    description=html.escape(article.meta_description or article.summary)
    body="".join("<p>"+html.escape(part.strip())+"</p>" for part in (article.body or "").split("\n\n") if part.strip())
    base=os.environ.get("PUBLIC_BASE_URL",request.url_root.rstrip("/")).rstrip("/")
    canonical=base+"/blog/"+article.slug
    locale=(article.language or "ar").replace("_","-")
    siblings=Article.query.filter_by(kind="blog",published=True,canonical_slug=article.canonical_slug or article.slug).all()
    alternates="".join('<link rel="alternate" hreflang="'+html.escape((x.language or "ar").replace("_","-"))+'" href="'+html.escape(base+"/blog/"+x.slug)+'">' for x in siblings)
    page=f"""<!doctype html><html lang="{html.escape(locale)}" dir="{'rtl' if locale.startswith('ar') else 'ltr'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><meta name="description" content="{description}"><link rel="canonical" href="{html.escape(canonical)}">{alternates}<meta property="og:type" content="article"><meta property="og:title" content="{title}"><meta property="og:description" content="{description}"><meta property="og:url" content="{html.escape(canonical)}"><meta name="robots" content="index,follow"><script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","headline":{json.dumps(article.title,ensure_ascii=False)},"description":{json.dumps(article.meta_description or article.summary,ensure_ascii=False)},"datePublished":{json.dumps(iso(article.created_at))},"mainEntityOfPage":{json.dumps(canonical)}}}</script></head><body><main><article><h1>{html.escape(article.title)}</h1><p>{description}</p>{body}</article></main></body></html>"""
    return page,200,{"Content-Type":"text/html; charset=utf-8","X-Robots-Tag":"index, follow"}

@app.get("/sitemap.xml")
def sitemap_xml():
    base=os.environ.get("PUBLIC_BASE_URL",request.url_root.rstrip("/")).rstrip("/")
    rows=Article.query.filter_by(kind="blog",published=True).order_by(Article.created_at.desc()).limit(5000).all()
    entries="".join("<url><loc>"+html.escape(base+"/blog/"+html.escape(x.slug))+"</loc><lastmod>"+(x.created_at.date().isoformat() if x.created_at else utcnow().date().isoformat())+"</lastmod></url>" for x in rows)
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+entries+"</urlset>"
    return xml,200,{"Content-Type":"application/xml; charset=utf-8"}
@app.get("/robots.txt")
def robots_txt():
    base=os.environ.get("PUBLIC_BASE_URL",request.url_root.rstrip("/")).rstrip("/")
    return "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: "+base+"/sitemap.xml\n",200,{"Content-Type":"text/plain; charset=utf-8"}

@app.get("/plans")
@app.get("/journal")
@app.get("/blog")
@app.get("/news")
@app.get("/login")
@app.get("/register")
@app.get("/account")
@app.get("/admin")
def standalone_section_route():
    return send_from_directory(".", "index.html")

@app.get("/styles.css")
def styles(): return send_from_directory(".", "styles.css")
@app.get("/platform.js")
def platform_script(): return send_from_directory(".", "platform.js")
@app.get("/pro-theme.css")
def pro_theme(): return send_from_directory(".", "pro-theme.css")
@app.get("/compat.css")
def compat_styles(): return send_from_directory(".", "compat.css")
@app.get("/api/strategy/status")
def strategy_status():
    diagnostic=market_strategies.diagnostic_self_test()
    return jsonify({"ok":diagnostic["ok"],"strategy": "SMART FLOW MTF QUANT + SMA200", **diagnostic}), 200 if diagnostic["ok"] else 500

@app.get("/health")
def health():
    return jsonify({"ok":True,"service":"SMART TRADING PRO","time":iso(utcnow())})

def persistent_database_configured(dialect,database_path,data_dir):
    """Accept PostgreSQL or SQLite physically located inside an absolute DATA_DIR."""
    if dialect=="postgresql":
        return True
    if dialect!="sqlite" or not data_dir or not database_path:
        return False
    if not os.path.isabs(data_dir) or not os.path.isabs(database_path):
        return False
    try:
        root=os.path.realpath(data_dir)
        target=os.path.realpath(database_path)
        return (
            os.path.isdir(root)
            and os.access(root,os.W_OK)
            and target!=root
            and os.path.commonpath((root,target))==root
        )
    except (OSError,ValueError):
        return False


def persistent_secret_configured(value):
    return bool(value and len(str(value).encode("utf-8"))>=32)


@app.get("/ready")
def readiness():
    checks={"database":False,"persistent_database":False,
            "persistent_secret":persistent_secret_configured(os.environ.get("SECRET_KEY")),
            "market_scheduler":False}
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"]=True
        checks["persistent_database"]=persistent_database_configured(
            db.engine.dialect.name,db.engine.url.database,
            os.environ.get("DATA_DIR","").strip()
        )
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
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return json_error("بيانات إنشاء الحساب غير صحيحة")
    email_value=data.get("email")
    email=email_value.strip().casefold() if isinstance(email_value,str) else ""
    password=data.get("password")
    if not valid_email(email):
        return json_error("البريد الإلكتروني غير صحيح")
    if not valid_password(password,12):
        return json_error("كلمة المرور يجب أن تكون 12 خانة على الأقل وتحتوي حروفاً وأرقاماً")
    if User.query.filter_by(email=email).first():
        return json_error("البريد مسجل مسبقاً",409)
    user=User(email=email,password_hash=generate_password_hash(password),role="user")
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return json_error("البريد مسجل مسبقاً",409)
    token=establish_user_session(user)
    return jsonify({"ok":True,"user":user_json(user),"csrf":token}),201

@app.post("/api/auth/login")
@limiter.limit("5 per minute")
def login():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return json_error("بيانات تسجيل الدخول غير صحيحة")
    identifier=data.get("email") or data.get("username") or ""
    login_id=identifier.strip().casefold() if isinstance(identifier,str) else ""
    password=data.get("password")
    if not login_id or not isinstance(password,str) or not password:
        return json_error("أدخل اسم المستخدم وكلمة المرور")
    user=User.query.filter_by(email=login_id).first()
    admin_username=os.environ.get("ADMIN_USERNAME","").strip().casefold()
    configured_admin_email=os.environ.get("ADMIN_EMAIL","").strip().casefold()
    admin_aliases={value for value in (admin_username, configured_admin_email.partition("@")[0] if "@" in configured_admin_email else "") if value}
    if not user and any(hmac.compare_digest(login_id,alias) for alias in admin_aliases):
        user=User.query.filter_by(role="admin").first()
    if not user or not check_password_hash(user.password_hash,password) or not user.active:
        return json_error("بيانات الدخول غير صحيحة",401)
    token=establish_user_session(user)
    return jsonify({"ok":True,"user":user_json(user),"csrf":token})

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

def saudi_market_is_open(now=None):
    """Saudi main-market continuous trading: Sun-Thu, 10:00-15:00 Asia/Riyadh."""
    local=(aware(now) or utcnow()).astimezone(timezone(timedelta(hours=3)))
    minute_of_day=local.hour*60+local.minute
    return local.weekday() not in (4,5) and 10*60 <= minute_of_day < 15*60


def read_scan_runtime(market):
    row=db.session.get(Setting,"scan-runtime:"+market)
    if not row:
        return {}
    try:
        value=json.loads(row.value)
        return value if isinstance(value,dict) else {}
    except (TypeError,ValueError):
        return {}


def scan_error_code(exc):
    if isinstance(exc,requests.Timeout):
        return "provider_timeout"
    status=getattr(getattr(exc,"response",None),"status_code",None)
    if status==429:
        return "provider_rate_limited"
    if status:
        return "provider_http_"+str(status)
    message=str(exc).lower()
    if "insufficient candle data" in message:
        return "insufficient_candle_data"
    if isinstance(exc,(requests.ConnectionError,ConnectionError)):
        return "provider_connection_error"
    if isinstance(exc,ValueError):
        return "provider_data_unavailable"
    return "scan_failed"


def scan_error_message(code):
    messages={
        "provider_timeout":"تأخر مزود بيانات السوق عن الرد في آخر فحص.",
        "provider_rate_limited":"مزود البيانات حدّ من الطلبات؛ يلزم تخفيف الضغط أو انتظار إعادة المحاولة.",
        "provider_connection_error":"تعذر الاتصال بمزود بيانات السوق في آخر فحص.",
        "insufficient_candle_data":"بيانات الشموع المكتملة لم تكفِ لاعتماد آخر دورة فحص.",
        "provider_data_unavailable":"مزود السوق أعاد بيانات غير مكتملة أو غير صالحة.",
    }
    if str(code or "").startswith("provider_http_"):
        return "مزود بيانات السوق أعاد خطأ HTTP في آخر فحص."
    return messages.get(code,"تعذر إكمال آخر دورة فحص مجدولة.")


@app.get("/api/system/status")
def system_status():
    admin=User.query.filter_by(role="admin").first()
    auto_scan_enabled=bool(globals().get("AUTO_SCAN_ENABLED",False))
    active_scheduler=globals().get("scheduler")
    runtime={}
    for market in MARKETS:
        item=read_scan_runtime(market)
        runtime[market]={
            "status":item.get("status","unknown"),
            "last_attempt_at":item.get("last_attempt_at"),
            "last_finished_at":item.get("last_finished_at"),
            "last_success_at":item.get("last_success_at"),
            "last_error_code":item.get("last_error_code"),
            "duration_seconds":item.get("duration_seconds"),
        }
    return jsonify({"ok":True,"admin_exists":bool(admin),"admin_login_configured":bool(os.environ.get("ADMIN_EMAIL","").strip() and os.environ.get("ADMIN_PASSWORD")),
                    "persistent_secret_configured":persistent_secret_configured(os.environ.get("SECRET_KEY")),
                    "database":"connected","time":iso(utcnow()),
                    "auto_scan_enabled":auto_scan_enabled,
                    "scheduler_running":bool(active_scheduler and active_scheduler.running),
                    "scanner_runtime":runtime})

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
    return {"configured":m in sources,"source":sources.get(m,"غير معروف"),"timeframe":"15m","timeframes":list(market_strategies.TIMEFRAMES),"requires_api_key":False,"access":"public_no_key"}
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
SNAPSHOT_CACHE_TTL=timedelta(minutes=15)


def build_market_snapshot(market,rows,updated_at=None,stale=False):
    up=sum(1 for item in rows if float(item.get("change_pct",0))>0)
    down=sum(1 for item in rows if float(item.get("change_pct",0))<0)
    stamp=iso(updated_at or utcnow())
    return {"ok":True,"ready":True,"market":market,
            "direction":"صاعد" if up>down else "هابط" if down>up else "متعادل",
            "side":"BUY" if up>down else "SELL" if down>up else "NEUTRAL",
            "direction_basis":"اتساع السوق حسب تغير السعر خلال 24 ساعة",
            "up":up,"down":down,"total":len(rows),
            "up_pct":round(up/len(rows)*100,1) if rows else 0,
            "down_pct":round(down/len(rows)*100,1) if rows else 0,
            "assets":rows[:40],"updated_at":stamp,"stale":bool(stale),
            "cache_ttl_minutes":15}


def read_market_snapshot(market):
    row=db.session.get(Setting,"market-snapshot:"+market)
    if not row:
        return None
    try:
        payload=json.loads(row.value)
        if not isinstance(payload,dict) or payload.get("market")!=market:
            return None
        updated=aware(datetime.fromisoformat(payload.get("updated_at","")))
        if updated is None:
            return None
        payload["stale"]=(utcnow()-updated)>SNAPSHOT_CACHE_TTL
        payload["cache_age_seconds"]=max(0,int((utcnow()-updated).total_seconds()))
        payload["cache_ttl_minutes"]=15
        payload["cache_status"]="stale" if payload["stale"] else "fresh"
        return payload
    except (TypeError,ValueError):
        app.logger.warning("Invalid persisted market snapshot: %s",market)
        return None


def persist_market_snapshot(market,rows,updated_at=None):
    if not rows:
        raise ValueError("Cannot persist an empty market snapshot")
    payload=build_market_snapshot(market,rows,updated_at)
    key="market-snapshot:"+market
    row=db.session.get(Setting,key)
    value=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    if row is None:
        db.session.add(Setting(key=key,value=value))
    else:
        row.value=value
    db.session.commit()
    return payload


@app.get("/api/markets/<market>/snapshot")
def snapshot(market):
    if market not in MARKETS: return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked: return blocked
    cached=read_market_snapshot(market)
    if cached and not cached["stale"]:
        return jsonify(cached)
    try:
        rows=market_tickers(market)
        fresh=persist_market_snapshot(market,rows)
        fresh["cache_status"]="refreshed"
        fresh["cache_age_seconds"]=0
        return jsonify(fresh)
    except Exception:
        app.logger.exception("snapshot refresh failed: %s",market)
        if cached:
            cached["stale"]=True
            cached["cache_status"]="stale_fallback"
            cached["warning"]="تعذر تحديث المصدر؛ يتم عرض آخر بيانات محفوظة."
            return jsonify(cached)
        return json_error("لا توجد بيانات محفوظة، وتعذر جلب بيانات السوق من المصدر حالياً",502)
def klines(market,symbol,interval,limit=120):
    if market not in ("spot","futures"):
        return market_adapters.klines(market,symbol,interval,limit)
    base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
    path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
    return fetch_json(base+path,{"symbol":symbol,"interval":interval,"limit":limit})
TIMEFRAMES=market_strategies.TIMEFRAMES

STRATEGY_FINGERPRINT=market_strategies.STRATEGY_FINGERPRINT
@app.get("/api/strategy-status")
def strategy_status_summary():
    current_active=Trade.query.filter(
        Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.expires_at>utcnow(),
        Trade.reason.like("SMART FLOW MTF QUANT:%")
    ).count()
    legacy_active=Trade.query.filter(
        Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.expires_at>utcnow(),
        Trade.reason.not_like("SMART FLOW MTF QUANT:%")
    ).count()
    diagnostics=market_strategies.diagnostic_self_test()
    return jsonify({
        "ok":diagnostics["ok"],
        "engine":"SMART FLOW MTF QUANT",
        "fingerprint":STRATEGY_FINGERPRINT,
        "markets":list(MARKETS),
        "timeframes":list(TIMEFRAMES),
        "current_active":current_active,
        "legacy_active":legacy_active,
        "legacy_removed":legacy_active==0,
        "manual_only":True,
        "diagnostics":diagnostics,
        "strategy_ready":diagnostics["ok"],
    })


def build_signal(market,item,timeframe):
    # Require a strong independent setup on the mapped signal timeframe first,
    # then require the trade timeframe analysis to confirm the same direction.
    symbol=item["symbol"]
    signal_timeframe=market_strategies.SIGNAL_TIMEFRAME[timeframe]
    signal_rows=klines(market,symbol,signal_timeframe,250)
    gate=market_strategies.analyze(market,symbol,signal_rows,timeframe=signal_timeframe)
    if not gate:
        return None
    rows=klines(market,symbol,timeframe,250)
    flow=None
    if item.get("include_microstructure") and market in ("spot","futures"):
        flow=market_adapters.microstructure(market,symbol)
    setup=market_strategies.analyze(market,symbol,rows,timeframe=timeframe,microstructure=flow)
    if not setup or setup.get("side") != gate.get("side"):
        return None
    setup["signal_timeframe"]=signal_timeframe
    setup["reason"]="SMART FLOW MTF QUANT: strong "+gate["side"]+" + SMA200 on "+signal_timeframe+"; same-side confirmation on "+timeframe+"; "+setup.get("reason","")
    setup.update({"market":market,"symbol":symbol,"quote_volume":item.get("quote_volume",0),
                  "status":"active","timeframe":timeframe})
    return setup

def filter_fresh_signals(signals, universe, now=None):
    """Reject stale/moved setups and anchor execution levels to the live quote."""
    now=now or utcnow()
    now_ms=int(now.timestamp()*1000)
    live_prices={}
    for item in universe:
        try:
            price=float(item.get("price") or 0)
            if item.get("symbol") and math.isfinite(price) and price>0:
                live_prices[item["symbol"]]=price
        except (TypeError,ValueError):
            continue
    accepted=[]
    rejected_old=0
    rejected_moved=0
    for signal in signals:
        try:
            candle_time=int(signal.get("signal_candle_time") or 0)
            candle_entry=float(signal.get("entry") or 0)
            stop=float(signal.get("stop") or 0)
            old_tp1=float(signal.get("tp1") or 0)
            current=live_prices.get(signal.get("symbol"))
            side=signal.get("side")
            direction=1.0 if side=="BUY" else -1.0
            interval_ms=market_strategies.INTERVAL_MS.get(signal.get("timeframe"))
            if not interval_ms or not candle_time or now_ms-(candle_time+interval_ms)>interval_ms*1.5+120000:
                rejected_old+=1
                continue
            if current is None or min(candle_entry,stop,old_tp1)<=0 or side not in ("BUY","SELL"):
                rejected_moved+=1
                continue
            old_target_distance=abs(old_tp1-candle_entry)
            old_risk=abs(candle_entry-stop)
            favorable_move=(current-candle_entry)*direction
            # A setup is invalid if price has already consumed most of its target,
            # moved too far from the signal candle, or crossed its structural stop.
            if old_target_distance<=0 or old_risk<=0 or favorable_move>=old_target_distance*0.80:
                rejected_moved+=1
                continue
            if abs(current-candle_entry)>max(old_risk*0.35,old_target_distance*0.50):
                rejected_moved+=1
                continue
            if (side=="BUY" and current<=stop) or (side=="SELL" and current>=stop):
                rejected_moved+=1
                continue
            live_risk=abs(current-stop)
            atr=float(signal.get("atr") or 0)
            if not math.isfinite(live_risk) or live_risk<=0 or not math.isfinite(atr) or atr<=0:
                rejected_moved+=1
                continue
            if live_risk>atr*2.5 or live_risk<atr*0.20:
                rejected_moved+=1
                continue
            # The published entry is the actual quote at approval time, not the
            # previous candle close. Rebuild all R-multiple targets from that entry.
            if live_risk > current * 0.0125:
                rejected_moved+=1
                continue
            targets=market_strategies.target_prices(current,side)
            if not targets:
                rejected_moved+=1
                continue
            signal["entry"]=current
            signal["tp1"],signal["tp2"],signal["tp3"]=targets
            signal["risk_distance"]=live_risk
            signal["entry_price_source"]="live_market_quote"
            accepted.append(signal)
        except (TypeError,ValueError,OverflowError):
            rejected_moved+=1
    return accepted,{"rejected_stale_candle":rejected_old,"rejected_late_price":rejected_moved}


def expire_stale_trades(market=None):
    now=utcnow()
    query=Trade.query.filter(Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at<=now)
    if market:
        query=query.filter(Trade.market==market)
    changed=query.update({"status":"expired"},synchronize_session=False)
    if changed:
        db.session.commit()
    return changed

def evaluate_trade_outcome_from_bars(trade,rows,now_ms=None):
    """Replay completed OHLC bars using the trade's own timeframe."""
    now_ms=now_ms if now_ms is not None else int(utcnow().timestamp()*1000)
    interval_ms=market_strategies.INTERVAL_MS.get(trade.timeframe)
    if not interval_ms:
        return trade.status,0
    try:
        created=aware(trade.created_at)
        created_ms=int(created.timestamp()*1000)
        first_bar=((created_ms+interval_ms-1)//interval_ms)*interval_ms
    except (AttributeError,TypeError,ValueError,OverflowError):
        return trade.status,0
    status=trade.status
    completed=0
    parsed=[]
    for row in rows or []:
        try:
            if not isinstance(row,(list,tuple)) or len(row)<6:
                continue
            stamp=int(float(row[0]))
            high=float(row[2])
            low=float(row[3])
            if not all(math.isfinite(value) for value in (high,low)) or high<=0 or low<=0 or high<low:
                continue
            if stamp<first_bar or stamp+interval_ms>now_ms:
                continue
            parsed.append((stamp,high,low))
        except (TypeError,ValueError,OverflowError):
            continue
    for _,high,low in sorted(parsed):
        completed+=1
        if trade.side=="BUY":
            stop_hit=low<=trade.stop
            tp1_hit=high>=trade.tp1
            tp2_hit=high>=trade.tp2
            tp3_hit=high>=trade.tp3
        else:
            stop_hit=high>=trade.stop
            tp1_hit=low<=trade.tp1
            tp2_hit=low<=trade.tp2
            tp3_hit=low<=trade.tp3
        # OHLC cannot reveal which extreme came first inside one candle.
        # Stop-first is the conservative, non-inflated outcome.
        if stop_hit:
            status="stopped_after_tp2" if status=="tp2_hit" else "stopped_after_tp1" if status=="tp1_hit" else "stopped"
            break
        if tp3_hit:
            status="tp3_hit"
            break
        if tp2_hit:
            status="tp2_hit"
        elif tp1_hit and status=="active":
            status="tp1_hit"
    return status,completed


def update_trade_outcomes(market,tickers):
    prices={}
    for item in tickers:
        try:
            symbol=item.get("symbol")
            price=float(item.get("price") or 0)
            if symbol and math.isfinite(price) and price>0:
                prices[symbol]=price
        except (TypeError,ValueError,OverflowError):
            continue
    trades=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES)).all()
    if not trades:
        return 0
    symbol_frames=sorted({(trade.symbol,trade.timeframe) for trade in trades if trade.symbol})
    def fetch_trade_bars(pair):
        symbol,frame=pair
        try:
            return pair,klines(market,symbol,frame,100)
        except Exception:
            return pair,[]
    with ThreadPoolExecutor(max_workers=min(8,max(1,len(symbol_frames)))) as pool:
        bars_by_symbol_frame=dict(pool.map(fetch_trade_bars,symbol_frames))
    changed=0
    now_ms=int(utcnow().timestamp()*1000)
    for trade in trades:
        price=prices.get(trade.symbol)
        if price is not None and trade.entry>0:
            direction=1 if trade.side=="BUY" else -1
            trade.result_pct=round((price/trade.entry-1)*direction*100,4)
        previous=trade.status
        rows=bars_by_symbol_frame.get((trade.symbol,trade.timeframe)) or []
        status,completed=evaluate_trade_outcome_from_bars(trade,rows,now_ms)
        if completed==0 and price is not None and trade.entry>0:
            # Provider fallback: preserve live-price tracking when no completed
            # post-entry candle is available, without fabricating OHLC history.
            stop_hit=price<=trade.stop if trade.side=="BUY" else price>=trade.stop
            tp1_hit=price>=trade.tp1 if trade.side=="BUY" else price<=trade.tp1
            tp2_hit=price>=trade.tp2 if trade.side=="BUY" else price<=trade.tp2
            tp3_hit=price>=trade.tp3 if trade.side=="BUY" else price<=trade.tp3
            if stop_hit:
                status="stopped_after_tp2" if previous=="tp2_hit" else "stopped_after_tp1" if previous=="tp1_hit" else "stopped"
            elif tp3_hit:
                status="tp3_hit"
            elif tp2_hit:
                status="tp2_hit"
            elif tp1_hit and previous=="active":
                status="tp1_hit"
        trade.status=status
        if trade.status!=previous:
            changed+=1
    db.session.commit()
    return changed

def select_scan_candidates(universe,offset=0,batch_size=80):
    """Rotate through the full eligible universe without changing signal rules."""
    # Prioritise fast-moving assets first (largest absolute 24h move), then liquidity.
    # Cursor rotation continues into slower assets on subsequent 15m scan cycles.
    ranked=sorted(universe,key=lambda x:(abs(float(x.get("change_pct") or 0)),float(x.get("quote_volume") or 0)),reverse=True)
    if not ranked:
        return [],0,0
    start=int(offset or 0)%len(ranked)
    # Always fill the requested batch, including when the cursor reaches the
    # tail of the ranked universe. The old slice returned only the remainder
    # (for example 27 of 80) and wasted most of that scan cycle.
    size=min(max(1,int(batch_size)),len(ranked))
    selected=[ranked[(start+i)%len(ranked)] for i in range(size)]
    next_offset=(start+size)%len(ranked)
    return selected,next_offset,start


def timeframe_bucket(frame,now):
    current=aware(now).astimezone(timezone.utc)
    if frame=="15m":
        return int(current.timestamp()//900)
    if frame=="1h":
        return int(current.timestamp()//3600)
    if frame=="4h":
        return int(current.timestamp()//14400)
    if frame=="1d":
        return current.date().toordinal()
    if frame=="1w":
        return (current.date()-datetime(1970,1,5).date()).days//7
    if frame=="1M":
        return current.year*12+current.month
    raise ValueError("Unsupported timeframe "+str(frame))


def market_scan_timeframes(market):
    """Expose the same independently-calculated frames for every supported market."""
    return market_strategies.TIMEFRAMES


def run_market_scan(market,force=False):
    if market not in MARKETS:
        raise ValueError("Unknown market "+str(market))
    now=utcnow()
    # Retire all still-open signals produced by the replaced single-timeframe engine.
    Trade.query.filter(
        Trade.market==market, Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.expires_at>now, Trade.reason.like("SMART FLOW QUANT:%")
    ).update({"status":"superseded"}, synchronize_session=False)
    db.session.commit()
    expire_stale_trades(market)
    scan_key="scan:"+market
    scan_row=db.session.get(Setting,scan_key)
    if scan_row and not force:
        try:
            last=aware(datetime.fromisoformat(scan_row.value))
            all_frames_current=all(
                db.session.get(Setting,f"scan-frame:smart-flow-quant:{market}:{frame}") is not None
                and db.session.get(Setting,f"scan-frame:smart-flow-quant:{market}:{frame}").value==str(timeframe_bucket(frame,now))
                for frame in market_scan_timeframes(market)
            )
            if last>now-timedelta(minutes=15) and all_frames_current and Trade.query.filter(
                Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.timeframe=="15m",
                Trade.expires_at>now,Trade.reason.like("SMART FLOW MTF QUANT:%")
            ).count():
                active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.timeframe.in_(TIMEFRAMES),Trade.expires_at>now,Trade.reason.like("SMART FLOW MTF QUANT:%")).order_by(Trade.score.desc()).limit(18).all()
                meta_row=db.session.get(Setting,"scan-meta:"+market)
                try:
                    meta=json.loads(meta_row.value) if meta_row else {}
                except (ValueError,TypeError):
                    meta={}
                return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":scan_row.value,"cached":True,**meta}
        except (ValueError,TypeError):
            app.logger.warning("Invalid scan timestamp for %s; forcing a fresh scan",market)
    frames_to_scan=[]
    frame_buckets={}
    scan_frames=market_scan_timeframes(market)
    for frame in scan_frames:
        bucket=timeframe_bucket(frame,now)
        frame_buckets[frame]=bucket
        frame_row=db.session.get(Setting,f"scan-frame:smart-flow-quant:{market}:{frame}")
        if frame_row is None or frame_row.value!=str(bucket):
            frames_to_scan.append(frame)
    if not frames_to_scan:
        frames_to_scan=["15m"]
    universe=market_tickers(market)
    if not universe:
        raise RuntimeError("Market provider returned an empty eligible universe")
    # Persist the real market breadth before candle analysis; a candle failure
    # must not discard a usable overview snapshot.
    persist_market_snapshot(market,universe,now)
    market_up=sum(1 for item in universe if item.get("change_pct",0)>0)
    market_down=sum(1 for item in universe if item.get("change_pct",0)<0)
    market_bias="BUY" if market_up>market_down else "SELL" if market_down>market_up else None
    # Update outcomes first, then keep the previous signal batch visible until
    # this scan has successfully analysed enough fresh candles.
    update_trade_outcomes(market,universe)
    # Scan a larger rotating slice; small markets are fully scanned every cycle.
    # This prevents the same top-20 symbols from monopolising every 15m scan.
    cursor_key="scan-cursor:"+market
    cursor_row=db.session.get(Setting,cursor_key)
    try:
        cursor=int(cursor_row.value) if cursor_row else 0
    except (TypeError,ValueError):
        cursor=0
    candidates,next_cursor,scan_offset=select_scan_candidates(universe,cursor,80)
    for index,item in enumerate(candidates):
        item["include_microstructure"]=(market in ("spot","futures") and index<12)
    found=[]
    completed=0
    failed=0
    with ThreadPoolExecutor(max_workers=8) as pool:
        frame_stats={frame:{"completed":0,"failed":0,"matches":0} for frame in frames_to_scan}
        futures={pool.submit(build_signal,market,item,frame):(item,frame) for item in candidates for frame in frames_to_scan}
        for future in as_completed(futures):
            _,frame=futures[future]
            try:
                signal=future.result()
                completed+=1
                frame_stats[frame]["completed"]+=1
                if signal:
                    found.append(signal)
                    frame_stats[frame]["matches"]+=1
            except Exception as exc:
                failed+=1
                frame_stats[frame]["failed"]+=1
                # Some Saudi tickers are not covered by Yahoo's candle endpoint.
                # Treat an individual unavailable symbol/frame as a skipped sample,
                # not as a traceback storm that obscures the market-level result.
                if market=="saudi":
                    app.logger.warning(
                        "candle sample skipped: market=%s error=%s",
                        market, type(exc).__name__
                    )
                else:
                    app.logger.exception("multi-timeframe signal analysis failed for %s",market)
    # Validate completeness separately for every timeframe. A healthy 15m
    # feed must never hide a broken daily/monthly candle provider.
    required_ratio=0.35 if market=="saudi" else 0.80
    incomplete_frames={}
    for frame in frames_to_scan:
        required=min(len(candidates),max(8 if market=="saudi" else 1,
                                       math.ceil(len(candidates)*required_ratio)))
        actual=frame_stats[frame]["completed"]
        if actual<required:
            incomplete_frames[frame]=(actual,required)
    if incomplete_frames:
        details=", ".join(f"{frame}={actual}/{required}" for frame,(actual,required) in incomplete_frames.items())
        raise RuntimeError("Insufficient candle data by timeframe: "+details)
    if failed:
        app.logger.warning(
            "market scan partial data: market=%s completed=%s failed=%s requested=%s",
            market,completed,failed,len(futures)
        )
    strategy_matches=len(found)
    raw_found=found
    found=[]
    freshness_by_frame={}
    for frame in frames_to_scan:
        frame_found,frame_freshness=filter_fresh_signals(
            [signal for signal in raw_found if signal.get("timeframe")==frame],universe,utcnow()
        )
        found.extend(frame_found)
        freshness_by_frame[frame]=frame_freshness
    freshness={key:sum(value[key] for value in freshness_by_frame.values())
               for key in ("rejected_stale_candle","rejected_late_price")}
    fresh_matches=len(found)
    # Market breadth is informational only. Each symbol is gated by its own
    # same-timeframe SMA200 and directional candle/flow confirmations.
    direction_rejected=0
    app.logger.info("signal validation: market=%s universe=%s scanned=%s completed=%s failed=%s strategy=%s fresh=%s accepted=%s stale=%s late=%s market_breadth=%s",
                    market,len(universe),len(candidates),completed,failed,strategy_matches,fresh_matches,len(found),
                    freshness["rejected_stale_candle"],freshness["rejected_late_price"],market_bias)
    # Keep the same 15m candle from being republished every scheduler cycle.
    existing_rows=Trade.query.filter(
        Trade.market==market,
        Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.reason.like("SMART FLOW MTF QUANT:%"),
        Trade.timeframe.in_(frames_to_scan),
    ).all()
    existing_by_key={}
    for trade in existing_rows:
        marker=trade.reason.rsplit("bar_ts=",1)[-1] if "bar_ts=" in trade.reason else ""
        if marker:
            existing_by_key[(trade.symbol,trade.timeframe,marker)]=trade
    retained_ids=set()
    new_signals=[]
    for frame in frames_to_scan:
        frame_signals=sorted(
            (x for x in found if x["timeframe"]==frame),
            key=lambda x:(x["score"],x.get("quote_volume",0)),
            reverse=True,
        )
        for signal in frame_signals[:3]:
            marker=str(signal["signal_candle_time"])
            key=(signal["symbol"],frame,marker)
            setting_key=f"signal-candle:smart-flow-quant:{market}:{signal['symbol']}:{frame}"
            candle_row=db.session.get(Setting,setting_key)
            previous=existing_by_key.get(key)
            if candle_row and candle_row.value==marker:
                if previous and aware(previous.expires_at)>now:
                    retained_ids.add(previous.id)
                continue
            if candle_row is None:
                db.session.add(Setting(key=setting_key,value=marker))
            else:
                candle_row.value=marker
            signal["reason"]=signal["reason"]+" | bar_ts="+marker
            new_signals.append(signal)
    # Retire legacy strategy trades only; preserve valid trades from other frames.
    Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.reason.not_like("SMART FLOW MTF QUANT:%")).update({"status":"superseded"},synchronize_session=False)
    active_query=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.timeframe.in_(frames_to_scan),Trade.reason.like("SMART FLOW MTF QUANT:%"))
    if retained_ids:
        active_query=active_query.filter(~Trade.id.in_(retained_ids))
    active_query.update({"status":"superseded"},synchronize_session=False)
    for signal in new_signals:
        frame=signal["timeframe"]
        db.session.add(Trade(market=market,symbol=signal["symbol"],side=signal["side"],entry=signal["entry"],stop=signal["stop"],tp1=signal["tp1"],tp2=signal["tp2"],tp3=signal["tp3"],score=signal["score"],change_15m_pct=signal["change_pct"],timeframe=frame,reason=signal["reason"],expires_at=now+timedelta(hours=24)))
    if not scan_row:
        scan_row=Setting(key=scan_key,value=iso(now)); db.session.add(scan_row)
    else:
        scan_row.value=iso(now)
    meta_key="scan-meta:"+market
    meta_row=db.session.get(Setting,meta_key)
    meta_value=json.dumps({"scan_universe":len(universe),"scan_batch_size":len(candidates),"scan_offset":scan_offset,
                            "analysis_completed":completed,"analysis_failed":failed,"strategy_matches":strategy_matches,
                            "fresh_matches":fresh_matches,"direction_rejected":direction_rejected,
                            "accepted_signals":len(found),"rejected_stale_candle":freshness["rejected_stale_candle"],
                            "rejected_late_price":freshness["rejected_late_price"],
                            "market_bias":market_bias,"timeframes":list(TIMEFRAMES),"scanned_timeframes":frames_to_scan},ensure_ascii=False)
    if not meta_row:
        db.session.add(Setting(key=meta_key,value=meta_value))
    else:
        meta_row.value=meta_value
    if cursor_row is None:
        db.session.add(Setting(key=cursor_key,value=str(next_cursor)))
    else:
        cursor_row.value=str(next_cursor)
    for frame in frames_to_scan:
        frame_key=f"scan-frame:smart-flow-quant:{market}:{frame}"
        frame_row=db.session.get(Setting,frame_key)
        bucket_value=str(frame_buckets[frame])
        if frame_row is None:
            db.session.add(Setting(key=frame_key,value=bucket_value))
        else:
            frame_row.value=bucket_value
        frame_scan_key=f"scan:{market}:{frame}"
        frame_scan_row=db.session.get(Setting,frame_scan_key)
        if frame_scan_row is None:
            db.session.add(Setting(key=frame_scan_key,value=iso(now)))
        else:
            frame_scan_row.value=iso(now)
        frame_meta_key=f"scan-meta:{market}:{frame}"
        frame_meta_row=db.session.get(Setting,frame_meta_key)
        frame_signals=[x for x in found if x.get("timeframe")==frame]
        frame_meta=json.dumps({
            "scan_universe":len(universe),"scan_batch_size":len(candidates),"scan_offset":scan_offset,
            "analysis_completed":frame_stats[frame]["completed"],
            "analysis_failed":frame_stats[frame]["failed"],
            "strategy_matches":frame_stats[frame]["matches"],
            "fresh_matches":len(frame_signals),
            "direction_rejected":0,"accepted_signals":len(frame_signals),
            "rejected_stale_candle":freshness_by_frame[frame]["rejected_stale_candle"],
            "rejected_late_price":freshness_by_frame[frame]["rejected_late_price"],
            "market_bias":market_bias,"timeframes":list(TIMEFRAMES),"scanned_timeframes":[frame]
        },ensure_ascii=False)
        if frame_meta_row is None:
            db.session.add(Setting(key=frame_meta_key,value=frame_meta))
        else:
            frame_meta_row.value=frame_meta
    db.session.commit()
    active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.timeframe.in_(TIMEFRAMES),Trade.expires_at>now,Trade.reason.like("SMART FLOW MTF QUANT:%")).order_by(Trade.score.desc()).limit(18).all()
    return {"ok":True,"market":market,"signals":[trade_json(x) for x in active],"updated_at":iso(now),
            "scan_universe":len(universe),"scan_batch_size":len(candidates),"scan_offset":scan_offset,
            "analysis_completed":completed,"analysis_failed":failed,"strategy_matches":strategy_matches,
            "fresh_matches":fresh_matches,"direction_rejected":direction_rejected,"accepted_signals":len(found),
            "rejected_stale_candle":freshness["rejected_stale_candle"],
            "rejected_late_price":freshness["rejected_late_price"],
            "market_bias":market_bias,"timeframes":list(TIMEFRAMES),"scanned_timeframes":frames_to_scan}
@app.get("/api/markets/<market>/signals")
def signals(market):
    if market not in MARKETS:
        return json_error("السوق غير معروف",404)
    blocked=gate_section(market)
    if blocked:
        return blocked
    try:
        # Keep this endpoint read-only. The single scheduler expires trades;
        # writing from page requests races with scheduled scans on SQLite.
        timeframe=request.args.get("timeframe","15m")
        if timeframe not in TIMEFRAMES:
            return json_error("الفريم غير مدعوم",400)
        row=db.session.get(Setting,f"scan:{market}:{timeframe}")
        meta_row=db.session.get(Setting,f"scan-meta:{market}:{timeframe}")
        # Backward-compatible read of the last 15m scan during rollout.
        if row is None and timeframe=="15m":
            row=db.session.get(Setting,"scan:"+market)
        if meta_row is None and timeframe=="15m":
            meta_row=db.session.get(Setting,"scan-meta:"+market)
        active=Trade.query.filter(Trade.market==market,Trade.status.in_(OPEN_TRADE_STATUSES),Trade.expires_at>utcnow(),Trade.reason.like("SMART FLOW MTF QUANT:%"),Trade.timeframe==timeframe).order_by(Trade.score.desc()).limit(3).all()
        updated=row.value if row else None
        try:
            meta=json.loads(meta_row.value) if meta_row else {}
        except (ValueError,TypeError):
            meta={}
        stale=True
        if updated:
            try:
                max_age_ms=market_strategies.INTERVAL_MS[timeframe]*1.5+120_000
                stale=aware(datetime.fromisoformat(updated))<utcnow()-timedelta(milliseconds=max_age_ms)
            except (ValueError,TypeError):
                stale=True
        # Never present an old batch or a closed-session quote as a live entry.
        market_closed=(market=="saudi" and not saudi_market_is_open())
        runtime=read_scan_runtime(market)
        scan_error=None
        if not market_closed:
            active_scheduler=globals().get("scheduler")
            if not globals().get("AUTO_SCAN_ENABLED",False):
                scan_error="الفحص التلقائي غير مفعّل على الخادم؛ يلزم تفعيل ENABLE_AUTO_SCAN."
            elif not active_scheduler or not active_scheduler.running:
                scan_error="المجدول الخلفي غير نشط داخل الخدمة."
            elif stale and runtime.get("status")=="error":
                scan_error=scan_error_message(runtime.get("last_error_code"))
        return jsonify({"ok":True,"market":market,"timeframe":timeframe,"timeframes":list(TIMEFRAMES),
                        "signals":[trade_json(x) for x in active] if not stale and not market_closed else [],
                        "updated_at":updated,"cached":True,"stale":stale,"scan_ready":bool(updated),
                        **meta,"timeframes":list(TIMEFRAMES),
                        "scan_error":scan_error,"market_closed":market_closed,
                        "engine":"SMART FLOW MTF QUANT","fingerprint":STRATEGY_FINGERPRINT})
    except Exception:
        app.logger.exception("signal retrieval failed")
        return json_error("تعذر قراءة نتائج الفحص المحفوظة حالياً",503)
def trade_json(t):
    # Public trade payload contains execution levels and status only; never disclose strategy rationale.
    return {"id":t.id,"market":t.market,"symbol":t.symbol,"side":t.side,"entry":t.entry,"stop":t.stop,"tp1":t.tp1,"tp2":t.tp2,"tp3":t.tp3,"score":t.score,"change_15m_pct":t.change_15m_pct,"change_pct":t.change_15m_pct,"timeframe":t.timeframe,"status":t.status,"result_pct":t.result_pct,"created_at":iso(t.created_at),"expires_at":iso(t.expires_at)}
@app.get("/api/trades")
def trade_history():
    # The journal is an outcome report, not a raw database dump:
    # replaced/expired signals are excluded from performance statistics.
    expire_stale_trades()
    open_rows=Trade.query.filter(
        Trade.status.in_(OPEN_TRADE_STATUSES),
        Trade.expires_at>utcnow()
    ).order_by(Trade.created_at.desc()).all()
    completed_all=Trade.query.filter(
        Trade.status.in_(("tp3_hit","stopped","stopped_after_tp1","stopped_after_tp2"))
    ).order_by(Trade.created_at.desc()).all()
    completed_rows=completed_all[:200]

    # Keep only the newest live setup for each instrument/timeframe.
    unique_open=[]
    seen=set()
    for trade in open_rows:
        key=(trade.market,trade.symbol,trade.timeframe)
        if key in seen:
            continue
        seen.add(key)
        unique_open.append(trade)

    wins=sum(1 for trade in completed_all if trade.status in ("tp3_hit","stopped_after_tp1","stopped_after_tp2"))
    losses=sum(1 for trade in completed_all if trade.status=="stopped")
    completed=wins+losses
    buys=sum(1 for trade in unique_open if trade.side=="BUY")
    sells=sum(1 for trade in unique_open if trade.side=="SELL")
    summary={
        "active":len(unique_open),"buy_active":buys,"sell_active":sells,
        "completed":completed,"wins":wins,"losses":losses,
        "win_rate":round(wins/completed*100,1) if completed else None,
        "tp3":sum(1 for trade in completed_all if trade.status=="tp3_hit"),
        "stopped_after_target":sum(1 for trade in completed_all if trade.status in ("stopped_after_tp1","stopped_after_tp2")),
    }
    return jsonify({
        "ok":True,"summary":summary,
        "active_trades":[trade_json(x) for x in unique_open[:100]],
        "completed_trades":[trade_json(x) for x in completed_rows],
        "trades":[trade_json(x) for x in (unique_open[:100]+completed_rows)],
    })
@app.get("/api/strategies")
def strategies():
    # Strategy documentation is private operational logic, not a customer-facing endpoint.
    return json_error("غير متاح",404)
def classify_news_headline(title):
    """Conservative headline-only sentiment; never presents a headline as a verified trade signal."""
    text_value=str(title or "").casefold()
    negative=("هبوط","انخفاض","تراجع","خسائر","أزمة","تحذير","انكماش","تضخم","رفع الفائدة","تشديد","بيع مكثف","اختراق أمني","إفلاس","تصفية","bearish","drop","falls","falling","decline","losses","crash","crisis","warning","recession","inflation","rate hike","selloff","hack","bankruptcy","liquidation","caída","bajada","pérdidas","crise","rückgang","verluste","einbruch","penurunan","kerugian","düşüş","kayıp","baisse","pertes","गिरावट","नुकसान")
    positive=("ارتفاع","صعود","مكاسب","نمو","انتعاش","تخفيف","خفض الفائدة","شراء قوي","bullish","surge","rally","gains","growth","rebound","recovery","rate cut","inflows","breakout","subida","ganancias","hausse","gewinne","anstieg","kenaikan","pertumbuhan","yükseliş","artış","hausse","croissance","वृद्धि","लाभ")
    neg=sum(1 for word in negative if word in text_value)
    pos=sum(1 for word in positive if word in text_value)
    if neg > pos:
        sentiment,direction,label="negative","SELL","سلبي · ضغط بيعي"
    elif pos > neg:
        sentiment,direction,label="positive","BUY","إيجابي · ضغط شرائي"
    else:
        sentiment,direction,label="neutral","NEUTRAL","محايد · لا اتجاه واضح"
    return {"sentiment":sentiment,"direction":direction,"sentiment_label":label,
            "sentiment_basis":"headline_only","sentiment_confidence":"low" if sentiment=="neutral" else "limited"}

@lru_cache(maxsize=8)
def _cached_google_news(language, bucket):
    queries={"ar":"أسواق المال تداول العملات الرقمية الأسهم الفوركس الذهب","en":"financial markets trading cryptocurrency stocks forex gold",
             "es":"mercados financieros trading criptomonedas acciones forex oro","de":"Finanzmärkte Handel Kryptowährungen Aktien Forex Gold",
             "id":"pasar keuangan trading kripto saham forex emas","pt":"mercados financeiros trading criptomoedas ações forex ouro",
             "tr":"finans piyasaları kripto para hisse senedi forex altın","fr":"marchés financiers trading cryptomonnaies actions forex or",
             "hi":"वित्तीय बाजार ट्रेडिंग क्रिप्टो शेयर फॉरेक्स सोना"}
    query=queries.get(language,queries["en"])
    locale={"ar":("ar","SA"),"en":("en","US"),"es":("es","ES"),"de":("de","DE"),"id":("id","ID"),"pt":("pt-BR","BR"),"tr":("tr","TR"),"fr":("fr","FR"),"hi":("hi","IN")}.get(language,("en","US"))
    from urllib.parse import quote
    url="https://news.google.com/rss/search?q="+quote(query)+"&hl="+locale[0]+"&gl="+locale[1]+"&ceid="+locale[1]+":"+locale[0]
    response=requests.get(url,headers={"User-Agent":"SMART-TRADING-PRO/1.0 news-reader"},timeout=8)
    response.raise_for_status()
    root=ET.fromstring(response.content)
    items=[]
    for item in root.findall("./channel/item")[:30]:
        title=(item.findtext("title") or "").strip()
        link=(item.findtext("link") or "").strip()
        source=item.find("source")
        source_name=(source.text or "").strip() if source is not None else ""
        published=(item.findtext("pubDate") or "").strip()
        if title and link.startswith("https://"):
            classified=classify_news_headline(title)
            items.append({"title":title,"source":source_name,"published_at":published,**classified})
    return items

@app.get("/api/news")
def live_news():
    blocked=gate_section("news")
    if blocked: return blocked
    language=(request.args.get("lang","ar").strip().lower() or "ar")
    if language not in ("ar","en","es","de","id","pt","tr","fr","hi"):
        language="en"
    try:
        source_items=_cached_google_news(language,int(time.time()//300))
        items=[]
        for item in source_items:
            title=str(item.get("title") or "").strip()
            if not title:
                continue
            source=classify_news_headline(title)
            items.append({"title":title[:500],"source":str(item.get("source") or "")[:120],
                          "published_at":str(item.get("published_at") or "")[:100],**source})
        return jsonify({"ok":True,"provider":"Google News RSS","language":language,"items":items,"updated_at":iso(utcnow()),"delivery":"in_app_only"})
    except Exception:
        app.logger.exception("live news feed failed")
        return jsonify({"ok":False,"provider":"Google News RSS","language":language,"items":[],"error":"تعذر جلب الأخبار الحية من المصدر حالياً","updated_at":iso(utcnow())}),502

@app.get("/api/content/<kind>")
def content_list(kind):
    if kind not in ("blog","news"): return json_error("نوع المحتوى غير معروف",404)
    if not section_enabled(kind): return json_error("القسم متوقف",404)
    language=(request.args.get("lang","ar").strip().lower() or "ar")
    if language not in ("ar","en","es","de","id","pt","tr","fr","hi"):
        language="en"
    rows=Article.query.filter_by(kind=kind,published=True,language=language).order_by(Article.created_at.desc()).limit(100).all()
    if not rows and language!="ar":
        rows=Article.query.filter_by(kind=kind,published=True,language="ar").order_by(Article.created_at.desc()).limit(100).all()
    return jsonify({"ok":True,"language":language,"items":[public_article(x) for x in rows]})
@app.post("/api/admin/login-bootstrap")
@limiter.limit("3 per hour")
def admin_bootstrap():
    # One-time bootstrap protected by an out-of-band secret; disabled after first admin exists.
    secret=os.environ.get("ADMIN_BOOTSTRAP_TOKEN","")
    if not secret or User.query.filter_by(role="admin").first():
        return json_error("تهيئة المدير غير متاحة",404)
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return json_error("بيانات التهيئة غير صحيحة")
    if not hmac.compare_digest(str(data.get("token","")),secret):
        return json_error("رمز التهيئة غير صحيح",403)
    email_value=data.get("email")
    email=email_value.strip().casefold() if isinstance(email_value,str) else ""
    password=data.get("password")
    if not valid_email(email) or not valid_password(password,14):
        return json_error("كلمة مرور المدير يجب أن تكون 14 خانة على الأقل وتحتوي حروفاً وأرقاماً")
    if User.query.filter_by(email=email).first():
        return json_error("البريد مستخدم بالفعل؛ استخدم بريداً آخر أو سجّل الدخول للحساب الموجود",409)
    user=User(email=email,password_hash=generate_password_hash(password),role="admin",subscription_plan="admin")
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return json_error("البريد مستخدم بالفعل؛ استخدم بريداً آخر",409)
    token=establish_user_session(user)
    return jsonify({"ok":True,"user":user_json(user),"csrf":token}),201

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
    language=str(data.get("language","ar")).strip().lower()
    if language not in ("ar","en","es","de","id","pt","tr","fr","hi"): return json_error("لغة المقال غير مدعومة")
    if kind not in ("blog","news") or not title or not body: return json_error("العنوان والمحتوى مطلوبان")
    slug=re.sub(r"[^a-z0-9\u0600-\u06ff]+","-",title.lower()).strip("-")[:200] or secrets.token_hex(8)
    if Article.query.filter_by(slug=slug).first(): slug+="-"+secrets.token_hex(3)
    a=Article(kind=kind,title=title[:220],slug=slug,summary=str(data.get("summary",""))[:500],body=body,published=bool(data.get("published",False)),
              language=language,meta_title=str(data.get("meta_title",title))[:70],meta_description=str(data.get("meta_description",data.get("summary","")))[:170],
              canonical_slug=str(data.get("canonical_slug",slug))[:240])
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
    if not valid_email(admin_email) or not valid_password(admin_password,14):
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
    article_columns={column["name"] for column in inspect(db.engine).get_columns(Article.__tablename__)}
    article_migrations={"language":"VARCHAR(8) NOT NULL DEFAULT 'ar'","meta_title":"VARCHAR(70) NOT NULL DEFAULT ''",
                        "meta_description":"VARCHAR(170) NOT NULL DEFAULT ''","canonical_slug":"VARCHAR(240) NOT NULL DEFAULT ''"}
    for column_name,column_type in article_migrations.items():
        if column_name not in article_columns:
            with db.engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {Article.__tablename__} ADD COLUMN {column_name} {column_type}"))
    provision_admin_from_env()


def write_scan_runtime(market,status,started_at=None,finished_at=None,result=None,error_code=None):
    key="scan-runtime:"+market
    row=db.session.get(Setting,key)
    try:
        record=json.loads(row.value) if row else {}
        if not isinstance(record,dict):
            record={}
    except (TypeError,ValueError):
        record={}
    if status in ("running","market_closed"):
        record["last_attempt_at"]=iso(started_at or utcnow())
    if status in ("success","error","market_closed"):
        finished_at=finished_at or utcnow()
        record["last_finished_at"]=iso(finished_at)
        if started_at:
            record["duration_seconds"]=round(max(0.0,(finished_at-started_at).total_seconds()),2)
    record["status"]=status
    if status=="success":
        record["last_success_at"]=iso(finished_at or utcnow())
        record["last_error_code"]=None
        if result:
            for key_name in ("scan_universe","scan_batch_size","analysis_completed","analysis_failed","strategy_matches","accepted_signals"):
                if key_name in result:
                    record[key_name]=result[key_name]
    elif status=="error":
        record["last_error_code"]=error_code or "scan_failed"
    elif status=="market_closed":
        record["last_error_code"]=None
    payload=json.dumps(record,ensure_ascii=False)
    if row is None:
        db.session.add(Setting(key=key,value=payload))
    else:
        row.value=payload
    db.session.commit()


def scheduled_market_scan(market):
    # Persist each attempt so a stale page can distinguish a closed exchange,
    # an inactive scheduler, and a failed provider/scanner cycle.
    with app.app_context():
        started=utcnow()
        try:
            write_scan_runtime(market,"running",started_at=started)
            if market=="saudi" and not saudi_market_is_open(started):
                write_scan_runtime(market,"market_closed",started_at=started,finished_at=utcnow())
                app.logger.info("scheduled scan skipped: market=saudi reason=market_closed")
                return
            result=run_market_scan(market,force=True)
            finished=utcnow()
            write_scan_runtime(market,"success",started_at=started,finished_at=finished,result=result)
            app.logger.info(
                "scheduled scan completed: market=%s signals=%s universe=%s frames=%s failures=%s",
                market,len(result.get("signals",[])),result.get("scan_universe"),
                result.get("timeframes"),result.get("analysis_failed",0)
            )
        except Exception as exc:
            db.session.rollback()
            code=scan_error_code(exc)
            try:
                write_scan_runtime(market,"error",started_at=started,finished_at=utcnow(),error_code=code)
            except Exception:
                db.session.rollback()
                app.logger.exception("could not persist scanner failure status: %s",market)
            app.logger.exception("scheduled scan failed: %s code=%s",market,code)
        finally:
            db.session.remove()


SCAN_INTERVAL_SECONDS=15*60
SCAN_INITIAL_DELAY_SECONDS=30
SCAN_MISFIRE_GRACE_SECONDS=300
SCAN_EXECUTOR_WORKERS=1


def market_scan_initial_delay_seconds(index):
    """Spread market jobs evenly across the 15-minute cycle."""
    spacing=max(1,SCAN_INTERVAL_SECONDS//len(MARKETS))
    return SCAN_INITIAL_DELAY_SECONDS+max(0,int(index))*spacing


AUTO_SCAN_ENABLED=os.environ.get("ENABLE_AUTO_SCAN","true").lower()=="true"
scheduler=None
if AUTO_SCAN_ENABLED:
    # One scheduler worker prevents seven markets from launching together on
    # the small production container. Each market keeps its own 15m cadence,
    # but starts at a staggered offset to avoid executor misfire backlogs.
    scheduler=BackgroundScheduler(
        timezone="UTC",
        executors={"default":{"type":"threadpool","max_workers":SCAN_EXECUTOR_WORKERS}},
        job_defaults={"coalesce":True,"max_instances":1,
                      "misfire_grace_time":SCAN_MISFIRE_GRACE_SECONDS},
    )
    for index,market in enumerate(MARKETS):
        scheduler.add_job(
            scheduled_market_scan,"interval",minutes=15,id="market-scan-"+market,
            args=[market],max_instances=1,coalesce=True,
            misfire_grace_time=SCAN_MISFIRE_GRACE_SECONDS,
            next_run_time=utcnow()+timedelta(seconds=market_scan_initial_delay_seconds(index))
        )
    scheduler.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","8080")))