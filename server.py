import os
import time
import requests

from flask import Flask, jsonify, request, render_template

app = Flask(__name__, template_folder="templates", static_folder="static")

# ============================================================
# إعدادات Binance Market Data
# ============================================================

BINANCE_APIS = [
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
# الصفحة الرئيسية
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# لوحة الإدارة
# ============================================================

@app.route("/admin")
def admin():
    return render_template("admin.html")


# ============================================================
# Cache
# ============================================================

def get_cache(key):
    item = CACHE.get(key)

    if not item:
        return None

    if time.time() - item["time"] > CACHE_TTL:
        CACHE.pop(key, None)
        return None

    return item["data"]


def set_cache(key, data):
    CACHE[key] = {
        "time": time.time(),
        "data": data
    }


# ============================================================
# طلب Binance
# ============================================================

def binance_get(path, params=None, timeout=15):

    errors = []

    for base in BINANCE_APIS:

        url = base + path

        try:

            response = SESSION.get(
                url,
                params=params,
                timeout=timeout
            )

            if response.status_code == 200:

                return {
                    "ok": True,
                    "data": response.json(),
                    "api": base
                }

            errors.append({
                "api": base,
                "status": response.status_code,
                "message": response.text[:500]
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
# اختبار Binance
# ============================================================

@app.route("/api/binance/test")
def binance_test():

    result = binance_get("/api/v3/ping")

    if result["ok"]:

        return jsonify({
            "ok": True,
            "service": "Binance",
            "api": result["api"],
            "status": 200,
            "message": "اتصال Binance يعمل"
        })

    return jsonify({
        "ok": False,
        "service": "Binance",
        "message": "فشل الاتصال ببيانات Binance",
        "errors": result["errors"]
    }), 502


# ============================================================
# الوقت
# ============================================================

@app.route("/api/binance/time")
def binance_time():

    result = binance_get("/api/v3/time")

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "errors": result["errors"]
        }), 502

    return jsonify({
        "ok": True,
        "serverTime": result["data"].get("serverTime"),
        "api": result["api"]
    })


# ============================================================
# الأسواق
# ============================================================

@app.route("/api/binance/markets")
def markets():

    cached = get_cache("markets")

    if cached:
        return jsonify(cached)

    result = binance_get(
        "/api/v3/exchangeInfo",
        params={
            "permissions": "SPOT"
        },
        timeout=30
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "message": "فشل جلب العملات",
            "errors": result["errors"]
        }), 502

    symbols = []

    for item in result["data"].get("symbols", []):

        if (
            item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
        ):

            symbols.append({
                "symbol": item.get("symbol"),
                "baseAsset": item.get("baseAsset"),
                "quoteAsset": item.get("quoteAsset")
            })

    output = {
        "ok": True,
        "count": len(symbols),
        "symbols": symbols,
        "api": result["api"]
    }

    set_cache("markets", output)

    return jsonify(output)


# ============================================================
# الأسعار
# ============================================================

@app.route("/api/binance/prices")
def prices():

    cached = get_cache("prices")

    if cached:
        return jsonify(cached)

    result = binance_get(
        "/api/v3/ticker/24hr",
        timeout=30
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "message": "فشل جلب الأسعار",
            "errors": result["errors"]
        }), 502

    output = []

    if isinstance(result["data"], list):

        for item in result["data"]:

            symbol = item.get("symbol", "")

            if symbol.endswith("USDT"):

                output.append({
                    "symbol": symbol,
                    "price": float(item.get("lastPrice", 0)),
                    "change24h": float(
                        item.get("priceChangePercent", 0)
                    ),
                    "volume": float(
                        item.get("quoteVolume", 0)
                    ),
                    "high24h": float(
                        item.get("highPrice", 0)
                    ),
                    "low24h": float(
                        item.get("lowPrice", 0)
                    )
                })

    response = {
        "ok": True,
        "count": len(output),
        "prices": output,
        "api": result["api"]
    }

    set_cache("prices", response)

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

    result = binance_get(
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
        "price": float(item.get("lastPrice", 0)),
        "change24h": float(
            item.get("priceChangePercent", 0)
        ),
        "volume": float(
            item.get("quoteVolume", 0)
        ),
        "high24h": float(
            item.get("highPrice", 0)
        ),
        "low24h": float(
            item.get("lowPrice", 0)
        ),
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
                250
            )
        )
    except:
        limit = 250

    limit = max(20, min(limit, 1000))

    allowed = [
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

    if interval not in allowed:

        return jsonify({
            "ok": False,
            "message": "الفريم غير مدعوم"
        }), 400

    result = binance_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=30
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
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
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
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema_value = (
            (price - ema_value)
            * multiplier
        ) + ema_value

    return ema_value


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# MACD
# ============================================================

def calculate_macd(values):

    if len(values) < 35:

        return {
            "macd": None,
            "signal": None,
            "histogram": None
        }

    fast_values = []
    slow_values = []

    fast = sum(values[:12]) / 12
    slow = sum(values[:26]) / 26

    fast_multiplier = 2 / 13
    slow_multiplier = 2 / 27

    for i, price in enumerate(values):

        if i >= 12:

            fast = (
                (price - fast)
                * fast_multiplier
            ) + fast

        if i >= 26:

            slow = (
                (price - slow)
                * slow_multiplier
            ) + slow

            fast_values.append(fast)
            slow_values.append(slow)

    macd_values = [
        f - s
        for f, s in zip(
            fast_values,
            slow_values
        )
    ]

    if len(macd_values) < 9:

        return {
            "macd": None,
            "signal": None,
            "histogram": None
        }

    signal = sum(
        macd_values[:9]
    ) / 9

    multiplier = 2 / 10

    for value in macd_values[9:]:

        signal = (
            (value - signal)
            * multiplier
        ) + signal

    current = macd_values[-1]

    return {
        "macd": current,
        "signal": signal,
        "histogram": current - signal
    }


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous),
            abs(low - previous)
        )

        trs.append(tr)

    return sum(
        trs[-period:]
    ) / period


# ============================================================
# التحليل الفني
# ============================================================

def technical_analysis(candles):

    closes = [
        x["close"]
        for x in candles
    ]

    highs = [
        x["high"]
        for x in candles
    ]

    lows = [
        x["low"]
        for x in candles
    ]

    volumes = [
        x["volume"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    rsi14 = calculate_rsi(
        closes,
        14
    )

    macd = calculate_macd(
        closes
    )

    atr14 = calculate_atr(
        candles,
        14
    )

    score = 0
    reasons = []

    # الاتجاه

    if ema20:

        if price > ema20:
            score += 1
            reasons.append(
                "السعر فوق EMA20"
            )
        else:
            score -= 1
            reasons.append(
                "السعر تحت EMA20"
            )

    if ema50:

        if price > ema50:
            score += 1
            reasons.append(
                "السعر فوق EMA50"
            )
        else:
            score -= 1
            reasons.append(
                "السعر تحت EMA50"
            )

    if ema200:

        if price > ema200:
            score += 2
            reasons.append(
                "السعر فوق EMA200"
            )
        else:
            score -= 2
            reasons.append(
                "السعر تحت EMA200"
            )

    # RSI

    if rsi14 is not None:

        if 50 <= rsi14 <= 70:

            score += 1

            reasons.append(
                "RSI يدعم الصعود"
            )

        elif rsi14 < 30:

            score += 1

            reasons.append(
                "RSI في تشبع بيع"
            )

        elif rsi14 > 75:

            score -= 1

            reasons.append(
                "RSI مرتفع"
            )

    # MACD

    if macd["histogram"] is not None:

        if macd["histogram"] > 0:

            score += 1

            reasons.append(
                "MACD إيجابي"
            )

        else:

            score -= 1

            reasons.append(
                "MACD سلبي"
            )

    # الحجم

    average_volume = (
        sum(volumes[-20:]) / 20
        if len(volumes) >= 20
        else 0
    )

    volume_ratio = (
        volumes[-1] / average_volume
        if average_volume > 0
        else 0
    )

    if volume_ratio >= 1.5:

        score += 2

        reasons.append(
            "حجم التداول مرتفع"
        )

    elif volume_ratio >= 1.1:

        score += 1

        reasons.append(
            "حجم التداول أعلى من المتوسط"
        )

    # اختراق

    if len(highs) >= 21:

        previous_high = max(
            highs[-21:-1]
        )

        if price > previous_high:

            score += 2

            reasons.append(
                "اختراق قمة آخر 20 شمعة"
            )

    # دعم ومقاومة

    support = min(
        lows[-20:]
    )

    resistance = max(
        highs[-20:]
    )

    # التصنيف

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

    # الأهداف

    if atr14 and atr14 > 0:

        sl = price - atr14 * 1.5

        tp1 = price + atr14 * 1.5

        tp2 = price + atr14 * 2.5

        tp3 = price + atr14 * 4

    else:

        sl = price * 0.98

        tp1 = price * 1.02

        tp2 = price * 1.04

        tp3 = price * 1.06

    risk = abs(
        price - sl
    )

    rr = (
        abs(tp1 - price) / risk
        if risk > 0
        else 0
    )

    return {
        "signal": signal,
        "score": score,

        "price": price,

        "entry": price,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "sl": sl,

        "rr": rr,

        "rsi": rsi14,

        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,

        "macd": macd["macd"],
        "macdSignal": macd["signal"],
        "macdHistogram": macd["histogram"],

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

    result = binance_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": 250
        },
        timeout=30
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "message": "فشل جلب بيانات التحليل",
            "errors": result["errors"]
        }), 502

    candles = []

    for x in result["data"]:

        candles.append({
            "time": int(x[0]),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5])
        })

    if len(candles) < 50:

        return jsonify({
            "ok": False,
            "message": "بيانات غير كافية"
        }), 400

    result_analysis = technical_analysis(
        candles
    )

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
# Multi-Timeframe
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

        result = binance_get(
            "/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": 250
            },
            timeout=30
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
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            })

        if len(candles) >= 50:

            results[interval] = {
                "ok": True,
                "analysis": technical_analysis(
                    candles
                )
            }

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "timeframes": results
    })


# ============================================================
# Health
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "تحليل العملات الرقمية"
    })


# ============================================================
# تشغيل
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
