import os
import time
import math
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, render_template

# =========================================================
# مضارب أبو سعود — Live Market Analyzer
# Lightweight / Real Data / No Charts / No Login
# =========================================================

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------------- CONFIG ----------------

BYBIT_BASE = "https://api.bybit.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

CACHE_SECONDS = 45
MAX_CANDLES = 80
MAX_RESULTS = 12
REQUEST_TIMEOUT = 7
MAX_WORKERS = 6

# ---------------------------------------------------------
# أدوات التحليل
# ---------------------------------------------------------

CRYPTO = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
]

SAUDI = [
    "2222.SR",   # أرامكو
    "1120.SR",   # الراجحي
    "2010.SR",   # سابك
    "1180.SR",   # الأهلي
    "1150.SR",   # الإنماء
    "7010.SR",   # STC
    "2380.SR",
    "4031.SR",
    "4003.SR",
    "5110.SR",
]

US_STOCKS = [
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "TSLA",
    "GOOGL",
    "AMD",
    "AVGO",
    "PLTR",
]

FOREX = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "USDCHF=X",
    "AUDUSD=X",
    "USDCAD=X",
]

COMMODITIES = [
    "GC=F",
    "SI=F",
    "CL=F",
    "BZ=F",
]

INDICES = [
    "^GSPC",
    "^IXIC",
    "^DJI",
    "^RUT",
    "^VIX",
]

FUTURES = [
    "ES=F",
    "NQ=F",
    "YM=F",
    "RTY=F",
    "GC=F",
    "CL=F",
]

MARKETS = {
    "crypto": CRYPTO,
    "saudi": SAUDI,
    "us": US_STOCKS,
    "forex": FOREX,
    "commodities": COMMODITIES,
    "indices": INDICES,
    "futures": FUTURES,
}

MARKET_NAMES = {
    "crypto": "العملات الرقمية",
    "saudi": "السوق السعودي",
    "us": "الأسهم الأمريكية",
    "forex": "الفوركس",
    "commodities": "الذهب والنفط",
    "indices": "المؤشرات",
    "futures": "العقود الآجلة",
}

# ---------------- CACHE ----------------

cache = {}
cache_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def cache_get(key):
    with cache_lock:
        item = cache.get(key)

    if not item:
        return None

    if time.time() - item["time"] > CACHE_SECONDS:
        return None

    return item["data"]


def cache_set(key, data):
    with cache_lock:
        cache[key] = {
            "time": time.time(),
            "data": data,
        }


# =========================================================
# DATA
# =========================================================

def get_interval(interval):
    allowed = {
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }
    return allowed.get(interval, "15")


def yahoo_range(interval):
    if interval == "5m":
        return "5d"
    if interval == "15m":
        return "5d"
    if interval == "30m":
        return "5d"
    if interval == "1h":
        return "1mo"
    if interval == "4h":
        return "3mo"
    return "6mo"


def fetch_bybit(symbol, interval):
    key = f"bybit:{symbol}:{interval}"
    old = cache_get(key)
    if old:
        return old

    url = f"{BYBIT_BASE}/v5/market/kline"

    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": get_interval(interval),
        "limit": MAX_CANDLES,
    }

    r = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Mudarib-Abo-Saud/1.0"},
    )

    r.raise_for_status()
    data = r.json()

    if data.get("retCode") != 0:
        raise RuntimeError(data.get("retMsg", "Bybit error"))

    rows = data.get("result", {}).get("list", [])

    candles = []

    for x in reversed(rows):
        if len(x) < 6:
            continue

        candles.append({
            "t": int(x[0]),
            "o": float(x[1]),
            "h": float(x[2]),
            "l": float(x[3]),
            "c": float(x[4]),
            "v": float(x[5]),
        })

    if len(candles) < 20:
        raise RuntimeError("بيانات غير كافية")

    cache_set(key, candles)
    return candles


def fetch_yahoo(symbol, interval):
    key = f"yahoo:{symbol}:{interval}"
    old = cache_get(key)

    if old:
        return old

    url = f"{YAHOO_BASE}/v8/finance/chart/{symbol}"

    params = {
        "interval": interval if interval != "4h" else "1h",
        "range": yahoo_range(interval),
        "includePrePost": "false",
        "events": "div,splits",
    }

    r = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    r.raise_for_status()

    data = r.json()
    result = data.get("chart", {}).get("result")

    if not result:
        raise RuntimeError("Yahoo لم يرجع بيانات")

    result = result[0]

    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles = []

    for i, ts in enumerate(timestamps):
        try:
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]

            if None in (o, h, l, c):
                continue

            candles.append({
                "t": int(ts) * 1000,
                "o": float(o),
                "h": float(h),
                "l": float(l),
                "c": float(c),
                "v": float(volumes[i] or 0),
            })
        except Exception:
            continue

    # Yahoo لا يدعم 4h مباشرة، لذلك نجمع شموع الساعة
    if interval == "4h":
        candles = aggregate_4h(candles)

    candles = candles[-MAX_CANDLES:]

    if len(candles) < 20:
        raise RuntimeError("بيانات غير كافية")

    cache_set(key, candles)
    return candles


def aggregate_4h(candles):
    if not candles:
        return []

    out = []
    bucket = None
    current = None

    for c in candles:
        ts = int(c["t"] / 1000)
        hour = datetime.fromtimestamp(
            ts,
            timezone.utc
        ).hour

        base_hour = hour - (hour % 4)

        dt = datetime.fromtimestamp(
            ts,
            timezone.utc
        ).replace(
            hour=base_hour,
            minute=0,
            second=0,
            microsecond=0
        )

        b = int(dt.timestamp())

        if bucket != b:
            if current:
                out.append(current)

            bucket = b

            current = {
                "t": b * 1000,
                "o": c["o"],
                "h": c["h"],
                "l": c["l"],
                "c": c["c"],
                "v": c["v"],
            }
        else:
            current["h"] = max(current["h"], c["h"])
            current["l"] = min(current["l"], c["l"])
            current["c"] = c["c"]
            current["v"] += c["v"]

    if current:
        out.append(current)

    return out


def fetch_candles(symbol, market, interval):
    if market == "crypto":
        return fetch_bybit(symbol, interval)

    return fetch_yahoo(symbol, interval)


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if not values:
        return []

    if len(values) < period:
        return [None] * len(values)

    result = [None] * len(values)

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    multiplier = 2 / (period + 1)

    prev = seed

    for i in range(period, len(values)):
        prev = (
            (values[i] - prev) * multiplier
        ) + prev

        result[i] = prev

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return [None] * len(values)

    result = [None] * len(values)

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]

        gain = max(change, 0)
        loss = max(-change, 0)

        avg_gain = (
            (avg_gain * (period - 1)) + gain
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + loss
        ) / period

        if avg_loss == 0:
            result[i] = 100
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))

    return result


def atr(candles, period=14):
    if len(candles) <= period:
        return [None] * len(candles)

    tr = [None]

    for i in range(1, len(candles)):
        high = candles[i]["h"]
        low = candles[i]["l"]
        prev_close = candles[i - 1]["c"]

        tr_value = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        tr.append(tr_value)

    result = [None] * len(candles)

    first = tr[1:period + 1]

    if len(first) < period:
        return result

    value = sum(first) / period
    result[period] = value

    for i in range(period + 1, len(candles)):
        value = (
            (value * (period - 1)) + tr[i]
        ) / period

        result[i] = value

    return result


# =========================================================
# ANALYSIS
# =========================================================

def analyze(symbol, market, interval, candles):
    closes = [x["c"] for x in candles]
    volumes = [x["v"] for x in candles]

    price = closes[-1]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    r = rsi(closes, 14)
    a = atr(candles, 14)

    ema20 = e20[-1]
    ema50 = e50[-1]
    ema200 = e200[-1]
    rsi_value = r[-1]
    atr_value = a[-1]

    score = 50

    reasons = []

    # ---------------- TREND ----------------

    if ema20 and price > ema20:
        score += 8
        reasons.append("السعر فوق EMA20")
    else:
        score -= 8

    if ema50 and price > ema50:
        score += 8
        reasons.append("السعر فوق EMA50")
    else:
        score -= 8

    if ema200:
        if price > ema200:
            score += 12
            reasons.append("الاتجاه فوق EMA200")
        else:
            score -= 12
            reasons.append("السعر تحت EMA200")

    # ---------------- RSI ----------------

    if rsi_value is not None:
        if 50 <= rsi_value <= 68:
            score += 8
            reasons.append("RSI إيجابي")
        elif rsi_value > 72:
            score -= 3
            reasons.append("RSI مرتفع")
        elif rsi_value < 35:
            score += 3
            reasons.append("RSI منخفض")

    # ---------------- MOMENTUM ----------------

    if len(closes) >= 6:
        move = (
            (closes[-1] - closes[-6])
            / closes[-6]
        ) * 100

        if move > 0:
            score += min(10, move * 2)
            reasons.append("زخم صاعد")
        elif move < 0:
            score -= min(10, abs(move) * 2)
            reasons.append("زخم هابط")

    # ---------------- VOLUME ----------------

    if len(volumes) >= 21:
        avg_volume = sum(volumes[-21:-1]) / 20

        if avg_volume > 0:
            volume_ratio = volumes[-1] / avg_volume

            if volume_ratio >= 1.5:
                score += 8
                reasons.append("حجم تداول مرتفع")
            elif volume_ratio < 0.6:
                score -= 3
    else:
        volume_ratio = 1

    # ---------------- CANDLE ----------------

    candle = candles[-1]

    candle_change = (
        (candle["c"] - candle["o"])
        / candle["o"]
    ) * 100

    if candle_change > 0:
        score += 5
    elif candle_change < 0:
        score -= 5

    # ---------------- SUPPORT / RESISTANCE ----------------

    recent = candles[-20:]

    support = min(x["l"] for x in recent)
    resistance = max(x["h"] for x in recent)

    # ---------------- SCORE ----------------

    score = max(0, min(100, round(score)))

    if score >= 78:
        signal = "شراء قوي"
        direction = "BUY"
    elif score >= 62:
        signal = "شراء"
        direction = "BUY"
    elif score <= 22:
        signal = "بيع قوي"
        direction = "SELL"
    elif score <= 38:
        signal = "بيع"
        direction = "SELL"
    else:
        signal = "محايد"
        direction = "NEUTRAL"

    # ---------------- TP / SL ----------------

    if atr_value and atr_value > 0:
        risk = max(
            atr_value * 1.2,
            price * 0.01
        )
    else:
        risk = price * 0.01

    if direction == "BUY":
        entry = price
        stop = price - risk
        target = price + risk * 2
    elif direction == "SELL":
        entry = price
        stop = price + risk
        target = price - risk * 2
    else:
        entry = price
        stop = price - risk
        target = price + risk * 2

    change_24 = 0

    if len(closes) >= 2:
        change_24 = (
            (closes[-1] - closes[-2])
            / closes[-2]
        ) * 100

    return {
        "symbol": symbol,
        "market": market,
        "market_name": MARKET_NAMES.get(
            market,
            market
        ),
        "interval": interval,

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10": round(score / 10, 1),

        "price": round(price, 10),
        "entry": round(entry, 10),
        "target": round(target, 10),
        "tp": round(target, 10),
        "stop": round(stop, 10),
        "sl": round(stop, 10),

        "change": round(change_24, 3),
        "change_percent": round(change_24, 3),

        "rsi": (
            round(rsi_value, 2)
            if rsi_value is not None
            else None
        ),

        "ema20": (
            round(ema20, 10)
            if ema20 is not None
            else None
        ),

        "ema50": (
            round(ema50, 10)
            if ema50 is not None
            else None
        ),

        "ema200": (
            round(ema200, 10)
            if ema200 is not None
            else None
        ),

        "atr": (
            round(atr_value, 10)
            if atr_value is not None
            else None
        ),

        "support": round(support, 10),
        "resistance": round(resistance, 10),

        "volume_ratio": round(
            volume_ratio,
            2
        ),

        "candle_change": round(
            candle_change,
            3
        ),

        "reasons": reasons[:5],

        "time": now_iso(),
    }


# =========================================================
# FETCH + ANALYZE
# =========================================================

def analyze_one(symbol, market, interval):
    try:
        candles = fetch_candles(
            symbol,
            market,
            interval
        )

        return analyze(
            symbol,
            market,
            interval,
            candles
        )

    except Exception as e:
        return {
            "symbol": symbol,
            "market": market,
            "market_name": MARKET_NAMES.get(
                market,
                market
            ),
            "interval": interval,
            "signal": "غير متاح",
            "direction": "ERROR",
            "score": 0,
            "score10": 0,
            "price": 0,
            "error": str(e),
            "time": now_iso(),
        }


def scan_market(market, interval, limit=MAX_RESULTS):
    symbols = MARKETS.get(market, [])

    results = []

    # تنفيذ متوازي لكن بعدد صغير حتى ما نضغط على المصدر
    workers = min(
        MAX_WORKERS,
        max(1, len(symbols))
    )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = [
            executor.submit(
                analyze_one,
                symbol,
                market,
                interval
            )
            for symbol in symbols
        ]

        for future in as_completed(futures):
            try:
                item = future.result()

                if item.get("direction") != "ERROR":
                    results.append(item)

            except Exception:
                pass

    results.sort(
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    return results[:limit]


def scan_all(interval, limit=MAX_RESULTS):
    all_results = []

    # كل سوق بشكل مستقل
    for market in MARKETS:
        results = scan_market(
            market,
            interval,
            limit=limit
        )

        all_results.extend(results)

    # الأقوى أولاً
    all_results.sort(
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    return all_results[:MAX_RESULTS]


# =========================================================
# API
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "status": "online",
        "service": "Mudarib Abo Saud",
        "version": "LIGHT-1.0",
        "time": now_iso(),
    })


@app.route("/api/scan")
def api_scan():
    from flask import request

    interval = request.args.get(
        "interval",
        "15m"
    )

    market = request.args.get(
        "market",
        "all"
    )

    try:
        limit = int(
            request.args.get(
                "limit",
                MAX_RESULTS
            )
        )
    except Exception:
        limit = MAX_RESULTS

    limit = max(
        1,
        min(limit, MAX_RESULTS)
    )

    cache_key = f"scan:{market}:{interval}:{limit}"

    old = cache_get(cache_key)

    if old:
        return jsonify({
            "ok": True,
            "cached": True,
            "interval": interval,
            "market": market,
            "count": len(old),
            "results": old,
            "signals": old,
            "time": now_iso(),
        })

    if market == "all":
        results = scan_all(
            interval,
            limit
        )
    else:
        results = scan_market(
            market,
            interval,
            limit
        )

    cache_set(
        cache_key,
        results
    )

    return jsonify({
        "ok": True,
        "cached": False,
        "interval": interval,
        "market": market,
        "count": len(results),
        "results": results,
        "signals": results,
        "time": now_iso(),
    })


@app.route("/api/signals")
def api_signals():
    return api_scan()


@app.route("/api/market-signals")
def api_market_signals():
    return api_scan()


@app.route("/api/analysis/<symbol>")
def api_analysis(symbol):
    from flask import request

    interval = request.args.get(
        "interval",
        "15m"
    )

    symbol = symbol.upper()

    market = "crypto"

    for market_name, symbols in MARKETS.items():
        if symbol in symbols:
            market = market_name
            break

    result = analyze_one(
        symbol,
        market,
        interval
    )

    return jsonify({
        "ok": result.get("direction") != "ERROR",
        "result": result,
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
