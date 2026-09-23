import os
import time
import math
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, render_template, request


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

OKX_BASE = "https://openapi.okx.com"

REQUEST_TIMEOUT = 12
CACHE_SECONDS = 20

cache = {
    "scan": {},
    "price": {},
}

cache_lock = threading.Lock()


# =========================================================
# CRYPTO
# =========================================================

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


# =========================================================
# OTHER MARKETS
# =========================================================

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


# =========================================================
# HELPERS
# =========================================================

def now_ms():
    return int(time.time() * 1000)


def clean_symbol(symbol):
    return str(symbol).strip().upper()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def interval_ok(interval):
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


# =========================================================
# OKX REQUEST
# =========================================================

def okx_get(path, params=None):
    url = OKX_BASE + path

    try:
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
                f"OKX error {data.get('code')}: {data.get('msg')}"
            )

        return data

    except Exception as exc:
        raise RuntimeError(str(exc))


# =========================================================
# OKX PRICE
# =========================================================

def okx_price(symbol):
    symbol = clean_symbol(symbol)

    with cache_lock:
        item = cache["price"].get(symbol)

        if item:
            if time.time() - item["time"] < CACHE_SECONDS:
                return item["price"]

    data = okx_get(
        "/api/v5/market/ticker",
        {
            "instId": symbol,
        },
    )

    rows = data.get("data", [])

    if not rows:
        raise RuntimeError(f"No ticker data for {symbol}")

    price = safe_float(rows[0].get("last"))

    if price <= 0:
        raise RuntimeError(f"Invalid price for {symbol}")

    with cache_lock:
        cache["price"][symbol] = {
            "time": time.time(),
            "price": price,
        }

    return price


# =========================================================
# OKX CANDLES
# =========================================================

def okx_candles(symbol, interval="15m", limit=100):
    symbol = clean_symbol(symbol)
    interval = interval_ok(interval)

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": symbol,
            "bar": interval,
            "limit": str(min(int(limit), 300)),
        },
    )

    rows = data.get("data", [])

    if not rows:
        raise RuntimeError(f"No candle data for {symbol}")

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
            f"Not enough candles for {symbol}: {len(candles)}"
        )

    return candles


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if not values:
        return 0.0

    alpha = 2.0 / (period + 1.0)

    result = values[0]

    for value in values[1:]:
        result = (value * alpha) + (result * (1.0 - alpha))

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
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["h"] - current["l"],
            abs(current["h"] - previous["c"]),
            abs(current["l"] - previous["c"]),
        )

        trs.append(tr)

    if not trs:
        return 0.0

    recent = trs[-period:]

    return sum(recent) / len(recent)


def macd(values):
    if len(values) < 30:
        return 0.0, 0.0, 0.0

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)

    line = ema12 - ema26

    # Simplified signal calculation
    macd_values = []

    for i in range(max(0, len(values) - 40), len(values)):
        part = values[: i + 1]

        if len(part) >= 26:
            macd_values.append(
                ema(part, 12) - ema(part, 26)
            )

    signal = ema(macd_values, 9) if macd_values else 0.0

    histogram = line - signal

    return line, signal, histogram


# =========================================================
# ANALYSIS
# =========================================================

def analyze_crypto(symbol, interval="15m"):
    candles = okx_candles(
        symbol,
        interval,
        120,
    )

    closes = [x["c"] for x in candles]

    current = candles[-1]

    price = current["c"]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200) if len(closes) >= 200 else ema(closes, 100)

    rsi_value = rsi(closes, 14)

    atr_value = atr(candles, 14)

    macd_line, macd_signal, macd_hist = macd(closes)

    # -----------------------------------------------------
    # Momentum
    # -----------------------------------------------------

    if len(closes) >= 6:
        momentum = (
            (price - closes[-6])
            / closes[-6]
        ) * 100
    else:
        momentum = 0.0

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

    current_volume = current["v"]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0
        else 1
    )

    # -----------------------------------------------------
    # Support / resistance
    # -----------------------------------------------------

    recent = candles[-20:]

    support = min(
        x["l"]
        for x in recent
    )

    resistance = max(
        x["h"]
        for x in recent
    )

    # -----------------------------------------------------
    # Score
    # -----------------------------------------------------

    score = 50.0

    reasons = []

    # Trend
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

    # RSI
    if 52 <= rsi_value <= 68:
        score += 8
        reasons.append("RSI إيجابي")
    elif rsi_value < 45:
        score -= 8
        reasons.append("RSI ضعيف")
    elif rsi_value > 75:
        score -= 5
        reasons.append("RSI مرتفع")

    # MACD
    if macd_hist > 0:
        score += 7
        reasons.append("MACD إيجابي")
    else:
        score -= 7
        reasons.append("MACD سلبي")

    # Momentum
    if momentum > 0.25:
        score += 7
        reasons.append("زخم صاعد")
    elif momentum < -0.25:
        score -= 7
        reasons.append("زخم هابط")

    # Volume
    if volume_ratio >= 1.20:
        if momentum >= 0:
            score += 5
            reasons.append("حجم تداول مرتفع")
        else:
            score -= 5
            reasons.append("ضغط بيع بحجم مرتفع")

    score = round(
        clamp(score, 0, 100),
        1,
    )

    # -----------------------------------------------------
    # Signal
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TP / SL
    # -----------------------------------------------------

    volatility_percent = (
        (atr_value / price) * 100
        if price > 0
        else 1
    )

    volatility_percent = clamp(
        volatility_percent,
        0.5,
        4.0,
    )

    stop_percent = max(
        1.0,
        volatility_percent * 1.25,
    )

    target_percent = stop_percent * 2

    if direction == "BUY":
        entry = price
        stop = price * (1 - stop_percent / 100)
        target = price * (1 + target_percent / 100)

    elif direction == "SELL":
        entry = price
        stop = price * (1 + stop_percent / 100)
        target = price * (1 - target_percent / 100)

    else:
        entry = price
        stop = None
        target = None

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

    # -----------------------------------------------------
    # Result
    # -----------------------------------------------------

    return {
        "symbol": symbol.replace("-USDT", "/USDT"),
        "rawSymbol": symbol,

        "market": "crypto",

        "interval": interval,

        "price": round_price(price),

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10": round(score / 10, 1),

        "entry": round_price(entry),
        "target": round_price(target),
        "stop": round_price(stop),

        "tpPercent": round(target_percent, 2),
        "slPercent": round(stop_percent, 2),

        "rsi": round(rsi_value, 2),

        "ema20": round_price(ema20),
        "ema50": round_price(ema50),
        "ema200": round_price(ema200),

        "macd": round(macd_line, 8),
        "macdSignal": round(macd_signal, 8),
        "macdHistogram": round(macd_hist, 8),

        "atrPercent": round(volatility_percent, 3),

        "momentum": round(momentum, 3),

        "volumeRatio": round(volume_ratio, 2),

        "support": round_price(support),
        "resistance": round_price(resistance),

        "reasons": reasons[:8],

        "source": "OKX",

        "updatedAt": now_ms(),
    }


# =========================================================
# SCAN CRYPTO
# =========================================================

def scan_crypto(interval="15m"):
    interval = interval_ok(interval)

    cache_key = f"crypto:{interval}"

    with cache_lock:
        cached = cache["scan"].get(cache_key)

        if cached:
            if time.time() - cached["time"] < CACHE_SECONDS:
                result = dict(cached["data"])
                result["cached"] = True
                return result

    results = []
    errors = []

    # لا نضغط على OKX بعدد كبير من الطلبات
    workers = min(
        5,
        len(CRYPTO_SYMBOLS),
    )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {
            executor.submit(
                analyze_crypto,
                symbol,
                interval,
            ): symbol

            for symbol in CRYPTO_SYMBOLS
        }

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                result = future.result()

                results.append(result)

            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "error": str(exc),
                    }
                )

    # الأقوى أولاً
    results.sort(
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    buy_signals = [
        x for x in results
        if x.get("direction") == "BUY"
    ]

    sell_signals = [
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
            buy_signals[:10]
            + sell_signals[:10]
        ),

        "errors": errors[:10],

        "cached": False,

        "updatedAt": now_ms(),
    }

    with cache_lock:
        cache["scan"][cache_key] = {
            "time": time.time(),
            "data": data,
        }

    return data


# =========================================================
# YAHOO FALLBACK FOR NON-CRYPTO
# =========================================================

YAHOO_BASE = "https://query1.finance.yahoo.com"


def yahoo_chart(symbol, interval="15m"):
    symbol = clean_symbol(symbol)

    # Yahoo intraday limitations
    yahoo_interval = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1H": "60m",
        "1D": "1d",
    }.get(interval, "15m")

    range_value = (
        "5d"
        if yahoo_interval in {
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

    result = data.get(
        "chart",
        {},
    ).get(
        "result",
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

    for i, timestamp in enumerate(timestamps):

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
            f"Not enough Yahoo candles for {symbol}"
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

    ema200 = (
        ema(closes, 200)
        if len(closes) >= 200
        else ema(closes, min(100, len(closes)))
    )

    rsi_value = rsi(closes)

    macd_line, macd_signal, macd_hist = macd(
        closes
    )

    if len(closes) >= 6:
        momentum = (
            (price - closes[-6])
            / closes[-6]
        ) * 100
    else:
        momentum = 0

    score = 50

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

    risk = 0.02

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

        "price": round(price, 4),

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10": round(score / 10, 1),

        "entry": round(price, 4),
        "target": (
            round(target, 4)
            if target
            else None
        ),
        "stop": (
            round(stop, 4)
            if stop
            else None
        ),

        "tpPercent": 4.0,
        "slPercent": 2.0,

        "rsi": round(rsi_value, 2),

        "ema20": round(ema20, 4),
        "ema50": round(ema50, 4),
        "ema200": round(ema200, 4),

        "macd": round(macd_line, 8),
        "macdSignal": round(macd_signal, 8),
        "macdHistogram": round(macd_hist, 8),

        "momentum": round(momentum, 3),

        "reasons": reasons,

        "source": "Yahoo Finance",

        "updatedAt": now_ms(),
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


@app.route("/api/price/<symbol>")
def api_price(symbol):

    symbol = clean_symbol(symbol)

    # تحويل BTCUSDT إلى BTC-USDT
    if "-" not in symbol:
        if symbol.endswith("USDT"):
            symbol = (
                symbol[:-4]
                + "-USDT"
            )

    try:
        price = okx_price(symbol)

        return jsonify(
            {
                "ok": True,
                "symbol": symbol,
                "price": price,
                "source": "OKX",
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

    interval = request.args.get(
        "interval",
        "15m",
    )

    interval = interval_ok(interval)

    market = request.args.get(
        "market",
        "crypto",
    ).lower()

    # -----------------------------------------------------
    # CRYPTO
    # -----------------------------------------------------

    if market in {
        "crypto",
        "cryptocurrency",
        "coins",
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

    # -----------------------------------------------------
    # OTHER MARKETS
    # -----------------------------------------------------

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

        for future in as_completed(futures):

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
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    signals = [
        x
        for x in results
        if x.get("direction") != "NEUTRAL"
    ]

    return jsonify(
        {
            "ok": True,
            "market": market,
            "source": (
                "Yahoo Finance"
                if market != "crypto"
                else "OKX"
            ),
            "interval": interval,
            "count": len(results),
            "results": results,
            "signals": signals,
            "errors": errors[:10],
            "cached": False,
            "updatedAt": now_ms(),
        }
    )


@app.route("/api/signals")
def api_signals():

    interval = interval_ok(
        request.args.get(
            "interval",
            "15m",
        )
    )

    try:
        data = scan_crypto(interval)

        return jsonify(
            {
                "ok": True,
                "signals": data.get(
                    "signals",
                    [],
                ),
                "count": len(
                    data.get(
                        "signals",
                        [],
                    )
                ),
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
def api_market_signals():

    interval = interval_ok(
        request.args.get(
            "interval",
            "15m",
        )
    )

    output = []

    for market in MARKETS:

        try:
            if market == "crypto":
                data = scan_crypto(
                    interval
                )
                output.extend(
                    data.get(
                        "results",
                        [],
                    )
                )

        except Exception:
            continue

    output.sort(
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    return jsonify(
        {
            "ok": True,
            "count": len(output),
            "results": output,
            "signals": [
                x for x in output
                if x.get("direction")
                != "NEUTRAL"
            ],
            "source": "OKX Spot",
            "interval": interval,
            "updatedAt": now_ms(),
        }
    )


@app.route("/api/analysis/<symbol>")
def api_analysis(symbol):

    symbol = clean_symbol(symbol)

    if "-" not in symbol:
        if symbol.endswith("USDT"):
            symbol = (
                symbol[:-4]
                + "-USDT"
            )

    interval = interval_ok(
        request.args.get(
            "interval",
            "15m",
        )
    )

    try:

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
                "error": str(exc),
                "symbol": symbol,
            }
        ), 502


@app.route("/api/status")
def api_status():

    return jsonify(
        {
            "ok": True,
            "app": "مضارب أبو سعود",
            "cryptoSource": "OKX",
            "cryptoSymbols": len(
                CRYPTO_SYMBOLS
            ),
            "defaultInterval": "15m",
            "liveAnalysis": True,
            "charts": False,
            "login": False,
            "updatedAt": now_ms(),
        }
    )


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify(
        {
            "ok": False,
            "error": "Not found",
        }
    ), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify(
        {
            "ok": False,
            "error": "Internal server error",
        }
    ), 500


# =========================================================
# LOCAL
# =========================================================

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

[/writing]

بعد الاستبدال

ما تحتاج تضيف API Key لـ OKX؛ هذا الكود يستخدم بيانات السوق العامة فقط.

بعد Deploy افتح بالترتيب:

1.
"https://mwq-tdwl.onrender.com/health"

المفروض تشوف:

{
  "ok": true,
  "online": true,
  "source": "OKX"
}

2.
"https://mwq-tdwl.onrender.com/api/scan?interval=15m"

المفروض الآن يكون:

"count": 20

وتلقى داخل "results" أسعار وتحليلات مثل:

BTC/USDT
signal: شراء
entry
target
stop
score
rsi

مهم: إذا ظهر "count: 0" مرة ثانية، الكود الجديد لن يخفي المشكلة؛ سيضع الخطأ الحقيقي داخل "error" أو "errors" عشان نعرف مباشرة وش يمنع الاتصال.

وبالنسبة لـ OKX، عنوان REST الرسمي للإنتاج هو "https://openapi.okx.com"، وواجهة الشموع العامة تدعم "15m".

لا تغيّر "app.js" الآن. خلنا أول نتأكد أن "/api/scan" يرجع البيانات، وبعدها نضبط العرض إذا احتاج.
