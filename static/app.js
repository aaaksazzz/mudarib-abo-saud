import os
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template, request


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

PORT = int(os.getenv("PORT", "8080"))

OKX_BASE = "https://openapi.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

TIMEOUT = 8
MAX_WORKERS = 5

# كل العملات موجودة بالقائمة
# لكن التحليل المباشر يقتصر على الأعلى نشاطاً
ANALYZE_LIMIT = 60

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})

cache = {}
cache_lock = threading.Lock()


# =========================================================
# HELPERS
# =========================================================

def now_ms():
    return int(time.time() * 1000)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def round_num(value, digits=4):
    try:
        return round(float(value), digits)
    except Exception:
        return 0


def percent_change(current, previous):
    if not previous:
        return 0
    return ((current - previous) / previous) * 100


def cache_get(key):
    with cache_lock:
        item = cache.get(key)

    if not item:
        return None

    expires, value = item

    if time.time() >= expires:
        return None

    return value


def cache_set(key, value, seconds):
    with cache_lock:
        cache[key] = (
            time.time() + seconds,
            value
        )


# =========================================================
# OKX REQUEST
# =========================================================

def okx_request(path, params=None):
    response = session.get(
        OKX_BASE + path,
        params=params or {},
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    if str(data.get("code", "0")) != "0":
        raise RuntimeError(
            data.get("msg", "OKX API error")
        )

    return data


# =========================================================
# HEALTH
# =========================================================

def check_okx():

    try:

        data = okx_request(
            "/api/v5/public/time"
        )

        return {
            "ok": True,
            "online": True,
            "source": "OKX",
            "serverTime": data.get("data", []),
            "timestamp": now_ms(),
            "error": None
        }

    except Exception as e:

        return {
            "ok": False,
            "online": False,
            "source": "OKX",
            "serverTime": [],
            "timestamp": now_ms(),
            "error": str(e)
        }


# =========================================================
# ALL OKX USDT SPOT COINS
# =========================================================

def get_usdt_instruments():

    cached = cache_get("okx_instruments")

    if cached is not None:
        return cached

    data = okx_request(
        "/api/v5/public/instruments",
        {
            "instType": "SPOT"
        }
    )

    result = []

    for item in data.get("data", []):

        symbol = item.get("instId", "")

        if not symbol.endswith("-USDT"):
            continue

        if item.get("quoteCcy") != "USDT":
            continue

        if item.get("state") != "live":
            continue

        result.append({
            "symbol": symbol,
            "base": item.get("baseCcy", ""),
            "quote": "USDT"
        })

    result.sort(
        key=lambda x: x["symbol"]
    )

    cache_set(
        "okx_instruments",
        result,
        600
    )

    return result


# =========================================================
# ALL OKX USDT TICKERS
# =========================================================

def get_all_tickers():

    cached = cache_get("okx_tickers")

    if cached is not None:
        return cached

    data = okx_request(
        "/api/v5/market/tickers",
        {
            "instType": "SPOT"
        }
    )

    result = {}

    for item in data.get("data", []):

        symbol = item.get("instId", "")

        if not symbol.endswith("-USDT"):
            continue

        result[symbol] = {
            "last": safe_float(item.get("last")),
            "open24h": safe_float(item.get("open24h")),
            "volume": safe_float(item.get("volCcy24h")),
            "timestamp": item.get("ts")
        }

    cache_set(
        "okx_tickers",
        result,
        20
    )

    return result


# =========================================================
# CANDLES
# =========================================================

def get_candles(
    symbol,
    interval="15m",
    limit=220
):

    data = okx_request(
        "/api/v5/market/candles",
        {
            "instId": symbol,
            "bar": interval,
            "limit": str(limit)
        }
    )

    candles = []

    for item in data.get("data", []):

        if len(item) < 6:
            continue

        candles.append({
            "t": int(safe_float(item[0])),
            "o": safe_float(item[1]),
            "h": safe_float(item[2]),
            "l": safe_float(item[3]),
            "c": safe_float(item[4]),
            "v": safe_float(item[5])
        })

    candles.sort(
        key=lambda x: x["t"]
    )

    return candles


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    ema_value = sum(
        values[:period]
    ) / period

    multiplier = 2 / (period + 1)

    for value in values[period:]:

        ema_value = (
            (value - ema_value)
            * multiplier
        ) + ema_value

    return ema_value


# =========================================================
# RSI
# =========================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    average_gain = (
        sum(gains[:period]) / period
    )

    average_loss = (
        sum(losses[:period]) / period
    )

    for i in range(period, len(gains)):

        average_gain = (
            (
                average_gain * (period - 1)
            ) + gains[i]
        ) / period

        average_loss = (
            (
                average_loss * (period - 1)
            ) + losses[i]
        ) / period

    if average_loss == 0:
        return 100

    rs = average_gain / average_loss

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# ATR
# =========================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return 0

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["h"] - current["l"],
            abs(
                current["h"]
                - previous["c"]
            ),
            abs(
                current["l"]
                - previous["c"]
            )
        )

        true_ranges.append(tr)

    return (
        sum(true_ranges[-period:])
        / period
    )


# =========================================================
# MACD
# =========================================================

def calculate_macd(values):

    if len(values) < 35:
        return 0, 0, 0

    fast = calculate_ema(
        values,
        12
    )

    slow = calculate_ema(
        values,
        26
    )

    if fast is None or slow is None:
        return 0, 0, 0

    macd_values = []

    fast_value = fast
    slow_value = slow

    fast_multiplier = 2 / 13
    slow_multiplier = 2 / 27

    for i in range(26, len(values)):

        fast_value = (
            (values[i] - fast_value)
            * fast_multiplier
        ) + fast_value

        slow_value = (
            (values[i] - slow_value)
            * slow_multiplier
        ) + slow_value

        macd_values.append(
            fast_value - slow_value
        )

    if len(macd_values) < 9:
        return 0, 0, 0

    signal = calculate_ema(
        macd_values,
        9
    ) or 0

    macd_value = macd_values[-1]

    histogram = (
        macd_value - signal
    )

    return (
        macd_value,
        signal,
        histogram
    )


# =========================================================
# ANALYSIS
# =========================================================

def analyze_coin(
    symbol,
    candles,
    interval="15m"
):

    if len(candles) < 50:
        return None

    closes = [
        x["c"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = (
        calculate_ema(
            closes,
            20
        )
        or price
    )

    ema50 = (
        calculate_ema(
            closes,
            50
        )
        or price
    )

    ema200 = (
        calculate_ema(
            closes,
            200
        )
        or price
    )

    rsi = calculate_rsi(
        closes
    )

    atr = calculate_atr(
        candles
    )

    macd, macd_signal, macd_hist = (
        calculate_macd(
            closes
        )
    )

    previous_volume = 0

    if len(candles) >= 21:

        previous_volume = (
            sum(
                x["v"]
                for x in candles[-21:-1]
            )
            / 20
        )

    volume_ratio = (
        candles[-1]["v"]
        / previous_volume
        if previous_volume
        else 0
    )

    momentum = percent_change(
        price,
        closes[-5]
    )

    candle_change = percent_change(
        price,
        closes[-2]
    )

    recent = candles[-30:]

    support = min(
        x["l"]
        for x in recent
    )

    resistance = max(
        x["h"]
        for x in recent
    )

    # =====================================================
    # SCORE
    # =====================================================

    score = 0

    # EMA20
    if price > ema20:
        score += 15
    else:
        score -= 15

    # EMA50
    if price > ema50:
        score += 15
    else:
        score -= 15

    # EMA200
    if price > ema200:
        score += 20
    else:
        score -= 20

    # RSI
    if 52 <= rsi <= 68:
        score += 10

    elif rsi >= 72:
        score -= 8

    elif rsi <= 30:
        score += 5

    elif rsi < 45:
        score -= 6

    # MACD
    if macd > macd_signal:
        score += 10
    else:
        score -= 10

    # Momentum
    if momentum > 0.3:
        score += 8

    elif momentum < -0.3:
        score -= 8

    # Volume
    if volume_ratio >= 1.5:
        score += 10

    elif volume_ratio >= 1:
        score += 4

    elif volume_ratio < 0.5:
        score -= 4

    score = max(
        -100,
        min(100, score)
    )

    # =====================================================
    # SIGNAL
    # =====================================================

    if score >= 35:

        direction = "BUY"
        signal = "شراء قوي"

    elif score >= 15:

        direction = "BUY"
        signal = "شراء"

    elif score <= -35:

        direction = "SELL"
        signal = "بيع قوي"

    elif score <= -15:

        direction = "SELL"
        signal = "بيع"

    else:

        direction = "HOLD"
        signal = "حيادي"

    # =====================================================
    # TREND
    # =====================================================

    if (
        price > ema20
        and ema20 > ema50
        and ema50 > ema200
    ):

        trend = "صاعد"

    elif (
        price < ema20
        and ema20 < ema50
        and ema50 < ema200
    ):

        trend = "هابط"

    else:

        trend = "متذبذب"

    # =====================================================
    # TARGET / STOP
    # =====================================================

    if direction == "BUY":

        take_profit = price * 1.018
        stop_loss = price * 0.99

    elif direction == "SELL":

        take_profit = price * 0.982
        stop_loss = price * 1.01

    else:

        take_profit = price
        stop_loss = price

    return {

        "name": symbol.replace(
            "-USDT",
            ""
        ),

        "symbol": symbol,

        "source": "OKX Spot",

        "interval": interval,

        "signal": signal,

        "direction": direction,

        "score": round_num(
            score,
            1
        ),

        "score10": round_num(
            score / 10,
            1
        ),

        "price": round_num(
            price,
            8
        ),

        "entry": round_num(
            price,
            8
        ),

        "takeProfit": round_num(
            take_profit,
            8
        ),

        "stopLoss": round_num(
            stop_loss,
            8
        ),

        "targetPercent": (
            1.8
            if direction != "HOLD"
            else 0
        ),

        "stopPercent": (
            1
            if direction != "HOLD"
            else 0
        ),

        "rsi": round_num(
            rsi,
            2
        ),

        "ema20": round_num(
            ema20,
            8
        ),

        "ema50": round_num(
            ema50,
            8
        ),

        "ema200": round_num(
            ema200,
            8
        ),

        "macd": round_num(
            macd,
            8
        ),

        "macdSignal": round_num(
            macd_signal,
            8
        ),

        "macdHistogram": round_num(
            macd_hist,
            8
        ),

        "atr": round_num(
            atr,
            8
        ),

        "momentum": round_num(
            momentum,
            2
        ),

        "candleChange": round_num(
            candle_change,
            2
        ),

        "volumeRatio": round_num(
            volume_ratio,
            2
        ),

        "support": round_num(
            support,
            8
        ),

        "resistance": round_num(
            resistance,
            8
        ),

        "supportDistance": round_num(
            percent_change(
                price,
                support
            ),
            2
        ),

        "resistanceDistance": round_num(
            percent_change(
                resistance,
                price
            ),
            2
        ),

        "trend": trend,

        "volatility": round_num(
            (
                atr / price * 100
                if price
                else 0
            ),
            2
        ),

        "updatedAt": now_ms()
    }


# =========================================================
# CRYPTO SCANNER
# =========================================================

def scan_crypto(interval="15m"):

    cache_key = (
        "crypto_scan_" + interval
    )

    cached = cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    instruments = get_usdt_instruments()

    tickers = get_all_tickers()

    all_symbols = [
        x["symbol"]
        for x in instruments
    ]

    active = []

    for item in instruments:

        symbol = item["symbol"]

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        price = ticker["last"]

        if price <= 0:
            continue

        volume_usdt = (
            ticker["volume"]
            * price
        )

        change = percent_change(
            price,
            ticker["open24h"]
        )

        active.append(
            (
                symbol,
                ticker,
                volume_usdt,
                change
            )
        )

    # الأعلى سيولة
    active.sort(
        key=lambda x: x[2],
        reverse=True
    )

    selected = active[
        :ANALYZE_LIMIT
    ]

    results = []
    errors = []

    def worker(item):

        symbol = item[0]

        try:

            candles = get_candles(
                symbol,
                interval,
                220
            )

            result = analyze_coin(
                symbol,
                candles,
                interval
            )

            if result:

                result["change24h"] = (
                    round_num(
                        item[3],
                        2
                    )
                )

                result["volume24h"] = (
                    round_num(
                        item[2],
                        0
                    )
                )

            return result

        except Exception as e:

            return {
                "_error": symbol,
                "message": str(e)
            }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item
            )
            for item in selected
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if not result:
                    continue

                if "_error" in result:

                    errors.append(
                        result
                    )

                else:

                    results.append(
                        result
                    )

            except Exception as e:

                errors.append({
                    "message": str(e)
                })

    signals = [
        x
        for x in results
        if x["direction"]
        in ("BUY", "SELL")
    ]

    results.sort(
        key=lambda x: abs(
            safe_float(
                x.get("score")
            )
        ),
        reverse=True
    )

    signals.sort(
        key=lambda x: abs(
            safe_float(
                x.get("score")
            )
        ),
        reverse=True
    )

    output = {

        "ok": True,

        "source": "OKX Spot",

        "market": "crypto",

        "interval": interval,

        "instrumentCount": len(
            all_symbols
        ),

        "analyzedCount": len(
            selected
        ),

        "count": len(
            results
        ),

        "signalCount": len(
            signals
        ),

        "results": results,

        "signals": signals,

        "errors": errors[:20],

        "updatedAt": now_ms()
    }

    cache_set(
        cache_key,
        output,
        15
    )

    return output


# =========================================================
# YAHOO MARKETS
# =========================================================

MARKETS = {

    "saudi": [

        (
            "TASI",
            "^TASI.SR",
            "تاسي"
        ),

        (
            "ARAMCO",
            "2222.SR",
            "أرامكو"
        ),

        (
            "SABIC",
            "2010.SR",
            "سابك"
        ),

        (
            "ALRAJHI",
            "1120.SR",
            "الراجحي"
        ),

        (
            "SNB",
            "1180.SR",
            "الأهلي"
        )

    ],

    "us": [

        (
            "SPY",
            "SPY",
            "S&P 500"
        ),

        (
            "QQQ",
            "QQQ",
            "Nasdaq"
        ),

        (
            "AAPL",
            "AAPL",
            "Apple"
        ),

        (
            "NVDA",
            "NVDA",
            "NVIDIA"
        ),

        (
            "MSFT",
            "MSFT",
            "Microsoft"
        ),

        (
            "TSLA",
            "TSLA",
            "Tesla"
        ),

        (
            "AMZN",
            "AMZN",
            "Amazon"
        ),

        (
            "META",
            "META",
            "Meta"
        ),

        (
            "GOOGL",
            "GOOGL",
            "Google"
        )

    ],

    "forex": [

        (
            "EURUSD",
            "EURUSD=X",
            "EUR/USD"
        ),

        (
            "GBPUSD",
            "GBPUSD=X",
            "GBP/USD"
        ),

        (
            "USDJPY",
            "JPY=X",
            "USD/JPY"
        ),

        (
            "AUDUSD",
            "AUDUSD=X",
            "AUD/USD"
        )

    ],

    "commodities": [

        (
            "GOLD",
            "GC=F",
            "Gold"
        ),

        (
            "OIL",
            "CL=F",
            "Oil"
        ),

        (
            "SILVER",
            "SI=F",
            "Silver"
        )

    ],

    "indices": [

        (
            "SPX",
            "^GSPC",
            "S&P 500"
        ),

        (
            "NDX",
            "^NDX",
            "Nasdaq 100"
        ),

        (
            "DJI",
            "^DJI",
            "Dow Jones"
        ),

        (
            "RUSSELL",
            "^RUT",
            "Russell 2000"
        )

    ],

    "futures": [

        (
            "ES",
            "ES=F",
            "S&P Futures"
        ),

        (
            "NQ",
            "NQ=F",
            "Nasdaq Futures"
        ),

        (
            "YM",
            "YM=F",
            "Dow Futures"
        ),

        (
            "GC",
            "GC=F",
            "Gold Futures"
        ),

        (
            "CL",
            "CL=F",
            "Oil Futures"
        )

    ]

}


# =========================================================
# YAHOO CANDLES
# =========================================================

def yahoo_candles(
    symbol,
    interval
):

    if interval == "15m":

        range_value = "5d"
        interval_value = "15m"

    elif interval == "1h":

        range_value = "1mo"
        interval_value = "1h"

    else:

        range_value = "3mo"
        interval_value = "1h"

    response = session.get(
        YAHOO_BASE
        + "/v8/finance/chart/"
        + symbol,

        params={
            "range": range_value,
            "interval": interval_value
        },

        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    results = (
        data
        .get("chart", {})
        .get("result", [])
    )

    if not results:
        return []

    result = results[0]

    timestamps = result.get(
        "timestamp",
        []
    )

    quote = (
        result
        .get("indicators", {})
        .get("quote", [{}])[0]
    )

    output = []

    for i, timestamp in enumerate(
        timestamps
    ):

        try:

            open_price = quote[
                "open"
            ][i]

            high_price = quote[
                "high"
            ][i]

            low_price = quote[
                "low"
            ][i]

            close_price = quote[
                "close"
            ][i]

            if (
                open_price is None
                or high_price is None
                or low_price is None
                or close_price is None
            ):
                continue

            volume_data = quote.get(
                "volume",
                []
            )

            volume = (
                volume_data[i]
                if i < len(volume_data)
                and volume_data[i] is not None
                else 0
            )

            output.append({

                "t": int(timestamp * 1000),

                "o": safe_float(
                    open_price
                ),

                "h": safe_float(
                    high_price
                ),

                "l": safe_float(
                    low_price
                ),

                "c": safe_float(
                    close_price
                ),

                "v": safe_float(
                    volume
                )

            })

        except Exception:
            continue

    return output


# =========================================================
# OTHER MARKET SCAN
# =========================================================

def scan_other_market(
    market,
    interval
):

    results = []
    errors = []

    for name, symbol, label in (
        MARKETS.get(
            market,
            []
        )
    ):

        try:

            candles = yahoo_candles(
                symbol,
                interval
            )

            result = analyze_coin(
                name,
                candles,
                interval
            )

            if result:

                result["name"] = label
                result["symbol"] = name
                result["source"] = (
                    "Yahoo Finance"
                )

                results.append(
                    result
                )

        except Exception as e:

            errors.append({
                "symbol": name,
                "message": str(e)
            })

    signals = [
        x
        for x in results
        if x["direction"]
        in ("BUY", "SELL")
    ]

    results.sort(
        key=lambda x: abs(
            safe_float(
                x["score"]
            )
        ),
        reverse=True
    )

    signals.sort(
        key=lambda x: abs(
            safe_float(
                x["score"]
            )
        ),
        reverse=True
    )

    return {

        "ok": True,

        "source": "Yahoo Finance",

        "market": market,

        "interval": interval,

        "instrumentCount": len(
            MARKETS.get(
                market,
                []
            )
        ),

        "analyzedCount": len(
            results
        ),

        "count": len(
            results
        ),

        "signalCount": len(
            signals
        ),

        "results": results,

        "signals": signals,

        "errors": errors,

        "updatedAt": now_ms()

    }


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


@app.route("/health")
def health():

    return jsonify(
        check_okx()
    )


@app.route("/api/health")
def api_health():

    return jsonify(
        check_okx()
    )


# =========================================================
# ALL USDT SYMBOLS
# =========================================================

@app.route("/api/crypto-symbols")
def crypto_symbols():

    try:

        symbols = (
            get_usdt_instruments()
        )

        return jsonify({

            "ok": True,

            "source": "OKX Spot",

            "count": len(symbols),

            "symbols": [
                x["symbol"]
                for x in symbols
            ],

            "updatedAt": now_ms()

        })

    except Exception as e:

        return jsonify({

            "ok": False,

            "count": 0,

            "symbols": [],

            "error": str(e)

        }), 500


# =========================================================
# TEST USDT
# =========================================================

@app.route("/api/test-usdt")
def test_usdt():

    try:

        instruments = (
            get_usdt_instruments()
        )

        tickers = (
            get_all_tickers()
        )

        active = []

        for item in instruments:

            symbol = item["symbol"]

            ticker = tickers.get(
                symbol
            )

            if not ticker:
                continue

            price = ticker["last"]

            if price <= 0:
                continue

            volume_usdt = (
                ticker["volume"]
                * price
            )

            change = percent_change(
                price,
                ticker["open24h"]
            )

            active.append({

                "symbol": symbol,

                "price": price,

                "change24h": round_num(
                    change,
                    2
                ),

                "volume24h": round_num(
                    volume_usdt,
                    0
                )

            })

        active.sort(
            key=lambda x: x[
                "volume24h"
            ],
            reverse=True
        )

        return jsonify({

            "ok": True,

            "source": "OKX Spot",

            "count": len(
                instruments
            ),

            "activeCount": len(
                active
            ),

            "symbols": [
                x["symbol"]
                for x in instruments
            ],

            "top": active[:20],

            "updatedAt": now_ms()

        })

    except Exception as e:

        return jsonify({

            "ok": False,

            "error": str(e)

        }), 500


# =========================================================
# SCAN
# =========================================================

@app.route("/api/scan")
def api_scan():

    market = request.args.get(
        "market",
        "crypto"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    if interval not in (
        "15m",
        "1h",
        "4h",
        "1d"
    ):

        interval = "15m"

    try:

        if market == "crypto":

            result = scan_crypto(
                interval
            )

        else:

            result = scan_other_market(
                market,
                interval
            )

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({

            "ok": False,

            "market": market,

            "interval": interval,

            "results": [],

            "signals": [],

            "count": 0,

            "signalCount": 0,

            "error": str(e)

        }), 500


# =========================================================
# SIGNALS ONLY
# =========================================================

@app.route("/api/signals")
def api_signals():

    market = request.args.get(
        "market",
        "crypto"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        if market == "crypto":

            result = scan_crypto(
                interval
            )

        else:

            result = scan_other_market(
                market,
                interval
            )

        return jsonify({

            "ok": result["ok"],

            "signals": result[
                "signals"
            ],

            "count": result[
                "signalCount"
            ],

            "market": market,

            "interval": interval,

            "updatedAt": result[
                "updatedAt"
            ]

        })

    except Exception as e:

        return jsonify({

            "ok": False,

            "signals": [],

            "count": 0,

            "error": str(e)

        }), 500


# =========================================================
# ONE COIN ANALYSIS
# =========================================================

@app.route("/api/analysis/<path:symbol>")
def single_analysis(symbol):

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        if not symbol.endswith(
            "-USDT"
        ):

            return jsonify({

                "ok": False,

                "error": "Unknown symbol"

            }), 404

        candles = get_candles(
            symbol,
            interval,
            220
        )

        result = analyze_coin(
            symbol,
            candles,
            interval
        )

        if not result:

            return jsonify({

                "ok": False,

                "error": (
                    "Not enough market data"
                )

            }), 404

        return jsonify({

            "ok": True,

            "data": result,

            "updatedAt": now_ms()

        })

    except Exception as e:

        return jsonify({

            "ok": False,

            "error": str(e)

        }), 500


# =========================================================
# BTC TEST
# =========================================================

@app.route("/api/test-analysis")
def test_analysis():

    try:

        interval = request.args.get(
            "interval",
            "15m"
        )

        candles = get_candles(
            "BTC-USDT",
            interval,
            220
        )

        result = analyze_coin(
            "BTC-USDT",
            candles,
            interval
        )

        return jsonify({

            "ok": True,

            "data": result,

            "updatedAt": now_ms()

        })

    except Exception as e:

        return jsonify({

            "ok": False,

            "error": str(e)

        }), 500


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
