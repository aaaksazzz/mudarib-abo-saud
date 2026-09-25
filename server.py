import os, sqlite3, secrets, time, hmac, threading, urllib.parse, xml.etree.ElementTree as ET, html
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, send_from_directory

app=Flask(__name__,template_folder="templates",static_folder=None)
app.config["MAX_CONTENT_LENGTH"]=512*1024
try:
 from werkzeug.middleware.proxy_fix import ProxyFix
 app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1)
except Exception:
 pass
BASE_DIR=os.path.dirname(os.path.abspath(__file__))
STATIC=os.path.join(BASE_DIR,"static")
# Canonical public origin for SEO. Preview/proxy hosts must never become canonical.
PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","https://mudarib-abo-saud-4.onrender.com").strip().rstrip("/")
app.jinja_env.globals["public_base_url"]=PUBLIC_BASE_URL
_db_env=os.getenv("SQLITE_FILE","mudarib.db").strip()
DB=_db_env if os.path.isabs(_db_env) else os.path.join(BASE_DIR,_db_env)
def _load_secret_key():
    configured=os.getenv("SECRET_KEY","").strip()
    if configured:
        return configured
    admin_user=os.getenv("ADMIN_USERNAME","").strip()
    admin_pass=os.getenv("ADMIN_PASSWORD","")
    if admin_user and admin_pass:
        import hashlib
        return hashlib.sha256(("mudarib-abo-saud-session-v2|" + admin_user + "|" + admin_pass).encode("utf-8")).hexdigest()
    path=os.path.join(os.path.dirname(DB) or ".", "session_secret.key")
    try:
        os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f:
                value=f.read().strip()
                if value:
                    return value
        value=secrets.token_hex(32)
        with open(path,"w",encoding="utf-8") as f:f.write(value)
        return value
    except Exception:
        return secrets.token_hex(32)
app.secret_key=_load_secret_key()
_session_secure_env=os.getenv("SESSION_COOKIE_SECURE","").strip().lower()
_session_secure=_session_secure_env in ("1","true","yes") if _session_secure_env else True
app.config.update(
 SESSION_COOKIE_NAME="mudarib_session",
 SESSION_COOKIE_HTTPONLY=True,
 SESSION_COOKIE_SAMESITE="Lax",
 SESSION_COOKIE_SECURE=_session_secure,
 SESSION_COOKIE_PATH="/",
 SESSION_REFRESH_EACH_REQUEST=True,
 PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)
PAID_MARKETS={"contracts":[("ES=F","S&P 500 E-mini"),("NQ=F","Nasdaq 100 E-mini"),("YM=F","Dow Jones E-mini"),("RTY=F","Russell 2000 E-mini"),("CL=F","Crude Oil WTI"),("GC=F","Gold Futures"),("SI=F","Silver Futures")],"saudi":[],"usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta Platforms"),("GOOGL","Alphabet"),("GOOG","Alphabet"),("TSLA","Tesla"),("AVGO","Broadcom"),("AMD","AMD"),("NFLX","Netflix"),("COST","Costco"),("JPM","JPMorgan Chase"),("V","Visa"),("MA","Mastercard"),("WMT","Walmart"),("ORCL","Oracle"),("CRM","Salesforce"),("LLY","Eli Lilly"),("XOM","Exxon Mobil"),("JNJ","Johnson & Johnson"),("BAC","Bank of America"),("ABBV","AbbVie"),("KO","Coca-Cola"),("PG","Procter & Gamble"),("HD","Home Depot"),("CVX","Chevron"),("MRK","Merck"),("PEP","PepsiCo"),("ADBE","Adobe"),("CSCO","Cisco"),("QCOM","Qualcomm"),("INTC","Intel"),("IBM","IBM"),("GE","GE Aerospace"),("CAT","Caterpillar"),("BA","Boeing"),("GS","Goldman Sachs"),("MS","Morgan Stanley"),("WFC","Wells Fargo"),("DIS","Disney"),("UBER","Uber"),("SHOP","Shopify"),("PLTR","Palantir"),("COIN","Coinbase"),("MCD","McDonalds"),("NKE","Nike"),("T","AT&T"),("VZ","Verizon")],"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("EURGBP=X","EUR/GBP"),("EURJPY=X","EUR/JPY"),("GBPJPY=X","GBP/JPY"),("AUDJPY=X","AUD/JPY"),("NZDJPY=X","NZD/JPY"),("USDMXN=X","USD/MXN"),("USDZAR=X","USD/ZAR"),("USDTRY=X","USD/TRY"),("USDSGD=X","USD/SGD"),("USDHKD=X","USD/HKD"),("XAUUSD=X","Gold"),("XAGUSD=X","Silver")]}

MARKETS=dict(PAID_MARKETS)
PLANS={"7d":{"days":7,"price":10},"30d":{"days":30,"price":20},"90d":{"days":90,"price":30}}
ADMIN_RATE_LOCK=threading.Lock()
ADMIN_RATE={}
ADMIN_WINDOW=300
ADMIN_MAX_FAILURES=8
AUTH_RATE_LOCK=threading.Lock()
AUTH_RATE={}
AUTH_WINDOW=300
AUTH_MAX_FAILURES=8

def _rate_key(scope, identity=""):
    remote=request.remote_addr or "unknown"
    return scope+"|"+remote+"|"+identity[:120].lower()

def _rate_limited(scope, identity=""):
    key=_rate_key(scope,identity); now=time.time()
    with AUTH_RATE_LOCK:
        state=AUTH_RATE.get(key,{"at":now,"failures":0})
        if now-state["at"]>AUTH_WINDOW:
            state={"at":now,"failures":0}
        if state["failures"]>=AUTH_MAX_FAILURES:
            return True
        state["at"]=now
        AUTH_RATE[key]=state
    return False

def _rate_fail(scope, identity=""):
    key=_rate_key(scope,identity); now=time.time()
    with AUTH_RATE_LOCK:
        state=AUTH_RATE.get(key,{"at":now,"failures":0})
        if now-state["at"]>AUTH_WINDOW:
            state={"at":now,"failures":0}
        state["failures"]+=1
        state["at"]=now
        AUTH_RATE[key]=state

def _rate_clear(scope, identity=""):
    key=_rate_key(scope,identity)
    with AUTH_RATE_LOCK:
        AUTH_RATE.pop(key,None)

def _safe_external_url(value, fallback="#"):
    try:
        u=urllib.parse.urlparse(str(value or "").strip())
        if u.scheme.lower() in ("http","https") and u.netloc:
            return u.geturl()
    except Exception:
        pass
    return fallback

@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options","nosniff")
    response.headers.setdefault("X-Frame-Options","DENY")
    response.headers.setdefault("Referrer-Policy","strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security","max-age=31536000; includeSubDomains")
    return response

@app.after_request
def cache_control_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"]="public, max-age=300, stale-while-revalidate=86400"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store"
    return response

@app.before_request
def protect_cross_site_state_changes():
    if request.method not in ("POST","PUT","PATCH","DELETE"):
        return None
    origin=request.headers.get("Origin")
    if not origin:
        return None
    expected=request.host_url.rstrip("/")
    if origin.rstrip("/")!=expected:
        return fail("طلب غير مسموح",403)
    return None

def _log_admin_env_status():
    admin_user_present=bool(os.getenv("ADMIN_USERNAME","").strip())
    admin_pass_present=bool(os.getenv("ADMIN_PASSWORD","").strip())
    app.logger.info("Admin environment status: ADMIN_USERNAME=%s ADMIN_PASSWORD=%s",admin_user_present,admin_pass_present)

_log_admin_env_status()
H=requests.Session(); H.headers["User-Agent"]="Mudarib-Abo-Saud/1.0"
NEWS_CACHE={"at":0,"items":[]}
NEWS_QUERIES=[("🇸🇦 السعودية","السعودية سوق الأسهم تاسي أرامكو الراجحي اقتصاد"),("🇺🇸 الأسواق الأمريكية","الأسواق الأمريكية ناسداك داو جونز الأسهم"),("₿ العملات الرقمية","بيتكوين إيثريوم العملات الرقمية كريبتو"),("🛢️ النفط والذهب","النفط الذهب أسعار الأسواق"),("🌍 الاقتصاد العالمي","الاقتصاد العالمي الفائدة الدولار الأسواق المالية")]

@app.get("/static/<path:name>")
def static_file(name): return send_from_directory(STATIC,name,max_age=0)

def conn():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
 c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; return c
def init():
 c=conn(); c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,email TEXT UNIQUE,name TEXT,password TEXT,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT,plan TEXT,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,content TEXT,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);\nCREATE TABLE IF NOT EXISTS blog_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,slug TEXT UNIQUE,title TEXT NOT NULL,excerpt TEXT DEFAULT '',content TEXT NOT NULL,category TEXT DEFAULT 'عام',cover_url TEXT DEFAULT '',author TEXT DEFAULT 'المضارب ذكي',published INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);\nCREATE TABLE IF NOT EXISTS telegram_sent(signal_key TEXT PRIMARY KEY,sent_at TEXT DEFAULT CURRENT_TIMESTAMP,message_id INTEGER);\nCREATE TABLE IF NOT EXISTS signal_cache(market TEXT NOT NULL,interval TEXT NOT NULL,items TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(market,interval));
CREATE TABLE IF NOT EXISTS strong_signal_cache(market TEXT NOT NULL,interval TEXT NOT NULL,items TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(market,interval));
CREATE INDEX IF NOT EXISTS idx_strong_signal_cache_updated ON strong_signal_cache(updated_at);
CREATE TABLE IF NOT EXISTS ai_memory(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,interval TEXT NOT NULL,symbol TEXT NOT NULL,direction TEXT NOT NULL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,created_at REAL NOT NULL,status TEXT DEFAULT 'open',result TEXT DEFAULT '',resolved_at REAL DEFAULT 0,pnl_percent REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_ai_memory_lookup ON ai_memory(market,interval,symbol,status);
CREATE TABLE IF NOT EXISTS ai_performance(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,interval TEXT NOT NULL,metric TEXT NOT NULL,value REAL NOT NULL,created_at REAL NOT NULL);"""); c.commit()
 try:
  c.execute("ALTER TABLE ai_memory ADD COLUMN pnl_percent REAL DEFAULT 0"); c.commit()
 except sqlite3.OperationalError: pass

 # مزامنة/إنشاء حساب الإدارة من متغيرات البيئة بدون صفحة تسجيل منفصلة للإدارة.
 try:
  admin_identity=os.getenv("ADMIN_USERNAME","").strip()
  admin_password=os.getenv("ADMIN_PASSWORD","")
  if admin_identity and admin_password:
   from werkzeug.security import generate_password_hash
   row=c.execute("SELECT id,username,email FROM users WHERE username=? OR lower(email)=lower(?) LIMIT 1",(admin_identity,admin_identity)).fetchone()
   admin_email=admin_identity if "@" in admin_identity else admin_identity+"@admin.local"
   if row:
    c.execute("UPDATE users SET is_admin=1,password=? WHERE id=?",(generate_password_hash(admin_password),row["id"]))
   else:
    c.execute("INSERT OR IGNORE INTO users(username,email,name,password,is_admin) VALUES(?,?,?,?,1)",(admin_identity,admin_email,"مدير الموقع",generate_password_hash(admin_password)))
   c.execute("UPDATE users SET is_admin=1 WHERE username=? OR lower(email)=lower(?)",(admin_identity,admin_identity))
   c.commit()
 except Exception:
  app.logger.exception("Admin account bootstrap failed")
 finally:
  c.close()
def _seed_beginner_blog():
 articles=[
  ("dalil-al-tadawul-lilmubtadien","content/blog_beginner_trading.txt","دليل عملي للمبتدئين لفهم التداول وقراءة السوق وإدارة رأس المال والمخاطر.","تعليم التداول"),
  ("al-amlat-alraqmiya-lilmubtadien","content/blog-crypto-beginners.txt","دليل مبسط لفهم العملات الرقمية وقراءة السوق والسيولة والتقلب وإدارة المخاطر.","العملات الرقمية"),
  ("idarat-ras-almal-fi-altadawul","content/blog-risk-management.txt","شرح عملي لإدارة رأس المال وتحديد المخاطرة وحجم الصفقة والعائد مقابل المخاطرة.","إدارة المخاطر"),
  ("altahlil-alfani-lilmubtadien","content/blog-technical-analysis.txt","دليل مبسط لفهم التحليل الفني وحركة السعر والدعم والمقاومة والاختراقات.","التحليل الفني"),
  ("alfurkas-lilmubtadien","content/blog-forex-beginners.txt","دليل للمبتدئين لفهم سوق الفوركس وأزواج العملات والسيولة والأخبار والرافعة.","الفوركس"),
  ("aleoqod-alajila-lilmubtadien","content/blog-futures-beginners.txt","دليل لفهم العقود الآجلة والهامش والرافعة وتاريخ العقد والفروقات عن السوق الفوري.","العقود الآجلة"),

  ("tahlil-harakat-alsaar-price-action","content/blog-price-action.txt","تعلم قراءة حركة السعر والقمم والقيعان والدعم والمقاومة والاختراقات.","حركة السعر"),
  ("tahlil-alshomoa-alyabaniya","content/blog-candlestick-analysis.txt","دليل تعلم الشموع اليابانية وأنماط الرفض والابتلاع وقراءة سياق الشمعة.","الشموع اليابانية"),
  ("tahlil-alaitijah","content/blog-trend-analysis.txt","تعلم تحليل الاتجاهات الصاعدة والهابطة والجانبية وبنية الحركة.","تحليل الاتجاه"),
  ("aldam-walmqawama","content/blog-support-resistance.txt","تعلم الدعم والمقاومة والاختراق وإعادة الاختبار بطريقة عملية.","الدعم والمقاومة"),
  ("tahlil-alhajm","content/blog-volume-analysis.txt","تعلم قراءة حجم التداول وربطه بحركة السعر والاختراقات والسيولة.","تحليل الحجم"),
  ("dalil-almoashirat-alfaniya","content/blog-indicators-guide.txt","دليل تعلم RSI وMACD والمتوسطات وStochastic وATR واستخدام المؤشرات.","المؤشرات الفنية"),
  ("volume-profile","content/blog-volume-profile.txt","تعلم Volume Profile وPoint of Control وValue Area وتوزيع التداول على الأسعار.","Volume Profile"),
  ("market-structure","content/blog-market-structure.txt","تعلم Market Structure والقمم والقيعان وكسر البنية.","بنية السوق"),
  ("alnamathij-alsariya","content/blog-chart-patterns.txt","تعلم المثلثات والأعلام والرأس والكتفين والقمم والقيعان المزدوجة.","النماذج السعرية"),
  ("altahlil-alasasi","content/blog-fundamental-analysis.txt","تعلم التحليل الأساسي للأسهم والعملات والسلع والعملات الرقمية.","التحليل الأساسي"),
  ("tahlil-manoiyat-alsouq","content/blog-sentiment-analysis.txt","تعلم تحليل معنويات السوق والأخبار والمراكز وتوجهات المتداولين.","معنويات السوق"),
  ("intermarket-analysis","content/blog-intermarket-analysis.txt","تعلم التحليل بين الأسواق وربط الأسهم والسندات والدولار والسلع.","التحليل بين الأسواق"),
  ("tahlil-mutadad-alar","content/blog-multi-timeframe-analysis.txt","تعلم التحليل متعدد الأطر الزمنية وربط الفريمات الكبيرة والصغيرة.","الأطر الزمنية"),
  ("tahlil-kami","content/blog-quantitative-analysis.txt","تعلم التحليل الكمي واستخدام البيانات والإحصاء والاختبارات التاريخية.","التحليل الكمي"),
  ("altahlil-algharizmi","content/blog-algorithmic-analysis.txt","تعلم التحليل الخوارزمي والتداول الآلي واختبار الاستراتيجيات.","التحليل الخوارزمي"),
  ("altahlil-aliqtisadi-alkuli","content/blog-economic-analysis.txt","تعلم التحليل الاقتصادي الكلي والفائدة والتضخم والنمو والسيولة.","الاقتصاد الكلي"),
  ("altahlil-alharmoniki","content/blog-harmonic-analysis.txt","دليل تعلم التحليل الهارموني ونماذج Gartley وBat وButterfly وCrab وShark وCypher ونسب فيبوناتشي.","التحليل الهارموني"),
  ("altahlil-alklasiki","content/blog-classical-analysis.txt","تعليم التداول بالتحليل الكلاسيكي: الاتجاه والدعم والمقاومة والاختراقات والنماذج السعرية وقراءة الشارت.","التحليل الكلاسيكي")
 ]
 c=conn()
 try:
  for slug,filename,excerpt,category in articles:
   if c.execute("SELECT 1 FROM blog_posts WHERE slug=?",(slug,)).fetchone(): continue
   path=os.path.join(BASE_DIR,filename)
   with open(path,"r",encoding="utf-8") as f: content=f.read().strip()
   title=content.split("\n",1)[0].strip()
   c.execute("INSERT INTO blog_posts(slug,title,excerpt,content,category,author,published) VALUES(?,?,?,?,?,?,1)",(slug,title,excerpt,content,category,"المضارب ذكي"))
  c.commit()
  app.logger.info("SEO trading blog articles seeded")
 except Exception:
  c.rollback()
  app.logger.exception("Trading blog seed failed")
 finally:
  c.close()

def ok(**x): return jsonify(ok=True,**x)
def fail(m,code=400): return jsonify(ok=False,message=m),code
def current_user():
    username=session.get("user")
    if not username:return None
    c=conn();u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone();c.close()
    return u

def has_active_subscription():
    u=current_user()
    if not u or not u["subscription_until"]:return False
    try:return datetime.fromisoformat(u["subscription_until"])>datetime.now(timezone.utc)
    except:return False

def require_market_access(market):
    # جميع الصفقات والتحليلات متاحة مجاناً حالياً.
    # نحتفظ بـ PAID_MARKETS داخلياً كقائمة أسواق فقط، وليس كحاجز وصول.
    return None

def _candles_from_yahoo(sym,interval,range_):
    last=None
    lookup={"XAUUSD=X":"GC=F","XAGUSD=X":"SI=F"}
    symbol=lookup.get(sym,sym)
    for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
        try:
            r=H.get("https://"+host+"/v8/finance/chart/"+urllib.parse.quote(symbol,safe=""),params={"interval":interval,"range":range_,"includePrePost":"true"},timeout=15)
            r.raise_for_status();payload=r.json();result=(payload.get("chart") or {}).get("result")
            if not result: raise ValueError((payload.get("chart") or {}).get("error") or "Yahoo returned no data")
            z=result[0];q=z["indicators"]["quote"][0];out=[];timestamps=z.get("timestamp",[]);volumes=q.get("volume") or [0]*len(timestamps)
            for i,t in enumerate(timestamps):
                try:
                    o,h,l,cl=q["open"][i],q["high"][i],q["low"][i],q["close"][i]
                    if None in (o,h,l,cl): continue
                    out.append({"time":t,"open":float(o),"high":float(h),"low":float(l),"close":float(cl),"volume":float(volumes[i] or 0)})
                except Exception: pass
            if out:return out
            raise ValueError("Yahoo returned empty candles")
        except Exception as e:
            last=e
            app.logger.warning("Yahoo source failed %s %s %s: %s",symbol,interval,range_,e)
    raise RuntimeError(str(last) if last else "Yahoo unavailable")

def _candles_from_finnhub(sym,interval):
    key=os.getenv("FINNHUB_API_KEY","").strip()
    if not key: raise RuntimeError("FINNHUB_API_KEY غير مضبوط")
    resolution={"5m":"5","15m":"15","30m":"30","1H":"60","4H":"240","1D":"D","1W":"W","1M":"M"}.get(interval,"D")
    now=int(time.time()); seconds={"5m":86400*5,"15m":86400*20,"30m":86400*30,"1H":86400*30,"4H":86400*120,"1D":86400*365,"1W":86400*1825,"1M":86400*3650}.get(interval,86400*365)
    r=H.get("https://finnhub.io/api/v1/stock/candle",params={"symbol":sym.replace(".SR",""),"resolution":resolution,"from":now-seconds,"to":now,"token":key},timeout=15);r.raise_for_status();d=r.json()
    if d.get("s")!="ok": raise RuntimeError(d.get("s") or "Finnhub no data")
    return [{"time":int(t),"open":float(o),"high":float(h),"low":float(l),"close":float(c),"volume":float(v or 0)} for t,o,h,l,c,v in zip(d["t"],d["o"],d["h"],d["l"],d["c"],d.get("v",[0]*len(d["t"])))]

def _candles_from_twelve(sym,interval):
    key=os.getenv("TWELVE_DATA_API_KEY","").strip()
    if not key: raise RuntimeError("TWELVE_DATA_API_KEY غير مضبوط")
    iv={"5m":"5min","15m":"15min","30m":"30min","1H":"1h","4H":"4h","1D":"1day","1W":"1week","1M":"1month"}.get(interval,"1day")
    r=H.get("https://api.twelvedata.com/time_series",params={"symbol":sym,"interval":iv,"outputsize":100,"apikey":key},timeout=15);r.raise_for_status();d=r.json()
    if d.get("status")=="error": raise RuntimeError(d.get("message") or "Twelve Data no data")
    out=[]
    for x in reversed(d.get("values") or []):
        try: out.append({"time":int(datetime.fromisoformat(x["datetime"].replace("Z","+00:00")).timestamp()),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0) or 0)})
        except Exception: pass
    if not out: raise RuntimeError("Twelve Data returned empty candles")
    return out

def _candles_from_alpha_vantage(sym,interval):
    key=os.getenv("ALPHAVANTAGE_API_KEY","").strip()
    if not key: raise RuntimeError("ALPHAVANTAGE_API_KEY غير مضبوط")
    if interval=="1D":
        fn="TIME_SERIES_DAILY";params={"function":fn,"symbol":sym,"outputsize":"compact","apikey":key}
        series_key="Time Series (Daily)"
    else:
        iv={"5m":"5min","15m":"15min","30m":"30min","1H":"60min"}.get(interval)
        if not iv: raise RuntimeError("Alpha Vantage لا يدعم هذا الفريم")
        params={"function":"TIME_SERIES_INTRADAY","symbol":sym,"interval":iv,"outputsize":"compact","apikey":key}
        series_key="Time Series ("+iv+")"
    r=H.get("https://www.alphavantage.co/query",params=params,timeout=20);r.raise_for_status();d=r.json();series=d.get(series_key) or {}
    if not series: raise RuntimeError(d.get("Note") or d.get("Information") or d.get("Error Message") or "Alpha Vantage no data")
    out=[]
    for dt,x in reversed(list(series.items())):
        try: out.append({"time":int(datetime.fromisoformat(dt.replace(" ","T")).replace(tzinfo=timezone.utc).timestamp()),"open":float(x["1. open"]),"high":float(x["2. high"]),"low":float(x["3. low"]),"close":float(x["4. close"]),"volume":float(x.get("5. volume",0) or 0)})
        except Exception: pass
    return out

def _candles_from_massive(sym,interval):
    key=os.getenv("MASSIVE_API_KEY","").strip()
    if not key: raise RuntimeError("MASSIVE_API_KEY غير مضبوط")
    mult={"5m":5,"15m":15,"30m":30,"1H":60,"4H":60,"1D":1}.get(interval)
    span="minute" if interval!="1D" else "day"
    end=datetime.now(timezone.utc); start=end-timedelta(days={"5m":7,"15m":20,"30m":35,"1H":60,"4H":180,"1D":370}.get(interval,30))
    url=f"https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(sym.replace('.SR',''),safe='')}/range/{mult}/{span}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
    r=H.get(url,params={"adjusted":"true","sort":"asc","limit":5000,"apiKey":key},timeout=20);r.raise_for_status();d=r.json()
    out=[]
    for x in d.get("results") or []:
        try: out.append({"time":int(x["t"])//1000,"open":float(x["o"]),"high":float(x["h"]),"low":float(x["l"]),"close":float(x["c"]),"volume":float(x.get("v",0) or 0)})
        except Exception: pass
    if not out: raise RuntimeError("Massive returned no data")
    return out

def _candles_from_eodhd(sym,interval):
    key=os.getenv("EODHD_API_KEY","").strip()
    if not key: raise RuntimeError("EODHD_API_KEY غير مضبوط")
    ticker=sym if "." in sym else sym+".US"
    if interval=="1D":
        end=datetime.now(timezone.utc); start=end-timedelta(days=730)
        r=H.get(f"https://eodhd.com/api/eod/{urllib.parse.quote(ticker,safe='')}",params={"api_token":key,"from":start.strftime("%Y-%m-%d"),"to":end.strftime("%Y-%m-%d"),"fmt":"json"},timeout=20)
    else:
        iv={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h"}.get(interval)
        if not iv: raise RuntimeError("EODHD unsupported interval")
        end=int(time.time()); start=end-{"5m":30,"15m":60,"30m":90,"1H":180,"4H":365}.get(interval,30)*86400
        r=H.get(f"https://eodhd.com/api/intraday/{urllib.parse.quote(ticker,safe='')}",params={"api_token":key,"interval":iv,"from":start,"to":end,"fmt":"json"},timeout=20)
    r.raise_for_status();d=r.json()
    out=[]
    for x in d if isinstance(d,list) else []:
        try:
            raw=x.get("timestamp")
            ts=int(raw) if raw is not None else int(datetime.fromisoformat(str(x["datetime"]).replace("Z","+00:00")).timestamp())
            out.append({"time":ts,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0) or 0)})
        except Exception: pass
    if not out: raise RuntimeError("EODHD returned no data")
    return out

def _candles_from_tiingo(sym,interval):
    key=os.getenv("TIINGO_API_KEY","").strip()
    if not key: raise RuntimeError("TIINGO_API_KEY غير مضبوط")
    freq={"5m":"5min","15m":"15min","30m":"30min","1H":"1hour","4H":"1hour","1D":"1day"}.get(interval,"1day")
    end=datetime.now(timezone.utc); start=end-timedelta(days={"5m":30,"15m":60,"30m":90,"1H":180,"4H":365,"1D":730}.get(interval,30))
    url=f"https://api.tiingo.com/tiingo/daily/{urllib.parse.quote(sym.replace('.SR',''),safe='')}/prices"
    r=H.get(url,params={"startDate":start.strftime("%Y-%m-%d"),"endDate":end.strftime("%Y-%m-%d"),"resampleFreq":freq},headers={"Content-Type":"application/json","Authorization":"Token "+key},timeout=20);r.raise_for_status();d=r.json()
    out=[]
    for x in d if isinstance(d,list) else []:
        try:
            ts=int(datetime.fromisoformat(str(x["date"]).replace("Z","+00:00")).timestamp())
            out.append({"time":ts,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0) or 0)})
        except Exception: pass
    if not out: raise RuntimeError("Tiingo returned no data")
    return out

def _candles_from_ninequant(sym,interval):
    if interval!="1D": raise RuntimeError("NineQuant الاحتياطي يدعم اليومي فقط حالياً")
    symbol=sym if "." in sym else sym+".US"
    r=H.get("https://api.ninequantai.com/v1/kline/"+urllib.parse.quote(symbol,safe=""),timeout=15)
    r.raise_for_status();d=r.json()
    rows=d.get("data") if isinstance(d,dict) else d
    if isinstance(rows,dict): rows=rows.get("candles") or rows.get("results") or rows.get("data")
    out=[]
    for x in rows or []:
        try:
            if isinstance(x,dict):
                ts=x.get("timestamp") or x.get("time") or x.get("t")
                o=x.get("open",x.get("o"));h=x.get("high",x.get("h"));l=x.get("low",x.get("l"));cl=x.get("close",x.get("c"));v=x.get("volume",x.get("v",0))
            else:
                ts,o,h,l,cl,v=x[:6]
            ts=float(ts); ts=ts/1000 if ts>100000000000 else ts
            out.append({"time":int(ts),"open":float(o),"high":float(h),"low":float(l),"close":float(cl),"volume":float(v or 0)})
        except Exception: pass
    if not out: raise RuntimeError("NineQuant returned no data")
    return out

def _candles_from_stooq(sym,interval):
    if interval!="1D": raise RuntimeError("Stooq احتياطي يومي فقط")
    base=sym.lower().replace(".sr","")
    if not base.isalnum(): raise RuntimeError("Stooq symbol unsupported")
    url="https://stooq.com/q/d/l/?"+urllib.parse.urlencode({"s":base+".us","d1":(datetime.now(timezone.utc)-timedelta(days=370)).strftime("%Y%m%d"),"d2":datetime.now(timezone.utc).strftime("%Y%m%d"),"i":"d"})
    r=H.get(url,timeout=15);r.raise_for_status();lines=r.text.strip().splitlines()
    if len(lines)<2: raise RuntimeError("Stooq returned no data")
    out=[]
    for line in lines[1:]:
        try:
            p=line.split(",");dt=datetime.fromisoformat(p[0]).replace(tzinfo=timezone.utc)
            out.append({"time":int(dt.timestamp()),"open":float(p[1]),"high":float(p[2]),"low":float(p[3]),"close":float(p[4]),"volume":float(p[5] or 0)})
        except Exception: pass
    return out

def yahoo(sym,interval,range_):
    sources=[("Yahoo",lambda:_candles_from_yahoo(sym,interval,range_))]
    if os.getenv("MASSIVE_API_KEY","").strip(): sources.append(("Massive",lambda:_candles_from_massive(sym,interval)))
    sources.append(("NineQuant",lambda:_candles_from_ninequant(sym,interval)))
    if os.getenv("FINNHUB_API_KEY","").strip(): sources.append(("Finnhub",lambda:_candles_from_finnhub(sym,interval)))
    if os.getenv("TWELVE_DATA_API_KEY","").strip(): sources.append(("Twelve Data",lambda:_candles_from_twelve(sym,interval)))
    if os.getenv("ALPHAVANTAGE_API_KEY","").strip(): sources.append(("Alpha Vantage",lambda:_candles_from_alpha_vantage(sym,interval)))
    if os.getenv("EODHD_API_KEY","").strip(): sources.append(("EODHD",lambda:_candles_from_eodhd(sym,interval)))
    if os.getenv("TIINGO_API_KEY","").strip(): sources.append(("Tiingo",lambda:_candles_from_tiingo(sym,interval)))
    if os.getenv("STOOQ_API_KEY","").strip(): sources.append(("Stooq",lambda:_candles_from_stooq(sym,interval)))
    errors=[]
    for name,fn in sources:
        try:
            out=fn()
            if len(out)>=12:
                app.logger.info("Market data source used %s for %s %s",name,sym,interval)
                return out
            raise RuntimeError("empty/insufficient candles")
        except Exception as e:
            errors.append(name+": "+str(e));app.logger.warning("Market source failed %s %s %s: %s",name,sym,interval,e)
    raise RuntimeError("تعذر جلب بيانات "+sym+" من جميع المصادر: "+" | ".join(errors[-3:]))
def okx(inst,bar):
 r=H.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":100},timeout=12);r.raise_for_status();out=[]
 for x in reversed(r.json().get("data",[])):
  try: out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
  except: pass
 return out
AI_CACHE={}
AI_CACHE_TTL=900
AI_STALE_TTL=3600
AI_CACHE_TTL=300
AI_MODEL=os.getenv("OPENAI_MODEL","gpt-5.6-luna").strip()
SCAN_CACHE={}
SCAN_CACHE_TTL=180
SCAN_CACHE_LOCK=threading.Lock()
SCAN_INFLIGHT={}
SCAN_INFLIGHT_LOCK=threading.Lock()

def _ai_json(prompt):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise RuntimeError("OPENAI_API_KEY غير مضبوط")
    body={"model":AI_MODEL,"input":[{"role":"system","content":[{"type":"input_text","text":"أنت متداول ومحلل أسواق آلي شديد الانضباط. ادرس الحركة الحالية ثم قارنها بالحركات السابقة المشابهة داخل البيانات قبل نشر أي صفقة. حلل بنية السوق والقمم والقيعان والشموع والاختراق وإعادة الاختبار والرفض والسيولة والحجم والزخم والتذبذب والسياق الزمني من OHLCV الخام. لا تعتمد على مؤشرات جاهزة. إذا كانت الأفضلية غير واضحة فأعد حيادي. لا تضمن الربح. اجعل وقف الخسارة خارج الضوضاء، وTP1=1R وTP2=2R وTP3=3R تقريباً. أعد JSON فقط بالمفاتيح: items، وكل عنصر يحتوي symbol,direction,confidence,trade_ready,entry,tp1,tp2,tp3,sl,rr,reason."}]},{"role":"user","content":[{"type":"input_text","text":prompt}]}],"text":{"format":{"type":"json_object"}}}
    r=H.post("https://api.openai.com/v1/responses",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=body,timeout=60)
    r.raise_for_status(); data=r.json(); txt=data.get("output_text")
    if not txt:
        for item in data.get("output",[]):
            for content in item.get("content",[]):
                if content.get("type")=="output_text": txt=content.get("text"); break
            if txt: break
    if not txt: raise RuntimeError("AI لم يرجع نتيجة")
    return __import__("json").loads(txt)

def _memory_stats(market,interval,symbol,direction):
    """Long-term learning memory: symbol + market + timeframe + direction, with recency weighting."""
    try:
        c=conn()
        rows=c.execute("SELECT result,created_at,confidence FROM ai_memory WHERE market=? AND interval=? AND symbol=? AND direction=? AND status='closed' ORDER BY created_at DESC LIMIT 250",(market,interval,symbol,direction)).fetchall()
        if not rows:
            rows=c.execute("SELECT result,created_at,confidence FROM ai_memory WHERE market=? AND interval=? AND direction=? AND status='closed' ORDER BY created_at DESC LIMIT 500",(market,interval,direction)).fetchall()
        c.close()
        if not rows:return 0,0.0
        now=time.time(); weighted_w=weighted_n=0.0
        for r in rows:
            age_days=max(0.0,(now-float(r["created_at"] or now))/86400.0)
            weight=1.0/(1.0+age_days/14.0)
            weighted_n+=weight
            if r["result"] in ("tp1","tp2","tp3"):weighted_w+=weight
        return len(rows),(weighted_w/weighted_n*100.0 if weighted_n else 0.0)
    except Exception:
        return 0,0.0

def _memory_profile(market,interval,symbol,direction):
    try:
        c=conn()
        rows=c.execute("SELECT result,confidence,created_at FROM ai_memory WHERE market=? AND interval=? AND symbol=? AND direction=? AND status='closed' ORDER BY created_at DESC LIMIT 500",(market,interval,symbol,direction)).fetchall()
        c.close()
        n=len(rows); wins=sum(1 for r in rows if r["result"] in ("tp1","tp2","tp3"))
        avg=sum(float(r["confidence"] or 0) for r in rows)/n if n else 0
        return {"samples":n,"wins":wins,"winRate":round(wins/n*100,1) if n else 0,"avgConfidence":round(avg,1)}
    except Exception:
        return {"samples":0,"wins":0,"winRate":0,"avgConfidence":0}

def _review_ai_memory(candles_by_symbol,market,interval):
    now=time.time()
    try:
        c=conn()
        age_seconds={"5m":900,"15m":2700,"30m":5400,"1H":14400,"4H":43200,"1D":172800,"1W":1209600}.get(interval,3600)
        rows=c.execute("SELECT id,symbol,direction,tp1,tp2,tp3,sl,created_at FROM ai_memory WHERE market=? AND interval=? AND status='open' AND created_at<? ORDER BY id LIMIT 500",(market,interval,now-age_seconds)).fetchall()
        for row in rows:
            future=[x for x in candles_by_symbol.get(row["symbol"],[]) if float(x.get("time",0) or 0)>float(row["created_at"])]
            result=""
            for k in future:
                hi=float(k["high"]); lo=float(k["low"])
                if row["direction"]=="شراء":
                    if lo<=float(row["sl"]): result="sl"; break
                    if hi>=float(row["tp3"]): result="tp3"; break
                    if hi>=float(row["tp2"]): result="tp2"; break
                    if hi>=float(row["tp1"]): result="tp1"; break
                else:
                    if hi>=float(row["sl"]): result="sl"; break
                    if lo<=float(row["tp3"]): result="tp3"; break
                    if lo<=float(row["tp2"]): result="tp2"; break
                    if lo<=float(row["tp1"]): result="tp1"; break
            if result:
                c.execute("UPDATE ai_memory SET status='closed',result=?,resolved_at=? WHERE id=?",(result,now,row["id"]))
        c.commit(); c.close()
    except Exception as e:
        app.logger.warning("AI memory review failed: %s",e)

def _remember_ai(items,market,interval,candles_by_symbol):
    now=time.time()
    try:
        c=conn()
        for x in items:
            if not x.get("trade_ready") or x.get("direction") not in ("شراء","بيع"): continue
            entry_value=float(x.get("entry",0) or 0)
            if entry_value<=0: continue
            c.execute("INSERT INTO ai_memory(market,interval,symbol,direction,entry,tp1,tp2,tp3,sl,confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (market,interval,x.get("symbol",""),x.get("direction"),entry_value,float(x.get("tp1",0) or 0),float(x.get("tp2",0) or 0),float(x.get("tp3",0) or 0),float(x.get("sl",0) or 0),float(x.get("confidence",0) or 0),float((candles_by_symbol.get(x.get("symbol"),[]) or [{}])[-1].get("time",now))))
        c.commit(); c.close()
    except Exception as e:
        app.logger.warning("AI memory write failed: %s",e)

def _register_trade_candidates(items):
    """Persist newly published strong AI opportunities for outcome tracking."""
    try:
        now=time.time(); db=conn()
        for x in items if isinstance(items,list) else []:
            if not x.get("trade_ready",x.get("tradeReady",False)) or x.get("direction") not in ("شراء","بيع"): continue
            entry_value=float(x.get("entry",0) or 0)
            vals=(x.get("market"),x.get("interval"),x.get("symbol"),x.get("direction"),entry_value)
            row=db.execute("SELECT id FROM ai_memory WHERE market=? AND interval=? AND symbol=? AND direction=? AND entry=? ORDER BY id DESC LIMIT 1",vals).fetchone()
            if row: continue
            db.execute("INSERT INTO ai_memory(market,interval,symbol,direction,entry,tp1,tp2,tp3,sl,confidence,created_at,status,result,resolved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'open','',0)",
                       (x.get("market"),x.get("interval"),x.get("symbol"),x.get("direction"),float(x.get("entry",0) or 0),float(x.get("tp1",0) or 0),float(x.get("tp2",0) or 0),float(x.get("tp3",0) or 0),float(x.get("sl",0) or 0),float(x.get("confidence",0) or 0),now))
        db.commit();db.close()
    except Exception as e:
        app.logger.warning("Trade tracker registration failed: %s",e)

def _resolve_open_trades():
    """Check open signals against subsequent candles and close them at TP/SL."""
    try:
        db=conn(); rows=db.execute("SELECT * FROM ai_memory WHERE status='open' ORDER BY created_at ASC LIMIT 300").fetchall(); db.close()
        for row in rows:
            try:
                market,interval,symbol=row["market"],row["interval"],row["symbol"]
                if market in ("crypto","futures"):
                    candles=binance_candles(symbol,interval,market)
                else:
                    ymap={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d","1W":"1wk","1M":"1mo"}
                    rg="5d" if interval=="5m" else "1mo" if interval in ("15m","30m") else "1y"
                    candles=_candles_from_yahoo(symbol,ymap.get(interval,"1d"),rg)
                if not candles: continue
                created=float(row["created_at"] or 0); entry=float(row["entry"] or 0); sl=float(row["sl"] or 0)
                tps=[(1,float(row["tp1"] or 0)),(2,float(row["tp2"] or 0)),(3,float(row["tp3"] or 0))]
                hit=None
                for candle in candles:
                    if float(candle.get("time",0)) < created: continue
                    high=float(candle.get("high",0)); low=float(candle.get("low",0))
                    if row["direction"]=="شراء":
                        if sl>0 and low<=sl: hit=("sl",sl); break
                        reached=[(n,p) for n,p in tps if p>0 and high>=p]
                        if reached: hit=("tp%d"%max(n for n,p in reached),max(p for n,p in reached)); break
                    else:
                        if sl>0 and high>=sl: hit=("sl",sl); break
                        reached=[(n,p) for n,p in tps if p>0 and low<=p]
                        if reached: hit=("tp%d"%max(n for n,p in reached),min(p for n,p in reached)); break
                if not hit: continue
                result,price=hit
                pnl=((price-entry)/entry*100.0) if row["direction"]=="شراء" else ((entry-price)/entry*100.0)
                db=conn(); db.execute("UPDATE ai_memory SET status='closed',result=?,resolved_at=?,pnl_percent=? WHERE id=?",(result,time.time(),round(pnl,4),row["id"])); db.commit(); db.close()
            except Exception as e:
                app.logger.warning("Trade outcome check failed %s/%s/%s: %s",row["market"],row["interval"],row["symbol"],e)
    except Exception as e:
        app.logger.warning("Trade tracker read failed: %s",e)

def _trade_stats(period=None):
    db=conn(); where="status='closed'"; args=[]
    if period: where+=" AND resolved_at>=?"; args.append(time.time()-period)
    row=db.execute("SELECT COUNT(*) total,SUM(CASE WHEN result IN ('tp1','tp2','tp3') THEN 1 ELSE 0 END) wins,SUM(CASE WHEN result='sl' THEN 1 ELSE 0 END) losses,COALESCE(SUM(pnl_percent),0) pnl,COALESCE(AVG(pnl_percent),0) avg_pnl FROM ai_memory WHERE "+where,args).fetchone()
    open_count=db.execute("SELECT COUNT(*) n FROM ai_memory WHERE status='open'").fetchone()["n"]; db.close()
    total=int(row["total"] or 0); wins=int(row["wins"] or 0); losses=int(row["losses"] or 0)
    return {"total":total,"wins":wins,"losses":losses,"open":int(open_count or 0),"pnl":round(float(row["pnl"] or 0),2),"avgPnl":round(float(row["avg_pnl"] or 0),2),"winRate":round(wins/total*100,2) if total else 0.0}

def _ai_quality(market,interval):
    try:
        c=conn()
        row=c.execute("SELECT COUNT(*) n,SUM(CASE WHEN result IN ('tp1','tp2','tp3') THEN 1 ELSE 0 END) wins,SUM(CASE WHEN result='sl' THEN 1 ELSE 0 END) losses FROM ai_memory WHERE market=? AND interval=? AND status='closed'",(market,interval)).fetchone()
        c.close()
        n=int(row["n"] or 0); w=int(row["wins"] or 0); l=int(row["losses"] or 0)
        winrate=(w/n*100.0 if n else 0.0)
        expectancy=((w*1.0-l*1.0)/n if n else 0.0)
        profit_factor=(w/l if l else (999.0 if w else 0.0))
        return {"samples":n,"winRate":round(winrate,2),"expectancyR":round(expectancy,3),"profitFactor":round(profit_factor,2)}
    except Exception:
        return {"samples":0,"winRate":0.0,"expectancyR":0.0,"profitFactor":0.0}

def _ai_quality_gate(market,interval,confidence):
    q=_ai_quality(market,interval)
    if q["samples"]<20: return confidence>=74
    if q["expectancyR"]<=0: return confidence>=82
    return confidence>=72

def _sanitize_ai_items(items):
    """Normalize AI output before it reaches cache/UI; weak AI results are never trade-ready."""
    clean=[]
    for raw in items if isinstance(items,list) else []:
        if not isinstance(raw,dict): continue
        x=dict(raw)
        try: conf=max(0.0,min(100.0,float(x.get("confidence",0) or 0)))
        except Exception: conf=0.0
        direction=str(x.get("direction","حيادي") or "حيادي").strip()
        if direction not in ("شراء","بيع","حيادي"): direction="حيادي"
        x["direction"]=direction
        x["confidence"]=round(conf,1)
        ready=bool(x.get("trade_ready",x.get("tradeReady",False))) and direction in ("شراء","بيع") and conf>=75.0
        x["trade_ready"]=ready
        clean.append(x)
    return clean

def _historical_pattern_search(candles, direction, lookback=180, pattern_len=8, forward=6):
    """Search earlier price/range patterns and estimate out-of-sample follow-through."""
    try:
        n=len(candles)
        if n < pattern_len + forward + 30: return {"samples":0,"hitRate":0.0,"similarity":0.0}
        def features(seq):
            closes=[float(x["close"]) for x in seq]
            highs=[float(x["high"]) for x in seq]
            lows=[float(x["low"]) for x in seq]
            base=max(abs(closes[0]),1e-12)
            return [((closes[i]/base)-1.0)*100.0 for i in range(len(closes))] + [
                ((highs[i]-lows[i])/max(abs(closes[i]),1e-12))*100.0 for i in range(len(closes))]
        cur=features(candles[-pattern_len:])
        hits=[]
        start=max(pattern_len, n-lookback)
        end=n-forward-pattern_len
        for i in range(start,end):
            if i+forward>=n-pattern_len: continue
            past=features(candles[i-pattern_len:i])
            if len(past)!=len(cur): continue
            dist=sum((a-b)**2 for a,b in zip(cur,past))**0.5
            similarity=max(0.0,1.0-min(1.0,dist/8.0))
            if similarity<0.55: continue
            entry=float(candles[i-1]["close"])
            future=[float(x["close"]) for x in candles[i:i+forward]]
            if not future or entry<=0: continue
            move=((max(future) if direction=="شراء" else min(future))/entry-1.0)*100.0
            if direction=="بيع": move=-move
            hits.append((similarity, move>0.15))
        if not hits: return {"samples":0,"hitRate":0.0,"similarity":0.0}
        hits=sorted(hits,key=lambda x:x[0],reverse=True)[:12]
        w=sum(x[0] for x in hits)
        return {"samples":len(hits),"hitRate":round(sum(x[0] for x in hits if x[1])/w*100.0,1) if w else 0.0,
                "similarity":round(sum(x[0] for x in hits)/len(hits)*100.0,1)}
    except Exception:
        return {"samples":0,"hitRate":0.0,"similarity":0.0}

def _local_batch(candles_by_symbol,market,interval,names):
    items=[]
    for symbol,candles in candles_by_symbol.items():
        if len(candles)<24: continue
        recent=candles[-12:]; last=recent[-1]; prev=recent[-2]
        close=float(last["close"]); prev_close=float(prev["close"])
        if close<=0 or prev_close<=0: continue
        change=(close/prev_close-1.0)*100.0
        avg_range=sum(max(0.0,float(x["high"])-float(x["low"])) for x in recent[:-1])/11.0
        recent_high=max(float(x["high"]) for x in recent)
        recent_low=min(float(x["low"]) for x in recent)
        prior_high=max(float(x["high"]) for x in candles[-24:-12])
        prior_low=min(float(x["low"]) for x in candles[-24:-12])
        mid=(recent_high+recent_low)/2.0
        bullish=(change>=0.35 and close>=mid) or close>prior_high
        bearish=(change<=-0.35 and close<=mid) or close<prior_low
        direction="شراء" if bullish and not bearish else "بيع" if bearish and not bullish else "حيادي"
        research={"samples":0,"hitRate":0.0,"similarity":0.0}
        confidence=50.0
        if direction!="حيادي":
            confidence=58.0+min(22.0,abs(change)*12.0)+(6.0 if (direction=="شراء" and close>prior_high) or (direction=="بيع" and close<prior_low) else 0.0)
            n,hist=_memory_stats(market,interval,symbol,direction)
            if n>=5:
                confidence += max(-12.0,min(12.0,(hist-50.0)*0.18))
                if hist<42: confidence-=8.0
                elif hist>=65: confidence+=4.0
            # Deep historical search: compare the current movement with earlier
            # unseen historical patterns instead of trusting one headline score.
            research=_historical_pattern_search(candles,direction)
            if research["samples"]>=3:
                confidence += max(-12.0,min(12.0,(research["hitRate"]-50.0)*0.24))
                if research["hitRate"]<40: confidence-=7.0
                elif research["hitRate"]>=70: confidence+=4.0
                if research["samples"]>=6 and research["hitRate"]>=75 and research["similarity"]>=70: confidence+=5.0
                if research["samples"]>=8 and research["hitRate"]>=82 and research["similarity"]>=78: confidence+=6.0
            else:
                research={"samples":0,"hitRate":0.0,"similarity":0.0}
            # Reward alignment between the current move and the long-term regime.
            ind=_indicator_snapshot(candles)
            if direction=="شراء" and ind.get("rsi") is not None and 48<=ind["rsi"]<=72: confidence+=3.0
            if direction=="بيع" and ind.get("rsi") is not None and 28<=ind["rsi"]<=52: confidence+=3.0
            if ind.get("relVolume",0)>=1.5: confidence+=4.0
            if ind.get("relVolume",0)>=2.5: confidence+=3.0
        confidence=round(max(0.0,min(100.0,confidence)),1)
        if direction!="حيادي" and avg_range>0:
            entry=close
            risk=max(avg_range*1.5,close*0.006)
            if direction=="شراء":
                sl=entry-risk; tp1=entry+risk; tp2=entry+2*risk; tp3=entry+3*risk
            else:
                sl=entry+risk; tp1=entry-risk; tp2=entry-2*risk; tp3=entry-3*risk
            rr=3.0
            # نشر الصفقة فقط إذا اجتمعت أدلة كافية؛ لا نرفع النسبة لمجرد الشكل.
            ready=_ai_quality_gate(market,interval,confidence) and confidence>=75.0
        else:
            entry=tp1=tp2=tp3=sl=0.0; rr=0.0; ready=False
        research_score=round((confidence*0.70)+(research.get("hitRate",0.0)*0.20)+(research.get("similarity",0.0)*0.10),1)
        items.append({"symbol":symbol,"direction":direction,"confidence":confidence,"researchScore":research_score,
                      "historicalSamples":research.get("samples",0),"historicalHitRate":research.get("hitRate",0.0),
                      "patternSimilarity":research.get("similarity",0.0),"trade_ready":ready,"entry":entry,
                      "tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"rr":rr,"reason":""})
    return items

def ai_batch(candles_by_symbol,market,interval,names):
    now=time.time()
    cache_key=market+"|"+interval+"|"+",".join(sorted(candles_by_symbol.keys()))
    cached=AI_CACHE.get(cache_key)
    if cached and now-cached["at"]<AI_CACHE_TTL:
        return cached["items"]
    # Persistent cache: refreshing the page must not generate a different set of
    # trades every few seconds. Keep the last valid analysis for 5 minutes.
    try:
        c=conn()
        row=c.execute("SELECT items,updated_at FROM signal_cache WHERE market=? AND interval=?",(market,interval)).fetchone()
        c.close()
        if row and now-float(row["updated_at"])<AI_CACHE_TTL:
            items=_sanitize_ai_items(__import__("json").loads(row["items"]))
            # If the persistent cache contains only weak/old signals, force a fresh scan.
            if any(x.get("trade_ready") for x in items):
                AI_CACHE[cache_key]={"at":float(row["updated_at"]),"items":items}
                return items
    except Exception as e:
        app.logger.warning("Persistent signal cache read failed: %s",e)
    if not os.getenv("OPENAI_API_KEY","").strip():
        items=_local_batch(candles_by_symbol,market,interval,names)
    else:
        # Two-stage AI: scan every symbol locally, then spend the expensive/deep
        # model context only on the strongest candidates. This keeps 100-symbol
        # scans practical instead of sending 100*220 candles in one huge request.
        local_items=_sanitize_ai_items(_local_batch(candles_by_symbol,market,interval,names))
        ranked=[x for x in local_items if x.get("direction") in ("شراء","بيع")]
        ranked.sort(key=lambda x:(float(x.get("confidence",0) or 0),float(x.get("researchScore",0) or 0)),reverse=True)
        deep_symbols={x.get("symbol") for x in ranked[:20]}
        payload=[{"symbol":symbol,"name":names.get(symbol,symbol),"candles":candles[-220:]} for symbol,candles in candles_by_symbol.items() if symbol in deep_symbols]
        prompt="السوق: "+market+"\nالفريم: "+interval+"\nأنت محرك تحليل عميق متعدد الأدلة. هذه قائمة مرشحين قوية فقط بعد فحص أولي لكل السوق. افحص كل مرشح بعمق، وابحث داخل الشموع السابقة عن حركات مشابهة للحركة الحالية، وقارن ما حدث بعدها، ووازن النتيجة مع الذاكرة السابقة لهذا الأصل والفريم والاتجاه. لا تختلق 100%: لا تعطِ confidence=100 إلا إذا كانت الأدلة التاريخية والحالية شديدة الاتساق. لا تجعل 91% أو أي رقم مرتفع كافياً وحده. لا تستخدم RSI/MACD/EMA/SMA أو أي مؤشر تقني جاهز، ولا تعتمد على نظام نقاط برمجي. إذا وجدت صفقة واضحة أعد شراء أو بيع، وإلا حيادي. trade_ready=true فقط عند وجود أفضلية واضحة بعد فحص الحركة السابقة المشابهة. أعط researchScore من 0 إلى 100 مبنياً على قوة الأدلة، وأعد historicalSamples وhistoricalHitRate وpatternSimilarity إن أمكن. قيّم الجودة باستخدام نتائج الذاكرة السابقة، ولا تنشر إذا كانت الأفضلية التاريخية ضعيفة. اجعل RR النهائي 3.0 تقريباً. البيانات:\n"+__import__("json").dumps(payload,ensure_ascii=False,separators=(",",":"))
        try:
            result=_ai_json(prompt)
            deep_items=_sanitize_ai_items(result.get("items",[]))
            deep_by_symbol={x.get("symbol"):x for x in deep_items if x.get("symbol")}
            items=[deep_by_symbol.get(x.get("symbol"),x) for x in local_items]
        except Exception as e:
            app.logger.warning("OpenAI unavailable; using local analysis: %s",e)
            items=local_items
    items=_sanitize_ai_items(items)
    AI_CACHE[cache_key]={"at":now,"items":items}
    try:
        c=conn()
        c.execute("INSERT INTO signal_cache(market,interval,items,updated_at) VALUES(?,?,?,?) ON CONFLICT(market,interval) DO UPDATE SET items=excluded.items,updated_at=excluded.updated_at",(market,interval,__import__("json").dumps(items,ensure_ascii=False,separators=(",",":")),now))
        c.commit(); c.close()
    except Exception as e:
        app.logger.warning("Persistent signal cache write failed: %s",e)
    return items

def _sma_values(values, period):
    if len(values)<period:return None
    return sum(values[-period:])/period

def _ema_values(values, period):
    if len(values)<period:return None
    k=2.0/(period+1.0); ema=sum(values[:period])/period
    for v in values[period:]: ema=(v*k)+(ema*(1-k))
    return ema

def _rsi_values(closes, period=14):
    if len(closes)<=period:return None
    gains=[];losses=[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; gains.append(max(d,0.0)); losses.append(max(-d,0.0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=((ag*(period-1))+gains[i])/period; al=((al*(period-1))+losses[i])/period
    if al==0:return 100.0
    return 100.0-(100.0/(1.0+(ag/al)))

def _atr_values(candles, period=14):
    if len(candles)<=period:return None
    trs=[]
    for i in range(1,len(candles)):
        h=float(candles[i]["high"]); l=float(candles[i]["low"]); pc=float(candles[i-1]["close"])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs[-period:])/period if len(trs)>=period else None

def _indicator_snapshot(candles):
    closes=[float(x["close"]) for x in candles if x.get("close") is not None]
    volumes=[float(x.get("volume",0) or 0) for x in candles]
    rsi=_rsi_values(closes,14); ema20=_ema_values(closes,20); ema50=_ema_values(closes,50); ema200=_ema_values(closes,200)
    sma20=_sma_values(closes,20); sma50=_sma_values(closes,50); sma200=_sma_values(closes,200)
    ema12=_ema_values(closes,12); ema26=_ema_values(closes,26)
    macd=(ema12-ema26) if ema12 is not None and ema26 is not None else None
    prev_rsi=_rsi_values(closes[:-1],14) if len(closes)>15 else None
    stoch_rsi=None
    if len(closes)>=30:
        rsis=[]
        for end in range(max(15,len(closes)-14),len(closes)+1):
            v=_rsi_values(closes[:end],14)
            if v is not None:rsis.append(v)
        if rsis:
            lo=min(rsis[-14:]); hi=max(rsis[-14:]); stoch_rsi=100.0 if hi==lo else ((rsi-lo)/(hi-lo))*100.0
    atr=_atr_values(candles,14)
    last=closes[-1] if closes else 0.0
    prev=closes[-2] if len(closes)>1 else last
    change=((last/prev)-1)*100 if prev else 0.0
    change5=((last/closes[-6])-1)*100 if len(closes)>5 and closes[-6] else 0.0
    change20=((last/closes[-21])-1)*100 if len(closes)>20 and closes[-21] else 0.0
    avgvol=sum(volumes[-20:-1])/max(1,len(volumes[-20:-1])) if len(volumes)>1 else 0.0
    relvol=(volumes[-1]/avgvol) if avgvol else 0.0
    return {"rsi":round(rsi,2) if rsi is not None else None,"prevRsi":round(prev_rsi,2) if prev_rsi is not None else None,"stochRsi":round(stoch_rsi,2) if stoch_rsi is not None else None,"macd":round(macd,8) if macd is not None else None,"ema20":ema20,"ema50":ema50,"ema200":ema200,"sma20":sma20,"sma50":sma50,"sma200":sma200,"atr":atr,"relVolume":round(relvol,2),"change":round(change,2),"change5":round(change5,2),"change20":round(change20,2),"price":last}

def _decorate_ai(item,market,interval,name,candles=None):
    d=item.get("direction","حيادي")
    try: conf=round(max(0.0,min(100.0,float(item.get("confidence",0) or 0))),1)
    except Exception: conf=0.0
    candles=candles or []
    last=candles[-1] if candles else {}
    prev=candles[-2] if len(candles)>1 else {}
    close=float(last.get("close",item.get("entry",0)) or 0)
    prev_close=float(prev.get("close",close) or close)
    change=((close/prev_close)-1)*100 if prev_close else 0
    volume=float(last.get("volume",0) or 0)
    return {"symbol":item.get("symbol",""),"displayName":name or item.get("symbol",""),"market":market,"interval":interval,
    "signal":"شراء قوي" if d=="شراء" and conf>=80 else "بيع قوي" if d=="بيع" and conf>=80 else d,
    "direction":d,"tradeReady":bool(item.get("trade_ready",False)) and d!="حيادي" and conf>=75.0,
    "confidence":conf,"price":close,"entry":float(item.get("entry",close) or close),
    "tp1":float(item.get("tp1",0) or 0),"tp2":float(item.get("tp2",0) or 0),"tp3":float(item.get("tp3",0) or 0),
    "sl":float(item.get("sl",0) or 0),"rr":float(item.get("rr",0) or 0),"reason":item.get("reason",""),
    "change":round(change,2),"volume":volume,"high":float(last.get("high",0) or 0),"low":float(last.get("low",0) or 0),
    "indicators":_indicator_snapshot(candles) if candles else {},
    "memory":_memory_profile(market,interval,item.get("symbol",""),d) if d in ("شراء","بيع") else {"samples":0,"wins":0,"winRate":0,"avgConfidence":0},
    "ai":True,"updatedAt":datetime.now(timezone.utc).isoformat()}

SAUDI_UNIVERSE=[
 ("2222.SR","أرامكو السعودية"),("1120.SR","الراجحي"),("2010.SR","سابك"),("7010.SR","الاتصالات السعودية"),("1180.SR","الأهلي السعودي"),("1050.SR","الإنماء"),("1060.SR","ساب"),("1080.SR","العربي الوطني"),("1010.SR","الرياض"),("1140.SR","البلاد"),("1090.SR","بنك الرياض"),("1211.SR","معادن"),("2082.SR","أكوا باور"),("2280.SR","المراعي"),("2310.SR","سبكيم"),("2290.SR","ينساب"),("4001.SR","أسواق العثيم"),("4002.SR","المواساة"),("4003.SR","إكسترا"),("4004.SR","دله الصحية"),("4007.SR","الحمادي"),("4013.SR","سليمان الحبيب"),("4030.SR","البحري"),("4040.SR","جرير"),("4050.SR","ساسكو"),("4200.SR","الدريس"),("4261.SR","ذيب"),("4300.SR","دار الأركان"),("4321.SR","مياهنا"),("4322.SR","رتال"),("5110.SR","الكابلات السعودية")
]

def _yahoo_universe(market):
    static=dict(MARKETS.get(market,[]))
    if market=="saudi": return SAUDI_UNIVERSE
    region="us" if market=="usmarket" else None
    if not region:return list(static.items())
    # Avoid Yahoo's screener endpoint by default: many hosting IPs receive 401,
    # and the repeated discovery adds load without improving the static fallback.
    if os.getenv("USE_YAHOO_SCREENER","0").strip().lower() not in ("1","true","yes"):
        return list(static.items())
    try:
        url="https://query1.finance.yahoo.com/v1/finance/screener"
        params={"formatted":"false","lang":"en-US","region":"US","corsDomain":"finance.yahoo.com"}
        payload={"offset":0,"size":250,"sortType":"DESC","sortField":"dayvolume","quoteType":"EQUITY","query":{"operator":"and","operands":[{"operator":"eq","operands":["region",region]}]},"userId":"","userIdType":"guid"}
        found={}
        for offset in range(0,2500,250):
            payload["offset"]=offset
            r=H.post(url,params=params,json=payload,timeout=20);r.raise_for_status()
            quotes=((r.json().get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
            if not quotes:break
            for q in quotes:
                s=str(q.get("symbol","")).strip()
                if s:found[s]=str(q.get("shortName") or q.get("longName") or s)
            if len(quotes)<250:break
        if found:return list(found.items())
    except Exception as e:app.logger.warning("Yahoo universe discovery failed %s: %s",market,e)
    return list(static.items())

def _scan_yahoo_symbols(symbols,market,interval,limit):
    universe=_yahoo_universe(market) if market in ("saudi","usmarket") else list(symbols)
    yi={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d","1W":"1wk","1M":"1mo"}.get(interval,"1d")
    rg="5d" if yi=="5m" else "1mo" if yi in ("15m","30m") else "5y" if yi=="1wk" else "10y" if yi=="1mo" else "1y"
    max_symbols=max(20,min(int(os.getenv("MARKET_SCAN_SYMBOLS","50")),100))
    universe=universe[:max_symbols];candles={};names=dict(universe)
    with ThreadPoolExecutor(max_workers=min(6,len(universe) or 1)) as ex:
        fs={ex.submit(yahoo,s,yi,rg):s for s,n in universe}
        for f in as_completed(fs):
            s=fs[f]
            try:
                cc=f.result()
                if len(cc)>=12:candles[s]=cc
            except Exception as e:app.logger.warning("AI data failed %s: %s",s,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol")),candles.get(x.get("symbol"),[])) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

_BINANCE_INTERVALS = {
    "5m":"5m","15m":"15m","30m":"30m",
    "1H":"1h","2H":"2h","4H":"4h","6H":"6h","8H":"8h","12H":"12h",
    "1D":"1d","3D":"3d","1W":"1w","1M":"1M",
    "1m":"1m","3m":"3m","1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h",
    "1d":"1d","3d":"3d","1w":"1w"
}

def _binance_interval(interval):
    key=str(interval or "15m").strip()
    # لا نستخدم lower() هنا لأن 1M في Binance = شهر، بينما 1m = دقيقة.
    api_interval=_BINANCE_INTERVALS.get(key)
    if not api_interval:
        raise ValueError(f"Unsupported Binance interval: {key}")
    return api_interval

def _binance_public_get(endpoint,params=None,timeout=12,prefer_data_api=False):
    """Public Binance request with 429/5xx retry and the public data-api fallback."""
    hosts=[]
    if prefer_data_api:
        hosts=["https://data-api.binance.vision","https://api.binance.com"]
    else:
        hosts=["https://api.binance.com","https://data-api.binance.vision"]
    last=None
    for host in hosts:
        for attempt in range(3):
            try:
                r=H.get(host+endpoint,params=params,timeout=timeout)
                if r.status_code in (418,429,500,502,503,504):
                    wait=min(2.5,0.35*(2**attempt))
                    try: wait=max(wait,min(3.0,float(r.headers.get("Retry-After","0") or 0)))
                    except Exception: pass
                    time.sleep(wait)
                    last=RuntimeError(f"Binance HTTP {r.status_code}")
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last=e
                if attempt<2: time.sleep(min(1.5,0.25*(2**attempt)))
    raise RuntimeError(str(last) if last else "Binance unavailable")

def binance_exchange_symbols(market):
    endpoint="/api/v3/exchangeInfo" if market=="crypto" else "/fapi/v1/exchangeInfo"
    data=_binance_public_get(endpoint,timeout=15)
    symbols=[]
    for s in data.get("symbols",[]):
        symbol=str(s.get("symbol",""))
        if (
            s.get("status")=="TRADING"
            and s.get("quoteAsset")=="USDT"
            and symbol.isascii()
            and symbol.isalnum()
        ):
            symbols.append(symbol)
    return symbols

def binance_candles(symbol,interval,market):
    api_interval=_binance_interval(interval)
    endpoint="/api/v3/klines" if market=="crypto" else "/fapi/v1/klines"
    data=_binance_public_get(
        endpoint,
        params={"symbol":symbol,"interval":api_interval,"limit":250},
        timeout=12,
        prefer_data_api=True,
    )
    return [
        {"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),
         "low":float(x[3]),"close":float(x[4]),"volume":float(x[5])}
        for x in data
    ]

def _scan_binance(market,interval,limit):
    symbols=binance_exchange_symbols(market)
    endpoint="/api/v3/ticker/24hr" if market=="crypto" else "/fapi/v1/ticker/24hr"
    tickers=_binance_public_get(endpoint,timeout=15)
    volumes={x.get("symbol"):float(x.get("quoteVolume",0) or 0) for x in tickers}
    symbols=sorted(symbols,key=lambda s:volumes.get(s,0),reverse=True)
    max_symbols=max(20,min(int(os.getenv("BINANCE_SCAN_SYMBOLS","100")),100));symbols=symbols[:max_symbols]
    candles={};names={s:s for s in symbols}
    # Keep concurrency below Binance's burst limit; each kline request is retried
    # automatically and the public data-api endpoint is preferred.
    with ThreadPoolExecutor(max_workers=min(5,len(symbols) or 1)) as ex:
        fs={ex.submit(binance_candles,s,interval,market):s for s in symbols}
        for f in as_completed(fs):
            s=fs[f]
            try:
                cc=f.result()
                if len(cc)>=12:candles[s]=cc
            except Exception as e:app.logger.warning("Binance data failed %s: %s",s,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol")),candles.get(x.get("symbol"),[])) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

def _scan_okx(market,interval,limit):
    bar={"5m":"5m","15m":"15m","30m":"30m","1H":"1H","4H":"4H","1D":"1D","1W":"1W","1M":"1M"}.get(interval,"15m"); typ="SPOT" if market=="crypto" else "SWAP"; suffix="-USDT" if market=="crypto" else "-USDT-SWAP"
    r=H.get("https://www.okx.com/api/v5/market/tickers",params={"instType":typ},timeout=12);r.raise_for_status()
    items=[x for x in r.json().get("data",[]) if x.get("instId","").endswith(suffix)]; items=sorted(items,key=lambda x:float(x.get("volCcy24h",0) or 0),reverse=True)[:limit]
    candles={}; names={x["instId"]:x["instId"] for x in items}
    with ThreadPoolExecutor(max_workers=min(6,len(items) or 1)) as ex:
        fs={ex.submit(okx,x["instId"],bar):x["instId"] for x in items}
        for f in as_completed(fs):
            sym=fs[f]
            try:
                c=f.result()
                if len(c)>=12:candles[sym]=c
            except Exception as e:app.logger.warning("AI data failed %s: %s",sym,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol"))) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

MONTH_CODES={3:"H",6:"M",9:"U",12:"Z",1:"F",2:"G",4:"J",5:"K",7:"N",8:"Q",10:"V",11:"X"}
MONTH_NAMES={1:"يناير",2:"فبراير",3:"مارس",4:"أبريل",5:"مايو",6:"يونيو",7:"يوليو",8:"أغسطس",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}

def _business_days_before(dt,n):
    d=dt; left=n
    while left>0:
        d-=timedelta(days=1)
        if d.weekday()<5:left-=1
    return d

def _third_friday(year,month):
    d=datetime(year,month,1,tzinfo=timezone.utc)
    while d.weekday()!=4:d+=timedelta(days=1)
    return d+timedelta(days=14)

def _next_quarter_after(dt):
    for year in range(dt.year,dt.year+2):
        for month in (3,6,9,12):
            if (year,month)>(dt.year,dt.month):return year,month
    return dt.year+1,3

def _quarter_contracts(now):
    cy,cm=_next_quarter_after(now); exp=_third_friday(cy,cm); roll=exp-timedelta(days=4)
    if now.date()>=roll.date():
        current=(cy,cm); current_exp=exp; current_roll=roll; ny,nm=_next_quarter_after(exp); next_exp=_third_friday(ny,nm); next_roll=next_exp-timedelta(days=4); nxt=(ny,nm)
    else:
        py,pm=cy,cm; prev_month={3:12,6:3,9:6,12:9}[pm]; prev_year=py-1 if pm==3 else py; current=(prev_year,prev_month); current_exp=_third_friday(prev_year,prev_month); current_roll=current_exp-timedelta(days=4); nxt=(cy,cm); next_exp=exp; next_roll=roll
    return current,current_roll,current_exp,nxt,next_roll,next_exp

def _monthly_contract(base,now,rule):
    y,m=now.year,now.month
    for _ in range(15):
        if rule=="CL":
            py,pm=y,m-1
            if pm==0:py,pm=y-1,12
            anchor=datetime(py,pm,25,tzinfo=timezone.utc); term=_business_days_before(anchor,3)
            if term.date()>=now.date():cur=(y,m);cur_exp=term;break
        elif rule=="GC":
            last=datetime(y,m+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m<12 else datetime(y,12,31,tzinfo=timezone.utc); business=[last]
            while len([x for x in business if x.weekday()<5])<3:business.append(business[-1]-timedelta(days=1))
            bs=sorted([x for x in business if x.weekday()<5]);term=bs[0]
            if term.date()>=now.date():cur=(y,m);cur_exp=term;break
        elif rule=="SI":
            last=datetime(y,m+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m<12 else datetime(y,12,31,tzinfo=timezone.utc); d=last;count=0;term=None
            while d>=last-timedelta(days=10):
                if d.weekday()<5:
                    count+=1
                    if count==3:term=d;break
                d-=timedelta(days=1)
            if term and term.date()>=now.date():cur=(y,m);cur_exp=term;break
        m+=1
        if m>12:y,m=y+1,1
    else:cur=(now.year,now.month);cur_exp=now
    if rule=="SI":
        allowed=(3,5,7,9,12);candidates=[];yy,mm=cur
        for k in range(1,15):
            nm=mm+k;ny=yy+(nm-1)//12;nm=((nm-1)%12)+1
            if nm in allowed:candidates.append((ny,nm))
        nxt=candidates[0]
    else:
        ny,nm=cur[0],cur[1]+1
        if nm>12:ny,nm=ny+1,1
        nxt=(ny,nm)
    if rule=="CL":
        py,nm=nxt[0],nxt[1]-1
        if nm==0:py,nm=py-1,12
        anchor=datetime(py,nm,25,tzinfo=timezone.utc);next_exp=_business_days_before(anchor,3)
    elif rule in ("GC","SI"):
        y2,m2=nxt;last=datetime(y2,m2+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m2<12 else datetime(y2,12,31,tzinfo=timezone.utc);d=last;count=0;next_exp=None
        while d>=last-timedelta(days=10):
            if d.weekday()<5:
                count+=1
                if count==3:next_exp=d;break
            d-=timedelta(days=1)
    roll=_business_days_before(cur_exp,5)
    return cur,roll,cur_exp,nxt,_business_days_before(next_exp,5),next_exp

def _contract_row(name,sym,rule,now):
    if rule=="quarter":cur,roll,exp,nxt,nroll,nexp=_quarter_contracts(now)
    else:cur,roll,exp,nxt,nroll,nexp=_monthly_contract(sym,now,rule)
    def label(pair):
        yy,mm=pair;return f"{sym}{MONTH_CODES[mm]}{str(yy)[-2:]} — {MONTH_NAMES[mm]} {yy}"
    return {"name":name,"symbol":sym,"current":label(cur),"next":label(nxt),"currentCode":sym+MONTH_CODES[cur[1]]+str(cur[0])[-2:],"nextCode":sym+MONTH_CODES[nxt[1]]+str(nxt[0])[-2:],"roll":roll.strftime("%Y-%m-%d"),"expiry":exp.strftime("%Y-%m-%d"),"nextRoll":nroll.strftime("%Y-%m-%d"),"nextExpiry":nexp.strftime("%Y-%m-%d"),"rollNote":"تاريخ Roll مخصص للمؤشرات حسب جدول CME؛ للسلع هو تاريخ آلي قبل آخر تداول."}

CONTRACT_SPECS=[("S&P 500 E-mini","ES","quarter"),("Nasdaq 100 E-mini","NQ","quarter"),("Dow Jones E-mini","YM","quarter"),("Russell 2000 E-mini","RTY","quarter"),("WTI النفط","CL","CL"),("الذهب","GC","GC"),("الفضة","SI","SI")]

@app.get("/api/contracts/calendar")
def contracts_calendar():
    now=datetime.now(timezone.utc);rows=[_contract_row(*x,now) for x in CONTRACT_SPECS]
    return ok(contracts=rows,source="CME rules + automatic calculation",updatedAt=now.isoformat())

def _telegram_send(text,signal_key=None):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat_id=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat_id:return False
    if signal_key:
        c=conn();row=c.execute("SELECT 1 FROM telegram_sent WHERE signal_key=?",(signal_key,)).fetchone();c.close()
        if row:return False
    try:
        r=H.post("https://api.telegram.org/bot"+token+"/sendMessage",json={"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15)
        r.raise_for_status();data=r.json()
        if not data.get("ok"):raise RuntimeError("Telegram API rejected message")
        if signal_key:
            mid=((data.get("result") or {}).get("message_id"))
            c=conn();c.execute("INSERT OR IGNORE INTO telegram_sent(signal_key,sent_at,message_id) VALUES(?,?,?)",(signal_key,datetime.now(timezone.utc).isoformat(),mid));c.commit();c.close()
        return True
    except Exception as e:
        app.logger.warning("Telegram send failed: %s",e);return False

def _telegram_opportunities(rows):
    sent=0
    for x in rows:
        try:
            market=x.get("market","");interval=x.get("interval","");symbol=x.get("symbol","");direction=x.get("direction","")
            entry=float(x.get("entry",0) or 0);tp1=float(x.get("tp1",0) or 0);tp2=float(x.get("tp2",0) or 0);tp3=float(x.get("tp3",0) or 0);sl=float(x.get("sl",0) or 0);conf=float(x.get("confidence",0) or 0)
            if not symbol or direction not in ("شراء","بيع") or entry<=0:continue
            key=f"{market}|{interval}|{symbol}|{direction}|{entry:.8f}"
            side="LONG" if direction=="شراء" else "SHORT"
            name=str(x.get("displayName") or symbol)
            msg=(f"{name} | {side}\n"
                 f"ENTRY: {entry:.8f}\n"
                 f"TP1: {tp1:.8f}\n"
                 f"TP2: {tp2:.8f}\n"
                 f"TP3: {tp3:.8f}\n"
                 f"SL: {sl:.8f}\n"
                 f"CONFIDENCE: {conf:.1f}%")
            if _telegram_send(msg,key):sent+=1
        except Exception as e:
            app.logger.warning("Telegram opportunity formatting failed: %s",e)
    return sent

def _strong_signal_items(items):
    """Keep only actionable strong signals and rank them by strength."""
    strong=[]
    for x in items if isinstance(items,list) else []:
        try:
            conf=float(x.get("confidence",0) or 0)
            ready=bool(x.get("tradeReady",x.get("trade_ready",False)))
        except Exception:
            conf=0.0; ready=False
        if ready and x.get("direction") in ("شراء","بيع") and conf>=75.0:
            y=dict(x)
            y["strength"]=round(conf,1)
            strong.append(y)
    return sorted(strong,key=lambda x:(float(x.get("strength",0) or 0),
                                       float(x.get("rr",0) or 0),
                                       float(x.get("researchScore",0) or 0)),reverse=True)

def _load_strong_signal_cache(key,now):
    try:
        market,interval=key.split("|",1)
        c=conn()
        row=c.execute("SELECT items,updated_at FROM strong_signal_cache WHERE market=? AND interval=?",(market,interval)).fetchone()
        c.close()
        if not row:return None
        updated=float(row["updated_at"] or 0)
        if now-updated>=900:return None
        import json
        items=json.loads(row["items"])
        return _strong_signal_items(items)
    except Exception as e:
        app.logger.warning("Strong signal cache read failed %s: %s",key,e)
        return None

def _save_strong_signal_cache(key,items,now):
    try:
        market,interval=key.split("|",1)
        import json
        payload=json.dumps(_strong_signal_items(items),ensure_ascii=False,separators=(",",":"))
        c=conn()
        c.execute("INSERT INTO strong_signal_cache(market,interval,items,updated_at) VALUES(?,?,?,?) ON CONFLICT(market,interval) DO UPDATE SET items=excluded.items,updated_at=excluded.updated_at",(market,interval,payload,now))
        c.commit();c.close()
    except Exception as e:
        app.logger.warning("Strong signal cache write failed %s: %s",key,e)

def _load_persistent_scan_cache(key,now):
    try:
        market,interval=key.split("|",1)
        c=conn()
        row=c.execute("SELECT items,updated_at FROM signal_cache WHERE market=? AND interval=?",(market,interval)).fetchone()
        c.close()
        if not row:return None
        updated=float(row["updated_at"] or 0)
        if now-updated>=SCAN_CACHE_TTL:return None
        import json
        items=json.loads(row["items"])
        return items if isinstance(items,list) else None
    except Exception as e:
        app.logger.warning("Persistent scan cache read failed %s: %s",key,e)
        return None

def _save_persistent_scan_cache(key,items,now):
    try:
        market,interval=key.split("|",1)
        import json
        payload=json.dumps(items,ensure_ascii=False,separators=(",",":"))
        c=conn()
        c.execute("INSERT INTO signal_cache(market,interval,items,updated_at) VALUES(?,?,?,?) ON CONFLICT(market,interval) DO UPDATE SET items=excluded.items,updated_at=excluded.updated_at",(market,interval,payload,now))
        c.commit();c.close()
    except Exception as e:
        app.logger.warning("Persistent scan cache write failed %s: %s",key,e)

def scan(market,interval):
    if interval not in ("5m","15m","30m","1H","4H","1D","1W","1M"):raise ValueError("الفريم غير مدعوم")
    if market not in ("crypto","futures","contracts","saudi","usmarket","forex"):raise ValueError("السوق غير معروف")
    key=market+"|"+interval
    now=time.time()
    with SCAN_CACHE_LOCK:
        cached=SCAN_CACHE.get(key)
        if cached and now-cached["at"]<SCAN_CACHE_TTL:
            return cached["items"]

    # Coalesce concurrent cold-cache requests from the homepage.
    owner=False
    with SCAN_INFLIGHT_LOCK:
        event=SCAN_INFLIGHT.get(key)
        if event is None:
            event=threading.Event()
            SCAN_INFLIGHT[key]=event
            owner=True
    if not owner:
        event.wait(timeout=90)
        with SCAN_CACHE_LOCK:
            cached=SCAN_CACHE.get(key)
            if cached and time.time()-cached["at"]<SCAN_CACHE_TTL:
                return cached["items"]
        with SCAN_INFLIGHT_LOCK:
            if SCAN_INFLIGHT.get(key) is event:
                SCAN_INFLIGHT.pop(key,None)
        return scan(market,interval)

    try:
        now=time.time()
        # Fresh market scan every 3 minutes. The persistent DB snapshot is kept
        # independently per market + timeframe and refreshed every 15 minutes.
        persistent=_load_strong_signal_cache(key,now)

        if market=="crypto":
            try:
                items=_scan_binance(market,interval,100)
            except Exception as e:
                app.logger.warning("Binance spot scan failed; using OKX fallback: %s",e)
                try:
                    items=_scan_okx(market,interval,100)
                except Exception as e2:
                    app.logger.warning("OKX spot fallback failed: %s",e2)
                    items=[]
        elif market=="futures":
            try:
                items=_scan_binance(market,interval,100)
            except Exception as e:
                app.logger.warning("Binance futures scan failed; using OKX fallback: %s",e)
                try:
                    items=_scan_okx(market,interval,100)
                except Exception as e2:
                    app.logger.warning("OKX futures fallback failed: %s",e2)
                    items=[]
        elif market=="contracts":
            try:
                items=_scan_yahoo_symbols(MARKETS["contracts"],market,interval,100)
            except Exception as e:
                app.logger.warning("Contracts scan failed: %s",e)
                items=[]
        else:
            try:
                items=_scan_yahoo_symbols(MARKETS[market],market,interval,100)
            except Exception as e:
                app.logger.warning("%s scan failed: %s",market,e)
                items=[]

        # Store only strong/actionable opportunities, already ranked by strength.
        saved_at=time.time()
        items=_strong_signal_items(items)
        # Register only the fresh scan; cached fallback signals must not create duplicates.
        _register_trade_candidates(items)

        # إذا ما طلع شيء قوي في الفحص الحالي، لا نخلي الفريم يختفي.
        # استخدم آخر لقطة محفوظة لهذا السوق + الفريم كشبكة أمان.
        if not items and persistent:
            items=persistent
            saved_at=time.time()

        with SCAN_CACHE_LOCK:
            SCAN_CACHE[key]={"at":saved_at,"items":items}
        # Persist only once per 15-minute cycle for this exact market/timeframe.
        if persistent is None:
            _save_strong_signal_cache(key,items,saved_at)
        return items
    finally:
        with SCAN_INFLIGHT_LOCK:
            event=SCAN_INFLIGHT.pop(key,None)
            if event is not None:
                event.set()

def fetch_news_feed(label,query):
 sources=[("https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":query,"hl":"ar","gl":"SA","ceid":"SA:ar"})),("https://www.bing.com/news/search?"+urllib.parse.urlencode({"q":query,"format":"rss","setlang":"ar-SA"}))]
 for url in sources:
  try:
   r=H.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/rss+xml, application/xml, text/xml, */*"});r.raise_for_status();root=ET.fromstring(r.content);items=[]
   for item in root.findall("./channel/item")[:10]:
    title=html.unescape((item.findtext("title") or "").strip());link=_safe_external_url(item.findtext("link") or "");pub=(item.findtext("pubDate") or "").strip();source=html.unescape((item.findtext("source") or "").strip()) or label;desc=html.unescape((item.findtext("description") or "").strip())
    if title and link:items.append({"title":title,"link":link,"published":pub,"source":source,"category":label,"description":desc})
   if items:return items
  except Exception as e:app.logger.warning("News source failed for %s: %s",label,e)
 fallback_urls={"🇸🇦 السعودية":"https://sa.investing.com/markets/saudi-arabia","🇺🇸 الأسواق الأمريكية":"https://sa.investing.com/markets/united-states","₿ العملات الرقمية":"https://sa.investing.com/news/cryptocurrency-news","🛢️ النفط والذهب":"https://sa.investing.com/commodities-news","🌍 الاقتصاد العالمي":"https://sa.investing.com/news/economy"}
 link=_safe_external_url(fallback_urls.get(label,"https://sa.investing.com/"));clean_label=label.split(" ",1)[1] if " " in label else label
 return [{"title":"أحدث أخبار "+clean_label,"link":link,"published":datetime.now(timezone.utc).isoformat(),"source":"مصدر الأخبار","category":label,"description":"تعذر جلب العناوين المباشرة حالياً؛ افتح المصدر لمتابعة آخر التحديثات."}]

@app.get("/api/live-news")
def live_news():
 global NEWS_CACHE
 now=time.time()
 if now-NEWS_CACHE["at"]<900 and NEWS_CACHE["items"]:return ok(news=NEWS_CACHE["items"],updatedAt=datetime.now(timezone.utc).isoformat())
 with ThreadPoolExecutor(max_workers=3) as ex:
  fs=[ex.submit(fetch_news_feed,*q) for q in NEWS_QUERIES];items=[]
  for f in fs:
   try:items.extend(f.result())
   except:pass
 seen=set();clean=[]
 for x in items:
  key=x["link"]
  if key in seen:continue
  seen.add(key);clean.append(x)
 clean.sort(key=lambda x:x.get("published",""),reverse=True);NEWS_CACHE={"at":now,"items":clean[:30]}
 return ok(news=clean[:30],updatedAt=datetime.now(timezone.utc).isoformat())

@app.get("/")
def home():return render_template("index.html",page_id="dashboard",page_title="المضارب ذكي")
HOME_CACHE={"at":0,"data":None};HOME_CACHE_TTL=900

def _home_cached_rows(market, interval):
    """Homepage must stay fast: read already-scanned data only; never start a cold market scan."""
    key=market+"|"+interval
    now=time.time()
    with SCAN_CACHE_LOCK:
        item=SCAN_CACHE.get(key)
        if item and isinstance(item.get("items"),list):
            return item["items"]
    # Persistent cache may be slightly older than the normal scan TTL; it is still
    # preferable to blocking the homepage on multiple external market providers.
    try:
        c=conn()
        row=c.execute("SELECT items,updated_at FROM strong_signal_cache WHERE market=? AND interval=?",(market,interval)).fetchone()
        c.close()
        if row and row["items"] and now-float(row["updated_at"] or 0)<900:
            import json
            data=_strong_signal_items(json.loads(row["items"]))
            with SCAN_CACHE_LOCK:
                SCAN_CACHE[key]={"at":now,"items":data}
            return data
    except Exception as e:
        app.logger.warning("Homepage cache read failed %s %s: %s",market,interval,e)
    return []

@app.get("/api/home/opportunities")
def home_opportunities():
    """Fast homepage response; detailed scans happen only in market pages/background refresh."""
    try:
        configs=[("crypto","15m"),("futures","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]
        rows=[x for market,interval in configs for x in _home_cached_rows(market,interval)]
        ready=_strong_signal_items(rows)
        top=ready[:5]
        return ok(opportunities=top,updatedAt=datetime.now(timezone.utc).isoformat())
    except Exception:
        app.logger.exception("home opportunities endpoint failed")
        return fail("تعذر قراءة الفرص المخزنة حالياً",502)

@app.get("/api/home/overview")
def home_overview():
 global HOME_CACHE
 try:
  now=time.time()
  if HOME_CACHE["data"] is not None and now-HOME_CACHE["at"]<HOME_CACHE_TTL:
   return ok(markets=HOME_CACHE["data"],updatedAt=datetime.now(timezone.utc).isoformat())
  configs=[("crypto","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]
  data=[]
  for market,interval in configs:
   rows=_home_cached_rows(market,interval)
   up=sum(1 for x in rows if x.get("direction")=="شراء")
   down=sum(1 for x in rows if x.get("direction")=="بيع")
   neutral=sum(1 for x in rows if x.get("direction")=="حيادي")
   eligible=[x for x in rows if x.get("tradeReady") and x.get("direction") in ("شراء","بيع") and float(x.get("confidence",0) or 0)>=75.0]
   top=max(eligible,key=lambda x:float(x.get("confidence",0) or 0)) if eligible else (rows[0] if rows else None)
   data.append({"market":market,"interval":interval,"total":len(rows),"up":up,"down":down,"neutral":neutral,"top":(top.get("displayName") or top.get("symbol")) if top else "لا توجد","confidence":top.get("confidence",0) if top else 0})
  HOME_CACHE={"at":now,"data":data}
  return ok(markets=data,updatedAt=datetime.now(timezone.utc).isoformat())
 except Exception:
  app.logger.exception("home overview failed");return fail("تعذر قراءة ملخص الأسواق حالياً",502)

SEO_MARKETS={
 "crypto":{"title":"تحليل العملات الرقمية اليوم","description":"تحليل العملات الرقمية والفرص الحالية على أزواج USDT مع بيانات السوق والفريمات المتاحة.","intro":"هذا القسم يعرض قراءة لحظية لبيانات العملات الرقمية ويُظهر فقط الفرص التي تستوفي شروط التحليل الحالية.","interval":"15m"},
 "futures":{"title":"تحليل كريبتو فيوتشر اليوم","description":"تحليل سوق عقود العملات الرقمية الآجلة والفرص الحالية مع ENTRY وTP وSL وCONFIDENCE.","intro":"تُعرض هنا إشارات عقود العملات الرقمية الآجلة بناءً على بيانات السوق الحالية، مع مستويات الدخول والأهداف ووقف الخسارة.","interval":"15m"},
 "contracts":{"title":"تحليل العقود الآجلة الأمريكية","description":"تحليل S&P 500 وNasdaq وDow Jones والسلع والعقود الآجلة المتاحة في الموقع.","intro":"صفحة تجمع تحليلات العقود الآجلة المتاحة مثل المؤشرات الرئيسية والذهب والنفط، مع تحديثات السوق الحالية.","interval":"15m"},
 "saudi":{"title":"تحليل السوق السعودي اليوم","description":"تحليل الأسهم السعودية وسوق تداول مع قراءة الاتجاه والفرص المتاحة عند توفر البيانات.","intro":"هذا القسم مخصص للسوق السعودي ويعرض إشارات التحليل والاتجاهات من بيانات السوق المتاحة.","interval":"1D"},
 "usmarket":{"title":"تحليل الأسهم الأمريكية اليوم","description":"تحليل الأسواق والأسهم الأمريكية والفرص الحالية مع مستويات الدخول والأهداف ووقف الخسارة عند توفرها.","intro":"صفحة تحليل للأسواق الأمريكية تعرض الفرص التي تستوفي شروط النظام من بيانات السوق الحالية.","interval":"1D"},
 "forex":{"title":"تحليل الفوركس والذهب اليوم","description":"تحليل أزواج الفوركس والذهب والفضة مع الاتجاه والفرص الحالية عند توفر بيانات السوق.","intro":"قسم الفوركس والسلع يعرض تحليلات أزواج العملات والذهب والفضة مع مستويات الصفقة عند توفر إشارة قابلة للتنفيذ.","interval":"1H"}
}
@app.get("/robots.txt")
def robots_txt():
    return "User-agent: *\nAllow: /\nAllow: /analysis/\nDisallow: /admin\nDisallow: /api/\nSitemap: "+PUBLIC_BASE_URL+"/sitemap.xml\n",200,{"Content-Type":"text/plain; charset=utf-8"}

@app.get("/sitemap.xml")
def sitemap_xml():
    host=PUBLIC_BASE_URL
    paths=["/","/blog","/spot","/futures","/contracts","/scanner","/saudi","/usmarket","/forex","/news","/analysis/crypto","/analysis/futures","/analysis/contracts","/analysis/saudi","/analysis/usmarket","/analysis/forex","/subscription"]
    try:
        c=conn()
        blog_rows=c.execute("SELECT slug FROM blog_posts WHERE published=1 ORDER BY id DESC LIMIT 100").fetchall()
        c.close()
        paths.extend("/blog/"+str(row["slug"]).strip("/") for row in blog_rows if row["slug"])
    except Exception:
        pass
    now=datetime.now(timezone.utc).date().isoformat()
    urls="".join("<url><loc>"+host+p+"</loc><lastmod>"+now+"</lastmod></url>" for p in paths)
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"+urls+"</urlset>",200,{"Content-Type":"application/xml; charset=utf-8"}

@app.get("/analysis/<market>")
def market_analysis_page(market):
    cfg=SEO_MARKETS.get(market)
    if not cfg:return ("غير موجود",404)
    return render_template("market_seo.html",page_id="analysis-"+market,page_title=cfg["title"],market_title=cfg["title"],market_description=cfg["description"],market_intro=cfg["intro"],market_key=market,market_interval=cfg["interval"],meta_description=cfg["description"],canonical_url=PUBLIC_BASE_URL+"/analysis/"+market)

@app.get("/<page>")
def pages(page):
 allowed={"spot":"spot","futures":"futures","contracts":"contracts","scanner":"scanner","saudi":"saudi","usmarket":"usmarket","forex":"forex","news":"news","subscription":"subscription","login":"login","register":"register","admin":"admin","trades":"trades"}
 if page in allowed:return render_template(allowed[page]+".html",page_id=page,page_title=page)
 return ("غير موجود",404)

@app.get("/api/ai/signals")
def signals():
 try:
  market=request.args.get("market","crypto");interval=request.args.get("interval","15m");limit=min(20,max(1,int(request.args.get("limit",20))))
  if market not in ("crypto","futures","contracts","saudi","usmarket","forex"):return fail("السوق غير معروف")
  access=require_market_access(market)
  if access:return access
  results=scan(market,interval)
  results=sorted(results,key=lambda x:(float(x.get("confidence",0) or 0),float(x.get("researchScore",0) or 0)),reverse=True)
  normalized=[]
  for x in results[:limit]:
   y=dict(x)
   ready=bool(y.get("trade_ready",y.get("tradeReady",False)))
   y["trade_ready"]=ready
   y["tradeReady"]=ready
   y["market"]=y.get("market",market)
   y["interval"]=y.get("interval",interval)
   normalized.append(y)
  return ok(results=normalized,market=market,interval=interval)
 except Exception as e:
  app.logger.exception("AI signals endpoint failed: %s",e)
  # Keep the page usable during a temporary provider/API failure.
  try:
   key=market+"|"+interval
   cached=_load_strong_signal_cache(key,time.time())
   if cached:
    return ok(results=cached[:limit],market=market,interval=interval,stale=True)
  except Exception as cache_error:
   app.logger.warning("AI stale cache fallback failed: %s",cache_error)
  return ok(results=[],market=market,interval=interval,degraded=True)

@app.get("/trades")
def trades_page():
    return render_template("trades.html",page_id="trades",page_title="متابعة الصفقات",meta_description="متابعة نتائج الصفقات وسجل الأداء اليومي والأسبوعي والشهري والسنوي.")

@app.get("/api/trades")
def trades_api():
    _resolve_open_trades()
    db=conn()
    rows=db.execute("SELECT id,market,interval,symbol,direction,entry,tp1,tp2,tp3,sl,confidence,created_at,status,result,resolved_at,pnl_percent FROM ai_memory ORDER BY id DESC LIMIT 500").fetchall()
    db.close()
    day=86400
    stats={"today":_trade_stats(day),"week":_trade_stats(day*7),"month":_trade_stats(day*30),"year":_trade_stats(day*365),"all":_trade_stats(None)}
    data=[]
    for r in rows:
        x=dict(r); created=x.pop("created_at",0); resolved=x.pop("resolved_at",0)
        x["createdAt"]=datetime.fromtimestamp(float(created or 0),timezone.utc).isoformat() if created else ""
        x["resolvedAt"]=datetime.fromtimestamp(float(resolved or 0),timezone.utc).isoformat() if resolved else ""
        x["pnlPercent"]=round(float(x.pop("pnl_percent") or 0),2)
        x["statusLabel"]="🟢 مفتوحة" if x["status"]=="open" else ("✅ حققت الهدف" if x["result"] in ("tp1","tp2","tp3") else "❌ ضربت الوقف")
        data.append(x)
    return ok(trades=data,stats=stats,updatedAt=datetime.now(timezone.utc).isoformat())

@app.get("/health")
def health():return jsonify(ok=True,status="healthy",service="mudarib-abo-saud",time=datetime.now(timezone.utc).isoformat()),200

@app.get("/api/status")
def api_status():
 return ok(status="online",service="مضارب أبو سعود",updatedAt=datetime.now(timezone.utc).isoformat(),features={"auth":True,"markets":True,"ai":True,"cacheMinutes":15})
@app.get("/admin")
def admin_page():
 return render_template("admin.html",page_id="admin",page_title="لوحة الإدارة",meta_description="لوحة إدارة موقع المضارب ذكي")

@app.get("/admin/")
def admin_page_slash():
 return admin_page()

@app.post("/api/auth/register")
def register():
    d=request.get_json(silent=True) or {}
    name=str(d.get("name","")).strip()
    email=str(d.get("email","")).strip().lower()
    pw=str(d.get("password",""))
    if not name or len(name)<2 or len(name)>120:
        return fail("اكتب اسمك بشكل صحيح")
    if "@" not in email or len(email)>254:
        return fail("البريد الإلكتروني غير صالح")
    if len(pw)<8 or len(pw)>256:
        return fail("كلمة المرور لازم تكون 8 أحرف على الأقل")
    if _rate_limited("register",email):
        return fail("محاولات تسجيل كثيرة، حاول بعد 5 دقائق",429)
    from werkzeug.security import generate_password_hash
    c=conn()
    try:
        if c.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)",(email,)).fetchone():
            _rate_fail("register",email)
            return fail("البريد الإلكتروني مستخدم مسبقاً",409)
        base=email.split("@")[0].strip().lower()
        import re
        username=re.sub(r"[^a-z0-9_\-]","",base)[:24] or "user"
        candidate=username
        n=1
        while c.execute("SELECT 1 FROM users WHERE username=?",(candidate,)).fetchone():
            n+=1
            candidate=f"{username}{n}"
        username=candidate
        c.execute(
            "INSERT INTO users(username,email,name,password,is_admin) VALUES(?,?,?,?,0)",
            (username,email,name,generate_password_hash(pw))
        )
        c.commit()
        session.clear()
        session.permanent=True
        session["user"]=username
        session["admin"]=False
        session.modified=True
        _rate_clear("register",email)
        return ok(user={"username":username,"email":email,"name":name},admin=False)
    except sqlite3.IntegrityError:
        c.rollback()
        _rate_fail("register",email)
        return fail("تعذر إنشاء الحساب، جرّب مرة ثانية",409)
    finally:
        c.close()

@app.post("/api/auth/login")
def login():
    d=request.get_json(silent=True) or {}
    identity=str(d.get("email","")).strip().lower()
    pw=str(d.get("password",""))
    from werkzeug.security import check_password_hash
    if not identity or not pw or len(identity)>254 or len(pw)>256:
        return fail("أدخل البريد/اسم المستخدم وكلمة المرور")
    if _rate_limited("login",identity):
        return fail("محاولات دخول كثيرة، حاول بعد 5 دقائق",429)
    c=conn()
    try:
        u=c.execute(
            "SELECT * FROM users WHERE lower(email)=lower(?) OR lower(username)=lower(?) LIMIT 1",
            (identity,identity)
        ).fetchone()
    finally:
        c.close()
    if not u or not check_password_hash(u["password"],pw):
        _rate_fail("login",identity)
        return fail("البريد أو كلمة المرور غير صحيحة",401)
    _rate_clear("login",identity)
    session.clear()
    session.permanent=True
    session["user"]=u["username"]
    session["admin"]=bool(u["is_admin"])
    session.modified=True
    return ok(user={"username":u["username"],"email":u["email"],"name":u["name"]},admin=bool(u["is_admin"]))

@app.post("/api/auth/logout")
def logout():
    session.clear()
    return ok()

@app.get("/api/me")
def me():
    username=session.get("user")
    if not username:
        return ok(user=None,admin=False,subscription_active=False,paid_markets=[])
    c=conn()
    try:
        r=c.execute(
            "SELECT id,username,email,name,is_admin,subscription_until,created_at FROM users WHERE username=?",
            (username,)
        ).fetchone()
    finally:
        c.close()
    if not r:
        session.clear()
        return ok(user=None,admin=False,subscription_active=False,paid_markets=[])
    is_admin=bool(r["is_admin"])
    session["admin"]=is_admin
    return ok(
        user=dict(r),
        admin=is_admin,
        subscription_active=has_active_subscription(),
        paid_markets=[]
    )

def admin():
    username=session.get("user")
    if not username or not session.get("admin"):
        return False
    c=conn()
    try:
        row=c.execute("SELECT is_admin FROM users WHERE username=?",(username,)).fetchone()
        return bool(row and row["is_admin"])
    finally:
        c.close()

@app.post("/api/admin/login")
def admin_login():
    # لوحة الإدارة تستخدم نفس نظام الحسابات، ولا يوجد نظام كلمة مرور ثانٍ داخل الصفحة.
    d=request.get_json(silent=True) or {}
    identity=str(d.get("username",d.get("email",""))).strip().lower()
    pw=str(d.get("password",""))
    if not identity or not pw:
        return fail("أدخل بيانات حساب الإدارة")
    if _rate_limited("admin-login",identity):
        return fail("محاولات دخول كثيرة، حاول بعد 5 دقائق",429)
    from werkzeug.security import check_password_hash
    c=conn()
    try:
        row=c.execute(
            "SELECT * FROM users WHERE (lower(username)=lower(?) OR lower(email)=lower(?)) AND is_admin=1 LIMIT 1",
            (identity,identity)
        ).fetchone()
    finally:
        c.close()
    if not row or not check_password_hash(row["password"],pw):
        _rate_fail("admin-login",identity)
        return fail("حساب الإدارة غير صحيح أو لا يملك صلاحية الإدارة",401)
    _rate_clear("admin-login",identity)
    session.clear()
    session.permanent=True
    session["user"]=row["username"]
    session["admin"]=True
    session["admin_user"]=row["username"]
    session.modified=True
    return ok(admin=True,user=row["username"])

@app.get("/api/admin/session")
def admin_session():
    return ok(admin=admin(),user=session.get("user") if admin() else None)

@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return ok()

@app.get("/api/subscription")
def subscription():return ok(plans=PLANS,payment={"trc20":os.getenv("TRC20_ADDRESS","TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6").strip(),"binancePay":os.getenv("BINANCE_PAY_ID","28191866").strip()})

@app.post("/api/subscription/request")
def sub_request():
 if not session.get("user"):return fail("سجل الدخول أولاً",401)
 if _rate_limited("subscription",session.get("user","")):return fail("طلبات كثيرة، حاول بعد 5 دقائق",429)
 d=request.get_json(silent=True) or {};plan=d.get("plan");txid=str(d.get("txid","")).strip()
 if plan not in PLANS or not txid:return fail("اختر الباقة وأدخل رقم العملية")
 if len(txid)<6 or len(txid)>200:return fail("رقم العملية غير صالح")
 c=conn()
 if c.execute("SELECT id FROM payments WHERE txid=? AND status IN ('pending','approved')",(txid,)).fetchone():c.close();return fail("رقم العملية مستخدم مسبقاً",409)
 c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(session["user"],plan,txid));c.commit();c.close();_rate_clear("subscription",session.get("user",""));return ok()

@app.post("/api/admin/telegram/test")
def telegram_test():
 if not admin():return fail("غير مصرح",403)
 token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
 chat_id=os.getenv("TELEGRAM_CHAT_ID","").strip()
 if not token or not chat_id:return fail("إعدادات تيليجرام غير مكتملة: أضف TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID",503)
 msg="<b>✅ اختبار تيليجرام — المضارب ذكي</b>\\n\\nتم إرسال هذه الرسالة بنجاح من لوحة الإدارة.\\n📡 القناة: "+html.escape(chat_id)
 try:
  resp=H.post("https://api.telegram.org/bot"+token+"/sendMessage",json={"chat_id":chat_id,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15)
  resp.raise_for_status()
  data=resp.json()
  if not data.get("ok"):return fail("تيليجرام رفض الرسالة",502)
  return ok(message="تم إرسال رسالة الاختبار إلى تيليجرام")
 except Exception as e:
  app.logger.warning("Telegram test failed: %s",e)
  return fail("فشل إرسال اختبار تيليجرام: "+str(e),502)

@app.get("/api/admin/ai-memory")
def admin_ai_memory():
 if not admin():return fail("غير مصرح",403)
 try:
  c=conn()
  total=c.execute("SELECT COUNT(*) n FROM ai_memory").fetchone()["n"]
  closed=c.execute("SELECT COUNT(*) n FROM ai_memory WHERE status='closed'").fetchone()["n"]
  wins=c.execute("SELECT COUNT(*) n FROM ai_memory WHERE status='closed' AND result IN ('tp1','tp2','tp3')").fetchone()["n"]
  losses=c.execute("SELECT COUNT(*) n FROM ai_memory WHERE status='closed' AND result='sl'").fetchone()["n"]
  recent=c.execute("SELECT market,interval,symbol,direction,confidence,result,status,created_at FROM ai_memory ORDER BY id DESC LIMIT 20").fetchall()
  c.close()
  return ok(total=int(total or 0),closed=int(closed or 0),wins=int(wins or 0),losses=int(losses or 0),win_rate=round((wins/closed*100) if closed else 0,1),recent=[dict(x) for x in recent])
 except Exception as e:return fail("تعذر قراءة ذاكرة الذكاء",500)

@app.get("/api/admin/stats")
def stats():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"],c.execute("SELECT COUNT(*) n FROM users WHERE subscription_until>?",(datetime.now(timezone.utc).isoformat(),)).fetchone()["n"]];c.close();return ok(users=r[0],pending_payments=r[1],active_subscriptions=r[2])

@app.get("/api/admin/users")
def users():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[dict(x) for x in c.execute("SELECT id,username,email,name,subscription_until,created_at FROM users ORDER BY id DESC").fetchall()];c.close();return ok(users=r)

@app.get("/api/admin/payments")
def payments():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()];c.close();return ok(payments=r)

@app.post("/api/admin/payments/approve")
def approve():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();p=c.execute("SELECT * FROM payments WHERE id=?",(d.get("id"),)).fetchone()
 if not p:c.close();return fail("الطلب غير موجود",404)
 if p["status"]!="pending":c.close();return fail("تمت معالجة الطلب مسبقاً",409)
 if p["plan"] not in PLANS:c.close();return fail("الباقة غير صالحة",400)
 u=c.execute("SELECT * FROM users WHERE username=?",(p["username"],)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 base=datetime.now(timezone.utc)
 if u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=PLANS[p["plan"]]["days"])).isoformat();c.execute("UPDATE users SET subscription_until=? WHERE username=?",(until,p["username"]));c.execute("UPDATE payments SET status='approved' WHERE id=?",(p["id"],));c.commit();c.close();return ok()

@app.post("/api/admin/payments/reject")
def reject():
 if not admin():return fail("غير مصرح",403)
 c=conn();c.execute("UPDATE payments SET status='rejected' WHERE id=?",(request.get_json(silent=True) or {}).get("id"));c.commit();c.close();return ok()

@app.post("/api/admin/users/delete")
def delete_user():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};uid=d.get("id");c=conn();u=c.execute("SELECT username,is_admin FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 if u["is_admin"]:c.close();return fail("لا يمكن حذف حساب الإدارة",400)
 c.execute("DELETE FROM payments WHERE username=?",(u["username"],));c.execute("DELETE FROM users WHERE id=?",(uid,));c.commit();c.close();return ok()

@app.post("/api/admin/users/extend")
def extend_user():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};uid=d.get("id");days=max(1,min(365,int(d.get("days",30))));c=conn();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 base=datetime.now(timezone.utc)
 if u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=days)).isoformat();c.execute("UPDATE users SET subscription_until=? WHERE id=?",(until,uid));c.commit();c.close();return ok(subscription_until=until)

@app.post("/api/admin/logout")
def admin_logout():session.pop("admin",None);session.pop("admin_user",None);session.pop("user",None);return ok()

@app.get("/blog")
def blog():
 c=conn();posts=[dict(x) for x in c.execute("SELECT id,slug,title,excerpt,content,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE published=1 ORDER BY id DESC LIMIT 50").fetchall()];c.close()
 return render_template("blog.html",page_id="blog",page_title="المدونة",meta_description="مدونة المضارب ذكي: تحليلات الأسواق والعملات الرقمية والأسهم والفوركس والعقود الآجلة.",posts=posts)

@app.get("/blog/<slug>")
def blog_post(slug):
 c=conn();post=c.execute("SELECT * FROM blog_posts WHERE slug=? AND published=1",(slug,)).fetchone();c.close()
 if not post:return ("المقال غير موجود",404)
 return render_template("blog_post.html",page_id="blog-post",page_title=post["title"],meta_description=post["excerpt"] or post["title"],canonical_url=request.base_url,post=dict(post))

@app.get("/api/blog")
def blog_api():
 c=conn();posts=[dict(x) for x in c.execute("SELECT id,slug,title,excerpt,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE published=1 ORDER BY id DESC LIMIT 50").fetchall()];c.close()
 return ok(posts=posts)

@app.post("/api/admin/blog")
def add_blog_post():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};title=str(d.get("title","")).strip();content=str(d.get("content","")).strip();excerpt=str(d.get("excerpt","")).strip();category=str(d.get("category","عام")).strip() or "عام";cover_url=str(d.get("cover_url","")).strip();author=str(d.get("author","المضارب ذكي")).strip() or "المضارب ذكي";slug=str(d.get("slug","")).strip().lower()
 import re
 if not slug:slug=re.sub(r"[^a-z0-9\u0600-\u06ff]+","-",title).strip("-") or "article-"+str(int(time.time()))
 if not title or len(title)>180 or not content:return fail("العنوان والمحتوى مطلوبان")
 if len(slug)>180:return fail("الرابط طويل")
 c=conn()
 try:c.execute("INSERT INTO blog_posts(slug,title,excerpt,content,category,cover_url,author) VALUES(?,?,?,?,?,?,?)",(slug,title,excerpt,content,category,cover_url,author));c.commit()
 except sqlite3.IntegrityError:c.close();return fail("رابط المقال مستخدم مسبقاً",409)
 c.close();return ok()

@app.get("/api/admin/blog")
def admin_blog_posts():
 if not admin():return fail("غير مصرح",403)
 c=conn();posts=[dict(x) for x in c.execute("SELECT * FROM blog_posts ORDER BY id DESC").fetchall()];c.close();return ok(posts=posts)

@app.put("/api/admin/blog/<int:post_id>")
def update_blog_post(post_id):
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};title=str(d.get("title","")).strip();content=str(d.get("content","")).strip();excerpt=str(d.get("excerpt","")).strip();category=str(d.get("category","عام")).strip() or "عام";cover_url=str(d.get("cover_url","")).strip();author=str(d.get("author","المضارب ذكي")).strip() or "المضارب ذكي";published=1 if d.get("published",True) else 0
 if not title or not content:return fail("العنوان والمحتوى مطلوبان")
 c=conn();row=c.execute("SELECT id FROM blog_posts WHERE id=?",(post_id,)).fetchone()
 if not row:c.close();return fail("المقال غير موجود",404)
 c.execute("UPDATE blog_posts SET title=?,excerpt=?,content=?,category=?,cover_url=?,author=?,published=?,updated_at=? WHERE id=?",(title,excerpt,content,category,cover_url,author,published,datetime.now(timezone.utc).isoformat(),post_id));c.commit();c.close();return ok()

@app.delete("/api/admin/blog/<int:post_id>")
def delete_blog_post(post_id):
 if not admin():return fail("غير مصرح",403)
 c=conn();cur=c.execute("DELETE FROM blog_posts WHERE id=?",(post_id,));c.commit();c.close()
 return ok() if cur.rowcount else fail("المقال غير موجود",404)

@app.get("/api/news")
def news():
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 50").fetchall()];c.close();return ok(news=r)
@app.post("/api/admin/news")
def add_news():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();c.execute("INSERT INTO news(title,content,source) VALUES(?,?,?)",(d.get("title",""),d.get("content",""),d.get("source","")));c.commit();c.close();return ok()

try:
    init()
    _seed_beginner_blog()
except Exception:
    app.logger.exception("Database initialization failed; continuing so health checks can respond")

if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))