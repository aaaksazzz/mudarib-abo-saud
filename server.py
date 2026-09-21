import os
import time
import math
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", template_folder=".")

# ============================================================
# تحليل العملات الرقمية
# Binance Public Market Data
# لا يحتاج API Key
# ============================================================

BINANCE_DATA_API = "https://data-api.binance.vision"

# مصادر احتياطية
BINANCE_FALLBACKS = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoAnalysisSite/1.0"
})

CACHE = {}
CACHE_TTL = 20


# ============================================================
# أدوات عامة
# ============================================================

def cache_get(key):
    item = CACHE.get(key)

    if not item:
        return None

    if time.time() - item["time"] > CACHE_TTL:
        del CACHE[key]
        return None

    return item["data"]


def cache_set(key, data):
    CACHE[key] = {
        "time": time.time(),
        "data": data
    }


def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def http_get(path, params=None, timeout=15):
    """
    يجرب data-api.binance.vision أولاً.
    إذا فشل يجرب المصادر الاحتياطية.
    """

    errors = []

    for base in BINANCE_FALLBACKS:
        url = base + path

        try:
            r = SESSION.get(
                url,
                params=params,
                timeout=timeout
            )

            if r.status_code == 200:
                return {
                    "ok": True,
                    "data": r.json(),
                    "api": base,
                    "status": 200
                }

            text = r.text[:500]

            errors.append({
                "api": base,
                "status": r.status_code,
                "message": text
            })

        except Exception as e:
            errors.append({
                "api": base,
                "status": None,
                "message": str(e)
            })

    return {
        "ok": False,
        "errors": errors
    }


# ============================================================
# الصفحة الرئيسية
# ============================================================

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


# ============================================================
# اختبار اتصال Binance
# ============================================================

@app.route("/api/binance/test")
def binance_test():

    result = http_get("/api/v3/ping")

    if result["ok"]:
        return jsonify({
            "ok": True,
            "service": "Binance",
            "api": result["api"],
            "status": result["status"],
            "message": "اتصال Binance يعمل"
        })

    return jsonify({
        "ok": False,
        "service": "Binance",
        "message": "فشل الاتصال ببيانات Binance",
        "errors": result["errors"]
    }), 502


# ============================================================
# وقت Binance
# ============================================================

@app.route("/api/binance/time")
def binance_time():

    result = http_get("/api/v3/time")

    if not result["ok"]:
        return jsonify({
            "ok": False,
            "message": "فشل الحصول على وقت Binance",
            "errors": result["errors"]
        }), 502

    return jsonify({
        "ok": True,
        "serverTime": result["data"].get("serverTime"),
        "api": result["api"]
    })


# ============================================================
# جميع عملات Spot USDT
# ============================================================

@app.route("/api/binance/markets")
def markets():

    cached = cache_get("markets")

    if cached:
        return jsonify(cached)

    result = http_get(
        "/api/v3/exchangeInfo",
        params={
            "permissions": "SPOT"
        },
        timeout=25
    )

    if not result["ok"]:
        return jsonify({
            "ok": False,
            "message": "فشل جلب العملات من Binance",
            "errors": result["errors"]
        }), 502

    data = result["data"]

    symbols = []

    for s in data.get("symbols", []):

        symbol = s.get("symbol", "")
        status = s.get("status")

        quote = s.get("quoteAsset")

        if (
            quote == "USDT"
            and status == "TRADING"
        ):
            symbols.append({
                "symbol": symbol,
                "baseAsset": s.get("baseAsset"),
                "quoteAsset": quote,
                "status": status
            })

    response = {
        "ok": True,
        "count": len(symbols),
        "symbols": symbols,
        "api": result["api"]
    }

    cache_set("markets", response)

    return jsonify(response)


# ============================================================
# الأسعار الحالية
# ============================================================

@app.route("/api/binance/prices")
def prices():

    cached = cache_get("prices")

    if cached:
        return jsonify(cached)

    result = http_get(
        "/api/v3/ticker/24hr",
        timeout=25
    )

    if not result["ok"]:
        return jsonify({
            "ok": False,
            "message": "فشل جلب الأسعار",
            "errors": result["errors"]
        }), 502

    data = result["data"]

    output = []

    if isinstance(data, list):

        for item in data:

            if item.get("symbol", "").endswith("USDT"):

                output.append({
                    "symbol": item.get("symbol"),
                    "price": safe_float(item.get("lastPrice")),
                    "change24h": safe_float(item.get("priceChangePercent")),
                    "volume": safe_float(item.get("quoteVolume")),
                    "high24h": safe_float(item.get("highPrice")),
                    "low24h": safe_float(item.get("lowPrice"))
                })

    response = {
        "ok": True,
        "count": len(output),
        "prices": output,
        "api": result["api"]
    }

    cache_set("prices", response)

    return jsonify(response)


# ============================================================
# سعر عملة واحدة
# ============================================================

@app.route("/api/binance/price")
def price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    result = http_get(
        "/api/v3/ticker/24hr",
        params={
            "symbol": symbol
        }
    )

    if not result["ok"]:
        return jsonify({
            "ok": False,
            "message": "فشل جلب السعر",
            "errors": result["errors"]
        }), 502

    item = result["data"]

    return jsonify({
        "ok": True,
        "symbol": item.get("symbol"),
        "price": safe_float(item.get("lastPrice")),
        "change24h": safe_float(item.get("priceChangePercent")),
        "volume": safe_float(item.get("quoteVolume")),
        "high24h": safe_float(item.get("highPrice")),
        "low24h": safe_float(item.get("lowPrice")),
        "api": result["api"]
    })


# ============================================================
# الشموع
# ============================================================

@app.route("/api/binance/klines")
def klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:
        limit = int(
            request.args.get(
                "limit",
                200
            )
        )
    except:
        limit = 200

    limit = max(20, min(limit, 1000))

    allowed_intervals = [
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w",
        "1M"
    ]

    if interval not in allowed_intervals:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    result = http_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=20
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "message": "فشل جلب الشموع",
            "errors": result["errors"]
        }), 502

    candles = []

    for x in result["data"]:

        candles.append({
            "time": int(x[0]),
            "open": safe_float(x[1]),
            "high": safe_float(x[2]),
            "low": safe_float(x[3]),
            "close": safe_float(x[4]),
            "volume": safe_float(x[5]),
            "closeTime": int(x[6]),
            "trades": int(x[8])
        })

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
        "api": result["api"]
    })


# ============================================================
# المؤشرات الفنية
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def macd(values):

    if len(values) < 35:
        return {
            "macd": None,
            "signal": None,
            "histogram": None
        }

    # حساب MACD لكل نقطة
    fast = []
    slow = []

    multiplier_fast = 2 / 10
    multiplier_slow = 2 / 27

    fast_value = sum(values[:12]) / 12
    slow_value = sum(values[:26]) / 26

    macd_values = []

    for i, price in enumerate(values):

        if i >= 12:
            fast_value = (
                (price - fast_value)
                * multiplier_fast
            ) + fast_value

        if i >= 26:
            slow_value = (
                (price - slow_value)
                * multiplier_slow
            ) + slow_value

            macd_values.append(
                fast_value - slow_value
            )

    if len(macd_values) < 9:
        return {
            "macd": None,
            "signal": None,
            "histogram": None
        }

    signal = sum(macd_values[:9]) / 9
    multiplier_signal = 2 / 10

    for value in macd_values[9:]:
        signal = (
            (value - signal)
            * multiplier_signal
        ) + signal

    current_macd = macd_values[-1]

    return {
        "macd": current_macd,
        "signal": signal,
        "histogram": current_macd - signal
    }


def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    return sum(trs[-period:]) / period


# ============================================================
# تحليل فني
# ============================================================

def calculate_analysis(candles):

    closes = [x["close"] for x in candles]

    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]

    volumes = [x["volume"] for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi14 = rsi(closes, 14)

    macd_data = macd(closes)

    atr14 = atr(candles, 14)

    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])

    average_volume = (
        sum(volumes[-20:]) / 20
        if len(volumes) >= 20
        else None
    )

    current_volume = volumes[-1]

    volume_ratio = None

    if average_volume and average_volume > 0:
        volume_ratio = current_volume / average_volume

    score = 0
    reasons = []

    # --------------------------
    # الاتجاه
    # --------------------------

    if ema20 and price > ema20:

        score += 1
        reasons.append("السعر فوق EMA20")

    else:

        score -= 1
        reasons.append("السعر تحت EMA20")

    if ema50 and price > ema50:

        score += 1
        reasons.append("السعر فوق EMA50")

    else:

        score -= 1
        reasons.append("السعر تحت EMA50")

    if ema200 and price > ema200:

        score += 2
        reasons.append("السعر فوق EMA200")

    elif ema200:

        score -= 2
        reasons.append("السعر تحت EMA200")

    # --------------------------
    # RSI
    # --------------------------

    if rsi14 is not None:

        if 50 <= rsi14 <= 70:

            score += 1
            reasons.append("RSI يدعم الاتجاه الصاعد")

        elif rsi14 < 30:

            score += 1
            reasons.append("RSI في منطقة تشبع بيع")

        elif rsi14 > 75:

            score -= 1
            reasons.append("RSI مرتفع")

    # --------------------------
    # MACD
    # --------------------------

    if macd_data["histogram"] is not None:

        if macd_data["histogram"] > 0:

            score += 1
            reasons.append("MACD إيجابي")

        else:

            score -= 1
            reasons.append("MACD سلبي")

    # --------------------------
    # حجم التداول
    # --------------------------

    if volume_ratio is not None:

        if volume_ratio >= 1.5:

            score += 2
            reasons.append("ارتفاع قوي في حجم التداول")

        elif volume_ratio >= 1.1:

            score += 1
            reasons.append("حجم التداول أعلى من المتوسط")

    # --------------------------
    # اختراق
    # --------------------------

    previous_high = max(highs[-21:-1])

    if price > previous_high:

        score += 2
        reasons.append("اختراق قمة آخر 20 شمعة")

    # --------------------------
    # الدعم والمقاومة
    # --------------------------

    resistance = recent_high
    support = recent_low

    # --------------------------
    # التصنيف
    # --------------------------

    if score >= 6:

        signal = "شراء قوي"

    elif score >= 3:

        signal = "شراء"

    elif score <= -6:

        signal = "بيع قوي"

    elif score <= -3:

        signal = "بيع"

    else:

        signal = "حيادي"

    # --------------------------
    # أهداف تحليلية
    # --------------------------

    entry = price

    if atr14 and atr14 > 0:

        sl = entry - (atr14 * 1.5)

        tp1 = entry + (atr14 * 1.5)

        tp2 = entry + (atr14 * 2.5)

        tp3 = entry + (atr14 * 4)

    else:

        sl = entry * 0.98

        tp1 = entry * 1.02

        tp2 = entry * 1.04

        tp3 = entry * 1.06

    risk = abs(entry - sl)

    rr1 = (
        abs(tp1 - entry) / risk
        if risk > 0
        else 0
    )

    return {
        "signal": signal,
        "score": score,
        "price": price,

        "entry": entry,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "sl": sl,

        "rr": rr1,

        "rsi": rsi14,

        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,

        "macd": macd_data["macd"],
        "macdSignal": macd_data["signal"],
        "macdHistogram": macd_data["histogram"],

        "atr": atr14,

        "support": support,
        "resistance": resistance,

        "volumeRatio": volume_ratio,

        "reasons": reasons
    }


# ============================================================
# التحليل
# ============================================================

@app.route("/api/binance/analysis")
def analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    result = http_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": 250
        },
        timeout=25
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "message": "فشل جلب بيانات التحليل",
            "errors": result["errors"]
        }), 502

    raw = result["data"]

    candles = []

    for x in raw:

        candles.append({
            "time": int(x[0]),
            "open": safe_float(x[1]),
            "high": safe_float(x[2]),
            "low": safe_float(x[3]),
            "close": safe_float(x[4]),
            "volume": safe_float(x[5])
        })

    if len(candles) < 50:

        return jsonify({
            "ok": False,
            "message": "بيانات الشموع غير كافية للتحليل"
        }), 400

    result_analysis = calculate_analysis(candles)

    return jsonify({
        "ok": True,

        "symbol": symbol,

        "interval": interval,

        "analysis": result_analysis,

        "candles": candles[-100:],

        "api": result["api"],

        "updated": int(time.time())
    })


# ============================================================
# فحص سريع لعملة
# ============================================================

@app.route("/api/binance/scan")
def scan():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper()

    intervals = [
        "5m",
        "15m",
        "1h",
        "4h",
        "1d"
    ]

    results = {}

    for interval in intervals:

        result = http_get(
            "/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": 250
            },
            timeout=20
        )

        if not result["ok"]:

            results[interval] = {
                "ok": False
            }

            continue

        candles = []

        for x in result["data"]:

            candles.append({
                "time": int(x[0]),
                "open": safe_float(x[1]),
                "high": safe_float(x[2]),
                "low": safe_float(x[3]),
                "close": safe_float(x[4]),
                "volume": safe_float(x[5])
            })

        if len(candles) >= 50:

            results[interval] = {
                "ok": True,
                "analysis": calculate_analysis(candles)
            }

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "timeframes": results
    })


# ============================================================
# Health Check
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "تحليل العملات الرقمية"
    })


# ============================================================
# تشغيل محلي
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
