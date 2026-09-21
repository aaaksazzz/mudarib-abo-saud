import os
import time
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ============================================================
# إعدادات
# ============================================================

BINANCE_APIS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

TIMEOUT = 10
RETRIES = 2

CACHE = {}
CACHE_SECONDS = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 CryptoAnalysis/1.0",
    "Accept": "application/json",
}


# ============================================================
# Cache
# ============================================================

def cache_get(key):
    item = CACHE.get(key)

    if not item:
        return None

    timestamp, value = item

    if time.time() - timestamp > CACHE_SECONDS:
        CACHE.pop(key, None)
        return None

    return value


def cache_set(key, value):
    CACHE[key] = (time.time(), value)


# ============================================================
# اتصال Binance
# ============================================================

def binance_request(path, params=None):
    """
    يجرب أكثر من Binance API.
    """

    last_error = None

    for base in BINANCE_APIS:

        url = base + path

        for attempt in range(RETRIES):

            try:

                response = requests.get(
                    url,
                    params=params or {},
                    headers=HEADERS,
                    timeout=TIMEOUT
                )

                # نجاح
                if response.status_code == 200:

                    try:
                        data = response.json()
                    except Exception:
                        last_error = {
                            "type": "json",
                            "message": "Binance رجع بيانات غير صالحة",
                            "api": base
                        }
                        continue

                    # Binance API error
                    if (
                        isinstance(data, dict)
                        and "code" in data
                        and data.get("code", 0) < 0
                    ):
                        last_error = {
                            "type": "binance",
                            "message": data.get(
                                "msg",
                                "Binance API error"
                            ),
                            "code": data.get("code"),
                            "api": base
                        }
                        continue

                    return {
                        "ok": True,
                        "data": data,
                        "api": base
                    }

                last_error = {
                    "type": "http",
                    "status": response.status_code,
                    "message": response.text[:300],
                    "api": base
                }

            except requests.exceptions.Timeout:

                last_error = {
                    "type": "timeout",
                    "message": "انتهت مهلة الاتصال",
                    "api": base
                }

            except requests.exceptions.ConnectionError:

                last_error = {
                    "type": "connection",
                    "message": "تعذر الاتصال بـ Binance",
                    "api": base
                }

            except requests.exceptions.RequestException as e:

                last_error = {
                    "type": "request",
                    "message": str(e)[:300],
                    "api": base
                }

            except Exception as e:

                last_error = {
                    "type": "unknown",
                    "message": str(e)[:300],
                    "api": base
                }

            # انتظار بسيط قبل إعادة المحاولة
            if attempt < RETRIES - 1:
                time.sleep(0.5)

    return {
        "ok": False,
        "error": last_error or {
            "type": "unknown",
            "message": "فشل الاتصال بـ Binance"
        }
    }


# ============================================================
# الصفحة الرئيسية
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# Health
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "ok": True,
        "service": "تحليل العملات الرقمية",
        "server": "Render",
        "timestamp": int(time.time())
    })


# ============================================================
# اختبار اتصال Binance
# ============================================================

@app.route("/api/binance/test")
def test_binance():

    result = binance_request("/api/v3/ping")

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "service": "Binance",
            "message": "فشل الاتصال بـ Binance",
            "error": result["error"]
        }), 502

    return jsonify({
        "ok": True,
        "service": "Binance",
        "message": "الاتصال بـ Binance يعمل",
        "api": result["api"]
    })


# ============================================================
# Server Time
# ============================================================

@app.route("/api/binance/time")
def binance_time():

    result = binance_request("/api/v3/time")

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "error": result["error"]
        }), 502

    return jsonify({
        "ok": True,
        "data": result["data"],
        "api": result["api"]
    })


# ============================================================
# العملات والأسعار
# ============================================================

@app.route("/api/binance/markets")
def markets():

    cached = cache_get("markets")

    if cached is not None:
        return jsonify(cached)

    # --------------------------------------------------------
    # Exchange Info
    # --------------------------------------------------------

    info_result = binance_request(
        "/api/v3/exchangeInfo"
    )

    if not info_result["ok"]:

        return jsonify({
            "ok": False,
            "error": "تعذر الاتصال بـ Binance لجلب العملات",
            "details": info_result["error"]
        }), 502

    info = info_result["data"]

    if not isinstance(info, dict):

        return jsonify({
            "ok": False,
            "error": "Binance رجع استجابة غير صحيحة"
        }), 502

    symbols_info = info.get("symbols")

    if not isinstance(symbols_info, list):

        return jsonify({
            "ok": False,
            "error": "قائمة العملات غير موجودة في استجابة Binance",
            "keys": list(info.keys())[:20]
        }), 502

    # --------------------------------------------------------
    # تحديد USDT Spot
    # --------------------------------------------------------

    allowed = set()

    for item in symbols_info:

        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol")
        status = item.get("status")
        quote_asset = item.get("quoteAsset")

        spot_allowed = item.get(
            "isSpotTradingAllowed",
            True
        )

        if (
            symbol
            and status == "TRADING"
            and quote_asset == "USDT"
            and spot_allowed
        ):
            allowed.add(symbol)

    # --------------------------------------------------------
    # Ticker
    # --------------------------------------------------------

    ticker_result = binance_request(
        "/api/v3/ticker/24hr"
    )

    if not ticker_result["ok"]:

        return jsonify({
            "ok": False,
            "error": "تعذر جلب أسعار العملات من Binance",
            "details": ticker_result["error"]
        }), 502

    tickers = ticker_result["data"]

    if not isinstance(tickers, list):

        return jsonify({
            "ok": False,
            "error": "بيانات الأسعار غير صحيحة"
        }), 502

    # --------------------------------------------------------
    # تجهيز البيانات
    # --------------------------------------------------------

    markets_list = []

    for ticker in tickers:

        if not isinstance(ticker, dict):
            continue

        symbol = ticker.get("symbol")

        if symbol not in allowed:
            continue

        try:

            price = float(
                ticker.get(
                    "lastPrice",
                    0
                )
            )

            change = float(
                ticker.get(
                    "priceChangePercent",
                    0
                )
            )

            volume = float(
                ticker.get(
                    "quoteVolume",
                    0
                )
            )

            high = float(
                ticker.get(
                    "highPrice",
                    0
                )
            )

            low = float(
                ticker.get(
                    "lowPrice",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):
            continue

        markets_list.append({
            "symbol": symbol,
            "price": price,
            "change24h": change,
            "volume24h": volume,
            "high24h": high,
            "low24h": low
        })

    # ترتيب حسب السيولة
    markets_list.sort(
        key=lambda x: x["volume24h"],
        reverse=True
    )

    response = {
        "ok": True,
        "count": len(markets_list),
        "markets": markets_list,
        "api": {
            "exchangeInfo": info_result["api"],
            "ticker": ticker_result["api"]
        },
        "timestamp": int(time.time())
    }

    cache_set(
        "markets",
        response
    )

    return jsonify(response)


# ============================================================
# الشموع
# ============================================================

@app.route("/api/binance/klines")
def klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m"
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                "250"
            )
        )

    except ValueError:

        limit = 250

    limit = max(
        10,
        min(limit, 1000)
    )

    allowed_intervals = {
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
        "1w"
    }

    if interval not in allowed_intervals:

        return jsonify({
            "ok": False,
            "error": "الفريم غير مدعوم"
        }), 400

    result = binance_request(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "error": "تعذر جلب الشموع",
            "details": result["error"]
        }), 502

    data = result["data"]

    if not isinstance(data, list):

        return jsonify({
            "ok": False,
            "error": "استجابة الشموع غير صحيحة"
        }), 502

    candles = []

    for c in data:

        try:

            candles.append({
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5])
            })

        except (
            IndexError,
            TypeError,
            ValueError
        ):
            continue

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
        "api": result["api"],
        "timestamp": int(time.time())
    })


# ============================================================
# أدوات التحليل
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
        ) + result

    return result


def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# التحليل الفني
# ============================================================

@app.route("/api/binance/analysis")
def analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m"
    ).strip()

    allowed_intervals = {
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
        "1w"
    }

    if interval not in allowed_intervals:

        return jsonify({
            "ok": False,
            "error": "الفريم غير مدعوم"
        }), 400

    result = binance_request(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 250
        }
    )

    if not result["ok"]:

        return jsonify({
            "ok": False,
            "error": "تعذر جلب بيانات التحليل",
            "details": result["error"]
        }), 502

    raw = result["data"]

    if not isinstance(raw, list):

        return jsonify({
            "ok": False,
            "error": "بيانات Binance غير صحيحة"
        }), 502

    closes = []
    highs = []
    lows = []
    volumes = []

    for candle in raw:

        try:

            closes.append(
                float(candle[4])
            )

            highs.append(
                float(candle[2])
            )

            lows.append(
                float(candle[3])
            )

            volumes.append(
                float(candle[5])
            )

        except (
            IndexError,
            TypeError,
            ValueError
        ):
            continue

    if len(closes) < 30:

        return jsonify({
            "ok": False,
            "error": "البيانات غير كافية للتحليل"
        }), 502

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema200 = ema(
        closes,
        200
    )

    rsi14 = rsi(
        closes,
        14
    )

    resistance = max(
        highs[-20:]
    )

    support = min(
        lows[-20:]
    )

    avg_volume = (
        sum(volumes[-20:])
        / min(
            20,
            len(volumes)
        )
    )

    volume_ratio = (
        volumes[-1]
        / avg_volume
        if avg_volume > 0
        else 0
    )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    score = 0
    reasons = []

    if ema20 is not None:

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

    if ema50 is not None:

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

    if ema200 is not None:

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

    if rsi14 is not None:

        if 55 <= rsi14 < 70:

            score += 1
            reasons.append(
                "RSI إيجابي"
            )

        elif 30 < rsi14 < 45:

            score -= 1
            reasons.append(
                "RSI سلبي"
            )

        elif rsi14 >= 70:

            reasons.append(
                "RSI مرتفع"
            )

        elif rsi14 <= 30:

            reasons.append(
                "RSI منخفض"
            )

        else:

            reasons.append(
                "RSI حيادي"
            )

    if volume_ratio >= 1.5:

        if score > 0:
            score += 1

        elif score < 0:
            score -= 1

        reasons.append(
            "حجم التداول أعلى من المتوسط"
        )

    # --------------------------------------------------------
    # الإشارة
    # --------------------------------------------------------

    if score >= 4:

        signal = "شراء قوي"
        signal_code = "STRONG_BUY"

    elif score >= 2:

        signal = "شراء"
        signal_code = "BUY"

    elif score <= -4:

        signal = "بيع قوي"
        signal_code = "STRONG_SELL"

    elif score <= -2:

        signal = "بيع"
        signal_code = "SELL"

    else:

        signal = "حيادي"
        signal_code = "NEUTRAL"

    return jsonify({

        "ok": True,

        "symbol": symbol,

        "interval": interval,

        "price": price,

        "signal": signal,

        "signal_code": signal_code,

        "score": score,

        "indicators": {

            "ema20": ema20,

            "ema50": ema50,

            "ema200": ema200,

            "rsi14": rsi14,

            "volume_ratio": volume_ratio

        },

        "levels": {

            "support": support,

            "resistance": resistance

        },

        "reasons": reasons,

        "candles": len(closes),

        "api": result["api"],

        "timestamp": int(time.time())

    })


# ============================================================
# تشغيل
# ============================================================

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
        debug=False
    )
