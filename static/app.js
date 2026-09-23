import os
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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

PORT = int(os.getenv("PORT", "8080"))

OKX_BASE = "https://openapi.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

REQUEST_TIMEOUT = 8

# عدد العملات التي نحللها فعليًا في كل Scan
# القائمة نفسها تحتوي كل عملات USDT
ANALYZE_LIMIT = 60

# عدد الطلبات المتزامنة
MAX_WORKERS = 5

# الكاش
INSTRUMENT_CACHE_SECONDS = 600
TICKER_CACHE_SECONDS = 20
SCAN_CACHE_SECONDS = 15

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# =========================================================
# CACHE
# =========================================================

_cache = {}
_cache_lock = threading.Lock()


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)

    if not item:
        return None

    expires, value = item

    if time.time() >= expires:
        return None

    return value


def cache_set(key, value, seconds):
    with _cache_lock:
        _cache[key] = (
            time.time() + seconds,
            value
        )


# =========================================================
# HELPERS
# =========================================================

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


def pct(a, b):
    if not b:
        return 0

    return ((a - b) / b) * 100


def now_ms():
    return int(time.time() * 1000)


# =========================================================
# OKX CONNECTION
# =========================================================

def okx_get(path, params=None):
    url = OKX_BASE + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") not in (None, "0", 0):
        raise RuntimeError(
            data.get("msg", "OKX API error")
        )

    return data


def okx_health():
    try:
        data = okx_get("/api/v5/public/time")

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

def okx_instruments():
    cached = cache_get("okx_usdt_instruments")

    if cached is not None:
        return cached

    data = okx_get(
        "/api/v5/public/instruments",
        {
            "instType": "SPOT"
        }
    )

    result = []

    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        quote = item.get("quoteCcy", "")
        state = item.get("state", "")

        if (
            quote == "USDT"
            and state == "live"
            and inst_id.endswith("-USDT")
        ):
            result.append({
                "symbol": inst_id,
                "base": item.get("baseCcy", ""),
                "quote": quote,
                "tickSize": item.get("tickSz"),
                "lotSize": item.get("lotSz")
            })

    result.sort(
        key=lambda x: x["symbol"]
    )

    cache_set(
        "okx_usdt_instruments",
        result,
        INSTRUMENT_CACHE_SECONDS
    )

    return result


# =========================================================
# ALL TICKERS IN ONE REQUEST
# =========================================================

def okx_all_tickers():
    cached = cache_get("okx_all_tickers")

    if cached is not None:
        return cached

    data = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": "SPOT"
        }
    )

    tickers = {}

    for item in data.get("data", []):
        symbol = item.get("instId", "")

        if not symbol.endswith("-USDT"):
            continue

        tickers[symbol] = {
            "symbol": symbol,
            "last": safe_float(item.get("last")),
            "open24h": safe_float(item.get("open24h")),
            "high24h": safe_float(item.get("high24h")),
            "low24h": safe_float(item.get("low24h")),
            "vol24h": safe_float(item.get("vol24h")),
            "volCcy24h": safe_float(item.get("volCcy24h")),
            "ts": item.get("ts")
        }

    cache_set(
        "okx_all_tickers",
        tickers,
        TICKER_CACHE_SECONDS
    )

    return tickers


# =========================================================
# CANDLES
# =========================================================

def okx_candles(symbol, interval="15m", limit=100):
    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": symbol,
            "bar": interval,
            "limit": str(limit)
        }
    )

    candles = []

    for row in data.get("data", []):
        if len(row) < 6:
            continue

        candles.append({
            "t": int(safe_float(row[0])),
            "o": safe_float(row[1]),
            "h": safe_float(row[2]),
            "l": safe_float(row[3]),
            "c": safe_float(row[4]),
            "v": safe_float(row[5]),
            "confirm": row[8] if len(row) > 8 else "1"
        })

    candles.sort(
        key=lambda x: x["t"]
    )

    return candles


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

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

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

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

    return 100 - (
        100 / (1 + rs)
    )


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["h"] - current["l"],
            abs(
                current["h"] - previous["c"]
            ),
            abs(
                current["l"] - previous["c"]
            )
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(
        trs[-period:]
    ) / period


def macd(values):
    if len(values) < 35:
        return None, None, None

    fast = []
    slow = []

    multiplier_fast = 2 / 13
    multiplier_slow = 2 / 27

    fast_value = sum(
        values[:12]
    ) / 12

    slow_value = sum(
        values[:26]
    ) / 26

    macd_values = []

    for i in range(26, len(values)):
        fast_value = (
            (values[i] - fast_value)
            * multiplier_fast
        ) + fast_value

        slow_value = (
            (values[i] - slow_value)
            * multiplier_slow
        ) + slow_value

        macd_values.append(
            fast_value - slow_value
        )

    if len(macd_values) < 9:
        return None, None, None

    signal = ema(
        macd_values,
        9
    )

    current = macd_values[-1]

    histogram = (
        current - signal
        if signal is not None
        else 0
    )

    return (
        current,
        signal,
        histogram
    )


# =========================================================
# ANALYSIS
# =========================================================

def calculate_analysis(
    symbol,
    candles,
    ticker=None,
    interval="15m"
):
    if len(candles) < 50:
        return None

    closes = [
        x["c"]
        for x in candles
    ]

    current = closes[-1]

    previous = closes[-2]

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

    current_rsi = rsi(
        closes,
        14
    )

    current_atr = atr(
        candles,
        14
    )

    macd_value, macd_signal, macd_hist = macd(
        closes
    )

    if current_rsi is None:
        current_rsi = 50

    if current_atr is None:
        current_atr = 0

    if ema20 is None:
        ema20 = current

    if ema50 is None:
        ema50 = current

    if ema200 is None:
        ema200 = current

    if macd_value is None:
        macd_value = 0

    if macd_signal is None:
        macd_signal = 0

    if macd_hist is None:
        macd_hist = 0

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    recent_volumes = [
        x["v"]
        for x in candles[-21:-1]
    ]

    avg_volume = (
        sum(recent_volumes)
        / len(recent_volumes)
        if recent_volumes
        else 0
    )

    current_volume = candles[-1]["v"]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0
        else 0
    )

    # -----------------------------------------------------
    # Momentum
    # -----------------------------------------------------

    momentum = pct(
        current,
        closes[-5]
    ) if len(closes) >= 5 else 0

    candle_change = pct(
        current,
        previous
    )

    # -----------------------------------------------------
    # Support / Resistance
    # -----------------------------------------------------

    lookback = candles[-30:]

    support = min(
        x["l"]
        for x in lookback
    )

    resistance = max(
        x["h"]
        for x in lookback
    )

    support_distance = (
        ((current - support) / current)
        * 100
        if current
        else 0
    )

    resistance_distance = (
        ((resistance - current) / current)
        * 100
        if current
        else 0
    )

    # -----------------------------------------------------
    # Score
    # -----------------------------------------------------

    score = 0

    # Trend
    if current > ema20:
        score += 15
    else:
        score -= 15

    if current > ema50:
        score += 15
    else:
        score -= 15

    if current > ema200:
        score += 20
    else:
        score -= 20

    # RSI
    if 52 <= current_rsi <= 68:
        score += 10

    elif current_rsi >= 72:
        score -= 8

    elif current_rsi <= 30:
        score += 5

    elif current_rsi < 45:
        score -= 6

    # MACD
    if macd_value > macd_signal:
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

    elif volume_ratio >= 1.0:
        score += 4

    elif volume_ratio < 0.5:
        score -= 4

    score = max(
        -100,
        min(100, score)
    )

    # -----------------------------------------------------
    # Direction
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Trend
    # -----------------------------------------------------

    if (
        current < ema20
        and ema20 < ema50
        and ema50 < ema200
    ):
        trend = "هابط"

    elif (
        current > ema20
        and ema20 > ema50
        and ema50 > ema200
    ):
        trend = "صاعد"

    else:
        trend = "متذبذب"

    # -----------------------------------------------------
    # TP / SL
    # -----------------------------------------------------

    if direction == "BUY":
        target_percent = 1.8
        stop_percent = 1.0

        entry = current

        take_profit = (
            entry
            * (1 + target_percent / 100)
        )

        stop_loss = (
            entry
            * (1 - stop_percent / 100)
        )

    elif direction == "SELL":
        target_percent = 1.8
        stop_percent = 1.0

        entry = current

        take_profit = (
            entry
            * (1 - target_percent / 100)
        )

        stop_loss = (
            entry
            * (1 + stop_percent / 100)
        )

    else:
        target_percent = 0
        stop_percent = 0

        entry = current
        take_profit = current
        stop_loss = current

    base = symbol.replace(
        "-USDT",
        ""
    )

    return {
        "name": base,
        "symbol": symbol,
        "source": "OKX Spot",

        "interval": interval,

        "signal": signal,
        "direction": direction,

        "score": round_num(score, 1),
        "score10": round_num(
            score / 10,
            1
        ),

        "price": round_num(
            current,
            8
        ),

        "entry": round_num(
            entry,
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

        "targetPercent": target_percent,
        "stopPercent": stop_percent,

        "rsi": round_num(
            current_rsi,
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
            macd_value,
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
            current_atr,
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
            support_distance,
            2
        ),

        "resistanceDistance": round_num(
            resistance_distance,
            2
        ),

        "trend": trend,

        "volatility": round_num(
            (
                current_atr / current * 100
                if current
                else 0
            ),
            2
        ),

        "updatedAt": now_ms()
    }


# =========================================================
# LIGHTWEIGHT CRYPTO SCAN
# =========================================================

def crypto_scan(interval="15m"):
    cache_key = (
        "crypto_scan_"
        + interval
    )

    cached = cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    instruments = okx_instruments()

    ticker_map = okx_all_tickers()

    # -----------------------------------------------------
    # القائمة كاملة
    # -----------------------------------------------------

    all_symbols = [
        item["symbol"]
        for item in instruments
    ]

    # -----------------------------------------------------
    # ترتيب حسب قيمة التداول
    # -----------------------------------------------------

    candidates = []

    for item in instruments:
        symbol = item["symbol"]

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:
            continue

        price = ticker["last"]

        volume_usdt = (
            ticker["volCcy24h"]
            * price
            if ticker["volCcy24h"] > 0
            else 0
        )

        change = pct(
            price,
            ticker["open24h"]
        )

        candidates.append({
            "symbol": symbol,
            "ticker": ticker,
            "volumeUSDT": volume_usdt,
            "change24h": change
        })

    candidates.sort(
        key=lambda x: x["volumeUSDT"],
        reverse=True
    )

    # -----------------------------------------------------
    # فقط العملات النشطة للتحليل
    # -----------------------------------------------------

    candidates = candidates[
        :ANALYZE_LIMIT
    ]

    results = []
    errors = []

    def analyze(item):
        symbol = item["symbol"]

        try:
            candles = okx_candles(
                symbol,
                interval,
                80
            )

            analysis = calculate_analysis(
                symbol,
                candles,
                item["ticker"],
                interval
            )

            if not analysis:
                return None

            analysis["change24h"] = round_num(
                item["change24h"],
                2
            )

            analysis["volume24h"] = round_num(
                item["volumeUSDT"],
                0
            )

            return analysis

        except Exception as e:
            return {
                "_error": symbol,
                "message": str(e)
            }

    # -----------------------------------------------------
    # طلبات محدودة
    # -----------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                analyze,
                item
            )
            for item in candidates
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
                    continue

                results.append(
                    result
                )

            except Exception as e:
                errors.append({
                    "message": str(e)
                })

    # -----------------------------------------------------
    # إشارات فقط
    # -----------------------------------------------------

    signals = [
        x for x in results
        if x.get("direction")
        in ("BUY", "SELL")
    ]

    # الأقوى أولاً
    signals.sort(
        key=lambda x: abs(
            safe_float(
                x.get("score")
            )
        ),
        reverse=True
    )

    results.sort(
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
            candidates
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
        SCAN_CACHE_SECONDS
    )

    return output


# =========================================================
# YAHOO MARKETS
# =========================================================

YAHOO_MARKETS = {

    "saudi": [
        ("TASI", "^TASI.SR", "تاسي"),
        ("ARAMCO", "2222.SR", "أرامكو"),
        ("SABIC", "2010.SR", "سابك"),
        ("ALRAJHI", "1120.SR", "الراجحي"),
        ("SNB", "1180.SR", "الأهلي"),
    ],

    "us": [
        ("SPY", "SPY", "S&P 500"),
        ("QQQ", "QQQ", "Nasdaq"),
        ("AAPL", "AAPL", "Apple"),
        ("NVDA", "NVDA", "NVIDIA"),
        ("MSFT", "MSFT", "Microsoft"),
        ("TSLA", "TSLA", "Tesla"),
        ("AMZN", "AMZN", "Amazon"),
        ("META", "META", "Meta"),
        ("GOOGL", "GOOGL", "Google"),
    ],

    "forex": [
        ("EURUSD", "EURUSD=X", "EUR/USD"),
        ("GBPUSD", "GBPUSD=X", "GBP/USD"),
        ("USDJPY", "JPY=X", "USD/JPY"),
        ("AUDUSD", "AUDUSD=X", "AUD/USD"),
    ],

    "commodities": [
        ("GOLD", "GC=F", "Gold"),
        ("OIL", "CL=F", "Oil"),
        ("SILVER", "SI=F", "Silver"),
    ],

    "indices": [
        ("SPX", "^GSPC", "S&P 500"),
        ("NDX", "^NDX", "Nasdaq 100"),
        ("DJI", "^DJI", "Dow Jones"),
        ("RUSSELL", "^RUT", "Russell 2000"),
    ],

    "futures": [
        ("ES", "ES=F", "S&P Futures"),
        ("NQ", "NQ=F", "Nasdaq Futures"),
        ("YM", "YM=F", "Dow Futures"),
        ("GC", "GC=F", "Gold Futures"),
        ("CL", "CL=F", "Oil Futures"),
    ]
}


def yahoo_chart(symbol, interval="15m"):
    if interval == "15m":
        range_value = "5d"
        yahoo_interval = "15m"

    elif interval == "1h":
        range_value = "1mo"
        yahoo_interval = "1h"

    elif interval == "4h":
        range_value = "3mo"
        yahoo_interval = "1h"

    else:
        range_value = "6mo"
        yahoo_interval = "1d"

    url = (
        YAHOO_BASE
        + "/v8/finance/chart/"
        + symbol
    )

    response = session.get(
        url,
        params={
            "range": range_value,
            "interval": yahoo_interval
        },
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    result = (
        data
        .get("chart", {})
        .get("result", [])
    )

    if not result:
        return []

    result = result[0]

    timestamps = result.get(
        "timestamp",
        []
    )

    quote = (
        result
        .get("indicators", {})
        .get("quote", [{}])[0]
    )

    opens = quote.get(
        "open",
        []
    )

    highs = quote.get(
        "high",
        []
    )

    lows = quote.get(
        "low",
        []
    )

    closes = quote.get(
        "close",
        []
    )

    volumes = quote.get(
        "volume",
        []
    )

    candles = []

    for i, timestamp in enumerate(
        timestamps
    ):
        try:
            if (
                opens[i] is None
                or highs[i] is None
                or lows[i] is None
                or closes[i] is None
            ):
                continue

            candles.append({
                "t": int(timestamp) * 1000,
                "o": safe_float(opens[i]),
                "h": safe_float(highs[i]),
                "l": safe_float(lows[i]),
                "c": safe_float(closes[i]),
                "v": safe_float(
                    volumes[i]
                    if i < len(volumes)
                    else 0
                )
            })

        except Exception:
            continue

    return candles


def yahoo_analysis(
    name,
    symbol,
    display_name,
    interval="15m"
):
    candles = yahoo_chart(
        symbol,
        interval
    )

    if len(candles) < 50:
        return None

    result = calculate_analysis(
        symbol,
        candles,
        None,
        interval
    )

    if not result:
        return None

    result["name"] = display_name
    result["symbol"] = name
    result["source"] = "Yahoo Finance"

    return result


def non_crypto_scan(
    market,
    interval="15m"
):
    items = YAHOO_MARKETS.get(
        market,
        []
    )

    results = []
    errors = []

    for name, symbol, display_name in items:
        try:
            result = yahoo_analysis(
                name,
                symbol,
                display_name,
                interval
            )

            if result:
                results.append(
                    result
                )

        except Exception as e:
            errors.append({
                "symbol": name,
                "message": str(e)
            })

    signals = [
        x for x in results
        if x.get("direction")
        in ("BUY", "SELL")
    ]

    signals.sort(
        key=lambda x: abs(
            safe_float(
                x.get("score")
            )
        ),
        reverse=True
    )

    results.sort(
        key=lambda x: abs(
            safe_float(
                x.get("score")
            )
        ),
        reverse=True
    )

    return {
        "ok": True,
        "source": "Yahoo Finance",
        "market": market,
        "interval": interval,
        "instrumentCount": len(items),
        "analyzedCount": len(results),
        "count": len(results),
        "signalCount": len(signals),
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
        okx_health()
    )


@app.route("/api/health")
def api_health():
    return jsonify(
        okx_health()
    )


@app.route("/api/crypto-symbols")
def crypto_symbols():
    try:
        instruments = okx_instruments()

        symbols = [
            x["symbol"]
            for x in instruments
        ]

        return jsonify({
            "ok": True,
            "source": "OKX Spot",
            "count": len(symbols),
            "symbols": symbols,
            "updatedAt": now_ms()
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "count": 0,
            "symbols": [],
            "error": str(e)
        }), 500


@app.route("/api/test-usdt")
def test_usdt():
    try:
        instruments = okx_instruments()

        tickers = okx_all_tickers()

        active = []

        for item in instruments:
            symbol = item["symbol"]

            ticker = tickers.get(
                symbol
            )

            if not ticker:
                continue

            active.append({
                "symbol": symbol,
                "price": ticker["last"],
                "change24h": round_num(
                    pct(
                        ticker["last"],
                        ticker["open24h"]
                    ),
                    2
                ),
                "volume24h": round_num(
                    ticker["volCcy24h"]
                    * ticker["last"],
                    0
                )
            })

        active.sort(
            key=lambda x: x["volume24h"],
            reverse=True
        )

        return jsonify({
            "ok": True,
            "source": "OKX Spot",
            "count": len(instruments),
            "activeCount": len(active),
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

    allowed_intervals = {
        "15m",
        "1h",
        "4h",
        "1d"
    }

    if interval not in allowed_intervals:
        interval = "15m"

    try:
        if market == "crypto":
            result = crypto_scan(
                interval
            )

        else:
            result = non_crypto_scan(
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
            "error": str(e),
            "updatedAt": now_ms()
        }), 500


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
            result = crypto_scan(
                interval
            )
        else:
            result = non_crypto_scan(
                market,
                interval
            )

        return jsonify({
            "ok": result.get("ok", False),
            "signals": result.get(
                "signals",
                []
            ),
            "count": result.get(
                "signalCount",
                0
            ),
            "market": market,
            "interval": interval,
            "updatedAt": result.get(
                "updatedAt"
            )
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "signals": [],
            "count": 0,
            "error": str(e)
        }), 500


@app.route("/api/analysis/<path:symbol>")
def api_analysis(symbol):
    interval = request.args.get(
        "interval",
        "15m"
    )

    try:
        if symbol.endswith("-USDT"):
            candles = okx_candles(
                symbol,
                interval,
                100
            )

            result = calculate_analysis(
                symbol,
                candles,
                None,
                interval
            )

            if not result:
                return jsonify({
                    "ok": False,
                    "error": "Not enough market data"
                }), 404

            return jsonify({
                "ok": True,
                "data": result,
                "updatedAt": now_ms()
            })

        return jsonify({
            "ok": False,
            "error": "Unknown symbol"
        }), 404

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/api/test-analysis")
def test_analysis():
    try:
        symbol = "BTC-USDT"
        interval = request.args.get(
            "interval",
            "15m"
        )

        candles = okx_candles(
            symbol,
            interval,
            100
        )

        result = calculate_analysis(
            symbol,
            candles,
            None,
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
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "ok": False,
        "error": "Not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "ok": False,
        "error": "Internal server error"
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
