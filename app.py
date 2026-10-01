import hashlib
import hmac
import os
import secrets
import sqlite3
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE=Path(__file__).resolve().parent
DATA_DIR=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA_DIR.mkdir(parents=True,exist_ok=True)
except PermissionError:
    DATA_DIR=BASE/"data"; DATA_DIR.mkdir(parents=True,exist_ok=True)
DB_PATH=DATA_DIR/"app.db"
SECRET=os.getenv("SESSION_SECRET") or secrets.token_hex(32)
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود الأمريكية","us":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس"}
TIMEFRAMES=["15m","30m","1h","4h","1d","1w","1M"]

app=FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware,secret_key=SECRET,max_age=60*60*24*14)
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,timeframe TEXT NOT NULL,change_pct REAL NOT NULL DEFAULT 0,profit_pct REAL,loss_pct REAL,ai_pct REAL,tag TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT NOT NULL,email TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS strategy_cache(cache_key TEXT PRIMARY KEY,candle_start TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS site_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS user_settings(user_id INTEGER PRIMARY KEY,language TEXT DEFAULT 'ar',theme TEXT DEFAULT 'light',accent TEXT DEFAULT '#00c896',font_size TEXT DEFAULT 'normal',default_market TEXT DEFAULT 'spot',default_timeframe TEXT DEFAULT '15m',notifications INTEGER DEFAULT 1,sounds INTEGER DEFAULT 1,card_style TEXT DEFAULT 'compact');
    CREATE TABLE IF NOT EXISTS manual_analyses(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,market TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT,timeframe TEXT NOT NULL,change_pct REAL,ai_pct REAL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,title TEXT,body TEXT,schools TEXT,analysis_image TEXT);
    """)
    c.commit(); c.close()

def password_hash(password:str,salt:Optional[str]=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000)
    return salt+"$"+digest.hex()

def password_ok(password,stored):
    try:
        salt,expected=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000).hex()
        return hmac.compare_digest(actual,expected)
    except ValueError: return False

def current_user(request:Request):
    uid=request.session.get("user_id")
    if not uid:return None
    c=db(); row=c.execute("SELECT id,name,email,is_admin FROM users WHERE id=?",(uid,)).fetchone(); c.close()
    return dict(row) if row else None

def page(request:Request,title:str):
    user=current_user(request)
    html=(BASE/"static"/"index.html").read_text(encoding="utf-8")
    boot="<script>window.__PAGE_TITLE__="+repr(title)+";window.__USER__="+repr(user)+";</script>"
    response=HTMLResponse(html.replace("</head>",boot+"</head>"))
    # Always fetch the latest document on a real browser refresh.
    # Static assets remain cache-busted separately.
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"]="no-cache"
    response.headers["Expires"]="0"
    return response

MANUAL_ANALYSIS_TIMEFRAMES=("15m","1h","4h","1d")
MANUAL_ANALYSIS_INTERVAL_MINUTES=30

def _analysis_schools(row):
    return ["Price Action","الشموع اليابانية","SMC","ICT","Fibonacci","EMA / RSI","الدعم والمقاومة"]

def _analysis_body(market,row):
    if not row: return f"لا توجد فرصة مكتملة الشروط حالياً في {MARKETS[market]}."
    return (f"{row.get('symbol')} — {'شراء' if row.get('side')=='BUY' else 'بيع'}. تمت قراءة الاتجاه والسلوك السعري والزخم "
            f"والمناطق الرئيسية عبر عدة مدارس. الفريم الأساسي {row.get('timeframe','15m')}، وقوة التوافق "
            f"{float(row.get('ai_pct') or 0):.0f}%.")

def _analysis_image_svg(market,row,schools):
    symbol=str(row.get("symbol") or market); side=str(row.get("side") or "BUY"); tf=str(row.get("timeframe") or "15m")
    accent="#22c55e" if side.upper()=="BUY" else "#ef4444"
    def esc(v): return str(v).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
    def num(v):
        try:return f"{float(v):.8g}"
        except Exception:return "—"
    w,h=900,600
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(symbol)} تحليل فني">',
        '<rect width="900" height="600" rx="28" fill="#0b1220"/>',f'<rect width="900" height="7" fill="{accent}"/>',
        f'<text x="55" y="62" fill="#f8fafc" font-size="30" font-family="Arial" font-weight="700">{esc(symbol)}</text>',
        f'<text x="55" y="94" fill="#94a3b8" font-size="17" font-family="Arial">{esc(MARKETS.get(market,market))} • تحليل متعدد المدارس</text>',
        f'<rect x="685" y="35" width="160" height="55" rx="15" fill="{accent}" opacity=".15"/>',
        f'<text x="765" y="70" text-anchor="middle" fill="{accent}" font-size="23" font-family="Arial" font-weight="700">{esc("شراء" if side.upper()=="BUY" else "بيع")}</text>',
        '<line x1="55" y1="125" x2="845" y2="125" stroke="#243247"/>',
        '<text x="55" y="160" fill="#64748b" font-size="13" font-family="Arial">المدارس المستخدمة</text>']
    y=190
    for school in schools:
        parts += [f'<rect x="55" y="{y-21}" width="220" height="34" rx="10" fill="#111827"/>',
                  f'<text x="165" y="{y+2}" text-anchor="middle" fill="#e2e8f0" font-size="14" font-family="Arial">{esc(school)}</text>']
        y+=43
        if y>355: break
    parts += [f'<text x="335" y="160" fill="#64748b" font-size="13" font-family="Arial">الخلاصة</text>',
        f'<text x="335" y="193" fill="#f8fafc" font-size="20" font-family="Arial" font-weight="700">{esc("توافق إيجابي" if side.upper()=="BUY" else "توافق سلبي")}</text>',
        f'<text x="335" y="228" fill="#94a3b8" font-size="14" font-family="Arial">الفريم الأساسي</text>',
        f'<text x="335" y="254" fill="#e2e8f0" font-size="19" font-family="Arial">{esc(tf)}</text>',
        f'<text x="335" y="292" fill="#94a3b8" font-size="14" font-family="Arial">قوة التوافق</text>',
        f'<text x="335" y="319" fill="#f8fafc" font-size="22" font-family="Arial" font-weight="700">{esc(num(row.get("ai_pct")))}%</text>',
        f'<text x="335" y="357" fill="#94a3b8" font-size="14" font-family="Arial">التغير</text>',
        f'<text x="335" y="384" fill="#f8fafc" font-size="20" font-family="Arial">{esc(num(row.get("change_pct")))}%</text>',
        '<rect x="55" y="400" width="790" height="125" rx="18" fill="#111827"/>',
        '<text x="80" y="432" fill="#64748b" font-size="13" font-family="Arial">خطة الصفقة</text>',
        f'<text x="80" y="464" fill="#38bdf8" font-size="17" font-family="Arial">دخول {esc(num(row.get("entry")))}</text>',
        f'<text x="250" y="464" fill="#22c55e" font-size="17" font-family="Arial">TP1 {esc(num(row.get("tp1")))}</text>',
        f'<text x="385" y="464" fill="#22c55e" font-size="17" font-family="Arial">TP2 {esc(num(row.get("tp2")))}</text>',
        f'<text x="520" y="464" fill="#22c55e" font-size="17" font-family="Arial">TP3 {esc(num(row.get("tp3")))}</text>',
        f'<text x="675" y="464" fill="#ef4444" font-size="17" font-family="Arial">SL {esc(num(row.get("sl")))}</text>',
        f'<text x="55" y="565" fill="#475569" font-size="12" font-family="Arial">تحليل متعدد المدارس • {esc(tf)} • لا يتم اعتماد الصفقة عند تعارض الإشارات</text>','</svg>']
    return "".join(parts)

def _manual_analysis_candidates():
    candidates=[]
    for market in MARKETS:
        for tf in MANUAL_ANALYSIS_TIMEFRAMES:
            try:
                if market=="spot": rows=_scan_spot_strategy(tf)
                elif market=="futures": rows=_scan_binance_futures(tf)
                else: rows=_scan_yahoo_market(market,tf)
                if rows:
                    row=dict(rows[0]); row["timeframe"]=tf
                    candidates.append((market,row))
            except Exception: continue
    candidates.sort(key=lambda x:(float(x[1].get("ai_pct") or 0),float(x[1].get("change_pct") or 0)),reverse=True)
    return candidates[:6]

def generate_manual_analyses():
    candidates=_manual_analysis_candidates(); c=db(); c.execute("DELETE FROM manual_analyses")
    for market,row in candidates:
        schools=_analysis_schools(row)
        c.execute("INSERT INTO manual_analyses(market,symbol,side,timeframe,change_pct,ai_pct,entry,tp1,tp2,tp3,sl,title,body,schools,analysis_image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (market,row.get("symbol"),row.get("side"),row.get("timeframe","15m"),row.get("change_pct"),row.get("ai_pct"),row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),f"تحليل {MARKETS[market]}",_analysis_body(market,row), " + ".join(schools),_analysis_image_svg(market,row,schools)))
    c.commit(); n=len(candidates); c.close(); return {"ok":True,"count":n}

@app.get("/api/analysis/manual")
def manual_analyses():
    c=db(); rows=c.execute("SELECT * FROM manual_analyses ORDER BY ai_pct DESC,id DESC").fetchall(); c.close()
    return {"timeframes":MANUAL_ANALYSIS_TIMEFRAMES,"analyses":[dict(r) for r in rows]}

@app.post("/api/analysis/manual/refresh")
def refresh_manual_analyses(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    return generate_manual_analyses()

def _manual_analysis_worker():
    import time
    while True:
        try: generate_manual_analyses()
        except Exception: pass
        time.sleep(MANUAL_ANALYSIS_INTERVAL_MINUTES*60)

# ===== Strategy engine: Spot BUY =====
# مصادر Binance الرسمية للبيانات العامة.
# Binance توثق 6 نقاط وصول للـSpot: الأساسي + GCP + api1..api4.
BINANCE_SPOT_BASES=[
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://data-api.binance.vision",
]
# كل فريم له مسار أساسي مختلف، ثم يمر على بقية المصادر كاحتياطي.
TIMEFRAME_SOURCE_INDEX={
    "15m":0,"30m":1,"1h":2,"4h":3,"1d":4,"1w":5,"1M":6
}

BINANCE_SOURCE_LIMITS={
    "binance_api":{"per_min":120,"per_day":50000},
    "binance_gcp":{"per_min":120,"per_day":50000},
    "binance_api1":{"per_min":120,"per_day":50000},
    "binance_api2":{"per_min":120,"per_day":50000},
    "binance_api3":{"per_min":120,"per_day":50000},
    "binance_api4":{"per_min":120,"per_day":50000},
    "binance_data":{"per_min":120,"per_day":50000},
}
BINANCE_SOURCE_NAMES=[
    "binance_api","binance_gcp","binance_api1","binance_api2",
    "binance_api3","binance_api4","binance_data"
]
_BINANCE_STATE={k:{"minute":0,"day":0,"minute_at":0,"day_at":0,"fails":0,"cooldown_until":0.0}
                for k in BINANCE_SOURCE_LIMITS}
_BINANCE_LOCK=__import__("threading").Lock()

def _binance_source_allowed(name,cost=1):
    import time
    now=time.time()
    with _BINANCE_LOCK:
        s=_BINANCE_STATE[name]; lim=BINANCE_SOURCE_LIMITS[name]
        if now-s["minute_at"]>=60: s["minute"]=0; s["minute_at"]=now
        if now-s["day_at"]>=86400: s["day"]=0; s["day_at"]=now
        return now>=s["cooldown_until"] and s["minute"]+cost<=lim["per_min"] and s["day"]+cost<=lim["per_day"]

def _binance_source_take(name,cost=1):
    with _BINANCE_LOCK:
        _BINANCE_STATE[name]["minute"]+=cost
        _BINANCE_STATE[name]["day"]+=cost

def _binance_source_fail(name,seconds=20):
    import time
    with _BINANCE_LOCK:
        s=_BINANCE_STATE[name]; s["fails"]+=1
        s["cooldown_until"]=time.time()+min(600,seconds*(2**min(s["fails"]-1,4)))

def _binance_source_ok(name):
    with _BINANCE_LOCK:
        _BINANCE_STATE[name]["fails"]=0
        _BINANCE_STATE[name]["cooldown_until"]=0.0

def _binance_json(url, timeout=5, timeframe=None, spot_fallback=False):
    if not spot_fallback:
        req=urllib.request.Request(url, headers={"User-Agent":"mudarib-pro/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    parsed=urllib.parse.urlsplit(url)
    path=parsed.path
    query=parsed.query
    primary=TIMEFRAME_SOURCE_INDEX.get(timeframe,0)
    bases=BINANCE_SPOT_BASES[primary:]+BINANCE_SPOT_BASES[:primary]
    last=None
    for base in bases:
        try:
            target=base+path+("?" + query if query else "")
            req=urllib.request.Request(target, headers={"User-Agent":"mudarib-pro/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data=json.loads(r.read().decode("utf-8"))
                if data is not None:
                    return data
        except Exception as exc:
            last=exc
            continue
    if last:
        raise last
    raise RuntimeError("لا يوجد مصدر بيانات متاح")

def _ema(values, period):
    if len(values) < period: return None
    k=2/(period+1); e=sum(values[:period])/period
    for v in values[period:]: e=(v*k)+(e*(1-k))
    return e

def _rsi(values, period=14):
    if len(values) < period+1: return None
    gains=[]; losses=[]
    for a,b in zip(values[-period-1:-1], values[-period:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/period; al=sum(losses)/period
    if al==0: return 100.0
    return 100-(100/(1+(ag/al)))

def _scan_spot_strategy(timeframe="15m", limit_symbols=0):
    """Spot BUY strategy: every timeframe is evaluated independently."""
    if timeframe not in {"15m","30m","1h","4h","1d","1w","1M"}:
        return []

    tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=6,timeframe=timeframe,spot_fallback=True)
    excluded=("USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT")
    candidates=[]
    for t in tickers:
        symbol=t.get("symbol","")
        if not symbol.endswith("USDT") or symbol.endswith(excluded):
            continue
        try:
            volume=float(t.get("quoteVolume",0))
            if volume >= 1_000_000:
                candidates.append((volume,symbol))
        except (TypeError,ValueError):
            continue

    # لا نفحص مئات الأزواج دفعة واحدة على خدمة 512MB.
    # نأخذ الأعلى سيولة فقط، ويُستخدم limit_symbols إن أُرسل.
    candidates=sorted(candidates,reverse=True)
    max_candidates=min(len(candidates),max(6,min(int(limit_symbols or 8),8)))
    candidates=candidates[:max_candidates]

    def scan_one(item):
        _, symbol=item
        params=urllib.parse.urlencode({
            "symbol":symbol,
            "interval":timeframe,
            "limit":260
        })
        klines=_binance_json(
            "https://api.binance.com/api/v3/klines?"+params,
            timeout=6,timeframe=timeframe,spot_fallback=True
        )
        if len(klines) < 200:
            return None

        closes=[float(x[4]) for x in klines]
        lows=[float(x[3]) for x in klines]
        price=closes[-1]
        ema20=_ema(closes,20)
        ema200=_ema(closes,200)
        rsi=_rsi(closes)

        # كل فريم مستقل: مؤشرات هذا الفريم فقط.
        change=(price-closes[-2])/closes[-2]*100

        # BUY: السعر فوق المتوسطات + RSI فوق 50 + تغير موجب 1% فأكثر.
        if None in (ema20,ema200,rsi):
            return None
        if not (price > ema20 and price > ema200 and rsi > 50 and change >= 1):
            return None

        sl=min(lows[-20:])
        risk=price-sl
        if risk <= 0 or risk/price > 0.08:
            return None

        tp1=price+risk
        tp2=price+risk*2
        tp3=price+risk*3
        ai=max(
            50,
            min(
                99,
                50+(rsi-50)*0.8+(price-ema20)/price*500
            )
        )

        return {
            "symbol":symbol,
            "side":"BUY",
            "timeframe":timeframe,
            "change_pct":change,
            "profit_pct":risk/price*100*2,
            "loss_pct":risk/price*100,
            "ai_pct":ai,
            "tag":"استراتيجية "+timeframe,
            "entry":price,
            "tp1":tp1,
            "tp2":tp2,
            "tp3":tp3,
            "sl":sl,
            "status":"open"
        }

    found=[]
    # نفحص كل العملات المؤهلة فوق مليون، وليس أعلى 30 فقط.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(scan_one,item) for item in candidates]
        for future in as_completed(futures):
            try:
                row=future.result()
                if row:
                    found.append(row)
            except Exception:
                continue

    return sorted(
        found,
        key=lambda x:(float(x["change_pct"]),float(x["ai_pct"])),
        reverse=True
    )[:20]

@app.get("/api/strategy/scan")
def strategy_scan(market:str="spot",timeframe:str="15m"):
    if market!="spot":
        return {"market":market,"timeframe":timeframe,"trades":[],"message":"المحرك الحالي مطبق للسبوت فقط"}
    try:
        rows=_scan_spot_strategy(timeframe)
        return {"market":"spot","market_name":MARKETS["spot"],"timeframe":timeframe,
                "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)


# ===== Multi-market live strategy engines =====
MARKET_RULES={
    "spot":{"sides":["BUY"],"source":"spot"},
    "futures":{"sides":["BUY","SELL"],"source":"futures"},
    "contracts":{"sides":["BUY","SELL"],"source":"yahoo"},
    "us":{"sides":["BUY"],"source":"yahoo"},
    "saudi":{"sides":["BUY"],"source":"yahoo"},
    "forex":{"sides":["BUY","SELL"],"source":"yahoo"},
}
FOREX_SYMBOLS=["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X"]
US_CONTRACT_SYMBOLS=["ES=F","NQ=F","YM=F","RTY=F","GC=F","SI=F","CL=F","NG=F","ZB=F","ZN=F"]
US_SYMBOLS=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","JPM","V","WMT","COST","ORCL"]
# Tadawul symbols are Yahoo-style 1180.SR etc.; keep a liquid core and allow expansion.
SAUDI_SYMBOLS=["2222.SR","1120.SR","1180.SR","2010.SR","7010.SR","7020.SR","1211.SR","2050.SR","2280.SR","1150.SR","1050.SR","1060.SR"]

# ===== Data Source Manager =====
# المصادر مرتبة: الرسمي/المباشر ثم البدائل. مفاتيح المزودات اختيارية ولا تُحفظ في الكود.
DATA_SOURCE_KEYS={
    "TWELVE_DATA_API_KEY": os.getenv("TWELVE_DATA_API_KEY","").strip(),
    "ALPHA_VANTAGE_API_KEY": os.getenv("ALPHA_VANTAGE_API_KEY","").strip(),
    "COINMARKETCAP_API_KEY": os.getenv("COINMARKETCAP_API_KEY","").strip(),
}

YAHOO_BASES=[
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]

# موزّع حمل محافظ لكل مصدر
SOURCE_LIMITS={
    "yahoo1":{"per_min":30,"per_day":20000},
    "yahoo2":{"per_min":30,"per_day":20000},
    "twelvedata":{"per_min":20,"per_day":800},
    "alphavantage":{"per_min":2,"per_day":20},
    "coinmarketcap":{"per_min":20,"per_day":1000},
}
_SOURCE_STATE={k:{"minute":0,"day":0,"minute_at":0,"day_at":0,"fails":0,"cooldown_until":0.0} for k in SOURCE_LIMITS}
_SOURCE_LOCK=__import__("threading").Lock()

def _source_allowed(name,cost=1):
    import time
    now=time.time()
    with _SOURCE_LOCK:
        s=_SOURCE_STATE[name]; lim=SOURCE_LIMITS[name]
        if now-s["minute_at"]>=60: s["minute"]=0; s["minute_at"]=now
        if now-s["day_at"]>=86400: s["day"]=0; s["day_at"]=now
        return now>=s["cooldown_until"] and s["minute"]+cost<=lim["per_min"] and s["day"]+cost<=lim["per_day"]

def _source_take(name,cost=1):
    import time
    with _SOURCE_LOCK:
        s=_SOURCE_STATE[name]; s["minute"]+=cost; s["day"]+=cost

def _source_fail(name,seconds=30):
    import time
    with _SOURCE_LOCK:
        s=_SOURCE_STATE[name]; s["fails"]+=1
        s["cooldown_until"]=time.time()+min(900,seconds*(2**min(s["fails"]-1,4)))

def _source_ok(name):
    with _SOURCE_LOCK:
        _SOURCE_STATE[name]["fails"]=0; _SOURCE_STATE[name]["cooldown_until"]=0.0


TWELVE_INTERVAL={
    "15m":"15min","30m":"30min","1h":"1h","4h":"4h",
    "1d":"1day","1w":"1week","1M":"1month"
}

def _json_get(url, timeout=6, headers=None, source=None):
    if source and not _source_allowed(source):
        raise RuntimeError("مصدر البيانات بلغ حصته المؤقتة")
    if source: _source_take(source)
    try:
        req=urllib.request.Request(url,headers=headers or {"User-Agent":"mudarib-pro/1.0"})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            data=json.loads(r.read().decode("utf-8"))
        if isinstance(data,dict) and (data.get("status")=="error" or data.get("Error Message") or data.get("Note")):
            raise RuntimeError(str(data.get("message") or data.get("Error Message") or data.get("Note")))
        if source: _source_ok(source)
        return data
    except Exception:
        if source: _source_fail(source)
        raise

def _valid_candles(candles, minimum=200):
    if not candles or len(candles)<minimum:
        return False
    try:
        return all(float(x[0])>0 and float(x[1])>0 for x in candles[-minimum:])
    except Exception:
        return False

def _twelve_chart(symbol,timeframe,outputsize=500):
    key=DATA_SOURCE_KEYS["TWELVE_DATA_API_KEY"]
    if not key:
        return []
    interval=TWELVE_INTERVAL.get(timeframe)
    if not interval:
        return []
    # Yahoo-style .SR symbols are converted to Tadawul notation only when the provider accepts it.
    td_symbol=symbol.replace(".SR",":TADAWUL")
    params=urllib.parse.urlencode({
        "symbol":td_symbol,"interval":interval,"outputsize":min(outputsize,5000),"apikey":key
    })
    d=_json_get("https://api.twelvedata.com/time_series?"+params,timeout=8,source="twelvedata")
    vals=d.get("values") or []
    out=[]
    for v in reversed(vals):
        try:
            out.append((float(v["close"]),float(v.get("low",v["close"]))))
        except Exception:
            continue
    return out

def _alpha_chart(symbol,timeframe,outputsize=500):
    key=DATA_SOURCE_KEYS["ALPHA_VANTAGE_API_KEY"]
    if not key:
        return []
    interval_map={"15m":"15min","30m":"30min","1h":"60min"}
    if timeframe in interval_map:
        fn="TIME_SERIES_INTRADAY"
        params={"function":fn,"symbol":symbol,"interval":interval_map[timeframe],"outputsize":"full","apikey":key}
    elif timeframe=="1d":
        params={"function":"TIME_SERIES_DAILY","symbol":symbol,"outputsize":"full","apikey":key}
    elif timeframe=="1w":
        params={"function":"TIME_SERIES_WEEKLY","symbol":symbol,"apikey":key}
    elif timeframe=="1M":
        params={"function":"TIME_SERIES_MONTHLY","symbol":symbol,"apikey":key}
    else:
        return []
    d=_json_get("https://www.alphavantage.co/query?"+urllib.parse.urlencode(params),timeout=10,source="alphavantage")
    series=next((v for k,v in d.items() if str(k).startswith("Time Series")),{})
    out=[]
    for v in reversed(list(series.values())):
        try: out.append((float(v["4. close"]),float(v["3. low"])))
        except Exception: continue
    return out[-outputsize:]

def _cmc_chart(symbol,timeframe,outputsize=500):
    """CoinMarketCap fallback for crypto when an API key is configured.
    Uses the same timeframe candles where CMC documents them; no cross-timeframe
    indicator calculation is performed here.
    """
    key=DATA_SOURCE_KEYS["COINMARKETCAP_API_KEY"]
    if not key:
        return []
    # Binance symbol -> base asset, e.g. BTCUSDT -> BTC.
    base=symbol[:-4] if symbol.endswith("USDT") else symbol
    if not base:
        return []
    # CMC V2 historical endpoint currently supports hourly and daily periods.
    if timeframe=="1h":
        period="hourly"
        interval="1h"
    elif timeframe=="1d":
        period="daily"
        interval="daily"
    elif timeframe=="1w":
        period="daily"
        interval="7d"
    elif timeframe=="1M":
        period="daily"
        interval="30d"
    else:
        return []
    params=urllib.parse.urlencode({
        "symbol":base,
        "time_period":period,
        "interval":interval,
        "count":min(outputsize,500),
        "convert":"USD"
    })
    headers={
        "Accept":"application/json",
        "X-CMC_PRO_API_KEY":key,
        "User-Agent":"mudarib-pro/1.0"
    }
    d=_json_get(
        "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical?"+params,
        timeout=10,headers=headers,source="coinmarketcap"
    )
    data=d.get("data")
    if isinstance(data,dict):
        data=[data]
    if not data:
        return []
    quotes=(data[0].get("quotes") or []) if isinstance(data[0],dict) else []
    out=[]
    for q in quotes:
        try:
            usd=(q.get("quote") or {}).get("USD") or {}
            out.append((float(usd["close"]),float(usd["low"])))
        except Exception:
            continue
    return out[-outputsize:]


def _yahoo_chart(symbol, interval="15m", range_="60d", timeframe=None):
    # يفحص أكثر من خادم Yahoo ثم ينتقل تلقائياً للمزودات البديلة المتاحة.
    q=urllib.parse.quote(symbol,safe="")
    errors=[]
    for base in YAHOO_BASES:
        try:
            url=f"{base}/v8/finance/chart/{q}?interval={interval}&range={range_}"
            d=_json_get(url,timeout=6,source=("yahoo1" if base.endswith("query1.finance.yahoo.com") else "yahoo2"))
            r=d.get("chart",{}).get("result") or []
            if r:
                rr=r[0]; qd=rr.get("indicators",{}).get("quote",[{}])[0]
                closes=qd.get("close",[]); lows=qd.get("low",[])
                candles=[(float(x),float(l)) for x,l in zip(closes,lows) if x is not None and l is not None]
                if _valid_candles(candles):
                    return candles
        except Exception as exc:
            errors.append(str(exc))
    tf=timeframe or next((k for k,v in TWELVE_INTERVAL.items() if v==interval),None)
    for name,fn in (
        ("TwelveData",lambda: _twelve_chart(symbol,tf or "1d")),
        ("AlphaVantage",lambda: _alpha_chart(symbol,tf or "1d")),
    ):
        try:
            candles=fn()
            if _valid_candles(candles):
                return candles
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return []


def _strategy_rows(symbol, timeframe, sides, candles):
    """Unified strategy used by every market; all indicators come from this timeframe only."""
    if len(candles)<200:
        return []
    closes=[float(x[0]) for x in candles]
    lows=[float(x[1]) for x in candles]
    price=closes[-1]
    ema20=_ema(closes,20)
    ema200=_ema(closes,200)
    rsi=_rsi(closes)
    if None in (ema20,ema200,rsi):
        return []

    change=(price-closes[-2])/closes[-2]*100

    # نفس العدادات لكل الأسواق والفريمات.
    long_ok=(price > ema20 and price > ema200 and rsi > 50 and change >= 1)
    out=[]

    for side in sides:
        # المحرك الموحد: الإشارة الأساسية شراء فقط.
        if side != "BUY" or not long_ok:
            continue

        sl=min(lows[-20:])
        risk=price-sl
        if risk <= 0 or risk/price > 0.08:
            continue

        tp1=price+risk
        tp2=price+risk*2
        tp3=price+risk*3
        profit=risk/price*200
        loss=risk/price*100
        ai=max(50,min(99,50+(rsi-50)*0.8+(price-ema20)/price*500))

        out.append({
            "symbol":symbol,
            "side":"BUY",
            "timeframe":timeframe,
            "change_pct":change,
            "profit_pct":profit,
            "loss_pct":loss,
            "ai_pct":ai,
            "tag":"استراتيجية "+timeframe,
            "entry":price,
            "tp1":tp1,
            "tp2":tp3-risk,
            "tp3":tp3,
            "sl":sl,
            "status":"open"
        })
    return out

def _candle_start(timeframe):
    from datetime import datetime, timezone, timedelta
    now=datetime.now(timezone.utc)
    if timeframe.endswith("m"):
        minutes=int(timeframe[:-1]); total=now.hour*60+now.minute; floored=(total//minutes)*minutes
        return now.replace(hour=floored//60,minute=floored%60,second=0,microsecond=0)
    if timeframe.endswith("h"):
        hours=int(timeframe[:-1]); return now.replace(hour=(now.hour//hours)*hours,minute=0,second=0,microsecond=0)
    if timeframe=="1d": return now.replace(hour=0,minute=0,second=0,microsecond=0)
    if timeframe=="1w": return now.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=now.weekday())
    if timeframe=="1M": return now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    return now.replace(second=0,microsecond=0)

_SCAN_LOCKS={}
_SCAN_LOCKS_GUARD=__import__("threading").Lock()
# عامل واحد فقط لكل عمليات المسح الخلفية: يمنع تراكم مسوحات ثقيلة على 0.2 vCPU / 512MB.
_SCAN_REFRESH_POOL=ThreadPoolExecutor(max_workers=1)

def _scan_lock(key):
    with _SCAN_LOCKS_GUARD:
        lock=_SCAN_LOCKS.get(key)
        if lock is None:
            lock=__import__("threading").Lock()
            _SCAN_LOCKS[key]=lock
        return lock

def _read_cached_scan(key,candle_start):
    c=db()
    row=c.execute("SELECT candle_start,payload FROM strategy_cache WHERE cache_key=?",(key,)).fetchone()
    c.close()
    if not row:
        return None,False
    try:
        data=json.loads(row["payload"])
        return data,row["candle_start"]==candle_start
    except Exception:
        return None,False

def _refresh_scan(key,candle_start,scanner):
    lock=_scan_lock(key)
    if not lock.acquire(blocking=False):
        return False
    try:
        rows=scanner()
        c=db()
        c.execute("INSERT INTO strategy_cache(cache_key,candle_start,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(cache_key) DO UPDATE SET candle_start=excluded.candle_start,payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",(key,candle_start,json.dumps(rows,ensure_ascii=False)))
        c.commit(); c.close()
        return True
    except Exception:
        return False
    finally:
        lock.release()

def _cached_scan(market,timeframe,scanner):
    """Return immediately from cache and refresh at most once per market/timeframe."""
    candle_start=_candle_start(timeframe).isoformat()
    key=f"v4:{market}:{timeframe}"
    cached,fresh=_read_cached_scan(key,candle_start)
    if fresh:
        return cached,False
    lock=_scan_lock(key)
    if lock.acquire(blocking=False):
        lock.release()
        _SCAN_REFRESH_POOL.submit(_refresh_scan,key,candle_start,scanner)
    return (cached if cached is not None else []),True

def _market_universe(market):
    if market=="forex": return FOREX_SYMBOLS
    if market=="us": return US_SYMBOLS
    if market=="saudi": return SAUDI_SYMBOLS
    if market=="contracts": return US_CONTRACT_SYMBOLS
    return []

def _scan_yahoo_market(market,timeframe):
    interval=timeframe
    range_map={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
    interval_map={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    def scan_one(symbol):
        candles=_yahoo_chart(symbol,interval_map[interval],range_map[interval],timeframe)
        return _strategy_rows(symbol,timeframe,["BUY"],candles)
    rows=[]
    # الأسواق غير Binance تعمل بعدد قليل من العمال لتفادي تجميد الخدمة.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(scan_one,s) for s in _market_universe(market)]
        for future in as_completed(futures):
            try: rows.extend(future.result())
            except Exception: pass
    return sorted([x for x in rows if float(x.get("change_pct",0)) >= 1],key=lambda x:(x["change_pct"],x["ai_pct"]),reverse=True)[:20]

def _binance_futures_json(url,timeout=5):
    # Futures uses the officially documented base. We do not invent alternate hosts.
    req=urllib.request.Request(url,headers={"User-Agent":"mudarib-pro/1.0"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _scan_binance_futures(timeframe):
    tickers=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=6)
    candidates=[]
    for t in tickers:
        s=t.get("symbol","")
        if s.endswith("USDT"):
            try:
                q=float(t.get("quoteVolume",0))
                if q>=1_000_000: candidates.append((q,s))
            except: pass
    def scan_one(item):
        _,symbol=item
        p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":260})
        k=_binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+p,timeout=6)
        candles=[(float(x[4]),float(x[3])) for x in k]
        return _strategy_rows(symbol,timeframe,["BUY","SELL"],candles)
    rows=[]
    # تشغيل محدود حتى لا يستهلك الفحص كل موارد الخدمة.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(scan_one,item) for item in sorted(candidates,reverse=True)[:15]]
        for future in as_completed(futures):
            try: rows.extend(future.result(timeout=0.2))
            except Exception: pass
    rows=[x for x in rows if abs(float(x.get("change_pct",0))) > 1]
    return sorted(rows,key=lambda x:(abs(x["change_pct"]),x["ai_pct"]),reverse=True)[:20]

# ===== Backward-compatible API aliases =====
@app.get("/api/auth/me")
def auth_me(request:Request):
    return me(request)

@app.get("/api/admin/me")
def admin_me(request:Request):
    u=admin_only(request)
    return {"user":u} if u else JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)

@app.get("/api/spot/scan")
def legacy_spot_scan(interval:str="15m",limit:int=40):
    if interval not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        rows,scanning=_cached_scan("spot",interval,lambda: _scan_spot_strategy(interval,min(max(limit,1),20)))
        return {"market":"spot","timeframe":interval,"scanning":scanning,"trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)

@app.get("/api/binance/scan")
def legacy_binance_scan(interval:str="15m",limit:int=40):
    return legacy_spot_scan(interval,limit)

@app.get("/api/spot/analysis")
def legacy_spot_analysis(symbol:str,interval:str="15m"):
    if interval not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        rows,_=_cached_scan("spot",interval,lambda: _scan_spot_strategy(interval,20))
        for x in rows:
            if x["symbol"]==symbol.upper():
                return x
        return {"symbol":symbol.upper(),"timeframe":interval,"found":False,"message":"لا توجد إشارة مطابقة حالياً"}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر تحليل الرمز حالياً"},status_code=502)

@app.get("/api/binance/analysis")
def legacy_binance_analysis(symbol:str,interval:str="15m"):
    return legacy_spot_analysis(symbol,interval)

@app.get("/api/strategy/scan-all")
def strategy_scan_all(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    try:
        if market=="spot":
            rows,scanning=_cached_scan(market,timeframe,lambda: _scan_spot_strategy(timeframe))
        elif market=="futures":
            rows,scanning=_cached_scan(market,timeframe,lambda: _scan_binance_futures(timeframe))
        else:
            rows,scanning=_cached_scan(market,timeframe,lambda: _scan_yahoo_market(market,timeframe))
        return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"scanning":scanning,
                "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر جلب بيانات السوق حالياً"},status_code=502)

def admin_only(request):
    u=current_user(request); return u if u and u["is_admin"] else None

@app.get("/api/admin/summary")
def admin_summary(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); a=c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; b=c.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]; d=c.execute("SELECT COUNT(*) c FROM support_messages WHERE status='new'").fetchone()["c"]; c.close()
    return {"users":a,"trades":b,"new_support":d}

@app.post("/api/admin/trades")
def admin_trade(request:Request,market:str=Form(...),symbol:str=Form(...),side:str=Form(...),timeframe:str=Form(...),change_pct:float=Form(...),profit_pct:float=Form(...),loss_pct:float=Form(...),ai_pct:float=Form(...),tag:str=Form(""),entry:float=Form(...),tp1:float=Form(...),tp2:float=Form(...),tp3:float=Form(...),sl:float=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    if market not in MARKETS or timeframe not in TIMEFRAMES or side not in {"BUY","SELL"}: return JSONResponse({"ok":False,"message":"بيانات الصفقة غير صالحة"},status_code=400)
    c=db(); c.execute("""INSERT INTO trades(market,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(market,symbol.upper(),side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl)); c.commit(); c.close()
    return {"ok":True,"message":"تم حفظ الصفقة"}

@app.post("/api/admin/message")
def admin_message(request:Request,title:str=Form(...),body:str=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); c.execute("UPDATE messages SET active=0"); c.execute("INSERT INTO messages(title,body,active) VALUES(?,?,1)",(title,body)); c.commit(); c.close()
    return {"ok":True,"message":"تم نشر الرسالة"}
