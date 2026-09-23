import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, render_template, request


app = Flask(__name__)

OKX_BASE = "https://openapi.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

REQUEST_TIMEOUT = 15
CACHE_SECONDS = 20

cache = {
    "scan": {},
    "price": {},
}

cache_lock = threading.Lock()


CRYPTO_SYMBOLS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "XRP-USDT",
    "BNB-USDT",
    "DOGE-USDT",
    "ADA-USDT",
    "AVAX-USDT",
    "LINK-USDT",
    "SUI-USDT",
    "TRX-USDT",
    "DOT-USDT",
    "LTC-USDT",
    "NEAR-USDT",
    "APT-USDT",
    "ATOM-USDT",
    "UNI-USDT",
    "FIL-USDT",
    "ETC-USDT",
    "OP-USDT",
]


MARKETS = {
    "crypto": CRYPTO_SYMBOLS,

    "saudi": [
        "2222.SR",
        "1120.SR",
        "2010.SR",
        "1180.SR",
        "1150.SR",
        "7010.SR",
        "2380.SR",
        "4031.SR",
        "4003.SR",
        "5110.SR",
    ],

    "us": [
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
    ],

    "forex": [
        "EURUSD=X",
        "GBPUSD=X",
        "USDJPY=X",
        "AUDUSD=X",
        "USDCAD=X",
        "USDCHF=X",
    ],

    "commodities": [
        "GC=F",
        "CL=F",
        "SI=F",
    ],

    "indices": [
        "^GSPC",
        "^IXIC",
        "^DJI",
        "^FTSE",
        "^N225",
    ],

    "futures": [
        "ES=F",
        "NQ=F",
        "YM=F",
        "RTY=F",
    ],
}


def now_ms():
    return int(time.time() * 1000)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_interval(interval):
    allowed = {
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1H",
        "2H",
        "4H",
        "6H",
        "12H",
        "1D",
        "1W",
        "1M",
    }

    return interval if interval in allowed else "15m"


def okx_get(path, params=None):
    url = OKX_BASE + path

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    data = response.json()

    if str(data.get("code", "0")) != "0":
        raise RuntimeError(
            f"OKX {data.get('code')}: {data.get('msg')}"
        )

    return data


def normalize_crypto_symbol(symbol):
    symbol = str(symbol).strip().upper()

    if "-" in symbol:
        return symbol

    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"

    return symbol


def okx_price(symbol):
    symbol = normalize_crypto_symbol(symbol)

    with cache_lock:
        item = cache["price"].get(symbol)

        if item and time.time() - item["time"] < CACHE_SECONDS:
            return item["price"]

    data = okx_get(
        "/api/v5/market/ticker",
        {
            "instId": symbol,
        },
    )

    rows = data.get("data", [])

    if not rows:
        raise RuntimeError(
            f"No price data for {symbol}"
        )

    price = safe_float(rows[0].get("last"))

    if price <= 0:
        raise RuntimeError(
            f"Invalid price for {symbol}"
        )

    with cache_lock:
        cache["price"][symbol] = {
            "time": time.time(),
            "price": price,
        }

    return price


def okx_candles(symbol, interval="15m", limit=120):
    symbol = normalize_crypto_symbol(symbol)
    interval = normalize_interval(interval)

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": symbol,
            "bar": interval,
            "limit": str(min(limit, 300)),
        },
    )

    rows = data.get("data", [])

    if not rows:
        raise RuntimeError(
            f"No candle data for {symbol}"
        )

    candles = []

    for row in reversed(rows):
        if len(row) < 6:
            continue

        candles.append(
            {
                "t": int(row[0]),
                "o": safe_float(row[1]),
                "h": safe_float(row[2]),
                "l": safe_float(row[3]),
                "c": safe_float(row[4]),
                "v": safe_float(row[5]),
                "confirm": row[8] if len(row) > 8 else "1",
            }
        )

    if len(candles) < 30:
        raise RuntimeError(
            f"Not enough candles: {len(candles)}"
        )

    return candles


def ema(values, period):
    if not values:
        return 0.0

    alpha = 2.0 / (period + 1.0)
    result = values[0]

    for value in values[1:]:
        result = (
            value * alpha
            + result * (1.0 - alpha)
        )

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

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

    return 100.0 - (
        100.0 / (1.0 + rs)
    )


def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    values = []

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
            ),
        )

        values.append(tr)

    return (
        sum(values[-period:])
        / min(period, len(values))
    )


def macd(values):
    if len(values) < 30:
        return 0.0, 0.0, 0.0

    line_values = []

    start = max(26, len(values) - 50)

    for i in range(start, len(values)):
        part = values[:i + 1]

        line_values.append(
            ema(part, 12)
            - ema(part, 26)
        )

    line = line_values[-1]

    signal = ema(
        line_values,
        9,
    )

    histogram = line - signal

    return line, signal, histogram


def round_price(value):
    if value is None:
        return None

    if value >= 1000:
        return round(value, 2)

    if value >= 1:
        return round(value, 4)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


def analyze_crypto(symbol, interval="15m"):
    candles = okx_candles(
        symbol,
        interval,
        120,
    )

    closes = [
        x["c"]
        for x in candles
    ]

    current = candles[-1]
    price = current["c"]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    if len(closes) >= 100:
        ema200 = ema(closes, 100)
    else:
        ema200 = ema(
            closes,
            min(50, len(closes)),
        )

    rsi_value = rsi(closes, 14)

    atr_value = atr(
        candles,
        14,
    )

    macd_line, macd_signal, macd_hist = macd(
        closes
    )

    if len(closes) >= 6:
        momentum = (
            (price - closes[-6])
            / closes[-6]
        ) * 100
    else:
        momentum = 0.0

    volumes = [
        x["v"]
        for x in candles[-21:-1]
    ]

    average_volume = (
        sum(volumes)
        / len(volumes)
        if volumes
        else 0.0
    )

    volume_ratio = (
        current["v"]
        / average_volume
        if average_volume > 0
        else 1.0
    )

    recent = candles[-20:]

    support = min(
        x["l"]
        for x in recent
    )

    resistance = max(
        x["h"]
        for x in recent
    )

    score = 50.0
    reasons = []

    if price > ema20:
        score += 8
        reasons.append("السعر فوق EMA20")
    else:
        score -= 8
        reasons.append("السعر تحت EMA20")

    if price > ema50:
        score += 8
        reasons.append("السعر فوق EMA50")
    else:
        score -= 8
        reasons.append("السعر تحت EMA50")

    if price > ema200:
        score += 10
        reasons.append("الاتجاه فوق EMA200")
    else:
        score -= 10
        reasons.append("الاتجاه تحت EMA200")

    if 52 <= rsi_value <= 68:
        score += 8
        reasons.append("RSI إيجابي")
    elif rsi_value < 45:
        score -= 8
        reasons.append("RSI ضعيف")
    elif rsi_value > 75:
        score -= 5
        reasons.append("RSI مرتفع")

    if macd_hist > 0:
        score += 7
        reasons.append("MACD إيجابي")
    else:
        score -= 7
        reasons.append("MACD سلبي")

    if momentum > 0.25:
        score += 7
        reasons.append("زخم صاعد")
    elif momentum < -0.25:
        score -= 7
        reasons.append("زخم هابط")

    if volume_ratio >= 1.20:
        if momentum >= 0:
            score += 5
            reasons.append("حجم مرتفع")
        else:
            score -= 5
            reasons.append("ضغط بيع بحجم مرتفع")

    score = round(
        clamp(score, 0, 100),
        1,
    )

    if score >= 68:
        signal = "شراء قوي"
        direction = "BUY"

    elif score >= 58:
        signal = "شراء"
        direction = "BUY"

    elif score <= 32:
        signal = "بيع قوي"
        direction = "SELL"

    elif score <= 42:
        signal = "بيع"
        direction = "SELL"

    else:
        signal = "حيادي"
        direction = "NEUTRAL"

    volatility = (
        atr_value / price * 100
        if price > 0
        else 1.0
    )

    volatility = clamp(
        volatility,
        0.5,
        4.0,
    )

    stop_percent = max(
        1.0,
        volatility * 1.25,
    )

    target_percent = stop_percent * 2

    if direction == "BUY":
        entry = price
        target = price * (
            1 + target_percent / 100
        )
        stop = price * (
            1 - stop_percent / 100
        )

    elif direction == "SELL":
        entry = price
        target = price * (
            1 - target_percent / 100
        )
        stop = price * (
            1 + stop_percent / 100
        )

    else:
        entry = price
        target = None
        stop = None

    return {
        "symbol": symbol.replace(
            "-USDT",
            "/USDT",
        ),
        "rawSymbol": symbol,
        "market": "crypto",
        "interval": interval,

        "price": round_price(price),

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10": round(
            score / 10,
            1,
        ),

        "entry": round_price(entry),
        "target": round_price(target),
        "stop": round_price(stop),

        "tpPercent": round(
            target_percent,
            2,
        ),
        "slPercent": round(
            stop_percent,
            2,
        ),

        "rsi": round(
            rsi_value,
            2,
        ),

        "ema20": round_price(ema20),
        "ema50": round_price(ema50),
        "ema200": round_price(ema200),

        "macd": round(
            macd_line,
            8,
        ),
        "macdSignal": round(
            macd_signal,
            8,
        ),
        "macdHistogram": round(
            macd_hist,
            8,
        ),

        "atrPercent": round(
            volatility,
            3,
        ),

        "momentum": round(
            momentum,
            3,
        ),

        "volumeRatio": round(
            volume_ratio,
            2,
        ),

        "support": round_price(
            support
        ),
        "resistance": round_price(
            resistance
        ),

        "reasons": reasons,

        "source": "OKX Spot",

        "updatedAt": now_ms(),
    }


def scan_crypto(interval="15m"):
    interval = normalize_interval(interval)

    cache_key = f"crypto:{interval}"

    with cache_lock:
        cached = cache["scan"].get(
            cache_key
        )

        if cached:
            if (
                time.time()
                - cached["time"]
                < CACHE_SECONDS
            ):
                result = dict(
                    cached["data"]
                )
                result["cached"] = True
                return result

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        futures = {
            executor.submit(
                analyze_crypto,
                symbol,
                interval,
            ): symbol
            for symbol in CRYPTO_SYMBOLS
        }

        for future in as_completed(
            futures
        ):
            symbol = futures[future]

            try:
                results.append(
                    future.result()
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "error": str(exc),
                    }
                )

    results.sort(
        key=lambda x: x.get(
            "score",
            0,
        ),
        reverse=True,
    )

    buy = [
        x for x in results
        if x.get("direction") == "BUY"
    ]

    sell = [
        x for x in results
        if x.get("direction") == "SELL"
    ]

    data = {
        "ok": True,
        "market": "crypto",
        "source": "OKX Spot",
        "interval": interval,
        "count": len(results),
        "results": results,
        "signals": (
            buy[:10] + sell[:10]
        ),
        "errors": errors,
        "cached": False,
        "updatedAt": now_ms(),
    }

    with cache_lock:
        cache["scan"][cache_key] = {
            "time": time.time(),
            "data": data,
        }

    return data


def yahoo_chart(
    symbol,
    interval="15m",
):
    interval_map = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1H": "60m",
        "1D": "1d",
    }

    yahoo_interval = interval_map.get(
        interval,
        "15m",
    )

    range_value = (
        "5d"
        if yahoo_interval
        in {
            "1m",
            "5m",
            "15m",
            "30m",
            "60m",
        }
        else "1mo"
    )

    url = (
        f"{YAHOO_BASE}/v8/finance/chart/"
        f"{symbol}"
    )

    response = requests.get(
        url,
        params={
            "interval": yahoo_interval,
            "range": range_value,
        },
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    response.raise_for_status()

    data = response.json()

    result = (
        data.get("chart", {})
        .get("result")
    )

    if not result:
        raise RuntimeError(
            f"No Yahoo data for {symbol}"
        )

    result = result[0]

    timestamps = result.get(
        "timestamp",
        [],
    )

    quote = (
        result
        .get("indicators", {})
        .get("quote", [{}])[0]
    )

    candles = []

    for i, timestamp in enumerate(
        timestamps
    ):
        try:
            o = quote["open"][i]
            h = quote["high"][i]
            l = quote["low"][i]
            c = quote["close"][i]
            v = quote["volume"][i]

            if None in (
                o,
                h,
                l,
                c,
            ):
                continue

            candles.append(
                {
                    "t": int(timestamp) * 1000,
                    "o": float(o),
                    "h": float(h),
                    "l": float(l),
                    "c": float(c),
                    "v": float(v or 0),
                }
            )

        except Exception:
            continue

    if len(candles) < 30:
        raise RuntimeError(
            f"Not enough Yahoo data for {symbol}"
        )

    return candles


def analyze_generic(
    symbol,
    market,
    interval="15m",
):
    candles = yahoo_chart(
        symbol,
        interval,
    )

    closes = [
        x["c"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    ema200 = ema(
        closes,
        min(
            100,
            len(closes),
        ),
    )

    rsi_value = rsi(closes)

    macd_line, macd_signal, macd_hist = macd(
        closes
    )

    if len(closes) >= 6:
        momentum = (
            (
                price
                - closes[-6]
            )
            / closes[-6]
        ) * 100
    else:
        momentum = 0.0

    score = 50.0
    reasons = []

    if price > ema20:
        score += 10
        reasons.append("فوق EMA20")
    else:
        score -= 10
        reasons.append("تحت EMA20")

    if price > ema50:
        score += 10
        reasons.append("فوق EMA50")
    else:
        score -= 10
        reasons.append("تحت EMA50")

    if price > ema200:
        score += 10
        reasons.append("الاتجاه صاعد")
    else:
        score -= 10
        reasons.append("الاتجاه هابط")

    if rsi_value >= 52:
        score += 7
        reasons.append("RSI إيجابي")
    elif rsi_value <= 45:
        score -= 7
        reasons.append("RSI ضعيف")

    if macd_hist > 0:
        score += 7
        reasons.append("MACD إيجابي")
    else:
        score -= 7
        reasons.append("MACD سلبي")

    if momentum > 0.2:
        score += 6
        reasons.append("زخم صاعد")
    elif momentum < -0.2:
        score -= 6
        reasons.append("زخم هابط")

    score = round(
        clamp(score, 0, 100),
        1,
    )

    if score >= 68:
        signal = "شراء قوي"
        direction = "BUY"
    elif score >= 58:
        signal = "شراء"
        direction = "BUY"
    elif score <= 32:
        signal = "بيع قوي"
        direction = "SELL"
    elif score <= 42:
        signal = "بيع"
        direction = "SELL"
    else:
        signal = "حيادي"
        direction = "NEUTRAL"

    if direction == "BUY":
        target = price * 1.04
        stop = price * 0.98
    elif direction == "SELL":
        target = price * 0.96
        stop = price * 1.02
    else:
        target = None
        stop = None

    return {
        "symbol": symbol,
        "rawSymbol": symbol,
        "market": market,
        "interval": interval,
        "price": round_price(price),
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(
            score / 10,
            1,
        ),
        "entry": round_price(price),
        "target": round_price(target),
        "stop": round_price(stop),
        "tpPercent": 4.0,
        "slPercent": 2.0,
        "rsi": round(
            rsi_value,
            2,
        ),
        "ema20": round_price(ema20),
        "ema50": round_price(ema50),
        "ema200": round_price(ema200),
        "macd": round(
            macd_line,
            8,
        ),
        "macdSignal": round(
            macd_signal,
            8,
        ),
        "macdHistogram": round(
            macd_hist,
            8,
        ),
        "momentum": round(
            momentum,
            3,
        ),
        "reasons": reasons,
        "source": "Yahoo Finance",
        "updatedAt": now_ms(),
    }


@app.route("/")
def index():
    return render_template(
        "index.html"
    )


@app.route("/health")
def health():
    result = {
        "ok": False,
        "online": False,
        "source": "OKX",
        "error": None,
    }

    try:
        data = okx_get(
            "/api/v5/public/time"
        )

        if data.get("code") == "0":
            result["ok"] = True
            result["online"] = True

            rows = data.get(
                "data",
                [],
            )

            if rows:
                result["serverTime"] = rows[0].get(
                    "ts"
                )

    except Exception as exc:
        result["error"] = str(exc)

    return jsonify(result)


@app.route("/api/status")
def status():
    return jsonify(
        {
            "ok": True,
            "app": "مضارب أبو سعود",
            "cryptoSource": "OKX Spot",
            "cryptoSymbols": len(
                CRYPTO_SYMBOLS
            ),
            "interval": "15m",
            "liveAnalysis": True,
            "charts": False,
            "login": False,
            "updatedAt": now_ms(),
        }
    )


@app.route("/api/price/<symbol>")
def api_price(symbol):
    try:
        symbol = normalize_crypto_symbol(
            symbol
        )

        price = okx_price(symbol)

        return jsonify(
            {
                "ok": True,
                "symbol": symbol,
                "price": price,
                "source": "OKX Spot",
                "updatedAt": now_ms(),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "symbol": symbol,
                "error": str(exc),
            }
        ), 502


@app.route("/api/scan")
def api_scan():
    interval = normalize_interval(
        request.args.get(
            "interval",
            "15m",
        )
    )

    market = request.args.get(
        "market",
        "crypto",
    ).lower()

    if market in {
        "crypto",
        "coins",
        "cryptocurrency",
    }:
        try:
            return jsonify(
                scan_crypto(interval)
            )

        except Exception as exc:
            return jsonify(
                {
                    "ok": False,
                    "market": "crypto",
                    "source": "OKX Spot",
                    "interval": interval,
                    "count": 0,
                    "results": [],
                    "signals": [],
                    "error": str(exc),
                    "updatedAt": now_ms(),
                }
            ), 502

    symbols = MARKETS.get(
        market,
        [],
    )

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        futures = {
            executor.submit(
                analyze_generic,
                symbol,
                market,
                interval,
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):
            symbol = futures[future]

            try:
                results.append(
                    future.result()
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "error": str(exc),
                    }
                )

    results.sort(
        key=lambda x: x.get(
            "score",
            0,
        ),
        reverse=True,
    )

    signals = [
        x for x in results
        if x.get("direction")
        != "NEUTRAL"
    ]

    return jsonify(
        {
            "ok": True,
            "market": market,
            "source": "Yahoo Finance",
            "interval": interval,
            "count": len(results),
            "results": results,
            "signals": signals,
            "errors": errors[:20],
            "cached": False,
            "updatedAt": now_ms(),
        }
    )


@app.route("/api/signals")
def api_signals():
    interval = normalize_interval(
        request.args.get(
            "interval",
            "15m",
        )
    )

    try:
        data = scan_crypto(interval)

        signals = data.get(
            "signals",
            [],
        )

        return jsonify(
            {
                "ok": True,
                "signals": signals,
                "count": len(signals),
                "source": "OKX Spot",
                "interval": interval,
                "updatedAt": now_ms(),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "signals": [],
                "count": 0,
                "source": "OKX Spot",
                "error": str(exc),
            }
        ), 502


@app.route("/api/market-signals")
def market_signals():
    interval = normalize_interval(
        request.args.get(
            "interval",
            "15m",
        )
    )

    try:
        data = scan_crypto(interval)

        results = data.get(
            "results",
            [],
        )

        signals = [
            x for x in results
            if x.get("direction")
            != "NEUTRAL"
        ]

        return jsonify(
            {
                "ok": True,
                "count": len(results),
                "results": results,
                "signals": signals,
                "source": "OKX Spot",
                "interval": interval,
                "updatedAt": now_ms(),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "count": 0,
                "results": [],
                "signals": [],
                "source": "OKX Spot",
                "error": str(exc),
            }
        ), 502


@app.route("/api/analysis/<symbol>")
def analysis(symbol):
    interval = normalize_interval(
        request.args.get(
            "interval",
            "15m",
        )
    )

    try:
        symbol = normalize_crypto_symbol(
            symbol
        )

        result = analyze_crypto(
            symbol,
            interval,
        )

        return jsonify(
            {
                "ok": True,
                "analysis": result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "symbol": symbol,
                "error": str(exc),
            }
        ), 502


@app.errorhandler(404)
def not_found(error):
    return jsonify(
        {
            "ok": False,
            "error": "Not found",
        }
    ), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify(
        {
            "ok": False,
            "error": "Internal server error",
        }
    ), 500


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "10000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
