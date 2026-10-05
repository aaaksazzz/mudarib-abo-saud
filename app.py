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
# Northflank redeploy trigger: Futures manual-entry fix is on main.
app=FastAPI(title="التداول الذكي PRO")

def _fnum(value, default=0.0):
    """Safely convert Binance numeric fields/responses to float."""
    if isinstance(value, dict):
        for key in ("value","price","data","availableBalance","stepSize","minQty","tickSize"):
            if key in value:
                return _fnum(value.get(key), default)
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

app.add_middleware(SessionMiddleware,secret_key=SECRET,max_age=60*60*24*14)


YAHOO_BASES=("https://query1.finance.yahoo.com","https://query2.finance.yahoo.com")
DATA_SOURCE_KEYS={k:os.getenv(k,"").strip() for k in ("TWELVE_DATA_API_KEY","ALPHA_VANTAGE_API_KEY","COINMARKETCAP_API_KEY")}

def _json_get(url,timeout=8,headers=None,source=None):
    req=urllib.request.Request(url,headers=headers or {"User-Agent":"mudarib-pro/1.0","Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            raw=r.read().decode("utf-8","replace")
            return json.loads(raw)
    except Exception as exc:
        raise RuntimeError(str(exc)[:240])

def _binance_futures_json(url,timeout=8):
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json"}
    if "fapi.binance.com" not in url:
        return _json_get(url,timeout,headers)
    path=url.replace("https://fapi.binance.com","",1)
    last=None
    for base in ("https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi4.binance.com"):
        try:return _json_get(base+path,timeout,headers)
        except Exception as exc:last=exc
    raise RuntimeError("Binance Futures sources unavailable: "+str(last)[:180])

def _signed_binance_request(base,method,path,params,key,secret):
    import time,hmac,hashlib,urllib.parse,urllib.error
    if not key or not secret: raise RuntimeError("مفاتيح Binance غير مهيأة")
    q=dict(params or {})
    q["timestamp"]=int(time.time()*1000); q.setdefault("recvWindow",5000)
    encoded=urllib.parse.urlencode(q)
    q["signature"]=hmac.new(secret.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    headers={"User-Agent":"mudarib-pro/1.0","Accept":"application/json","X-MBX-APIKEY":key}
    method=str(method or "GET").upper()
    try:
        if method=="GET":
            u=base+path+"?"+urllib.parse.urlencode(q)
            req=urllib.request.Request(u,headers=headers,method="GET")
        else:
            req=urllib.request.Request(base+path,data=urllib.parse.urlencode(q).encode(),headers={**headers,"Content-Type":"application/x-www-form-urlencoded"},method=method)
        with urllib.request.urlopen(req,timeout=12) as r:
            data=json.loads(r.read().decode("utf-8","replace"))
            if isinstance(data,dict) and data.get("code",0)<0: raise RuntimeError(str(data))
            return data
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8","replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        raise RuntimeError(str(exc)[:300])

def _trade_secrets():
    key=os.getenv("BINANCE_API_KEY","").strip(); secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret: raise RuntimeError("مفاتيح Binance غير مهيأة في Northflank")
    return key,secret

def _trade_user_required(request):
    return current_user(request)

def admin_only(request):
    return admin_user(request)

def _floor_step(value,step):
    from decimal import Decimal,ROUND_FLOOR
    if step<=0:return float(value)
    return float((Decimal(str(value))/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(step)))

def _decimal_step(value,step):
    return _floor_step(value,step)

def _round_tick(value,tick):
    from decimal import Decimal,ROUND_HALF_UP
    if tick<=0:return float(value)
    return float((Decimal(str(value))/Decimal(str(tick))).quantize(Decimal("1"),rounding=ROUND_HALF_UP)*Decimal(str(tick)))

def _fmt_binance(value,step=0):
    s=("%0.16f"%float(value)).rstrip("0").rstrip(".")
    return s or "0"

def _futures_position_mode():
    try:
        key,secret=_trade_secrets()
        d=_signed_binance_request("https://fapi.binance.com","GET","/fapi/v1/positionSide/dual",{},key,secret)
        return bool(d.get("dualSidePosition")) if isinstance(d,dict) else False
    except Exception:
        return False

def _binance_futures_positions():
    key,secret=_trade_secrets()
    d=_signed_binance_request("https://fapi.binance.com","GET","/fapi/v2/positionRisk",{},key,secret)
    return d.get("data",[]) if isinstance(d,dict) and isinstance(d.get("data"),list) else (d if isinstance(d,list) else [])

def _spot_symbol_rules(symbol,key=None,secret=None):
    symbol=str(symbol).upper()
    d=_binance_json("https://api.binance.com/api/v3/exchangeInfo",timeout=10)
    for info in d.get("symbols",[]):
        if str(info.get("symbol","")).upper()!=symbol:continue
        lot={}; pf={}; notional={}
        for f in info.get("filters",[]):
            ft=str(f.get("filterType","")).upper()
            if ft=="LOT_SIZE":lot=f
            elif ft=="PRICE_FILTER":pf=f
            elif ft in ("MIN_NOTIONAL","NOTIONAL"):notional=f
        return info,lot,pf,notional
    raise RuntimeError(f"رمز Spot غير موجود على Binance: {symbol}")

def _rsi(closes,period=14):
    if len(closes)<=period:return 50.0
    gains=[];losses=[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1];g=max(d,0);l=max(-d,0);gains.append(g);losses.append(l)
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for g,l in zip(gains[period:],losses[period:]):
        ag=(ag*(period-1)+g)/period; al=(al*(period-1)+l)/period
    if al<=0:return 100.0
    return 100-(100/(1+ag/al))

def _scan_binance_generic(market,timeframe,limit_symbols=20):
    is_spot=market=="spot"; base="https://api.binance.com" if is_spot else "https://fapi.binance.com"
    kpath="/api/v3/klines" if is_spot else "/fapi/v1/klines"
    tpath="/api/v3/ticker/24hr" if is_spot else "/fapi/v1/ticker/24hr"
    info=_binance_json(base+("/api/v3/exchangeInfo" if is_spot else "/fapi/v1/exchangeInfo"),timeout=10)
    allowed=set()
    for s in info.get("symbols",[]):
        if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT": allowed.add(s.get("symbol"))
    tickers=_binance_json(base+tpath,timeout=10)
    ranked=[]
    for t in tickers if isinstance(tickers,list) else []:
        sym=t.get("symbol")
        if sym not in allowed or sym in BINANCE_SCANNER_EXCLUDED:continue
        try:
            vol=float(t.get("quoteVolume") or 0); ch24=float(t.get("priceChangePercent") or 0)
            if vol>=BINANCE_SCANNER_MIN_VOLUME:ranked.append((sym,vol,ch24))
        except Exception:pass
    ranked.sort(key=lambda x:x[1],reverse=True)
    out=[]
    for sym,vol,ch24 in ranked[:limit_symbols]:
        try:
            q=urllib.parse.urlencode({"symbol":sym,"interval":timeframe,"limit":210})
            ks=_binance_json(base+kpath+"?"+q,timeout=8) if is_spot else _binance_futures_json(base+kpath+"?"+q,timeout=8)
            if not isinstance(ks,list) or len(ks)<60:continue
            ks=ks[:-1]
            closes=[float(x[4]) for x in ks]; opens=[float(x[1]) for x in ks]; highs=[float(x[2]) for x in ks]; lows=[float(x[3]) for x in ks]; volumes=[float(x[7]) for x in ks]
            price=closes[-1]; prev=closes[-2]; change=(price/prev-1)*100 if prev else 0
            candle_change=(closes[-1]/opens[-1]-1)*100 if opens[-1] else 0
            if abs(candle_change)>4.0 or abs(candle_change)<0.5:continue
            e20=sum(closes[-20:])/20; e200=(sum(closes[-200:])/200 if len(closes)>=200 else sum(closes)/len(closes))
            rsi=_rsi(closes)
            avgvol=sum(volumes[-21:-1])/20 if len(volumes)>=21 else 0
            vr=volumes[-1]/avgvol if avgvol else 0
            side=None; score=50; reasons=[]
            if is_spot:
                if price<e20 and rsi<50: side="BUY";score+=25;reasons.append("السعر تحت EMA20");reasons.append("RSI تحت 50")
                if price<e200:score+=10;reasons.append("السعر تحت EMA200")
            else:
                if price<e20 and rsi<50:side="BUY";score+=22;reasons+=["زخم هابط/شراء ارتدادي","RSI تحت 50"]
                elif price>e20 and rsi>50:side="SELL";score+=22;reasons+=["زخم صاعد/بيع معاكس","RSI فوق 50"]
                if price<e200 and side=="BUY":score+=10
                if price>e200 and side=="SELL":score+=10
            if vr>=1.5:score+=10;reasons.append("حجم أعلى من المتوسط")
            if abs(change)<=3:score+=5
            if abs(candle_change)>3:score-=10
            if side and score>=60:
                risk=price*0.02
                if side=="BUY": sl=price-risk;tp1=price+risk;tp2=price+risk*2;tp3=price+risk*3
                else: sl=price+risk;tp1=price-risk;tp2=price-risk*2;tp3=price-risk*3
                out.append({"symbol":sym,"side":side,"timeframe":timeframe,"change_pct":change,"change_24h":ch24,"price":price,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"ai_pct":min(95,score),"score":min(95,score),"volume":vol,"volume_ratio":round(vr,2),"rsi":round(rsi,2),"reasons":reasons,"patterns":reasons,"candle_start":ks[-1][0],"expires_at":ks[-1][6],"target_pct":10,"stop_pct":5,"leverage":20 if not is_spot else 1})
        except Exception:
            continue
    out.sort(key=lambda x:(float(x.get("ai_pct") or 0),abs(float(x.get("change_pct") or 0))),reverse=True)
    return out

def _lab_active_config():
    try:
        p=DATA_DIR/"strategy_lab"/"active.json"
        if not p.exists(): return None
        x=json.loads(p.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) and x.get("active") else None
    except Exception:
        return None

def _scan_binance_lab_strategy(market, limit_symbols=20):
    cfg=_lab_active_config()
    if not cfg: return []
    p=cfg.get("parameters") or {}
    is_spot=market=="spot"
    base="https://api.binance.com" if is_spot else "https://fapi.binance.com"
    kpath="/api/v3/klines" if is_spot else "/fapi/v1/klines"
    tpath="/api/v3/ticker/24hr" if is_spot else "/fapi/v1/ticker/24hr"
    info=_binance_json(base+("/api/v3/exchangeInfo" if is_spot else "/fapi/v1/exchangeInfo"),timeout=10)
    allowed={x.get("symbol") for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"}
    tickers=_binance_json(base+tpath,timeout=10)
    ranked=[]
    for t in tickers if isinstance(tickers,list) else []:
        sym=t.get("symbol")
        if sym not in allowed or sym in BINANCE_SCANNER_EXCLUDED: continue
        try:
            vol=float(t.get("quoteVolume") or 0)
            if vol>=BINANCE_SCANNER_MIN_VOLUME: ranked.append((sym,vol,float(t.get("priceChangePercent") or 0)))
        except Exception: pass
    ranked.sort(key=lambda x:x[1],reverse=True)
    out=[]
    for sym,vol,ch24 in ranked[:limit_symbols]:
        try:
            q5=urllib.parse.urlencode({"symbol":sym,"interval":"5m","limit":210})
            q1=urllib.parse.urlencode({"symbol":sym,"interval":"1m","limit":210})
            k5=_binance_json(base+kpath+"?"+q5,timeout=8) if is_spot else _binance_futures_json(base+kpath+"?"+q5,timeout=8)
            k1=_binance_json(base+kpath+"?"+q1,timeout=8) if is_spot else _binance_futures_json(base+kpath+"?"+q1,timeout=8)
            if not isinstance(k5,list) or not isinstance(k1,list) or len(k5)<10 or len(k1)<10: continue
            c5=k5[-2]; c1=k1[-2]
            move5=(float(c5[4])-float(c5[1]))/float(c5[1]) if float(c5[1]) else 0
            move1=(float(c1[4])-float(c1[1]))/float(c1[1]) if float(c1[1]) else 0
            side="BUY" if p["strong_min"]<=move5<=p["strong_max"] and move1>=p["confirm_min"] else None
            if not is_spot and -p["strong_max"]<=move5<=-p["strong_min"] and move1<=-p["confirm_min"]: side="SELL"
            if not side: continue
            price=float(c1[4]); tp_move=p["tp_margin"]/p["leverage"]; sl_move=p["sl_margin"]/p["leverage"]
            risk=price*sl_move
            tp1=price*(1+tp_move) if side=="BUY" else price*(1-tp_move)
            sl=price*(1-sl_move) if side=="BUY" else price*(1+sl_move)
            out.append({"symbol":sym,"side":side,"timeframe":"5m+1m","change_pct":round(move5*100,3),"change_24h":ch24,"price":price,"entry":price,"tp1":tp1,"tp2":tp1,"tp3":tp1,"sl":sl,"ai_pct":90,"score":90,"volume":vol,"volume_ratio":0,"reasons":["استراتيجية مستخرجة تاريخياً","5د قوة","1د تأكيد"],"patterns":["STRATEGY_LAB"],"candle_start":c1[0],"expires_at":c1[6],"target_pct":p["tp_margin"]*100,"stop_pct":p["sl_margin"]*100,"leverage":p["leverage"] if not is_spot else 1})
        except Exception:
            continue
    return sorted(out,key=lambda x:float(x.get("volume") or 0),reverse=True)

def _scan_spot_strategy(timeframe,limit_symbols=20):
    if timeframe=="15m" and _lab_active_config():
        return _scan_binance_lab_strategy("spot",limit_symbols)
    return _scan_binance_generic("spot",timeframe,limit_symbols)

def _scan_binance_futures(timeframe):
    if timeframe=="15m" and _lab_active_config():
        return _scan_binance_lab_strategy("futures",20)
    return _scan_binance_generic("futures",timeframe,20)

_YAHOO_SYMBOLS={
    "us":["NVDA","AMD","TSLA","AAPL","MSFT","AMZN","META","GOOGL","AVGO","NFLX","PLTR","MSTR","SMCI","MU","QCOM","ARM","COIN","HOOD","SHOP","CRWD","ORCL"],
    "saudi":["2222.SR","1120.SR","2010.SR","7010.SR","7020.SR","1211.SR","1180.SR","1150.SR","1060.SR","4030.SR","2380.SR","4200.SR","2280.SR","2080.SR","2050.SR"],
    "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","USDCAD=X","AUDUSD=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F"]
}

def _scan_yahoo_market(market,timeframe):
    symbols=_YAHOO_SYMBOLS.get(market,[])
    interval=timeframe if timeframe in {"15m","30m","1h","4h","1d","1w","1M"} else "15m"
    imap={"1w":"1wk","1M":"1mo"}
    ranges={"15m":"60d","30m":"60d","1h":"2y","4h":"2y","1d":"5y","1w":"10y","1M":"max"}
    out=[]
    for sym in symbols:
        try:
            u=f"{YAHOO_BASES[0]}/v8/finance/chart/{urllib.parse.quote(sym,safe='')}?"+urllib.parse.urlencode({"interval":imap.get(interval,interval),"range":ranges[interval]})
            d=_json_get(u,timeout=8); rr=(d.get("chart",{}).get("result") or [None])[0]
            q=((rr or {}).get("indicators",{}).get("quote") or [{}])[0]
            closes=[float(x) for x in (q.get("close") or []) if x is not None]
            opens=[float(x) for x in (q.get("open") or []) if x is not None]
            if len(closes)<30:continue
            price=closes[-1];prev=closes[-2];change=(price/prev-1)*100 if prev else 0
            e20=sum(closes[-20:])/20;e200=sum(closes[-200:])/200 if len(closes)>=200 else sum(closes)/len(closes);rsi=_rsi(closes)
            side="BUY" if price>e20 and rsi>50 else "SELL" if price<e20 and rsi<50 else None
            if not side:continue
            score=65+(10 if (side=="BUY" and price>e200) or (side=="SELL" and price<e200) else 0)
            risk=price*0.02
            sl=price-risk if side=="BUY" else price+risk
            out.append({"symbol":sym,"side":side,"timeframe":timeframe,"change_pct":change,"change_24h":change,"price":price,"entry":price,"tp1":price+(risk if side=="BUY" else -risk),"tp2":price+(2*risk if side=="BUY" else -2*risk),"tp3":price+(3*risk if side=="BUY" else -3*risk),"sl":sl,"ai_pct":score,"score":score,"volume":0,"volume_ratio":0,"rsi":round(rsi,2),"reasons":["EMA20","RSI","EMA200"]})
        except Exception:continue
    return sorted(out,key=lambda x:(x["ai_pct"],abs(x["change_pct"])),reverse=True)[:20]

def _cached_scan(market,timeframe,fn):
    try:
        rows=fn()
        return rows,False
    except Exception:
        return [],True

def _spot_real_entry(signal):
    signal=signal if isinstance(signal,dict) else {}
    symbol=str(signal.get("symbol") or "").upper()
    if not symbol.endswith("USDT"):raise RuntimeError("رمز Spot غير صالح")
    if str(signal.get("side") or "BUY").upper()!="BUY":raise RuntimeError("السبوت شراء فقط")
    if str(signal.get("timeframe") or "15m")!="15m":raise RuntimeError("الدخول الحقيقي للسبوت مسموح فقط على 15m")
    key,secret=_trade_secrets()
    bal=_signed_binance_request("https://api.binance.com","GET","/api/v3/account",{},key,secret)
    usdt=next((float(b.get("free") or 0) for b in bal.get("balances",[]) if b.get("asset")=="USDT"),0.0)
    if usdt<=0:raise RuntimeError(f"رصيد USDT المتاح غير كافٍ: {usdt:.8f}")
    info,lot,pf,notional=_spot_symbol_rules(symbol,key,secret)
    price=float((_binance_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}") or {}).get("price") or 0)
    if price<=0:raise RuntimeError("تعذر الحصول على سعر Binance الحالي")
    step=float(lot.get("stepSize") or 0);minq=float(lot.get("minQty") or 0)
    qty=_floor_step((usdt*0.985)/price,step)
    if qty<=0 or qty<minq:raise RuntimeError("الكمية أقل من الحد الأدنى لرمز Spot")
    order=_signed_binance_request("https://api.binance.com","POST","/api/v3/order",{"symbol":symbol,"side":"BUY","type":"MARKET","quantity":_fmt_binance(qty,step),"newOrderRespType":"RESULT"},key,secret)
    avg=float(order.get("cummulativeQuoteQty") or 0)/float(order.get("executedQty") or qty)
    if avg<=0:avg=price
    risk=avg*0.02
    return {"symbol":symbol,"side":"BUY","timeframe":"15m","entry":avg,"qty":float(order.get("executedQty") or qty),"tp_price":avg+risk,"sl_price":avg-risk,"order_id":order.get("orderId")}


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


# مراقب صفقات Binance الحقيقية: يبدأ Trailing عند +1% ثم يحمي 1% تحت القمة.
_TRADE_WATCHER_STATE = {"spot": {}, "futures": {}}

def _watcher_spot_assets(key, secret):
    acct=_signed_binance_request("https://api.binance.com","GET","/api/v3/account",{},key,secret)
    assets=[]
    for b in acct.get("balances",[]):
        asset=str(b.get("asset") or "").upper()
        free=float(b.get("free") or 0)
        qty=free+float(b.get("locked") or 0)
        if asset in {"USDT","USDC","FDUSD","BUSD","TUSD","DAI","EUR","TRY","BNB"} or qty<=0:
            continue
        symbol=asset+"USDT"
        try:
            info,lot,price_filter,notional=_spot_symbol_rules(symbol,key,secret)
        except Exception:
            continue
        qty=_decimal_step(free,float(lot.get("stepSize") or 0))
        if qty>0: assets.append((symbol,qty))
    return assets

def _watcher_spot_entry(symbol,key,secret):
    try:
        trades=_signed_binance_request("https://api.binance.com","GET","/api/v3/myTrades",
                                       {"symbol":symbol,"limit":100},key,secret)
        buys=[x for x in trades if x.get("isBuyer")]
        q=sum(float(x.get("qty") or 0) for x in buys)
        quote=sum(float(x.get("quoteQty") or 0) for x in buys)
        return quote/q if q>0 else 0.0
    except Exception:
        return 0.0

def _spot_trailing_watcher():
    import os,time
    key=os.getenv("BINANCE_API_KEY","").strip(); secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret: return
    while True:
        try:
            for symbol,qty in _watcher_spot_assets(key,secret):
                price=float((_binance_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",timeout=5) or {}).get("price") or 0)
                if price<=0: continue
                st=_TRADE_WATCHER_STATE["spot"].setdefault(symbol,{"entry":0.0,"peak":price,"armed":False,"last_protected_pct":0})
                if st["entry"]<=0: st["entry"]=_watcher_spot_entry(symbol,key,secret) or price
                entry=float(st["entry"] or price)
                st["peak"]=max(float(st["peak"] or price),price)

                # من +1% يبدأ التأمين على Binance نفسه، ثم نحدّث الحماية
                # كل 1% إضافية من أعلى مستوى وصل له السعر.
                gain_pct=((price-entry)/entry*100) if entry else 0.0
                if gain_pct>=1.0:
                    st["armed"]=True
                    milestone=int(gain_pct)
                    if milestone>int(st.get("last_protected_pct") or 0):
                        _,lot,price_filter,notional=_spot_symbol_rules(symbol,key,secret)
                        tick=float(price_filter.get("tickSize") or 0)
                        step=float(lot.get("stepSize") or 0)
                        asset=symbol[:-4]
                        acct=_signed_binance_request("https://api.binance.com","GET","/api/v3/account",{},key,secret)
                        free_asset=next((float(b.get("free") or 0) for b in acct.get("balances",[]) if b.get("asset")==asset),0.0)
                        protected_qty=_decimal_step(free_asset*0.998,step)
                        if protected_qty>0:
                            # احذف أوامر الحماية القديمة ثم ضع حماية جديدة حقيقية على Binance.
                            try:
                                _signed_binance_request("https://api.binance.com","DELETE","/api/v3/openOrders",
                                    {"symbol":symbol},key,secret)
                            except Exception as exc:
                                print(f"[TRADE-WATCHER] Spot {symbol} cancel old protection failed: {str(exc)[:160]}",flush=True)

                            stop_price=_decimal_step(st["peak"]*0.99,tick)
                            take_price=_decimal_step(st["peak"]*1.01,tick)
                            if stop_price<entry: stop_price=_decimal_step(entry,tick)
                            if take_price<=stop_price: take_price=_decimal_step(price*1.01,tick)
                            try:
                                _signed_binance_request("https://api.binance.com","POST","/api/v3/orderList/oco",{
                                    "symbol":symbol,"side":"SELL",
                                    "quantity":_fmt_binance(protected_qty,step),
                                    "aboveType":"LIMIT_MAKER","abovePrice":_fmt_binance(take_price,tick),
                                    "belowType":"STOP_LOSS_LIMIT","belowPrice":_fmt_binance(stop_price,tick),
                                    "belowStopPrice":_fmt_binance(stop_price,tick),
                                    "belowTimeInForce":"GTC"
                                },key,secret)
                                st["last_protected_pct"]=milestone
                                print(f"[TRADE-WATCHER] Spot {symbol} Binance protection updated +{milestone}% TP={take_price} SL={stop_price}",flush=True)
                            except Exception as exc:
                                print(f"[TRADE-WATCHER] Spot {symbol} Binance protection +{milestone}% failed: {str(exc)[:180]}",flush=True)

                # Backup محلي فقط إذا لم تنفذ حماية Binance.
                if st["armed"] and price<=st["peak"]*0.99:
                    _,lot,_,_=_spot_symbol_rules(symbol,key,secret)
                    sell_qty=_decimal_step(qty,float(lot.get("stepSize") or 0))
                    if sell_qty>0:
                        _signed_binance_request("https://api.binance.com","POST","/api/v3/order",
                            {"symbol":symbol,"side":"SELL","type":"MARKET","quantity":_fmt_binance(sell_qty,float(lot.get("stepSize") or 0)),"newOrderRespType":"RESULT"},key,secret)
                        print(f"[TRADE-WATCHER] Spot closed {symbol}",flush=True)
                        _TRADE_WATCHER_STATE["spot"].pop(symbol,None)
        except Exception as exc:
            print(f"[TRADE-WATCHER] Spot scan failed: {exc}",flush=True)
        time.sleep(5)

def _futures_trailing_watcher():
    import os,time
    key=os.getenv("BINANCE_API_KEY","").strip(); secret=os.getenv("BINANCE_API_SECRET","").strip()
    if not key or not secret: return
    while True:
        try:
            positions=_binance_futures_positions()
            live=set()
            for p in positions:
                symbol=str(p.get("symbol") or "").upper(); amt=float(p.get("positionAmt") or 0); entry=float(p.get("entryPrice") or 0)
                if not symbol or amt==0 or entry<=0: continue
                live.add(symbol)
                price=float((_binance_futures_json(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}") or {}).get("price") or 0)
                if price<=0: continue
                st=_TRADE_WATCHER_STATE["futures"].setdefault(symbol,{"entry":entry,"peak":price,"trough":price,"armed":False})
                side="BUY" if amt>0 else "SELL"
                if side=="BUY":
                    st["peak"]=max(float(st.get("peak") or price),price)
                    if price>=entry*1.01: st["armed"]=True
                    hit=st["armed"] and price<=st["peak"]*0.99
                else:
                    st["trough"]=min(float(st.get("trough") or price),price)
                    if price<=entry*0.99: st["armed"]=True
                    hit=st["armed"] and price>=st["trough"]*1.01
                if hit:
                    exit_side="SELL" if side=="BUY" else "BUY"
                    _signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/order",
                        {"symbol":symbol,"side":exit_side,"type":"MARKET","quantity":f"{abs(amt):.12f}","reduceOnly":"true","newOrderRespType":"RESULT"},key,secret)
                    print(f"[TRADE-WATCHER] Futures closed {symbol}",flush=True)
                    _TRADE_WATCHER_STATE["futures"].pop(symbol,None)
            for symbol in list(_TRADE_WATCHER_STATE["futures"]):
                if symbol not in live: _TRADE_WATCHER_STATE["futures"].pop(symbol,None)
        except Exception as exc:
            print(f"[TRADE-WATCHER] Futures scan failed: {exc}",flush=True)
        time.sleep(5)

def _start_trade_watchers():
    import threading
    threading.Thread(target=_spot_trailing_watcher,daemon=True,name="binance-spot-trailing").start()
    threading.Thread(target=_futures_trailing_watcher,daemon=True,name="binance-futures-trailing").start()
    print("[TRADE-WATCHER] Spot/Futures live trailing 1% enabled",flush=True)

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
        _start_trade_watchers()
    except Exception as exc:
        print(f"[STARTUP] worker scheduling error: {type(exc).__name__}: {exc}", flush=True)

@app.get("/api/fast-market")
def fast_market_api(market:str="spot",timeframe:str="15m"):
    """Live market feed used by the current Spot/Futures frontend."""
    if market not in MARKETS:
        return JSONResponse({"ok":False,"message":"قسم غير صالح"},status_code=400)
    if timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"فريم غير صالح"},status_code=400)
    try:
        if market=="spot":
            rows=_scan_spot_strategy(timeframe,limit_symbols=20)
        elif market=="futures":
            rows=_scan_binance_futures(timeframe)
        else:
            rows=_scan_yahoo_market(market,timeframe)
        rows=[dict(x) for x in (rows or [])]
        return {"ok":True,"market":market,"timeframe":timeframe,"trades":rows,"scanning":False,
                "updated_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    except Exception as exc:
        # Keep the API alive and let the UI retry instead of returning FastAPI 404/HTML.
        return JSONResponse({"ok":False,"market":market,"timeframe":timeframe,"trades":[],"scanning":True,
                             "message":"تعذر جلب بيانات Binance حالياً، إعادة المحاولة تلقائياً",
                             "detail":str(exc)[:180]},status_code=200)

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

# Frontend route aliases: prevent cached/mobile navigation from hitting FastAPI 404.
@app.get("/fast-spot",response_class=HTMLResponse)
def fast_spot_page(request:Request): return page(request,"السبوت")

@app.get("/fast-futures",response_class=HTMLResponse)
def fast_futures_page(request:Request): return page(request,"الفيوتشر")

@app.get("/fast-contracts",response_class=HTMLResponse)
def fast_contracts_page(request:Request): return page(request,"العقود الأمريكية")

@app.get("/fast-us",response_class=HTMLResponse)
def fast_us_page(request:Request): return page(request,"السوق الأمريكي")

@app.get("/fast-saudi",response_class=HTMLResponse)
def fast_saudi_page(request:Request): return page(request,"السوق السعودي")

@app.get("/fast-forex",response_class=HTMLResponse)
def fast_forex_page(request:Request): return page(request,"الفوركس والذهب")

@app.get("/spot",response_class=HTMLResponse)
def spot_alias_page(request:Request): return RedirectResponse("/fast-spot",status_code=307)

@app.get("/futures",response_class=HTMLResponse)
def futures_alias_page(request:Request): return RedirectResponse("/fast-futures",status_code=307)

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
    """Read Futures quantity/price filters robustly across Binance symbol variants."""
    symbol=str(symbol or "").upper()
    d=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=10)
    if isinstance(d,dict) and isinstance(d.get("data"),dict) and "symbols" not in d:
        d=d["data"]
    symbols=d.get("symbols",[]) if isinstance(d,dict) else []
    for info in symbols:
        if not isinstance(info,dict) or str(info.get("symbol") or "").upper()!=symbol:
            continue
        if str(info.get("status") or "TRADING").upper() not in {"TRADING",""}:
            raise RuntimeError(f"رمز الفيوتشر غير متاح للتداول حالياً: {symbol}")
        lot=None
        market_lot=None
        price_filter=None
        for flt in (info.get("filters") or []):
            if not isinstance(flt,dict):
                continue
            ftype=str(flt.get("filterType") or "").upper()
            if ftype=="LOT_SIZE":
                lot=flt
            elif ftype=="MARKET_LOT_SIZE":
                market_lot=flt
            elif ftype=="PRICE_FILTER":
                price_filter=flt

        # MARKET orders may be governed by MARKET_LOT_SIZE on some symbols.
        lot_source=lot if lot and _fnum(lot.get("stepSize"),0.0)>0 else market_lot
        step=_fnum(lot_source.get("stepSize") if lot_source else 0.0,0.0)
        min_qty=_fnum(lot_source.get("minQty") if lot_source else 0.0,0.0)
        tick=_fnum(price_filter.get("tickSize") if price_filter else 0.0,0.0)

        # Compatibility fallback for unusual filter payloads.
        if step<=0:
            try:
                qp=int(info.get("quantityPrecision"))
                if qp>=0:
                    step=10.0**(-qp)
            except (TypeError,ValueError):
                pass
        if tick<=0:
            try:
                pp=int(info.get("pricePrecision"))
                if pp>=0:
                    tick=10.0**(-pp)
            except (TypeError,ValueError):
                pass

        if step<=0:
            raise RuntimeError(f"Binance لم يرجع stepSize صالح للرمز {symbol}")
        return info,{"stepSize":step,"minQty":min_qty},{"tickSize":tick}

    raise RuntimeError(f"رمز الفيوتشر غير موجود على Binance: {symbol}")

def _futures_real_entry(signal):
    signal=signal if isinstance(signal,dict) else {}
    symbol=str(signal.get("symbol") or "").upper()
    if not symbol.endswith("USDT"): raise RuntimeError("رمز Futures غير صالح")
    side=str(signal.get("side") or "").upper()
    if side not in {"BUY","SELL"}: raise RuntimeError("اتجاه الصفقة غير صالح")
    timeframe=str(signal.get("timeframe") or "15m")
    if timeframe!="15m": raise RuntimeError("الدخول الحقيقي للفيوتشر مسموح فقط على فريم 15m")

    def _fnum(value, default=0.0):
        if isinstance(value,dict):
            for key in ("value","price","data","availableBalance","stepSize","minQty","tickSize"):
                if key in value:
                    return _fnum(value.get(key),default)
            return float(default)
        try:
            return float(value)
        except (TypeError,ValueError):
            return float(default)

    key,secret=_trade_secrets()
    status=None
    try:
        bal=_signed_binance_request("https://fapi.binance.com","GET","/fapi/v2/balance",{},key,secret)
        if isinstance(bal,dict):
            bal=bal.get("data") if isinstance(bal.get("data"),list) else bal.get("balances") or []
        if not isinstance(bal,list):
            bal=[]
        available=0.0
        for item in bal:
            if isinstance(item,dict) and str(item.get("asset") or "").upper()=="USDT":
                available=_fnum(item.get("availableBalance"),0.0)
                break
    except Exception as exc:
        raise RuntimeError("تعذر قراءة هامش Binance Futures: "+str(exc)[:220])
    if available<=0: raise RuntimeError(f"الهامش المتاح USDT غير كافٍ: {available:.8f}")

    _,lot,price_filter=_futures_symbol_rules(symbol)
    step=_fnum(lot.get("stepSize"),0.0)
    min_qty=_fnum(lot.get("minQty"),0.0)
    tick=_fnum(price_filter.get("tickSize"),0.0)
    if step<=0: raise RuntimeError(f"Binance لم يرجع stepSize صالح للرمز {symbol}")

    try:
        _signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/leverage",
                                {"symbol":symbol,"leverage":20},key,secret)
    except Exception as exc:
        raise RuntimeError("تعذر ضبط رافعة 20x: "+str(exc)[:220])

    ticker=_binance_futures_json(
        f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={urllib.parse.quote(symbol,safe='')}",timeout=6)
    if isinstance(ticker,dict) and isinstance(ticker.get("data"),dict):
        ticker=ticker["data"]
    price=_fnum(ticker.get("price") if isinstance(ticker,dict) else ticker,0.0)
    if price<=0: raise RuntimeError("تعذر الحصول على سعر Binance الحالي")

    margin=available*0.985
    qty=_floor_step((margin*20)/price,step)
    if qty<=0 or (min_qty>0 and qty<min_qty):
        raise RuntimeError(f"الكمية أقل من الحد الأدنى: {qty} < {min_qty}")

    hedge_mode=_futures_position_mode()
    position_side="LONG" if side=="BUY" else "SHORT"
    market_params={"symbol":symbol,"side":side,"type":"MARKET","quantity":_fmt_binance(qty,step),
                   "newOrderRespType":"RESULT"}
    if hedge_mode:
        market_params["positionSide"]=position_side
    market_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/order",
                                         market_params,key,secret)
    if isinstance(market_order,dict) and isinstance(market_order.get("data"),dict):
        market_order=market_order["data"]
    if not isinstance(market_order,dict):
        raise RuntimeError("استجابة دخول Futures غير صالحة")
    executed=_fnum(market_order.get("executedQty"),qty)
    avg=_fnum(market_order.get("avgPrice"),price)
    if executed<=0 or avg<=0:
        raise RuntimeError("Binance Futures لم تنفذ الصفقة")

    if side=="BUY":
        tp=avg*1.005; sl=avg*0.9975; exit_side="SELL"
    else:
        tp=avg*0.995; sl=avg*1.0025; exit_side="BUY"
    tp=_round_tick(tp,tick); sl=_round_tick(sl,tick)
    if tp<=0 or sl<=0: raise RuntimeError("مستويات TP/SL غير صالحة")

    tp_order=None; sl_order=None; protection_errors=[]
    base_tp={"algoType":"CONDITIONAL","symbol":symbol,"side":exit_side,"type":"TAKE_PROFIT_MARKET",
             "triggerPrice":_fmt_binance(tp,tick),"closePosition":"true","workingType":"MARK_PRICE"}
    base_sl={"algoType":"CONDITIONAL","symbol":symbol,"side":exit_side,"type":"STOP_MARKET",
             "triggerPrice":_fmt_binance(sl,tick),"closePosition":"true","workingType":"MARK_PRICE"}
    if hedge_mode:
        base_tp["positionSide"]=position_side
        base_sl["positionSide"]=position_side
    try:
        tp_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/algoOrder",
                                         base_tp,key,secret)
        print(f"[PROTECTION] Futures {symbol} {side} TP={tp} placed",flush=True)
    except Exception as exc:
        protection_errors.append("TP: "+str(exc)[:180])
        print(f"[PROTECTION] Futures {symbol} TP failed: {str(exc)[:180]}",flush=True)
    try:
        sl_order=_signed_binance_request("https://fapi.binance.com","POST","/fapi/v1/algoOrder",
                                         base_sl,key,secret)
        print(f"[PROTECTION] Futures {symbol} {side} SL={sl} placed",flush=True)
    except Exception as exc:
        protection_errors.append("SL: "+str(exc)[:180])
        print(f"[PROTECTION] Futures {symbol} SL failed: {str(exc)[:180]} — position left open for watcher",flush=True)

    return {"symbol":symbol,"side":side,"timeframe":"15m","entry":avg,"qty":executed,
            "margin_usdt":margin,"notional_usdt":margin*20,"leverage":20,
            "target_margin_pct":10,"stop_margin_pct":5,"tp_price":tp,"sl_price":sl,
            "order_id":market_order.get("orderId"),"tp_order":tp_order,"sl_order":sl_order,
            "protection_errors":protection_errors}

@app.post("/api/spot/entry")
async def spot_entry_api(request:Request):
    user=_trade_user_required(request)
    if not user:
        return JSONResponse({"ok":False,"message":"سجّل الدخول أولاً لتنفيذ أمر حقيقي على Binance Spot"},status_code=401)
    try:
        signal=await request.json()
        trade=_spot_real_entry(signal if isinstance(signal,dict) else {})
        return {"ok":True,"trade":trade}
    except Exception as exc:
        return JSONResponse({"ok":False,"message":str(exc)[:300]},status_code=400)

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
    try:
        _strategy_lab_resume_on_startup()
    except Exception as exc:
        print(f"[STRATEGY-LAB] resume check failed: {exc}",flush=True)

@app.get("/api/bots/status")
def all_bots_status():
    configured=bool(os.getenv("BINANCE_API_KEY","").strip() and os.getenv("BINANCE_API_SECRET","").strip())
    return {
        "ok":True,"configured":configured,
        "spot":{"enabled":configured,"status":"manual-entry","timeframe":"15m","real_orders":configured},
        "futures":{"enabled":configured,"status":"manual-entry","timeframe":"15m","real_orders":configured}
    }

# ===== STRATEGY LAB: automatic historical strategy finder =====

# Historical research only: no real orders are placed by this lab.
_STRATEGY_LAB_STATE_PATH = DATA_DIR/"strategy_lab"/"state.json"
_STRATEGY_LAB = {"running": False, "progress": 0, "message": "جاهز", "results": [], "started_at": None, "finished_at": None, "error": None}

def _strategy_lab_save_state():
    try:
        _STRATEGY_LAB_STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
        with _STRATEGY_LAB_LOCK:
            state=dict(_STRATEGY_LAB)
        _STRATEGY_LAB_STATE_PATH.write_text(json.dumps(state,ensure_ascii=False),encoding="utf-8")
    except Exception:
        pass

def _strategy_lab_load_state():
    try:
        if _STRATEGY_LAB_STATE_PATH.exists():
            saved=json.loads(_STRATEGY_LAB_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(saved,dict):
                with _STRATEGY_LAB_LOCK: _STRATEGY_LAB.update(saved)
    except Exception:
        pass
_STRATEGY_LAB_LOCK = __import__("threading").Lock()

def _lab_fetch_klines(symbol, interval, start_ms, end_ms):
    rows=[]
    cur=int(start_ms)
    while cur < int(end_ms):
        q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"startTime":cur,"endTime":int(end_ms),"limit":1500})
        data=_binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+q,timeout=15)
        if not data: break
        rows.extend(data)
        nxt=int(data[-1][0])+1
        if nxt <= cur: break
        cur=nxt
        if len(data)<1500: break
    return rows

def _lab_candle(k):
    return {
        "t":int(k[0]),"o":float(k[1]),"h":float(k[2]),
        "l":float(k[3]),"c":float(k[4]),"v":float(k[7])
    }

def _lab_download_data(symbols, days):
    end=int(time.time()*1000)
    start=end-int(days)*86400000
    out={}
    total=len(symbols)
    for idx,symbol in enumerate(symbols,1):
        k5=_lab_fetch_klines(symbol,"5m",start,end)
        k1=_lab_fetch_klines(symbol,"1m",start,end)
        if len(k5)>=100 and len(k1)>=500:
            out[symbol]={"m5":[_lab_candle(x) for x in k5],"m1":[_lab_candle(x) for x in k1]}
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB["message"]=f"تحميل البيانات {idx}/{total}: {symbol}"
            _STRATEGY_LAB["progress"]=min(25,int(idx/total*25))
        _strategy_lab_save_state()
    return out

def _lab_eval_symbol(data, p, start_cut, end_cut):
    m5=data["m5"]; m1=data["m1"]
    one={x["t"]:x for x in m1}
    trades=[]
    i=0
    while i < len(m5)-1:
        c=m5[i]
        if not (start_cut <= c["t"] < end_cut):
            i+=1; continue
        move=(c["c"]-c["o"])/c["o"] if c["o"] else 0
        side="BUY" if p["strong_min"] <= move <= p["strong_max"] else "SELL" if -p["strong_max"] <= move <= -p["strong_min"] else None
        if not side:
            i+=1; continue
        confirm=one.get(c["t"]+300000)
        if not confirm:
            i+=1; continue
        cmove=(confirm["c"]-confirm["o"])/confirm["o"] if confirm["o"] else 0
        if side=="BUY" and cmove < p["confirm_min"]:
            i+=1; continue
        if side=="SELL" and cmove > -p["confirm_min"]:
            i+=1; continue
        entry=confirm["c"]
        tp_move=p["tp_margin"]/p["leverage"]
        sl_move=p["sl_margin"]/p["leverage"]
        tp=entry*(1+tp_move) if side=="BUY" else entry*(1-tp_move)
        sl=entry*(1-sl_move) if side=="BUY" else entry*(1+sl_move)
        result=None
        exit_t=None
        end_i=min(len(m1), one.get(confirm["t"],confirm)["t"] and len(m1))
        # Locate confirmation index once, then scan forward.
        j=0
        while j<len(m1) and m1[j]["t"]<=confirm["t"]: j+=1
        stop_j=min(len(m1),j+p["max_hold_min"])
        while j<stop_j:
            x=m1[j]
            if side=="BUY":
                hit_tp=x["h"]>=tp; hit_sl=x["l"]<=sl
            else:
                hit_tp=x["l"]<=tp; hit_sl=x["h"]>=sl
            if hit_tp and hit_sl:
                result="LOSS"
            elif hit_tp:
                result="WIN"
            elif hit_sl:
                result="LOSS"
            if result:
                exit_t=x["t"]
                break
            j+=1
        if result and exit_t is not None and exit_t < end_cut:
            trades.append({"side":side,"result":result,"t":c["t"]})
            while i<len(m5) and m5[i]["t"]<=exit_t:
                i+=1
            continue
        if result and exit_t is not None and exit_t >= end_cut:
            i+=1
            continue
        i+=1
    return trades

def _lab_metrics(trades):
    n=len(trades); wins=sum(1 for x in trades if x["result"]=="WIN"); losses=n-wins
    if not n: return {"trades":0,"wins":0,"losses":0,"win_rate":0,"net_pct":0,"max_dd_pct":0,"profit_factor":0}
    equity=100.0; peak=100.0; maxdd=0.0
    gross_win=0.0; gross_loss=0.0
    for x in trades:
        delta=10.0 if x["result"]=="WIN" else -5.0
        equity += delta
        if delta>0: gross_win+=delta
        else: gross_loss+=-delta
        peak=max(peak,equity)
        maxdd=max(maxdd,(peak-equity)/peak*100 if peak else 0)
    return {
        "trades":n,"wins":wins,"losses":losses,
        "win_rate":round(wins/n*100,2),
        "net_pct":round(equity-100,2),
        "max_dd_pct":round(maxdd,2),
        "profit_factor":round(gross_win/gross_loss,2) if gross_loss else 99.0
    }

def _lab_score(train,test):
    # Require enough trades and reward out-of-sample performance.
    if test["trades"]<20 or train["trades"]<30: return -999999
    if test["max_dd_pct"]>60: return -999999
    return round(
        test["net_pct"]*0.45 +
        test["profit_factor"]*20 +
        test["win_rate"]*0.35 -
        test["max_dd_pct"]*0.40 +
        min(train["profit_factor"],5)*8, 3
    )

def _run_strategy_lab(days=14,max_symbols=12,min_volume=1000000):
    ticker=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=20)
    exchange=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=20)
    allowed={x["symbol"] for x in exchange["symbols"] if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL" and x.get("quoteAsset")=="USDT"}
    vols={x["symbol"]:float(x.get("quoteVolume") or 0) for x in ticker if x.get("symbol") in allowed}
    symbols=sorted([s for s,v in vols.items() if v>=float(min_volume)],key=lambda s:vols[s],reverse=True)[:int(max_symbols)]
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB["message"]=f"اختيار {len(symbols)} عقود حسب حجم 24 ساعة"
        _STRATEGY_LAB["progress"]=2
    data=_lab_download_data(symbols,int(days))
    if not data: raise RuntimeError("تعذر تحميل بيانات Binance Futures")
    # 70/30 chronological split.
    all_times=[c["t"] for d in data.values() for c in d["m5"]]
    cut=min(all_times)+int((max(all_times)-min(all_times))*0.70)
    end=max(all_times)+1
    params=[]
    for sm in (0.005,0.0075,0.01,0.0125,0.015):
        for sx in (0.02,0.03,0.04,0.06):
            if sx<=sm: continue
            for cm in (0.001,0.002,0.003,0.004):
                for tp in (0.05,0.10,0.15):
                    for sl in (0.03,0.05,0.07):
                        params.append({"strong_min":sm,"strong_max":sx,"confirm_min":cm,"tp_margin":tp,"sl_margin":sl,"leverage":20,"max_hold_min":120})
    results=[]
    total=len(params)
    for n,p in enumerate(params,1):
        train=[]; test=[]
        for d in data.values():
            train.extend(_lab_eval_symbol(d,p,min(all_times),cut))
            test.extend(_lab_eval_symbol(d,p,cut,end))
        tm=_lab_metrics(train); xm=_lab_metrics(test)
        score=_lab_score(tm,xm)
        if score>-999000:
            results.append({"rank":0,"score":score,"parameters":p,"train":tm,"test":xm,"markets":len(data)})
        if n%10==0:
            results.sort(key=lambda x:x["score"],reverse=True)
            results=results[:100]
            with _STRATEGY_LAB_LOCK:
                _STRATEGY_LAB["progress"]=25+int(n/total*70)
                _STRATEGY_LAB["message"]=f"اختبار {n}/{total} تركيبة"
            _strategy_lab_save_state()
    results.sort(key=lambda x:x["score"],reverse=True)
    for i,r in enumerate(results,1): r["rank"]=i
    result_dir=DATA_DIR/"strategy_lab"; result_dir.mkdir(parents=True,exist_ok=True)
    # Auto-activate only an out-of-sample validated strategy; signal-only, never places orders.
    active=None
    for r in results:
        t=r["test"]
        if t["trades"]>=30 and t["net_pct"]>0 and t["profit_factor"]>=1.20 and t["max_dd_pct"]<=40:
            active={"active":True,"activated_at":time.time(),"reason":"OOS validation","rank":r["rank"],"score":r["score"],"parameters":r["parameters"],"train":r["train"],"test":r["test"],"markets_tested":r["markets"]}
            break
    if active:
        (result_dir/"active.json").write_text(json.dumps(active,ensure_ascii=False,indent=2),encoding="utf-8")
    else:
        # Never deploy a strategy just because it was the best of a bad batch.
        (result_dir/"active.json").write_text(json.dumps({"active":False,"message":"لا توجد استراتيجية اجتازت شروط الاختبار الخارجي"},ensure_ascii=False,indent=2),encoding="utf-8")
    (result_dir/"results.json").write_text(json.dumps({"generated_at":time.time(),"days":days,"symbols":symbols,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["rank,score,strong_min,strong_max,confirm_min,tp_margin,sl_margin,train_trades,train_win_rate,test_trades,test_win_rate,test_net_pct,test_max_dd,test_profit_factor"]
    for r in results:
        p=r["parameters"]; a=r["train"]; b=r["test"]
        lines.append(",".join(map(str,[r["rank"],r["score"],p["strong_min"],p["strong_max"],p["confirm_min"],p["tp_margin"],p["sl_margin"],a["trades"],a["win_rate"],b["trades"],b["win_rate"],b["net_pct"],b["max_dd_pct"],b["profit_factor"]])))
    (result_dir/"results.csv").write_text("\n".join(lines),encoding="utf-8")
    return results

def _strategy_lab_worker(days,max_symbols,min_volume):
    try:
        results=_run_strategy_lab(days,max_symbols,min_volume)
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB.update({"running":False,"progress":100,"message":f"اكتمل البحث: {len(results)} نتيجة محفوظة","results":results[:20],"finished_at":time.time(),"error":None})
        _strategy_lab_save_state()
    except Exception as exc:
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB.update({"running":False,"message":"توقف البحث بسبب خطأ","error":str(exc)[:300],"finished_at":time.time()})
        _strategy_lab_save_state()

@app.get("/strategy-lab",response_class=HTMLResponse)
def strategy_lab_page():
    p=BASE/"static"/"strategy-lab.html"
    response=FileResponse(p,media_type="text/html")
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.post("/api/strategy-lab/start")
async def strategy_lab_start(request:Request):
    with _STRATEGY_LAB_LOCK:
        if _STRATEGY_LAB["running"]:
            return {"ok":False,"message":"البحث شغال حالياً"}
    body=await request.json()
    days=max(3,min(60,int(body.get("days",14))))
    max_symbols=max(4,min(30,int(body.get("max_symbols",12))))
    min_volume=max(100000,float(body.get("min_volume",1000000)))
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({"running":True,"progress":0,"message":"بدء البحث...","results":[],"started_at":time.time(),"finished_at":None,"error":None})
    _strategy_lab_save_state()
    __import__("threading").Thread(target=_strategy_lab_worker,args=(days,max_symbols,min_volume),daemon=True).start()
    return {"ok":True,"message":"بدأ البحث","days":days,"max_symbols":max_symbols,"min_volume":min_volume,"combinations":648}

@app.get("/api/strategy-lab/status")
def strategy_lab_status():
    with _STRATEGY_LAB_LOCK:
        return {"ok":True,**_STRATEGY_LAB}

def _strategy_lab_resume_on_startup():
    _strategy_lab_load_state()
    with _STRATEGY_LAB_LOCK:
        running=_STRATEGY_LAB.get("running")
    if running:
        print("[STRATEGY-LAB] resuming persistent research after server restart",flush=True)
        __import__("threading").Thread(target=_strategy_lab_worker,args=(14,30,1000000),daemon=True).start()

@app.get("/api/strategy-lab/results")
def strategy_lab_results(download:int=0):
    p=DATA_DIR/"strategy_lab"/"results.json"
    if not p.exists(): return JSONResponse({"ok":False,"message":"لا توجد نتائج بعد"},status_code=404)
    if download:
        return FileResponse(p,media_type="application/json",filename="strategy-lab-results.json")
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")))

@app.get("/api/strategy-lab/results.csv")
def strategy_lab_csv():
    p=DATA_DIR/"strategy_lab"/"results.csv"
    if not p.exists(): return JSONResponse({"ok":False,"message":"لا توجد نتائج بعد"},status_code=404)
    return FileResponse(p,media_type="text/csv",filename="strategy-lab-results.csv")
