import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
app = FastAPI(title="التداول الذكي PRO", version="2.1.1")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

BINANCE = {
    "spot": "https://api.binance.com/api/v3/ticker/24hr",
    "futures": "https://fapi.binance.com/fapi/v1/ticker/24hr",
}
KLINES = {
    "spot": "https://api.binance.com/api/v3/klines",
    "futures": "https://fapi.binance.com/fapi/v1/klines",
}
CACHE = {}
CACHE_TTL = 20
TECH_CACHE = {}
TECH_CACHE_TTL = 90
STABLES = {"USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP", "USDE"}
INTERVALS = {"15m", "1h", "4h", "1d", "1w", "1M"}
HIGHER_INTERVAL = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w", "1w": "1M", "1M": "1M"}


def fetch_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": "SmartTradingPro/2.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * alpha + value * (1 - alpha)
    return value


def market_tickers(market):
    raw = fetch_json(BINANCE[market])
    rows = []
    for item in raw:
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base in STABLES:
            continue
        try:
            price = float(item.get("lastPrice") or 0)
            change = float(item.get("priceChangePercent") or 0)
            quote_volume = float(item.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0 or quote_volume < 1_000_000:
            continue
        rows.append({"symbol": symbol, "price": price, "change_pct": change, "quote_volume": quote_volume})
    rows.sort(key=lambda x: x["quote_volume"], reverse=True)
    return rows


def candle_closes(market, symbol, interval):
    from urllib.parse import urlencode
    url = KLINES[market] + "?" + urlencode({"symbol": symbol, "interval": interval, "limit": 220})
    candles = fetch_json(url, timeout=7)
    return [float(candle[4]) for candle in candles if len(candle) > 4]


@app.get("/", response_class=HTMLResponse)
def home():
    page = BASE / "static" / "index.html"
    html = page.read_text(encoding="utf-8")
    # Keep the interactive technical filter separate from the main page markup.
    if 'src="/static/technical.js"' not in html:
        html = html.replace("</body>", '<script src="/static/technical.js?v=2.1"></script></body>')
    # Do not expose admin navigation until authenticated role-based access is implemented.
    html = html.replace('<button data-page="admin"><span class="ico">⚙</span>الإدارة</button>', "")
    return HTMLResponse(html)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "service": "smart-trading-pro", "version": "2.1.1", "timestamp": int(time.time())}


@app.get("/api/market/{market}")
def market_data(market: str, limit: int = Query(40, ge=1, le=100)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({
            "ok": True, "market": market, "live": False, "items": [],
            "message": "مصدر الأسعار المباشر لهذا السوق غير مربوط حاليًا؛ لم نعرض بيانات تقديرية."
        })
    now = time.time()
    cached = CACHE.get(market)
    if cached and now - cached[0] < CACHE_TTL:
        data = cached[1]
    else:
        try:
            data = market_tickers(market)
            CACHE[market] = (now, data)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return JSONResponse({
                "ok": False, "market": market, "live": False, "items": [],
                "message": "تعذر جلب الأسعار المباشرة الآن. حاول التحديث بعد قليل."
            }, status_code=503)
    return {"ok": True, "market": market, "live": True, "updated_at": int(now), "items": data[:limit]}


@app.get("/api/technical/{market}")
def technical_filter(market: str, interval: str = Query("15m"), limit: int = Query(12, ge=1, le=20)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفلتر الفني متاح حاليًا لسبوت وفيوتشر Binance فقط."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    cache_key = (market, interval, limit)
    now = time.time()
    cached = TECH_CACHE.get(cache_key)
    if cached and now - cached[0] < TECH_CACHE_TTL:
        return cached[1]
    try:
        tickers = market_tickers(market)[:limit]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب بيانات السوق المباشرة."}, status_code=503)

    higher = HIGHER_INTERVAL[interval]
    def analyze(ticker):
        try:
            closes, higher_closes = None, None
            closes = candle_closes(market, ticker["symbol"], interval)
            higher_closes = closes if higher == interval else candle_closes(market, ticker["symbol"], higher)
            e50, e200 = ema(closes, 50), ema(closes, 200)
            h50, h200 = ema(higher_closes, 50), ema(higher_closes, 200)
            if None in (e50, e200, h50, h200):
                return None
            eligible = ticker["price"] > e200 and e50 > e200 and h50 > h200
            return {**ticker, "ema50": e50, "ema200": e200, "higher_interval": higher,
                    "higher_ema50": h50, "higher_ema200": h200, "eligible": eligible}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError):
            return None

    analyzed = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(analyze, ticker) for ticker in tickers]
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                analyzed.append(item)
    analyzed.sort(key=lambda x: x["quote_volume"], reverse=True)
    eligible_items = [item for item in analyzed if item["eligible"]]
    result = {
        "ok": True, "live": True, "market": market, "interval": interval,
        "higher_interval": higher, "scanned": len(tickers), "analyzed": len(analyzed),
        "updated_at": int(now), "items": eligible_items,
        "message": "شرط الاتجاه: السعر فوق EMA200 وEMA50 فوق EMA200 على الفريم المختار، مع تأكيد EMA50 فوق EMA200 على الفريم الأعلى. هذا فلتر اتجاه وليس ضمان ربح."
    }
    TECH_CACHE[cache_key] = (now, result)
    return result


SIGNAL_CACHE = {}
SIGNAL_CACHE_TTL = 75


def candle_data(market: str, symbol: str, interval: str):
    from urllib.parse import urlencode
    url = KLINES[market] + "?" + urlencode({"symbol": symbol, "interval": interval, "limit": 220})
    raw = fetch_json(url, timeout=8)
    return [{"high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
            for k in raw if len(k) > 4]


def build_signal(market: str, ticker: dict, interval: str):
    candles = candle_data(market, ticker["symbol"], interval)
    if len(candles) < 205:
        return None
    closes = [k["close"] for k in candles]
    e50, e200 = ema(closes, 50), ema(closes, 200)
    if e50 is None or e200 is None:
        return None
    # ATR-based risk levels from actual Binance candles; not a guaranteed outcome.
    tr = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        tr.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
    atr = sum(tr[-14:]) / min(14, len(tr))
    price = closes[-1]
    if atr <= 0 or price <= 0:
        return None
    if e50 > e200 and price > e50 and closes[-1] >= closes[-2]:
        side = "BUY"
    elif market == "futures" and e50 < e200 and price < e50 and closes[-1] <= closes[-2]:
        side = "SELL"
    else:
        return None
    entry = price
    risk = atr * 1.5
    if side == "BUY":
        stop, t1, t2, t3 = entry - risk, entry + risk, entry + 2*risk, entry + 3*risk
    else:
        stop, t1, t2, t3 = entry + risk, entry - risk, entry - 2*risk, entry - 3*risk
    if stop <= 0 or (side == "BUY" and stop >= entry) or (side == "SELL" and stop <= entry):
        return None
    spread = abs(e50 - e200) / entry * 100
    momentum = abs(closes[-1] - closes[-4]) / entry * 100 if len(closes) >= 4 else 0
    score = min(94, max(60, int(65 + min(spread, 2.0)*7 + min(momentum, 2.0)*4)))
    risk_pct = abs(entry - stop) / entry * 100
    return {
        "symbol": ticker["symbol"], "side": side, "market": market, "interval": interval,
        "entry": entry, "stop": stop, "tp1": t1, "tp2": t2, "tp3": t3,
        "stop_pct": risk_pct, "tp1_pct": abs(t1-entry)/entry*100,
        "tp2_pct": abs(t2-entry)/entry*100, "tp3_pct": abs(t3-entry)/entry*100,
        "score": score, "quote_volume": ticker["quote_volume"], "updated_at": int(time.time()),
        "method": "اتجاه EMA50/200 + تأكيد حركة الشمعة",
        "status": "مراقبة — لم يُسجّل تحقق هدف أو وقف"
    }


@app.get("/api/signals/{market}")
def signal_cards(market: str, interval: str = Query("15m"), limit: int = Query(12, ge=1, le=20)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({"ok": False, "live": False, "items": [],
                             "message": "مصدر هذا السوق غير مربوط؛ لا يمكن إنشاء صفقات فعلية."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    key = (market, interval, limit)
    now = time.time()
    cached = SIGNAL_CACHE.get(key)
    if cached and now - cached[0] < SIGNAL_CACHE_TTL:
        return cached[1]
    try:
        tickers = market_tickers(market)[:limit]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب أسعار السوق الآن."}, status_code=503)

    found = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(build_signal, market, ticker, interval) for ticker in tickers]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    found.append(item)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError, ZeroDivisionError):
                continue
    found.sort(key=lambda x: (x["score"], x["quote_volume"]), reverse=True)
    medals = ["gold", "silver", "bronze"]
    for i, item in enumerate(found):
        item["rank"] = i + 1
        item["medal"] = medals[i] if i < 3 else "standard"
    result = {"ok": True, "live": True, "market": market, "interval": interval,
              "scanned": len(tickers), "count": len(found), "updated_at": int(now),
              "items": found, "message": "مستويات الدخول والوقف والأهداف محسوبة من شموع Binance وATR. درجة التوافق تقدير فني وليست احتمال ربح مثبتًا. لا تتوفر نتائج تاريخية موثقة لهذه الإشارات بعد."}
    SIGNAL_CACHE[key] = (now, result)
    return result


@app.get("/api/status")
def status():
    return {"ok": True, "site": "ready", "markets": {"spot": "live", "futures": "live", "alpha": "not_connected", "contracts": "not_connected", "us": "not_connected", "saudi": "not_connected", "forex": "not_connected", "gold": "not_connected"}}
