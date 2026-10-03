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
    CREATE TABLE IF NOT EXISTS futures_execution_lease(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT,expires_at REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
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
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN auto_enabled INTEGER NOT NULL DEFAULT 0")
    except Exception: pass
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN last_error TEXT")
    except Exception: pass
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN halted INTEGER NOT NULL DEFAULT 0")
    except Exception: pass
    try: c.execute("ALTER TABLE futures_bot_state ADD COLUMN halt_reason TEXT")
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
def binance_status_api():
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
        delayed_worker(_crypto_analysis_worker,"crypto-analysis-15m")
        if "_spot_outcome_worker" in globals():
            delayed_worker(_spot_outcome_worker,"spot-signal-outcomes")
        # Futures worker يعمل 24/7، والتنفيذ الحقيقي مفعّل افتراضياً؛ يبقى متوقفاً فقط عند تفعيل دائرة الحماية.
        delayed_worker(_futures_real_supervisor,"auto-futures-real",delay=20)
        print("[AUTO-FUTURES] 24/7 REAL worker scheduled with automatic restart supervision", flush=True)
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
def binance_futures_status_api():
    return _binance_futures_private_status()

def _futures_available_usdt():
    """Read-only: available USDT from the user's Binance USDⓈ-M Futures account."""
    status=_binance_futures_private_status()
    if not status.get("connected"):
        return None,status
    try:
        return max(0.0,float(status.get("available_usdt") or 0)),status
    except Exception:
        return 0.0,status

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

def _futures_bot_price(symbol):
    if not symbol:return None
    try:
        d=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/price?"+urllib.parse.urlencode({"symbol":symbol}),timeout=5)
        return float(d.get("price"))
    except Exception:
        return None

def _futures_exchange_position(symbol):
    if not symbol:
        return None
    if not os.getenv("BINANCE_API_KEY","").strip() or not os.getenv("BINANCE_API_SECRET","").strip():
        return None
    try:
        rows=_binance_futures_signed_request("GET","/fapi/v3/positionRisk",{"symbol":str(symbol).upper()})
        if not isinstance(rows,list):
            return None
        total=0.0
        for row in rows:
            if str(row.get("symbol","")).upper()!=str(symbol).upper():
                continue
            try:
                total += abs(float(row.get("positionAmt") or 0))
            except Exception:
                pass
        return total
    except Exception as exc:
        print(f"[AUTO-FUTURES] exchange position check failed symbol={symbol} error={type(exc).__name__}: {str(exc)[:180]}", flush=True)
        return None

def _futures_exchange_position_info(symbol):
    """Return live Binance position quantity/entry price for order reconciliation."""
    if not symbol:
        return None
    try:
        rows=_binance_futures_signed_request("GET","/fapi/v3/positionRisk",{"symbol":str(symbol).upper()})
        if not isinstance(rows,list):
            return None
        best=None
        for row in rows:
            if str(row.get("symbol","")).upper()!=str(symbol).upper():
                continue
            try:
                qty=abs(float(row.get("positionAmt") or 0))
            except Exception:
                qty=0.0
            if qty<=0:
                continue
            try:
                entry=float(row.get("entryPrice") or 0)
            except Exception:
                entry=0.0
            if best is None or qty>best["quantity"]:
                best={"quantity":qty,"entry_price":entry,"position_side":str(row.get("positionSide") or "")}
        return best
    except Exception as exc:
        print(f"[AUTO-FUTURES] exchange position info failed symbol={symbol} error={type(exc).__name__}: {str(exc)[:180]}", flush=True)
        return None

def _futures_open_protection_orders(symbol):
    rows=_binance_futures_signed_request("GET","/fapi/v1/openOrders",{"symbol":str(symbol).upper()})
    return [x for x in (rows if isinstance(rows,list) else []) if str(x.get("type","")).upper() in ("STOP_MARKET","TAKE_PROFIT_MARKET")]

def _futures_cancel_order(symbol,order_id):
    return _binance_futures_signed_request("DELETE","/fapi/v1/order",{"symbol":str(symbol).upper(),"orderId":str(order_id)})

def _futures_market_close(symbol,side,quantity,position_side=None):
    p={"symbol":str(symbol).upper(),"side":"SELL" if str(side).upper()=="BUY" else "BUY","type":"MARKET","quantity":str(quantity).rstrip("0").rstrip("."),
       "reduceOnly":"false" if position_side else "true"}
    if position_side:p["positionSide"]=position_side
    return _binance_futures_signed_request("POST","/fapi/v1/order",p)

def _futures_emergency_close(symbol, side, attempts=5):
    """Aggressive safety close for a bot-managed live Binance position."""
    import time
    symbol=str(symbol or "").upper()
    side=str(side or "BUY").upper()
    if not symbol:
        return False
    for attempt in range(max(1,int(attempts))):
        try:
            qty=float(_futures_exchange_position(symbol) or 0)
            if qty<=0:
                return True
            rules=_futures_symbol_rules(symbol)
            qty=_floor_step(qty,rules.get("step_size",0))
            if qty<=0:
                return False
            dual=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
            hedge=bool(dual.get("dualSidePosition"))
            ps=("LONG" if side=="BUY" else "SHORT") if hedge else None
            _futures_market_close(symbol,side,qty,ps)
            time.sleep(0.35)
            remaining=_futures_exchange_position(symbol)
            if remaining is not None and remaining<=0:
                print("[AUTO-FUTURES] EMERGENCY CLOSE confirmed symbol={} attempt={}".format(symbol,attempt+1),flush=True)
                return True
            print("[AUTO-FUTURES] EMERGENCY CLOSE retry symbol={} attempt={} remaining={}".format(symbol,attempt+1,remaining),flush=True)
        except Exception as exc:
            print("[AUTO-FUTURES] EMERGENCY CLOSE failed symbol={} attempt={} error={}: {}".format(symbol,attempt+1,type(exc).__name__,str(exc)[:220]),flush=True)
        time.sleep(min(2.0,0.4*(attempt+1)))
    return False


def _futures_halt(reason):
    """Safety circuit breaker: stop opening new Futures positions until manual restart."""
    stamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    _futures_bot_write({
        "halted":1,
        "enabled":0,
        "last_error":str(reason)[:500],
        "halt_reason":str(reason)[:500],
        "last_checked_at":stamp
    })
    print("[AUTO-FUTURES] SAFETY HALT: {}".format(str(reason)[:500]),flush=True)

def _futures_ensure_protection(state,px=None):
    symbol=str(state.get("symbol") or "").upper(); side=str(state.get("side") or "BUY").upper()
    entry=float(state.get("entry") or 0)
    if not symbol or entry<=0:
        _futures_halt("بيانات حماية غير صالحة")
        return {"ok":False,"message":"بيانات الحماية غير صالحة"}
    px=px or _futures_bot_price(symbol)
    if not px:
        _futures_halt("تعذر قراءة السعر الحالي للحماية")
        return {"ok":False,"message":"تعذر قراءة السعر الحالي"}
    profit=((px-entry)/entry*100) if side=="BUY" else ((entry-px)/entry*100)
    peak=max(float(state.get("peak_profit_pct") or 0),profit)
    rules=_futures_symbol_rules(symbol); tick=rules.get("tick_size",0)
    dual=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
    ps="LONG" if bool(dual.get("dualSidePosition")) and side=="BUY" else "SHORT" if bool(dual.get("dualSidePosition")) else None
    orders=_futures_open_protection_orders(symbol)
    stops=[o for o in orders if str(o.get("type","")).upper()=="STOP_MARKET"]
    for o in orders:
        if str(o.get("type","")).upper()=="TAKE_PROFIT_MARKET":
            try:_futures_cancel_order(symbol,o.get("orderId"))
            except Exception:pass
    # حماية أرباح أقوى: وقف الخسارة الأولي -5%، ثم يبدأ قفل الربح مبكراً
    # ويصعد كل 2.5 نقطة مئوية بدلاً من انتظار 5 نقاط كاملة.
    # هذا يقلل إعادة الأرباح عند الانعكاسات السريعة، مع عدم تحريك الوقف للخلف أبداً.
    if profit < 7.5:
        locked=-5.0
    else:
        locked=max(0.0, round((profit-5.0)/2.5)*2.5)
        locked=min(locked, profit-1.0)
    old_profit=float(state.get("protected_profit_pct") or 0)
    locked=max(locked, old_profit)
    desired=_round_step(entry*(1+locked/100) if side=="BUY" else entry*(1-locked/100),tick)
    if (side=="BUY" and desired>=px) or (side=="SELL" and desired<=px):
        _futures_halt("سعر الحماية غير صالح")
        return {"ok":False,"message":"سعر الحماية غير صالح"}
    old_price=float(stops[0].get("stopPrice") or 0) if stops else 0
    if stops and old_price>0 and locked<=old_profit:
        _futures_bot_write({"last_price":px,"peak_profit_pct":peak,"protected_profit_pct":max(old_profit,locked),"protection_price":old_price,
                            "last_checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
        return {"ok":True,"changed":False}
    base={"symbol":symbol,"side":"SELL" if side=="BUY" else "BUY","closePosition":"true","workingType":"MARK_PRICE"}
    if ps:base["positionSide"]=ps
    try:
        new=_binance_futures_signed_request("POST","/fapi/v1/order",dict(base,type="STOP_MARKET",stopPrice=f"{desired:.16f}".rstrip("0").rstrip(".")))
    except Exception as exc:
        if stops:
            _futures_halt("فشل تحديث حماية الصفقة؛ تم الإبقاء على وقف Binance الحالي")
            return {"ok":False,"kept_existing":True,"message":"فشل تحديث الحماية مع وجود وقف سابق","detail":str(exc)[:250]}
        _futures_halt("فشل إنشاء أول وقف حماية")
        _futures_emergency_close(symbol,side)
        return {"ok":False,"message":"فشل وضع الحماية وتمت محاولة إغلاق Market","detail":str(exc)[:250]}
    for o in stops:
        try:
            if str(o.get("orderId"))!=str(new.get("orderId")):_futures_cancel_order(symbol,o.get("orderId"))
        except Exception as exc:print("[AUTO-FUTURES] old stop cancel failed {}: {}".format(symbol,exc),flush=True)
    _futures_bot_write({"last_price":px,"peak_profit_pct":peak,"protected_profit_pct":locked,"protection_price":desired,
                        "last_checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    print("[AUTO-FUTURES] PROTECTION symbol={} profit={:.2f}% locked={:.2f}% stop={}".format(symbol,profit,locked,desired),flush=True)
    return {"ok":True,"changed":True,"protection_price":desired,"protected_profit_pct":locked}

def _futures_bot_tick():
    """Track a real Binance Futures position and maintain exchange-side protection."""
    state=_futures_bot_read()
    if state.get("status")!="open" or not state.get("symbol"): return state
    exchange_qty=_futures_exchange_position(state["symbol"])
    if exchange_qty is not None and exchange_qty<=0:
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"closed_at":now,"outcome":"exchange_closed","realized_pct":None,"last_checked_at":now})
        print("[AUTO-FUTURES] reconciled OPEN state symbol={} exchange_qty=0".format(state["symbol"]),flush=True)
        return _futures_bot_read()
    px=_futures_bot_price(state["symbol"])
    if px is None:return state
    try:
        protection=_futures_ensure_protection(state,px)
        if not protection.get("ok"):
            _futures_halt("فشل فحص/تحديث حماية الصفقة")
            return _futures_bot_read()
    except Exception as exc:
        _futures_halt("استثناء في محرك حماية الصفقة: {}".format(str(exc)[:300]))
        print("[AUTO-FUTURES] protection check failed symbol={} error={}: {}".format(state["symbol"],type(exc).__name__,str(exc)[:220]),flush=True)
        return _futures_bot_read()
    entry=float(state.get("entry") or 0); side=str(state.get("side") or "BUY").upper()
    profit=((px-entry)/entry*100) if side=="BUY" else ((entry-px)/entry*100)
    _futures_bot_write({"last_price":px,"last_checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                        "peak_profit_pct":max(float(state.get("peak_profit_pct") or 0),profit)})
    return _futures_bot_read()

def _binance_futures_signed_request(method, path, params=None):
    """Signed USD-M Futures request. Never retry a write order across gateways."""
    import time, hmac, hashlib, urllib.error
    from urllib.parse import urlencode
    key=os.getenv("BINANCE_API_KEY","").strip()
    secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret:
        raise RuntimeError("Binance API غير مهيأ")
    method=method.upper()
    q=dict(params or {})
    q["timestamp"]=int(time.time()*1000)
    q.setdefault("recvWindow",5000)
    encoded=urlencode(q)
    sig=hmac.new(secret.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    body=(encoded+"&signature="+sig).encode()
    hosts=("https://fapi.binance.com",) if method=="POST" else (
        "https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com",
        "https://fapi3.binance.com","https://fapi4.binance.com"
    )
    errors=[]
    for idx,base in enumerate(hosts):
        try:
            req=urllib.request.Request(
                base+path,
                data=body if method=="POST" else None,
                headers={"X-MBX-APIKEY":key,"Content-Type":"application/x-www-form-urlencoded","User-Agent":"mudarib-pro/1.0"},
                method=method
            )
            if method!="POST":
                req.full_url=base+path+"?"+encoded+"&signature="+sig
            with urllib.request.urlopen(req,timeout=10) as resp:
                raw=resp.read().decode("utf-8","replace").strip()
                if not raw:
                    raise RuntimeError(f"Binance returned empty response HTTP {getattr(resp,'status','?')}")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    raise RuntimeError(f"Binance returned invalid JSON HTTP {getattr(resp,'status','?')}: {raw[:180]}")
        except urllib.error.HTTPError as exc:
            raw=exc.read().decode("utf-8","replace")
            try: data=json.loads(raw)
            except Exception: data={"code":exc.code,"msg":raw[:240]}
            code=exc.code
            # A write request is never replayed after 429/418/5xx.
            if method=="POST":
                raise RuntimeError(f"Binance Futures: {data}")
            errors.append(str(data)[:320])
            if code in (418,429):
                retry_after=1
                try: retry_after=max(1,min(15,int(exc.headers.get("Retry-After","1"))))
                except Exception: pass
                time.sleep(retry_after)
        except Exception as exc:
            if method=="POST":
                raise
            errors.append(str(exc)[:240])
            time.sleep(0.25)
    raise RuntimeError("Binance Futures: "+" | ".join(errors[-3:]))

def _futures_symbol_rules(symbol):
    info=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=8)
    row=next((x for x in info.get("symbols",[]) if str(x.get("symbol"))==str(symbol)),None)
    if not row: raise RuntimeError("رمز الفيوتشر غير متاح حالياً")
    filters={str(f.get("filterType")):f for f in row.get("filters",[])}
    lot=filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE") or {}
    market_lot=filters.get("MARKET_LOT_SIZE") or lot
    price=filters.get("PRICE_FILTER",{})
    notional_filter=filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    min_notional=float(notional_filter.get("notional") or notional_filter.get("minNotional") or 0)
    return {
        "step_size":float(market_lot.get("stepSize") or lot.get("stepSize") or 0),
        "min_qty":float(market_lot.get("minQty") or lot.get("minQty") or 0),
        "max_qty":float(market_lot.get("maxQty") or lot.get("maxQty") or 0),
        "tick_size":float(price.get("tickSize") or 0),
        "min_notional":min_notional
    }

_FUTURES_20X_CACHE={"at":0.0,"symbols":set(),"count":0}

def _futures_max_leverage(symbol):
    """Read Binance's symbol-specific maximum initial leverage safely."""
    data=_binance_futures_signed_request("GET","/fapi/v1/leverageBracket",{"symbol":str(symbol).upper()})
    rows=data if isinstance(data,list) else [data]
    row=next((x for x in rows if str(x.get("symbol","")).upper()==str(symbol).upper()),None)
    brackets=(row or {}).get("brackets") or []
    values=[]
    for b in brackets:
        try:
            v=int(float(b.get("initialLeverage") or 0))
            if v>0: values.append(v)
        except Exception:
            pass
    if not values:
        raise RuntimeError("تعذر قراءة الحد الأقصى للرافعة لهذا الرمز من Binance")
    return max(values)

def _futures_20x_symbols():
    """Return the live Binance Futures symbols that support at least 20x."""
    import time
    now=time.time()
    if now-float(_FUTURES_20X_CACHE.get("at") or 0) < 60 and _FUTURES_20X_CACHE.get("symbols"):
        return set(_FUTURES_20X_CACHE["symbols"]), int(_FUTURES_20X_CACHE.get("count") or 0)
    data=_binance_futures_signed_request("GET","/fapi/v1/leverageBracket",{})
    rows=data if isinstance(data,list) else [data]
    eligible=set()
    for row in rows:
        symbol=str(row.get("symbol") or "").upper()
        if not symbol.endswith("USDT"):
            continue
        values=[]
        for b in row.get("brackets") or []:
            try:
                v=int(float(b.get("initialLeverage") or 0))
                if v>0: values.append(v)
            except Exception:
                pass
        if values and max(values)>=1:
            eligible.add(symbol)
    _FUTURES_20X_CACHE={"at":now,"symbols":eligible,"count":len(eligible)}
    return eligible,len(eligible)


def _futures_order_quantity(balance,entry,leverage,rules):
    if balance<=0 or entry<=0 or leverage<=0:
        raise RuntimeError("الرصيد أو سعر الدخول غير صالح")
    margin_pct=float(os.getenv("FUTURES_MARGIN_PCT","100") or 100)
    margin_pct=max(1.0,min(100.0,margin_pct))
    # Binance may reject using the literal full available balance because fees
    # and small margin/rounding requirements still need headroom (-2019).
    buffer_pct=float(os.getenv("FUTURES_MARGIN_BUFFER_PCT","2") or 2)
    buffer_pct=max(0.5,min(10.0,buffer_pct))
    requested_margin=balance*(margin_pct/100.0)
    safe_margin=balance*(1.0-buffer_pct/100.0)
    margin=min(requested_margin,safe_margin)
    raw_qty=(margin*leverage)/entry
    step=rules["step_size"]
    qty=_floor_step(raw_qty,step)
    min_qty=rules["min_qty"]
    min_notional=rules.get("min_notional",0.0)
    required_qty=min_qty
    if min_notional>0:
        required_qty=max(required_qty,min_notional/entry)
    if qty<=0 or qty<required_qty:
        # لا نرفع الكمية تلقائياً فوق الهامش المتاح؛ نتخطى الرمز بأمان.
        raise RuntimeError(f"الكمية المتاحة أقل من الحد الأدنى للرمز (المتاح={qty:g}, المطلوب>={required_qty:g})")
    if rules["max_qty"]>0:
        qty=min(qty,rules["max_qty"])
    if qty<=0 or qty<min_qty:
        raise RuntimeError("الكمية بعد التقريب أقل من الحد الأدنى للرمز")
    return qty,margin


def _floor_step(value, step):
    if step<=0:return float(value)
    return max(0.0, (int(float(value)/step+1e-12))*step)

def _round_step(value, step):
    if step<=0:return float(value)
    return round(round(float(value)/step)*step, 16)

def _futures_bot_prepare_real(timeframe="15m"):
    """Prepare the first Futures signal that Binance can actually execute."""
    if timeframe not in TIMEFRAMES: timeframe="15m"
    state=_futures_bot_tick()
    if state.get("halted"):
        return {"ok":False,"mode":"halted","message":"البوت متوقف لأسباب حماية؛ يحتاج تشغيل يدوي","bot":_futures_bot_read(),"real_orders":True}
    if state.get("status")=="open":
        return {"ok":True,"mode":"real_auto","message":"هناك صفقة حقيقية مفتوحة بالفعل","bot":_futures_bot_read(),"real_orders":True}
    payload=fast_market_api("futures",timeframe)
    rows=(payload.get("trades") or []) if isinstance(payload,dict) else []
    if not rows:
        return {"ok":False,"mode":"real_auto","message":"لا توجد إشارة فيوتشر مطابقة حالياً","real_orders":True}
    balance,status=_futures_available_usdt()
    if balance is None:
        return {"ok":False,"mode":"real_auto","message":"تعذر قراءة رصيد Binance","binance":status,"real_orders":True}
    if balance<=0:
        return {"ok":False,"mode":"real_auto","message":"رصيد USDT المتاح غير كافٍ","balance_usdt":balance,"real_orders":True}
    selected=None
    skipped=[]
    for candidate in rows:
        try:
            row=dict(candidate)
            symbol=str(row.get("symbol") or "").upper()
            entry=float(row.get("entry") or row.get("current") or 0)
            if not symbol.endswith("USDT") or entry<=0:
                continue
            max_lev=int(_futures_max_leverage(symbol))
            if max_lev<1:
                skipped.append(f"{symbol}:max{max_lev}x")
                continue
            leverage=min(20,max_lev)
            rules=_futures_symbol_rules(symbol)
            qty,margin=_futures_order_quantity(balance,entry,leverage,rules)
            selected=(row,entry,leverage,qty,margin)
            break
        except Exception as exc:
            skipped.append(f"{candidate.get('symbol','?')}:{str(exc)[:100]}")
    if not selected:
        print("[AUTO-FUTURES] no executable candidate balance={} skipped={}".format(balance, " | ".join(skipped[:8])), flush=True)
        return {"ok":False,"mode":"real_auto","message":"لا توجد إشارة قابلة للتنفيذ ضمن الرصيد والرافعة المتاحة حالياً","balance_usdt":balance,"skipped":skipped[:8],"real_orders":True}
    row,entry,leverage,quantity,margin=selected
    now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    notional=margin*leverage
    _futures_bot_write({
        "enabled":1,"status":"ready","symbol":row.get("symbol"),"side":row.get("side"),
        "timeframe":timeframe,"entry":entry,"tp1":row.get("tp1"),"tp2":row.get("tp2"),"tp3":row.get("tp3"),
        "sl":row.get("sl"),"score":row.get("score",row.get("ai_pct",0)),"ai_pct":row.get("ai_pct",0),
        "balance_usdt":balance,"margin_usdt":margin,"notional_usdt":notional,"quantity":quantity,
        "leverage":leverage,"peak_profit_pct":0,"protected_profit_pct":0,"protection_price":None,
        "opened_at":None,"closed_at":None,"outcome":None,"realized_pct":None,"last_price":entry,
        "last_checked_at":now,"auto_enabled":1
    })
    return {"ok":True,"mode":"real_auto","message":"تم تجهيز أول صفقة قابلة للتنفيذ الحقيقي","bot":_futures_bot_read(),"binance":{"connected":status.get("connected"),"balance_usdt":balance},"real_orders":True}

def _futures_real_supervisor():
    """Keep the real Futures worker alive across app/browser restarts; state is recovered from persistent storage/Binance."""
    """Keep the real Futures worker alive continuously if its thread ever exits unexpectedly."""
    import time
    while True:
        try:
            _futures_real_worker()
        except Exception as exc:
            print(f"[AUTO-FUTURES] supervisor restarting worker: {type(exc).__name__}: {str(exc)[:220]}", flush=True)
            time.sleep(5)

def _futures_real_worker():
    """Automatic Futures worker with a safety circuit breaker; manual restart required after a protection fault."""
    import time
    scan_every=15
    last_scan=0
    retry_after=0
    real_enabled=os.getenv("AUTO_REAL_FUTURES","1").strip().lower() in ("1","true","yes","on")
    shard_count,shard_index=_futures_shard_config()
    worker_id=os.getenv("HOSTNAME") or f"shard-{shard_index}"
    print(f"[AUTO-FUTURES] worker started mode={'REAL' if real_enabled else 'DISABLED'} shard={shard_index+1}/{shard_count} id={worker_id}", flush=True)
    # Crash/restart recovery: reconcile the persisted bot position against Binance before scanning.
    try:
        recovery_state=_futures_bot_read()
        recovery_symbol=str(recovery_state.get("symbol") or "").upper()
        if recovery_state.get("status")=="open" and recovery_symbol:
            live_qty=_futures_exchange_position(recovery_symbol)
            if live_qty is not None and live_qty>0:
                print("[AUTO-FUTURES] RECOVERY live position found symbol={} qty={}".format(recovery_symbol,live_qty),flush=True)
                if recovery_state.get("halted"):
                    _futures_emergency_close(recovery_symbol,str(recovery_state.get("side") or "BUY"),attempts=5)
            elif live_qty is not None and live_qty<=0:
                stamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"closed_at":stamp,
                                    "outcome":"restart_reconciled_closed","last_checked_at":stamp})
                print("[AUTO-FUTURES] RECOVERY no live position; local state reconciled closed",flush=True)
    except Exception as recovery_exc:
        print("[AUTO-FUTURES] RECOVERY check failed: {}: {}".format(type(recovery_exc).__name__,str(recovery_exc)[:220]),flush=True)
    while True:
        if not real_enabled:
            time.sleep(10)
            continue
        try:
            state=_futures_bot_read()
            if state.get("halted"):
                # Keep checking any remaining real position and try to close it.
                symbol_h=str(state.get("symbol") or "").upper()
                if state.get("status")=="open" and symbol_h:
                    try:
                        q_h=_futures_exchange_position(symbol_h)
                        if q_h is not None and q_h>0:
                            side_h=str(state.get("side") or "BUY").upper()
                            rules_h=_futures_symbol_rules(symbol_h)
                            qty_h=_floor_step(q_h,rules_h.get("step_size",0))
                            dual_h=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
                            ps_h="LONG" if bool(dual_h.get("dualSidePosition")) and side_h=="BUY" else "SHORT" if bool(dual_h.get("dualSidePosition")) else None
                            if qty_h>0:
                                closed_h=_futures_emergency_close(symbol_h,side_h,attempts=5)
                                print("[AUTO-FUTURES] SAFETY HALT emergency close result symbol={} closed={}".format(symbol_h,closed_h),flush=True)
                            remain_h=_futures_exchange_position(symbol_h)
                            if remain_h is not None and remain_h<=0:
                                stamp_h=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                                _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"halted":1,
                                                    "closed_at":stamp_h,"outcome":"safety_halt_closed","last_checked_at":stamp_h})
                                print("[AUTO-FUTURES] SAFETY HALT position confirmed closed symbol={}".format(symbol_h),flush=True)
                    except Exception as close_h_exc:
                        print("[AUTO-FUTURES] SAFETY HALT close retry failed symbol={} error={}: {}".format(symbol_h,type(close_h_exc).__name__,str(close_h_exc)[:220]),flush=True)
                time.sleep(10)
                continue
            state=_futures_bot_tick()
            if state.get("halted"):
                time.sleep(10)
                continue
            now=time.time()
            status=str(state.get("status") or "idle")
            symbol=str(state.get("symbol") or "")
            print(f"[AUTO-FUTURES] tick status={status} symbol={symbol}", flush=True)
            if status=="open":
                # A local DB flag is never proof of an exchange position.
                if not state.get("auto_enabled"):
                    stamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                    _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"closed_at":stamp,
                                        "outcome":"legacy_state","realized_pct":0,"last_checked_at":stamp})
                    print(f"[AUTO-FUTURES] retired legacy local state symbol={symbol}; waiting for fresh REAL signal", flush=True)
                    status="closed"
                else:
                    exchange_qty=_futures_exchange_position(symbol)
                    if exchange_qty is not None and exchange_qty <= 0:
                        stamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                        _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"closed_at":stamp,
                                            "outcome":"exchange_closed","realized_pct":None,"last_checked_at":stamp})
                        print(f"[AUTO-FUTURES] reconciled stale OPEN state symbol={symbol}; Binance position is closed", flush=True)
                        status="closed"
            if status!="open" and now-last_scan>=scan_every and now>=retry_after:
                # Futures auto-entry always evaluates the requested strategy on 15m.
                # Do not change the strategy conditions here.
                timeframe="15m"
                result=_futures_bot_prepare_real(timeframe)
                bot=result.get("bot") or {}
                print(f"[AUTO-FUTURES] prepare ok={result.get('ok')} status={bot.get('status')} symbol={bot.get('symbol')} message={result.get('message')}", flush=True)
                if result.get("ok") and bot.get("status")=="ready":
                    if not _futures_execution_lease(worker_id,ttl=45):
                        print(f"[AUTO-FUTURES] shard {shard_index+1}/{shard_count} skipped execution: lease owned by another worker",flush=True)
                        time.sleep(2)
                        continue
                    try:
                        execution=_futures_bot_execute_real()
                    finally:
                        _futures_execution_lease_release(worker_id)
                    detail=str(execution.get("detail") or "")
                    # Log the Binance error without credentials/signatures so the real
                    # reason for a rejected order is visible in Northflank.
                    if not execution.get("ok"):
                        retry_after=time.time()+60
                        print(f"[AUTO-FUTURES] REAL execution ok=False symbol={bot.get('symbol')} message={execution.get('message')} detail={detail[:500]}", flush=True)
                    else:
                        print(f"[AUTO-FUTURES] REAL execution ok=True symbol={bot.get('symbol')} message={execution.get('message')}", flush=True)
                last_scan=now
        except Exception as exc:
            print(f"[AUTO-FUTURES] loop error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(10)

@app.get("/api/futures/bot")
def futures_bot_status():
    real_enabled=os.getenv("AUTO_REAL_FUTURES","1").strip().lower() in ("1","true","yes","on")
    bot=_futures_bot_tick() if not _futures_bot_read().get("halted") else _futures_bot_read()
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
    return {
        "ok":True,
        "mode":"real_auto" if real_enabled else "disabled",
        "real_orders":real_enabled,
        "message":("بوت الفيوتشر متوقف للحماية — يحتاج تشغيل يدوي" if bot.get("halted") else
                   "بوت الفيوتشر الآلي الحقيقي مفعّل" if real_enabled else "بوت الفيوتشر الآلي غير مفعّل"),
        "bot":bot
    }

@app.post("/api/futures/bot/start")
def futures_bot_start(timeframe:str="15m"):
    """Manual safety reset: clears the circuit breaker, then prepares one real scan."""
    real_enabled=os.getenv("AUTO_REAL_FUTURES","1").strip().lower() in ("1","true","yes","on")
    if not real_enabled:
        return {"ok":False,"mode":"disabled","message":"التنفيذ الحقيقي الآلي غير مفعّل"}
    _futures_bot_write({"halted":0,"halt_reason":None,"last_error":None,"enabled":0})
    result=_futures_bot_prepare_real(timeframe)
    if not result.get("ok"):
        return result
    return result

def _futures_bot_execute_real():
    """Execute the prepared Futures signal using the Binance credentials configured in Northflank."""
    if not os.getenv("BINANCE_API_KEY","").strip() or not os.getenv("BINANCE_API_SECRET","").strip():
        return {"ok":False,"message":"BINANCE_API_KEY و BINANCE_API_SECRET غير مهيأة في Northflank"}
    state=_futures_bot_read()
    if state.get("status")!="ready":
        return {"ok":False,"message":"لا توجد صفقة جاهزة للتنفيذ","bot":state}
    symbol=str(state.get("symbol") or "").upper()
    side=str(state.get("side") or "BUY").upper()
    if not symbol.endswith("USDT") or side not in ("BUY","SELL"):
        return {"ok":False,"message":"بيانات الصفقة غير صالحة","bot":state}
    try:
        rules=_futures_symbol_rules(symbol)
        entry=float(state.get("entry") or 0)
        requested_leverage=int(os.getenv("FUTURES_LEVERAGE","20"))
        requested_leverage=max(1,requested_leverage)
        balance,status=_futures_available_usdt()
        if balance is None or balance<=0 or entry<=0:
            raise RuntimeError("الرصيد أو سعر الدخول غير صالح")
        # الحد الأعلى المسموح به 20x: استخدم 20x إذا كان متاحاً، وإلا استخدم الحد الأقصى الفعلي للرمز.
        max_leverage=_futures_max_leverage(symbol)
        if max_leverage < 1:
            raise RuntimeError(f"الرمز {symbol} لا يدعم رافعة صالحة — تم تخطي الدخول")
        # إذا كان الحد الأعلى أكبر من 20x نثبت الرافعة عند 20x.
        leverage=min(20, int(max_leverage))
        # احسب الكمية على الرافعة الفعلية، وبحد أقصى 20x.
        qty,margin=_futures_order_quantity(balance,entry,leverage,rules)
        _binance_futures_signed_request("POST","/fapi/v1/leverage",{"symbol":symbol,"leverage":leverage})
        dual=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
        position_side="LONG" if bool(dual.get("dualSidePosition")) and side=="BUY" else "SHORT" if bool(dual.get("dualSidePosition")) else None
        # امنع تكرار الدخول إذا كان Binance عنده مركز حقيقي قبل إرسال الأمر.
        existing=_futures_exchange_position_info(symbol)
        if existing and float(existing.get("quantity") or 0)>0:
            raise RuntimeError(f"يوجد مركز حقيقي مفتوح مسبقاً على {symbol}؛ لن يتم فتح مركز ثانٍ")
        entry_params={
            "symbol":symbol,"side":side,"type":"MARKET",
            "quantity":f"{qty:.16f}".rstrip("0").rstrip("."),
            "newOrderRespType":"RESULT"
        }
        if position_side: entry_params["positionSide"]=position_side
        entry_order=_binance_futures_signed_request("POST","/fapi/v1/order",entry_params)
        executed_raw=entry_order.get("executedQty")
        avg_raw=entry_order.get("avgPrice")
        print(f"[AUTO-FUTURES] REAL ENTRY RESPONSE symbol={symbol} side={side} orderId={entry_order.get('orderId')} status={entry_order.get('status')} executedQty={executed_raw} avgPrice={avg_raw}", flush=True)
        actual_qty=float(executed_raw or 0)
        actual_entry=float(avg_raw or entry_order.get("price") or 0)
        if actual_qty<=0 or actual_entry<=0:
            live=_futures_exchange_position_info(symbol)
            if live and float(live.get("quantity") or 0)>0 and float(live.get("entry_price") or 0)>0:
                actual_qty=float(live["quantity"])
                actual_entry=float(live["entry_price"])
                print(f"[AUTO-FUTURES] reconciled MARKET fill from positionRisk symbol={symbol} qty={actual_qty} entry={actual_entry}",flush=True)
            else:
                raise RuntimeError(f"أمر الدخول لم يُؤكد فعلياً: executedQty={executed_raw}, avgPrice={avg_raw}")

        # نضع الحماية فقط بعد التأكد من التنفيذ الفعلي.
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat()
        # سجّل المركز فور نجاح أمر الدخول حتى لا يعيد العامل فتح مركز ثانٍ إذا فشل أمر الحماية.
        _futures_bot_write({
            "enabled":1,"auto_enabled":1,"status":"open",
            "entry":actual_entry,"quantity":actual_qty,"balance_usdt":balance,
            "margin_usdt":margin,"notional_usdt":margin*leverage,"leverage":leverage,
            "tp1":actual_entry*(1+(5.0/leverage)/100) if side=="BUY" else actual_entry*(1-(5.0/leverage)/100),
            "tp2":actual_entry*(1+(7.5/leverage)/100) if side=="BUY" else actual_entry*(1-(7.5/leverage)/100),
            "tp3":actual_entry*(1+(10.0/leverage)/100) if side=="BUY" else actual_entry*(1-(10.0/leverage)/100),
            "sl":actual_entry*(1-(5.0/leverage)/100) if side=="BUY" else actual_entry*(1+(5.0/leverage)/100),
            "opened_at":now,"last_price":actual_entry,"last_checked_at":now,
            "peak_profit_pct":0,"protected_profit_pct":0,"protection_price":None,
            "outcome":None,"realized_pct":None
        })
        tick=rules["tick_size"]
        if side=="BUY": sl_price=_round_step(actual_entry*(1-(5.0/leverage)/100),tick)
        else: sl_price=_round_step(actual_entry*(1+(5.0/leverage)/100),tick)
        close_side="SELL" if side=="BUY" else "BUY"
        protection_base={"symbol":symbol,"side":close_side,"closePosition":"true","workingType":"MARK_PRICE"}
        if position_side: protection_base["positionSide"]=position_side
        sl_order=_binance_futures_signed_request("POST","/fapi/v1/order",dict(protection_base,type="STOP_MARKET",stopPrice=f"{sl_price:.16f}".rstrip("0").rstrip(".")))
        print("[AUTO-FUTURES] REAL INITIAL SL OK symbol={} orderId={} stopPrice={}".format(symbol,sl_order.get("orderId"),sl_price),flush=True)
        live=_futures_open_protection_orders(symbol)
        if not any(str(x.get("orderId"))==str(sl_order.get("orderId")) for x in live):
            raise RuntimeError("Binance لم يؤكد وجود وقف الحماية بعد الدخول")
        return {"ok":True,"real_orders":True,"message":"تم تنفيذ الصفقة ووضع SL -5% وتأمين ربح متحرك بعد +10%","bot":_futures_bot_read(),"orders":{"entry":entry_order,"stop_loss":sl_order}}
    except Exception as exc:
        current=_futures_bot_read()
        safe_detail=f"{type(exc).__name__}: {str(exc)[:500]}"
        # If entry succeeded but protection failed, never leave an unprotected position.
        if current.get("status")=="open":
            _futures_halt("فشل الحماية بعد الدخول: {}".format(safe_detail))
            symbol2=str(current.get("symbol") or "").upper()
            side2=str(current.get("side") or "BUY").upper()
            try:
                q2=_futures_exchange_position(symbol2)
                if q2 and q2>0:
                    rules2=_futures_symbol_rules(symbol2)
                    qty2=_floor_step(q2,rules2.get("step_size",0))
                    dual2=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
                    ps2="LONG" if bool(dual2.get("dualSidePosition")) and side2=="BUY" else "SHORT" if bool(dual2.get("dualSidePosition")) else None
                    if qty2>0:
                        _futures_market_close(symbol2,side2,qty2,ps2)
                remain2=_futures_exchange_position(symbol2)
                now2=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                if remain2 is not None and remain2<=0:
                    _futures_bot_write({"status":"closed","enabled":0,"auto_enabled":0,"halted":1,"closed_at":now2,
                                        "outcome":"protection_failure_emergency_close","realized_pct":None,
                                        "last_error":safe_detail,"halt_reason":"فشل الحماية بعد الدخول","last_checked_at":now2})
                else:
                    _futures_bot_write({"halted":1,"last_error":safe_detail,"halt_reason":"فشل الحماية بعد الدخول","last_checked_at":now2})
            except Exception as close_exc:
                _futures_halt("فشل الحماية والإغلاق الطارئ: {}".format(str(close_exc)[:300]))
        elif current.get("status")=="ready":
            _futures_bot_write({
                "status":"idle","enabled":0,"auto_enabled":0,"halted":0,
                "last_error":safe_detail,
                "last_checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            })
        return {"ok":False,"real_orders":True,"message":"فشل التنفيذ الحقيقي","detail":safe_detail,"bot":_futures_bot_read()}

@app.post("/api/futures/bot/close")
def futures_bot_close(request:Request):
    """Close only through a real Binance MARKET order; never mark a position closed locally."""
    u=current_user(request)
    if not u:
        return JSONResponse({"ok":False,"message":"يجب تسجيل الدخول قبل إغلاق الصفقة"},status_code=401)
    state=_futures_bot_read()
    if state.get("status")!="open" or not state.get("symbol"):
        return {"ok":True,"real_orders":True,"message":"لا توجد صفقة حقيقية مفتوحة","bot":state}
    symbol=str(state.get("symbol") or "").upper()
    side=str(state.get("side") or "BUY").upper()
    try:
        exchange_qty=_futures_exchange_position(symbol)
        if exchange_qty is None:
            raise RuntimeError("تعذر التحقق من مركز Binance الحقيقي")
        if exchange_qty<=0:
            return {"ok":True,"real_orders":True,"message":"المركز مغلق فعلياً على Binance","bot":_futures_bot_tick()}
        rules=_futures_symbol_rules(symbol)
        qty=_floor_step(exchange_qty,rules.get("step_size",0))
        if qty<=0:
            raise RuntimeError("الكمية الحقيقية على Binance أقل من الحد القابل للإغلاق")
        dual=_binance_futures_signed_request("GET","/fapi/v1/positionSide/dual")
        position_side="LONG" if bool(dual.get("dualSidePosition")) and side=="BUY" else "SHORT" if bool(dual.get("dualSidePosition")) else None
        params={
            "symbol":symbol,
            "side":"SELL" if side=="BUY" else "BUY",
            "type":"MARKET",
            "quantity":f"{qty:.16f}".rstrip("0").rstrip("."),
            "reduceOnly":"false" if position_side else "true"
        }
        if position_side:
            params["positionSide"]=position_side
        order=_binance_futures_signed_request("POST","/fapi/v1/order",params)
        remaining=_futures_exchange_position(symbol)
        if remaining is None or remaining>0:
            return {"ok":False,"real_orders":True,"message":"تم إرسال أمر الإغلاق لكن Binance لم يؤكد إغلاق المركز بالكامل","order":order,"bot":_futures_bot_read()}
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        px=_futures_bot_price(symbol) or float(state.get("last_price") or state.get("entry") or 0)
        entry=float(state.get("entry") or 0)
        realized=((px-entry)/entry*100) if side=="BUY" and entry>0 else ((entry-px)/entry*100) if entry>0 else None
        _futures_bot_write({
            "status":"closed","enabled":0,"auto_enabled":0,"closed_at":now,
            "outcome":"manual_exchange_close","realized_pct":realized,
            "last_price":px,"last_checked_at":now
        })
        return {"ok":True,"real_orders":True,"message":"تم إغلاق الصفقة فعلياً على Binance","order":order,"bot":_futures_bot_read()}
    except Exception as exc:
        return {"ok":False,"real_orders":True,"message":"فشل إغلاق الصفقة الحقيقية","detail":f"{type(exc).__name__}: {str(exc)[:300]}","bot":_futures_bot_read()}

@app.get("/api/strategy/scan/{kind}")
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
    with ThreadPoolExecutor(max_workers=12) as pool:
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
        minutes={"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440}.get(tf,15)
        bucket=int(time.time()//(minutes*60))*(minutes*60)
        candle_start=str(row.get("candle_start") or datetime.fromtimestamp(bucket,tz=timezone.utc).isoformat())
        market=str(row.get("market") or market or "spot")
        key=f"{market}:{row.get('symbol')}:{tf}:{candle_start}"
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
            params=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":180})
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
            if not setups:return None
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
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures=[pool.submit(scan_one,x) for x in candidates]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x: found.append(x)
            except Exception: pass
    return sorted(found,key=lambda x:(float(x["score"]),abs(float(x["change_pct"])),float(x["quote_volume"])),reverse=True)[:30]

def _scan_yahoo_market(market,timeframe):
    """مسح خفيف ومستقل لأسواق Yahoo؛ العقود والفوركس تسمح بالشراء والبيع."""
    if market not in {"contracts","us","saudi","forex"} or timeframe not in TIMEFRAMES:
        return []
    interval_map={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    # Yahoo لا يوفر 4h مباشرة؛ نستخدم 1h كبيانات خام لهذا الفريم.
    range_map={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}
    sides=MARKET_RULES.get(market,{}).get("sides",["BUY"])
    symbols=_market_universe(market)

    def scan_one(symbol):
        try:
            candles=_yahoo_chart(symbol,interval_map[timeframe],range_map[timeframe],timeframe)
            return _strategy_rows(symbol,timeframe,sides,candles)
        except Exception:
            return []

    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(scan_one,s) for s in symbols]
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                pass

    # لا نخفي الإشارات الصحيحة لمجرد أن الحركة أقل من 1%؛
    # _strategy_rows أصلاً يفرض +0.30% للشراء و-0.30% للبيع.
    return sorted(
        rows,
        key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),
        reverse=True
    )[:20]

def _binance_futures_json(url,timeout=5):
    """Futures data helper with official Binance API failover.
    Each request tries multiple documented API hosts before failing, so one
    unhealthy edge does not stop the scanner or leave trades empty.
    """
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json"}
    if "fapi.binance.com" not in url:
        return _json_get(url,timeout=timeout,headers=headers)
    path=url.replace("https://fapi.binance.com","",1)
    errors=[]
    for base in (
        "https://fapi.binance.com",
        "https://fapi1.binance.com",
        "https://fapi2.binance.com",
        "https://fapi3.binance.com",
        "https://fapi4.binance.com",
    ):
        try:
            return _json_get(base+path,timeout=timeout,headers=headers)
        except Exception as exc:
            errors.append(str(exc)[:100])
    raise RuntimeError("Binance Futures sources unavailable: "+" | ".join(errors[-3:]))


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


def _futures_execution_lease(owner,ttl=45):
    import time
    now=time.time(); c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT owner,expires_at FROM futures_execution_lease WHERE id=1").fetchone()
        if row and float(row["expires_at"] or 0)>now and str(row["owner"] or "")!=owner:
            c.execute("ROLLBACK"); return False
        c.execute("INSERT INTO futures_execution_lease(id,owner,expires_at,updated_at) VALUES(1,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,updated_at=CURRENT_TIMESTAMP",(owner,now+ttl))
        c.commit(); return True
    except Exception:
        try:c.execute("ROLLBACK")
        except Exception:pass
        return False
    finally:c.close()

def _futures_execution_lease_release(owner):
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE"); c.execute("UPDATE futures_execution_lease SET owner=NULL,expires_at=0,updated_at=CURRENT_TIMESTAMP WHERE id=1 AND owner=?",(owner,)); c.commit()
    except Exception:
        try:c.execute("ROLLBACK")
        except Exception:pass
    finally:c.close()

def _scan_binance_futures(timeframe):
    """Continuous sequential Futures scanner: walks the full eligible universe in batches."""
    tickers=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=6)
    candidates=[]
    for t in tickers:
        s=t.get("symbol","")
        if s.endswith("USDT"):
            try:
                q=float(t.get("quoteVolume",0))
                if q>0: candidates.append((q,s))
            except Exception:
                pass

    # Single service scans the whole universe continuously, batch by batch.
    candidates=_futures_shard_candidates(candidates)
    candidates=sorted(candidates,key=lambda x:x[0],reverse=True)

    rows=[]
    batch_size=max(12,int(os.getenv("FUTURES_SCAN_BATCH_SIZE","40") or 40))
    workers=max(4,min(16,int(os.getenv("FUTURES_SCAN_WORKERS","12") or 12)))

    def scan_one(item):
        _,symbol=item
        try:
            p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":260})
            k=_binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+p,timeout=6)
            # Keep close, low and high so SELL protection uses a real high.
            candles=[(float(x[4]),float(x[3]),float(x[2])) for x in k]
            return _strategy_rows(symbol,timeframe,["BUY","SELL"],candles)
        except Exception:
            return []

    # Scan sequential batches: the bot keeps moving through the universe
    # instead of launching the entire market at once.
    for offset in range(0,len(candidates),batch_size):
        batch=candidates[offset:offset+batch_size]
        with ThreadPoolExecutor(max_workers=min(workers,len(batch) or 1)) as pool:
            futures=[pool.submit(scan_one,item) for item in batch]
            for future in as_completed(futures):
                try:
                    rows.extend(future.result())
                except Exception:
                    pass

        # Keep the best current matches; enough to feed execution without
        # waiting for another full-market pass.
        if rows:
            rows=sorted(rows,key=lambda x:(abs(float(x.get("change_pct",0))),float(x.get("ai_pct",0))),reverse=True)[:40]

    rows=[x for x in rows if abs(float(x.get("change_pct",0))) >= 0.30]
    return sorted(rows,key=lambda x:(abs(x["change_pct"]),x["ai_pct"]),reverse=True)[:20]

def _strategy_rows(symbol, timeframe, sides, candles):
    """Unified live strategy: EMA200 + RSI 50 + 1% move on the selected timeframe."""
    if timeframe not in TIMEFRAMES or len(candles)<220:
        return []
    closes=[float(x[0]) for x in candles]
    lows=[float(x[1]) for x in candles]
    highs=[float(x[2]) if len(x)>=3 else float(x[0]) for x in candles]
    price=closes[-1]
    prev_price=closes[-2]
    ema200=_ema(closes,200)
    rsi=_rsi(closes)
    if ema200 is None or rsi is None:
        return []

    # التغير محسوب من آخر شمعة مغلقة إلى الشمعة المغلقة السابقة
    # على نفس الفريم المختار، بدون خلط الفريمات.
    change=(price-prev_price)/prev_price*100 if prev_price else 0.0

    if rsi>50.0 and price>ema200 and change>=1.0 and "BUY" in sides:
        sl=min(lows[-20:]); risk=price-sl
        if risk<=0 or risk/price>0.08:
            return []
        score=min(99.0,70.0+min(15.0,(rsi-50.0)*1.5)+min(14.0,max(0.0,change-1.0)*2.0))
        return [{"symbol":symbol,"side":"BUY","timeframe":timeframe,"change_pct":round(change,3),
                 "profit_pct":round(risk/price*100,3),"loss_pct":round(risk/price*100,3),
                 "ai_pct":round(score,1),"tag":"RSI > 50 + فوق EMA200 + تغير +1%",
                 "strategy_label":"شراء: RSI فوق 50 + السعر فوق EMA200 + تغير +1% على نفس الفريم",
                 "strategy_mode":"RSI50_EMA200_LEVEL_1PCT","entry":price,
                 "tp1":price+risk,"tp2":price+risk*2,"tp3":price+risk*3,"sl":sl,"status":"open",
                 "ema200":ema200,"rsi":rsi,"candle_start":_candle_start(timeframe).isoformat()}]

    if rsi<50.0 and price<ema200 and change<=-1.0 and "SELL" in sides:
        sl=max(highs[-20:]); risk=sl-price
        if risk<=0 or risk/price>0.08:
            return []
        score=min(99.0,70.0+min(15.0,(50.0-rsi)*1.5)+min(14.0,max(0.0,abs(change)-1.0)*2.0))
        return [{"symbol":symbol,"side":"SELL","timeframe":timeframe,"change_pct":round(change,3),
                 "profit_pct":round(risk/price*100,3),"loss_pct":round(risk/price*100,3),
                 "ai_pct":round(score,1),"tag":"RSI < 50 + تحت EMA200 + تغير -1%",
                 "strategy_label":"بيع: RSI تحت 50 + السعر تحت EMA200 + تغير -1% على نفس الفريم",
                 "strategy_mode":"RSI50_EMA200_LEVEL_1PCT","entry":price,
                 "tp1":price-risk,"tp2":price-risk*2,"tp3":price-risk*3,"sl":sl,"status":"open",
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
    return (cached if cached is not None else []),True


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
    with ThreadPoolExecutor(max_workers=20) as pool:
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
    with ThreadPoolExecutor(max_workers=12) as pool:
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


def _market_universe(market):
    if market=="forex": return FOREX_SYMBOLS
    if market=="us": return US_SYMBOLS
    if market=="saudi": return SAUDI_SYMBOLS
    if market=="contracts": return US_CONTRACT_SYMBOLS
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
    return page(request,"فيوتشر سريع")

@app.get("/fast-futures", response_class=HTMLResponse)
def fast_futures_page(request:Request):
    return page(request,"إشارة فيوتشر سريعة")

def _spot_fast_payload(timeframe):
    rows,scanning=_cached_scan("spot",timeframe,lambda:_scan_spot_strategy(timeframe,20))
    trades=[dict(x,rank=i+1,medal="🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "") for i,x in enumerate(rows)]
    breadth=_breadth_binance("spot",timeframe)
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
        if market=="futures":
            # لا نفحص مئات العملات داخل طلب HTTP. نستخدم نفس محرك الاستراتيجية مع
            # cache بالخلفية حتى لا يتحول طلب الصفحة إلى 502 عند ضغط Binance.
            rows,scanning=_cached_scan("futures",timeframe,lambda:_scan_binance_futures(timeframe))
            if not rows and scanning:
                # أول فحص قد يكون ما زال يعمل في الخلفية؛ نعيد استجابة سليمة بدل 502.
                rows=[]
            try:
                _,futures_20x_count=_futures_20x_symbols()
            except Exception:
                futures_20x_count=None
        else:
            endpoint="https://api.binance.com/api/v3/klines"
            ticker_url="https://api.binance.com/api/v3/ticker/24hr"
            tickers=_binance_json(ticker_url,timeout=8,timeframe=timeframe,spot_fallback=True)
            candidates=[]
            for t in tickers if isinstance(tickers,list) else []:
                symbol=str(t.get("symbol",""))
                if not symbol.endswith("USDT") or symbol in BINANCE_SCANNER_EXCLUDED: continue
                try:
                    qv=float(t.get("quoteVolume") or 0)
                    if qv >= BINANCE_SCANNER_MIN_VOLUME: candidates.append((qv,symbol))
                except Exception: pass
            candidates=sorted(candidates,reverse=True)
            def scan(item):
                _,symbol=item
                try:
                    p=urllib.parse.urlencode({"symbol":symbol,"interval":timeframe,"limit":260})
                    u=endpoint+"?"+p
                    ks=_binance_json(u,timeout=6,timeframe=timeframe,spot_fallback=True)
                    if len(ks)<221:return []
                    ks=ks[:-1]
                    candles=[(float(k[4]),float(k[3]),float(k[2])) for k in ks]
                    return _strategy_rows(symbol,timeframe,["BUY"],candles)
                except Exception:return []
            rows=[]
            with ThreadPoolExecutor(max_workers=20) as pool:
                for fut in [pool.submit(scan,x) for x in candidates]:
                    try: rows.extend(fut.result())
                    except Exception: pass
            rows,scanning=_cached_scan(market,timeframe,lambda:_scan_yahoo_market(market,timeframe))
            if market in {"us","saudi"}: rows=[x for x in rows if str(x.get("side","")).upper()=="BUY"]
        if market=="futures":
            # فيوتشر: رافعة العرض 20x، هدف سعري 10%، وقف سعري 5%.
            # المستويات الثلاثة تقسم الهدف إلى 5% / 7.5% / 10%.
            for x in rows:
                entry=float(x.get("entry") or 0)
                if entry<=0:
                    continue
                x["leverage"]=20
                x["target_pct"]=10.0
                x["stop_pct"]=5.0
                x["profit_pct"]=10.0
                x["loss_pct"]=5.0
                if str(x.get("side","")).upper()=="SELL":
                    x["tp1"]=entry*0.95
                    x["tp2"]=entry*0.925
                    x["tp3"]=entry*0.90
                    x["sl"]=entry*1.05
                else:
                    x["tp1"]=entry*1.05
                    x["tp2"]=entry*1.075
                    x["tp3"]=entry*1.10
                    x["sl"]=entry*0.95
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
        return {"ok":True,"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"scanning":False,"scanned":len(rows),"futures_20x_count":futures_20x_count if market=="futures" else None,"trade":rows[0] if rows else None,"tracking":bool(rows and rows[0].get("tracking")),"tracking_status":"متابعة حتى الإغلاق" if rows and rows[0].get("tracking") else "","trades":[dict(x,rank=i+1,medal="👑" if i==0 else "") for i,x in enumerate(rows)]}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":"تعذر فحص السوق حالياً","detail":str(exc)[:160]},status_code=502)

@app.get("/fast-spot", response_class=HTMLResponse)
def fast_spot_page(request:Request):
    return page(request,"استراتيجية السبوت")

@app.get("/fast-futures", response_class=HTMLResponse)
def fast_futures_page(request:Request):
    return page(request,"إشارة فيوتشر سريعة")

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