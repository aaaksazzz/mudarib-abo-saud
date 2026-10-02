"""Runtime strategy override for the trading engine.
User strategy: MA200 + RSI 50 cross + high volume. No MA20.
Loaded by sitecustomize before the ASGI service starts.
"""
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEFRAMES=("15m","30m","1h","4h","1d","1w","1M")


def _sma(values, n=200):
    return sum(values[-n:])/n if len(values) >= n else None


def _strategy_rows(app, symbol, timeframe, sides, candles):
    if len(candles) < 220:
        return []
    closes=[float(x[0]) for x in candles]
    lows=[float(x[1]) for x in candles]
    highs=[float(x[2]) if len(x)>2 else float(x[0]) for x in candles]
    vols=[float(x[3]) if len(x)>3 else 0.0 for x in candles]
    ma200=_sma(closes,200)
    rsi_now=app._rsi(closes)
    rsi_prev=app._rsi(closes[:-1])
    avg_vol=sum(vols[-21:-1])/20 if len(vols)>=21 else 0
    ratio=vols[-1]/avg_vol if avg_vol>0 else 0
    if ma200 is None or rsi_now is None or rsi_prev is None or avg_vol<=0:
        return []
    price=closes[-1]
    buy=price>ma200 and rsi_prev<=50<rsi_now and ratio>=1.5
    sell=price<ma200 and rsi_prev>=50>rsi_now and ratio>=1.5
    side="BUY" if buy else "SELL" if sell else None
    if side not in sides:
        return []
    sl=min(lows[-20:]) if side=="BUY" else max(highs[-20:])
    risk=abs(price-sl)
    if risk<=0 or risk/price>0.08:
        return []
    tp1=price+risk if side=="BUY" else price-risk
    tp2=price+2*risk if side=="BUY" else price-2*risk
    tp3=price+3*risk if side=="BUY" else price-3*risk
    ai=max(50,min(99,60+min(30,abs(rsi_now-50)*1.2+(ratio-1.5)*10)))
    return [{
        "symbol":symbol,"side":side,
        "signal_label":"شراء" if side=="BUY" else "بيع",
        "strategy_label":"MA200 + RSI50 Cross + High Volume",
        "strategy_mode":"MA200_RSI50_VOLUME","timeframe":timeframe,
        "change_pct":round((price/closes[-2]-1)*100,3),
        "profit_pct":abs(tp1/price-1)*100,"loss_pct":risk/price*100,
        "ai_pct":round(ai,1),"tag":"MA200 + RSI50 + Volume",
        "entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "status":"open","ma200":ma200,"rsi":rsi_now,"rsi_prev":rsi_prev,
        "volume":vols[-1],"volume_avg20":avg_vol,"volume_ratio":round(ratio,2),
        "volume_high":True,
        "conditions":"السعر مقابل MA200 + قطع RSI50 + فوليوم عالي"
    }]


def _binance_spot(app,timeframe,limit_symbols=None):
    tickers=app._binance_json("https://api.binance.com/api/v3/ticker/24hr",timeout=8,timeframe=timeframe,spot_fallback=True)
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        s=str(t.get("symbol",""))
        if not s.endswith("USDT") or s in app.BINANCE_SCANNER_EXCLUDED:
            continue
        try:
            q=float(t.get("quoteVolume") or 0)
            if q>=app.BINANCE_SCANNER_MIN_VOLUME and float(t.get("lastPrice") or 0)>0:
                candidates.append((q,s))
        except Exception:
            pass
    candidates.sort(reverse=True)
    if limit_symbols is not None:
        candidates=candidates[:max(1,int(limit_symbols))]
    def one(item):
        q,s=item
        try:
            u="https://api.binance.com/api/v3/klines?"+urllib.parse.urlencode({"symbol":s,"interval":timeframe,"limit":260})
            ks=app._binance_json(u,timeout=7,timeframe=timeframe,spot_fallback=True)
            if not isinstance(ks,list) or len(ks)<221:
                return None
            closed=ks[:-1]
            candles=[(float(x[4]),float(x[3]),float(x[2]),float(x[5])) for x in closed]
            rows=_strategy_rows(app,s,timeframe,["BUY"],candles)
            for r in rows:
                r.update({"quote_volume":q,"market":"spot","candle_start":str(closed[-1][0])})
            return rows[0] if rows else None
        except Exception:
            return None
    out=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in [ex.submit(one,x) for x in candidates]:
            try:
                r=f.result()
                if r: out.append(r)
            except Exception:
                pass
    return sorted(out,key=lambda x:(float(x.get("ai_pct") or 0),float(x.get("volume_ratio") or 0),float(x.get("quote_volume") or 0)),reverse=True)[:40]


def _binance_futures(app,timeframe):
    tickers=app._binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/24hr",timeout=8)
    candidates=[]
    for t in tickers if isinstance(tickers,list) else []:
        s=str(t.get("symbol",""))
        if s.endswith("USDT"):
            try:candidates.append((float(t.get("quoteVolume") or 0),s))
            except Exception:pass
    def one(item):
        q,s=item
        try:
            u="https://fapi.binance.com/fapi/v1/klines?"+urllib.parse.urlencode({"symbol":s,"interval":timeframe,"limit":260})
            ks=app._binance_futures_json(u,timeout=7)
            if not isinstance(ks,list) or len(ks)<221:return None
            closed=ks[:-1]
            candles=[(float(x[4]),float(x[3]),float(x[2]),float(x[5])) for x in closed]
            rows=_strategy_rows(app,s,timeframe,["BUY","SELL"],candles)
            for r in rows:r.update({"quote_volume":q,"market":"futures","candle_start":str(closed[-1][0])})
            return rows[0] if rows else None
        except Exception:return None
    out=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in [ex.submit(one,x) for x in candidates]:
            try:
                r=f.result()
                if r:out.append(r)
            except Exception:pass
    return sorted(out,key=lambda x:(float(x.get("ai_pct") or 0),float(x.get("volume_ratio") or 0),float(x.get("quote_volume") or 0)),reverse=True)[:40]


def _yahoo_candles(app,symbol,timeframe):
    interval={"15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","1M":"1mo"}[timeframe]
    range_={"15m":"60d","30m":"60d","1h":"60d","4h":"1y","1d":"2y","1w":"5y","1M":"10y"}[timeframe]
    q=urllib.parse.quote(symbol,safe="")
    for base in app.YAHOO_BASES:
        try:
            d=app._json_get(f"{base}/v8/finance/chart/{q}?interval={interval}&range={range_}",timeout=6,source=("yahoo1" if base.endswith("query1.finance.yahoo.com") else "yahoo2"))
            rr=(d.get("chart",{}).get("result") or [None])[0]
            if not rr:continue
            ts=rr.get("timestamp") or []
            qd=rr.get("indicators",{}).get("quote",[{}])[0]
            o,h,l,c,v=[qd.get(k,[]) for k in ("open","high","low","close","volume")]
            raw=[(int(t),float(a),float(b),float(cc),float(cl),float(vv or 0)) for t,a,b,cc,cl,vv in zip(ts,o,h,l,c,v) if None not in (a,b,cc,cl)]
            if timeframe!="4h":
                return [(x[4],x[3],x[2],x[5]) for x in raw]
            # Aggregate Yahoo 1h candles into real 4h bars.
            out=[]; bucket=None; cur=[]
            for x in raw:
                b=(x[0]//14400)*14400
                if bucket is None or b==bucket:
                    bucket=b;cur.append(x)
                else:
                    out.append((cur[-1][4],min(z[3] for z in cur),max(z[2] for z in cur),sum(z[5] for z in cur)))
                    bucket=b;cur=[x]
            if cur:out.append((cur[-1][4],min(z[3] for z in cur),max(z[2] for z in cur),sum(z[5] for z in cur)))
            return out
        except Exception:
            continue
    return []


def _yahoo_market(app,market,timeframe):
    # Spot/Saudi/US are long-only; all other markets allow both directions.
    sides=["BUY"] if market in {"saudi","us"} else ["BUY","SELL"]
    symbols=app._market_universe(market)
    def one(s):
        try:return _strategy_rows(app,s,timeframe,sides,_yahoo_candles(app,s,timeframe))
        except Exception:return []
    out=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in [ex.submit(one,s) for s in symbols]:
            try:out.extend(f.result())
            except Exception:pass
    return sorted(out,key=lambda x:(float(x.get("ai_pct") or 0),float(x.get("volume_ratio") or 0)),reverse=True)[:40]


def apply(app):
    app._scan_spot_strategy=lambda timeframe="15m",limit_symbols=None:_binance_spot(app,timeframe,limit_symbols)
    app._scan_binance_futures=lambda timeframe:_binance_futures(app,timeframe)
    app._scan_yahoo_market=lambda market,timeframe:_yahoo_market(app,market,timeframe)
    app._strategy_rows=lambda symbol,timeframe,sides,candles:_strategy_rows(app,symbol,timeframe,sides,candles)
