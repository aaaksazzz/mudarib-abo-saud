import hashlib
import hmac
import os
import secrets
import sqlite3
import json
import urllib.request
import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse, FileResponse
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
BREADTH_REFERENCE={x:x for x in TIMEFRAMES}
REFERENCE_TIMEFRAMES=list(TIMEFRAMES)
BINANCE_SPOT_BASES=("https://api.binance.com","https://api-gcp.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://api4.binance.com","https://data-api.binance.vision")

# Deploy trigger: keep Northflank aligned with main.
app=FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware,secret_key=SECRET,max_age=60*60*24*14)
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

@app.middleware("http")
async def _cache_control_middleware(request:Request,call_next):
    response=await call_next(request)
    path=request.url.path
    if path.startswith("/static/") or path.startswith("/api/") or "text/html" in response.headers.get("content-type",""):
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]="no-cache"
        response.headers["Expires"]="0"
    return response

def db():
    # SQLite shared by API/workers: tolerate short concurrent writes and enable WAL.
    c=sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

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
    CREATE TABLE IF NOT EXISTS crypto_analysis_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,slot TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,timeframe TEXT NOT NULL,price REAL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,confidence REAL,patterns TEXT,body TEXT,chart_svg TEXT);
    CREATE TABLE IF NOT EXISTS daily_analyses(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,analysis_date TEXT NOT NULL,market TEXT NOT NULL,slot INTEGER NOT NULL,symbol TEXT,side TEXT,timeframe TEXT,change_pct REAL,ai_pct REAL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,title TEXT,body TEXT,analysis_type TEXT,chart_svg TEXT,UNIQUE(analysis_date,market,slot));
    CREATE TABLE IF NOT EXISTS hourly_analyses(id INTEGER PRIMARY KEY AUTOINCREMENT,analysis_hour TEXT PRIMARY KEY,market TEXT NOT NULL,symbol TEXT,side TEXT,timeframe TEXT,change_pct REAL,ai_pct REAL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,analysis_type TEXT,chart_svg TEXT,title TEXT,body TEXT);
    CREATE TABLE IF NOT EXISTS spot_signal_events(id INTEGER PRIMARY KEY AUTOINCREMENT,signal_key TEXT UNIQUE NOT NULL,market TEXT NOT NULL DEFAULT 'spot',symbol TEXT NOT NULL,side TEXT NOT NULL,timeframe TEXT NOT NULL,candle_start TEXT NOT NULL,entry REAL NOT NULL,tp1 REAL NOT NULL,tp2 REAL NOT NULL,tp3 REAL NOT NULL,sl REAL NOT NULL,score REAL NOT NULL,volume_ratio REAL,book_imbalance REAL,buy_pressure REAL,spread_pct REAL,status TEXT NOT NULL DEFAULT 'open',outcome TEXT,exit_price REAL,realized_pct REAL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,closed_at TEXT,last_price REAL,last_checked_at TEXT,peak_profit_pct REAL NOT NULL DEFAULT 0,protected_profit_pct REAL NOT NULL DEFAULT 0,protection_price REAL,expires_at TEXT);
    CREATE TABLE IF NOT EXISTS futures_bot_state(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'idle',symbol TEXT,side TEXT,timeframe TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,score REAL,ai_pct REAL,balance_usdt REAL,margin_usdt REAL,notional_usdt REAL,quantity REAL,leverage REAL NOT NULL DEFAULT 20,peak_profit_pct REAL NOT NULL DEFAULT 0,protected_profit_pct REAL NOT NULL DEFAULT 0,protection_price REAL,opened_at TEXT,closed_at TEXT,outcome TEXT,realized_pct REAL,last_price REAL,last_checked_at TEXT,manual_confirmed INTEGER NOT NULL DEFAULT 0,last_error TEXT);
    """)
    # Safe migrations for existing Northflank volumes.
    for col,ddl in (
        ("peak_profit_pct","ALTER TABLE spot_signal_events ADD COLUMN peak_profit_pct REAL NOT NULL DEFAULT 0"),
        ("protected_profit_pct","ALTER TABLE spot_signal_events ADD COLUMN protected_profit_pct REAL NOT NULL DEFAULT 0"),
        ("protection_price","ALTER TABLE spot_signal_events ADD COLUMN protection_price REAL"),
        ("expires_at","ALTER TABLE spot_signal_events ADD COLUMN expires_at TEXT"),
        ("market","ALTER TABLE spot_signal_events ADD COLUMN market TEXT NOT NULL DEFAULT 'spot'"),
    ):
        try:
            c.execute(f"SELECT {col} FROM spot_signal_events LIMIT 1")
        except Exception:
            try: c.execute(ddl)
            except Exception: pass
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN last_error TEXT")
    except Exception: pass
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN last_signal_candle TEXT")
    except Exception: pass
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

def _binance_private_status():
    """Read-only Binance account connectivity. Secrets come only from Northflank env vars."""
    import os, time, hmac, hashlib
    from urllib.parse import urlencode
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        return {"connected":False,"configured":False,"message":"Binance API غير مهيأ"}
    try:
        ts=int(time.time()*1000)
        q=urlencode({"timestamp":ts,"recvWindow":5000})
        sig=hmac.new(secret.encode(),q.encode(),hashlib.sha256).hexdigest()
        data=_binance_json("https://api.binance.com/api/v3/account?"+q+"&signature="+sig,
                           timeout=8, headers={"X-MBX-APIKEY":key})
        if not isinstance(data,dict) or "balances" not in data:
            return {"connected":False,"configured":True,"message":"تعذر التحقق من Binance"}
        balances=[]
        for b in data.get("balances",[]):
            free=float(b.get("free") or 0); locked=float(b.get("locked") or 0)
            if free or locked:
                balances.append({"asset":b.get("asset"),"free":free,"locked":locked})
        return {"connected":True,"configured":True,"message":"Binance متصل","balances":balances}
    except Exception as exc:
        return {"connected":False,"configured":True,"message":"فشل اتصال Binance","detail":str(exc)[:120]}

@app.get("/api/binance/status")
def binance_status_api(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    return _binance_private_status()

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

DAILY_ANALYSIS_MARKETS=tuple(MARKETS.keys())
DAILY_ANALYSIS_TIMEFRAME="15m"
HOURLY_ANALYSIS_TIMEFRAME="15m"

def _riyadh_today():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=3))).date().isoformat()

def _analysis_body(market,row,slot):
    if not row:
        return f"لا توجد إشارة مطابقة للاستراتيجية في {MARKETS[market]} وقت إنشاء التحليل."
    side="شراء" if row.get("side")=="BUY" else "بيع"
    return (f"تحليل {MARKETS[market]} اليومي رقم {slot}: {row.get('symbol')} — {side}. "
            f"التغير {float(row.get('change_pct',0)):.2f}%، وقوة التحليل {float(row.get('ai_pct',0)):.0f}%. "
            f"الدخول {row.get('entry')}, TP1 {row.get('tp1')}, TP2 {row.get('tp2')}, TP3 {row.get('tp3')}, "
            f"والوقف {row.get('sl')}. مبني على EMA20/EMA200 وRSI والتغير السعري على 15 دقيقة.")

def _analysis_chart_candles(market,symbol,timeframe="15m"):
    """يجلب آخر شموع للرمز المختار فقط؛ خفيف على الخدمة."""
    try:
        if market=="spot":
            p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":120})
            k=_binance_json("https://api.binance.com/api/v3/klines?"+p,timeout=6,timeframe=timeframe,spot_fallback=True)
            return [(float(x[1]),float(x[2]),float(x[3]),float(x[4])) for x in k if len(x)>=5]
        if market=="futures":
            p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":120})
            k=_binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+p,timeout=6)
            return [(float(x[1]),float(x[2]),float(x[3]),float(x[4])) for x in k if len(x)>=5]
        q=urllib.parse.quote(symbol,safe="")
        interval_map={"1m":"1m","3m":"5m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
        range_map={"1m":"7d","3m":"30d","5m":"30d","15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
        for base in YAHOO_BASES:
            try:
                u=f"{base}/v8/finance/chart/{q}?interval={interval_map.get(timeframe,'15m')}&range={range_map.get(timeframe,'60d')}"
                d=_json_get(u,timeout=6,source=("yahoo1" if base.endswith("query1.finance.yahoo.com") else "yahoo2"))
                rr=(d.get("chart",{}).get("result") or [])[0]
                qt=rr.get("indicators",{}).get("quote",[{}])[0]
                o,h,l,cl=qt.get("open",[]),qt.get("high",[]),qt.get("low",[]),qt.get("close",[])
                out=[]
                for a,b,cc,dv in zip(o,h,l,cl):
                    if None not in (a,b,cc,dv): out.append((float(a),float(b),float(cc),float(dv)))
                if out: return out[-120:]
            except Exception:
                continue
    except Exception:
        pass
    return []

def _analysis_chart_svg(market,row,analysis_type):
    """شارت تحليل فني مرسوم بأسلوب احترافي قريب من شارتات TradingView."""
    symbol=row.get("symbol")
    if not symbol: return ""
    candles=_analysis_chart_candles(market,symbol,row.get("timeframe","15m"))
    if len(candles)<30: return ""

    w,h=1180,650
    left,right,top,bottom=72,125,48,72
    vals=[x[1] for x in candles]+[x[2] for x in candles]
    levels=[float(v) for v in (row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl")) if v is not None]
    nums=vals+levels
    lo=min(nums); hi=max(nums); span=max(hi-lo,hi*0.003)
    lo-=span*.07; hi+=span*.07

    def y(v):
        return top+(hi-float(v))/(hi-lo)*(h-top-bottom)
    n=len(candles); plot_w=w-left-right; step=plot_w/max(n,1); body=max(3,step*.58)

    closes=[x[3] for x in candles]
    def ema(vals,period):
        if len(vals)<period: return []
        k=2/(period+1); e=sum(vals[:period])/period; out=[None]*(period-1)+[e]
        for v in vals[period:]:
            e=v*k+e*(1-k); out.append(e)
        return out

    ema20=ema(closes,20); ema200=ema(closes,200)
    lows=[x[2] for x in candles]; highs=[x[1] for x in candles]
    support=min(lows[-40:]); resistance=max(highs[-40:])
    low_i=min(range(max(0,n-40),n),key=lambda i:lows[i])
    high_i=max(range(max(0,n-40),n),key=lambda i:highs[i])

    parts=[
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{symbol} تحليل فني">',
        '<rect width="100%" height="100%" rx="18" fill="#0b1220"/>',
        f'<text x="{left}" y="27" fill="#f8fafc" font-size="20" font-family="Arial" font-weight="700">{symbol} • {analysis_type}</text>',
        f'<text x="{left}" y="45" fill="#94a3b8" font-size="12" font-family="Arial">15m • شموع + اتجاه + دعم ومقاومة + Fibonacci + EMA + مستويات الصفقة</text>'
    ]

    # شبكة السعر والزمن.
    for gy in range(7):
        yy=top+gy*(h-top-bottom)/6
        price=hi-(hi-lo)*gy/6
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{w-right}" y2="{yy:.1f}" stroke="#243247" stroke-width="1"/>')
        parts.append(f'<text x="8" y="{yy+4:.1f}" fill="#64748b" font-size="12" font-family="Arial">{price:.6g}</text>')
    for gx in range(9):
        xx=left+gx*plot_w/8
        parts.append(f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{h-bottom}" stroke="#182338" stroke-width="1"/>')

    # مناطق دعم ومقاومة حقيقية من آخر 40 شمعة.
    sy=y(support); ry=y(resistance)
    parts.append(f'<rect x="{left}" y="{sy-8:.1f}" width="{plot_w}" height="16" fill="#22c55e" opacity=".08"/>')
    parts.append(f'<line x1="{left}" y1="{sy:.1f}" x2="{w-right}" y2="{sy:.1f}" stroke="#22c55e" stroke-width="1.5" stroke-dasharray="7 6"/>')
    parts.append(f'<text x="{w-right+8}" y="{sy+4:.1f}" fill="#22c55e" font-size="12" font-family="Arial">دعم {support:.6g}</text>')
    parts.append(f'<rect x="{left}" y="{ry-8:.1f}" width="{plot_w}" height="16" fill="#ef4444" opacity=".08"/>')
    parts.append(f'<line x1="{left}" y1="{ry:.1f}" x2="{w-right}" y2="{ry:.1f}" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="7 6"/>')
    parts.append(f'<text x="{w-right+8}" y="{ry+4:.1f}" fill="#ef4444" font-size="12" font-family="Arial">مقاومة {resistance:.6g}</text>')

    # Fibonacci retracement من آخر موجة واضحة.
    if high_i>low_i:
        fib_hi,fib_lo=resistance,support
    else:
        fib_hi,fib_lo=support,resistance
    for ratio in (0.236,0.382,0.5,0.618,0.786):
        fv=fib_hi-(fib_hi-fib_lo)*ratio
        yy=y(fv)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{w-right}" y2="{yy:.1f}" stroke="#a78bfa" stroke-width="1" opacity=".48" stroke-dasharray="3 7"/>')
        parts.append(f'<text x="{w-right+8}" y="{yy+4:.1f}" fill="#a78bfa" font-size="11" font-family="Arial">Fib {ratio:.3g} {fv:.6g}</text>')

    # شموع.
    for i,(o,hh,ll,cl) in enumerate(candles):
        x=left+i*step+step/2
        parts.append(f'<line x1="{x:.1f}" y1="{y(hh):.1f}" x2="{x:.1f}" y2="{y(ll):.1f}" stroke="#cbd5e1" stroke-width="1"/>')
        topb=min(y(o),y(cl)); bh=max(2,abs(y(cl)-y(o)))
        fill="#22c55e" if cl>=o else "#ef4444"
        parts.append(f'<rect x="{x-body/2:.1f}" y="{topb:.1f}" width="{body:.1f}" height="{bh:.1f}" fill="{fill}" rx="1"/>')

    # خطوط EMA.
    for series,stroke,width in ((ema20,"#f59e0b",2),(ema200,"#38bdf8",2)):
        pts=[]
        for i,v in enumerate(series):
            if v is not None:
                x=left+i*step+step/2; pts.append(f"{x:.1f},{y(v):.1f}")
        if pts:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{stroke}" stroke-width="{width}" opacity=".9"/>')
    parts.append(f'<rect x="{left+8}" y="{top+8}" width="190" height="42" rx="8" fill="#0f172a" opacity=".92"/>')
    parts.append(f'<text x="{left+18}" y="{top+25}" fill="#f59e0b" font-size="12" font-family="Arial">EMA20</text>')
    parts.append(f'<text x="{left+75}" y="{top+25}" fill="#38bdf8" font-size="12" font-family="Arial">EMA200</text>')
    parts.append(f'<text x="{left+18}" y="{top+42}" fill="#94a3b8" font-size="11" font-family="Arial">اتجاه + مناطق سعرية</text>')

    # Trendline من قاع/قمة محلية إلى آخر إغلاق.
    start_i=low_i if low_i<n-1 else max(0,n-20)
    start_v=lows[start_i]
    end_i=n-1; end_v=closes[-1]
    parts.append(f'<line x1="{left+start_i*step+step/2:.1f}" y1="{y(start_v):.1f}" x2="{left+end_i*step+step/2:.1f}" y2="{y(end_v):.1f}" stroke="#fbbf24" stroke-width="2.5" opacity=".9"/>')
    parts.append(f'<circle cx="{left+start_i*step+step/2:.1f}" cy="{y(start_v):.1f}" r="4" fill="#fbbf24"/>')
    parts.append(f'<text x="{left+start_i*step+step/2+8:.1f}" y="{y(start_v)-8:.1f}" fill="#fbbf24" font-size="11" font-family="Arial">قاع الاتجاه</text>')

    # Entry / TP / SL.
    line_meta=[("الدخول",row.get("entry"),"#38bdf8"),("TP1",row.get("tp1"),"#22c55e"),("TP2",row.get("tp2"),"#22c55e"),("TP3",row.get("tp3"),"#22c55e"),("SL",row.get("sl"),"#ef4444")]
    for label,val,stroke in line_meta:
        if val is None: continue
        yy=y(val)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{w-right}" y2="{yy:.1f}" stroke="{stroke}" stroke-width="2.2" stroke-dasharray="10 5"/>')
        parts.append(f'<rect x="{w-right+4}" y="{yy-12:.1f}" width="116" height="23" rx="6" fill="#111827"/>')
        parts.append(f'<text x="{w-right+12}" y="{yy+4:.1f}" fill="{stroke}" font-size="12" font-family="Arial" font-weight="700">{label} {float(val):.6g}</text>')

    # منطقة الصفقة.
    entry=row.get("entry"); sl=row.get("sl"); tp3=row.get("tp3")
    if entry is not None and sl is not None and tp3 is not None:
        ya,yb=y(entry),y(tp3)
        topz=min(ya,yb); botz=max(ya,yb)
        parts.append(f'<rect x="{left}" y="{topz:.1f}" width="{plot_w}" height="{max(2,botz-topz):.1f}" fill="#22c55e" opacity=".045"/>')
        parts.append(f'<text x="{left+8}" y="{topz+16:.1f}" fill="#22c55e" font-size="11" font-family="Arial">منطقة الأهداف</text>')

    parts.append(f'<text x="{left}" y="{h-22}" fill="#64748b" font-size="12" font-family="Arial">Trading-style technical drawing • تحليل فني • {symbol} • {row.get("timeframe","15m")}</text>')
    return "".join(parts)

def _analysis_type(row):
    return "Price Action + شموع + EMA20/EMA200 + RSI + دعم/مقاومة"

def _hourly_analysis_for_markets():
    """اختيار تحليل واحد فقط كل ساعة على مستوى جميع الأسواق."""
    candidates=[]
    for market in DAILY_ANALYSIS_MARKETS:
        try:
            rows=_daily_analysis_for_market(market)
            if rows: candidates.append((market,rows[0]))
        except Exception:
            continue
    if not candidates: return None
    return max(candidates,key=lambda x: float(x[1].get("ai_pct") or 0))

def _hourly_analysis_worker():
    import time
    from datetime import datetime, timezone, timedelta
    tz=timezone(timedelta(hours=3))

    def generate_now():
        try:
            result=_hourly_analysis_for_markets()
            if not result:
                return
            market,row=result
            c=db()
            hour=datetime.now(tz).strftime("%Y-%m-%d %H:00")
            cutoff=(datetime.now(tz)-timedelta(hours=24)).strftime("%Y-%m-%d %H:00")
            c.execute("DELETE FROM hourly_analyses WHERE analysis_hour<?",(cutoff,))
            atype=_analysis_type(row)
            chart=_analysis_chart_svg(market,row,atype)
            c.execute("INSERT OR REPLACE INTO hourly_analyses(analysis_hour,market,symbol,side,timeframe,change_pct,ai_pct,entry,tp1,tp2,tp3,sl,analysis_type,chart_svg,title,body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(hour,market,row.get("symbol"),row.get("side"),row.get("timeframe","15m"),row.get("change_pct"),row.get("ai_pct"),row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),atype,chart,f"تحليل الساعة — {MARKETS[market]}",_analysis_body(market,row,1)+" تمت قراءة الشموع والسياق السعري ورسم المستويات على الشارت."))
            c.commit(); c.close()
        except Exception:
            pass

    # توليد أول تحليل فور تشغيل الخدمة، ثم تحديثه عند بداية كل ساعة.
    generate_now()
    while True:
        now=datetime.now(tz)
        target=(now+timedelta(hours=1)).replace(minute=0,second=10,microsecond=0)
        time.sleep(max(30,(target-now).total_seconds()))
        generate_now()

def _daily_analysis_for_market(market):
    if market=="spot": rows=_scan_spot_strategy("15m")
    elif market=="futures": rows=_scan_binance_futures("15m")
    else: rows=_scan_yahoo_market(market,"15m")
    return rows[:2]

def generate_daily_analyses(force=False):
    """يُبقي تحليلين فقط لكل سوق لليوم الحالي ويحذف الأيام السابقة نهائياً."""
    today=_riyadh_today()
    c=db()
    c.execute("DELETE FROM daily_analyses WHERE analysis_date<>?",(today,))
    c.commit(); c.close()
    if not force:
        c=db(); n=c.execute("SELECT COUNT(*) c FROM daily_analyses WHERE analysis_date=?",(today,)).fetchone()["c"]; c.close()
        if n>=len(DAILY_ANALYSIS_MARKETS)*2: return {"date":today,"created":0}
    created=0
    for market in DAILY_ANALYSIS_MARKETS:
        try: rows=_daily_analysis_for_market(market)
        except Exception: rows=[]
        c=db()
        for slot in (1,2):
            row=rows[slot-1] if len(rows)>=slot else None
            if row:
                atype=_analysis_type(row) if row else "Price Action + الشموع + EMA20/EMA200 + RSI + دعم/مقاومة"
                chart=_analysis_chart_svg(market,row,atype) if row else ""
                c.execute("INSERT INTO daily_analyses(analysis_date,market,slot,symbol,side,timeframe,change_pct,ai_pct,entry,tp1,tp2,tp3,sl,title,body,analysis_type,chart_svg) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(analysis_date,market,slot) DO UPDATE SET symbol=excluded.symbol,side=excluded.side,timeframe=excluded.timeframe,change_pct=excluded.change_pct,ai_pct=excluded.ai_pct,entry=excluded.entry,tp1=excluded.tp1,tp2=excluded.tp2,tp3=excluded.tp3,sl=excluded.sl,title=excluded.title,body=excluded.body,analysis_type=excluded.analysis_type,chart_svg=excluded.chart_svg,created_at=CURRENT_TIMESTAMP",
                (today,market,slot,row.get("symbol"),row.get("side"),row.get("timeframe","15m"),row.get("change_pct"),row.get("ai_pct"),row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),f"تحليل {slot} — {MARKETS[market]}",_analysis_body(market,row,slot)))
            else:
                c.execute("INSERT INTO daily_analyses(analysis_date,market,slot,timeframe,title,body) VALUES(?,?,?,?,?,?) ON CONFLICT(analysis_date,market,slot) DO UPDATE SET title=excluded.title,body=excluded.body,created_at=CURRENT_TIMESTAMP",
                (today,market,slot,"15m",f"تحليل {slot} — {MARKETS[market]}",_analysis_body(market,None,slot)))
            created+=1
        c.commit(); c.close()
    return {"date":today,"created":created}

def _daily_analysis_worker():
    import time
    from datetime import datetime, timezone, timedelta
    tz=timezone(timedelta(hours=3))
    while True:
        now=datetime.now(tz); target=now.replace(hour=3,minute=5,second=0,microsecond=0)
        if now>=target: target+=timedelta(days=1)
        time.sleep(max(60,(target-now).total_seconds()))
        try: generate_daily_analyses()
        except Exception: pass

@app.on_event("startup")
def startup():
    # ثبّت الإقلاع أولاً: قاعدة البيانات والصحة يجب أن تصبح جاهزة فوراً.
    # محركات التحليل تعمل بعد مهلة قصيرة حتى لا تزاحم health checks أثناء نشر نسخة جديدة.
    init_db()
    try:
        import threading, time
        def delayed_worker(fn, name, delay=45):
            def run():
                try:
                    time.sleep(delay)
                    fn()
                except Exception:
                    pass
            threading.Thread(target=run,daemon=True,name=name).start()
        # Keep startup lightweight on the 0.2 vCPU / 512 MB service.
        # Heavy analysis/outcome workers are triggered on demand by API routes.
        if os.getenv("ENABLE_BACKGROUND_ANALYSIS","0") == "1":
            delayed_worker(_crypto_analysis_worker,"crypto-analysis-15m")
            if "_spot_outcome_worker" in globals():
                delayed_worker(_spot_outcome_worker,"spot-signal-outcomes")
        # تم تحويل البوت بالكامل إلى Binance Spot؛ لا نشغّل عامل Futures القديم.
    except Exception as exc:
        print(f"[STARTUP] worker scheduling error: {type(exc).__name__}: {exc}", flush=True)

@app.get("/health")
def health(): return {"status":"ok","service":"trading-pro"}

@app.get("/api/system/servers")
def system_servers():
    """فحص كل مصادر البيانات الاحتياطية قبل الاعتماد عليها."""
    import time

    def probe(name,url,source=None):
        started=time.time()
        try:
            _json_get(url,timeout=4,source=source)
            return {"name":name,"server":url.split("/api/")[0] if "/api/" in url else url,"ok":True,"latency_ms":round((time.time()-started)*1000,1)}
        except Exception as exc:
            return {"name":name,"server":url.split("/api/")[0] if "/api/" in url else url,"ok":False,"latency_ms":round((time.time()-started)*1000,1),"error":str(exc)[:120]}

    spot=[probe("Binance Spot",base+"/api/v3/ping") for base in BINANCE_SPOT_BASES]
    yahoo=[]
    for base in YAHOO_BASES:
        source="yahoo1" if "query1" in base else "yahoo2"
        yahoo.append(probe("Yahoo",base+"/v8/finance/chart/BTC-USD?interval=1d&range=5d",source=source))

    fallbacks=[
        {"name":"TwelveData","configured":bool(DATA_SOURCE_KEYS["TWELVE_DATA_API_KEY"])},
        {"name":"AlphaVantage","configured":bool(DATA_SOURCE_KEYS["ALPHA_VANTAGE_API_KEY"])},
        {"name":"CoinMarketCap","configured":bool(DATA_SOURCE_KEYS["COINMARKETCAP_API_KEY"])}
    ]

    started=time.time()
    try:
        _binance_futures_json("https://fapi.binance.com/fapi/v1/ping",timeout=4)
        futures={"name":"Binance Futures","server":"https://fapi.binance.com","ok":True,"latency_ms":round((time.time()-started)*1000,1)}
    except Exception as exc:
        futures={"name":"Binance Futures","server":"https://fapi.binance.com","ok":False,"latency_ms":round((time.time()-started)*1000,1),"error":str(exc)[:120]}

    healthy_spot=[x for x in spot if x["ok"]]
    return {"ok":bool(healthy_spot or futures.get("ok") or any(x["ok"] for x in yahoo)),
            "active_spot_server":healthy_spot[0]["server"] if healthy_spot else None,
            "binance_spot":spot,"yahoo":yahoo,"configured_fallbacks":fallbacks,"binance_futures":futures}

@app.get("/robots.txt",response_class=PlainTextResponse)
def robots():
    return PlainTextResponse("""User-agent: *
Allow: /
Disallow: /admin
Disallow: /api/

Sitemap: https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/sitemap.xml
""",media_type="text/plain")

@app.get("/sitemap.xml",response_class=PlainTextResponse)
def sitemap():
    p=BASE/"static"/"sitemap.xml"
    if p.exists():
        return PlainTextResponse(p.read_text(encoding="utf-8"),media_type="application/xml")
    return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',media_type="application/xml")


@app.get("/",response_class=HTMLResponse)
def home(request:Request): return page(request,"الرئيسية")

@app.get("/analysis",response_class=HTMLResponse)
def analysis_page(request:Request): return page(request,"التحليل الفني")

@app.get("/strategy",response_class=HTMLResponse)
def strategy_page(request:Request):
    response=FileResponse(BASE/"static"/"strategy.html",media_type="text/html")
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"]="no-cache"
    response.headers["Expires"]="0"
    return response

@app.get("/market/{market}",response_class=HTMLResponse)
def market_page(request:Request,market:str):
    return page(request,MARKETS[market]) if market in MARKETS else RedirectResponse("/",status_code=303)

@app.get("/blog",response_class=HTMLResponse)
def blog_page(request:Request): return page(request,"مدونة التداول")

@app.get("/blog/{slug}",response_class=HTMLResponse)
def blog_article_page(request:Request,slug:str): return page(request,"مدونة التداول | "+slug.replace("-"," "))

@app.get("/forum",response_class=HTMLResponse)
def forum(request:Request): return RedirectResponse("/blog",status_code=303)

@app.get("/account",response_class=HTMLResponse)
def account(request:Request): return page(request,"حسابي")

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request): return page(request,"تسجيل الدخول")

@app.get("/register",response_class=HTMLResponse)
def register_page(request:Request): return page(request,"إنشاء حساب")

@app.get("/admin/login",response_class=HTMLResponse)
def admin_login_page(request:Request): return page(request,"دخول الإدارة")

@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request):
    return page(request,"الإدارة")

@app.post("/api/register")
def register(request:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...)):
    name=name.strip(); email=email.strip().lower()
    if len(name)<2 or len(password)<6 or "@" not in email:
        return JSONResponse({"ok":False,"message":"تحقق من البيانات وكلمة المرور 6 أحرف على الأقل"},status_code=400)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,?)",(name,email,password_hash(password),1 if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]==0 else 0)); c.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError:
        c.close(); return JSONResponse({"ok":False,"message":"البريد مستخدم مسبقاً"},status_code=409)
    c.close(); request.session["user_id"]=uid
    return {"ok":True,"message":"تم إنشاء الحساب"}

@app.post("/api/login")
def login(request:Request,email:str=Form(...),password:str=Form(...)):
    c=db(); row=c.execute("SELECT * FROM users WHERE email=?",(email.strip().lower(),)).fetchone(); c.close()
    if not row or not password_ok(password,row["password_hash"]):
        return JSONResponse({"ok":False,"message":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
    request.session["user_id"]=row["id"]; return {"ok":True,"message":"تم تسجيل الدخول"}

@app.post("/api/logout")
def logout(request:Request): request.session.clear(); return {"ok":True}

@app.get("/api/me")
def me(request:Request):
    u=current_user(request)
    if not u:return {"user":None}
    c=db(); row=c.execute("SELECT * FROM user_settings WHERE user_id=?",(u["id"],)).fetchone()
    if not row:
        c.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)",(u["id"],)); c.commit()
        row=c.execute("SELECT * FROM user_settings WHERE user_id=?",(u["id"],)).fetchone()
    c.close()
    return {"user":u,"settings":dict(row) if row else {}}

@app.post("/api/account/profile")
def update_profile(request:Request,name:str=Form(...),email:str=Form(...)):
    u=current_user(request)
    if not u:return JSONResponse({"ok":False,"message":"يجب تسجيل الدخول"},status_code=401)
    name=name.strip(); email=email.strip().lower()
    if len(name)<2 or "@" not in email:return JSONResponse({"ok":False,"message":"تحقق من الاسم والبريد"},status_code=400)
    c=db()
    try:
        c.execute("UPDATE users SET name=?,email=? WHERE id=?",(name,email,u["id"])); c.commit()
    except sqlite3.IntegrityError:
        c.close(); return JSONResponse({"ok":False,"message":"البريد مستخدم مسبقاً"},status_code=409)
    c.close(); return {"ok":True,"message":"تم تحديث بيانات الحساب"}

@app.post("/api/account/password")
def update_password(request:Request,current_password:str=Form(...),new_password:str=Form(...)):
    u=current_user(request)
    if not u:return JSONResponse({"ok":False,"message":"يجب تسجيل الدخول"},status_code=401)
    if len(new_password)<6:return JSONResponse({"ok":False,"message":"كلمة المرور الجديدة 6 أحرف على الأقل"},status_code=400)
    c=db(); row=c.execute("SELECT password_hash FROM users WHERE id=?",(u["id"],)).fetchone()
    if not row or not password_ok(current_password,row["password_hash"]):
        c.close(); return JSONResponse({"ok":False,"message":"كلمة المرور الحالية غير صحيحة"},status_code=400)
    c.execute("UPDATE users SET password_hash=? WHERE id=?",(password_hash(new_password),u["id"])); c.commit(); c.close()
    return {"ok":True,"message":"تم تغيير كلمة المرور"}

@app.post("/api/account/settings")
def update_account_settings(request:Request):
    u=current_user(request)
    if not u:return JSONResponse({"ok":False,"message":"يجب تسجيل الدخول"},status_code=401)
    allowed={"language","theme","accent","font_size","default_market","default_timeframe","notifications","sounds","card_style"}
    data={k:request.query_params.get(k) for k in allowed if request.query_params.get(k) is not None}
    if "notifications" in data:data["notifications"]=1 if data["notifications"] in ("1","true","on") else 0
    if "sounds" in data:data["sounds"]=1 if data["sounds"] in ("1","true","on") else 0
    c=db(); c.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)",(u["id"],))
    if data:
        cols=",".join([k+"=?" for k in data]); vals=list(data.values())+[u["id"]]
        c.execute("UPDATE user_settings SET "+cols+" WHERE user_id=?",vals)
    c.commit(); c.close()
    return {"ok":True,"message":"تم حفظ إعدادات الحساب"}

DEFAULT_SETTINGS = {
    "site_name":"التداول الذكي PRO",
    "language":"ar",
    "accent":"#00c896",
    "accent2":"#6c63ff",
    "default_theme":"light",
    "ticker_enabled":"1",
    "ticker_text":"عاجل | فرص السوق وتحديثات التداول",
    "maintenance":"0",
    "footer_text":"منصة التداول الذكي PRO",
    "card_style":"compact"
}

def site_settings():
    c=db()
    rows=c.execute("SELECT key,value FROM site_settings").fetchall()
    c.close()
    out=dict(DEFAULT_SETTINGS)
    out.update({r["key"]:r["value"] for r in rows})
    return out

def save_site_settings(values):
    c=db()
    for key,value in values.items():
        if key in DEFAULT_SETTINGS:
            c.execute("INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))
    c.commit(); c.close()

def admin_user(request:Request):
    u=current_user(request)
    return u if u and u.get("is_admin") else None

@app.get("/api/settings")
def get_settings():
    return {"ok":True,"settings":site_settings()}

@app.get("/api/admin/settings")
def admin_settings(request:Request):
    if not admin_user(request):
        return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    return {"ok":True,"settings":site_settings()}

@app.post("/api/admin/settings")
def update_settings(request:Request):
    if not admin_user(request):
        return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    allowed=set(DEFAULT_SETTINGS)
    data={}
    for key in allowed:
        value=request.query_params.get(key)
        if value is not None: data[key]=value
    save_site_settings(data)
    return {"ok":True,"message":"تم حفظ إعدادات الموقع","settings":site_settings()}

@app.get("/api/message")
def active_message():
    c=db(); row=c.execute("SELECT id,title,body FROM messages WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone(); c.close()
    return {"message":dict(row) if row else None}

@app.get("/api/trades/{market}")
def trades(market:str,timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    c=db()
    rows=c.execute("""SELECT id,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl,status,created_at
    FROM trades WHERE market=? AND timeframe=? AND status='open'
    ORDER BY change_pct DESC,COALESCE(ai_pct,0) DESC,id ASC""",(market,timeframe)).fetchall()
    c.close(); out=[]
    for rank,row in enumerate(rows,1):
        x=dict(row); x["rank"]=rank; x["medal"]="🥇" if rank==1 else "🥈" if rank==2 else "🥉" if rank==3 else ""; out.append(x)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"trades":out}

@app.post("/api/support")
def support(request:Request,name:str=Form(...),email:str=Form(...),body:str=Form(...)):
    u=current_user(request); c=db()
    c.execute("INSERT INTO support_messages(user_id,name,email,body) VALUES(?,?,?,?)",(u["id"] if u else None,name.strip(),email.strip().lower(),body.strip()))
    c.commit(); c.close(); return {"ok":True,"message":"تم إرسال رسالتك للدعم"}


# ===== Unified visual analysis =====
# فريمات التحليل المرئي: نركز على الفريمات التي تعطي قراراً عملياً
# بدون تحميل الخدمة بفحص كل الفريمات في كل دورة.
MANUAL_ANALYSIS_TIMEFRAMES=("15m","1h","4h")
MANUAL_ANALYSIS_INTERVAL_MINUTES=30

def _analysis_schools(row):
    return ["Price Action","الشموع اليابانية","SMC","ICT","Fibonacci","EMA / RSI","الدعم والمقاومة"]

def _manual_analysis_body(market,row):
    if not row: return f"لا توجد فرصة مكتملة الشروط حالياً في {MARKETS[market]}."
    return (f"{row.get('symbol')} — {'شراء' if row.get('side')=='BUY' else 'بيع'}. تمت قراءة الاتجاه والسلوك السعري والزخم "
            f"والمناطق الرئيسية عبر عدة مدارس. الفريم الأساسي {row.get('timeframe','15m')}، وقوة التوافق "
            f"{float(row.get('ai_pct') or 0):.0f}%.")

def _manual_analysis_image(market,row,schools):
    symbol=str(row.get("symbol") or market); side=str(row.get("side") or "BUY"); tf=str(row.get("timeframe") or "15m")
    accent="#22c55e" if side.upper()=="BUY" else "#ef4444"
    def esc(v): return str(v).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
    def num(v):
        try:return f"{float(v):.8g}"
        except Exception:return "—"
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 600" role="img" aria-label="{esc(symbol)} تحليل فني">',
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
        f'<text x="55" y="565" fill="#475569" font-size="12" font-family="Arial">تحليل متعدد المدارس • {esc(tf)} • لا يتم اعتماد الفرصة عند تعارض الإشارات</text>','</svg>']
    return "".join(parts)

def generate_manual_analyses():
    """مولد التحليل المرئي مع تشغيل أولي حقيقي عند فراغ الكاش."""
    candidates=[]
    cache_empty=True

    # أولاً نقرأ الكاش حتى يبقى الطلب خفيفاً. إذا كان الكاش فارغاً بالكامل،
    # نعمل bootstrap محدوداً لبايننس فقط مرة واحدة حتى لا تبقى الصفحة عالقة على
    # "لا توجد فرصة" بعد النشر الأول.
    for market in MARKETS:
        for tf in MANUAL_ANALYSIS_TIMEFRAMES:
            try:
                if market=="spot":
                    rows,_=_cached_scan(market,tf,lambda tf=tf: _scan_spot_strategy(tf,limit_symbols=8))
                elif market=="futures":
                    rows,_=_cached_scan(market,tf,lambda tf=tf: _scan_binance_futures(tf))
                else:
                    rows,_=_cached_scan(market,tf,lambda market=market,tf=tf: _scan_yahoo_market(market,tf))
                if rows:
                    cache_empty=False
                for row in (rows or [])[:3]:
                    row=dict(row); row["timeframe"]=tf
                    ai=float(row.get("ai_pct") or 0)
                    if ai >= 60:
                        candidates.append((market,row))
            except Exception:
                continue

    # Bootstrap واحد فقط إذا لم يوجد أي كاش: بيانات Binance الحقيقية، وبعدد محدود
    # من الرموز، ثم نعيد بناء الصور من النتائج. لا نستخدم بيانات وهمية.
    if not candidates and cache_empty:
        for market in ("spot","futures"):
            for tf in MANUAL_ANALYSIS_TIMEFRAMES:
                try:
                    if market=="spot":
                        rows=_scan_spot_strategy(tf,limit_symbols=8)
                    else:
                        rows=_scan_binance_futures(tf)
                    for row in (rows or [])[:3]:
                        row=dict(row); row["timeframe"]=tf
                        if float(row.get("ai_pct") or 0) >= 60:
                            candidates.append((market,row))
                except Exception:
                    continue

    # منع تكرار نفس الأصل، واختيار عدد قليل من الصفقات المدروسة.
    candidates.sort(
        key=lambda x:(float(x[1].get("ai_pct") or 0),
                      float(x[1].get("change_pct") or 0)),
        reverse=True
    )
    unique=[]
    seen=set()
    for market,row in candidates:
        key=(market,str(row.get("symbol")))
        if key in seen:
            continue
        seen.add(key)
        unique.append((market,row))
        if len(unique)>=6:
            break

    c=db()
    c.execute("DELETE FROM manual_analyses")
    for market,row in unique:
        schools=_analysis_schools(row)
        c.execute(
            "INSERT INTO manual_analyses(market,symbol,side,timeframe,change_pct,ai_pct,entry,tp1,tp2,tp3,sl,title,body,schools,analysis_image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                market,row.get("symbol"),row.get("side"),row.get("timeframe","15m"),
                row.get("change_pct"),row.get("ai_pct"),row.get("entry"),
                row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),
                f"تحليل {MARKETS[market]}",
                _manual_analysis_body(market,row),
                " + ".join(schools),
                _manual_analysis_image(market,row,schools)
            )
        )
    c.commit()
    n=len(unique)
    c.close()
    return {"ok":True,"count":n}

@app.get("/api/analysis/manual")
def manual_analyses():
    c=db()
    rows=c.execute("SELECT * FROM manual_analyses ORDER BY ai_pct DESC,id DESC").fetchall()
    c.close()
    if rows:
        return {"timeframes":MANUAL_ANALYSIS_TIMEFRAMES,"analyses":[dict(r) for r in rows],"scanning":False}

    # أول زيارة بعد النشر: لا نترك الصفحة فارغة؛ شغّل التوليد مرة بالخلفية.
    import threading
    if not getattr(manual_analyses,"_refreshing",False):
        manual_analyses._refreshing=True
        def refresh():
            try:
                generate_manual_analyses()
            finally:
                manual_analyses._refreshing=False
        threading.Thread(target=refresh,daemon=True,name="manual-analysis-on-demand").start()

    return {
        "timeframes":MANUAL_ANALYSIS_TIMEFRAMES,
        "analyses":[],
        "scanning":True,
        "message":"جاري فحص الأسواق وإعداد صور التحليل..."
    }

@app.post("/api/analysis/manual/refresh")
def refresh_manual_analyses(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    return generate_manual_analyses()


def _pa_pivots(candles,window=3):
    highs=[]; lows=[]
    n=len(candles)
    for i in range(window,n-window):
        h=candles[i]["high"]; l=candles[i]["low"]
        if h>=max(x["high"] for x in candles[i-window:i+window+1]):
            highs.append(i)
        if l<=min(x["low"] for x in candles[i-window:i+window+1]):
            lows.append(i)
    return highs,lows

def _pa_analysis(candles):
    n=len(candles)
    highs,lows=_pa_pivots(candles,3)
    price=candles[-1]["close"]
    recent_h=highs[-8:]; recent_l=lows[-8:]
    sh=[(i,candles[i]["high"]) for i in recent_h]
    sl=[(i,candles[i]["low"]) for i in recent_l]
    tol=max(price*0.006, (max(x["high"] for x in candles[-60:])-min(x["low"] for x in candles[-60:]))*0.025)
    resistance=max([v for _,v in sh[-5:]] or [max(x["high"] for x in candles[-30:])])
    support=min([v for _,v in sl[-5:]] or [min(x["low"] for x in candles[-30:])])
    patterns=[]; drawings=[]

    def add(name,kind,score,detail=""):
        patterns.append({"name":name,"kind":kind,"confidence":round(max(50,min(95,score))),"detail":detail})

    # الاتجاه من آخر قمتين وقاعين، بدون مؤشرات.
    trend="عرضي"
    if len(sh)>=2 and len(sl)>=2:
        if sh[-1][1]>sh[-2][1] and sl[-1][1]>sl[-2][1]: trend="صاعد"
        elif sh[-1][1]<sh[-2][1] and sl[-1][1]<sl[-2][1]: trend="هابط"
    add("اتجاه سعري "+trend,"trend",72)

    # خطوط الاتجاه من آخر نقطتين واضحتين.
    if len(sh)>=2:
        drawings.append({"type":"line","x1":sh[-2][0],"y1":sh[-2][1],"x2":sh[-1][0],"y2":sh[-1][1],"label":"خط مقاومة/اتجاه"})
    if len(sl)>=2:
        drawings.append({"type":"line","x1":sl[-2][0],"y1":sl[-2][1],"x2":sl[-1][0],"y2":sl[-1][1],"label":"خط دعم/اتجاه"})

    # Double Top / Bottom.
    if len(sh)>=2 and abs(sh[-1][1]-sh[-2][1])<=tol:
        add("قمة مزدوجة","double_top",82,"قمتان متقاربتان سعرياً")
        drawings.append({"type":"zone","x1":sh[-2][0],"x2":sh[-1][0],"y1":max(sh[-1][1],sh[-2][1])-tol,"y2":max(sh[-1][1],sh[-2][1])+tol,"label":"Double Top"})
    if len(sl)>=2 and abs(sl[-1][1]-sl[-2][1])<=tol:
        add("قاع مزدوج","double_bottom",82,"قاعان متقاربان سعرياً")
        drawings.append({"type":"zone","x1":sl[-2][0],"x2":sl[-1][0],"y1":min(sl[-1][1],sl[-2][1])-tol,"y2":min(sl[-1][1],sl[-2][1])+tol,"label":"Double Bottom"})

    # Head & Shoulders / inverse.
    if len(sh)>=3:
        a,b,c=sh[-3],sh[-2],sh[-1]
        if b[1]>a[1] and b[1]>c[1] and abs(a[1]-c[1])<=tol*1.4:
            add("نموذج الرأس والكتفين","head_shoulders",90,"كتفان متقاربان والرأس أعلى")
            drawings += [{"type":"line","x1":a[0],"y1":a[1],"x2":b[0],"y2":b[1],"label":"الرأس والكتف"},
                         {"type":"line","x1":b[0],"y1":b[1],"x2":c[0],"y2":c[1],"label":"الرأس والكتف"}]
    if len(sl)>=3:
        a,b,c=sl[-3],sl[-2],sl[-1]
        if b[1]<a[1] and b[1]<c[1] and abs(a[1]-c[1])<=tol*1.4:
            add("نموذج الرأس والكتفين المعكوس","inverse_head_shoulders",90,"كتفان متقاربان والرأس أسفل")
            drawings += [{"type":"line","x1":a[0],"y1":a[1],"x2":b[0],"y2":b[1],"label":"Inverse H&S"},
                         {"type":"line","x1":b[0],"y1":b[1],"x2":c[0],"y2":c[1],"label":"Inverse H&S"}]

    # Triangle / wedge / channel based on slope convergence.
    if len(sh)>=3 and len(sl)>=3:
        xh=[p[0] for p in sh[-3:]]; yh=[p[1] for p in sh[-3:]]
        xl=[p[0] for p in sl[-3:]]; yl=[p[1] for p in sl[-3:]]
        hs=(yh[-1]-yh[0])/max(1,xh[-1]-xh[0]); lslope=(yl[-1]-yl[0])/max(1,xl[-1]-xl[0])
        span_h=abs(yh[0]-yl[0]); span_l=abs(yh[-1]-yl[-1])
        if span_h>0 and span_l<span_h*0.72:
            if hs<0 and lslope>0: name="مثلث متماثل"; kind="sym_triangle"
            elif hs<0 and abs(lslope)<abs(hs)*0.35: name="مثلث هابط"; kind="descending_triangle"
            elif abs(hs)<abs(lslope)*0.35 and lslope>0: name="مثلث صاعد"; kind="ascending_triangle"
            else: name="مثلث تقاربي"; kind="triangle"
            add(name,kind,84,"تقارب خطي بين القمم والقيعان")
            drawings += [{"type":"line","x1":xh[0],"y1":yh[0],"x2":xh[-1],"y2":yh[-1],"label":name},
                         {"type":"line","x1":xl[0],"y1":yl[0],"x2":xl[-1],"y2":yl[-1],"label":name}]
        elif hs*lslope>0 and abs(hs-lslope)>0:
            add("وتد سعري","wedge",80,"خطا القمم والقيعان يتحركان في اتجاه واحد")
            drawings += [{"type":"line","x1":xh[0],"y1":yh[0],"x2":xh[-1],"y2":yh[-1],"label":"Wedge"},
                         {"type":"line","x1":xl[0],"y1":yl[0],"x2":xl[-1],"y2":yl[-1],"label":"Wedge"}]
        elif abs(hs-lslope)<=max(abs(hs),abs(lslope),price*0.00001)*0.35:
            add("قناة سعرية","channel",78,"خطا اتجاه متوازيان تقريباً")
            drawings += [{"type":"line","x1":xh[0],"y1":yh[0],"x2":xh[-1],"y2":yh[-1],"label":"قناة"},
                         {"type":"line","x1":xl[0],"y1":yl[0],"x2":xl[-1],"y2":yl[-1],"label":"قناة"}]

    # Breakout / breakdown / retest.
    last_close=candles[-1]["close"]; prev_close=candles[-2]["close"]
    if prev_close<=resistance and last_close>resistance:
        add("اختراق مقاومة","breakout",91,"إغلاق شمعة فوق المقاومة")
    elif prev_close>=support and last_close<support:
        add("كسر دعم","breakdown",91,"إغلاق شمعة تحت الدعم")
    elif abs(last_close-resistance)/max(price,1)<0.002:
        add("إعادة اختبار مقاومة","retest",76,"السعر يختبر منطقة المقاومة")
    elif abs(last_close-support)/max(price,1)<0.002:
        add("إعادة اختبار دعم","retest",76,"السعر يختبر منطقة الدعم")

    # شموع حقيقية.
    o,h,l,c=candles[-1]["open"],candles[-1]["high"],candles[-1]["low"],candles[-1]["close"]
    body=abs(c-o); rng=max(h-l,1e-12); upper=h-max(o,c); lower=min(o,c)-l
    if body/rng<0.12: add("دوجي","candlestick",72,"تردد سعري")
    if lower>body*2 and upper<body*1.2: add("Pin Bar شرائية","candlestick",79,"ذيل سفلي طويل")
    if upper>body*2 and lower<body*1.2: add("Pin Bar بيعية","candlestick",79,"ذيل علوي طويل")
    po,pc=candles[-2]["open"],candles[-2]["close"]
    if pc<po and c>o and c>=po and o<=pc: add("ابتلاع شرائي","engulfing",84,"شمعة تغطي جسم السابقة")
    if pc>po and c<o and c<=po and o>=pc: add("ابتلاع بيعي","engulfing",84,"شمعة تغطي جسم السابقة")

    # Liquidity / equal highs & lows.
    if len(sh)>=2 and abs(sh[-1][1]-sh[-2][1])<=tol:
        add("سيولة فوق القمم المتساوية","liquidity",75,"Equal Highs")
    if len(sl)>=2 and abs(sl[-1][1]-sl[-2][1])<=tol:
        add("سيولة تحت القيعان المتساوية","liquidity",75,"Equal Lows")

    # Fibonacci من آخر موجة كبيرة.
    if sh and sl:
        hi=max(sh[-1][1],sl[-1][1]); lo=min(sh[-1][1],sl[-1][1])
        if hi>lo:
            drawings.append({"type":"fib","hi":hi,"lo":lo,"label":"Fibonacci 0.382 / 0.5 / 0.618"})

    # اختيار الاتجاه والصفقة من السعر والبنية فقط.
    bullish=sum(1 for p in patterns if p["kind"] in {"breakout","inverse_head_shoulders","double_bottom","engulfing"} and p["confidence"]>=80)
    bearish=sum(1 for p in patterns if p["kind"] in {"breakdown","head_shoulders","double_top"} and p["confidence"]>=80)
    if bullish and not bearish: side="BUY"
    elif bearish and not bullish: side="SELL"
    elif trend=="صاعد" and price>support*(1.002): side="BUY"
    elif trend=="هابط" and price<resistance*(0.998): side="SELL"
    else: side="WAIT"

    stop_candidates=[v for _,v in sl if v<price] if side=="BUY" else [v for _,v in sh if v>price]
    stop=(max(stop_candidates) if side=="BUY" and stop_candidates else min(stop_candidates) if side=="SELL" and stop_candidates else (support if side=="BUY" else resistance))
    risk=abs(price-stop)
    if risk<=0 or risk/price>0.06: risk=price*0.015
    entry=price
    if side=="BUY":
        sl_price=entry-risk; tp1=entry+risk; tp2=entry+risk*2; tp3=entry+risk*3
    elif side=="SELL":
        sl_price=entry+risk; tp1=entry-risk; tp2=entry-risk*2; tp3=entry-risk*3
    else:
        sl_price=entry; tp1=entry; tp2=entry; tp3=entry

    score=55
    if trend in ("صاعد","هابط"): score+=10
    score+=min(25,max([p["confidence"] for p in patterns],default=50)-50)*0.6
    if side=="WAIT": score=min(score,59)
    score=round(max(50,min(95,score)),1)
    return {
        "side":side,"trend":trend,"support":support,"resistance":resistance,
        "entry":entry,"sl":sl_price,"tp1":tp1,"tp2":tp2,"tp3":tp3,
        "confidence":score,"patterns":patterns[-8:],"drawings":drawings[-12:]
    }

def _pa_svg(symbol,candles,a):
    w,h=1180,690; left,right,top,bottom=70,150,55,75
    vals=[x["high"] for x in candles]+[x["low"] for x in candles]
    for v in (a["entry"],a["tp1"],a["tp2"],a["tp3"],a["sl"],a["support"],a["resistance"]): vals.append(float(v))
    lo=min(vals); hi=max(vals); pad=max((hi-lo)*0.08,hi*0.002); lo-=pad; hi+=pad
    n=len(candles); pw=w-left-right; step=pw/max(n,1); body=max(2,step*.58)
    def X(i): return left+i*step+step/2
    def Y(v): return top+(hi-float(v))/(hi-lo)*(h-top-bottom)
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d"><rect width="100%%" height="100%%" rx="18" fill="#08111f"/>'%(w,h)]
    parts.append('<text x="%d" y="30" fill="#fff" font-size="21" font-family="Arial" font-weight="700">%s • تحليل فني 15m</text>'%(left,symbol))
    parts.append('<text x="%d" y="48" fill="#94a3b8" font-size="12" font-family="Arial">Price Action • نماذج سعرية • دعم ومقاومة • Fibonacci • بدون مؤشرات</text>'%left)
    for z in range(7):
        yy=top+z*(h-top-bottom)/6; pv=hi-(hi-lo)*z/6
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1e293b"/><text x="8" y="%.1f" fill="#64748b" font-size="11" font-family="Arial">%.6g</text>'%(left,yy,w-right,yy,yy+4,pv))
    for i,k in enumerate(candles):
        xx=X(i); up=k["close"]>=k["open"]; col="#22c55e" if up else "#ef4444"
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#cbd5e1"/>'%(xx,Y(k["high"]),xx,Y(k["low"])))
        yy=min(Y(k["open"]),Y(k["close"])); bh=max(2,abs(Y(k["close"])-Y(k["open"])))
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="1"/>'%(xx-body/2,yy,body,bh,col))
    sy=Y(a["support"]); ry=Y(a["resistance"])
    parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#22c55e" stroke-width="2" stroke-dasharray="7 5"/><text x="%d" y="%.1f" fill="#22c55e" font-size="12" font-family="Arial">دعم %.6g</text>'%(left,sy,w-right,sy,w-right+8,sy+4,a["support"]))
    parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ef4444" stroke-width="2" stroke-dasharray="7 5"/><text x="%d" y="%.1f" fill="#ef4444" font-size="12" font-family="Arial">مقاومة %.6g</text>'%(left,ry,w-right,ry,w-right+8,ry+4,a["resistance"]))
    for d in a["drawings"]:
        if d["type"]=="line":
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#fbbf24" stroke-width="2.5" opacity=".9"/><text x="%.1f" y="%.1f" fill="#fbbf24" font-size="11" font-family="Arial">%s</text>'%(X(d["x1"]),Y(d["y1"]),X(d["x2"]),Y(d["y2"]),X(d["x2"])-80,Y(d["y2"])-7,d["label"]))
        elif d["type"]=="zone":
            y1=Y(d["y1"]); y2=Y(d["y2"])
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#a78bfa" opacity=".12"/>'%(X(d["x1"]),min(y1,y2),max(4,X(d["x2"])-X(d["x1"])),abs(y2-y1)+4))
        elif d["type"]=="fib":
            hi2=d["hi"]; lo2=d["lo"]
            for r in (.382,.5,.618):
                fv=hi2-(hi2-lo2)*r; yy=Y(fv)
                parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#a78bfa" stroke-dasharray="3 6" opacity=".65"/><text x="%d" y="%.1f" fill="#a78bfa" font-size="11" font-family="Arial">Fib %.3g %.6g</text>'%(left,yy,w-right,yy,w-right+8,yy+4,r,fv))
    meta=[("الدخول",a["entry"],"#38bdf8"),("TP1",a["tp1"],"#22c55e"),("TP2",a["tp2"],"#22c55e"),("TP3",a["tp3"],"#22c55e"),("SL",a["sl"],"#ef4444")]
    for lab,v,col in meta:
        yy=Y(v)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="2" stroke-dasharray="10 5"/><rect x="%d" y="%.1f" width="132" height="22" rx="6" fill="#111827"/><text x="%d" y="%.1f" fill="%s" font-size="11" font-family="Arial" font-weight="700">%s %.6g</text>'%(left,yy,w-right,yy,col,w-right+3,yy-11,w-right+10,yy+4,col,lab,v))
    side_ar="شراء" if a["side"]=="BUY" else "بيع" if a["side"]=="SELL" else "انتظار"
    parts.append('<rect x="%d" y="55" width="220" height="42" rx="9" fill="#111827"/><text x="%d" y="73" fill="#fff" font-size="13" font-family="Arial">الاتجاه: %s</text><text x="%d" y="90" fill="#94a3b8" font-size="11" font-family="Arial">ثقة النموذج: %.0f%%</text>'%(left+10,left+22,side_ar,left+22,a["confidence"]))
    parts.append('<text x="%d" y="%d" fill="#64748b" font-size="11" font-family="Arial">تحليل آلي مبني على الشموع المغلقة فقط • ليس ضماناً للربح</text>'%(left,h-22))
    return "".join(parts)


# ===== BINANCE SPOT OPPORTUNITY STRATEGY =====
BINANCE_SCANNER_EXCLUDED={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","BUSDUSDT"}
BINANCE_SCANNER_MIN_VOLUME=float(os.getenv("BINANCE_SCANNER_MIN_VOLUME","1000000"))
BINANCE_SCANNER_TIMEFRAME=os.getenv("BINANCE_SCANNER_TIMEFRAME","15m")

def _binance_json(url,timeout=6,timeframe=None,spot_fallback=True):
    """Binance Spot helper with automatic official endpoint failover."""
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json"}
    if "api.binance.com" not in url:
        return _json_get(url,timeout=timeout,headers=headers)
    path=url.replace("https://api.binance.com","",1)
    errors=[]
    # Official Binance Spot endpoints; try the next source on any connection/API failure.
    for base in (
        "https://api.binance.com",
        "https://api-gcp.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api4.binance.com",
        "https://data-api.binance.vision",
    ):
        try:
            return _json_get(base+path,timeout=timeout,headers=headers)
        except Exception as exc:
            errors.append(str(exc)[:100])
    raise RuntimeError("Binance sources unavailable: "+" | ".join(errors[-3:]))


def _binance_spot_strategy_scan():
    """Dedicated Binance Spot page: raw order-flow + price action, no indicators."""
    from datetime import datetime, timezone
    rows=_scan_spot_strategy(BINANCE_SCANNER_TIMEFRAME,20)
    opportunities=[]
    for r in rows:
        opportunities.append({
            "type":"spot_order_flow",
            "symbol":r.get("symbol"),
            "side":"BUY",
            "status":"فرصة شراء سبوت",
            "direction":"شراء سبوت فقط",
            "timeframe":r.get("timeframe",BINANCE_SCANNER_TIMEFRAME),
            "price":r.get("entry"),
            "entry":r.get("entry"),
            "sl":r.get("sl"),
            "tp1":r.get("tp1"),
            "tp2":r.get("tp2"),
            "tp3":r.get("tp3"),
            "change_15m":r.get("change_pct",0),
            "change_24h":r.get("change_24h",0),
            "volume":r.get("volume",0),
            "volume_ratio":r.get("volume_ratio",0),
            "score":r.get("score",0),
            "reasons":r.get("reasons") or r.get("patterns") or [],
            "spread_pct":r.get("spread_pct",0),
            "book_imbalance":r.get("book_imbalance",50),
            "buy_pressure":r.get("buy_pressure",50),
            "taker_buy_share":r.get("taker_buy_share",50),
            "breakout":r.get("breakout",False),
            "retest":r.get("retest",False),
            "risk":"إشارة ورقية قابلة للقياس؛ لا يوجد ضمان ربح.",
            "signal_score":r.get("score",0),
            "liquidity_sweep":r.get("liquidity_sweep",False),
            "reclaim":r.get("reclaim",False),
            "flow_confirmations":r.get("flow_confirmations",0)
        })
    return {
        "ok":True,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "market":"spot",
        "timeframe":BINANCE_SCANNER_TIMEFRAME,
        "method":"edge_scanner_price_action_order_flow",
                "indicators":False,
        "assumptions":{
            "min_volume":BINANCE_SCANNER_MIN_VOLUME,
            "excluded_stablecoins":sorted(BINANCE_SCANNER_EXCLUDED)
        },
        "opportunities":opportunities
    }


def _binance_futures_private_status():
    """Read-only Binance USDⓈ-M Futures connectivity and USDT balance."""
    import os, time, hmac, hashlib
    from urllib.parse import urlencode
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        return {"connected":False,"configured":False,"futures_enabled":False,"message":"مفاتيح Binance غير مهيأة في السيرفس"}
    ts=int(time.time()*1000)
    q=urlencode({"timestamp":ts,"recvWindow":5000})
    sig=hmac.new(secret.encode(),q.encode(),hashlib.sha256).hexdigest()
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json","X-MBX-APIKEY":key}
    errors=[]
    for base in (
        "https://fapi.binance.com",
        "https://fapi1.binance.com",
        "https://fapi2.binance.com",
        "https://fapi3.binance.com",
        "https://fapi4.binance.com",
    ):
        try:
            data=_json_get(base+"/fapi/v3/balance?"+q+"&signature="+sig,timeout=8,headers=headers)
            if not isinstance(data,list):
                return {"connected":False,"configured":True,"futures_enabled":False,"message":"Binance Futures أعاد استجابة غير متوقعة","detail":str(data)[:180]}
            usdt=next((b for b in data if str(b.get("asset"))=="USDT"),None)
            balance=float((usdt or {}).get("balance") or 0)
            available=float((usdt or {}).get("availableBalance") or 0)
            return {
                "connected":True,"configured":True,"futures_enabled":True,
                "message":"Binance Futures متصل",
                "balance_usdt":balance,"available_usdt":available,
                "asset":"USDT","endpoint":base+"/fapi/v3/balance"
            }
        except Exception as exc:
            errors.append(str(exc)[:180])
    return {
        "connected":False,"configured":True,"futures_enabled":False,
        "message":"فشل اتصال Binance Futures",
        "detail":" | ".join(errors[-3:])
    }

@app.get("/api/binance/futures-status")
def binance_futures_status_api(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    return _binance_futures_private_status()

def _binance_futures_trade_request(path, params):
    """Signed Binance USDⓈ-M request for an explicit manual Entry/protection order.
    Never fan-out an order request to multiple Binance hosts: a timeout/429 can be ambiguous
    and retrying the same MARKET order may duplicate a real position.
    """
    import os, time, hmac, hashlib, urllib.parse, urllib.error
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        raise RuntimeError("مفاتيح Binance Futures غير مهيأة")
    q=dict(params or {})
    q["timestamp"]=int(time.time()*1000)
    q["recvWindow"]=5000
    encoded=urllib.parse.urlencode(q)
    q["signature"]=hmac.new(secret.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    body=urllib.parse.urlencode(q).encode()
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json",
             "X-MBX-APIKEY":key,"Content-Type":"application/x-www-form-urlencoded"}
    base="https://fapi.binance.com"
    try:
        req=urllib.request.Request(base+path,data=body,headers=headers,method="POST")
        with urllib.request.urlopen(req,timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail=exc.read().decode("utf-8","replace")[:500]
        except Exception:
            detail=""
        raise RuntimeError(f"Binance Futures order request failed: HTTP {exc.code}: {detail}")
    except Exception as exc:
        raise RuntimeError("Binance Futures order request failed: "+str(exc)[:300])

def _futures_symbol_rules(symbol):
    info=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=8)
    for s in info.get("symbols",[]):
        if s.get("symbol")==symbol:
            step=0.0; min_qty=0.0; tick=0.0
            for flt in s.get("filters",[]):
                if flt.get("filterType")=="LOT_SIZE":
                    step=float(flt.get("stepSize") or 0); min_qty=float(flt.get("minQty") or 0)
                elif flt.get("filterType")=="PRICE_FILTER":
                    tick=float(flt.get("tickSize") or 0)
            return step,min_qty,tick
    raise RuntimeError("رمز العقود غير متاح حالياً")

def _floor_step(value, step):
    if step<=0:return value
    import math
    return math.floor(value/step)*step

def _round_tick(value, tick):
    if tick<=0:return value
    import math
    return round(math.floor(value/tick)*tick, max(0, len(str(tick).split(".")[-1].rstrip("0"))))

def _best_futures_15m_signal():
    """Return only the highest-AI live Futures signal on 15m for real execution."""
    rows=_scan_binance_futures("15m")
    ranked=sorted(
        [x for x in (rows or []) if str(x.get("timeframe") or "15m")=="15m" and str(x.get("side") or "").upper() in {"BUY","SELL"}],
        key=lambda x:(float(x.get("ai_pct") or x.get("score") or 0),abs(float(x.get("change_pct") or 0))),
        reverse=True
    )
    return ranked[0] if ranked else None

def _execute_futures_entry(signal):
    """Execute only the current #1 AI Futures signal on 15m."""
    import os, math
    requested=signal if isinstance(signal,dict) else {}
    symbol=str(requested.get("symbol") or "").upper()
    side=str(requested.get("side") or "").upper()
    timeframe=str(requested.get("timeframe") or "15m")
    if not symbol or side not in {"BUY","SELL"}:
        raise RuntimeError("الإشارة غير صالحة")
    if timeframe!="15m":
        raise RuntimeError("الدخول الحقيقي مسموح فقط على فريم 15m")
    # نتحقق من أن العملة ما زالت عقد USDT صالحاً، لكن لا نعيد ترتيب السوق هنا.
    signal=dict(requested)
    signal["symbol"]=symbol
    signal["side"]=side
    signal["timeframe"]="15m"
    leverage=20
    # TP/SL are percentages of leveraged margin:
    # +10% margin at 20x = +0.50% price move; -5% margin at 20x = -0.25%.
    # نسب الربح/الوقف محسوبة من هامش الصفقة، وليس من سعر العقد:
    # عند 20x: ربح 10% من الهامش = حركة سعر 0.50%، ووقف 5% = حركة 0.25%.
    target_margin_pct=10.0
    stop_margin_pct=5.0
    target_price_move=target_margin_pct/leverage
    stop_price_move=stop_margin_pct/leverage
    status=_binance_futures_private_status()
    if not status.get("connected"):
        raise RuntimeError(status.get("message") or "Binance Futures غير متصل")
    available=float(status.get("available_usdt") or 0)
    if available<=0:
        raise RuntimeError("لا يوجد هامش USDT متاح")
    # استخدم كامل الهامش المتاح؛ هامش الرسوم/التسوية قد يجعل Binance يرفض آخر جزء.
    margin=available*0.995
    price=float(signal.get("entry") or 0)
    if price<=0: raise RuntimeError("سعر الدخول غير صالح")
    step,min_qty,tick=_futures_symbol_rules(symbol)
    qty=_floor_step((margin*leverage)/price,step)
    if qty<=0 or qty<min_qty:
        raise RuntimeError("الهامش المتاح أقل من الحد الأدنى للكمية")
    _binance_futures_trade_request("/fapi/v1/leverage",{"symbol":symbol,"leverage":leverage})
    opened=_binance_futures_trade_request("/fapi/v1/order",{
        "symbol":symbol,"side":side,"type":"MARKET","quantity":("%."+str(max(0,len(str(step).split(".")[-1].rstrip("0"))))+"f")%qty if step and "." in str(step) else str(qty)
    })
    executed=float(opened.get("avgPrice") or price)
    close_side="SELL" if side=="BUY" else "BUY"
    tp_price=executed*(1+target_price_move/100 if side=="BUY" else 1-target_price_move/100)
    sl_price=executed*(1-stop_price_move/100 if side=="BUY" else 1+stop_price_move/100)
    tp_price=_round_tick(tp_price,tick); sl_price=_round_tick(sl_price,tick)
    try:
        tp=_binance_futures_trade_request("/fapi/v1/order",{
            "symbol":symbol,"side":close_side,"type":"TAKE_PROFIT_MARKET","stopPrice":str(tp_price),
            "closePosition":"true","workingType":"MARK_PRICE"
        })
        sl=_binance_futures_trade_request("/fapi/v1/order",{
            "symbol":symbol,"side":close_side,"type":"STOP_MARKET","stopPrice":str(sl_price),
            "closePosition":"true","workingType":"MARK_PRICE"
        })
    except Exception as exc:
        # إذا فشل تركيب الحماية، حاول إغلاق المركز فوراً بدلاً من تركه مكشوفاً.
        try:
            _binance_futures_trade_request("/fapi/v1/order",{
                "symbol":symbol,"side":close_side,"type":"MARKET","quantity":str(qty),"reduceOnly":"true"
            })
        except Exception:
            pass
        raise RuntimeError("تم فتح الصفقة لكن تعذر تركيب TP/SL وتمت محاولة الإغلاق: "+str(exc)[:180])
    now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    _futures_bot_write({
        "enabled":1,"status":"open","symbol":symbol,"side":side,"timeframe":"15m",
        "entry":executed,"tp1":tp_price,"tp2":tp_price,"tp3":tp_price,"sl":sl_price,
        "score":float(signal.get("score") or signal.get("ai_pct") or 0),
        "ai_pct":float(signal.get("ai_pct") or signal.get("score") or 0),
        "balance_usdt":available,"margin_usdt":margin,"notional_usdt":margin*leverage,
        "quantity":qty,"leverage":leverage,"opened_at":now,"last_price":executed,
        "last_checked_at":now,"last_error":None,"manual_confirmed":1
    })
    return {"opened":opened,"tp":tp,"sl":sl,"margin_usdt":margin,"leverage":leverage,
            "entry":executed,"tp_price":tp_price,"sl_price":sl_price,
            "target_margin_pct":target_margin_pct,"stop_margin_pct":stop_margin_pct,
            "target_price_move_pct":target_price_move,"stop_price_move_pct":stop_price_move}

def _binance_futures_positions():
    """Read all live USD-M Futures positions; used to prevent duplicate auto entries."""
    import os, time, hmac, hashlib, urllib.parse
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        raise RuntimeError("مفاتيح Binance Futures غير مهيأة")
    q={"timestamp":int(time.time()*1000),"recvWindow":5000}
    encoded=urllib.parse.urlencode(q)
    q["signature"]=hmac.new(secret.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    query=urllib.parse.urlencode(q)
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json","X-MBX-APIKEY":key}
    errors=[]
    for base in ("https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi4.binance.com"):
        try:
            req=urllib.request.Request(base+"/fapi/v3/positionRisk?"+query,headers=headers,method="GET")
            with urllib.request.urlopen(req,timeout=8) as r:
                data=json.loads(r.read().decode("utf-8"))
            if not isinstance(data,list):
                raise RuntimeError("استجابة مراكز Binance غير متوقعة")
            return [x for x in data if abs(float(x.get("positionAmt") or 0))>0]
        except Exception as exc:
            errors.append(str(exc)[:160])
    raise RuntimeError("تعذر قراءة مراكز Binance Futures: "+" | ".join(errors[-3:]))


def _futures_bot_read():
    c=db()
    row=c.execute("SELECT * FROM futures_bot_state WHERE id=1").fetchone()
    c.close()
    return dict(row) if row else {"id":1,"enabled":0,"status":"idle"}

def _futures_bot_write(fields):
    if not fields:return
    import time
    keys=list(fields.keys())
    vals=[fields[k] for k in keys]
    sets=",".join(f"{k}=?" for k in keys)
    last=None
    for attempt in range(4):
        c=None
        try:
            c=db()
            c.execute(f"INSERT INTO futures_bot_state(id) VALUES(1) ON CONFLICT(id) DO NOTHING")
            c.execute(f"UPDATE futures_bot_state SET {sets} WHERE id=1",vals)
            c.commit()
            return
        except sqlite3.OperationalError as exc:
            last=exc
            if "locked" not in str(exc).lower() or attempt==3:
                raise
            time.sleep(0.25*(attempt+1))
        finally:
            if c is not None:
                try:c.close()
                except Exception:pass
    if last: raise last

@app.get("/api/futures/bot")
def futures_bot_status():
    real_enabled=False
    bot=_futures_bot_read()
    # أعرض الربح/الخسارة الحالية من سعر الدخول الفعلي والكمية المنفذة على Binance.
    try:
        entry=float(bot.get("entry") or 0)
        last=float(bot.get("last_price") or entry)
        qty=float(bot.get("quantity") or 0)
        side=str(bot.get("side") or "BUY").upper()
        profit_pct=((last-entry)/entry*100) if entry>0 and side=="BUY" else ((entry-last)/entry*100) if entry>0 else 0.0
        pnl_usdt=((last-entry)*qty) if side=="BUY" else ((entry-last)*qty)
        bot["profit_pct"]=profit_pct
        bot["pnl_usdt"]=pnl_usdt
    except Exception:
        bot["profit_pct"]=0.0
        bot["pnl_usdt"]=0.0
    configured=bool(os.getenv("BINANCE_API_KEY","").strip() and os.getenv("BINANCE_API_SECRET","").strip())
    return {
        "ok":True,
        "mode":"real_orders_ready" if configured else "not_configured",
        "real_orders":configured,
        "message":"تنفيذ حقيقي على Binance Futures متاح عند الضغط على دخول" if configured else "مفاتيح Binance Futures غير مهيأة",
        "bot":bot
    }

@app.get("/api/futures/preflight")
def futures_preflight():
    """Read-only margin preflight. Never places an order."""
    status=_binance_futures_private_status()
    if not status.get("connected"):
        return {"ok":False,"ready":False,"message":status.get("message") or "Binance Futures غير متصل"}
    available=float(status.get("available_usdt") or 0)
    usable=available*0.90
    return {
        "ok":True,
        "ready":available>0,
        "message":"الهامش متاح للفحص فقط" if available>0 else "لا يوجد هامش USDT متاح",
        "available_usdt":round(available,8),
        "suggested_margin_usdt":round(usable,8),
        "buffer_pct":10.0,
        "leverage":20,
        "target_margin_pct":10.0,
        "stop_margin_pct":5.0,
        "mode":"preflight_only"
    }

@app.post("/api/futures/entry")
async def futures_entry(request:Request):
    try:
        payload=await request.json()
        result=_execute_futures_entry(payload if isinstance(payload,dict) else {})
        return {"ok":True,"mode":"real_orders","message":"تم تنفيذ دخول حقيقي وتركيب TP/SL","trade":result}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":str(exc)[:300]},status_code=400)


def strategy_scan(kind:str, timeframe:str="15m", market:str="spot"):
    # مركز الاستراتيجيات يعمل على كل الأسواق، لكن المحركات الخاصة بالنماذج
    # تُطبّق مباشرة على Binance Spot؛ بقية الأسواق تستخدم محرك المسح الخاص بها.
    if kind not in ("order-flow","price-action","breakout","liquidity","patterns"):
        return {"ok":False,"error":"unknown_strategy"}
    if market not in MARKETS:
        market="spot"
    if timeframe not in TIMEFRAMES:
        timeframe="15m"

    if market=="spot":
        if kind=="order-flow":
            rows=_scan_spot_strategy(timeframe,20)
        else:
            rows=_scan_special_strategy(kind,timeframe,24)
    elif market=="futures":
        rows=_scan_binance_futures(timeframe)
    else:
        rows=_scan_yahoo_market(market,timeframe)

    # بوابة اتجاه حيّة: لا نعتمد على cache قديم عند اختيار الصفقة.
    # نستخدم نفس مصدر الاتجاه الذي تستخدمه صفحة الإشارة السريعة حتى لا تظهر
    # صفقة شراء والسوق هابط أو العكس.
    reference=BREADTH_REFERENCE.get(timeframe,timeframe)
    if market in {"spot","futures"}:
        breadth=_breadth_binance(market,reference)
    else:
        breadth=_breadth_yahoo(market,reference)
    up=int(breadth.get("up") or 0); down=int(breadth.get("down") or 0)
    flat=int(breadth.get("flat") or 0)
    total=up+down+flat
    directional=up+down
    up_pct=(up/directional*100) if directional else 0
    down_pct=(down/directional*100) if directional else 0
    direction="BUY" if up>down and up_pct>=55 else "SELL" if down>up and down_pct>=55 else "WAIT"

    if direction=="WAIT":
        rows=[]
    elif market=="spot" and direction=="SELL":
        # السبوت في الاستراتيجية الحالية شراء فقط.
        rows=[]
    else:
        rows=[x for x in rows if str(x.get("side","")).upper()==direction]

    rows=sorted(rows,key=lambda x:(float(x.get("ai_pct",x.get("score",0)) or 0),abs(float(x.get("change_pct",x.get("change_24h",0)) or 0))),reverse=True)[:20]
    return {"ok":True,"engine":kind,"market":market,"market_name":MARKETS[market],
            "opportunities":rows,"timeframe":timeframe,
            "reference_timeframe":breadth.get("reference_timeframe",BREADTH_REFERENCE.get(timeframe,timeframe)),
            "direction":direction,"breadth_up":up,"breadth_down":down,"breadth_flat":flat,
            "breadth_up_pct":round(up_pct,1),"breadth_down_pct":round(down_pct,1),
            "universe":int(breadth.get("universe") or total) }


@app.get("/api/strategy/performance")
def strategy_performance():
    _update_spot_signal_outcomes()
    c=db()
    total=c.execute("SELECT COUNT(*) FROM spot_signal_events").fetchone()[0]
    closed=c.execute("SELECT COUNT(*) FROM spot_signal_events WHERE status='closed'").fetchone()[0]
    wins=c.execute("SELECT COUNT(*) FROM spot_signal_events WHERE outcome='win'").fetchone()[0]
    losses=c.execute("SELECT COUNT(*) FROM spot_signal_events WHERE outcome='loss'").fetchone()[0]
    open_count=c.execute("SELECT COUNT(*) FROM spot_signal_events WHERE status='open'").fetchone()[0]
    pnl=c.execute("SELECT COALESCE(SUM(realized_pct),0) FROM spot_signal_events WHERE status='closed'").fetchone()[0] or 0
    rows=c.execute("""SELECT symbol,timeframe,score,entry,tp1,tp2,tp3,sl,status,outcome,realized_pct,created_at,closed_at
                      FROM spot_signal_events ORDER BY id DESC LIMIT 30""").fetchall()
    c.close()
    win_rate=(wins/closed*100) if closed else 0
    return {"ok":True,"mode":"signal_tracking","total_signals":total,"closed":closed,"open":open_count,
            "wins":wins,"losses":losses,"win_rate":round(win_rate,2),
            "realized_pct_sum":round(float(pnl),3),"minimum_sample_for_reading":100,
            "note":"هذه إحصاءات إشارات مسجلة فعلياً وليست ضماناً للربح. لا يُعتبر الأداء ذا دلالة قبل عينة كافية.",
            "signals":[dict(x) for x in rows]}


@app.get("/api/strategy/signals")
def strategy_signals(limit:int=50):
    limit=max(1,min(int(limit or 50),100))
    c=db()
    rows=c.execute("""SELECT * FROM spot_signal_events ORDER BY id DESC LIMIT ?""",(limit,)).fetchall()
    c.close()
    return {"ok":True,"mode":"paper_tracking","signals":[dict(x) for x in rows]}



def _spot_engine_scan(engine="price-action", timeframe="15m", limit_symbols=30):
    """Shared Binance Spot scanner for the five strategy-center engines."""
    tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=10,spot_fallback=True)
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        symbol=str(t.get("symbol",""))
        if not symbol.endswith("USDT") or symbol in BINANCE_SCANNER_EXCLUDED:
            continue
        try:
            qv=float(t.get("quoteVolume") or 0)
            if qv>=BINANCE_SCANNER_MIN_VOLUME:
                candidates.append((qv,symbol,float(t.get("priceChangePercent") or 0)))
        except Exception:
            pass
    candidates=sorted(candidates,reverse=True)[:max(10,min(int(limit_symbols or 30),30))]

    def one(item):
        qv,symbol,change24=item
        try:
            params=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":100})
            data=_binance_json("https://api.binance.com/api/v3/klines?"+params,timeout=7,timeframe=timeframe,spot_fallback=True)
            if not isinstance(data,list) or len(data)<50:
                return None
            data=data[:-1]
            candles=[{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5]),"taker_buy_quote":float(k[10])} for k in data]
            price=candles[-1]["close"]; prev=candles[-2]["close"]
            change=(price/prev-1)*100 if prev else 0
            a=_pa_analysis(candles)
            kinds={p.get("kind") for p in a.get("patterns",[])}
            names=[p.get("name") for p in a.get("patterns",[])]
            bull_kinds={"breakout","double_bottom","inverse_head_shoulders","engulfing"}
            bear_kinds={"breakdown","double_top","head_shoulders"}
            bull=sum(1 for p in a.get("patterns",[]) if p.get("kind") in bull_kinds and p.get("confidence",0)>=75)
            bear=sum(1 for p in a.get("patterns",[]) if p.get("kind") in bear_kinds and p.get("confidence",0)>=75)
            prior_high=max(x["high"] for x in candles[-21:-1]); prior_low=min(x["low"] for x in candles[-21:-1])
            sweep=any(candles[i]["low"]<prior_low and candles[i]["close"]>prior_low for i in range(max(0,len(candles)-6),len(candles)-1))
            breakout=price>prior_high
            retest=breakout and min(x["low"] for x in candles[-4:])<=prior_high*1.0015
            avg=sum(x["volume"] for x in candles[-21:-1])/20
            vr=candles[-1]["volume"]/avg if avg else 0
            side=a.get("side","WAIT")
            score=float(a.get("confidence") or 0)
            reason=[]
            if "breakout" in kinds: reason.append("اختراق مقاومة")
            if "breakdown" in kinds: reason.append("كسر دعم")
            if "double_top" in kinds: reason.append("قمة مزدوجة")
            if "double_bottom" in kinds: reason.append("قاع مزدوج")
            if "head_shoulders" in kinds: reason.append("رأس وكتفين")
            if "inverse_head_shoulders" in kinds: reason.append("رأس وكتفين معكوس")
            if "sym_triangle" in kinds or "ascending_triangle" in kinds or "descending_triangle" in kinds: reason.append("مثلث سعري")
            if "wedge" in kinds: reason.append("وتد سعري")
            if "engulfing" in kinds: reason.append("ابتلاع سعري")
            if sweep: reason.append("Liquidity Sweep")
            if retest: reason.append("Retest")
            if vr>=1.3: reason.append(f"حجم {vr:.1f}x")
            # Each engine has its own trigger; no one engine borrows another's score.
            if engine=="price-action":
                ok=side=="BUY" and score>=75 and bull>=1 and bear==0
                tag="Price Action"
            elif engine=="breakout":
                ok=breakout and retest and side=="BUY" and bull>=1 and vr>=1.15
                score=min(95,60+(15 if retest else 0)+(10 if vr>=1.3 else 0)+(10 if bull else 0))
                tag="Breakout + Retest"
            elif engine=="liquidity":
                ok=sweep and side=="BUY" and bull>=1 and bear==0
                score=min(95,65+(15 if vr>=1.2 else 0)+(10 if change>0 else 0)+(5 if bull else 0))
                tag="Liquidity Sweep + Reclaim"
            elif engine=="patterns":
                ok=side=="BUY" and bull>=1 and bear==0 and any(k in kinds for k in {"double_bottom","inverse_head_shoulders","sym_triangle","ascending_triangle","wedge","engulfing"})
                score=min(95,max(score,70))
                tag="Chart Patterns"
            else:
                return None
            if not ok:
                return None
            entry=price
            risk=entry-float(a.get("sl") or 0)
            if risk<=0 or risk/entry>0.05:
                return None
            return {
                "symbol":symbol,"side":"BUY","timeframe":timeframe,"price":entry,
                "entry":entry,"sl":entry-risk,"tp1":entry+risk,"tp2":entry+risk*2,"tp3":entry+risk*3,
                "score":round(score,1),"ai_pct":round(score,1),"change_pct":change,"change_24h":change24,
                "volume":qv,"volume_ratio":vr,"trend":a.get("trend"),"support":a.get("support"),"resistance":a.get("resistance"),
                "patterns":names[-8:],"reasons":reason[-8:],"tag":tag,"status":"فرصة شراء سبوت",
                "risk":"إشارة تحليلية قابلة للاختبار وليست ضماناً للربح."
            }
        except Exception:
            return None
    out=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(one,x) for x in candidates]
        for f in as_completed(fs):
            try:
                x=f.result()
                if x: out.append(x)
            except Exception:
                pass
    return sorted(out,key=lambda x:(x["score"],x["volume_ratio"],x["change_pct"]),reverse=True)[:10]


@app.get("/api/strategy/engine")
def strategy_engine(engine:str="order-flow",timeframe:str="15m"):
    allowed={"order-flow","price-action","breakout","liquidity","patterns"}
    if engine not in allowed:
        engine="order-flow"
    if timeframe not in TIMEFRAMES:
        timeframe="15m"
    if engine=="order-flow":
        data=_binance_spot_strategy_scan()
        data["engine"]="order-flow"
        return data
    rows=_spot_engine_scan(engine,timeframe,30)
    return {"ok":True,"engine":engine,"market":"spot","timeframe":timeframe,
            "updated_at":datetime.now(timezone.utc).isoformat(),"paper_tracking":True,
            "opportunities":rows}

@app.get("/api/binance/opportunities")
def binance_opportunities():
    try:
        return _binance_spot_strategy_scan()
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر فحص فرص Binance Spot حالياً"},status_code=502)


@app.get("/api/analysis/chart")
def analysis_chart(symbol:str="BTCUSDT",timeframe:str="15m",limit:int=180):
    """شارت حي 15 دقيقة بتحليل Price Action فعلي ورسومات نماذج، بدون EMA/RSI."""
    allowed={"15m","30m","1h","4h","1d","1w","1M"}
    if timeframe not in allowed: timeframe="15m"
    symbol=symbol.upper().strip()
    if not symbol.endswith("USDT") or len(symbol)>20 or not symbol.replace("USDT","").isalnum():
        symbol="BTCUSDT"
    limit=max(100,min(int(limit or 180),240))
    params=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":limit})
    data=_binance_json("https://api.binance.com/api/v3/klines?"+params,timeout=8,timeframe=timeframe,spot_fallback=True)
    if not isinstance(data,list) or len(data)<80:
        return JSONResponse({"ok":False,"message":"بيانات الشارت غير مكتملة"},status_code=502)
    data=data[:-1] if len(data)>80 else data
    candles=[{"time":int(k[0])//1000,"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in data]
    a=_pa_analysis(candles)
    return {"ok":True,"symbol":symbol,"timeframe":timeframe,"candles":candles,"price":candles[-1]["close"],
            "change_pct":(candles[-1]["close"]-candles[-2]["close"])/candles[-2]["close"]*100,
            **a,"chart_svg":_pa_svg(symbol,candles,a),
            "conditions":[{"name":p["name"],"ok":p["confidence"]>=75} for p in a["patterns"]]}

@app.get("/api/analysis/latest")
def analysis_latest():
    c=db()
    row=c.execute("SELECT * FROM crypto_analysis_posts ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    if not row: return {"ok":False,"message":"لم ينشر تحليل بعد"}
    d=dict(row)
    try: d["patterns"]=json.loads(d.get("patterns") or "[]")
    except Exception: d["patterns"]=[]
    return {"ok":True,**d}

def _generate_crypto_analysis_post():
    """يختار أفضل صفقة Price Action من العملات الأعلى سيولة كل 15 دقيقة."""
    from datetime import datetime,timezone,timedelta
    tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=7,timeframe="15m",spot_fallback=True)
    excluded={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","BUSDUSDT"}
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        sym=t.get("symbol","")
        if not sym.endswith("USDT") or sym in excluded: continue
        try:
            qv=float(t.get("quoteVolume",0))
            if qv>=1_000_000: candidates.append((qv,sym))
        except Exception: pass
    candidates=sorted(candidates,reverse=True)[:10]
    found=[]
    for _,sym in candidates:
        try:
            p=urllib.parse.urlencode({"symbol":sym,"interval":"15m","limit":181})
            ks=_binance_json("https://api.binance.com/api/v3/klines?"+p,timeout=7,timeframe="15m",spot_fallback=True)
            if len(ks)<100: continue
            ks=ks[:-1]
            cs=[{"time":int(k[0])//1000,"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in ks]
            aa=_pa_analysis(cs)
            if aa["side"]=="WAIT" or aa["confidence"]<62: continue
            found.append((aa["confidence"],sym,cs,aa))
        except Exception: continue
    if not found: return None
    _,symbol,candles,a=max(found,key=lambda z:z[0])
    now=datetime.now(timezone(timedelta(hours=3)))
    slot=now.strftime("%Y-%m-%d %H:%M")
    side_ar="شراء" if a["side"]=="BUY" else "بيع"
    pnames="، ".join(x["name"] for x in a["patterns"][:5]) or "بنية سعرية"
    body=("تحليل عملة %s على فريم 15 دقيقة — %s.\n"
          "النماذج المرصودة: %s.\n"
          "الاتجاه: %s | الثقة: %.0f%%.\n"
          "الدخول: %.8g | TP1: %.8g | TP2: %.8g | TP3: %.8g | SL: %.8g.\n"
          "التحليل مبني على الشموع المغلقة، القمم والقيعان، خطوط الاتجاه، مناطق الدعم والمقاومة وFibonacci. لا يتم استخدام EMA أو RSI في هذا التحليل."
          %(symbol,side_ar,pnames,a["trend"],a["confidence"],a["entry"],a["tp1"],a["tp2"],a["tp3"],a["sl"]))
    chart=_pa_svg(symbol,candles,a)
    c=db()
    c.execute("INSERT OR REPLACE INTO crypto_analysis_posts(slot,symbol,side,timeframe,price,entry,tp1,tp2,tp3,sl,confidence,patterns,body,chart_svg) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (slot,symbol,a["side"],"15m",candles[-1]["close"],a["entry"],a["tp1"],a["tp2"],a["tp3"],a["sl"],a["confidence"],json.dumps(a["patterns"],ensure_ascii=False),body,chart))
    c.commit(); c.close()
    return {"symbol":symbol,"side":a["side"],"confidence":a["confidence"],"slot":slot}

def _crypto_analysis_worker():
    import time
    from datetime import datetime,timezone,timedelta
    tz=timezone(timedelta(hours=3))
    try: _generate_crypto_analysis_post()
    except Exception: pass
    while True:
        now=datetime.now(tz)
        target=now.replace(minute=(now.minute//15+1)*15%60,second=8,microsecond=0)
        if target<=now:
            target=target+timedelta(hours=1 if now.minute>=45 else 0)
        time.sleep(max(20,(target-now).total_seconds()))
        try: _generate_crypto_analysis_post()
        except Exception: pass


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
    "forex":{"sides":["BUY","SELL"],"source":"yahoo"},}
FOREX_SYMBOLS=["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","USDCAD=X","AUDUSD=X","NZDUSD=X","EURGBP=X","EURJPY=X","EURCHF=X","EURAUD=X","EURCAD=X","EURNZD=X","GBPJPY=X","GBPCHF=X","GBPAUD=X","GBPCAD=X","GBPNZD=X","AUDJPY=X","AUDNZD=X","AUDCAD=X","AUDCHF=X","CADJPY=X","CADCHF=X","CHFJPY=X","NZDJPY=X","NZDCAD=X","NOKUSD=X","SEKUSD=X","SGDUSD=X","HKDUSD=X","CNYUSD=X","MXNUSD=X","ZARUSD=X","TRYUSD=X","INRUSD=X","BRLUSD=X"]
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
                rr=r[0]
                qd=rr.get("indicators",{}).get("quote",[{}])[0]
                closes=qd.get("close",[])
                lows=qd.get("low",[])
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


def _ema(values, period):
    """Exponential moving average used by the unified non-Spot market engine."""
    values=[float(v) for v in values]
    if len(values)<period:
        return None
    k=2/(period+1)
    e=sum(values[:period])/period
    for v in values[period:]:
        e=v*k+e*(1-k)
    return e

def _rsi(values, period=14):
    """Simple RSI from closed candles; returns None when history is insufficient."""
    values=[float(v) for v in values]
    if len(values)<period+1:
        return None
    gains=0.0
    losses=0.0
    for i in range(len(values)-period,len(values)):
        d=values[i]-values[i-1]
        if d>0:
            gains+=d
        elif d<0:
            losses-=d
    if losses<=0:
        return 100.0 if gains>0 else 50.0
    return 100-(100/(1+(gains/period)/(losses/period)))

def _record_signal(row, market="spot"):
    """Persist a unique strategy signal so the site can measure the strategy honestly."""
    try:
        tf=str(row.get("timeframe") or "15m")
        import time
        from datetime import datetime,timezone
        minutes={"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440,"1w":10080,"1M":43200}.get(tf,15)
        bucket=int(time.time()//(minutes*60))*(minutes*60)
        candle_start=str(row.get("candle_start") or datetime.fromtimestamp(bucket,tz=timezone.utc).isoformat())
        market=str(row.get("market") or market or "spot")
        key=f"{market}:{row.get('symbol')}:{tf}:{candle_start}"
        if tf=="1M":
            next_month=(datetime.fromtimestamp(bucket,tz=timezone.utc).replace(day=28)+__import__("datetime").timedelta(days=4)).replace(day=1)
            expires_at=next_month.isoformat()
        else:
            expires_at=datetime.fromtimestamp(bucket+minutes*60,tz=timezone.utc).isoformat()
        c=db()
        c.execute("""INSERT OR IGNORE INTO spot_signal_events
        (signal_key,market,symbol,side,timeframe,candle_start,entry,tp1,tp2,tp3,sl,score,volume_ratio,book_imbalance,buy_pressure,spread_pct,expires_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (key,market,row.get("symbol"),row.get("side","BUY"),tf,candle_start,row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),row.get("score",0),row.get("volume_ratio"),row.get("book_imbalance"),row.get("buy_pressure"),row.get("spread_pct"),expires_at))
        c.commit(); c.close()
    except Exception:
        pass


def _scan_spot_strategy(timeframe="15m", limit_symbols=None):
    """Breakout + Volume Profile POC retest. BUY on bullish breakout, SELL on bearish mirror."""
    if timeframe not in TIMEFRAMES: return []
    tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=8,timeframe=timeframe,spot_fallback=True)
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        symbol=str(t.get("symbol",""))
        if not symbol.endswith("USDT") or symbol in BINANCE_SCANNER_EXCLUDED: continue
        try:
            qv=float(t.get("quoteVolume") or 0); price=float(t.get("lastPrice") or 0)
            if qv>=1_000_000 and price>0: candidates.append((qv,symbol))
        except Exception: pass
    candidates.sort(reverse=True)
    if limit_symbols is not None: candidates=candidates[:max(1,int(limit_symbols))]

    def build_profile(ks,start_i,end_i):
        rows=40
        lo=min(float(k[3]) for k in ks[start_i:end_i+1])
        hi=max(float(k[2]) for k in ks[start_i:end_i+1])
        if hi<=lo:return None
        step=(hi-lo)/rows; profile=[0.0]*rows
        for k in ks[start_i:end_i+1]:
            kh,kl,kv=float(k[2]),float(k[3]),float(k[5])
            if kh<=kl or kv<=0: continue
            a=max(0,int((kl-lo)/step)); b=min(rows-1,int((kh-lo)/step))
            share=kv/max(1,b-a+1)
            for bi in range(a,b+1): profile[bi]+=share
        pi=max(range(rows),key=lambda z:profile[z])
        poc_low=lo+pi*step; poc_high=poc_low+step; poc=(poc_low+poc_high)/2
        mx=max(profile) or 1.0
        return {"lo":lo,"hi":hi,"step":step,"poc":poc,"poc_low":poc_low,"poc_high":poc_high,
                "bins":[{"price":lo+(i+0.5)*step,"volume_ratio":round(v/mx,4)} for i,v in enumerate(profile)]}

    def scan_one(item):
        qv,symbol=item
        try:
            params=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":221})
            ks=_binance_json("https://api.binance.com/api/v3/klines?"+params,timeout=7,timeframe=timeframe,spot_fallback=True)
            if not isinstance(ks,list) or len(ks)<50:return None
            ks=ks[:-1]
            highs=[float(k[2]) for k in ks]; lows=[float(k[3]) for k in ks]
            closes=[float(k[4]) for k in ks]; vols=[float(k[5]) for k in ks]
            pivot=5
            ph=[i for i in range(pivot,len(ks)-pivot) if highs[i]==max(highs[i-pivot:i+pivot+1])]
            pl=[i for i in range(pivot,len(ks)-pivot) if lows[i]==min(lows[i-pivot:i+pivot+1])]
            if not ph or not pl:return None

            setups=[]
            # صعود: قمة سابقة -> قاع بعدها/قبل الاختراق -> اختراق القمة -> رجوع إلى POC.
            for hi_i in reversed(ph):
                old_high=highs[hi_i]
                later=[j for j in range(hi_i+1,len(ks)) if closes[j]>old_high]
                if later:
                    br=later[-1]
                    lows_before=[x for x in pl if x<hi_i]
                    if lows_before:
                        low_i=lows_before[-1]
                        profile=build_profile(ks,low_i,br)
                        if profile:
                            post_high=max(highs[br:])
                            price=closes[-1]
                            touch=lows[-1]<=profile["poc_high"] and highs[-1]>=profile["poc_low"]
                            if touch and post_high>old_high*1.001 and price>=lows[low_i] and price<=profile["poc_high"]*1.008:
                                risk=max(price-lows[low_i],price*0.005)
                                setups.append({
                                    "symbol":symbol,"side":"BUY","signal_label":"شراء",
                                    "strategy_label":"اختراق القمة + إعادة اختبار POC","strategy_mode":"BREAKOUT_POC_RETEST",
                                    "timeframe":timeframe,"change_pct":round((price/closes[-2]-1)*100,3) if closes[-2] else 0,
                                    "entry":price,"poc":profile["poc"],"poc_low":profile["poc_low"],"poc_high":profile["poc_high"],
                                    "prev_high":old_high,"last_low":lows[low_i],"breakout_price":closes[br],
                                    "sl":lows[low_i],"tp1":old_high,"tp2":post_high,"tp3":post_high+risk,
                                    "score":0,"ai_pct":0,"volume_ratio":round(vols[-1]/(sum(vols[-21:-1])/20),2) if sum(vols[-21:-1])>0 else 1,
                                    "tag":"شراء","quote_volume":qv,"profile_rows":40,"breakout_index":br,"poc_touched":True,
                                    "profile_direction":"صاعد","profile_start":"قاع الموجة","profile_end":"شمعة الاختراق","profile_low":profile["lo"],"profile_high":profile["hi"],"profile_bins":profile["bins"]
                                })
                                break

            # هبوط معكوس: قاع سابق -> قمة بعدها/قبل الاختراق -> كسر القاع -> رجوع إلى POC.
            for lo_i in reversed(pl):
                old_low=lows[lo_i]
                later=[j for j in range(lo_i+1,len(ks)) if closes[j]<old_low]
                if later:
                    br=later[-1]
                    highs_before=[x for x in ph if x<lo_i]
                    if highs_before:
                        high_i=highs_before[-1]
                        profile=build_profile(ks,high_i,br)
                        if profile:
                            post_low=min(lows[br:])
                            price=closes[-1]
                            touch=lows[-1]<=profile["poc_high"] and highs[-1]>=profile["poc_low"]
                            if touch and post_low<old_low*0.999 and price<=highs[high_i] and price>=profile["poc_low"]*0.992:
                                risk=max(highs[high_i]-price,price*0.005)
                                setups.append({
                                    "symbol":symbol,"side":"SELL","signal_label":"بيع",
                                    "strategy_label":"كسر القاع + إعادة اختبار POC","strategy_mode":"BREAKDOWN_POC_RETEST",
                                    "timeframe":timeframe,"change_pct":round((price/closes[-2]-1)*100,3) if closes[-2] else 0,
                                    "entry":price,"poc":profile["poc"],"poc_low":profile["poc_low"],"poc_high":profile["poc_high"],
                                    "prev_high":highs[high_i],"last_low":old_low,"breakout_price":closes[br],
                                    "sl":highs[high_i],"tp1":old_low,"tp2":post_low,"tp3":max(0,post_low-risk),
                                    "score":0,"ai_pct":0,"volume_ratio":round(vols[-1]/(sum(vols[-21:-1])/20),2) if sum(vols[-21:-1])>0 else 1,
                                    "tag":"بيع","quote_volume":qv,"profile_rows":40,"breakout_index":br,"poc_touched":True,
                                    "profile_direction":"هابط","profile_start":"قمة الموجة","profile_end":"شمعة الكسر","profile_bins":profile["bins"]
                                })
                                break
            if not setups:
                # لا نخلي شرط POC النادر يخفي السوق بالكامل.
                # إذا ما اكتمل نموذج الاختراق/POC، نستخدم نفس بوابة الاستراتيجية
                # الأساسية (EMA200 + RSI + حركة 15m) لإخراج فرصة صالحة بدل "0" دائم.
                basic_candles=[(float(k[4]),float(k[3]),float(k[2]),float(k[1])) for k in ks[-220:]]
                fallback=_strategy_rows(symbol,timeframe,["BUY"],basic_candles)
                if fallback:
                    x=fallback[0]
                    x["quote_volume"]=qv
                    x["strategy_label"]="شراء: EMA200 + RSI50 + حركة 15m"
                    x["strategy_mode"]="EMA200_RSI50_FALLBACK"
                    x["tag"]="إشارة أساسية بعد فشل نموذج POC"
                    return x
                return None
            x=setups[0]
            if x["side"]=="BUY":
                strength=(10 if x["entry"]>=x["poc"] else 0)+(10 if x["change_pct"]>=0 else 0)+(10 if x["tp2"]>x["tp1"]*1.01 else 0)
            else:
                strength=(10 if x["entry"]<=x["poc"] else 0)+(10 if x["change_pct"]<=0 else 0)+(10 if x["tp2"]<x["tp1"]*0.99 else 0)
            x["score"]=round(min(99,69+strength),1); x["ai_pct"]=x["score"]
            return x
        except Exception:
            return None

    found=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(scan_one,x) for x in candidates]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x: found.append(x)
            except Exception: pass
    return sorted(found,key=lambda x:(float(x["score"]),abs(float(x["change_pct"])),float(x["quote_volume"])),reverse=True)[:30]

_YAHOO_SCAN_CURSOR={"us":0,"saudi":0,"contracts":0,"forex":0}
_YAHOO_SCAN_LOCK=__import__('threading').Lock()

def _scan_yahoo_market(market,timeframe):
    """مسح دوّار للأسواق غير Binance: الكون كامل، لكن كل دورة تفحص دفعة صغيرة حتى لا تخنق مزود البيانات."""
    if market not in {"contracts","us","saudi","forex"} or timeframe not in TIMEFRAMES:
        return []
    interval_map={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    range_map={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
    sides=MARKET_RULES.get(market,{}).get("sides",["BUY"])
    symbols=_market_universe(market)
    if not symbols:
        return []
    # لا نرسل مئات الطلبات دفعة واحدة إلى Yahoo. الكون كامل، والفحص يتنقل عليه دفعات.
    batch_size=24 if market in {"us","saudi"} else 16
    with _YAHOO_SCAN_LOCK:
        start=_YAHOO_SCAN_CURSOR.get(market,0) % len(symbols)
        batch=[symbols[(start+i)%len(symbols)] for i in range(min(batch_size,len(symbols)))]
        _YAHOO_SCAN_CURSOR[market]=(start+len(batch)) % len(symbols)

    def scan_one(symbol):
        try:
            candles=_yahoo_chart(symbol,interval_map[timeframe],range_map[timeframe],timeframe)
            return _strategy_rows(symbol,timeframe,sides,candles)
        except Exception:
            return []

    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(scan_one,s) for s in batch]
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                pass

    return sorted(rows,key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),reverse=True)[:20]

_FUTURES_DATA_BASES=(
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
)
_FUTURES_DATA_CURSOR=0
_FUTURES_DATA_LOCK=__import__("threading").Lock()

def _binance_futures_json(url,timeout=5):
    """Futures market-data failover with round-robin source selection."""
    global _FUTURES_DATA_CURSOR
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json"}
    if "fapi.binance.com" not in url:
        return _json_get(url,timeout=timeout,headers=headers)
    path=url.replace("https://fapi.binance.com","",1)
    with _FUTURES_DATA_LOCK:
        start=_FUTURES_DATA_CURSOR % len(_FUTURES_DATA_BASES)
        _FUTURES_DATA_CURSOR=(start+1) % len(_FUTURES_DATA_BASES)
    ordered=_FUTURES_DATA_BASES[start:]+_FUTURES_DATA_BASES[:start]
    errors=[]
    for base in ordered:
        try:
            return _json_get(base+path,timeout=timeout,headers=headers)
        except Exception as exc:
            errors.append(f"{base}: {str(exc)[:90]}")
    raise RuntimeError("Binance Futures sources unavailable: "+" | ".join(errors[-5:]))


def _futures_shard_config():
    # A single Northflank service must scan the full Futures universe.
    # Sharding is opt-in: set FUTURES_SHARD_COUNT>1 only when multiple
    # worker services are actually deployed.
    try: count=max(1,int(os.getenv("FUTURES_SHARD_COUNT","1")))
    except Exception: count=1
    try: index=int(os.getenv("FUTURES_SHARD_INDEX","0"))
    except Exception: index=0
    return count,index % count

def _futures_shard_candidates(candidates):
    """Return this worker's rotating shard. The shared cursor advances one shard at a time."""
    count,index=_futures_shard_config()
    if count<=1:
        return sorted(candidates,key=lambda x:x[1])

    # Each worker keeps its configured shard, so multiple services can work
    # in parallel without duplicating the whole market. A completed pass
    # naturally returns to the first shard for that worker.
    return sorted(candidates,key=lambda x:x[1])[index::count]


def _scan_binance_futures(timeframe):
    """Fast live USD-M Futures scanner for the API and 15m execution gate."""
    tickers=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=8)
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        symbol=str(t.get("symbol") or "")
        if not symbol.endswith("USDT") or symbol.endswith(("UPUSDT","DOWNUSDT","BULLUSDT","BEARUSDT")):
            continue
        try:
            q=float(t.get("quoteVolume") or 0)
            if q < 1_000_000:
                continue
        except Exception:
            continue
        candidates.append((q,symbol))
    candidates=sorted(candidates,key=lambda x:x[0],reverse=True)
    rows=[]
    workers=max(4,min(12,int(os.getenv("FUTURES_SCAN_WORKERS","8") or 8)))

    def scan_one(item):
        _,symbol=item
        try:
            p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":221})
            k=_binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+p,timeout=7)
            if len(k)<220:
                return []
            # Closed candles only: no phantom signal from the still-open candle.
            closed=k[:-1]
            candles=[(float(x[4]),float(x[3]),float(x[2]),float(x[1])) for x in closed[-220:]]
            return _strategy_rows(symbol,timeframe,["BUY","SELL"],candles)
        except Exception:
            return []

    batch_size=max(10,int(os.getenv("FUTURES_SCAN_BATCH_SIZE","30") or 30))
    for offset in range(0,len(candidates),batch_size):
        batch=candidates[offset:offset+batch_size]
        with ThreadPoolExecutor(max_workers=min(workers,len(batch) or 1)) as pool:
            futures=[pool.submit(scan_one,item) for item in batch]
            for future in as_completed(futures):
                try:
                    rows.extend(future.result())
                except Exception:
                    pass
        if rows:
            rows=sorted(rows,key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),reverse=True)[:40]

    return sorted(
        [x for x in rows if abs(float(x.get("change_pct") or 0))>=0.30],
        key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),
        reverse=True
    )[:20]

def _strategy_rows(symbol, timeframe, sides, candles):
    """Unified live strategy: EMA200 + RSI 50 + 1% move, with mandatory gap guard."""
    if timeframe not in TIMEFRAMES or len(candles)<220:
        return []
    closes=[float(x[0]) for x in candles]
    lows=[float(x[1]) for x in candles]
    highs=[float(x[2]) if len(x)>=3 else float(x[0]) for x in candles]
    price=closes[-1]
    prev_price=closes[-2]
    # Gap Guard: أي فجوة واضحة بين افتتاح آخر شمعة مغلقة وإغلاق الشمعة السابقة تمنع الدخول.
    # نستخدم 0.10% كحد أدنى لتجاهل فروقات التغذية الطفيفة جدًا.
    last_open=float(candles[-1][3]) if len(candles[-1])>=4 else prev_price
    gap_pct=abs((last_open-prev_price)/prev_price*100) if prev_price else 0.0
    if gap_pct>=0.10:
        return []
    ema200=_ema(closes,200)
    rsi=_rsi(closes)
    if ema200 is None or rsi is None:
        return []

    # التغير محسوب من آخر شمعة مغلقة إلى الشمعة المغلقة السابقة
    # على نفس الفريم المختار، بدون خلط الفريمات.
    change=(price-prev_price)/prev_price*100 if prev_price else 0.0

    if rsi>50.0 and price>ema200 and change>=0.30 and "BUY" in sides:
        sl=min(lows[-20:]); risk=price-sl
        if risk<=0 or risk/price>0.08:
            return []
        score=min(99.0,70.0+min(15.0,(rsi-50.0)*1.5)+min(14.0,max(0.0,change-1.0)*2.0))
        return [{"symbol":symbol,"side":"BUY","timeframe":timeframe,"change_pct":round(change,3),
                 "profit_pct":10.0,"loss_pct":5.0,
                 "ai_pct":round(score,1),"tag":"RSI > 50 + فوق EMA200 + تغير +0.30%",
                 "strategy_label":"شراء: RSI فوق 50 + السعر فوق EMA200 + تغير +0.30% على نفس الفريم",
                 "strategy_mode":"RSI50_EMA200_MARGIN_10_5","entry":price,
                 "tp1":price*1.005,"tp2":price*1.01,"tp3":price*1.015,"sl":price*0.9975,"status":"open",
                 "ema200":ema200,"rsi":rsi,"candle_start":_candle_start(timeframe).isoformat()}]

    if rsi<50.0 and price<ema200 and change<=-0.30 and "SELL" in sides:
        sl=max(highs[-20:]); risk=sl-price
        if risk<=0 or risk/price>0.08:
            return []
        score=min(99.0,70.0+min(15.0,(50.0-rsi)*1.5)+min(14.0,max(0.0,abs(change)-1.0)*2.0))
        return [{"symbol":symbol,"side":"SELL","timeframe":timeframe,"change_pct":round(change,3),
                 "profit_pct":10.0,"loss_pct":5.0,
                 "ai_pct":round(score,1),"tag":"RSI < 50 + تحت EMA200 + تغير -0.30%",
                 "strategy_label":"بيع: RSI تحت 50 + السعر تحت EMA200 + تغير -0.30% على نفس الفريم",
                 "strategy_mode":"RSI50_EMA200_MARGIN_10_5","entry":price,
                 "tp1":price*0.995,"tp2":price*0.99,"tp3":price*0.985,"sl":price*1.0025,"status":"open",
                 "ema200":ema200,"rsi":rsi,"candle_start":_candle_start(timeframe).isoformat()}]
    return []
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
    return (cached if fresh else []),True


def _breadth_cache_key(market,timeframe):
    return f"breadth:v1:{market}:{timeframe}"


def _breadth_binance(market,timeframe):
    """عدد الصاعد والهابط من آخر شمعة مغلقة لنفس الفريم، مستقل عن إشارات الاستراتيجية."""
    if market=="spot":
        tickers=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=10,timeframe=timeframe,spot_fallback=True)
        candidates=[]
        for t in tickers if isinstance(tickers,list) else []:
            s=str(t.get("symbol",""))
            if not s.endswith("USDT") or s in BINANCE_SCANNER_EXCLUDED:
                continue
            try:
                qv=float(t.get("quoteVolume") or 0)
                if qv>=BINANCE_SCANNER_MIN_VOLUME:
                    candidates.append((qv,s))
            except Exception:
                continue
        candidates=sorted(candidates,reverse=True)[:80]
        endpoint="https://api.binance.com/api/v3/klines"
        def one(item):
            _,s=item
            try:
                p=urllib.parse.urlencode({"symbol":s,"interval":timeframe,"limit":2})
                ks=_binance_json(endpoint+"?"+p,timeout=5,timeframe=timeframe,spot_fallback=True)
                if len(ks)<2:return None
                k=ks[-2]; o=float(k[1]); cl=float(k[4])
                return 1 if cl>o else -1 if cl<o else 0
            except Exception:return None
    else:
        tickers=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=8)
        candidates=[]
        for t in tickers if isinstance(tickers,list) else []:
            s=str(t.get("symbol",""))
            if not s.endswith("USDT"): continue
            try:
                qv=float(t.get("quoteVolume") or 0)
                if qv>=5_000_000:candidates.append((qv,s))
            except Exception: pass
        candidates=sorted(candidates,reverse=True)[:80]
        endpoint="https://fapi.binance.com/fapi/v1/klines"
        def one(item):
            _,s=item
            try:
                p=urllib.parse.urlencode({"symbol":s,"interval":timeframe,"limit":2})
                ks=_binance_futures_json(endpoint+"?"+p,timeout=5)
                if len(ks)<2:return None
                k=ks[-2]; o=float(k[1]); cl=float(k[4])
                return 1 if cl>o else -1 if cl<o else 0
            except Exception:return None
    up=down=flat=0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for v in pool.map(one,candidates):
            if v==1: up+=1
            elif v==-1: down+=1
            elif v==0: flat+=1
    return {"up":up,"down":down,"flat":flat,"universe":up+down+flat,"timeframe":timeframe}


def _breadth_yahoo(market,timeframe):
    interval_map={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    range_map={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
    def one(symbol):
        try:
            candles=_yahoo_chart(symbol,interval_map[timeframe],range_map[timeframe],timeframe)
            if len(candles)<2:return None
            prev=float(candles[-2][0]); cl=float(candles[-1][0])
            return 1 if cl>prev else -1 if cl<prev else 0
        except Exception:return None
    up=down=flat=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for v in pool.map(one,_market_universe(market)):
            if v==1: up+=1
            elif v==-1: down+=1
            elif v==0: flat+=1
    return {"up":up,"down":down,"flat":flat,"universe":up+down+flat,"timeframe":timeframe}


def _market_breadth(market,timeframe):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return {"ok":False,"message":"قسم أو فريم غير صالح"}
    key=_breadth_cache_key(market,timeframe)
    candle_start=_candle_start(timeframe).isoformat()
    cached,fresh=_read_cached_scan(key,candle_start)
    if fresh and isinstance(cached,dict):
        return dict(cached,ok=True,cached=True)
    lock=_scan_lock(key)
    if lock.acquire(blocking=False):
        lock.release()
        scanner=(lambda:_breadth_binance(market,timeframe)) if market in {"spot","futures"} else (lambda:_breadth_yahoo(market,timeframe))
        _SCAN_REFRESH_POOL.submit(_refresh_scan,key,candle_start,scanner)
    return dict(cached or {"up":0,"down":0,"flat":0,"universe":0,"timeframe":timeframe},ok=True,cached=False,scanning=True)


_EQUITY_UNIVERSE_CACHE={}
_EQUITY_UNIVERSE_TTL=900
_EQUITY_UNIVERSE_LOCK=__import__('threading').Lock()

def _yahoo_equity_universe(region='us', min_daily_volume=1000000):
    import time
    key=str(region)+':'+str(int(min_daily_volume))
    with _EQUITY_UNIVERSE_LOCK:
        cached=_EQUITY_UNIVERSE_CACHE.get(key)
        if cached and time.time()-cached[0] < _EQUITY_UNIVERSE_TTL:
            return list(cached[1])
    symbols=[]; seen=set()
    for offset in range(0,5000,250):
        body={'offset':offset,'size':250,'sortField':'dayvolume','sortType':'DESC','quoteType':'EQUITY','query':{'operator':'AND','operands':[{'operator':'EQ','operands':['region',region]},{'operator':'GT','operands':['dayvolume',int(min_daily_volume)]}]}}
        try:
            req=urllib.request.Request('https://query1.finance.yahoo.com/v1/finance/screener',data=json.dumps(body).encode('utf-8'),headers={'User-Agent':'mudarib-pro/1.0','Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=10) as resp:
                raw=json.loads(resp.read().decode('utf-8'))
            result=((raw.get('finance') or {}).get('result') or [{}])[0]
            quotes=result.get('quotes') or []
            if not quotes: break
            for q in quotes:
                s=str(q.get('symbol') or '').strip()
                vol=float(q.get('regularMarketVolume') or q.get('dayvolume') or 0)
                if s and vol>min_daily_volume and s not in seen:
                    seen.add(s); symbols.append(s)
            if len(quotes)<250: break
        except Exception:
            break
    if not symbols:
        symbols=list(US_SYMBOLS if region=='us' else SAUDI_SYMBOLS)
    with _EQUITY_UNIVERSE_LOCK:
        _EQUITY_UNIVERSE_CACHE[key]=(time.time(),list(symbols))
    return symbols

def _market_universe(market):
    if market=='forex': return FOREX_SYMBOLS
    if market=='us': return _yahoo_equity_universe('us',1000000)
    if market=='saudi': return _yahoo_equity_universe('sa',0)
    if market=='contracts': return US_CONTRACT_SYMBOLS
    return []

@app.get("/api/market-breadth")
def market_breadth(market:str="spot",timeframe:str="15m"):
    try:
        return _market_breadth(market,timeframe)
    except Exception:
        return JSONResponse({"ok":False,"message":"تعذر حساب صاعد وهابط حالياً"},status_code=502)

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
            rows,scanning=_cached_scan("spot",timeframe,lambda:_scan_spot_strategy(timeframe))
        elif market=="futures":
            rows,scanning=_cached_scan("futures",timeframe,lambda:_scan_binance_futures(timeframe))
        else:
            rows,scanning=_cached_scan(market,timeframe,lambda:_scan_yahoo_market(market,timeframe))
        if market=="spot":
            return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"scanning":scanning,
                    "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]}
        breadth=_breadth_binance(market,timeframe) if market=="futures" else _breadth_yahoo(market,timeframe)
        up=int(breadth.get("up") or 0); down=int(breadth.get("down") or 0)
        directional=up+down
        side="BUY" if up>down and directional and up/directional>=0.51 else "SELL" if down>up and directional and down/directional>=0.51 else "WAIT"
        allowed=[x for x in rows if str(x.get("side","")).upper()==side] if side in {"BUY","SELL"} else []
        return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"scanning":scanning,
                "direction":side,"breadth_up":up,"breadth_down":down,"breadth_flat":int(breadth.get("flat") or 0),
                "trades":[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(allowed)]}
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


def _futures_fast_signal(timeframe="15m"):
    if timeframe not in TIMEFRAMES: timeframe="15m"
    return fast_market_api("futures",timeframe)

@app.get("/api/futures/fast-signal")
def futures_fast_signal(timeframe:str="15m"):
    return _futures_fast_signal(timeframe)

@app.get("/futures-signal", response_class=HTMLResponse)
def futures_signal_page(request:Request):
    return page(request,"استراتيجية الفيوتشر")

@app.get("/futures-bot", response_class=HTMLResponse)
def futures_bot_page(request:Request):
    return page(request,"استراتيجية الفيوتشر")

def _spot_fast_payload(timeframe):
    rows,scanning=_cached_scan("spot",timeframe,lambda:_scan_spot_strategy(timeframe,20))
    trades=[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]
    breadth=_market_breadth("spot",timeframe)
    return {"ok":True,"market":"spot","market_name":MARKETS["spot"],"timeframe":timeframe,
            "breadth_up":int(breadth.get("up") or 0),"breadth_down":int(breadth.get("down") or 0),
            "breadth_flat":int(breadth.get("flat") or 0),"universe":int(breadth.get("universe") or 0),
            "scanning":scanning,"scanned":len(rows),"trade":trades[0] if trades else None,"trades":trades}

@app.get("/api/fast-market")
def fast_market_api(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    try:
        futures_20x_count=None
        if market=="spot":
            rows,scanning=_cached_scan("spot",timeframe,lambda:_scan_spot_strategy(timeframe,20))
        elif market=="futures":
            rows,scanning=_cached_scan("futures",timeframe,lambda:_scan_binance_futures(timeframe))
            try:
                _,futures_20x_count=_futures_20x_symbols()
            except Exception:
                futures_20x_count=None
        else:
            rows,scanning=_cached_scan(market,timeframe,lambda:_scan_yahoo_market(market,timeframe))
            if market in {"us","saudi"}:
                rows=[x for x in rows if str(x.get("side","")).upper()=="BUY"]

        if market=="futures":
            for x in rows:
                entry=float(x.get("entry") or 0)
                if entry<=0:                    continue
                x["leverage"]=20
                x["target_pct"]=10.0
                x["stop_pct"]=5.0
                x["profit_pct"]=10.0
                x["loss_pct"]=5.0
                if str(x.get("side","")).upper()=="SELL":
                    x["tp1"]=entry*0.995
                    x["tp2"]=entry*0.99
                    x["tp3"]=entry*0.985
                    x["sl"]=entry*1.0025
                else:
                    x["tp1"]=entry*1.005
                    x["tp2"]=entry*1.01
                    x["tp3"]=entry*1.015
                    x["sl"]=entry*0.9975
            public_fields={"symbol","side","timeframe","change_pct","profit_pct","loss_pct","ai_pct",
                           "entry","tp1","tp2","tp3","sl","status","tracking","tracking_status",
                           "leverage","target_pct","stop_pct"}
            rows=[{k:x.get(k) for k in public_fields if k in x} for x in rows]

        rows=sorted(rows,key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),reverse=True)[:20]
        if rows:
            from datetime import datetime,timezone
            now_iso=datetime.now(timezone.utc).isoformat()
            c=db()
            active_rows=c.execute("SELECT * FROM spot_signal_events WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 30",(market,timeframe)).fetchall()
            c.close()
            active=None
            for ar in active_rows:
                exp=str(ar["expires_at"] or "")
                if exp and exp > now_iso:
                    active=ar
                    break
            if active:
                first=dict(active)
                first["tracking"]=True
                first["tracking_status"]="متابعة حتى نهاية الفريم"
                first["expired_at"]=first.get("expires_at")
                rows=[first]+[x for x in rows if x.get("symbol")!=first.get("symbol")][:19]
            else:
                _record_signal(dict(rows[0],market=market), market=market)
                rows[0]["tracking"]=True
                rows[0]["tracking_status"]="متابعة حتى نهاية الفريم"
        return {"ok":True,"market":market,"market_name":MARKETS[market],"timeframe":timeframe,
                "scanning":bool(scanning),"scanned":len(rows),
                "futures_20x_count":futures_20x_count if market=="futures" else None,
                "trade":rows[0] if rows else None,
                "tracking":bool(rows and rows[0].get("tracking")),
                "tracking_status":"متابعة حتى الإغلاق" if rows and rows[0].get("tracking") else "",
                "trades":[dict(x,rank=i+1,medal="👑" if i==0 else "") for i,x in enumerate(rows)]}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":"تعذر فحص السوق حالياً","detail":str(exc)[:160]},status_code=502)

@app.get("/bot", response_class=HTMLResponse)
def standalone_bot_page(request:Request):
    return page(request,"البوت")

@app.get("/spot-bot", response_class=HTMLResponse)
def spot_bot_page(request:Request):
    return page(request,"بوت السبوت")

@app.get("/fast-spot", response_class=HTMLResponse)
def fast_spot_page(request:Request):
    return page(request,"استراتيجية السبوت")

@app.get("/fast-futures", response_class=HTMLResponse)
def fast_futures_page(request:Request):
    return page(request,"استراتيجية الفيوتشر")

@app.get("/fast-contracts", response_class=HTMLResponse)
def fast_contracts_page(request:Request):
    return page(request,"إشارة العقود الأمريكية")

@app.get("/fast-us", response_class=HTMLResponse)
def fast_us_page(request:Request):
    return page(request,"إشارة السوق الأمريكي")

@app.get("/fast-saudi", response_class=HTMLResponse)
def fast_saudi_page(request:Request):
    return page(request,"إشارة السوق السعودي")

@app.get("/fast-forex", response_class=HTMLResponse)
def fast_forex_page(request:Request):
    return page(request,"إشارة فوركس وذهب")

@app.get("/list", response_class=HTMLResponse)
def liquidity_list_page(request:Request):
    return page(request,"قائمة Liquidity Sweep")

@app.post("/api/admin/message")
def admin_message(request:Request,title:str=Form(...),body:str=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); c.execute("UPDATE messages SET active=0"); c.execute("INSERT INTO messages(title,body,active) VALUES(?,?,1)",(title,body)); c.commit(); c.close()
    return {"ok":True,"message":"تم نشر الرسالة"}
# ===== MANUAL REAL BINANCE ORDER EXECUTION =====
# These endpoints are intentionally explicit/manual: no background trading.
# API keys stay server-side in Northflank env vars.
def _trade_user_required(request:Request):
    # Real-money execution must not be exposed to anonymous visitors.
    return current_user(request)

def _signed_binance_request(base_url, method, path, params, api_key, api_secret, timeout=12):
    import time, urllib.parse, urllib.request, urllib.error, hmac, hashlib, json
    p=dict(params or {})
    p.setdefault("timestamp", int(time.time()*1000))
    p.setdefault("recvWindow", 5000)
    payload=urllib.parse.urlencode(p, doseq=True)
    sig=hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    url=base_url+path
    headers={"X-MBX-APIKEY":api_key,"User-Agent":"mudarib-pro/real-trade/1.0"}
    try:
        if method.upper()=="GET":
            req=urllib.request.Request(url+"?"+payload+"&signature="+sig,headers=headers,method="GET")
        else:
            body=payload+"&signature="+sig
            req=urllib.request.Request(url,data=body.encode(),headers={**headers,"Content-Type":"application/x-www-form-urlencoded"},method=method.upper())
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode("utf-8","ignore")
        try: detail=json.loads(raw)
        except Exception: detail={"code":exc.code,"msg":raw[:240]}
        raise RuntimeError(str(detail.get("msg") or detail)[:300])

def _trade_secrets():
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET غير مهيأة في Northflank")
    return key,secret

def _decimal_step(value, step):
    from decimal import Decimal, ROUND_DOWN
    v=Decimal(str(value)); s=Decimal(str(step or "0"))
    if s<=0:return float(v)
    return float((v/s).to_integral_value(rounding=ROUND_DOWN)*s)

def _spot_symbol_rules(symbol, api_key, api_secret):
    d=_binance_json("https://api.binance.com/api/v3/exchangeInfo?symbol="+urllib.parse.quote(symbol),timeout=8)
    info=(d.get("symbols") or [None])[0]
    if not info: raise RuntimeError("رمز السبوت غير موجود على Binance")
    lot=next((f for f in info.get("filters",[]) if f.get("filterType")=="LOT_SIZE"),{})
    price=next((f for f in info.get("filters",[]) if f.get("filterType")=="PRICE_FILTER"),{})
    notional=next((f for f in info.get("filters",[]) if f.get("filterType") in {"NOTIONAL","MIN_NOTIONAL"}),{})
    return info,lot,price,notional

def _spot_real_entry(signal):
    symbol=str(signal.get("symbol") or "").upper()
    if not symbol.endswith("USDT"): raise RuntimeError("السبوت يقبل أزواج USDT فقط")
    side=str(signal.get("side") or "BUY").upper()
    if side!="BUY": raise RuntimeError("زر دخول السبوت مخصص للشراء فقط")
    key,secret=_trade_secrets()
    _,lot,price_filter,notional=_spot_symbol_rules(symbol,key,secret)
    acct=_signed_binance_request("https://api.binance.com","GET","/api/v3/account",{},key,secret)
    usdt=next((float(b.get("free") or 0) for b in acct.get("balances",[]) if b.get("asset")=="USDT"),0.0)
    # Leave a small fee/rounding reserve so MARKET BUY cannot fail on commission.
    spend=usdt*0.995
    min_notional=float(notional.get("minNotional") or 0)
    if spend<=0 or spend<min_notional: raise RuntimeError(f"رصيد USDT غير كافٍ للتنفيذ: {usdt:.8f}")
    order=_signed_binance_request("https://api.binance.com","POST","/api/v3/order",{
        "symbol":symbol,"side":"BUY","type":"MARKET","quoteOrderQty":f"{spend:.8f}","newOrderRespType":"FULL"
    },key,secret)
    qty=float(order.get("executedQty") or 0)
    quote=float(order.get("cummulativeQuoteQty") or spend)
    if qty<=0: raise RuntimeError("Binance لم تنفذ كمية شراء")
    entry=quote/qty if quote>0 else float(signal.get("entry") or 0)
    tick=float(price_filter.get("tickSize") or 0)
    tp=float(signal.get("tp1") or entry*1.005)
    sl=float(signal.get("sl") or entry*0.9975)
    if tp<=entry: tp=entry*1.005
    if sl>=entry: sl=entry*0.9975
    tp=_decimal_step(tp,tick); sl=_decimal_step(sl,tick)
    if tp<=entry or sl>=entry: raise RuntimeError("مستويات TP/SL غير صالحة بعد التقريب")
    # Current Spot OCO is represented by two linked exit legs; use the public
    # order-list endpoint. If it is rejected, the market BUY remains real and
    # the error is surfaced instead of pretending protection exists.
    oco=_signed_binance_request("https://api.binance.com","POST","/api/v3/order/oco",{
        "symbol":symbol,"side":"SELL","quantity":f"{_decimal_step(qty,float(lot.get('stepSize') or 0)):.12f}",
        "price":f"{tp:.12f}","stopPrice":f"{sl:.12f}",
        "stopLimitPrice":f"{sl:.12f}","stopLimitTimeInForce":"GTC"
    },key,secret)
    return {"symbol":symbol,"side":"BUY","entry":entry,"qty":qty,"spent_usdt":quote,
            "tp_price":tp,"sl_price":sl,"order_id":order.get("orderId"),
            "protection":oco}

@app.post("/api/spot/entry")
async def spot_entry_api(request:Request):
    user=_trade_user_required(request)
    if not user:
        return JSONResponse({"ok":False,"message":"سجّل الدخول أولاً لتنفيذ أمر حقيقي على Binance"},status_code=401)
    try:
        signal=await request.json()
        trade=_spot_real_entry(signal if isinstance(signal,dict) else {})
        return {"ok":True,"trade":trade}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":str(exc)[:300]},status_code=400)

def _futures_symbol_rules(symbol):
    d=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=10)
    info=next((x for x in d.get("symbols",[]) if x.get("symbol")==symbol),None)
    if not info: raise RuntimeError("رمز الفيوتشر غير موجود على Binance")
    lot=next((f for f in info.get("filters",[]) if f.get("filterType")=="LOT_SIZE"),{})
    price=next((f for f in info.get("filters",[]) if f.get("filterType")=="PRICE_FILTER"),{})
    return info,lot,price

def _futures_real_entry(signal):
    symbol=str(signal.get("symbol") or "").upper()
    if not symbol.endswith("USDT"): raise RuntimeError("رمز Futures غير صالح")
    side=str(signal.get("side") or "").upper()
    if side not in {"BUY","SELL"}: raise RuntimeError("اتجاه الصفقة غير صالح")
    key,secret=_trade_secrets()
    _,lot,price_filter=_futures_symbol_rules(symbol)
    # Set the requested leverage first.
    _signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/leverage",
                            {"symbol":symbol,"leverage":20},key,secret)
    bal=_signed_binance_request("https://fapi.binance.com","GET","/fapi/v2/balance",{},key,secret)
    available=next((float(x.get("availableBalance") or 0) for x in bal if x.get("asset")=="USDT"),0.0)
    margin=available*0.985
    if margin<=0: raise RuntimeError(f"الهامش المتاح USDT غير كافٍ: {available:.8f}")
    price=float(signal.get("entry") or 0)
    if price<=0:
        mp=_binance_futures_json(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={urllib.parse.quote(symbol)}",timeout=5)
        price=float(mp.get("price") or 0)
    if price<=0: raise RuntimeError("تعذر الحصول على سعر الدخول")
    qty=_decimal_step((margin*20)/price,float(lot.get("stepSize") or 0))
    min_qty=float(lot.get("minQty") or 0)
    if qty<min_qty: raise RuntimeError(f"الكمية أقل من الحد الأدنى: {qty} < {min_qty}")
    entry_side=side
    market_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/order",{
        "symbol":symbol,"side":entry_side,"type":"MARKET","quantity":f"{qty:.12f}",
        "newOrderRespType":"RESULT"
    },key,secret)
    executed=float(market_order.get("executedQty") or qty)
    avg=float(market_order.get("avgPrice") or price)
    if executed<=0: raise RuntimeError("Binance Futures لم تنفذ الصفقة")
    # 10% target / 5% stop on margin = +0.5% / -0.25% underlying at 20x.
    if side=="BUY":
        tp=avg*1.005; sl=avg*0.9975; exit_side="SELL"
    else:
        tp=avg*0.995; sl=avg*1.0025; exit_side="BUY"
    tick=float(price_filter.get("tickSize") or 0)
    tp=_decimal_step(tp,tick); sl=_decimal_step(sl,tick)
    # Since Binance moved conditional Futures orders to the Algo Order API,
    # use the current /fapi/v1/algoOrder endpoint for both protection legs.
    tp_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/algoOrder",{
        "algoType":"CONDITIONAL","symbol":symbol,"side":exit_side,"type":"TAKE_PROFIT_MARKET",
        "triggerPrice":f"{tp:.12f}","closePosition":"true","workingType":"MARK_PRICE"
    },key,secret)
    try:
        sl_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/algoOrder",{
            "algoType":"CONDITIONAL","symbol":symbol,"side":exit_side,"type":"STOP_MARKET",
            "triggerPrice":f"{sl:.12f}","closePosition":"true","workingType":"MARK_PRICE"
        },key,secret)
    except Exception as exc:
        # If the stop could not be created, immediately flatten the position
        # rather than leaving an unprotected leveraged position.
        try:
            _signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/order",{
                "symbol":symbol,"side":exit_side,"type":"MARKET","quantity":f"{executed:.12f}"
            },key,secret)
        except Exception:
            pass
        raise RuntimeError("تم فتح الصفقة لكن تعذر وضع الوقف؛ تمت محاولة الإغلاق فوراً: "+str(exc)[:220])
    return {"symbol":symbol,"side":side,"entry":avg,"qty":executed,"margin_usdt":margin,
            "notional_usdt":margin*20,"leverage":20,"target_margin_pct":10,
            "stop_margin_pct":5,"tp_price":tp,"sl_price":sl,
            "order_id":market_order.get("orderId"),"tp_order":tp_order,"sl_order":sl_order}

@app.post("/api/futures/entry")
async def futures_entry_api(request:Request):
    user=_trade_user_required(request)
    if not user:
        return JSONResponse({"ok":False,"message":"سجّل الدخول أولاً لتنفيذ أمر حقيقي على Binance"},status_code=401)
    try:
        signal=await request.json()
        trade=_futures_real_entry(signal if isinstance(signal,dict) else {})
        return {"ok":True,"trade":trade}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":str(exc)[:300]},status_code=400)

@app.get("/api/futures/preflight")
def futures_preflight_api(request:Request):
    user=_trade_user_required(request)
    if not user:
        return JSONResponse({"ok":False,"message":"سجّل الدخول أولاً لتنفيذ أمر حقيقي على Binance"},status_code=401)
    try:
        key,secret=_trade_secrets()
        bal=_signed_binance_request("https://fapi.binance.com","GET","/fapi/v2/balance",{},key,secret)
        available=next((float(x.get("availableBalance") or 0) for x in bal if x.get("asset")=="USDT"),0.0)
        return {"ok":True,"available_usdt":available,"suggested_margin_usdt":available*0.985,"leverage":20,
                "target_margin_pct":10,"stop_margin_pct":5}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":str(exc)[:300]},status_code=400)

# ===== MANUAL REAL ORDER EXECUTION =====
# Automatic Spot/Futures bots are removed. Orders are placed only by explicit Entry buttons.
# ===== REAL ORDER EXECUTION =====
# Automatic trading workers are disabled. Real orders are placed only by an explicit Entry button.
_FUTURES_WORKER_STARTED=False
_SPOT_WORKER_STARTED=False

@app.on_event("startup")
def _start_real_bot_workers():
    print("[REAL-ORDERS] automatic bots disabled; manual Entry only",flush=True)

@app.get("/api/bots/status")
def all_bots_status():
    configured=bool(os.getenv("BINANCE_API_KEY","").strip() and os.getenv("BINANCE_API_SECRET","").strip())
    return {
        "ok":True,"configured":configured,
        "spot":{"enabled":configured,"status":"manual-entry","timeframe":"15m","real_orders":configured},
        "futures":{"enabled":configured,"status":"manual-entry","timeframe":"15m","real_orders":configured}
    }

# ===== STABLE API CORE =====
# Canonical market/data endpoints live here. This is intentionally kept in app.py
# so the service does not depend on runtime monkey-patching from sitecustomize.
_OPP_CACHE={"at":0.0,"rows":{}}
_OPP_TTL=20.0
_RADAR_CACHE={"at":0.0,"rows":[]}

def _market_scan_rows(market, timeframe="15m"):
    if market not in MARKETS:
        return []
    if timeframe not in TIMEFRAMES:
        timeframe="15m"
    if market=="spot":
        return _scan_spot_strategy(timeframe,20)
    if market=="futures":
        return _scan_binance_futures(timeframe)
    return _scan_yahoo_market(market,timeframe)

def opportunities(market="spot", timeframe="15m"):
    """Canonical internal API: always returns a list, never a response object."""
    key=(str(market),str(timeframe))
    now=time.time()
    cached=_OPP_CACHE["rows"].get(key)
    if cached is not None and now-_OPP_CACHE["at"]<_OPP_TTL:
        return list(cached)
    try:
        rows=_market_scan_rows(market,timeframe)
    except Exception:
        rows=[]
    # External research is additive only; never fabricate levels.
    try:
        import research_engine
        extra=research_engine.decide(research_engine.discover(market))
        if extra:
            rows=list(rows or [])
            seen={(str(x.get("symbol")),str(x.get("side") or x.get("direction")),str(x.get("entry")),str(x.get("sl"))) for x in rows}
            for x in extra:
                if timeframe!="15m" and str(x.get("timeframe"))=="15m":
                    continue
                k=(str(x.get("symbol")),str(x.get("side") or x.get("direction")),str(x.get("entry")),str(x.get("sl")))
                if k not in seen:
                    x=dict(x); x["side"]=x.get("direction"); x["timeframe"]=x.get("timeframe") or "حسب المصدر"
                    rows.append(x); seen.add(k)
    except Exception:
        pass
    rows=sorted(rows,key=lambda x:(float(x.get("recommendation_score") or x.get("ai_pct") or x.get("score") or 0),abs(float(x.get("change_pct") or 0))),reverse=True)[:50]
    _OPP_CACHE["rows"][key]=list(rows)
    _OPP_CACHE["at"]=now
    return list(rows)

def _public_market_row(x,market):
    d=dict(x or {})
    side=str(d.get("side") or d.get("direction") or "").upper()
    d["side"]=side
    d["direction"]=side
    d["market"]=market
    d["recommendation_score"]=float(d.get("recommendation_score") or d.get("ai_pct") or d.get("score") or 0)
    d["source_count"]=int(d.get("source_count") or d.get("research_sources") or 0)
    d["detected_at"]=float(d.get("detected_at") or time.time())
    if not d.get("targets"):
        d["targets"]=[d[k] for k in ("tp1","tp2","tp3") if d.get(k) not in (None,"")]
    return d

@app.get("/api/opportunities")
def opportunities_api(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS:
        return JSONResponse({"ok":False,"message":"قسم سوق غير صالح"},status_code=400)
    if timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        rows=[_public_market_row(x,market) for x in opportunities(market,timeframe)]
        return {"ok":True,"market":market,"timeframe":timeframe,"opportunities":rows,
                "scan_stats":{"analyzed":len(rows),"valid_15m":sum(1 for x in rows if x.get("timeframe")=="15m"),
                              "updated_at":time.time(),"scanning":False}}
    except Exception as exc:
        # A temporary provider failure must not turn the whole page into a 502.
        return {"ok":True,"market":market,"timeframe":timeframe,"opportunities":[],
                "scan_stats":{"analyzed":0,"valid_15m":0,"updated_at":time.time(),"scanning":True},
                "message":"جاري إعادة فحص بيانات السوق"}

@app.get("/api/radar")
def radar_api():
    global _RADAR_CACHE
    now=time.time()
    if now-_RADAR_CACHE["at"]<20:
        return {"ok":True,"opportunities":_RADAR_CACHE["rows"],"updated_at":_RADAR_CACHE["at"]}
    all_rows=[]
    for market in MARKETS:
        try:
            all_rows.extend(_public_market_row(x,market) for x in opportunities(market,"15m"))
        except Exception:
            continue
    all_rows.sort(key=lambda x:float(x.get("recommendation_score") or 0),reverse=True)
    _RADAR_CACHE={"at":now,"rows":all_rows[:100]}
    return {"ok":True,"opportunities":_RADAR_CACHE["rows"],"updated_at":now}

@app.get("/api/gold-signals")
def gold_signals_api():
    rows=[]
    for market in MARKETS:
        try:
            rows.extend(_public_market_row(x,market) for x in opportunities(market,"15m"))
        except Exception:
            continue
    rows.sort(key=lambda x:float(x.get("recommendation_score") or 0),reverse=True)
    out=[]
    for i,x in enumerate(rows[:10]):
        y=dict(x); y["ai"]=y.get("recommendation_score",0); y["alignment"]=y.get("research_agreement",0)
        y["rank"]=i+1; out.append(y)
    return {"ok":True,"signals":out,"updated":time.time()}

@app.get("/api/blog")
def blog_api():
    try:
        from content import BLOG
        return {"ok":True,"items":BLOG,"updated":time.time()}
    except Exception:
        return {"ok":True,"items":[],"updated":time.time()}

@app.get("/api/news")
def news_api_direct():
    try:
        import news_engine
        return {"ok":True,"items":news_engine.get_news(),"generated_at":time.time(),
                "mode":"arabic multi-market intelligence","sources_hidden":True}
    except Exception:
        return {"ok":True,"items":[],"generated_at":time.time(),"sources_hidden":True,"message":"جاري تحديث الأخبار"}

# Results is a first-class API, not a side-loaded router.
try:
    import results as _results_module
    app.include_router(_results_module.router)
except Exception:
    pass

# Admin/auth controls are installed explicitly during normal app import.
try:
    import admin_access as _admin_access
    _admin_access.install()
except Exception as _admin_exc:
    print("[ADMIN] install failed:",_admin_exc,flush=True)

