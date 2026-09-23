import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests
from flask import Flask, jsonify, render_template, request


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 Mudarib-Abo-Saud/3.0"
})

CACHE = {}
CACHE_LOCK = threading.Lock()

CACHE_SECONDS = 30
SCAN_CACHE_SECONDS = 45


# =========================================================
# الأسواق
# =========================================================

MARKETS = {

    "crypto": {
        "name": "العملات الرقمية",
        "symbols": [
            "BTC-USD",
            "ETH-USD",
            "BNB-USD",
            "SOL-USD",
            "XRP-USD",
            "DOGE-USD",
            "ADA-USD",
            "AVAX-USD",
            "LINK-USD",
            "DOT-USD",
            "TRX-USD",
            "LTC-USD",
            "BCH-USD",
            "UNI-USD",
            "ATOM-USD",
        ]
    },

    "saudi": {
        "name": "السوق السعودي",
        "symbols": [
            "^TASI.SR",
            "2222.SR",
            "1120.SR",
            "2010.SR",
            "1180.SR",
            "1150.SR",
            "1050.SR",
            "1010.SR",
            "1060.SR",
            "1080.SR",
            "2020.SR",
            "1211.SR",
            "4003.SR",
            "4030.SR",
            "4001.SR",
            "4261.SR",
            "4200.SR",
            "2050.SR",
            "2060.SR",
            "2380.SR",
        ]
    },

    "forex": {
        "name": "الفوركس",
        "symbols": [
            "EURUSD=X",
            "GBPUSD=X",
            "USDJPY=X",
            "USDCHF=X",
            "AUDUSD=X",
            "USDCAD=X",
            "NZDUSD=X",
            "EURGBP=X",
            "EURJPY=X",
            "GBPJPY=X",
            "USDTRY=X",
            "USDSAR=X",
        ]
    },

    "us": {
        "name": "الأسهم الأمريكية",
        "symbols": [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "META",
            "TSLA",
            "GOOGL",
            "GOOG",
            "AMD",
            "NFLX",
            "AVGO",
            "INTC",
            "MU",
            "PLTR",
            "COIN",
            "MSTR",
            "JPM",
            "BAC",
            "WMT",
            "COST",
        ]
    },

    "commodities": {
        "name": "السلع",
        "symbols": [
            "GC=F",
            "SI=F",
            "CL=F",
            "BZ=F",
            "NG=F",
        ]
    },

    "indices": {
        "name": "المؤشرات",
        "symbols": [
            "^GSPC",
            "^NDX",
            "^DJI",
            "^RUT",
            "^FTSE",
            "^GDAXI",
            "^N225",
            "^HSI",
            "DX-Y.NYB",
        ]
    },

    "futures": {
        "name": "الفيوتشرز",
        "symbols": [
            "ES=F",
            "NQ=F",
            "YM=F",
            "RTY=F",
            "GC=F",
            "SI=F",
            "CL=F",
            "NG=F",
        ]
    }
}


# =========================================================
# أسماء العرض
# =========================================================

DISPLAY_NAMES = {

    "^TASI.SR": "تاسي",
    "2222.SR": "أرامكو",
    "1120.SR": "الراجحي",
    "2010.SR": "سابك",
    "1180.SR": "الأهلي السعودي",
    "1150.SR": "مصرف الإنماء",

    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "NZDUSD=X": "NZD/USD",
    "EURGBP=X": "EUR/GBP",
    "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY",
    "USDTRY=X": "USD/TRY",
    "USDSAR=X": "USD/SAR",

    "GC=F": "الذهب",
    "SI=F": "الفضة",
    "CL=F": "النفط الأمريكي",
    "BZ=F": "برنت",
    "NG=F": "الغاز الطبيعي",

    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
    "DX-Y.NYB": "DXY",

    "ES=F": "S&P Futures",
    "NQ=F": "Nasdaq Futures",
    "YM=F": "Dow Futures",
    "RTY=F": "Russell Futures",
}


# =========================================================
# أدوات عامة
# =========================================================

def now_ms():
    return int(time.time() * 1000)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def display_name(symbol):
    return DISPLAY_NAMES.get(
        symbol,
        symbol.replace("-USD", "")
             .replace(".SR", "")
             .replace("=X", "")
    )


def interval_normalize(interval):
    allowed = {
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "1h",
        "1d": "1d",
    }

    return allowed.get(interval, "15m")


# =========================================================
# Yahoo Finance
# =========================================================

def yahoo_chart(symbol, interval="15m", limit=220):

    interval = interval_normalize(interval)

    if interval == "5m":
        range_value = "5d"
    elif interval == "15m":
        range_value = "10d"
    elif interval == "1h":
        range_value = "1mo"
    else:
        range_value = "1y"

    key = f"yf:{symbol}:{interval}"

    with CACHE_LOCK:
        item = CACHE.get(key)

    if item and time.time() - item["ts"] < CACHE_SECONDS:
        return item["data"]

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + requests.utils.quote(symbol, safe="")
    )

    params = {
        "interval": interval,
        "range": range_value,
        "events": "history",
        "includeAdjustedClose": "true"
    }

    response = HTTP.get(
        url,
        params=params,
        timeout=7
    )

    response.raise_for_status()

    data = response.json()

    result = data.get("chart", {}).get("result")

    if not result:
        raise RuntimeError("بيانات السوق غير متوفرة")

    result = result[0]

    timestamps = result.get("timestamp") or []
    quote = (
        result.get("indicators", {})
        .get("quote", [{}])[0]
    )

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles = []

    for i in range(len(timestamps)):

        if i >= len(opens):
            continue

        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]

        if None in (o, h, l, c):
            continue

        candles.append({
            "t": int(timestamps[i]) * 1000,
            "o": safe_float(o),
            "h": safe_float(h),
            "l": safe_float(l),
            "c": safe_float(c),
            "v": safe_float(
                volumes[i] if i < len(volumes) else 0
            )
        })

    candles = candles[-limit:]

    if len(candles) < 30:
        raise RuntimeError("عدد الشموع غير كافٍ للتحليل")

    with CACHE_LOCK:
        CACHE[key] = {
            "ts": time.time(),
            "data": candles
        }

    return candles


# =========================================================
# المؤشرات
# =========================================================

def ema(values, period):

    if not values:
        return 0.0

    if len(values) < period:
        period = len(values)

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        value = (
            price * multiplier
            + value * (1 - multiplier)
        )

    return value


def rsi(values, period=14):

    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):

    if len(candles) < 2:
        return 0.0

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["h"]
        low = current["l"]
        previous_close = previous["c"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    if not trs:
        return 0.0

    sample = trs[-period:]

    return sum(sample) / len(sample)


def volume_ratio(candles, period=20):

    if len(candles) < period + 1:
        return 1.0

    current = candles[-1]["v"]

    previous = [
        x["v"]
        for x in candles[-period-1:-1]
        if x["v"] > 0
    ]

    if not previous:
        return 1.0

    average = sum(previous) / len(previous)

    if average <= 0:
        return 1.0

    return current / average


def momentum(candles, bars=5):

    if len(candles) <= bars:
        return 0.0

    old = candles[-bars-1]["c"]
    new = candles[-1]["c"]

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100


# =========================================================
# التحليل
# =========================================================

def analyze(candles):

    closes = [x["c"] for x in candles]
    highs = [x["h"] for x in candles]
    lows = [x["l"] for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi_value = rsi(closes, 14)
    atr_value = atr(candles, 14)
    vol_ratio = volume_ratio(candles, 20)
    mom = momentum(candles, 5)

    score = 50
    reasons = []

    # -----------------------------------------------------
    # EMA20
    # -----------------------------------------------------

    if price > ema20:
        score += 8
        reasons.append("السعر فوق EMA20")
    else:
        score -= 8
        reasons.append("السعر تحت EMA20")

    # -----------------------------------------------------
    # EMA50
    # -----------------------------------------------------

    if price > ema50:
        score += 8
        reasons.append("السعر فوق EMA50")
    else:
        score -= 8
        reasons.append("السعر تحت EMA50")

    # -----------------------------------------------------
    # EMA200
    # -----------------------------------------------------

    if price > ema200:
        score += 12
        reasons.append("الاتجاه فوق EMA200")
    else:
        score -= 12
        reasons.append("الاتجاه تحت EMA200")

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if 52 <= rsi_value <= 68:

        score += 8
        reasons.append("RSI إيجابي")

    elif 68 < rsi_value <= 75:

        score += 3
        reasons.append("RSI مرتفع")

    elif 30 <= rsi_value < 48:

        score -= 3
        reasons.append("RSI ضعيف")

    elif rsi_value < 30:

        score += 2
        reasons.append("RSI في تشبع بيعي")

    else:

        score -= 5
        reasons.append("RSI غير مناسب")

    # -----------------------------------------------------
    # Momentum
    # -----------------------------------------------------

    if mom > 0.25:

        score += 8
        reasons.append("الزخم صاعد")

    elif mom < -0.25:

        score -= 8
        reasons.append("الزخم هابط")

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    if vol_ratio >= 1.5:

        if mom > 0:
            score += 8
            reasons.append("حجم تداول مرتفع مع صعود")
        else:
            score -= 8
            reasons.append("حجم مرتفع مع هبوط")

    elif vol_ratio >= 1.15:

        score += 3
        reasons.append("حجم التداول جيد")

    # -----------------------------------------------------
    # تثبيت النتيجة
    # -----------------------------------------------------

    score = max(0, min(100, round(score)))

    if score >= 80:

        signal = "شراء قوي"
        direction = "buy"

    elif score >= 65:

        signal = "شراء"
        direction = "buy"

    elif score <= 20:

        signal = "بيع قوي"
        direction = "sell"

    elif score <= 35:

        signal = "بيع"
        direction = "sell"

    else:

        signal = "حيادي"
        direction = "neutral"

    # -----------------------------------------------------
    # Entry / TP / SL
    # -----------------------------------------------------

    volatility = atr_value

    if volatility <= 0:
        volatility = price * 0.01

    risk = max(
        volatility * 1.2,
        price * 0.005
    )

    if direction == "buy":

        entry = price
        sl = max(price - risk, 0)

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.0
        tp3 = price + risk * 3.0

    elif direction == "sell":

        entry = price
        sl = price + risk

        tp1 = max(price - risk * 1.5, 0)
        tp2 = max(price - risk * 2.0, 0)
        tp3 = max(price - risk * 3.0, 0)

    else:

        entry = price
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

    support = min(lows[-20:])
    resistance = max(highs[-20:])

    return {
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(score / 10, 1),

        "price": price,
        "entry": entry,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,

        "rsi": round(rsi_value, 2),

        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,

        "atr": atr_value,
        "volumeRatio": round(vol_ratio, 2),
        "momentum": round(mom, 3),

        "support": support,
        "resistance": resistance,

        "reasons": reasons,

        "updatedAt": now_ms()
    }


# =========================================================
# تحليل رمز واحد
# =========================================================

def analyze_symbol(symbol, interval="15m", market=None):

    candles = yahoo_chart(
        symbol,
        interval,
        220
    )

    result = analyze(candles)

    result.update({
        "symbol": symbol,
        "name": display_name(symbol),
        "market": market,
        "interval": interval
    })

    return result


# =========================================================
# API
# =========================================================

@app.get("/")
def home():

    return render_template("index.html")


@app.get("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud",
        "time": now_ms()
    })


# =========================================================
# الأسواق
# =========================================================

@app.get("/api/markets")
def get_markets():

    output = {}

    for key, market in MARKETS.items():

        output[key] = {
            "name": market["name"],
            "count": len(market["symbols"]),
            "symbols": [
                {
                    "symbol": x,
                    "name": display_name(x)
                }
                for x in market["symbols"]
            ]
        }

    return jsonify({
        "ok": True,
        "markets": output
    })


# =========================================================
# تحليل
# =========================================================

@app.get("/api/analysis")
def api_analysis():

    symbol = request.args.get(
        "symbol",
        "BTC-USD"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        result = analyze_symbol(
            symbol,
            interval
        )

        return jsonify({
            "ok": True,
            "analysis": result
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# تحليل سوق كامل
# =========================================================

@app.get("/api/scan")
def api_scan():

    market = request.args.get(
        "market",
        "crypto"
    ).lower()

    interval = request.args.get(
        "interval",
        "15m"
    )

    limit = request.args.get(
        "limit",
        "20"
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 20

    limit = max(1, min(limit, 30))

    if market not in MARKETS:

        return jsonify({
            "ok": False,
            "message": "السوق غير موجود"
        }), 400

    cache_key = f"scan:{market}:{interval}"

    with CACHE_LOCK:

        cached = CACHE.get(cache_key)

    if cached:

        if time.time() - cached["ts"] < SCAN_CACHE_SECONDS:

            payload = dict(cached["data"])
            payload["cached"] = True

            return jsonify(payload)

    symbols = MARKETS[market]["symbols"]

    results = []

    def worker(symbol):

        try:

            return analyze_symbol(
                symbol,
                interval,
                market
            )

        except Exception:

            return None

    # خفيف على Render
    with ThreadPoolExecutor(
        max_workers=5
    ) as pool:

        futures = [
            pool.submit(worker, symbol)
            for symbol in symbols[:limit]
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

    # ترتيب الأقوى أولاً
    results.sort(
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    payload = {
        "ok": True,
        "market": market,
        "marketName": MARKETS[market]["name"],
        "interval": interval,
        "count": len(results),
        "results": results,
        "updatedAt": now_ms(),
        "cached": False
    }

    with CACHE_LOCK:

        CACHE[cache_key] = {
            "ts": time.time(),
            "data": payload
        }

    return jsonify(payload)


# =========================================================
# جميع الأسواق
# =========================================================

@app.get("/api/all-signals")
def all_signals():

    interval = request.args.get(
        "interval",
        "15m"
    )

    output = []

    # لا نفحص كل شيء في نفس اللحظة
    # حتى يبقى Render خفيف

    markets_to_scan = [
        "saudi",
        "forex",
        "crypto",
        "us",
        "commodities",
        "indices",
        "futures"
    ]

    def scan_market(market):

        try:

            symbols = MARKETS[market]["symbols"]

            local = []

            # أول 12 فقط لكل سوق
            # لتقليل الضغط

            for symbol in symbols[:12]:

                try:

                    result = analyze_symbol(
                        symbol,
                        interval,
                        market
                    )

                    if result["direction"] != "neutral":
                        local.append(result)

                except Exception:
                    continue

            return local

        except Exception:

            return []

    with ThreadPoolExecutor(
        max_workers=4
    ) as pool:

        futures = [
            pool.submit(
                scan_market,
                market
            )
            for market in markets_to_scan
        ]

        for future in as_completed(futures):

            try:
                output.extend(
                    future.result()
                )
            except Exception:
                pass

    # أقوى الإشارات أولاً
    output.sort(
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    return jsonify({
        "ok": True,
        "interval": interval,
        "count": len(output),
        "signals": output[:50],
        "updatedAt": now_ms()
    })


# =========================================================
# الصفقات فقط
# =========================================================

@app.get("/api/signals")
def signals():

    market = request.args.get(
        "market",
        "crypto"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        if market not in MARKETS:

            return jsonify({
                "ok": False,
                "message": "السوق غير موجود"
            }), 400

        symbols = MARKETS[market]["symbols"]

        results = []

        def worker(symbol):

            try:

                result = analyze_symbol(
                    symbol,
                    interval,
                    market
                )

                if result["direction"] == "neutral":
                    return None

                # نعرض فقط الإشارات الأقوى
                if result["score"] < 60:
                    return None

                return result

            except Exception:

                return None

        with ThreadPoolExecutor(
            max_workers=5
        ) as pool:

            futures = [
                pool.submit(worker, symbol)
                for symbol in symbols
            ]

            for future in as_completed(futures):

                try:

                    item = future.result()

                    if item:
                        results.append(item)

                except Exception:
                    pass

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        return jsonify({
            "ok": True,
            "market": market,
            "interval": interval,
            "count": len(results),
            "signals": results,
            "updatedAt": now_ms()
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# الأسعار
# =========================================================

@app.get("/api/price")
def api_price():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if not symbol:

        return jsonify({
            "ok": False,
            "message": "symbol مطلوب"
        }), 400

    try:

        candles = yahoo_chart(
            symbol,
            interval,
            30
        )

        last = candles[-1]
        previous = candles[-2]

        price = last["c"]

        if previous["c"]:

            change = (
                (price - previous["c"])
                / previous["c"]
            ) * 100

        else:

            change = 0

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "name": display_name(symbol),
            "price": price,
            "change": round(change, 4),
            "time": last["t"]
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# شمعات API فقط للتحليل
# لا يوجد شارت في الواجهة
# =========================================================

@app.get("/api/klines")
def api_klines():

    symbol = request.args.get(
        "symbol",
        "BTC-USD"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        candles = yahoo_chart(
            symbol,
            interval,
            220
        )

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "klines": candles
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e)
        }), 503


# =========================================================
# أقوى الصفقات
# =========================================================

@app.get("/api/top-signals")
def top_signals():

    interval = request.args.get(
        "interval",
        "15m"
    )

    all_results = []

    markets = [
        "saudi",
        "forex",
        "crypto",
        "us",
        "commodities",
        "indices",
        "futures"
    ]

    for market in markets:

        symbols = MARKETS[market]["symbols"]

        # 5 فقط من كل سوق
        for symbol in symbols[:5]:

            try:

                result = analyze_symbol(
                    symbol,
                    interval,
                    market
                )

                if (
                    result["direction"] != "neutral"
                    and result["score"] >= 65
                ):
                    all_results.append(result)

            except Exception:
                continue

    all_results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return jsonify({
        "ok": True,
        "signals": all_results[:20],
        "count": len(all_results),
        "updatedAt": now_ms()
    })


# =========================================================
# أخبار خفيفة
# =========================================================

NEWS_CACHE = {
    "ts": 0,
    "items": []
}


def clean_text(value):

    if not value:
        return ""

    value = value.replace(
        "<![CDATA[",
        ""
    ).replace(
        "]]>",
        ""
    )

    return " ".join(
        value.replace(
            "<![CDATA[",
            ""
        ).split()
    )


@app.get("/api/news")
def api_news():

    now = time.time()

    with CACHE_LOCK:

        if (
            NEWS_CACHE["items"]
            and now - NEWS_CACHE["ts"] < 600
        ):

            return jsonify({
                "ok": True,
                "news": NEWS_CACHE["items"],
                "cached": True
            })

    feeds = [
        (
            "CoinDesk",
            "https://www.coindesk.com/arc/outboundfeeds/rss/"
        ),
        (
            "Yahoo Finance",
            "https://finance.yahoo.com/news/rssindex"
        )
    ]

    items = []

    for source, url in feeds:

        try:

            response = HTTP.get(
                url,
                timeout=6
            )

            response.raise_for_status()

            root = ET.fromstring(
                response.content
            )

            for item in root.findall(".//item")[:10]:

                title = clean_text(
                    item.findtext("title")
                )

                link = (
                    item.findtext("link")
                    or ""
                )

                description = clean_text(
                    item.findtext("description")
                )

                pub = (
                    item.findtext("pubDate")
                    or ""
                )

                if title and link:

                    items.append({
                        "title": title,
                        "link": link,
                        "source": source,
                        "published": pub,
                        "description": description[:250]
                    })

        except Exception:
            continue

    items = items[:20]

    with CACHE_LOCK:

        NEWS_CACHE.update({
            "ts": time.time(),
            "items": items
        })

    return jsonify({
        "ok": True,
        "news": items,
        "cached": False
    })


# =========================================================
# معلومات النظام
# =========================================================

@app.get("/api/status")
def api_status():

    return jsonify({
        "ok": True,
        "service": "مضارب أبو سعود",
        "version": "3.0-lite",
        "data": "Yahoo Finance",
        "markets": list(MARKETS.keys()),
        "serverTime": datetime.now(
            timezone.utc
        ).isoformat(),
        "features": {
            "signals": True,
            "analysis": True,
            "charts": False,
            "login": False,
            "database": False,
            "binance": False
        }
    })


# =========================================================
# تشغيل Render
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
