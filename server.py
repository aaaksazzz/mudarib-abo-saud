import os
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__, template_folder="templates", static_folder="static")

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "Mozilla/5.0 Mudarib-Abo-Saud/3.0"})

BYBIT_BASE = "https://api.bybit.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"
CACHE = {}
LOCK = threading.Lock()

INTERVALS = {"5m", "15m", "1h", "4h", "1d"}

# Representative liquid instruments for each market.
MARKETS = {
    "crypto": [
        ("BTCUSDT", "Bitcoin", "crypto"), ("ETHUSDT", "Ethereum", "crypto"),
        ("SOLUSDT", "Solana", "crypto"), ("XRPUSDT", "XRP", "crypto"),
        ("BNBUSDT", "BNB", "crypto"), ("DOGEUSDT", "Dogecoin", "crypto"),
        ("ADAUSDT", "Cardano", "crypto"), ("AVAXUSDT", "Avalanche", "crypto"),
        ("LINKUSDT", "Chainlink", "crypto"), ("SUIUSDT", "Sui", "crypto"),
    ],
    "saudi": [
        ("2222.SR", "أرامكو", "saudi"), ("1120.SR", "الراجحي", "saudi"),
        ("2010.SR", "سابك", "saudi"), ("1180.SR", "الأهلي السعودي", "saudi"),
        ("1150.SR", "الإنماء", "saudi"), ("7010.SR", "إس تي سي", "saudi"),
        ("2380.SR", "بترو رابغ", "saudi"), ("4031.SR", "البحري", "saudi"),
        ("4003.SR", "إكسترا", "saudi"), ("5110.SR", "كهرباء السعودية", "saudi"),
        ("1211.SR", "معادن", "saudi"), ("2050.SR", "صافولا", "saudi"),
    ],
    "us": [
        ("AAPL", "Apple", "us"), ("NVDA", "NVIDIA", "us"), ("MSFT", "Microsoft", "us"),
        ("AMZN", "Amazon", "us"), ("META", "Meta", "us"), ("TSLA", "Tesla", "us"),
        ("GOOGL", "Alphabet", "us"), ("AMD", "AMD", "us"), ("AVGO", "Broadcom", "us"),
        ("NFLX", "Netflix", "us"), ("JPM", "JPMorgan", "us"), ("PLTR", "Palantir", "us"),
        ("COIN", "Coinbase", "us"), ("MSTR", "Strategy", "us"), ("BA", "Boeing", "us"),
    ],
    "forex": [
        ("EURUSD=X", "EUR/USD", "forex"), ("GBPUSD=X", "GBP/USD", "forex"),
        ("USDJPY=X", "USD/JPY", "forex"), ("USDCHF=X", "USD/CHF", "forex"),
        ("AUDUSD=X", "AUD/USD", "forex"), ("USDCAD=X", "USD/CAD", "forex"),
        ("NZDUSD=X", "NZD/USD", "forex"), ("EURGBP=X", "EUR/GBP", "forex"),
    ],
    "commodities": [
        ("GC=F", "الذهب", "commodities"), ("SI=F", "الفضة", "commodities"),
        ("CL=F", "النفط WTI", "commodities"), ("BZ=F", "برنت", "commodities"),
        ("NG=F", "الغاز الطبيعي", "commodities"),
    ],
    "indices": [
        ("^GSPC", "S&P 500", "indices"), ("^IXIC", "Nasdaq", "indices"),
        ("^DJI", "Dow Jones", "indices"), ("^RUT", "Russell 2000", "indices"),
        ("^VIX", "VIX", "indices"), ("^FTSE", "FTSE 100", "indices"),
        ("^GDAXI", "DAX", "indices"), ("^N225", "Nikkei 225", "indices"),
        ("^HSI", "Hang Seng", "indices"),
    ],
    "futures": [
        ("ES=F", "S&P 500 Futures", "futures"), ("NQ=F", "Nasdaq Futures", "futures"),
        ("YM=F", "Dow Futures", "futures"), ("RTY=F", "Russell Futures", "futures"),
        ("GC=F", "Gold Futures", "futures"), ("CL=F", "Crude Oil Futures", "futures"),
    ],
}

LABELS = {
    "crypto": "العملات الرقمية", "saudi": "السوق السعودي", "us": "الأسهم الأمريكية",
    "forex": "الفوركس", "commodities": "السلع", "indices": "المؤشرات العالمية", "futures": "العقود الآجلة"
}


def http_get(url, params=None, timeout=8):
    r = HTTP.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ema(values, period):
    if not values:
        return None
    p = min(period, len(values))
    e = sum(values[:p]) / p
    k = 2.0 / (p + 1)
    for v in values[p:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0.0
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    return sum(tr[-period:]) / min(period, len(tr))


def analyze(candles):
    if len(candles) < 40:
        raise ValueError("بيانات غير كافية للتحليل")
    closes = [x[4] for x in candles]
    highs = [x[2] for x in candles]
    lows = [x[3] for x in candles]
    price = closes[-1]
    e20, e50, e200 = ema(closes,20), ema(closes,50), ema(closes,200)
    rv = rsi(closes,14)
    e12, e26 = ema(closes,12), ema(closes,26)
    macd = e12 - e26
    hist_values = []
    start = max(26, len(closes)-80)
    for i in range(start, len(closes)):
        hist_values.append((ema(closes[:i+1],12) or 0) - (ema(closes[:i+1],26) or 0))
    ms = ema(hist_values,9) if hist_values else 0
    hist = macd - (ms or 0)
    score = 50
    reasons = []
    for value, pts, good, bad in [
        (price > e20, 8, "السعر فوق EMA20", "السعر تحت EMA20"),
        (price > e50, 8, "السعر فوق EMA50", "السعر تحت EMA50"),
        (price > e200, 10, "السعر فوق EMA200", "السعر تحت EMA200"),
        (hist > 0, 8, "MACD إيجابي", "MACD سلبي"),
    ]:
        score += pts if value else -pts
        reasons.append(good if value else bad)
    if 50 <= rv <= 70:
        score += 8; reasons.append("RSI في نطاق إيجابي")
    elif rv > 70:
        score += 2; reasons.append("RSI مرتفع")
    elif rv < 30:
        score += 3; reasons.append("RSI منخفض")
    else:
        score -= 5; reasons.append("RSI محايد")
    score = max(0, min(100, int(round(score))))
    if score >= 80:
        signal, direction = "شراء قوي", "buy"
    elif score >= 65:
        signal, direction = "شراء", "buy"
    elif score <= 20:
        signal, direction = "بيع قوي", "sell"
    elif score <= 35:
        signal, direction = "بيع", "sell"
    else:
        signal, direction = "حيادي", "neutral"
    a = atr(highs, lows, closes, 14)
    risk = max(a * 1.5, price * 0.01)
    if direction == "buy":
        sl, tp1, tp2, tp3 = price-risk, price+risk*1.5, price+risk*2, price+risk*3
    elif direction == "sell":
        sl, tp1, tp2, tp3 = price+risk, price-risk*1.5, price-risk*2, price-risk*3
    else:
        sl = tp1 = tp2 = tp3 = None
    return {
        "signal": signal, "direction": direction, "score": score, "score10": round(score/10,1),
        "price": price, "entry": price, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "rsi": round(rv,2), "ema20": e20, "ema50": e50, "ema200": e200,
        "macd": macd, "macd_signal": ms, "macd_histogram": hist, "atr": a,
        "support": min(lows[-20:]), "resistance": max(highs[-20:]), "reasons": reasons,
    }


def yahoo_range(interval):
    return {"5m":"5d", "15m":"5d", "1h":"1mo", "4h":"3mo", "1d":"1y"}.get(interval,"5d")


def yahoo_interval(interval):
    return {"5m":"5m", "15m":"15m", "1h":"1h", "4h":"1h", "1d":"1d"}.get(interval, "15m")


def yahoo_candles(symbol, interval):
    data = http_get(f"{YAHOO_BASE}/v8/finance/chart/{symbol}", {
        "interval": yahoo_interval(interval), "range": yahoo_range(interval), "events": "history"
    })
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError("Yahoo لم يرجع بيانات")
    result = result[0]
    ts = result.get("timestamp") or []
    q = (result.get("indicators", {}).get("quote") or [{}])[0]
    candles = []
    for i, t in enumerate(ts):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            v = q.get("volume", [0]*len(ts))[i] or 0
            if None in (o,h,l,c):
                continue
            candles.append((int(t)*1000,float(o),float(h),float(l),float(c),float(v or 0)))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    if interval == "4h" and candles:
        # Aggregate Yahoo's 1h candles into 4h candles.
        out=[]
        for i in range(0, len(candles), 4):
            chunk=candles[i:i+4]
            if len(chunk)<4: continue
            out.append((chunk[0][0],chunk[0][1],max(x[2] for x in chunk),min(x[3] for x in chunk),chunk[-1][4],sum(x[5] for x in chunk)))
        candles=out
    return candles


def bybit_candles(symbol, interval):
    iv = {"5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"}[interval]
    data = http_get(f"{BYBIT_BASE}/v5/market/kline", {"category":"spot","symbol":symbol,"interval":iv,"limit":200})
    if data.get("retCode") != 0:
        raise ValueError(data.get("retMsg") or "Bybit error")
    rows = data.get("result", {}).get("list", [])
    out=[]
    for x in reversed(rows):
        out.append((int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])))
    return out


def fetch_one(item, interval):
    symbol, name, market = item
    if market == "crypto":
        candles = bybit_candles(symbol, interval)
        source = "Bybit"
    else:
        candles = yahoo_candles(symbol, interval)
        source = "Yahoo Finance"
    a = analyze(candles)
    return {
        **a, "symbol": symbol, "name": name, "market": market,
        "marketName": LABELS[market], "interval": interval, "source": source,
        "updatedAt": int(time.time()*1000),
    }


def all_items():
    out=[]
    for items in MARKETS.values(): out.extend(items)
    return out


def do_scan(interval, market="all", limit=80):
    items = all_items() if market == "all" else MARKETS.get(market, [])
    if not items:
        raise ValueError("السوق غير معروف")
    limit = max(1, min(int(limit), 120))
    # Always scan every category at least once; limit is only a final display cap.
    results=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(fetch_one,x,interval) for x in items]
        for f in as_completed(futures):
            try: results.append(f.result())
            except Exception as e:
                pass
    rank={"شراء قوي":5,"شراء":4,"حيادي":3,"بيع":2,"بيع قوي":1}
    results.sort(key=lambda x:(rank.get(x["signal"],0),x["score"]), reverse=True)
    if market == "all":
        # Keep enough cards for every section.
        return results[:limit]
    return results[:limit]


def cached_scan(interval, market, limit):
    key=f"{market}:{interval}:{limit}"
    now=time.time()
    with LOCK:
        old=CACHE.get(key)
    if old and now-old["ts"] < 45:
        return {**old["payload"], "cached": True}
    results=do_scan(interval,market,limit)
    payload={"ok":True,"interval":interval,"market":market,"count":len(results),"results":results,"cached":False}
    with LOCK: CACHE[key]={"ts":time.time(),"payload":payload}
    return payload


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"ok":True,"service":"mudarib-abo-saud","version":"3.0","time":int(time.time())})


@app.get("/api/scan")
def scan():
    interval=request.args.get("interval","15m")
    market=request.args.get("market","all").lower()
    try: limit=int(request.args.get("limit","80"))
    except ValueError: limit=80
    if interval not in INTERVALS:
        return jsonify({"ok":False,"message":"فريم غير صحيح"}),400
    try:
        return jsonify(cached_scan(interval,market,limit))
    except Exception as e:
        return jsonify({"ok":False,"message":f"تعذر جلب بيانات السوق: {str(e)[:180]}"}),503


@app.get("/api/signals")
def signals():
    return scan()


@app.get("/api/market-signals")
def market_signals():
    return scan()


@app.get("/api/analysis")
def analysis():
    symbol=request.args.get("symbol","BTCUSDT").upper()
    interval=request.args.get("interval","15m")
    market=request.args.get("market", "crypto" if symbol.endswith("USDT") else "us")
    try:
        if market == "crypto": c=bybit_candles(symbol,interval); source="Bybit"
        else: c=yahoo_candles(symbol,interval); source="Yahoo Finance"
        return jsonify({"ok":True,"analysis":{**analyze(c),"symbol":symbol,"interval":interval,"source":source}})
    except Exception as e:
        return jsonify({"ok":False,"message":str(e)[:180]}),503


@app.get("/api/markets")
def markets():
    return jsonify({"ok":True,"markets":{k:[{"symbol":x[0],"name":x[1]} for x in v] for k,v in MARKETS.items()}})


@app.get("/api/news")
def news():
    # Keep this endpoint compatible with the existing frontend.
    try:
        data=http_get("https://query1.finance.yahoo.com/v1/finance/search", {"q":"markets","newsCount":12}, 8)
        items=[]
        for x in data.get("news",[])[:12]:
            items.append({"title":x.get("title",""),"link":x.get("link",""),"source":x.get("publisher","Yahoo Finance"),"published":""})
        return jsonify({"ok":True,"news":items,"cached":False})
    except Exception as e:
        return jsonify({"ok":True,"news":[],"cached":False,"message":"تعذر جلب الأخبار الآن"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")), debug=False)
