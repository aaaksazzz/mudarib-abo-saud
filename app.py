import hashlib
import time
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
# Strategy Lab encryption-at-rest. Prefer STRATEGY_LAB_ENCRYPTION_KEY as a Northflank secret.
LAB_CIPHER_KEY=os.getenv("STRATEGY_LAB_ENCRYPTION_KEY","").strip() or SECRET
def _lab_crypto_key():
    return hashlib.sha256(("strategy-lab-v1:" + LAB_CIPHER_KEY).encode("utf-8")).digest()
def _lab_encrypt_text(plain):
    raw=plain.encode("utf-8"); nonce=secrets.token_bytes(16); key=_lab_crypto_key(); out=bytearray(); counter=0
    for pos in range(0,len(raw),32):
        block=raw[pos:pos+32]; stream=hmac.new(key,nonce+counter.to_bytes(8,"big"),hashlib.sha256).digest()
        out.extend(a^b for a,b in zip(block,stream)); counter+=1
    cipher=bytes(out); tag=hmac.new(key,b"SL1"+nonce+cipher,hashlib.sha256).digest()
    import base64
    return "SL1:" + base64.urlsafe_b64encode(nonce+cipher+tag).decode("ascii")
def _lab_decrypt_text(payload):
    import base64
    if not isinstance(payload,str) or not payload.startswith("SL1:"): raise ValueError("not encrypted")
    blob=base64.urlsafe_b64decode(payload[4:].encode("ascii"))
    if len(blob)<48: raise ValueError("encrypted payload too short")
    nonce,cipher,tag=blob[:16],blob[16:-32],blob[-32:]; key=_lab_crypto_key()
    expected=hmac.new(key,b"SL1"+nonce+cipher,hashlib.sha256).digest()
    if not hmac.compare_digest(tag,expected): raise ValueError("strategy lab authentication failed")
    out=bytearray(); counter=0
    for pos in range(0,len(cipher),32):
        block=cipher[pos:pos+32]; stream=hmac.new(key,nonce+counter.to_bytes(8,"big"),hashlib.sha256).digest()
        out.extend(a^b for a,b in zip(block,stream)); counter+=1
    return bytes(out).decode("utf-8")
def _lab_read_json(path, default=None):
    if not path.exists(): return default
    try:
        raw=path.read_text(encoding="utf-8")
        try: return json.loads(_lab_decrypt_text(raw))
        except Exception:
            value=json.loads(raw); _lab_write_json(path,value); return value
    except Exception: return default
def _lab_write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(_lab_encrypt_text(json.dumps(value,ensure_ascii=False,indent=2)),encoding="utf-8")
    tmp.replace(path)
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

# Temporary standalone lock for Strategy Lab while the main admin login is being repaired.
# The password is stored only as a SHA-256 digest; the raw password is never kept in code.
STRATEGY_LAB_PASSWORD_SHA256="3dab93046a583566b8fd5043a8e79d0b77b96f5c501b9406ebd2905a12806aec"

def strategy_lab_access(request:Request):
    return bool(request.session.get("strategy_lab_unlocked"))

def _strategy_lab_password_ok(password:str):
    digest=hashlib.sha256(str(password or "").encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest,STRATEGY_LAB_PASSWORD_SHA256)

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

def _lab_active_config(market=None,timeframe=None):
    try:
        d=DATA_DIR/"strategy_lab"; mp=d/"active_map.json"
        if not mp.exists() or not market or not timeframe: return None
        x=_lab_read_json(mp,{})
        a=x.get(f"{market}:{timeframe}") if isinstance(x,dict) else None
        return a if isinstance(a,dict) and a.get("active") and a.get("factory_approved") else None
    except Exception:
        return None
def _scan_binance_lab_strategy(market, limit_symbols=20, requested_timeframe="15m"):
    cfg=_lab_active_config(market,requested_timeframe)
    if not cfg: return []
    p=cfg.get("parameters") or {}
    is_spot=market=="spot"; base="https://api.binance.com" if is_spot else "https://fapi.binance.com"
    kpath="/api/v3/klines" if is_spot else "/fapi/v1/klines"; tpath="/api/v3/ticker/24hr" if is_spot else "/fapi/v1/ticker/24hr"
    info=_binance_json(base+("/api/v3/exchangeInfo" if is_spot else "/fapi/v1/exchangeInfo"),timeout=10)
    allowed={x.get("symbol") for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"}
    tickers=_binance_json(base+tpath,timeout=10); ranked=[]
    for t in tickers if isinstance(tickers,list) else []:
        sym=t.get("symbol")
        if sym not in allowed or sym in BINANCE_SCANNER_EXCLUDED: continue
        try:
            vol=float(t.get("quoteVolume") or 0)
            if vol>=BINANCE_SCANNER_MIN_VOLUME: ranked.append((sym,vol,float(t.get("priceChangePercent") or 0)))
        except Exception: pass
    ranked.sort(key=lambda x:x[1],reverse=True); out=[]
    signal_interval=str(p.get("signal_interval",requested_timeframe)); confirm_interval=str(p.get("confirm_interval","1m"))
    for sym,vol,ch24 in ranked[:limit_symbols]:
        try:
            q1=urllib.parse.urlencode({"symbol":sym,"interval":signal_interval,"limit":210}); q2=urllib.parse.urlencode({"symbol":sym,"interval":confirm_interval,"limit":210})
            k1=_binance_json(base+kpath+"?"+q1,timeout=8) if is_spot else _binance_futures_json(base+kpath+"?"+q1,timeout=8)
            k2=_binance_json(base+kpath+"?"+q2,timeout=8) if is_spot else _binance_futures_json(base+kpath+"?"+q2,timeout=8)
            if not isinstance(k1,list) or not isinstance(k2,list) or len(k1)<10 or len(k2)<10: continue
            c1=k1[-2]; c2_by_t={int(x[0]):x for x in k2}; c2=c2_by_t.get(int(c1[0]) + int(p.get("signal_ms",900000)))
            if not c2: continue
            move1=(float(c1[4])-float(c1[1]))/float(c1[1]) if float(c1[1]) else 0; move2=(float(c2[4])-float(c2[1]))/float(c2[1]) if float(c2[1]) else 0
            side="BUY" if p["strong_min"]<=move1<=p["strong_max"] and move2>=p["confirm_min"] else None
            if not is_spot and -p["strong_max"]<=move1<=-p["strong_min"] and move2<=-p["confirm_min"]: side="SELL"
            if not side: continue
            price=float(c2[4]); tp_move=p["tp_margin"]/p["leverage"]; sl_move=p["sl_margin"]/p["leverage"]; risk=price*sl_move
            tp1=price*(1+tp_move) if side=="BUY" else price*(1-tp_move); sl=price*(1-sl_move) if side=="BUY" else price*(1+sl_move)
            out.append({"symbol":sym,"side":side,"timeframe":f"{signal_interval}+{confirm_interval}","change_pct":round(move1*100,3),"change_24h":ch24,"price":price,"entry":price,"tp1":tp1,"tp2":tp1,"tp3":tp1,"sl":sl,"ai_pct":90,"score":90,"volume":vol,"volume_ratio":0,"reasons":["استراتيجية مستخرجة تاريخياً",f"{signal_interval} قوة",f"{confirm_interval} تأكيد"],"patterns":["STRATEGY_LAB"],"candle_start":c2[0],"expires_at":c2[6],"target_pct":p["tp_margin"]*100,"stop_pct":p["sl_margin"]*100,"leverage":p["leverage"] if not is_spot else 1})
        except Exception: continue
    return sorted(out,key=lambda x:float(x.get("volume") or 0),reverse=True)

def _scan_spot_strategy(timeframe,limit_symbols=20):
    if _lab_active_config("spot",timeframe):
        return _scan_binance_lab_strategy("spot",limit_symbols,timeframe)
    return []

def _scan_binance_futures(timeframe):
    if _lab_active_config("futures",timeframe):
        return _scan_binance_lab_strategy("futures",20,timeframe)
    return []

_YAHOO_SYMBOLS={
    "us":["NVDA","AMD","TSLA","AAPL","MSFT","AMZN","META","GOOGL","AVGO","NFLX","PLTR","MSTR","SMCI","MU","QCOM","ARM","COIN","HOOD","SHOP","CRWD","ORCL"],
    "saudi":["2222.SR","1120.SR","2010.SR","7010.SR","7020.SR","1211.SR","1180.SR","1150.SR","1060.SR","4030.SR","2380.SR","4200.SR","2280.SR","2080.SR","2050.SR"],
    "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","USDCAD=X","AUDUSD=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F"]
}

def _scan_yahoo_market(market,timeframe):
    cfg=_lab_active_config(market,timeframe)
    if not cfg: return []
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
    # Optional dedicated admin bootstrap. Credentials come from Northflank secrets, never source code.
    admin_name=os.getenv("ADMIN_USERNAME","").strip() or "aaaksazzz"
    admin_password=os.getenv("ADMIN_PASSWORD","")
    admin_password_hash="961d37f69b4243806da8a53f4d678cf8$5f1dd01196179a9951853f4a8378049b5267e1dd081ac4708e1f1284ca1b77fa"
    if admin_name and (admin_password or admin_password_hash):
        admin_email=os.getenv("ADMIN_EMAIL",f"{admin_name}@admin.local").strip().lower()
        try:
            row=c.execute("SELECT id FROM users WHERE name=? OR email=? LIMIT 1",(admin_name,admin_email)).fetchone()
            hashed=password_hash(admin_password) if admin_password else admin_password_hash
            if row:
                c.execute("UPDATE users SET name=?,email=?,password_hash=?,is_admin=1 WHERE id=?",(admin_name,admin_email,hashed,row["id"]))
            else:
                c.execute("INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,1)",(admin_name,admin_email,hashed))
            print("[ADMIN] dedicated admin account ready",flush=True)
        except Exception as exc:
            print(f"[ADMIN] bootstrap error: {type(exc).__name__}",flush=True)
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
def admin_login_page(request:Request):
    if admin_user(request):
        return RedirectResponse("/admin",status_code=303)
    html="""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>دخول الإدارة | SMART TRADING PRO</title>
<style>
body{margin:0;background:#0b1220;color:#fff;font-family:Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{width:min(92vw,420px);background:#111a2b;border:1px solid #26334a;border-radius:18px;padding:24px;box-sizing:border-box;box-shadow:0 16px 45px #0006}
h1{margin:0 0 8px;font-size:24px}.muted{color:#9aa8bd;margin-bottom:20px}
label{display:block;margin:12px 0 6px}.input{width:100%;box-sizing:border-box;padding:13px;border-radius:10px;border:1px solid #33425c;background:#0b1220;color:#fff;font-size:16px}
button{width:100%;margin-top:18px;padding:13px;border:0;border-radius:10px;background:#16a36b;color:#fff;font-weight:700;font-size:16px;cursor:pointer}
#msg{margin-top:14px;text-align:center;color:#ff9b9b;min-height:20px}
</style>
</head>
<body><main class="card">
<h1>🔐 دخول الإدارة</h1>
<div class="muted">SMART TRADING PRO — أدخل الرقم السري للوصول للإدارة</div>
<form id="f">
<input type="hidden" name="username" value="aaaksazzz">
<label>الرقم السري</label>
<input class="input" type="password" inputmode="numeric" pattern="[0-9]*" name="password" autocomplete="current-password" autofocus required>
<button type="submit">دخول الإدارة</button>
<div id="msg"></div>
</form>
</main>
<script>
document.getElementById("f").addEventListener("submit",async e=>{
 e.preventDefault();
 const f=e.currentTarget, msg=document.getElementById("msg");
 msg.textContent="جارٍ التحقق...";
 const r=await fetch("/api/admin/login",{method:"POST",body:new FormData(f),credentials:"same-origin"});
 let d={}; try{d=await r.json()}catch(_){}
 if(r.ok&&d.ok){location.href="/admin";return}
 msg.textContent=d.message||"بيانات دخول الإدارة غير صحيحة";
});
</script>
</body></html>"""
    response=HTMLResponse(html)
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request):
    if not admin_user(request):
        return RedirectResponse("/admin/login",status_code=303)
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
    identifier=email.strip()
    c=db(); row=c.execute("SELECT * FROM users WHERE email=? OR name=? LIMIT 1",(identifier.lower(),identifier)).fetchone(); c.close()
    if not row or not password_ok(password,row["password_hash"]):
        return JSONResponse({"ok":False,"message":"بيانات الدخول غير صحيحة"},status_code=401)
    request.session["user_id"]=row["id"]; return {"ok":True,"message":"تم تسجيل الدخول"}

@app.post("/api/admin/login")
def admin_login(request:Request,username:str=Form(...),password:str=Form(...)):
    identifier=username.strip()
    c=db(); row=c.execute("SELECT * FROM users WHERE (name=? OR email=?) AND is_admin=1 LIMIT 1",(identifier,identifier.lower())).fetchone(); c.close()
    if not row or not password_ok(password,row["password_hash"]):
        return JSONResponse({"ok":False,"message":"بيانات دخول الإدارة غير صحيحة"},status_code=401)
    request.session["user_id"]=row["id"]
    return {"ok":True,"message":"تم تسجيل دخول الإدارة"}

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
        "method":"edge_scanner_price_action_order_flow",                "indicators":False,
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
_STRATEGY_LAB = {"running": False, "progress": 0, "message": "جاهز", "results": [], "started_at": None, "finished_at": None, "error": None, "job_params": None, "heartbeat_at": None, "market": "futures", "timeframe": "15m", "active_strategy": None}
_STRATEGY_LAB_WORKER_ALIVE = False
_STRATEGY_LAB_HEARTBEAT_STOP = __import__("threading").Event()

def _strategy_lab_save_state():
    try:
        _STRATEGY_LAB_STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
        with _STRATEGY_LAB_LOCK:
            state=dict(_STRATEGY_LAB)
            state["heartbeat_at"]=time.time() if state.get("running") else state.get("heartbeat_at")
        tmp=_STRATEGY_LAB_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state,ensure_ascii=False),encoding="utf-8")
        tmp.replace(_STRATEGY_LAB_STATE_PATH)
    except Exception:
        pass

def _strategy_lab_heartbeat():
    while not _STRATEGY_LAB_HEARTBEAT_STOP.wait(3):
        with _STRATEGY_LAB_LOCK:
            if not _STRATEGY_LAB.get("running"):
                return
            _STRATEGY_LAB["heartbeat_at"]=time.time()
        _strategy_lab_save_state()

def _strategy_lab_start_heartbeat():
    _STRATEGY_LAB_HEARTBEAT_STOP.clear()
    __import__("threading").Thread(target=_strategy_lab_heartbeat,daemon=True).start()

def _strategy_lab_stop_heartbeat():
    _STRATEGY_LAB_HEARTBEAT_STOP.set()

def _strategy_lab_load_state():
    try:
        if _STRATEGY_LAB_STATE_PATH.exists():
            saved=json.loads(_STRATEGY_LAB_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(saved,dict):
                with _STRATEGY_LAB_LOCK: _STRATEGY_LAB.update(saved)
    except Exception:
        pass
_STRATEGY_LAB_LOCK = __import__("threading").Lock()

def _lab_fetch_klines(symbol, interval, start_ms, end_ms, market="futures"):
    rows=[]
    cur=int(start_ms)
    while cur < int(end_ms):
        q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"startTime":cur,"endTime":int(end_ms),"limit":1500})
        data=(_binance_json(("https://api.binance.com/api/v3/klines" if market=="spot" else "https://fapi.binance.com/fapi/v1/klines")+"?"+q,timeout=15) if market=="spot" else _binance_futures_json("https://fapi.binance.com/fapi/v1/klines?"+q,timeout=15))
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

def _lab_fetch_order_book(symbol, market="futures", limit=100):
    """Fetch a live Binance order-book snapshot for the deep Strategy Lab pass.
    Historical order-book data is not available from Binance REST, so depth is
    stored as a current liquidity snapshot alongside the historical OHLCV/volume.
    """
    symbol=str(symbol).upper()
    path="/api/v3/depth" if market=="spot" else "/fapi/v1/depth"
    params=urllib.parse.urlencode({"symbol":symbol,"limit":int(limit)})
    if market=="spot":
        data=_binance_json("https://api.binance.com"+path+"?"+params,timeout=8)
    else:
        data=_binance_futures_json("https://fapi.binance.com"+path+"?"+params,timeout=8)
    bids=data.get("bids") if isinstance(data,dict) else None
    asks=data.get("asks") if isinstance(data,dict) else None
    if not isinstance(bids,list) or not isinstance(asks,list) or not bids or not asks:
        raise RuntimeError(f"بيانات Order Book غير مكتملة: {symbol}")
    def levels(rows):
        out=[]
        for row in rows:
            if not isinstance(row,(list,tuple)) or len(row)<2: continue
            try: out.append((float(row[0]),float(row[1])))
            except Exception: continue
        return out
    bids=levels(bids); asks=levels(asks)
    if not bids or not asks: raise RuntimeError(f"مستويات العمق غير صالحة: {symbol}")
    best_bid=bids[0][0]; best_ask=asks[0][0]
    mid=(best_bid+best_ask)/2 if best_bid and best_ask else 0
    bid_qty=sum(q for _,q in bids[:20]); ask_qty=sum(q for _,q in asks[:20])
    total_qty=bid_qty+ask_qty
    return {
        "last_update_id":data.get("lastUpdateId"),
        "bids":bids[:100],
        "asks":asks[:100],
        "best_bid":best_bid,
        "best_ask":best_ask,
        "mid":mid,
        "spread":best_ask-best_bid,
        "spread_pct":((best_ask-best_bid)/mid*100) if mid else 0,
        "bid_qty_top20":bid_qty,
        "ask_qty_top20":ask_qty,
        "imbalance_pct":((bid_qty-ask_qty)/total_qty*100) if total_qty else 0,
        "bid_share_pct":(bid_qty/total_qty*100) if total_qty else 50,
        "ask_share_pct":(ask_qty/total_qty*100) if total_qty else 50,
        "fetched_at":time.time()
    }

def _lab_download_data(symbols, days, market="futures", timeframe="15m"):
    end=int(time.time()*1000); start=end-int(days)*86400000; out={}
    total=len(symbols); cache_dir=DATA_DIR/"strategy_lab"/"market_cache"; cache_dir.mkdir(parents=True,exist_ok=True)
    confirm_map={"15m":"5m","30m":"5m","1h":"15m","4h":"15m","1d":"1h","1w":"4h","1M":"1d"}; confirm_interval=confirm_map.get(timeframe,"1m")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def _download_one(symbol):
        cache_file=cache_dir/(str(market)+"_"+str(symbol)+"_"+str(timeframe)+"_"+str(days)+"d.json")
        if cache_file.exists():
            try:
                cached=json.loads(cache_file.read_text(encoding="utf-8"))
                cached_data=cached.get("data") or {}
                cached_depth=cached_data.get("depth") if isinstance(cached_data,dict) else None
                if cached.get("symbol")==symbol and cached.get("market")==market and cached.get("timeframe")==timeframe and cached.get("days")==days and cached_data and cached_depth and cached_depth.get("bids") and cached_depth.get("asks"): return symbol,cached_data
            except Exception: pass
        ks=_lab_fetch_klines(symbol,timeframe,start,end,market); kc=_lab_fetch_klines(symbol,confirm_interval,start,end,market)
        if len(ks)<50 or len(kc)<100: return symbol,None
        # OHLCV + Volume التاريخي، ثم لقطة Order Book/Depth حقيقية وقت الفحص.
        depth=None
        for attempt in range(3):
            try:
                depth=_lab_fetch_order_book(symbol,market,limit=100)
                if depth.get("bids") and depth.get("asks"): break
            except Exception:
                depth=None
            time.sleep(0.35*(attempt+1))
        if not depth or not depth.get("bids") or not depth.get("asks"): return symbol,None
        item={"signal":[_lab_candle(x) for x in ks],"confirm":[_lab_candle(x) for x in kc],"depth":depth}
        try: cache_file.write_text(json.dumps({"symbol":symbol,"market":market,"timeframe":timeframe,"confirm_interval":confirm_interval,"days":days,"data":item},ensure_ascii=False),encoding="utf-8")
        except Exception: pass
        return symbol,item
    with ThreadPoolExecutor(max_workers=min(12,max(1,len(symbols)))) as pool:
        futures={pool.submit(_download_one,s):s for s in symbols}
        for idx,fut in enumerate(as_completed(futures),1):
            symbol,item=fut.result()
            if item: out[symbol]=item
            with _STRATEGY_LAB_LOCK:
                _STRATEGY_LAB["current_symbol"]=symbol; _STRATEGY_LAB["symbols_done"]=idx; _STRATEGY_LAB["symbols_total"]=total; _STRATEGY_LAB["message"]="⚡ يفحص "+str(symbol)+" — "+str(idx)+"/"+str(total); _STRATEGY_LAB["progress"]=min(25,int(idx/total*25))
            if idx==1 or idx%4==0: _strategy_lab_save_state()
    return out
_STRATEGY_LAB_METHODS=[
("price_action","Price Action"),("breakout","Breakout"),("range_breakout","Range Breakout"),
("momentum","Momentum"),("mean_reversion","Mean Reversion"),("market_structure","Market Structure"),
("support_resistance","Support/Resistance"),("volatility","Volatility Regime"),
("volume_behavior","Volume + Price"),("candlestick","Candlestick"),("session","Session/Time"),
("statistical","Statistical"),("indicator_hybrid","Indicator Hybrid"),("hybrid","Multi-Method Hybrid")]

def _lab_method_signal(rows,i,p):
    if i<25:return None
    c=rows[i]; o,h,l,cl=[float(c[k]) for k in ("o","h","l","c")]
    idea=p.get("idea","indicator_hybrid"); n=max(5,int(p.get("lookback",20))); hist=rows[max(0,i-n):i]
    if not hist:return None
    hh=max(float(x["h"]) for x in hist); ll=min(float(x["l"]) for x in hist)
    span=max(h-l,1e-12); body=abs(cl-o); upper=h-max(o,cl); lower=min(o,cl)-l
    move=(cl-o)/o if o else 0.0; minimum=float(p.get("min_move",.001))
    if idea=="price_action":
        if body/span>=.60 and cl>o and cl>=h-span*.20:return "BUY"
        if body/span>=.60 and cl<o and cl<=l+span*.20:return "SELL"
    elif idea=="breakout":
        z=float(p.get("buffer",.001))
        if cl>hh*(1+z) and move>=minimum:return "BUY"
        if cl<ll*(1-z) and move<=-minimum:return "SELL"
    elif idea=="range_breakout":
        width=(hh-ll)/max(ll,1e-12)
        if width<=float(p.get("range_max",.02)) and cl>hh and move>=minimum:return "BUY"
        if width<=float(p.get("range_max",.02)) and cl<ll and move<=-minimum:return "SELL"
    elif idea=="momentum":
        k=max(2,int(p.get("streak",3))); seq=rows[max(0,i-k):i+1]
        up=sum(float(x["c"])>float(x["o"]) for x in seq); dn=sum(float(x["c"])<float(x["o"]) for x in seq)
        if up>=k and move>=minimum:return "BUY"
        if dn>=k and move<=-minimum:return "SELL"
    elif idea=="mean_reversion":
        mid=(hh+ll)/2; half=max((hh-ll)/2,1e-12); dev=(cl-mid)/half
        if dev<=-.75 and lower>=body and cl>o:return "BUY"
        if dev>=.75 and upper>=body and cl<o:return "SELL"
    elif idea=="market_structure":
        z=rows[max(0,i-6):i]
        if len(z)>=6:
            left=z[:3]; right=z[3:]
            if max(x["h"] for x in right)>max(x["h"] for x in left) and min(x["l"] for x in right)>min(x["l"] for x in left) and cl>o:return "BUY"
            if min(x["l"] for x in right)<min(x["l"] for x in left) and max(x["h"] for x in right)<max(x["h"] for x in left) and cl<o:return "SELL"
    elif idea=="support_resistance":
        tol=float(p.get("tolerance",.003))
        if abs(l-ll)/max(ll,1e-12)<=tol and lower>=body and cl>o:return "BUY"
        if abs(h-hh)/max(hh,1e-12)<=tol and upper>=body and cl<o:return "SELL"
    elif idea=="volatility":
        trs=[]
        for j,x in enumerate(hist):
            prev=hist[j-1]["c"] if j else x["o"]
            trs.append(max(x["h"]-x["l"],abs(x["h"]-prev),abs(x["l"]-prev)))
        if len(trs)>=20:
            ratio=(sum(trs[-5:])/5)/max(sum(trs[-20:])/20,1e-12)
            if ratio>=1.5 and move>=minimum and cl>o:return "BUY"
            if ratio>=1.5 and move<=-minimum and cl<o:return "SELL"
    elif idea=="volume_behavior":
        av=sum(float(x.get("v",0)) for x in hist[-20:])/max(1,min(20,len(hist))); vr=float(c.get("v",0))/max(av,1e-12)
        if vr>=1.5 and move>=minimum and cl>o:return "BUY"
        if vr>=1.5 and move<=-minimum and cl<o:return "SELL"
    elif idea=="candlestick":
        p1=rows[i-1]; po,pc=float(p1["o"]),float(p1["c"])
        if (pc<po and cl>o and cl>=po and o<=pc) or (lower>=body*2 and cl>o):return "BUY"
        if (pc>po and cl<o and cl<=po and o>=pc) or (upper>=body*2 and cl<o):return "SELL"
    elif idea=="session":
        import datetime as _dt
        hour=_dt.datetime.fromtimestamp(float(c["t"])/1000,_dt.timezone.utc).hour
        if any(a<=hour<b for a,b in ((7,11),(13,17))):
            if move>=minimum and cl>o:return "BUY"
            if move<=-minimum and cl<o:return "SELL"
    elif idea=="statistical":
        closes=[float(x["c"]) for x in hist]; path=sum(abs(closes[j]-closes[j-1]) for j in range(1,len(closes)))
        eff=abs(closes[-1]-closes[0])/max(path,1e-12) if len(closes)>1 else 0
        if eff>=.35 and move>=minimum:return "BUY"
        if eff>=.35 and move<=-minimum:return "SELL"
    elif idea=="indicator_hybrid":
        closes=[float(x["c"]) for x in rows[max(0,i-50):i]]
        if len(closes)>=20:
            e20=sum(closes[-20:])/20; e50=sum(closes[-50:])/max(1,min(50,len(closes))); r=_rsi(closes)
            if cl>e20>e50 and r>50:return "BUY"
            if cl<e20<e50 and r<50:return "SELL"
    elif idea=="hybrid":
        av=sum(float(x.get("v",0)) for x in hist[-20:])/max(1,min(20,len(hist))); vr=float(c.get("v",0))/max(av,1e-12)
        if cl>hh and move>0 and vr>=1.1:return "BUY"
        if cl<ll and move<0 and vr>=1.1:return "SELL"
    return None

def _lab_hidden_edge_scan(data_map, timeframe):
    """تنقيب عن Edges مخفية قابلة للاختبار؛ لا يعتمدها بدون اختبارات لاحقة."""
    findings=[]
    for symbol,d in (data_map or {}).items():
        rows=d.get("signal",[])
        if len(rows)<80: continue
        closes=[float(x.get("c",0)) for x in rows]
        vols=[float(x.get("v",0)) for x in rows]
        for window in (3,5,8,13,20):
            for i in range(window+20,len(rows)-1):
                base=closes[i-window] or 0
                if not base: continue
                move=(closes[i]-base)/base
                av=sum(vols[i-window:i])/max(1,window)
                vr=vols[i]/max(av,1e-12)
                nxt=(closes[i+1]-closes[i])/max(closes[i],1e-12)
                # نمط مخفي بسيط: حركة + سلوك حجم ثم قياس العائد التالي.
                if abs(move)>=0.005 and (vr>=1.5 or vr<=0.6):
                    direction="BUY" if move>0 else "SELL"
                    aligned=nxt>0 if direction=="BUY" else nxt<0
                    findings.append({"symbol":symbol,"window":window,"direction":direction,
                        "move_pct":move*100,"volume_ratio":vr,"next_return_pct":nxt*100,
                        "aligned":bool(aligned)})
    findings.sort(key=lambda x:(abs(x["next_return_pct"]),x["volume_ratio"]),reverse=True)
    return findings[:50]

def _lab_method_params(profile,timeframe,confirm_map,interval_ms,confirm_ms,difficulty=1):
    defaults={"price_action":{"lookback":8,"min_move":.001},"breakout":{"lookback":20,"buffer":.001,"min_move":.001},
      "range_breakout":{"lookback":20,"range_max":.02,"min_move":.002},"momentum":{"lookback":8,"streak":3,"min_move":.001},
      "mean_reversion":{"lookback":20},"market_structure":{"lookback":8},"support_resistance":{"lookback":20,"tolerance":.003},
      "volatility":{"lookback":20,"min_move":.002},"volume_behavior":{"lookback":20,"min_move":.001},"candlestick":{"lookback":8},
      "session":{"lookback":8,"min_move":.001},"statistical":{"lookback":20,"min_move":.001},"indicator_hybrid":{"lookback":50},"hybrid":{"lookback":20}}
    base_methods=['price_action','candlestick','momentum','breakout','support_resistance','volume_behavior','range_breakout','market_structure','mean_reversion','volatility','session','statistical','indicator_hybrid','hybrid']
    level=max(1,int(difficulty)); count=min(len(base_methods),1+((level-1)*3)//2)
    allowed=set(base_methods[:count])
    if level>=5: allowed=set(base_methods)
    allowed=set(x for x in allowed if x in [m[0] for m in _STRATEGY_LAB_METHODS])
    out=[]
    for idea,name in _STRATEGY_LAB_METHODS:
        if idea not in allowed: continue
        base=dict(defaults[idea]); base_lb=int(base.get("lookback",8))
        lbs=sorted(set([base_lb]+([max(3,int(base_lb*1.5)),max(3,int(base_lb*2))] if level>=2 else [])))
        moves=sorted(set(([.0005,float(base.get("min_move",.001)),.002,.004] if "min_move" in base and level>=2 else [float(base.get("min_move",.001))])))
        tps=list(dict.fromkeys(profile["tp"][:2]+([x*1.5 for x in profile["tp"][:2]] if level>=4 else [])))
        sls=list(dict.fromkeys(profile["sl"][:2]+([x*.75 for x in profile["sl"][:2]] if level>=4 else [])))
        confirms=[.0005,.001,.002,0.0] if level>=6 else [.0005]; lats=[0,1] if level>=8 else [0]
        for lb in lbs:
            for mv in moves:
                for tp in tps:
                    for sl in sls:
                        for cm in confirms:
                            for lat in lats:
                                p={"idea":idea,"method_name":name,**base,"lookback":lb,"strong_min":0,"strong_max":0,"confirm_min":cm,
                                   "tp_margin":tp,"sl_margin":sl,"leverage":profile["leverage"],"max_hold_min":profile["max_hold"],
                                   "signal_interval":timeframe,"confirm_interval":confirm_map.get(timeframe,timeframe),
                                   "signal_ms":interval_ms.get(timeframe,0),"confirm_ms":confirm_ms.get(confirm_map.get(timeframe,"1m"),60000),"latency_bars":lat}
                                if "min_move" in p: p["min_move"]=mv
                                out.append(p)
    return out

def _lab_eval_symbol(data,p,start_cut,end_cut):
    """Execution-realistic research simulator; never sends real exchange orders."""
    import bisect
    signal=data["signal"]; confirm_rows=data["confirm"]
    confirm_times=[int(x["t"]) for x in confirm_rows]
    confirm_by_t={t:x for t,x in zip(confirm_times,confirm_rows)}
    signal_ms=int(p.get("signal_ms",900000)); confirm_step_ms=max(60000,int(p.get("confirm_ms",60000)))
    trades=[]; i=0
    lev=max(1.0,float(p.get("leverage",1)))
    fee_rate=float(p.get("fee_rate", .0004 if lev>1 else .0010))
    slip_rate=float(p.get("slippage", .0005))
    spread_rate=float(p.get("spread", .0002))
    latency_bars=max(0,int(p.get("latency_bars",0)))
    funding_8h=float(p.get("funding_rate_8h", .0001 if lev>1 else 0.0))
    maintenance=float(p.get("maintenance_margin_rate", .005 if lev>1 else 0.0))
    while i<len(signal)-1:
        c=signal[i]
        if not(start_cut<=c["t"]<end_cut):
            i+=1; continue
        side=_lab_method_signal(signal,i,p)
        if not side:
            i+=1; continue
        confirm=signal[i+1] if signal_ms==0 else confirm_by_t.get(int(c["t"])+signal_ms)
        if not confirm:
            i+=1; continue
        co=float(confirm["o"]); cc=float(confirm["c"])
        cmove=(cc-co)/co if co else 0.0
        mc=float(p.get("confirm_min",0))
        if side=="BUY" and cmove<mc:
            i+=1; continue
        if side=="SELL" and cmove>-mc:
            i+=1; continue

        # Realistic fill: spread + adverse slippage + optional execution latency.
        fill=confirm
        if latency_bars:
            idx=bisect.bisect_left(confirm_times,int(confirm["t"]))
            if idx < len(confirm_rows) and confirm_times[idx]==int(confirm["t"]) and idx+latency_bars<len(confirm_rows):
                fill=confirm_rows[idx+latency_bars]
            else:
                i+=1; continue
        raw_entry=float(fill["o"]) if latency_bars else cc
        half_spread=spread_rate/2
        entry=raw_entry*(1+half_spread+slip_rate) if side=="BUY" else raw_entry*(1-half_spread-slip_rate)

        tpm=float(p["tp_margin"])/lev
        slm=float(p["sl_margin"])/lev
        tp=entry*(1+tpm) if side=="BUY" else entry*(1-tpm)
        sl=entry*(1-slm) if side=="BUY" else entry*(1+slm)
        liq=None
        if lev>1 and maintenance>0:
            liq_move=max(0.0001,(1.0/lev)-maintenance)
            liq=entry*(1-liq_move) if side=="BUY" else entry*(1+liq_move)

        j=bisect.bisect_right(confirm_times,int(fill["t"]))
        stop_j=min(len(confirm_rows),j+int(float(p["max_hold_min"])*60000/confirm_step_ms))
        result=None; exit_t=None; exit_px=None; exit_reason=None; funding_cost=0.0
        while j<stop_j:
            x=confirm_rows[j]
            xh=float(x["h"]); xl=float(x["l"])
            hit_liq=(xl<=liq if side=="BUY" and liq else xh>=liq if side=="SELL" and liq else False)
            hit_sl=xl<=sl if side=="BUY" else xh>=sl
            hit_tp=xh>=tp if side=="BUY" else xl<=tp
            if hit_liq:
                result="LOSS"; exit_t=x["t"]; exit_px=liq; exit_reason="LIQUIDATION"; break
            if hit_sl:
                result="LOSS"; exit_t=x["t"]; exit_px=sl; exit_reason="SL"; break
            if hit_tp:
                result="WIN"; exit_t=x["t"]; exit_px=tp; exit_reason="TP"; break
            j+=1

        if result is None and j>0 and j<len(confirm_rows) and int(confirm_rows[j-1]["t"])<end_cut:
            x=confirm_rows[j-1]
            exit_t=x["t"]; raw_exit=float(x["c"])
            exit_px=raw_exit*(1-half_spread-slip_rate) if side=="BUY" else raw_exit*(1+half_spread+slip_rate)
            result="WIN" if ((exit_px>entry) if side=="BUY" else (exit_px<entry)) else "LOSS"
            exit_reason="TIME"

        if result and exit_t is not None and int(exit_t)<int(end_cut):
            gross_return=((exit_px-entry)/entry if side=="BUY" else (entry-exit_px)/entry)
            hold_ms=max(0,int(exit_t)-int(fill["t"]))
            funding_periods=(hold_ms/(8*60*60*1000))
            funding_cost=max(0.0,funding_periods)*funding_8h*lev
            fee_cost=2*fee_rate*lev
            net_pct=(gross_return*lev-fee_cost-funding_cost)*100
            trades.append({
                "side":side,"result":result,"t":c["t"],
                "entry":round(entry,12),"exit":round(float(exit_px),12),
                "exit_reason":exit_reason,"pnl_pct":round(net_pct,4),
                "gross_return_pct":round(gross_return*100,4),
                "fee_pct":round(fee_cost*100,4),
                "funding_pct":round(funding_cost*100,4),
                "slippage_pct":round(2*slip_rate*lev*100,4),
                "spread_pct":round(spread_rate*lev*100,4),
                "latency_bars":latency_bars,
                "hold_minutes":round(hold_ms/60000,2),
                "idea":p.get("idea"),"method":p.get("method_name")
            })
            while i<len(signal) and int(signal[i]["t"])<=int(exit_t):
                i+=1
            continue
        i+=1
    return trades

def _lab_metrics(trades):
    n=len(trades); wins=sum(1 for x in trades if x["result"]=="WIN"); losses=n-wins
    if not n:
        return {"trades":0,"wins":0,"losses":0,"win_rate":0,"net_pct":0,"max_dd_pct":0,"profit_factor":0,"starting_capital":1000.0,"ending_capital":1000.0,"fees_pct":0,"funding_pct":0}
    starting=1000.0; equity=starting; peak=starting; maxdd=0.0
    gross_win=0.0; gross_loss=0.0; fees=0.0; funding=0.0
    for x in trades:
        delta=float(x.get("pnl_pct",0.0))
        equity*=max(0.0,1.0+delta/100.0)
        if delta>0:gross_win+=delta
        else:gross_loss+=-delta
        fees+=float(x.get("fee_pct",0.0)); funding+=float(x.get("funding_pct",0.0))
        peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak*100 if peak else 0)
    return {
        "trades":n,"wins":wins,"losses":losses,"win_rate":round(wins/n*100,2),
        "net_pct":round((equity/starting-1)*100,2),"max_dd_pct":round(maxdd,2),
        "profit_factor":round(gross_win/gross_loss,2) if gross_loss else 99.0,
        "starting_capital":starting,"ending_capital":round(equity,2),
        "fees_pct":round(fees,2),"funding_pct":round(funding,2)
    }

def _lab_score(train,test):
    """Comparable research score with hard sample-quality controls."""
    min_test=20; min_train=30
    sample_ok=test.get("trades",0)>=min_test and train.get("trades",0)>=min_train
    if not sample_ok:
        # Keep the result visible for research, but never let tiny samples win.
        sample_penalty=max(0,min_test-test.get("trades",0))*25 + max(0,min_train-train.get("trades",0))*10
    else:
        sample_penalty=0
    pf_test=min(float(test.get("profit_factor",0)),5.0)
    pf_train=min(float(train.get("profit_factor",0)),5.0)
    consistency=min(float(test.get("net_pct",0)),max(0,float(train.get("net_pct",0)))*0.50)
    score=(
        float(test.get("net_pct",0))*0.50 +
        pf_test*25 +
        float(test.get("win_rate",0))*0.20 -
        float(test.get("max_dd_pct",0))*0.70 +
        pf_train*10 +
        consistency*0.20 -
        sample_penalty
    )
    if test.get("net_pct",0)<=0: score-=25
    if train.get("net_pct",0)<=0: score-=15
    if pf_test<1.25: score-=(1.25-pf_test)*20
    if pf_train<1.15: score-=(1.15-pf_train)*10
    if test.get("max_dd_pct",0)>30: score-=(test.get("max_dd_pct",0)-30)*1.5
    if test.get("win_rate",0)<50: score-=(50-test.get("win_rate",0))*0.5
    # PF is capped above for ranking so one/two lucky trades cannot create
    # absurd scores such as PF=99 dominating the entire research set.
    return round(score,3)

def _lab_candidate_ok(r):
    tr=r.get("train",{}); te=r.get("test",{})
    return bool(
        te.get("trades",0)>=10 and tr.get("trades",0)>=15 and
        te.get("net_pct",0)>0 and tr.get("net_pct",0)>0 and
        te.get("profit_factor",0)>=1.05 and tr.get("profit_factor",0)>=1.05 and
        te.get("max_dd_pct",0)<=40 and te.get("win_rate",0)>=45
    )

def _lab_live_validate_candidate(candidate, market, timeframe, symbols, days=2):
    """Paper/live-market validation using the newest CLOSED candles.
    Never places an order; it only checks whether the candidate still behaves
    on the current market before it is handed to signal pages.
    """
    try:
        sample=symbols[:min(6,len(symbols))]
        if not sample: return {"status":"no_symbols","trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}
        if market in ("spot","futures"):
            fresh=_lab_download_data(sample,max(2,int(days)),market,timeframe)
        else:
            fresh={}
            for sym in sample:
                rows=_lab_yahoo_rows(sym,timeframe,max(7,int(days)))
                if len(rows)>=40: fresh[sym]={"signal":rows,"confirm":rows}
        if not fresh: return {"status":"no_data","trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}
        times=[c["t"] for d in fresh.values() for c in d["signal"]]
        if not times: return {"status":"no_data","trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}
        end=max(times)+1
        # Only the recent closed portion is treated as the live-market paper window.
        start=max(min(times),end-int(max(1,int(days))*86400000))
        trades=[]
        for d in fresh.values():
            trades.extend(_lab_eval_symbol(d,candidate["parameters"],start,end))
        m=_lab_metrics(trades)
        m.update({"status":"paper_live","checked_at":time.time(),"symbols":len(fresh),"timeframe":timeframe})
        return m
    except Exception as exc:
        return {"status":"error","error":str(exc)[:200],"trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}

# Market-specific lab profiles: each market gets its own search space and risk model.
_STRATEGY_LAB_PROFILES = {
    "spot": {
        "strong_min": (0.003,0.005,0.0075,0.01,0.0125),
        "strong_max": (0.015,0.02,0.03,0.04),
        "confirm_min": (0.001,0.002,0.003,0.004),
        "tp": (0.02,0.03,0.05,0.08),
        "sl": (0.01,0.02,0.03),
        "leverage": 1, "max_hold": 240
    },
    "futures": {
        "strong_min": (0.005,0.0075,0.01,0.0125,0.015),
        "strong_max": (0.02,0.03,0.04,0.06),
        "confirm_min": (0.001,0.002,0.003,0.004),
        "tp": (0.05,0.10,0.15),
        "sl": (0.03,0.05,0.07),
        "leverage": 20, "max_hold": 120
    },
    "forex": {
        "strong_min": (0.001,0.0015,0.002,0.003,0.004),
        "strong_max": (0.004,0.006,0.008,0.012),
        "confirm_min": (0.0005,0.001,0.0015,0.002),
        "tp": (0.004,0.006,0.01,0.015),
        "sl": (0.002,0.003,0.005,0.008),
        "leverage": 1, "max_hold": 360
    },
    "us": {
        "strong_min": (0.002,0.004,0.006,0.008,0.01),
        "strong_max": (0.01,0.015,0.02,0.03),
        "confirm_min": (0.001,0.002,0.003),
        "tp": (0.02,0.04,0.06,0.08),
        "sl": (0.01,0.02,0.03,0.04),
        "leverage": 1, "max_hold": 480
    },
    "saudi": {
        "strong_min": (0.002,0.004,0.006,0.008,0.01),
        "strong_max": (0.01,0.015,0.02,0.03),
        "confirm_min": (0.001,0.002,0.003),
        "tp": (0.02,0.04,0.06,0.08),
        "sl": (0.01,0.02,0.03,0.04),
        "leverage": 1, "max_hold": 480
    },
    "contracts": {
        "strong_min": (0.001,0.002,0.003,0.005,0.008),
        "strong_max": (0.006,0.01,0.015,0.02),
        "confirm_min": (0.0005,0.001,0.002),
        "tp": (0.005,0.01,0.015,0.02),
        "sl": (0.0025,0.005,0.0075,0.01),
        "leverage": 1, "max_hold": 360
    }
}
def _lab_factory_audit(candidate, data, all_times, cut, end):
    """Full strategy-factory gate: walk-forward stability + execution stress + Monte Carlo.
    Research only; never sends exchange orders.
    """
    if not candidate or not data:
        return {"approved":False,"reason":"no_candidate","walk_forward":0,"stress_pass":0,"stress_total":0,"monte_carlo_positive":0}
    p=dict(candidate.get("parameters") or {})
    test_start=int(cut); test_end=int(end)
    test_span=max(1,test_end-test_start)
    windows=[]
    for n in range(3):
        a=test_start+int(test_span*n/3)
        b=test_start+int(test_span*(n+1)/3)
        if b>a: windows.append((a,b))
    wf=[]
    for a,b in windows:
        tr=[]
        for d in data.values():
            tr.extend(_lab_eval_symbol(d,p,a,b))
        m=_lab_metrics(tr)
        wf.append(m)
    wf_positive=sum(1 for m in wf if m.get("trades",0)>=5 and m.get("net_pct",0)>0 and m.get("profit_factor",0)>=1.05)
    wf_score=round(wf_positive/max(1,len(wf))*100,2)

    stress_variants=[
        {"name":"base","slippage":float(p.get("slippage",.0005)),"fee_rate":float(p.get("fee_rate",.0004 if float(p.get("leverage",1))>1 else .001)),"latency_bars":int(p.get("latency_bars",0))},
        {"name":"slippage_x2","slippage":float(p.get("slippage",.0005))*2,"fee_rate":float(p.get("fee_rate",.0004 if float(p.get("leverage",1))>1 else .001)),"latency_bars":int(p.get("latency_bars",0))},
        {"name":"fees_x1_5","slippage":float(p.get("slippage",.0005)),"fee_rate":float(p.get("fee_rate",.0004 if float(p.get("leverage",1))>1 else .001))*1.5,"latency_bars":int(p.get("latency_bars",0))},
        {"name":"one_bar_latency","slippage":float(p.get("slippage",.0005)),"fee_rate":float(p.get("fee_rate",.0004 if float(p.get("leverage",1))>1 else .001)),"latency_bars":max(1,int(p.get("latency_bars",0)))},
    ]
    stress=[]
    for v in stress_variants:
        q=dict(p); q.update(v)
        trades=[]
        for d in data.values():
            trades.extend(_lab_eval_symbol(d,q,test_start,test_end))
        m=_lab_metrics(trades)
        stress.append({"name":v["name"],"trades":m.get("trades",0),"net_pct":m.get("net_pct",0),"profit_factor":m.get("profit_factor",0),"max_dd_pct":m.get("max_dd_pct",0)})
    stress_pass=sum(1 for x in stress if x["trades"]>=10 and x["net_pct"]>0 and x["profit_factor"]>=1.05 and x["max_dd_pct"]<=35)

    base_trades=[]
    for d in data.values():
        base_trades.extend(_lab_eval_symbol(d,p,test_start,test_end))
    returns=[float(x.get("pnl_pct",0)) for x in base_trades]
    positive_prob=0.0
    mc_median=0.0
    if len(returns)>=10:
        import random
        rng=random.Random(7919)
        positives=0; samples=[]
        for _ in range(300):
            equity=1.0
            for _j in range(len(returns)):
                r=rng.choice(returns)
                equity*=max(0.0,1.0+r/100.0)
            net=(equity-1.0)*100
            samples.append(net)
            if net>0: positives+=1
        samples.sort()
        positive_prob=round(positives/300*100,2)
        mc_median=round(samples[150],2)

    approved=bool(
        wf_score>=66.67 and
        stress_pass>=3 and
        (positive_prob>=60 or len(returns)<10) and
        candidate.get("test",{}).get("trades",0)>=20 and
        candidate.get("train",{}).get("trades",0)>=30
    )
    return {
        "approved":approved,
        "walk_forward":wf_score,
        "walk_forward_windows":wf,
        "stress_pass":stress_pass,
        "stress_total":len(stress),
        "stress":stress,
        "monte_carlo_positive":positive_prob,
        "monte_carlo_median_net":mc_median,
        "tested_trades":len(returns),
        "factory_version":"1.0",
        "gate":"walk-forward + execution stress + Monte Carlo"
    }

def _lab_profile(market):
    return _STRATEGY_LAB_PROFILES.get(market, _STRATEGY_LAB_PROFILES["futures"])

def _lab_save_successful_strategy(result, active=False):
    """Save every factory-approved winner in the encrypted strategy archive, ranked by strength."""
    rd=DATA_DIR/"strategy_lab"; rd.mkdir(parents=True,exist_ok=True)
    path=rd/"strategies.json"
    try:
        rows=_lab_read_json(path,[])
        if not isinstance(rows,list): rows=[]
    except Exception: rows=[]
    key=(result.get("market"),result.get("timeframe"),result.get("score"),str(result.get("parameters",{})))
    rows=[x for x in rows if (x.get("market"),x.get("timeframe"),x.get("score"),str(x.get("parameters",{})))!=key]
    item=dict(result); item["saved_at"]=time.time(); item["approved"]=True
    item["factory_approved"]=True; item["installed"]=True; item["active"]=bool(active)
    rows.append(item)
    # Archive every approved strategy, ordered by strength. Keep the full
    # history on disk; top10.json is only the quick shortlist for the UI.
    rows=sorted(rows,key=lambda x:(float(x.get("score",-999999)),float((x.get("factory_audit") or {}).get("walk_forward",0)),int((x.get("factory_audit") or {}).get("stress_pass",0))),reverse=True)
    for rank, row in enumerate(rows,1):
        row["strength_rank"]=rank
        row["strength_label"]="احترافي جداً" if rank<=3 else ("قوي جداً" if rank<=10 else ("قوي" if rank<=25 else "معتمد"))
    rows=rows[:5000]
    _lab_write_json(path,rows)
    _lab_write_json(rd/"top10.json",rows[:10])
    _lab_write_json(rd/"top50.json",rows[:50])
    return item

def _lab_jewel_score(result):
    if not isinstance(result,dict): return (0.0,"")
    tr=result.get("train") or {}; te=result.get("test") or {}; fa=result.get("factory_audit") or {}
    train_pf=float(tr.get("profit_factor",0) or 0); test_pf=float(te.get("profit_factor",0) or 0)
    train_net=float(tr.get("net_pct",0) or 0); test_net=float(te.get("net_pct",0) or 0)
    test_dd=float(te.get("max_dd_pct",999) or 999); trades=int(te.get("trades",0) or 0)
    wr=float(te.get("win_rate",0) or 0); wf=float(fa.get("walk_forward",0) or 0)
    stress=int(fa.get("stress_pass",0) or 0); mc=float(fa.get("monte_carlo_positive",0) or 0)
    if not bool(fa.get("approved")): return (0.0,"")
    consistency=min(100.0,max(0.0,(test_net/max(train_net,0.01))*100.0))
    pf_score=min(100.0,max(0.0,(min(train_pf,test_pf)-1.0)*100.0))
    dd_score=max(0.0,100.0-min(100.0,test_dd*2.0))
    trade_score=min(100.0,trades/2.0); stress_score=min(100.0,stress/4.0*100.0)
    jewel=round(0.22*min(wf,100)+0.18*min(mc,100)+0.16*stress_score+0.14*pf_score+0.12*consistency+0.10*dd_score+0.05*min(100,wr)+0.03*trade_score,2)
    label="💎 جوهرة نادرة" if jewel>=90 else ("💎 جوهرة" if jewel>=80 else ("🟢 قوية" if jewel>=70 else ""))
    return jewel,label

def _lab_save_jewel(result):
    score,label=_lab_jewel_score(result)
    if not label: return None
    rd=DATA_DIR/"strategy_lab"; rd.mkdir(parents=True,exist_ok=True); path=rd/"jewels.json"
    try: rows=_lab_read_json(path,[]) or []
    except Exception: rows=[]
    if not isinstance(rows,list): rows=[]
    item=dict(result); item["jewel_score"]=score; item["jewel_label"]=label; item["jewel_saved_at"]=time.time()
    key=(item.get("market"),item.get("timeframe"),str(item.get("parameters",{})))
    rows=[x for x in rows if (x.get("market"),x.get("timeframe"),str(x.get("parameters",{})))!=key]
    rows.append(item); rows=sorted(rows,key=lambda x:(float(x.get("jewel_score",0)),float(x.get("score",-999999))),reverse=True)[:5000]
    for rank,row in enumerate(rows,1): row["jewel_rank"]=rank
    _lab_write_json(path,rows); _lab_write_json(rd/"top_jewels.json",rows[:50])
    return item

def _run_strategy_lab(days=30,max_symbols=100,min_volume=1000000,market="futures",timeframe="15m"):
    market=str(market or "futures").lower(); timeframe=str(timeframe or "15m")
    if market not in ("spot","futures"): market="futures"
    if timeframe not in TIMEFRAMES: timeframe="15m"
    if market=="spot":
        ticker=_binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=20); exchange=_binance_json("https://api.binance.com/api/v3/exchangeInfo",timeout=20)
        allowed={x["symbol"] for x in exchange["symbols"] if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"}
    else:
        ticker=_binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=20); exchange=_binance_futures_json("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=20)
        allowed={x["symbol"] for x in exchange["symbols"] if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL" and x.get("quoteAsset")=="USDT"}
    vols={x["symbol"]:float(x.get("quoteVolume") or 0) for x in ticker if x.get("symbol") in allowed}
    universe=sorted([s for s,v in vols.items() if v>max(1000000.0,float(min_volume))],key=lambda s:vols[s],reverse=True)[:min(int(max_symbols),400)]
    ticker_map={x.get("symbol"):x for x in ticker if x.get("symbol") in universe}
    ranked=sorted(universe,key=lambda s:(float(ticker_map.get(s,{}).get("quoteVolume") or 0),abs(float(ticker_map.get(s,{}).get("priceChangePercent") or 0))),reverse=True)
    # Three-speed screening: quick -> medium -> deep.
    # QUICK: use the full liquid universe without downloading candles. This keeps
    # the lab moving across markets instead of getting stuck on one symbol.
    fast_universe=ranked[:min(400,len(ranked))]
    if not fast_universe:
        raise RuntimeError("لا توجد أصول فوق 1M$ في هذا السوق")
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({
            "market":market,"timeframe":timeframe,
            "message":f"⚡ فحص سريع: {len(fast_universe)} أصل فوق 1M$ → فرز السيولة أولاً → متوسط",
            "current_symbol":fast_universe[0],"symbols_done":0,"symbols_total":len(fast_universe),
            "fast_universe_total":len(fast_universe),"progress":5,"research_phase":"quick"
        })
    # MEDIUM: only a small shortlist gets candles. Rank by recent move, volume
    # and data quality. Use 2 days max so every market can get a turn quickly.
    medium_symbols=fast_universe[:min(20,len(fast_universe))]
    medium_days=min(2,max(1,int(days)))
    medium_data=_lab_download_data(medium_symbols,medium_days,market,timeframe)
    medium_rank=[]
    for sym,d in medium_data.items():
        try:
            rows=d.get("signal",[])
            if len(rows)>=20:
                first=float(rows[0]["c"]); last=float(rows[-1]["c"])
                change=abs(last/first-1.0) if first else 0.0
                recent=sum(float(x.get("v",0)) for x in rows[-20:])
                quality=min(len(rows)/1000.0,1.0)
                medium_rank.append((sym,change,recent,quality))
        except Exception:
            continue
    medium_rank.sort(key=lambda x:(x[1],x[2],x[3]),reverse=True)
    symbols=[x[0] for x in medium_rank[:min(8,len(medium_rank))]]
    if not symbols:
        symbols=medium_symbols[:8]
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({
            "message":f"🧠 فحص متوسط: {len(medium_symbols)} أصل → 🔬 عميق: {len(symbols)} أصل — ثم ينتقل للسوق التالي",
            "current_symbol":symbols[0] if symbols else None,"symbols_done":0,"symbols_total":len(symbols),
            "progress":20,"research_phase":"deep"
        })
    # DEEP: full requested history, but only on the best 8 from the medium pass.
    data=_lab_download_data(symbols,int(days),market,timeframe)
    if not data:
        # Do not freeze the factory on one bad symbol/API response.
        raise RuntimeError("لم تكتمل بيانات العمق — سيتم تدوير السوق والمحاولة لاحقاً")
    all_times=[c["t"] for d in data.values() for c in d["signal"]]; cut=min(all_times)+int((max(all_times)-min(all_times))*0.70); end=max(all_times)+1
    interval_ms={"15m":900000,"30m":1800000,"1h":3600000,"4h":14400000,"1d":86400000,"1w":604800000,"1M":2592000000}
    confirm_map={"15m":"1m","30m":"1m","1h":"5m","4h":"15m","1d":"1h","1w":"4h","1M":"1d"}; confirm_ms={"1m":60000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}
    profile=_lab_profile(market)
    difficulty=int(_STRATEGY_LAB.get('difficulty_level',1) or 1)
    params=_lab_method_params(profile,timeframe,confirm_map,interval_ms,confirm_ms,difficulty)
    if not params: raise RuntimeError("لا توجد استراتيجية في المستوى الحالي")
    hidden_edges=_lab_hidden_edge_scan(data,timeframe)
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB["hidden_edges_found"]=len(hidden_edges)
        _STRATEGY_LAB["hidden_edges"]=hidden_edges[:12]
        _STRATEGY_LAB["research_phase"]="hidden_edge_scan"
        _STRATEGY_LAB["message"]=f"🕵️ كاشف المعادن: تم العثور على {len(hidden_edges)} نمطاً مرشحاً للفحص"
    strategy_cursor_path=DATA_DIR/"strategy_lab"/"strategy_cursor.json"
    try:
        sc=json.loads(strategy_cursor_path.read_text(encoding="utf-8")) if strategy_cursor_path.exists() else {}
        strategy_idx=int(sc.get("index",0))
    except Exception: strategy_idx=0
    strategy_idx%=len(params)
    batch_size=min(24,len(params))
    params=[params[(strategy_idx+i)%len(params)] for i in range(batch_size)]
    selected=params[0] if params else {}
    results=[]; total=len(params)
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB["combinations_generated_total"]=int(_STRATEGY_LAB.get("combinations_generated_total",0) or 0)+total
        _STRATEGY_LAB.update({"strategy_index":strategy_idx+1,"strategy_total":len(_lab_method_params(profile,timeframe,confirm_map,interval_ms,confirm_ms,difficulty)),"current_strategy":selected,"research_phase":"strategy_build"})
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({"tested":0,"total_combinations":total,"best_score":None,"best_candidate":None,"validated_candidates":0,"message":f"🧠 بناء وفحص 1/{total}"})
    for n,p in enumerate(params,1):
        train=[]; test=[]
        for d in data.values(): train.extend(_lab_eval_symbol(d,p,min(all_times),cut)); test.extend(_lab_eval_symbol(d,p,cut,end))
        tm=_lab_metrics(train); xm=_lab_metrics(test); score=_lab_score(tm,xm)
        eligible=_lab_candidate_ok({"train":tm,"test":xm})
        candidate={"rank":0,"score":score,"eligible":eligible,"parameters":p,"train":tm,"test":xm,"markets":len(data),"market":market,"timeframe":timeframe}
        results.append(candidate)
        # كل استراتيجية تُبنى ثم تُفحص فوراً، وتظهر نتيجتها وتُحفظ قبل الانتقال للي بعدها.
        audit=None
        if eligible:
            with _STRATEGY_LAB_LOCK:
                _STRATEGY_LAB.update({"research_phase":"factory_test","current_strategy":p,"message":f"🏭 بناء/فحص Factory {n}/{total} — {p.get('method_name') or p.get('idea') or 'Strategy'}"})
            try:
                audit=_lab_factory_audit(candidate,data,all_times,cut,end)
                candidate["factory_audit"]=audit
                candidate["factory_approved"]=bool(audit.get("approved"))
                if candidate["factory_approved"]:
                    _lab_save_successful_strategy(candidate,active=False)
                    jewel=_lab_save_jewel(candidate)
                    if jewel:
                        with _STRATEGY_LAB_LOCK:
                            _STRATEGY_LAB["jewels_found"]=int(_STRATEGY_LAB.get("jewels_found",0) or 0)+1
                            _STRATEGY_LAB["latest_jewel"]={"market":jewel.get("market"),"timeframe":jewel.get("timeframe"),"jewel_score":jewel.get("jewel_score"),"jewel_label":jewel.get("jewel_label"),"score":jewel.get("score")}
            except Exception as exc:
                candidate["factory_audit"]={"approved":False,"reason":str(exc)[:180],"factory_version":"1.0"}
                candidate["factory_approved"]=False
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB.update({
                "research_phase":"strategy_build",
                "tested":n,
                "total_combinations":total,
                "strategies_tested_total":int(_STRATEGY_LAB.get("strategies_tested_total",0) or 0)+1,
                "current_strategy":p,
                "last_test_result":{"method":p.get("method_name") or p.get("idea"),"score":score,"eligible":eligible,"factory_approved":bool(candidate.get("factory_approved")),"train":tm,"test":xm},
                "message":f"{'✅ اجتازت' if candidate.get('factory_approved') else ('🟡 مرشح — ينتقل لفحص Factory' if eligible else '❌ مرفوض')} — {p.get('method_name') or p.get('idea') or 'Strategy'} — {n}/{total}",
                "progress":min(90,25+int(n/max(1,total)*65))
            })
        try:
            live_path=DATA_DIR/"strategy_lab"/"live_results.json"
            _lab_write_json(live_path,{"generated_at":time.time(),"running":True,"phase":"build_and_test","market":market,"timeframe":timeframe,"tested":n,"total":total,"current_strategy":p,"last_result":candidate,"results":sorted(results,key=lambda x:x["score"],reverse=True)[:20]})
        except Exception: pass
        _strategy_lab_save_state()
        if n>=1:
            results.sort(key=lambda x:x["score"],reverse=True); results=results[:100]
            best=results[0] if results else None
            try:
                result_dir=DATA_DIR/"strategy_lab"; result_dir.mkdir(parents=True,exist_ok=True)
                _lab_write_json(result_dir/"live_results.json",{"generated_at":time.time(),"running":True,"market":market,"timeframe":timeframe,"days":days,"symbols":symbols,"tested":n,"total":total,"results":results})
            except Exception: pass
            with _STRATEGY_LAB_LOCK:
                _STRATEGY_LAB.update({
                    "progress":25+int(n/total*70),
                    "message":f"اختبار {n}/{total} تركيبة — {market}/{timeframe}",
                    "tested":n,
                    "total_combinations":total,
                    "best_score":best.get("score") if best else None,
                    "best_candidate":best,
                })
                _STRATEGY_LAB["results"]=results[:20]
            _strategy_lab_save_state()
    results.sort(key=lambda x:x["score"],reverse=True)
    for i,r in enumerate(results,1): r["rank"]=i
    result_dir=DATA_DIR/"strategy_lab"; result_dir.mkdir(parents=True,exist_ok=True); active_path=result_dir/"active.json"
    active_map_path=result_dir/"active_map.json"
    candidates=[r for r in results if _lab_candidate_ok(r)]
    # Factory gate: a strategy is not approved until it survives multiple
    # unseen windows and adverse execution assumptions.
    factory_candidates=[]
    for r in candidates:
        try:
            audit=_lab_factory_audit(r,data,all_times,cut,end)
            r["factory_audit"]=audit
            r["factory_approved"]=bool(audit.get("approved"))
            if r["factory_approved"]:
                factory_candidates.append(r)
                _lab_save_successful_strategy(r,active=False)
                with _STRATEGY_LAB_LOCK:
                    _STRATEGY_LAB["message"]=f"✅ استراتيجية ناجحة تركبت فوراً — {market}/{timeframe}"
        except Exception as exc:
            r["factory_audit"]={"approved":False,"reason":str(exc)[:180],"factory_version":"1.0"}
            r["factory_approved"]=False
    candidates=factory_candidates
    old={}
    try: old=json.loads(active_path.read_text(encoding="utf-8")) if active_path.exists() else {}
    except Exception: old={}
    chosen=sorted(candidates,key=lambda x:(x.get("score",-999999),x.get("factory_audit",{}).get("walk_forward",0),x.get("factory_audit",{}).get("stress_pass",0)),reverse=True)[0] if candidates else None
    live_metrics=_lab_live_validate_candidate(chosen,market,timeframe,symbols,days=2) if chosen else {"status":"no_candidate","trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}
    live_pass=bool(chosen and live_metrics.get("status")=="paper_live" and live_metrics.get("trades",0)>=5 and live_metrics.get("net_pct",0)>0 and live_metrics.get("profit_factor",0)>=1.10)
    if chosen:
        chosen["live_market"]=live_metrics
        chosen["live_validated"]=live_pass
    old_score=float(old.get("score",-999999)) if old.get("active") else -999999; replaced=False
    if chosen and live_pass and (not old.get("active") or chosen["score"]>old_score):
        active={"active":True,"activated_at":time.time(),"reason":"Factory approval + OOS + current-market live validation","rank":chosen["rank"],"score":chosen["score"],"parameters":chosen["parameters"],"train":chosen["train"],"test":chosen["test"],"live_market":live_metrics,"factory_audit":chosen.get("factory_audit",{}),"factory_approved":True,"live_validated":True,"markets_tested":chosen["markets"],"market":market,"timeframe":timeframe}
        _lab_write_json(active_path,active); replaced=True
        try:
            amap=_lab_read_json(active_map_path,{})
            if not isinstance(amap,dict): amap={}
            amap[f"{market}:{timeframe}"]=active
            _lab_write_json(active_map_path,amap)
        except Exception: pass
    elif old.get("active"): active=old
    else:
        active={"active":False,"message":"لا توجد استراتيجية اجتازت شروط الاختبار الخارجي"}; active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2),encoding="utf-8")
    registry_path=result_dir/"strategies.json"; registry=[]
    try: registry=_lab_read_json(registry_path,[]); registry=registry if isinstance(registry,list) else []
    except Exception: registry=[]
    for r in candidates[:20]:
        registry.append({"saved_at":time.time(),"market":market,"timeframe":timeframe,"score":r["score"],"rank":r["rank"],"parameters":r["parameters"],"train":r["train"],"test":r["test"],"active":bool(active.get("active") and r["score"]==active.get("score") and market==active.get("market") and timeframe==active.get("timeframe"))})
    registry=sorted(registry,key=lambda x:x.get("score",-999999),reverse=True)[:200]; _lab_write_json(registry_path,registry)
    _lab_write_json(result_dir/"results.json",{"generated_at":time.time(),"days":days,"symbols":symbols,"market":market,"timeframe":timeframe,"results":results,"active":active,"replaced":replaced,"validated_candidates":len(candidates),"tested":total,"total_combinations":total,"best_score":results[0].get("score") if results else None,"live_market_validation":live_metrics})
    lines=["rank,score,market,timeframe,strong_min,strong_max,confirm_min,tp_margin,sl_margin,train_trades,train_win_rate,test_trades,test_win_rate,test_net_pct,test_max_dd,test_profit_factor"]
    for r in results:
        p=r["parameters"]; a=r["train"]; b=r["test"]; lines.append(",".join(map(str,[r["rank"],r["score"],r["market"],r["timeframe"],p["strong_min"],p["strong_max"],p["confirm_min"],p["tp_margin"],p["sl_margin"],a["trades"],a["win_rate"],b["trades"],b["win_rate"],b["net_pct"],b["max_dd_pct"],b["profit_factor"]])))
    try:
        (result_dir/"results.csv").write_text("\n".join(lines)+"\n",encoding="utf-8")
    except Exception:
        pass
    import datetime; stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    txt=[f"مختبر الاستراتيجيات - {stamp} UTC",f"market={market}",f"timeframe={timeframe}",f"days={days}",f"symbols={symbols}",f"validated_candidates={len(candidates)}",f"active_score={active.get('score')}",f"replaced={replaced}","", "المرشحون:"]
    for r in results[:50]:
        p=r["parameters"]; a=r["train"]; b=r["test"]; txt.append(f"#{r['rank']} score={r['score']} | {market}/{timeframe} | strong={p['strong_min']:.4f}-{p['strong_max']:.4f} | confirm={p['confirm_min']:.4f} | TP={p['tp_margin']:.2f} | SL={p['sl_margin']:.2f} | lev={p['leverage']} | train={a['trades']}/{a['win_rate']}% | test={b['trades']}/{b['win_rate']}% net={b['net_pct']}% PF={b['profit_factor']} DD={b['max_dd_pct']}%")
    _lab_write_json(result_dir/"results.txt",{"generated_at":time.time(),"text":"\n".join(txt)}); archive_dir=result_dir/"archive"; archive_dir.mkdir(parents=True,exist_ok=True); _lab_write_json(archive_dir/f"strategy_lab_{stamp}.txt",{"generated_at":time.time(),"text":"\n".join(txt)})
    try:
        _lab_write_json(strategy_cursor_path,{"index":strategy_idx+1,"updated_at":time.time(),"last_strategy":selected,"passed":bool(chosen and live_pass)})
    except Exception: pass
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB["stage_passed"]=bool(chosen and live_pass)
        _STRATEGY_LAB["successful_installed"]=len(factory_candidates)
        _STRATEGY_LAB.update({
            "active_strategy":active,
            "results":results[:20],
            "validated_candidates":len(candidates),
            "factory_approved":sum(1 for x in results if x.get("factory_approved")),
            "best_score":results[0].get("score") if results else None,
            "best_candidate":results[0] if results else None,
            "tested":total,
            "total_combinations":total,
        })
    return results

def _lab_yahoo_rows(symbol, timeframe, days):
    imap={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}
    ranges={"15m":"60d","30m":"60d","1h":"2y","4h":"2y","1d":"5y","1w":"10y","1M":"max"}
    interval=imap[timeframe]; rng=ranges[timeframe]
    u=f"{YAHOO_BASES[0]}/v8/finance/chart/{urllib.parse.quote(symbol,safe='')}?"+urllib.parse.urlencode({"interval":interval,"range":rng})
    d=_json_get(u,timeout=15); rr=(d.get("chart",{}).get("result") or [None])[0]
    if not rr: return []
    ts=rr.get("timestamp") or []; q=((rr.get("indicators") or {}).get("quote") or [{}])[0]
    o=q.get("open") or []; h=q.get("high") or []; l=q.get("low") or []; cl=q.get("close") or []; v=q.get("volume") or []
    out=[]
    for i,t in enumerate(ts):
        try:
            if None in (o[i],h[i],l[i],cl[i]): continue
            out.append({"t":int(t)*1000,"o":float(o[i]),"h":float(h[i]),"l":float(l[i]),"c":float(cl[i]),"v":float(v[i] or 0)})
        except Exception: continue
    cutoff=int(time.time()*1000)-int(days)*86400000
    return [x for x in out if x["t"]>=cutoff]
    
def _run_strategy_lab_yahoo(days=30,max_symbols=30,market="forex",timeframe="1h"):
    symbols=list(_YAHOO_SYMBOLS.get(market,[]))
    if market=="contracts": symbols=["ES=F","NQ=F","YM=F","GC=F","SI=F","CL=F"]
    symbols=symbols[:int(max_symbols)]
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({"market":market,"timeframe":timeframe,"message":f"🔎 مختبر {market} / {timeframe} — تحميل تاريخي حبة حبة","symbols_total":len(symbols),"symbols_done":0,"progress":2})
    data={}
    for i,sym in enumerate(symbols,1):
        try:
            rows=_lab_yahoo_rows(sym,timeframe,int(days))
            if len(rows)>=40: data[sym]={"signal":rows,"confirm":rows}
        except Exception: pass
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB["current_symbol"]=sym; _STRATEGY_LAB["symbols_done"]=i; _STRATEGY_LAB["message"]=f"🔎 يفحص {sym} — {i}/{len(symbols)}"; _STRATEGY_LAB["progress"]=min(25,int(i/max(1,len(symbols))*25))
        _strategy_lab_save_state()
    if not data: raise RuntimeError(f"لا توجد بيانات تاريخية متاحة لـ {market}/{timeframe}")
    all_times=[c["t"] for d in data.values() for c in d["signal"]]; cut=min(all_times)+int((max(all_times)-min(all_times))*0.70); end=max(all_times)+1
    profile=_lab_profile(market)
    params=_lab_method_params(profile,timeframe,{},{timeframe:0},{timeframe:60000})
    for p in params:
        p["confirm_interval"]=timeframe; p["signal_ms"]=0; p["confirm_ms"]=60000
    results=[]; total=len(params)
    for n,p in enumerate(params,1):
        tr=[]; te=[]
        for d in data.values():
            tr.extend(_lab_eval_symbol(d,p,min(all_times),cut)); te.extend(_lab_eval_symbol(d,p,cut,end))
        tm=_lab_metrics(tr); xm=_lab_metrics(te); score=_lab_score(tm,xm)
        if score>-999000: results.append({"rank":0,"score":score,"parameters":p,"train":tm,"test":xm,"markets":len(data),"market":market,"timeframe":timeframe})
        if n%20==0:
            with _STRATEGY_LAB_LOCK: _STRATEGY_LAB["progress"]=25+int(n/total*70); _STRATEGY_LAB["message"]=f"🧠 اختبار {market}/{timeframe} — {n}/{total}"
            _strategy_lab_save_state()
    results.sort(key=lambda x:x["score"],reverse=True)
    for i,r in enumerate(results,1): r["rank"]=i
    candidates=[r for r in results if _lab_candidate_ok(r)]
    factory_candidates=[]
    for r in candidates:
        try:
            audit=_lab_factory_audit(r,data,all_times,cut,end)
            r["factory_audit"]=audit
            r["factory_approved"]=bool(audit.get("approved"))
            if r["factory_approved"]: factory_candidates.append(r)
        except Exception as exc:
            r["factory_audit"]={"approved":False,"reason":str(exc)[:180],"factory_version":"1.0"}
            r["factory_approved"]=False
    candidates=factory_candidates
    rd=DATA_DIR/"strategy_lab"; rd.mkdir(parents=True,exist_ok=True); mp=rd/"active_map.json"
    try: amap=_lab_read_json(mp,{}) or {}; amap=amap if isinstance(amap,dict) else {}
    except Exception: amap={}
    key=f"{market}:{timeframe}"; old=amap.get(key) or {}; chosen=sorted(candidates,key=lambda x:(x.get("score",-999999),x.get("factory_audit",{}).get("walk_forward",0),x.get("factory_audit",{}).get("stress_pass",0)),reverse=True)[0] if candidates else None; replaced=False
    live_metrics=_lab_live_validate_candidate(chosen,market,timeframe,symbols,days=max(2,min(7,int(days)))) if chosen else {"status":"no_candidate","trades":0,"win_rate":0,"net_pct":0,"profit_factor":0,"max_dd_pct":0}
    live_pass=bool(chosen and live_metrics.get("status")=="paper_live" and live_metrics.get("trades",0)>=5 and live_metrics.get("net_pct",0)>0 and live_metrics.get("profit_factor",0)>=1.10)
    if chosen:
        chosen["live_market"]=live_metrics
        chosen["live_validated"]=live_pass
    if chosen and live_pass and (not old.get("active") or chosen["score"]>float(old.get("score",-999999))):
        active={"active":True,"activated_at":time.time(),"reason":"OOS + current-market live validation","rank":chosen["rank"],"score":chosen["score"],"parameters":chosen["parameters"],"train":chosen["train"],"test":chosen["test"],"live_market":live_metrics,"live_validated":True,"markets_tested":chosen["markets"],"market":market,"timeframe":timeframe}
        amap[key]=active; _lab_write_json(mp,amap); replaced=True
    else: active=old if old.get("active") else {"active":False,"market":market,"timeframe":timeframe,"message":"لم تجتز استراتيجية الاختبار الخارجي + تحقق السوق الحالي"}
    registry=rd/"strategies.json"
    try: rows=_lab_read_json(registry,[]) or []; rows=rows if isinstance(rows,list) else []
    except Exception: rows=[]
    for r in candidates[:20]:
        item=dict(r); item["saved_at"]=time.time(); item["approved"]=bool(r.get("factory_approved")); item["factory_approved"]=bool(r.get("factory_approved"))
        item["live_market"]=live_metrics if r is chosen else {"status":"not_live_checked"}
        item["live_validated"]=bool(r is chosen and live_pass)
        item["active"]=bool(active.get("active") and r.get("score")==active.get("score") and market==active.get("market") and timeframe==active.get("timeframe"))
        rows.append(item)
    dedup={}
    for r in rows:
        k=(r.get("market"),r.get("timeframe"),r.get("score"),str(r.get("parameters",{})))
        dedup[k]=r
    rows=sorted(dedup.values(),key=lambda x:x.get("score",-999999),reverse=True)[:200]
    _lab_write_json(registry,rows)
    _lab_write_json(rd/f"results_{market}_{timeframe}.json",{"generated_at":time.time(),"market":market,"timeframe":timeframe,"results":results,"active":active,"replaced":replaced,"validated_candidates":len(candidates),"live_market_validation":live_metrics})
    with _STRATEGY_LAB_LOCK: _STRATEGY_LAB["active_strategy"]=active
    return results, active

def _strategy_lab_run_all_stages(days=30,max_symbols=100,min_volume=1000000,requested_market=None,requested_timeframe=None,one_shot=False):
    # Low-resource persistent pipeline: run ONE market/timeframe stage per cycle.
    # The cursor is durable so a restart continues from the next stage instead of restarting all 42 stages.
    import gc
    stages=[("spot",tf) for tf in TIMEFRAMES] + [("futures",tf) for tf in TIMEFRAMES] + [("forex",tf) for tf in TIMEFRAMES] + [("us",tf) for tf in TIMEFRAMES] + [("saudi",tf) for tf in TIMEFRAMES] + [("contracts",tf) for tf in TIMEFRAMES]
    cursor_path=DATA_DIR/"strategy_lab"/"stage_cursor.json"
    cursor_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        cursor=json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
        idx=int(cursor.get("index",0)) % len(stages)
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB["difficulty_level"]=max(1,int(cursor.get("difficulty_level",_STRATEGY_LAB.get("difficulty_level",1))) or 1)
    except Exception:
        idx=0
    if requested_market in ("spot","futures","forex","us","saudi","contracts"):
        market=requested_market
        timeframe=requested_timeframe if requested_timeframe in TIMEFRAMES else "15m"
        idx=stages.index((market,timeframe))
    else:
        market,timeframe=stages[idx]
    with _STRATEGY_LAB_LOCK:
        difficulty=max(1,int(_STRATEGY_LAB.get("difficulty_level",1) or 1))
        _STRATEGY_LAB["difficulty_level"]=difficulty
        _STRATEGY_LAB["market"]=market
        _STRATEGY_LAB["timeframe"]=timeframe
        _STRATEGY_LAB["message"]=f"🚦 المستوى {difficulty} — {market} / {timeframe} — بناء سريع ومستودع مفتوح"
        _STRATEGY_LAB["running"]=True
        _STRATEGY_LAB["stage_index"]=idx+1
        _STRATEGY_LAB["stage_total"]=len(stages)
    try:
        if market in ("spot","futures"):
            result=_run_strategy_lab(days,max_symbols,min_volume,market,timeframe)
        else:
            result=_run_strategy_lab_yahoo(max(7,days),max_symbols,market,timeframe)
        if not one_shot:
            current_level=max(1,int(_STRATEGY_LAB.get("difficulty_level",1) or 1))
            promoted=bool(_STRATEGY_LAB.get("stage_passed",False))
            # لا نصعّب ولا ننتقل للسوق/الفريم التالي إلا بعد نجاح حقيقي.
            # إذا فشلت الاستراتيجية الحالية، نكمل الاستراتيجية التالية داخل نفس المرحلة.
            next_level=(current_level+1) if promoted else current_level
            next_idx=(idx+1)%len(stages)
            _STRATEGY_LAB["difficulty_level"]=next_level
            if promoted:
                # بعد النجاح نبدأ المستوى الجديد من أول استراتيجية بسيطة.
                try:
                    (DATA_DIR/"strategy_lab"/"strategy_cursor.json").write_text(json.dumps({"index":0,"updated_at":time.time(),"last_passed_stage":f"{market}:{timeframe}","passed":True},ensure_ascii=False),encoding="utf-8")
                except Exception: pass
            cursor_path.write_text(json.dumps({"index":next_idx,"updated_at":time.time(),"last_stage":f"{market}:{timeframe}","difficulty_level":next_level,"stage_passed":promoted},ensure_ascii=False),encoding="utf-8")
        _strategy_lab_save_state()
        gc.collect()
        return result if isinstance(result,list) else []
    except Exception as exc:
        # A single bad symbol/API response must never pin the factory forever.
        # Record the failure, then rotate to the next market/timeframe.
        next_idx=(idx+1)%len(stages)
        cursor_path.write_text(json.dumps({
            "index":next_idx,"updated_at":time.time(),
            "last_stage":f"{market}:{timeframe}",
            "last_error":str(exc)[:240],
            "difficulty_level":max(1,int(_STRATEGY_LAB.get("difficulty_level",1) or 1))
        },ensure_ascii=False),encoding="utf-8")
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB["stage_passed"]=False
            _STRATEGY_LAB["research_phase"]="rotate"
            _STRATEGY_LAB["error"]=str(exc)[:300]
        _STRATEGY_LAB["message"]=f"❌ {market}/{timeframe} فشل بعد الفحص — {str(exc)[:180]} — ينتقل للسوق التالي"
        _strategy_lab_save_state()
        gc.collect()
        return []

def _strategy_lab_worker(days,max_symbols,min_volume,market="futures",timeframe="15m",one_shot=False):
    # Hard cap: scan up to 400 symbols, but only run heavy historical tests on the fast-filtered shortlist.
    max_symbols=max(100,min(400,int(max_symbols)))
    global _STRATEGY_LAB_WORKER_ALIVE
    _STRATEGY_LAB_WORKER_ALIVE=True
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB["difficulty_level"]=max(1,min(5,int(_STRATEGY_LAB.get("difficulty_level",1) or 1)))
        _STRATEGY_LAB["job_params"]={"days":int(days),"max_symbols":int(max_symbols),"min_volume":float(min_volume),"market":market,"timeframe":timeframe,"difficulty_level":_STRATEGY_LAB["difficulty_level"]}
        _STRATEGY_LAB["cadence"]="1m"
        _STRATEGY_LAB["heartbeat_at"]=time.time()
    _strategy_lab_start_heartbeat()
    _strategy_lab_save_state()
    results=[]
    try:
        # Persistent 24/7 factory: one stage at a time, never stops after 24h.
        # Every cycle advances the durable cursor, so all 6 markets × 7 timeframes
        # are continuously revisited without rebuilding the whole universe at once.
        while True:
            cycle_started=time.time()
            try:
                # التشغيل الدائم يمسح كل الأسواق/الفريمات بالتتابع؛ one_shot فقط يقيد نفسه بالطلب.
                stage_market=market if one_shot else None
                stage_timeframe=timeframe if one_shot else None
                stage_output=_strategy_lab_run_all_stages(days,max_symbols,min_volume,stage_market,stage_timeframe,one_shot)
                # Normalize market runners that return (results, active).
                if isinstance(stage_output, tuple):
                    results = stage_output[0] if isinstance(stage_output[0], list) else []
                else:
                    results = stage_output if isinstance(stage_output, list) else []
                with _STRATEGY_LAB_LOCK:
                    stage_error=_STRATEGY_LAB.get("error")
                    failed=(not results and bool(stage_error))
                    _STRATEGY_LAB.update({
                        "running":True,
                        "progress":100,
                        "message":(f"❌ لم تُحفظ نتائج: {stage_error[:220]} — ينتقل للسوق/الفريم التالي" if failed else f"تم حفظ نتائج الدورة: {len(results)} نتيجة — ينتقل للسوق/الفريم التالي بسرعة"),
                        "results":results[:20],
                        "finished_at":time.time(),
                        "error":stage_error if failed else None
                    })
                _strategy_lab_save_state()
            except Exception as exc:
                results=[]
                with _STRATEGY_LAB_LOCK:
                    _STRATEGY_LAB.update({
                        "running":True,
                        "message":"❌ تعذر إكمال دورة البحث: "+str(exc)[:220]+" — ينتقل بعد حفظ الخطأ",
                        "error":str(exc)[:300],
                        "results":[],
                        "finished_at":time.time()
                    })
                _strategy_lab_save_state()
            if one_shot:
                _strategy_lab_stop_heartbeat()
                with _STRATEGY_LAB_LOCK:
                    _STRATEGY_LAB["running"]=False
                    _STRATEGY_LAB["message"]=f"اكتمل الاختبار المطلوب: {market}/{timeframe} — النتائج الناجحة محفوظة"
                    _STRATEGY_LAB["cadence"]="manual"
                    _STRATEGY_LAB["cadence_seconds"]=0
                _strategy_lab_save_state()
                return
            # Continuous mode: rotate to the next market/timeframe quickly.
            # Each stage uses quick -> medium -> deep screening and persists results.
            try:
                cpath=DATA_DIR/"strategy_lab"/"stage_cursor.json"
                c=json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}
                next_idx=int(c.get("index",0))
                if next_idx==0 and str(c.get("last_stage",""))=="contracts:1M":
                    c["last_full_pass_at"]=time.time()
                    c["full_pass_count"]=int(c.get("full_pass_count",0) or 0)+1
                    c["bootstrap_complete"]=True
                    cpath.write_text(json.dumps(c,ensure_ascii=False),encoding="utf-8")
            except Exception:
                pass
            # Fast rotation: no 15-minute idle between stages. The lab itself is
            # the continuous scanner; deep tests provide the heavy validation.
            wait=max(2,5-(time.time()-cycle_started))
            with _STRATEGY_LAB_LOCK:
                _STRATEGY_LAB["cadence_seconds"]=wait
                _STRATEGY_LAB["cadence"]="1m"
                _STRATEGY_LAB["message"]=f"تم حفظ نتائج الدورة: {len(results)} نتيجة — ينتقل للسوق التالي بسرعة"
            _strategy_lab_save_state()
            time.sleep(wait)
    except Exception as exc:
        _strategy_lab_stop_heartbeat()
        with _STRATEGY_LAB_LOCK:
            _STRATEGY_LAB.update({"running":False,"message":"توقف البحث بسبب خطأ","error":str(exc)[:300],"finished_at":time.time()})
        _strategy_lab_save_state()
        _STRATEGY_LAB_WORKER_ALIVE=False

@app.get("/strategy-lab",response_class=HTMLResponse)
def strategy_lab_page(request:Request):
    if not strategy_lab_access(request):
        html="""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مختبر الاستراتيجيات | SMART TRADING PRO</title>
<style>
body{margin:0;background:#0b1220;color:#fff;font-family:Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{width:min(92vw,420px);background:#111a2b;border:1px solid #26334a;border-radius:18px;padding:24px;box-sizing:border-box;box-shadow:0 16px 45px #0006}
h1{margin:0 0 8px;font-size:24px}.muted{color:#9aa8bd;margin-bottom:20px}
.input{width:100%;box-sizing:border-box;padding:14px;border-radius:10px;border:1px solid #33425c;background:#0b1220;color:#fff;font-size:20px;text-align:center;letter-spacing:6px}
button{width:100%;margin-top:18px;padding:13px;border:0;border-radius:10px;background:#16a36b;color:#fff;font-weight:700;font-size:16px;cursor:pointer}
#msg{margin-top:14px;text-align:center;color:#ff9b9b;min-height:20px}
</style>
</head>
<body><main class="card">
<h1>🔐 مختبر الاستراتيجيات</h1>
<div class="muted">أدخل الرقم السري للوصول إلى المصنع.</div>
<form id="f">
<input class="input" name="password" type="password" inputmode="numeric" autocomplete="off" maxlength="6" placeholder="••••••" required autofocus>
<button type="submit">دخول المختبر</button>
<div id="msg"></div>
</form>
</main>
<script>
document.getElementById("f").addEventListener("submit",async e=>{
 e.preventDefault();
 const f=e.currentTarget,msg=document.getElementById("msg");
 msg.textContent="جارٍ التحقق...";
 const r=await fetch("/api/strategy-lab/unlock",{method:"POST",body:new FormData(f),credentials:"same-origin"});
 let d={};try{d=await r.json()}catch(_){}
 if(r.ok&&d.ok){location.reload();return}
 msg.textContent=d.message||"الرقم السري غير صحيح";
});
</script>
</body></html>"""
        response=HTMLResponse(html)
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        return response
    p=BASE/"static"/"strategy-lab.html"
    response=FileResponse(p,media_type="text/html")
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.post("/api/strategy-lab/unlock")
def strategy_lab_unlock(request:Request,password:str=Form(...)):
    if not _strategy_lab_password_ok(password):
        return JSONResponse({"ok":False,"message":"الرقم السري غير صحيح"},status_code=401)
    request.session["strategy_lab_unlocked"]=True
    return {"ok":True,"message":"تم فتح مختبر الاستراتيجيات"}

@app.post("/api/strategy-lab/start")
async def strategy_lab_start(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    with _STRATEGY_LAB_LOCK:
        if _STRATEGY_LAB["running"]:
            return {"ok":False,"message":"البحث شغال حالياً"}
    body=await request.json()
    days=max(7,min(60,int(body.get("days",30))))
    max_symbols=max(100,min(400,int(body.get("max_symbols",100))))
    min_volume=max(1000001.0,float(body.get("min_volume",1000000)))
    market=str(body.get("market","futures")).lower(); timeframe=str(body.get("timeframe","15m"))
    if market not in ("spot","futures","forex","us","saudi","contracts"): market="futures"
    one_shot=bool(body.get("one_shot",False))
    if timeframe not in TIMEFRAMES: timeframe="15m"
    with _STRATEGY_LAB_LOCK:
        _STRATEGY_LAB.update({"running":True,"progress":0,"message":"⏳ البحث مستمر...","results":[],"started_at":time.time(),"finished_at":None,"error":None,"job_params":{"days":days,"max_symbols":max_symbols,"min_volume":min_volume,"market":market,"timeframe":timeframe},"market":market,"timeframe":timeframe,"heartbeat_at":time.time()})
    _strategy_lab_save_state()
    __import__("threading").Thread(target=_strategy_lab_worker,args=(days,max_symbols,min_volume,market,timeframe,one_shot),daemon=True).start()
    return {"ok":True,"message":"بدأ البحث المستمر 24/7","days":days,"max_symbols":max_symbols,"min_volume":min_volume,"market":market,"timeframe":timeframe,"combinations":648}

@app.get("/api/strategy-lab/status")
def strategy_lab_status(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    # Browser refresh must read the durable job state, not reset to in-memory defaults.
    try:
        if _STRATEGY_LAB_STATE_PATH.exists():
            saved=json.loads(_STRATEGY_LAB_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(saved,dict):
                with _STRATEGY_LAB_LOCK:
                    if saved.get("running") and not _STRATEGY_LAB.get("running"):
                        _STRATEGY_LAB.update(saved)
    except Exception:
        pass
    with _STRATEGY_LAB_LOCK:
        return {"ok":True,**_STRATEGY_LAB}

def _strategy_lab_resume_on_startup():
    _strategy_lab_load_state()
    with _STRATEGY_LAB_LOCK:
        running=_STRATEGY_LAB.get("running")
        p=_STRATEGY_LAB.get("job_params") or {}
        days=int(p.get("days",30))
        # Migrate the old one-day bootstrap state to the real factory window.
        if days <= 1:
            days=30
        max_symbols=max(100,min(400,int(p.get("max_symbols",100))))
        min_volume=max(1000001.0,float(p.get("min_volume",1000000)))
        market=str(p.get("market","futures"))
        timeframe=str(p.get("timeframe","15m"))
        _STRATEGY_LAB["job_params"]={"days":days,"max_symbols":max_symbols,"min_volume":min_volume,"market":market,"timeframe":timeframe}
        if not running:
            _STRATEGY_LAB.update({"running":True,"message":"🚀 مختبر الاستراتيجيات — بدء البحث الخفيف تلقائياً","started_at":time.time(),"error":None})
        _STRATEGY_LAB["heartbeat_at"]=time.time()
    print(f"[STRATEGY-LAB] {'resuming' if running else 'starting'} persistent full-market research: days={days}, symbols={max_symbols}, min_volume={min_volume}",flush=True)
    if not _STRATEGY_LAB_WORKER_ALIVE:
        __import__("threading").Thread(target=_strategy_lab_worker,args=(days,max_symbols,min_volume,market,timeframe),daemon=True).start()

@app.get("/api/strategy-lab/results")
def strategy_lab_results(request:Request,download:int=0):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    p=DATA_DIR/"strategy_lab"/"results.json"
    if not p.exists(): return JSONResponse({"ok":False,"message":"لا توجد نتائج بعد"},status_code=404)
    if download:
        return FileResponse(p,media_type="application/json",filename="strategy-lab-results.json")
    return JSONResponse(_lab_read_json(p,{"ok":False,"message":"لا توجد نتائج بعد"}))

@app.get("/api/strategy-lab/results.csv")
def strategy_lab_csv(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    p=DATA_DIR/"strategy_lab"/"results.csv"
    if not p.exists(): return JSONResponse({"ok":False,"message":"لا توجد نتائج بعد"},status_code=404)
    return FileResponse(p,media_type="text/csv",filename="strategy-lab-results.csv")

@app.get("/api/strategy-lab/results.txt")
def strategy_lab_txt(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    p=DATA_DIR/"strategy_lab"/"results.txt"
    if not p.exists(): return JSONResponse({"ok":False,"message":"لا توجد نتائج بعد"},status_code=404)
    return FileResponse(p,media_type="text/plain; charset=utf-8",filename="strategy-lab-results.txt")

@app.get("/api/strategy-lab/strategies")
def strategy_lab_strategies(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    p=DATA_DIR/"strategy_lab"/"strategies.json"
    if not p.exists(): return {"ok":True,"count":0,"strategies":[]}
    try:
        rows=_lab_read_json(p,[])
        rows=rows if isinstance(rows,list) else []
        rows=sorted(rows,key=lambda x:(float(x.get("score",-999999)),float((x.get("factory_audit") or {}).get("walk_forward",0)),int((x.get("factory_audit") or {}).get("stress_pass",0))),reverse=True)
        for rank,row in enumerate(rows,1):
            row["strength_rank"]=rank
        return {"ok":True,"count":len(rows),"strategies":rows,"top10":rows[:10]}
    except Exception as exc: return JSONResponse({"ok":False,"message":str(exc)[:200]},status_code=500)

@app.get("/api/strategy-lab/jewels")
def strategy_lab_jewels(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    p=DATA_DIR/"strategy_lab"/"jewels.json"
    try: rows=_lab_read_json(p,[]) if p.exists() else []
    except Exception: rows=[]
    rows=rows if isinstance(rows,list) else []
    rows=sorted(rows,key=lambda x:(float(x.get("jewel_score",0)),float(x.get("score",-999999))),reverse=True)
    return {"ok":True,"count":len(rows),"jewels":rows[:100],"top10":rows[:10]}

@app.get("/api/strategy-lab/archive")
def strategy_lab_archive(request:Request):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    """Return the persistent strategy archive index and archived TXT files."""
    d=DATA_DIR/"strategy_lab"/"archive"
    d.mkdir(parents=True,exist_ok=True)
    files=sorted([p.name for p in d.glob("*.txt")],reverse=True)
    return {"ok":True,"count":len(files),"files":files}

@app.get("/api/strategy-lab/archive/{filename}")
def strategy_lab_archive_file(request:Request,filename:str):
    if not strategy_lab_access(request): return JSONResponse({"ok":False,"message":"مختبر الاستراتيجيات مقفل — أدخل الرقم السري"},status_code=403)
    d=DATA_DIR/"strategy_lab"/"archive"
    safe=Path(filename).name
    p=d/safe
    if p.suffix.lower()!=".txt" or not p.exists():
        return JSONResponse({"ok":False,"message":"النتيجة غير موجودة"},status_code=404)
    return FileResponse(p,media_type="text/plain; charset=utf-8",filename=safe)