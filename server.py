import os
import time
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ============================================================
# إعدادات
# ============================================================

BINANCE = "https://api.binance.com"

REQUEST_TIMEOUT = 15

# تخزين مؤقت بسيط لتقليل الضغط على Binance
CACHE = {}
CACHE_SECONDS = 20


# ============================================================
# أدوات Binance
# ============================================================

def binance_get(path, params=None, timeout=REQUEST_TIMEOUT):
    """
    اتصال آمن مع Binance.
    إذا صار خطأ يرجع None بدل ما يطيح السيرفر.
    """

    url = BINANCE + path

    try:
        response = requests.get(
            url,
            params=params or {},
            timeout=timeout,
            headers={
                "User-Agent": "CryptoAnalysis/1.0"
            }
        )

        # أخطاء HTTP
        if response.status_code != 200:
            return {
                "_error": True,
                "_status": response.status_code,
                "_message": f"Binance HTTP {response.status_code}",
                "_body": response.text[:500]
            }

        try:
            data = response.json()
        except Exception:
            return {
                "_error": True,
                "_status": response.status_code,
                "_message": "Binance returned invalid JSON",
                "_body": response.text[:500]
            }

        # Binance ممكن يرجع JSON فيه code/msg
        if isinstance(data, dict) and "code" in data and data.get("code", 0) < 0:
            return {
                "_error": True,
                "_status": response.status_code,
                "_message": data.get("msg", "Binance API error"),
                "_code": data.get("code")
            }

        return data

    except requests.exceptions.Timeout:
        return {
            "_error": True,
            "_message": "انتهت مهلة الاتصال مع Binance"
        }

    except requests.exceptions.ConnectionError:
        return {
            "_error": True,
            "_message": "تعذر الاتصال بـ Binance"
        }

    except requests.exceptions.RequestException as e:
        return {
            "_error": True,
            "_message": f"خطأ اتصال: {str(e)[:200]}"
        }

    except Exception as e:
        return {
            "_error": True,
            "_message": f"خطأ غير متوقع: {str(e)[:200]}"
        }


def cache_get(key):
    item = CACHE.get(key)

    if not item:
        return None

    timestamp, data = item

    if time.time() - timestamp > CACHE_SECONDS:
        CACHE.pop(key, None)
        return None

    return data


def cache_set(key, data):
    CACHE[key] = (time.time(), data)


# ============================================================
# الصفحة الرئيسية
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# فحص السيرفر
# ============================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "تحليل العملات الرقمية",
        "server_time": int(time.time())
    })


# ============================================================
# اختبار Binance
# ============================================================

@app.route("/api/binance/test")
def binance_test():

    data = binance_get("/api/v3/ping")

    if isinstance(data, dict) and data.get("_error"):
        return jsonify({
            "ok": False,
            "error": data.get("_message", "Binance error"),
            "details": data
        }), 502

    return jsonify({
        "ok": True,
        "message": "Binance متصل",
        "data": data
    })


# ============================================================
# معلومات العملات + الأسعار
# ============================================================

@app.route("/api/binance/markets")
def markets():

    cache_key = "markets"

    cached = cache_get(cache_key)

    if cached is not None:
        return jsonify(cached)

    # --------------------------------------------------------
    # معلومات العملات
    # --------------------------------------------------------

    info = binance_get("/api/v3/exchangeInfo")

    if isinstance(info, dict) and info.get("_error"):
        return jsonify({
            "ok": False,
            "error": "تعذر جلب معلومات العملات من Binance",
            "details": info
        }), 502

    if not isinstance(info, dict):
        return jsonify({
            "ok": False,
            "error": "استجابة Binance غير صحيحة"
        }), 502

    symbols_info = info.get("symbols")

    if not isinstance(symbols_info, list):
        return jsonify({
            "ok": False,
            "error": "Binance لم يرجع قائمة العملات",
            "details": info
        }), 502

    # --------------------------------------------------------
    # تحديد عملات Spot USDT
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
    # أسعار 24 ساعة
    # --------------------------------------------------------

    tickers = binance_get("/api/v3/ticker/24hr")

    if isinstance(tickers, dict) and tickers.get("_error"):
        return jsonify({
            "ok": False,
            "error": "تعذر جلب أسعار Binance",
            "details": tickers
        }), 502

    if not isinstance(tickers, list):
        return jsonify({
            "ok": False,
            "error": "Binance لم يرجع بيانات الأسعار"
        }), 502

    # --------------------------------------------------------
    # تجهيز النتيجة
    # --------------------------------------------------------

    result = []

    for ticker in tickers:

        if not isinstance(ticker, dict):
            continue

        symbol = ticker.get("symbol")

        if symbol not in allowed:
            continue

        try:
            price = float(ticker.get("lastPrice", 0))
            change = float(ticker.get("priceChangePercent", 0))
            volume = float(ticker.get("quoteVolume", 0))
            high = float(ticker.get("highPrice", 0))
            low = float(ticker.get("lowPrice", 0))
        except (TypeError, ValueError):
            continue

        result.append({
            "symbol": symbol,
            "price": price,
            "change24h": change,
            "volume24h": volume,
            "high24h": high,
            "low24h": low
        })

    # ترتيب حسب حجم التداول
    result.sort(
        key=lambda x: x.get("volume24h", 0),
        reverse=True
    )

    response = {
        "ok": True,
        "count": len(result),
        "markets": result
    }

    cache_set(cache_key, response)

    return jsonify(response)


# ============================================================
# تحليل عملة
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

    if not symbol.endswith("USDT"):
        return jsonify({
            "ok": False,
            "error": "حالياً الموقع يدعم أزواج USDT فقط"
        }), 400

    # --------------------------------------------------------
    # جلب الشموع
    # --------------------------------------------------------

    klines = binance_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": 250
        }
    )

    if isinstance(klines, dict) and klines.get("_error"):
        return jsonify({
            "ok": False,
            "error": "تعذر جلب الشموع من Binance",
            "details": klines
        }), 502

    if not isinstance(klines, list):
        return jsonify({
            "ok": False,
            "error": "بيانات الشموع غير صحيحة"
        }), 502

    if len(klines) < 30:
        return jsonify({
            "ok": False,
            "error": "عدد الشموع غير كافٍ للتحليل"
        }), 502

    # --------------------------------------------------------
    # استخراج الأسعار
    # --------------------------------------------------------

    closes = []
    highs = []
    lows = []
    volumes = []

    for candle in klines:

        try:
            closes.append(float(candle[4]))
            highs.append(float(candle[2]))
            lows.append(float(candle[3]))
            volumes.append(float(candle[5]))
        except (IndexError, TypeError, ValueError):
            continue

    if len(closes) < 30:
        return jsonify({
            "ok": False,
            "error": "تعذر قراءة بيانات الشموع"
        }), 502

    current_price = closes[-1]

    # ========================================================
    # EMA
    # ========================================================

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

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    # ========================================================
    # RSI
    # ========================================================

    def calculate_rsi(values, period=14):

        if len(values) <= period:
            return None

        gains = []
        losses = []

        for i in range(1, len(values)):
            difference = values[i] - values[i - 1]

            if difference > 0:
                gains.append(difference)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(difference))

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

    rsi = calculate_rsi(closes)

    # ========================================================
    # الدعم والمقاومة البسيطة
    # ========================================================

    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])

    # ========================================================
    # حجم التداول
    # ========================================================

    avg_volume = (
        sum(volumes[-20:]) / 20
        if len(volumes) >= 20
        else sum(volumes) / len(volumes)
    )

    current_volume = volumes[-1]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0
        else 0
    )

    # ========================================================
    # الاتجاه
    # ========================================================

    score = 0
    reasons = []

    if ema20 is not None and current_price > ema20:
        score += 1
        reasons.append("السعر فوق EMA20")

    elif ema20 is not None:
        score -= 1
        reasons.append("السعر تحت EMA20")

    if ema50 is not None and current_price > ema50:
        score += 1
        reasons.append("السعر فوق EMA50")

    elif ema50 is not None:
        score -= 1
        reasons.append("السعر تحت EMA50")

    if ema200 is not None and current_price > ema200:
        score += 2
        reasons.append("السعر فوق EMA200")

    elif ema200 is not None:
        score -= 2
        reasons.append("السعر تحت EMA200")

    # ========================================================
    # RSI
    # ========================================================

    if rsi is not None:

        if rsi >= 70:
            reasons.append("RSI مرتفع")

        elif rsi >= 55:
            score += 1
            reasons.append("RSI إيجابي")

        elif rsi <= 30:
            reasons.append("RSI منخفض")

        elif rsi <= 45:
            score -= 1
            reasons.append("RSI سلبي")

        else:
            reasons.append("RSI حيادي")

    # ========================================================
    # الحجم
    # ========================================================

    if volume_ratio >= 1.5:
        reasons.append("حجم تداول مرتفع")

        if score > 0:
            score += 1
        elif score < 0:
            score -= 1

    # ========================================================
    # تحديد الإشارة
    # ========================================================

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

    # ========================================================
    # النتيجة
    # ========================================================

    return jsonify({
        "ok": True,

        "symbol": symbol,

        "interval": interval,

        "price": current_price,

        "signal": signal,

        "signal_code": signal_code,

        "score": score,

        "indicators": {
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi14": rsi,
            "volume_ratio": volume_ratio
        },

        "levels": {
            "resistance": recent_high,
            "support": recent_low
        },

        "reasons": reasons,

        "candles": len(closes),

        "timestamp": int(time.time())
    })


# ============================================================
# بيانات الشموع للواجهة
# ============================================================

@app.route("/api/binance/klines")
def get_klines():

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
                100
            )
        )
    except ValueError:
        limit = 100

    limit = max(10, min(limit, 1000))

    data = binance_get(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if isinstance(data, dict) and data.get("_error"):
        return jsonify({
            "ok": False,
            "error": "تعذر جلب بيانات الشموع",
            "details": data
        }), 502

    if not isinstance(data, list):
        return jsonify({
            "ok": False,
            "error": "بيانات الشموع غير صحيحة"
        }), 502

    candles = []

    for candle in data:

        try:
            candles.append({
                "time": int(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5])
            })

        except (IndexError, TypeError, ValueError):
            continue

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "candles": candles
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
