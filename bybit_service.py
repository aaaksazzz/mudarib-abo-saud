import os
import time
import threading
import requests

from flask import Flask, jsonify, request


# =========================================================
# APP
# =========================================================

app = Flask(__name__)


# =========================================================
# BINANCE SPOT
# =========================================================

BINANCE_BASES = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

TIMEOUT = int(os.getenv("BINANCE_TIMEOUT", "15"))

# مهم:
# جلب العملات حبة حبة وليس بشكل متوازي
REQUEST_DELAY = float(
    os.getenv("BINANCE_REQUEST_DELAY", "0.45")
)

# مدة الاحتفاظ بالبيانات
CACHE_TTL = int(
    os.getenv("BINANCE_CACHE_TTL", "900")
)

# عدد العملات في الفحص
DEFAULT_SCAN_LIMIT = int(
    os.getenv("CRYPTO_SCAN_LIMIT", "40")
)

# أقل حجم تداول 24 ساعة بالدولار
MIN_QUOTE_VOLUME = float(
    os.getenv("MIN_QUOTE_VOLUME", "1000000")
)


HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "Chrome/151.0.0.0 "
        "Mobile Safari/537.36 "
        "Mudarib-Abo-Saud/5.0"
    ),
    "Accept": "application/json,text/plain,*/*",
})


# =========================================================
# CACHE
# =========================================================

CACHE = {}

CACHE_LOCK = threading.Lock()

LAST_REQUEST_TIME = 0.0


# =========================================================
# CACHE FUNCTIONS
# =========================================================

def cache_set(key, value):
    with CACHE_LOCK:
        CACHE[key] = {
            "time": time.time(),
            "data": value,
        }


def cache_get(key):
    with CACHE_LOCK:
        item = CACHE.get(key)

        if not item:
            return None

        age = time.time() - item["time"]

        if age > CACHE_TTL:
            return None

        return item["data"]


def cache_age(key):
    with CACHE_LOCK:
        item = CACHE.get(key)

        if not item:
            return None

        return round(
            max(0, time.time() - item["time"]),
            2,
        )


# =========================================================
# REQUEST DELAY
# =========================================================

def wait_before_request():
    global LAST_REQUEST_TIME

    with CACHE_LOCK:
        now = time.time()

        elapsed = (
            now - LAST_REQUEST_TIME
        )

        if elapsed < REQUEST_DELAY:
            time.sleep(
                REQUEST_DELAY - elapsed
            )

        LAST_REQUEST_TIME = time.time()


# =========================================================
# BINANCE REQUEST
# =========================================================

def binance_request(
    path,
    params=None,
    retries=4,
):
    last_error = None

    for attempt in range(retries):

        wait_before_request()

        for base in BINANCE_BASES:

            url = base + path

            try:

                response = HTTP.get(
                    url,
                    params=params or {},
                    timeout=TIMEOUT,
                )

                status = response.status_code

                # -----------------------------------------
                # RATE LIMIT
                # -----------------------------------------

                if status == 429:

                    retry_after = (
                        response.headers.get(
                            "Retry-After",
                            "3",
                        )
                    )

                    try:
                        delay = float(
                            retry_after
                        )
                    except Exception:
                        delay = 3.0

                    delay = max(
                        delay,
                        2.0,
                    )

                    last_error = (
                        "Binance HTTP 429 "
                        f"(انتظار {delay} ثانية)"
                    )

                    time.sleep(delay)

                    continue

                # -----------------------------------------
                # TEMPORARY BAN
                # -----------------------------------------

                if status == 418:

                    delay = (
                        10 + attempt * 5
                    )

                    last_error = (
                        "Binance HTTP 418 "
                        "IP temporarily banned"
                    )

                    time.sleep(delay)

                    continue

                # -----------------------------------------
                # SERVER ERROR
                # -----------------------------------------

                if status >= 500:

                    last_error = (
                        f"Binance HTTP {status}"
                    )

                    time.sleep(
                        2 + attempt
                    )

                    continue

                # -----------------------------------------
                # JSON
                # -----------------------------------------

                try:

                    data = response.json()

                except Exception:

                    last_error = (
                        f"Binance HTTP {status}: "
                        f"{response.text[:500]}"
                    )

                    continue

                # -----------------------------------------
                # HTTP ERROR
                # -----------------------------------------

                if status != 200:

                    message = ""

                    if isinstance(
                        data,
                        dict,
                    ):
                        message = data.get(
                            "msg",
                            "",
                        )

                    last_error = (
                        f"Binance HTTP {status}: "
                        f"{message or data}"
                    )

                    continue

                # -----------------------------------------
                # BINANCE API ERROR
                # -----------------------------------------

                if isinstance(
                    data,
                    dict,
                ):

                    code = data.get(
                        "code"
                    )

                    if (
                        isinstance(
                            code,
                            int,
                        )
                        and code < 0
                    ):

                        last_error = (
                            f"Binance code {code}: "
                            f"{data.get('msg', '')}"
                        )

                        continue

                return data

            except requests.RequestException as e:

                last_error = (
                    f"Binance connection error: {e}"
                )

                time.sleep(
                    1 + attempt
                )

            except Exception as e:

                last_error = str(e)

                time.sleep(
                    1 + attempt
                )

    raise RuntimeError(
        last_error
        or "تعذر الاتصال بـ Binance"
    )


# =========================================================
# TIME
# =========================================================

def binance_time():
    return binance_request(
        "/api/v3/time"
    )


# =========================================================
# SYMBOLS
# =========================================================

def get_symbols(force=False):

    key = "exchange_info"

    if not force:

        cached = cache_get(key)

        if cached is not None:
            return cached

    data = binance_request(
        "/api/v3/exchangeInfo"
    )

    symbols = []

    for item in data.get(
        "symbols",
        [],
    ):

        symbol = item.get(
            "symbol",
            "",
        )

        status = item.get(
            "status",
            "",
        )

        quote = item.get(
            "quoteAsset",
            "",
        )

        if not symbol:
            continue

        if status != "TRADING":
            continue

        if quote != "USDT":
            continue

        symbols.append({
            "symbol": symbol,
            "baseAsset": item.get(
                "baseAsset"
            ),
            "quoteAsset": quote,
            "status": status,
            "source": "Binance Spot",
        })

    cache_set(
        key,
        symbols,
    )

    return symbols


# =========================================================
# TICKERS
# =========================================================

def get_tickers(force=False):

    key = "tickers"

    if not force:

        cached = cache_get(key)

        if cached is not None:
            return cached

    data = binance_request(
        "/api/v3/ticker/24hr"
    )

    result = []

    for item in data:

        symbol = item.get(
            "symbol",
            "",
        )

        if not symbol.endswith(
            "USDT"
        ):
            continue

        try:

            price = float(
                item.get(
                    "lastPrice",
                    0,
                )
            )

            change = float(
                item.get(
                    "priceChangePercent",
                    0,
                )
            )

            volume = float(
                item.get(
                    "volume",
                    0,
                )
            )

            quote_volume = float(
                item.get(
                    "quoteVolume",
                    0,
                )
            )

        except Exception:

            continue

        result.append({
            "symbol": symbol,
            "price": price,
            "change24h": change,
            "volume24h": volume,
            "quoteVolume24h": quote_volume,
            "source": "Binance Spot",
        })

    cache_set(
        key,
        result,
    )

    return result


# =========================================================
# INTERVALS
# =========================================================

INTERVALS = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "3d": "3d",
    "1w": "1w",
    "1M": "1M",
}


# =========================================================
# KLINE NORMALIZE
# =========================================================

def normalize_kline(row):

    return {
        "time": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }


# =========================================================
# GET KLINES
# =========================================================

def get_klines(
    symbol,
    interval="15m",
    limit=230,
    force=False,
):

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )

    interval = (
        str(interval)
        .strip()
    )

    if interval not in INTERVALS:

        raise RuntimeError(
            f"الفاصل غير مدعوم: {interval}"
        )

    try:
        limit = int(limit)
    except Exception:
        limit = 230

    limit = max(
        1,
        min(
            limit,
            1000,
        ),
    )

    key = (
        f"klines:"
        f"{symbol}:"
        f"{interval}:"
        f"{limit}"
    )

    cached = None

    if not force:
        cached = cache_get(key)

    if cached is not None:
        return cached

    data = binance_request(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": INTERVALS[
                interval
            ],
            "limit": limit,
        },
    )

    candles = []

    for row in data:

        try:

            candles.append(
                normalize_kline(row)
            )

        except Exception:
            continue

    cache_set(
        key,
        candles,
    )

    return candles


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )

    data = binance_request(
        "/api/v3/ticker/24hr",
        {
            "symbol": symbol,
        },
    )

    return {
        "symbol": symbol,
        "price": float(
            data.get(
                "lastPrice",
                0,
            )
        ),
        "change24h": float(
            data.get(
                "priceChangePercent",
                0,
            )
        ),
        "volume24h": float(
            data.get(
                "volume",
                0,
            )
        ),
        "quoteVolume24h": float(
            data.get(
                "quoteVolume",
                0,
            )
        ),
        "source": "Binance Spot",
    }


# =========================================================
# TECHNICAL INDICATORS
# =========================================================

def ema(values, period):

    if not values:
        return None

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            price - value
        ) * multiplier + value

    return value


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(
            gains[:period]
        ) / period
    )

    avg_loss = (
        sum(
            losses[:period]
        ) / period
    )

    for i in range(
        period,
        len(gains),
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

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


def atr(
    candles,
    period=14,
):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(
        1,
        len(candles),
    ):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous[
            "close"
        ]

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            ),
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return (
        sum(
            trs[-period:]
        )
        / period
    )


def macd_hist(
    values,
    fast=12,
    slow=26,
    signal=9,
):

    if len(values) < (
        slow + signal
    ):
        return None

    macd_values = []

    for i in range(
        slow,
        len(values) + 1,
    ):

        fast_ema = ema(
            values[:i],
            fast,
        )

        slow_ema = ema(
            values[:i],
            slow,
        )

        if (
            fast_ema is None
            or slow_ema is None
        ):
            continue

        macd_values.append(
            fast_ema - slow_ema
        )

    if len(macd_values) < signal:
        return None

    macd_line = macd_values[-1]

    signal_line = ema(
        macd_values,
        signal,
    )

    if signal_line is None:
        return None

    return (
        macd_line
        - signal_line
    )


# =========================================================
# ANALYSIS
# =========================================================

def analyze_klines(
    candles,
    symbol,
    section="spot",
    interval="15m",
):

    if not candles:
        raise RuntimeError(
            "لا توجد بيانات للعملة"
        )

    if len(candles) < 60:

        raise RuntimeError(
            "بيانات غير كافية للتحليل"
        )

    closes = [
        float(x["close"])
        for x in candles
    ]

    price = closes[-1]

    e20 = ema(
        closes,
        20,
    )

    e50 = ema(
        closes,
        50,
    )

    e200 = ema(
        closes,
        200,
    )

    current_rsi = rsi(
        closes,
        14,
    )

    current_atr = atr(
        candles,
        14,
    )

    current_macd = macd_hist(
        closes
    )

    score = 50

    if e20 is not None:

        if price > e20:
            score += 8
        else:
            score -= 8

    if e50 is not None:

        if price > e50:
            score += 8
        else:
            score -= 8

    if e200 is not None:

        if price > e200:
            score += 10
        else:
            score -= 10

    if current_rsi is not None:

        if 50 <= current_rsi <= 70:
            score += 8

        elif current_rsi > 70:
            score += 2

        elif current_rsi < 30:
            score += 3

        else:
            score -= 5

    if current_macd is not None:

        if current_macd > 0:
            score += 8
        else:
            score -= 8

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    if score >= 80:
        signal = "شراء قوي"

    elif score >= 65:
        signal = "شراء"

    elif score <= 20:
        signal = "بيع قوي"

    elif score <= 35:
        signal = "بيع"

    else:
        signal = "حيادي"

    risk = (
        current_atr
        if current_atr
        else price * 0.01
    )

    risk = max(
        risk * 1.5,
        price * 0.01,
    )

    direction = (
        "BUY"
        if score >= 50
        else "SELL"
    )

    if direction == "BUY":

        sl = price - risk
        tp1 = price + risk * 1.5
        tp2 = price + risk * 2
        tp3 = price + risk * 3

    else:

        sl = price + risk
        tp1 = price - risk * 1.5
        tp2 = price - risk * 2
        tp3 = price - risk * 3

    recent = candles[-20:]

    support = min(
        x["low"]
        for x in recent
    )

    resistance = max(
        x["high"]
        for x in recent
    )

    return {
        "symbol": symbol,
        "section": section,
        "interval": interval,
        "source": "Binance Spot",
        "data_source": "Binance Spot",

        "price": price,

        "signal": signal,
        "direction": direction,
        "score": score,

        "rsi": current_rsi,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "macd": current_macd,
        "atr": current_atr,

        "entry": price,

        "sl": sl,
        "stop_loss": sl,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "support": support,
        "resistance": resistance,

        "candles": candles[-100:],

        "updated_at": int(
            time.time()
        ),
    }


# =========================================================
# SAVE ANALYSIS IN SAME CACHE
# =========================================================

def analysis_key(
    symbol,
    interval,
):
    return (
        f"analysis:"
        f"{symbol}:"
        f"{interval}"
    )


def get_cached_analysis(
    symbol,
    interval,
):

    return cache_get(
        analysis_key(
            symbol,
            interval,
        )
    )


def analyze_symbol(
    symbol,
    interval="15m",
    force=False,
    section="spot",
):

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )

    key = analysis_key(
        symbol,
        interval,
    )

    # -----------------------------------------------------
    # أهم نقطة:
    # نفس تحليل Spot يستخدمه Alpha وFutures
    # -----------------------------------------------------

    if not force:

        cached = cache_get(key)

        if cached is not None:

            result = dict(
                cached
            )

            result["section"] = (
                section
            )

            result["data_source"] = (
                "Binance Spot Cache"
            )

            return result

    candles = get_klines(
        symbol,
        interval,
        230,
        force=force,
    )

    analysis = analyze_klines(
        candles,
        symbol,
        "spot",
        interval,
    )

    # التخزين يكون مرة واحدة
    cache_set(
        key,
        analysis,
    )

    result = dict(
        analysis
    )

    result["section"] = section

    result["data_source"] = (
        "Binance Spot Cache"
    )

    return result


# =========================================================
# SCAN
# =========================================================

def scan_spot(
    interval="15m",
    limit=40,
    force=False,
):

    scan_key = (
        f"scan:"
        f"{interval}:"
        f"{limit}"
    )

    if not force:

        cached = cache_get(
            scan_key
        )

        if cached is not None:
            return cached

    tickers = get_tickers()

    candidates = []

    for item in tickers:

        symbol = item.get(
            "symbol",
            "",
        )

        quote_volume = float(
            item.get(
                "quoteVolume24h",
                0,
            )
            or 0
        )

        if not symbol.endswith(
            "USDT"
        ):
            continue

        if quote_volume < (
            MIN_QUOTE_VOLUME
        ):
            continue

        candidates.append(
            item
        )

    candidates.sort(
        key=lambda x: float(
            x.get(
                "quoteVolume24h",
                0,
            )
            or 0
        ),
        reverse=True,
    )

    try:
        limit = int(limit)
    except Exception:
        limit = DEFAULT_SCAN_LIMIT

    limit = max(
        1,
        min(
            limit,
            len(candidates),
        ),
    )

    candidates = candidates[
        :limit
    ]

    results = []

    # =====================================================
    # حبة حبة
    # =====================================================

    for item in candidates:

        symbol = item[
            "symbol"
        ]

        try:

            analysis = analyze_symbol(
                symbol=symbol,
                interval=interval,
                force=force,
                section="spot",
            )

            analysis[
                "quoteVolume24h"
            ] = item.get(
                "quoteVolume24h",
                0,
            )

            analysis[
                "change24h"
            ] = item.get(
                "change24h",
                0,
            )

            analysis[
                "volume24h"
            ] = item.get(
                "volume24h",
                0,
            )

            results.append(
                analysis
            )

        except Exception as e:

            print(
                f"SCAN {symbol}: {e}"
            )

            continue

    results.sort(
        key=lambda x: float(
            x.get(
                "score",
                0,
            )
            or 0
        ),
        reverse=True,
    )

    output = {
        "ok": True,
        "source": "Binance Spot",
        "data_source": (
            "Binance Spot Cache"
        ),
        "interval": interval,
        "count": len(results),
        "results": results,
        "updated_at": int(
            time.time()
        ),
    }

    cache_set(
        scan_key,
        output,
    )

    return output


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def home():

    return jsonify({
        "ok": True,
        "service": (
            "mudarib-abo-saud"
        ),
        "source": "Binance Spot",
        "mode": "sequential",
        "cache": True,
    })


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    try:

        data = binance_time()

        return jsonify({
            "ok": True,
            "connected": True,
            "source": "Binance Spot",
            "server_time": data.get(
                "serverTime"
            ),
            "cached_items": len(
                CACHE
            ),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "connected": False,
            "source": "Binance Spot",
            "error": str(e),
        }), 502


# =========================================================
# BINANCE TEST
# =========================================================

@app.get("/api/binance/test")
def api_binance_test():

    try:

        data = binance_time()

        return jsonify({
            "ok": True,
            "connected": True,
            "source": "Binance Spot",
            "server_time": data.get(
                "serverTime"
            ),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "connected": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE MARKETS
# =========================================================

@app.get("/api/binance/markets")
def api_binance_markets():

    try:

        data = get_symbols()

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "count": len(data),
            "markets": data,
            "symbols": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE PRICES
# =========================================================

@app.get("/api/binance/prices")
def api_binance_prices():

    try:

        data = get_tickers()

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "count": len(data),
            "prices": data,
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE PRICE
# =========================================================

@app.get("/api/binance/price")
def api_binance_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    try:

        data = get_price(
            symbol
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "price": data,
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE KLINES
# =========================================================

@app.get("/api/binance/klines")
def api_binance_klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                "230",
            )
        )

    except Exception:

        limit = 230

    force = (
        request.args.get(
            "force",
            "0",
        )
        == "1"
    )

    try:

        candles = get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            force=force,
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "symbol": symbol,
            "interval": interval,
            "count": len(candles),
            "candles": candles,
            "klines": candles,
            "cache_age": cache_age(
                f"klines:"
                f"{symbol}:"
                f"{interval}:"
                f"{max(1, min(limit, 1000))}"
            ),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE ANALYSIS
# =========================================================

@app.get("/api/binance/analysis")
def api_binance_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    force = (
        request.args.get(
            "force",
            "0",
        )
        == "1"
    )

    try:

        analysis = analyze_symbol(
            symbol=symbol,
            interval=interval,
            force=force,
            section="spot",
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "analysis": analysis,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# BINANCE SCAN
# =========================================================

@app.get("/api/binance/scan")
def api_binance_scan():

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                str(DEFAULT_SCAN_LIMIT),
            )
        )

    except Exception:

        limit = DEFAULT_SCAN_LIMIT

    force = (
        request.args.get(
            "force",
            "0",
        )
        == "1"
    )

    try:

        result = scan_spot(
            interval=interval,
            limit=limit,
            force=force,
        )

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# ALPHA
# نفس بيانات SPOT
# =========================================================

@app.get("/api/alpha/analysis")
def alpha_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        analysis = analyze_symbol(
            symbol=symbol,
            interval=interval,
            force=False,
            section="alpha",
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "data_source": (
                "Same Spot Cache"
            ),
            "analysis": analysis,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


@app.get("/api/alpha/scan")
def alpha_scan():

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                str(DEFAULT_SCAN_LIMIT),
            )
        )

    except Exception:

        limit = DEFAULT_SCAN_LIMIT

    try:

        result = scan_spot(
            interval=interval,
            limit=limit,
            force=False,
        )

        result = dict(
            result
        )

        result[
            "section"
        ] = "alpha"

        result[
            "data_source"
        ] = "Same Spot Cache"

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# FUTURES
# نفس بيانات SPOT
# =========================================================

@app.get("/api/futures/analysis")
def futures_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        analysis = analyze_symbol(
            symbol=symbol,
            interval=interval,
            force=False,
            section="futures",
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "data_source": (
                "Same Spot Cache"
            ),
            "analysis": analysis,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


@app.get("/api/futures/scan")
def futures_scan():

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                str(DEFAULT_SCAN_LIMIT),
            )
        )

    except Exception:

        limit = DEFAULT_SCAN_LIMIT

    try:

        result = scan_spot(
            interval=interval,
            limit=limit,
            force=False,
        )

        result = dict(
            result
        )

        result[
            "section"
        ] = "futures"

        result[
            "data_source"
        ] = "Same Spot Cache"

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# OLD SIMPLE ROUTES
# =========================================================

@app.get("/symbols")
def symbols():

    try:

        data = get_symbols()

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "count": len(data),
            "symbols": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


@app.get("/tickers")
def tickers():

    try:

        data = get_tickers()

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "count": len(data),
            "tickers": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


@app.get("/price")
def price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    try:

        data = get_price(
            symbol
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "data": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


@app.get("/klines")
def klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT",
    ).upper().strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    try:

        limit = int(
            request.args.get(
                "limit",
                "230",
            )
        )

    except Exception:

        limit = 230

    try:

        data = get_klines(
            symbol,
            interval,
            limit,
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "symbol": symbol,
            "interval": interval,
            "count": len(data),
            "candles": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# PROXY
# =========================================================

@app.post("/proxy")
def proxy():

    body = request.get_json(
        silent=True
    ) or {}

    path = str(
        body.get(
            "path",
            "",
        )
    ).strip()

    params = (
        body.get(
            "params"
        )
        or {}
    )

    allowed = {
        "/api/v3/ping",
        "/api/v3/time",
        "/api/v3/exchangeInfo",
        "/api/v3/ticker/24hr",
        "/api/v3/ticker/price",
        "/api/v3/klines",
        "/api/v3/avgPrice",
        "/api/v3/depth",
        "/api/v3/trades",
    }

    if path not in allowed:

        return jsonify({
            "ok": False,
            "error": "Endpoint not allowed",
        }), 400

    try:

        data = binance_request(
            path,
            params,
        )

        return jsonify({
            "ok": True,
            "source": "Binance Spot",
            "result": data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# CACHE STATUS
# =========================================================

@app.get("/cache")
def cache_status():

    with CACHE_LOCK:

        items = []

        for key, value in CACHE.items():

            age = (
                time.time()
                - value["time"]
            )

            items.append({
                "key": key,
                "age_seconds": round(
                    age,
                    2,
                ),
                "expired": (
                    age > CACHE_TTL
                ),
            })

    return jsonify({
        "ok": True,
        "source": "Binance Spot",
        "cache_ttl": CACHE_TTL,
        "request_delay": REQUEST_DELAY,
        "items": items,
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
