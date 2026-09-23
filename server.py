# -*- coding: utf-8 -*-

import os
import time
import math
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

import requests
from flask import Flask, jsonify, request, render_template


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)


# =========================================================
# SETTINGS
# =========================================================

OKX_BASE = "https://www.okx.com"

YAHOO_CHART = (
    "https://query1.finance.yahoo.com/v8/finance/chart"
)

# SAHMK
SAHMK_BASE = "https://api.sahmk.sa"

SAHMK_API_KEY = os.environ.get(
    "SAHMK_API_KEY",
    ""
).strip()

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "Mudarib-Abo-Saud/2.0"
    ),
    "Accept": (
        "application/json,"
        "text/plain,"
        "*/*"
    )
})

CACHE = {}
CACHE_LOCK = threading.Lock()


# =========================================================
# CACHE
# =========================================================

def cache_get(key):

    with CACHE_LOCK:

        item = CACHE.get(key)

        if not item:
            return None

        expires, value = item

        if time.time() > expires:

            CACHE.pop(key, None)

            return None

        return value


def cache_set(
    key,
    value,
    seconds=60
):

    with CACHE_LOCK:

        CACHE[key] = (
            time.time() + seconds,
            value
        )


# =========================================================
# HELPERS
# =========================================================

def safe_float(
    value,
    default=0.0
):

    try:

        if value is None:
            return default

        return float(value)

    except Exception:

        return default


def round_price(value):

    value = safe_float(value)

    if value >= 1000:
        return round(value, 2)

    if value >= 100:
        return round(value, 3)

    if value >= 1:
        return round(value, 4)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def clean_html(text):

    if not text:
        return ""

    text = unescape(str(text))

    result = []

    inside = False

    for char in text:

        if char == "<":
            inside = True
            continue

        if char == ">":
            inside = False
            continue

        if not inside:
            result.append(char)

    return "".join(result).strip()


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):

    if not values:
        return []

    period = max(
        1,
        int(period)
    )

    if len(values) < period:

        return [
            None
            for _ in values
        ]

    multiplier = 2 / (
        period + 1
    )

    result = [
        None
        for _ in values
    ]

    initial = sum(
        values[:period]
    ) / period

    result[period - 1] = initial

    previous = initial

    for i in range(
        period,
        len(values)
    ):

        previous = (
            (
                values[i]
                - previous
            )
            * multiplier
            + previous
        )

        result[i] = previous

    return result


def rsi(
    values,
    period=14
):

    if len(values) <= period:

        return [
            None
            for _ in values
        ]

    result = [
        None
        for _ in values
    ]

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

    if avg_loss == 0:

        result[period] = 100

    else:

        rs = (
            avg_gain
            / avg_loss
        )

        result[period] = (
            100
            - (
                100
                / (1 + rs)
            )
        )

    for i in range(
        period + 1,
        len(values)
    ):

        gain = gains[i - 1]
        loss = losses[i - 1]

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gain
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + loss
        ) / period

        if avg_loss == 0:

            result[i] = 100

        else:

            rs = (
                avg_gain
                / avg_loss
            )

            result[i] = (
                100
                - (
                    100
                    / (1 + rs)
                )
            )

    return result


def atr(
    highs,
    lows,
    closes,
    period=14
):

    if len(closes) <= period:

        return [
            None
            for _ in closes
        ]

    tr = [None]

    for i in range(
        1,
        len(closes)
    ):

        value = max(
            highs[i] - lows[i],
            abs(
                highs[i]
                - closes[i - 1]
            ),
            abs(
                lows[i]
                - closes[i - 1]
            )
        )

        tr.append(value)

    result = [
        None
        for _ in closes
    ]

    first = (
        sum(
            x
            for x in tr[
                1:period + 1
            ]
            if x is not None
        )
        / period
    )

    result[period] = first

    previous = first

    for i in range(
        period + 1,
        len(closes)
    ):

        previous = (
            (
                previous
                * (period - 1)
            )
            + tr[i]
        ) / period

        result[i] = previous

    return result


def macd(values):

    e12 = ema(
        values,
        12
    )

    e26 = ema(
        values,
        26
    )

    line = [
        None
        for _ in values
    ]

    for i in range(
        len(values)
    ):

        if (
            e12[i] is not None
            and e26[i] is not None
        ):

            line[i] = (
                e12[i]
                - e26[i]
            )

    valid = [
        x
        for x in line
        if x is not None
    ]

    signal_values = ema(
        valid,
        9
    )

    signal = [
        None
        for _ in values
    ]

    pos = 0

    for i in range(
        len(values)
    ):

        if line[i] is not None:

            if (
                pos
                < len(signal_values)
            ):

                signal[i] = (
                    signal_values[pos]
                )

            pos += 1

    histogram = [
        None
        for _ in values
    ]

    for i in range(
        len(values)
    ):

        if (
            line[i] is not None
            and signal[i] is not None
        ):

            histogram[i] = (
                line[i]
                - signal[i]
            )

    return (
        line,
        signal,
        histogram
    )


# =========================================================
# ANALYSIS
# =========================================================

def analyze_candles(candles):

    if (
        not candles
        or len(candles) < 60
    ):

        return {
            "signal": "غير متاح",
            "direction": "neutral",
            "score": 50,
            "score10": 5.0,
            "price": 0,
            "entry": 0,
            "tp1": 0,
            "tp2": 0,
            "tp3": 0,
            "sl": 0,
            "rsi": 0,
            "ema20": 0,
            "ema50": 0,
            "ema200": 0,
            "atr": 0,
            "macd": 0,
            "reasons": [],
            "candles": candles
        }

    closes = [
        safe_float(x["c"])
        for x in candles
    ]

    highs = [
        safe_float(x["h"])
        for x in candles
    ]

    lows = [
        safe_float(x["l"])
        for x in candles
    ]

    e20 = ema(
        closes,
        20
    )

    e50 = ema(
        closes,
        50
    )

    e200 = ema(
        closes,
        200
    )

    rs = rsi(
        closes,
        14
    )

    at = atr(
        highs,
        lows,
        closes,
        14
    )

    (
        macd_line,
        macd_signal,
        macd_hist
    ) = macd(closes)

    price = closes[-1]

    score = 50

    reasons = []

    v20 = (
        e20[-1]
        or price
    )

    v50 = (
        e50[-1]
        or price
    )

    v200 = (
        e200[-1]
        or price
    )

    vrsi = (
        rs[-1]
        if rs[-1] is not None
        else 50
    )

    vatr = (
        at[-1]
        if at[-1] is not None
        else price * 0.01
    )

    vmh = (
        macd_hist[-1]
        if macd_hist[-1] is not None
        else 0
    )

    # EMA20
    if price > v20:

        score += 8

        reasons.append(
            "السعر فوق EMA20"
        )

    else:

        score -= 8

        reasons.append(
            "السعر تحت EMA20"
        )

    # EMA50
    if price > v50:

        score += 8

        reasons.append(
            "السعر فوق EMA50"
        )

    else:

        score -= 8

        reasons.append(
            "السعر تحت EMA50"
        )

    # EMA200
    if price > v200:

        score += 10

        reasons.append(
            "السعر فوق EMA200"
        )

    else:

        score -= 10

        reasons.append(
            "السعر تحت EMA200"
        )

    # RSI
    if 50 <= vrsi <= 68:

        score += 8

        reasons.append(
            "RSI إيجابي"
        )

    elif 32 <= vrsi < 50:

        score -= 5

        reasons.append(
            "RSI ضعيف"
        )

    elif vrsi > 72:

        score -= 4

        reasons.append(
            "RSI مرتفع"
        )

    elif vrsi < 28:

        score += 3

        reasons.append(
            "RSI منخفض"
        )

    # MACD
    if vmh > 0:

        score += 8

        reasons.append(
            "MACD إيجابي"
        )

    elif vmh < 0:

        score -= 8

        reasons.append(
            "MACD سلبي"
        )

    # Latest candle
    if len(closes) >= 2:

        previous = closes[-2]

        if previous != 0:

            change = (
                (
                    closes[-1]
                    - previous
                )
                / previous
            ) * 100

            if change > 0:

                score += 5

                reasons.append(
                    "آخر شمعة إيجابية"
                )

            elif change < 0:

                score -= 5

                reasons.append(
                    "آخر شمعة سلبية"
                )

    score = max(
        0,
        min(
            100,
            score
        )
    )

    if score >= 78:

        signal = "شراء قوي"
        direction = "buy"

    elif score >= 62:

        signal = "شراء"
        direction = "buy"

    elif score <= 22:

        signal = "بيع قوي"
        direction = "sell"

    elif score <= 38:

        signal = "بيع"
        direction = "sell"

    else:

        signal = "حيادي"
        direction = "neutral"

    risk = max(
        vatr * 1.2,
        price * 0.01
    )

    if direction == "sell":

        entry = price

        sl = (
            price
            + risk
        )

        tp1 = (
            price
            - risk
        )

        tp2 = (
            price
            - risk * 2
        )

        tp3 = (
            price
            - risk * 3
        )

    else:

        entry = price

        sl = (
            price
            - risk
        )

        tp1 = (
            price
            + risk
        )

        tp2 = (
            price
            + risk * 2
        )

        tp3 = (
            price
            + risk * 3
        )

    return {
        "signal": signal,
        "direction": direction,

        "score": int(score),

        "score10": round(
            score / 10,
            1
        ),

        "price": round_price(
            price
        ),

        "entry": round_price(
            entry
        ),

        "tp1": round_price(
            tp1
        ),

        "tp2": round_price(
            tp2
        ),

        "tp3": round_price(
            tp3
        ),

        "sl": round_price(
            sl
        ),

        "rsi": round(
            vrsi,
            2
        ),

        "ema20": round_price(
            v20
        ),

        "ema50": round_price(
            v50
        ),

        "ema200": round_price(
            v200
        ),

        "atr": round_price(
            vatr
        ),

        "macd": round(
            vmh,
            8
        ),

        "reasons": reasons,

        "candles": candles
    }


# =========================================================
# OKX COMMON
# =========================================================

def okx_get(
    path,
    params=None
):

    try:

        response = HTTP.get(
            OKX_BASE + path,
            params=params or {},
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        if data.get(
            "code"
        ) not in (
            None,
            "0",
            0
        ):

            return None

        return data

    except Exception:

        return None


def normalize_okx_symbol(
    symbol
):

    symbol = str(
        symbol or ""
    ).upper()

    symbol = symbol.replace(
        "-",
        ""
    )

    if symbol.endswith(
        "USDT"
    ):

        base = symbol[:-4]

        return (
            f"{base}-USDT"
        )

    return symbol


# =========================================================
# OKX SPOT
# =========================================================

def okx_markets():

    cached = cache_get(
        "okx_markets"
    )

    if cached is not None:
        return cached

    data = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": "SPOT"
        }
    )

    if not data:
        return []

    markets = []

    for item in data.get(
        "data",
        []
    ):

        inst_id = item.get(
            "instId",
            ""
        )

        if not inst_id.endswith(
            "-USDT"
        ):

            continue

        last = safe_float(
            item.get("last")
        )

        volume = safe_float(
            item.get("volCcy24h")
        )

        if last <= 0:
            continue

        open24 = safe_float(
            item.get("open24h")
        )

        change = 0

        if open24 > 0:

            change = (
                (
                    last
                    - open24
                )
                / open24
            ) * 100

        markets.append({
            "symbol":
                inst_id.replace(
                    "-",
                    ""
                ),

            "okx_symbol":
                inst_id,

            "name":
                inst_id.replace(
                    "-USDT",
                    ""
                ),

            "price":
                round_price(last),

            "volume24h":
                volume,

            "change24h":
                round(
                    change,
                    2
                )
        })

    markets.sort(
        key=lambda x:
            x["volume24h"],
        reverse=True
    )

    cache_set(
        "okx_markets",
        markets,
        60
    )

    return markets


def okx_klines(
    symbol,
    interval="15m",
    limit=300
):

    inst_id = (
        normalize_okx_symbol(
            symbol
        )
    )

    interval_map = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
        "1D": "1D"
    }

    bar = interval_map.get(
        interval,
        "15m"
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 300

    limit = max(
        20,
        min(
            limit,
            300
        )
    )

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": limit
        }
    )

    if not data:
        return []

    result = []

    rows = list(
        reversed(
            data.get(
                "data",
                []
            )
        )
    )

    for row in rows:

        if len(row) < 6:
            continue

        result.append({
            "t": int(
                safe_float(
                    row[0]
                )
            ),

            "o": safe_float(
                row[1]
            ),

            "h": safe_float(
                row[2]
            ),

            "l": safe_float(
                row[3]
            ),

            "c": safe_float(
                row[4]
            ),

            "v": safe_float(
                row[5]
            )
        })

    return result


def crypto_analysis(
    symbol,
    interval="15m"
):

    candles = okx_klines(
        symbol,
        interval,
        300
    )

    result = analyze_candles(
        candles
    )

    result["symbol"] = (
        symbol.upper()
    )

    result["interval"] = interval

    result["source"] = "OKX"

    return result


def crypto_scan(
    interval="15m",
    limit=80
):

    key = (
        f"crypto_scan:"
        f"{interval}:"
        f"{limit}"
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    markets = okx_markets()

    results = []

    for market in markets[
        :int(limit)
    ]:

        symbol = market[
            "symbol"
        ]

        try:

            analysis = (
                crypto_analysis(
                    symbol,
                    interval
                )
            )

            if analysis.get(
                "price",
                0
            ) <= 0:

                continue

            analysis["name"] = (
                market["name"]
            )

            analysis[
                "volume24h"
            ] = market[
                "volume24h"
            ]

            analysis[
                "change24h"
            ] = market[
                "change24h"
            ]

            results.append(
                analysis
            )

        except Exception:
            continue

    results.sort(
        key=lambda x:
            x.get(
                "score",
                0
            ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "OKX",
        "market": "crypto",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        key,
        payload,
        60
    )

    return payload


# =========================================================
# OKX SPOT ROUTES
# =========================================================

@app.get(
    "/api/okx/test"
)
def okx_test():

    markets = okx_markets()

    return jsonify({
        "ok": True,
        "source": "OKX",
        "connected": bool(
            markets
        ),
        "markets": len(
            markets
        )
    })


@app.get(
    "/api/okx/markets"
)
def okx_markets_route():

    markets = okx_markets()

    return jsonify({
        "ok": True,
        "source": "OKX",
        "results": markets,
        "markets": markets,
        "count": len(markets)
    })


@app.get(
    "/api/okx/klines"
)
def okx_klines_route():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    candles = okx_klines(
        symbol,
        interval,
        300
    )

    return jsonify({
        "ok": True,
        "source": "OKX",
        "symbol": symbol.upper(),
        "interval": interval,
        "candles": candles,
        "data": candles
    })


@app.get(
    "/api/okx/analysis"
)
def okx_analysis_route():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify({
        "ok": True,
        "source": "OKX",
        **crypto_analysis(
            symbol,
            interval
        )
    })


@app.get(
    "/api/okx/prices"
)
def okx_prices():

    markets = okx_markets()

    prices = []

    for item in markets:

        prices.append({
            "symbol":
                item["symbol"],

            "price":
                item["price"],

            "volume24h":
                item["volume24h"],

            "change24h":
                item.get(
                    "change24h",
                    0
                )
        })

    return jsonify({
        "ok": True,
        "source": "OKX",
        "prices": prices,
        "results": prices
    })


@app.get(
    "/api/okx/price"
)
def okx_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    target = (
        symbol.upper()
        .replace("-", "")
    )

    markets = okx_markets()

    for item in markets:

        if item["symbol"] == target:

            return jsonify({
                "ok": True,
                "source": "OKX",
                "symbol": target,
                "price": item[
                    "price"
                ]
            })

    analysis = crypto_analysis(
        target,
        "15m"
    )

    return jsonify({
        "ok": True,
        "source": "OKX",
        "symbol": target,
        "price":
            analysis.get(
                "price",
                0
            )
    })


@app.get(
    "/api/okx/scan"
)
def okx_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    limit = request.args.get(
        "limit",
        "80"
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 80

    return jsonify(
        crypto_scan(
            interval,
            limit
        )
    )


# =========================================================
# REAL OKX FUTURES / SWAP
# =========================================================

def okx_futures_markets():

    cached = cache_get(
        "okx_futures_markets"
    )

    if cached is not None:
        return cached

    data = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": "SWAP"
        }
    )

    if not data:
        return []

    markets = []

    for item in data.get(
        "data",
        []
    ):

        inst_id = item.get(
            "instId",
            ""
        )

        if not inst_id.endswith(
            "-USDT-SWAP"
        ):

            continue

        last = safe_float(
            item.get("last")
        )

        if last <= 0:
            continue

        open24 = safe_float(
            item.get("open24h")
        )

        change = 0

        if open24 > 0:

            change = (
                (
                    last
                    - open24
                )
                / open24
            ) * 100

        volume = safe_float(
            item.get(
                "volCcy24h"
            )
        )

        markets.append({
            "symbol":
                inst_id,

            "okx_symbol":
                inst_id,

            "name":
                inst_id.replace(
                    "-SWAP",
                    ""
                ),

            "price":
                round_price(last),

            "volume24h":
                volume,

            "change24h":
                round(
                    change,
                    2
                )
        })

    markets.sort(
        key=lambda x:
            x["volume24h"],
        reverse=True
    )

    cache_set(
        "okx_futures_markets",
        markets,
        60
    )

    return markets


def normalize_okx_future(
    symbol
):

    symbol = str(
        symbol or ""
    ).upper()

    symbol = symbol.replace(
        "-",
        ""
    )

    if symbol.endswith(
        "USDT"
    ):

        base = symbol[:-4]

        return (
            f"{base}-USDT-SWAP"
        )

    if symbol.endswith(
        "USDT-SWAP".replace(
            "-",
            ""
        )
    ):

        return symbol

    return symbol


def okx_futures_klines(
    symbol,
    interval="15m",
    limit=300
):

    inst_id = (
        normalize_okx_future(
            symbol
        )
    )

    interval_map = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D"
    }

    bar = interval_map.get(
        interval,
        "15m"
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 300

    limit = max(
        20,
        min(
            limit,
            300
        )
    )

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": limit
        }
    )

    if not data:
        return []

    candles = []

    rows = list(
        reversed(
            data.get(
                "data",
                []
            )
        )
    )

    for row in rows:

        if len(row) < 6:
            continue

        candles.append({
            "t": int(
                safe_float(
                    row[0]
                )
            ),

            "o": safe_float(
                row[1]
            ),

            "h": safe_float(
                row[2]
            ),

            "l": safe_float(
                row[3]
            ),

            "c": safe_float(
                row[4]
            ),

            "v": safe_float(
                row[5]
            )
        })

    return candles


def futures_analysis(
    symbol,
    interval="15m"
):

    candles = okx_futures_klines(
        symbol,
        interval,
        300
    )

    result = analyze_candles(
        candles
    )

    result["symbol"] = (
        symbol.upper()
    )

    result["interval"] = interval

    result["source"] = (
        "OKX Futures"
    )

    return result


def futures_scan_data(
    interval="15m",
    limit=40
):

    key = (
        f"okx_futures:"
        f"{interval}:"
        f"{limit}"
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    markets = (
        okx_futures_markets()
    )

    results = []

    for market in markets[
        :int(limit)
    ]:

        try:

            result = (
                futures_analysis(
                    market[
                        "symbol"
                    ],
                    interval
                )
            )

            if result.get(
                "price",
                0
            ) <= 0:

                continue

            result["name"] = (
                market["name"]
            )

            result[
                "volume24h"
            ] = market[
                "volume24h"
            ]

            result[
                "change24h"
            ] = market[
                "change24h"
            ]

            results.append(
                result
            )

        except Exception:
            continue

    results.sort(
        key=lambda x:
            x.get(
                "score",
                0
            ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "OKX Futures",
        "market": "futures",
        "type": "SWAP",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        key,
        payload,
        60
    )

    return payload


@app.get(
    "/api/futures/markets"
)
def futures_markets():

    markets = (
        okx_futures_markets()
    )

    return jsonify({
        "ok": True,
        "source": "OKX Futures",
        "type": "SWAP",
        "markets": markets,
        "results": markets,
        "count": len(markets)
    })


@app.get(
    "/api/futures/scan"
)
def futures_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    limit = request.args.get(
        "limit",
        "40"
    )

    try:
        limit = int(limit)
    except Exception:
        limit = 40

    return jsonify(
        futures_scan_data(
            interval,
            limit
        )
    )


# =========================================================
# COMPATIBILITY
# =========================================================

@app.get(
    "/api/binance/test"
)
@app.get(
    "/api/bybit/test"
)
def exchange_test():

    markets = okx_markets()

    return jsonify({
        "ok": True,
        "source": "OKX",
        "connected": bool(
            markets
        ),
        "markets": len(
            markets
        ),
        "note":
            "المصدر الحالي OKX"
    })


@app.get(
    "/api/binance/markets"
)
@app.get(
    "/api/bybit/markets"
)
def exchange_markets():

    markets = okx_markets()

    return jsonify({
        "ok": True,
        "source": "OKX",
        "results": markets,
        "markets": markets
    })


@app.get(
    "/api/binance/klines"
)
@app.get(
    "/api/bybit/klines"
)
def exchange_klines():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    candles = okx_klines(
        symbol,
        interval
    )

    return jsonify({
        "ok": True,
        "source": "OKX",
        "candles": candles,
        "data": candles
    })


@app.get(
    "/api/binance/analysis"
)
@app.get(
    "/api/bybit/analysis"
)
def exchange_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify({
        "ok": True,
        "source": "OKX",
        **crypto_analysis(
            symbol,
            interval
        )
    })


@app.get(
    "/api/binance/scan"
)
@app.get(
    "/api/bybit/scan"
)
def exchange_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify(
        crypto_scan(
            interval,
            80
        )
    )


@app.get(
    "/api/binance/prices"
)
@app.get(
    "/api/bybit/prices"
)
def exchange_prices():

    return okx_prices()


@app.get(
    "/api/binance/price"
)
@app.get(
    "/api/bybit/price"
)
def exchange_price():

    return okx_price()


# =========================================================
# YAHOO FINANCE
# =========================================================

YAHOO_RANGES = {

    "5m": "5d",

    "15m": "1mo",

    "30m": "1mo",

    "1h": "3mo",

    "4h": "1y",

    "1d": "2y"
}


def yahoo_candles(
    symbol,
    interval="1d"
):

    interval = interval.lower()

    if interval == "4h":

        raw = yahoo_candles(
            symbol,
            "1h"
        )

        if not raw:
            return []

        grouped = []

        for candle in raw:

            if not grouped:

                grouped.append({
                    "t": candle["t"],
                    "o": candle["o"],
                    "h": candle["h"],
                    "l": candle["l"],
                    "c": candle["c"],
                    "v": candle["v"]
                })

                continue

            last = grouped[-1]

            if (
                candle["t"]
                - last["t"]
            ) < (
                4
                * 60
                * 60
                * 1000
            ):

                last["h"] = max(
                    last["h"],
                    candle["h"]
                )

                last["l"] = min(
                    last["l"],
                    candle["l"]
                )

                last["c"] = (
                    candle["c"]
                )

                last["v"] += (
                    candle["v"]
                )

            else:

                grouped.append({
                    "t":
                        candle["t"],

                    "o":
                        candle["o"],

                    "h":
                        candle["h"],

                    "l":
                        candle["l"],

                    "c":
                        candle["c"],

                    "v":
                        candle["v"]
                })

        return grouped

    interval_map = {

        "5m": "5m",

        "15m": "15m",

        "30m": "30m",

        "1h": "1h",

        "1d": "1d"
    }

    yahoo_interval = (
        interval_map.get(
            interval,
            "1d"
        )
    )

    range_value = (
        YAHOO_RANGES.get(
            interval,
            "2y"
        )
    )

    key = (
        f"yahoo:"
        f"{symbol}:"
        f"{interval}"
    )

    cached = cache_get(key)

    if cached is not None:
        return cached

    try:

        response = HTTP.get(
            f"{YAHOO_CHART}/{symbol}",
            params={
                "interval":
                    yahoo_interval,

                "range":
                    range_value,

                "includePrePost":
                    "false",

                "events":
                    "div,splits"
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        result = (
            data
            .get("chart", {})
            .get("result")
        )

        if not result:
            return []

        result = result[0]

        timestamps = (
            result.get(
                "timestamp",
                []
            )
        )

        quote = (
            result
            .get(
                "indicators",
                {}
            )
            .get(
                "quote",
                [{}]
            )[0]
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

        for i, ts in enumerate(
            timestamps
        ):

            try:

                o = opens[i]
                h = highs[i]
                l = lows[i]
                c = closes[i]

                if (
                    o is None
                    or h is None
                    or l is None
                    or c is None
                ):

                    continue

                v = (
                    volumes[i]
                    if (
                        i
                        < len(volumes)
                        and volumes[i]
                        is not None
                    )
                    else 0
                )

                candles.append({
                    "t":
                        int(ts)
                        * 1000,

                    "o":
                        safe_float(o),

                    "h":
                        safe_float(h),

                    "l":
                        safe_float(l),

                    "c":
                        safe_float(c),

                    "v":
                        safe_float(v)
                })

            except Exception:

                continue

        cache_set(
            key,
            candles,
            120
        )

        return candles

    except Exception:

        return []


# =========================================================
# SAUDI MARKET - SAHMK
# =========================================================

SAUDI_STOCKS = {

    "2222":
        "أرامكو السعودية",

    "1120":
        "مصرف الراجحي",

    "2010":
        "سابك",

    "1180":
        "الأهلي السعودي",

    "7010":
        "stc",

    "1211":
        "معادن",

    "1150":
        "مصرف الإنماء",

    "1060":
        "بنك ساب",

    "2020":
        "سابك للمغذيات الزراعية",

    "7020":
        "زين السعودية",

    "7030":
        "موبايلي",

    "4001":
        "أسواق العثيم",

    "4190":
        "جرير",

    "4280":
        "المملكة",

    "6010":
        "نادك",

    "4003":
        "إكسترا",

    "4002":
        "المواساة",

    "4004":
        "دله الصحية",

    "4050":
        "ساسكو",

    "4200":
        "الدريس",

    "4261":
        "ذيب",

    "4262":
        "بدجت السعودية",

    "5110":
        "كهرباء السعودية",

    "2060":
        "التصنيع",

    "2190":
        "سيسكو القابضة",

    "2290":
        "ينساب",

    "2330":
        "المتقدمة",

    "2380":
        "رابغ للتكرير والبتروكيماويات",

    "2350":
        "كيان السعودية",

    "2100":
        "وفرة",

    "3003":
        "أسمنت المدينة",

    "3010":
        "أسمنت العربية",

    "3030":
        "أسمنت السعودية",

    "3040":
        "أسمنت القصيم",

    "3050":
        "أسمنت الجنوب",

    "3060":
        "أسمنت ينبع",

    "3090":
        "أسمنت تبوك",

    "8010":
        "التعاونية",

    "8040":
        "ولاء",

    "8050":
        "سلامة",

    "8100":
        "سايكو",

    "8120":
        "اتحاد الخليج الأهلية"
}


def sahmk_headers():

    headers = {
        "Accept":
            "application/json",

        "User-Agent":
            "Mozilla/5.0 "
            "Mudarib-Abo-Saud/2.0"
    }

    if SAHMK_API_KEY:

        headers[
            "Authorization"
        ] = (
            "Bearer "
            + SAHMK_API_KEY
        )

        headers[
            "X-API-Key"
        ] = SAHMK_API_KEY

    return headers


def sahmk_get(
    path,
    params=None
):

    try:

        response = HTTP.get(
            SAHMK_BASE + path,
            params=params or {},
            headers=sahmk_headers(),
            timeout=15
        )

        response.raise_for_status()

        return response.json()

    except Exception:

        return None


def sahmk_quote(
    symbol
):

    symbol = str(
        symbol
    ).upper().replace(
        ".SR",
        ""
    )

    # محاولة أكثر من مسار
    paths = [

        f"/api/v1/quote/{symbol}/",

        f"/api/v1/quote/{symbol}",

        f"/api/v1/stocks/{symbol}",

        f"/api/v1/stock/{symbol}"
    ]

    for path in paths:

        data = sahmk_get(
            path
        )

        if not data:
            continue

        if isinstance(
            data,
            dict
        ):

            if "data" in data:

                inner = data[
                    "data"
                ]

                if isinstance(
                    inner,
                    dict
                ):

                    return inner

            return data

    return None


def sahmk_value(
    data,
    names,
    default=0
):

    if not isinstance(
        data,
        dict
    ):

        return default

    for name in names:

        if name in data:

            value = data[
                name
            ]

            if value is not None:

                return value

    return default


def saudi_quote(
    symbol
):

    clean = str(
        symbol
    ).upper().replace(
        ".SR",
        ""
    )

    # المصدر الأساسي
    data = sahmk_quote(
        clean
    )

    if data:

        price = safe_float(
            sahmk_value(
                data,
                [
                    "price",
                    "last",
                    "lastPrice",
                    "close",
                    "currentPrice"
                ]
            )
        )

        if price > 0:

            previous = safe_float(
                sahmk_value(
                    data,
                    [
                        "previousClose",
                        "prevClose",
                        "previous",
                        "prev"
                    ]
                )
            )

            change = safe_float(
                sahmk_value(
                    data,
                    [
                        "change",
                        "priceChange"
                    ]
                )
            )

            change_percent = (
                safe_float(
                    sahmk_value(
                        data,
                        [
                            "changePercent",
                            "percentChange",
                            "changePct"
                        ]
                    )
                )
            )

            if (
                change_percent == 0
                and previous > 0
            ):

                change_percent = (
                    (
                        price
                        - previous
                    )
                    / previous
                ) * 100

            return {
                "price":
                    round_price(
                        price
                    ),

                "change":
                    round(
                        change,
                        4
                    ),

                "changePercent":
                    round(
                        change_percent,
                        2
                    ),

                "volume":
                    safe_float(
                        sahmk_value(
                            data,
                            [
                                "volume",
                                "vol",
                                "volume24h"
                            ]
                        )
                    ),

                "source":
                    "SAHMK"
            }

    # احتياطي Yahoo
    yahoo_symbol = (
        f"{clean}.SR"
    )

    candles = yahoo_candles(
        yahoo_symbol,
        "1d"
    )

    if candles:

        last = candles[-1]

        price = safe_float(
            last["c"]
        )

        previous = (
            safe_float(
                candles[-2]["c"]
            )
            if len(candles) >= 2
            else 0
        )

        change_percent = 0

        if previous > 0:

            change_percent = (
                (
                    price
                    - previous
                )
                / previous
            ) * 100

        return {
            "price":
                round_price(
                    price
                ),

            "change":
                round(
                    price - previous,
                    4
                )
                if previous
                else 0,

            "changePercent":
                round(
                    change_percent,
                    2
                ),

            "volume":
                safe_float(
                    last.get(
                        "v"
                    )
                ),

            "source":
                "Yahoo Finance"
        }

    return None


def saudi_candles(
    symbol,
    interval="1d"
):

    clean = str(
        symbol
    ).upper().replace(
        ".SR",
        ""
    )

    # SAHMK قد يوفر تاريخ، لكن مساره يختلف
    # لذلك نستخدم Yahoo للشموع التاريخية
    # مع إبقاء السعر الحالي من SAHMK.

    return yahoo_candles(
        f"{clean}.SR",
        interval
    )


def saudi_analysis(
    symbol,
    name,
    interval
):

    candles = saudi_candles(
        symbol,
        interval
    )

    result = analyze_candles(
        candles
    )

    quote = saudi_quote(
        symbol
    )

    if quote:

        if quote.get(
            "price",
            0
        ) > 0:

            result[
                "price"
            ] = quote[
                "price"
            ]

            result[
                "entry"
            ] = quote[
                "price"
            ]

    result[
        "symbol"
    ] = symbol

    result[
        "name"
    ] = name

    result[
        "interval"
    ] = interval

    result[
        "source"
    ] = (
        quote.get(
            "source"
        )
        if quote
        else "SAHMK"
    )

    return result


def saudi_scan(
    interval="1d"
):

    key = (
        f"saudi:"
        f"{interval}"
    )

    cached = cache_get(
        key
    )

    if cached is not None:
        return cached

    results = []

    for symbol, name in (
        SAUDI_STOCKS.items()
    ):

        try:

            result = (
                saudi_analysis(
                    symbol,
                    name,
                    interval
                )
            )

            if result.get(
                "price",
                0
            ) <= 0:

                continue

            results.append(
                result
            )

        except Exception:

            continue

    results.sort(
        key=lambda x:
            x.get(
                "score",
                0
            ),
        reverse=True
    )

    payload = {
        "ok": True,

        "source":
            "SAHMK + Yahoo",

        "market":
            "saudi",

        "interval":
            interval,

        "results":
            results,

        "count":
            len(results),

        "updated":
            now_iso()
    }

    cache_set(
        key,
        payload,
        120
    )

    return payload


@app.get(
    "/api/saudi/markets"
)
def saudi_markets():

    return jsonify({
        "ok": True,

        "source":
            "SAHMK",

        "markets": [
            {
                "symbol":
                    f"{symbol}.SR",

                "code":
                    symbol,

                "name":
                    name
            }

            for symbol, name
            in SAUDI_STOCKS.items()
        ]
    })


@app.get(
    "/api/saudi/analysis"
)
def saudi_analysis_route():

    symbol = request.args.get(
        "symbol",
        "2222.SR"
    )

    clean = (
        symbol.upper()
        .replace(
            ".SR",
            ""
        )
    )

    name = (
        SAUDI_STOCKS.get(
            clean,
            symbol.upper()
        )
    )

    interval = request.args.get(
        "interval",
        "1d"
    )

    return jsonify({
        "ok": True,

        **saudi_analysis(
            clean,
            name,
            interval
        )
    })


@app.get(
    "/api/saudi/scan"
)
def saudi_scan_route():

    interval = request.args.get(
        "interval",
        "1d"
    )

    return jsonify(
        saudi_scan(
            interval
        )
    )


# =========================================================
# US MARKET
# =========================================================

US_STOCKS = {

    "AAPL":
        "Apple",

    "MSFT":
        "Microsoft",

    "NVDA":
        "NVIDIA",

    "AMZN":
        "Amazon",

    "META":
        "Meta",

    "GOOGL":
        "Alphabet",

    "GOOG":
        "Alphabet C",

    "TSLA":
        "Tesla",

    "AVGO":
        "Broadcom",

    "AMD":
        "AMD",

    "NFLX":
        "Netflix",

    "JPM":
        "JPMorgan",

    "V":
        "Visa",

    "MA":
        "Mastercard",

    "WMT":
        "Walmart",

    "COST":
        "Costco",

    "KO":
        "Coca-Cola",

    "PEP":
        "PepsiCo",

    "XOM":
        "Exxon Mobil",

    "CVX":
        "Chevron",

    "BAC":
        "Bank of America",

    "INTC":
        "Intel",

    "QCOM":
        "Qualcomm",

    "ORCL":
        "Oracle",

    "CRM":
        "Salesforce",

    "ADBE":
        "Adobe",

    "UBER":
        "Uber",

    "PYPL":
        "PayPal",

    "PLTR":
        "Palantir",

    "COIN":
        "Coinbase"
}


def yahoo_analysis(
    symbol,
    name,
    interval
):

    candles = yahoo_candles(
        symbol,
        interval
    )

    result = analyze_candles(
        candles
    )

    result["symbol"] = symbol

    result["name"] = name

    result["interval"] = interval

    result["source"] = (
        "Yahoo Finance"
    )

    return result


def us_scan(
    interval="1d"
):

    key = (
        f"us:"
        f"{interval}"
    )

    cached = cache_get(
        key
    )

    if cached is not None:
        return cached

    results = []

    for symbol, name in (
        US_STOCKS.items()
    ):

        try:

            result = (
                yahoo_analysis(
                    symbol,
                    name,
                    interval
                )
            )

            if result.get(
                "price",
                0
            ) <= 0:

                continue

            results.append(
                result
            )

        except Exception:

            continue

    results.sort(
        key=lambda x:
            x.get(
                "score",
                0
            ),
        reverse=True
    )

    payload = {

        "ok": True,

        "source":
            "Yahoo Finance",

        "market":
            "usmarket",

        "interval":
            interval,

        "results":
            results,

        "count":
            len(results),

        "updated":
            now_iso()
    }

    cache_set(
        key,
        payload,
        120
    )

    return payload


@app.get(
    "/api/usmarket/markets"
)
def us_markets():

    return jsonify({

        "ok": True,

        "source":
            "Yahoo Finance",

        "markets": [

            {
                "symbol":
                    symbol,

                "name":
                    name
            }

            for symbol, name
            in US_STOCKS.items()
        ]
    })


@app.get(
    "/api/usmarket/analysis"
)
def us_analysis_route():

    symbol = request.args.get(
        "symbol",
        "AAPL"
    )

    interval = request.args.get(
        "interval",
        "1d"
    )

    name = (
        US_STOCKS.get(
            symbol.upper(),
            symbol.upper()
        )
    )

    return jsonify({

        "ok": True,

        **yahoo_analysis(
            symbol.upper(),
            name,
            interval
        )
    })


@app.get(
    "/api/usmarket/signals"
)
def us_signals():

    interval = request.args.get(
        "interval",
        "1d"
    )

    return jsonify(
        us_scan(
            interval
        )
    )


# =========================================================
# FOREX
# =========================================================

FOREX_PAIRS = {

    "EURUSD=X":
        "EUR/USD",

    "GBPUSD=X":
        "GBP/USD",

    "USDJPY=X":
        "USD/JPY",

    "USDCHF=X":
        "USD/CHF",

    "USDCAD=X":
        "USD/CAD",

    "AUDUSD=X":
        "AUD/USD",

    "NZDUSD=X":
        "NZD/USD",

    "EURGBP=X":
        "EUR/GBP",

    "EURJPY=X":
        "EUR/JPY",

    "GBPJPY=X":
        "GBP/JPY",

    "AUDJPY=X":
        "AUD/JPY",

    "CADJPY=X":
        "CAD/JPY",

    "CHFJPY=X":
        "CHF/JPY",

    "EURAUD=X":
        "EUR/AUD",

    "EURCHF=X":
        "EUR/CHF",

    "GBPAUD=X":
        "GBP/AUD",

    "GBPCAD=X":
        "GBP/CAD",

    "AUDCAD=X":
        "AUD/CAD",

    "AUDCHF=X":
        "AUD/CHF",

    "NZDJPY=X":
        "NZD/JPY"
}


def forex_scan(
    interval="1h"
):

    key = (
        f"forex:"
        f"{interval}"
    )

    cached = cache_get(
        key
    )

    if cached is not None:
        return cached

    results = []

    for symbol, name in (
        FOREX_PAIRS.items()
    ):

        try:

            result = (
                yahoo_analysis(
                    symbol,
                    name,
                    interval
                )
            )

            if result.get(
                "price",
                0
            ) <= 0:

                continue

            results.append(
                result
            )

        except Exception:

            continue

    results.sort(
        key=lambda x:
            x.get(
                "score",
                0
            ),
        reverse=True
    )

    payload = {

        "ok": True,

        "source":
            "Yahoo Finance",

        "market":
            "forex",

        "interval":
            interval,

        "results":
            results,

        "count":
            len(results),

        "updated":
            now_iso()
    }

    cache_set(
        key,
        payload,
        120
    )

    return payload


@app.get(
    "/api/forex/markets"
)
def forex_markets():

    return jsonify({

        "ok": True,

        "source":
            "Yahoo Finance",

        "markets": [

            {
                "symbol":
                    symbol,

                "name":
                    name
            }

            for symbol, name
            in FOREX_PAIRS.items()
        ]
    })


@app.get(
    "/api/forex/analysis"
)
def forex_analysis_route():

    symbol = request.args.get(
        "symbol",
        "EURUSD=X"
    )

    interval = request.args.get(
        "interval",
        "1h"
    )

    name = (
        FOREX_PAIRS.get(
            symbol.upper(),
            symbol.upper()
        )
    )

    return jsonify({

        "ok": True,

        **yahoo_analysis(
            symbol.upper(),
            name,
            interval
        )
    })


@app.get(
    "/api/forex/signals"
)
def forex_signals():

    interval = request.args.get(
        "interval",
        "1h"
    )

    return jsonify(
        forex_scan(
            interval
        )
    )


# =========================================================
# ARABIC NEWS
# =========================================================

ARABIC_RSS = [

    (
        "عكاظ",
        "https://www.okaz.com.sa/rss"
    ),

    (
        "العربية",
        "https://www.alarabiya.net/.mrss/ar.xml"
    ),

    (
        "اقتصاد الشرق مع بلومبرغ",
        "https://asharq.com/feed/"
    ),

    (
        "الاقتصادية",
        "https://www.aleqt.com/rss"
    )
]


def fetch_rss(
    source_name,
    url
):

    try:

        response = HTTP.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        items = []

        nodes = root.findall(
            ".//item"
        )

        for item in nodes[:20]:

            title = (
                item.findtext(
                    "title"
                )
                or ""
            ).strip()

            link = (
                item.findtext(
                    "link"
                )
                or ""
            ).strip()

            pub = (
                item.findtext(
                    "pubDate"
                )
                or item.findtext(
                    "published"
                )
                or item.findtext(
                    "updated"
                )
                or ""
            ).strip()

            description = (
                item.findtext(
                    "description"
                )
                or ""
            ).strip()

            title = clean_html(
                title
            )

            description = clean_html(
                description
            )

            if not title:
                continue

            items.append({

                "title":
                    title,

                "description":
                    description,

                "link":
                    link,

                "published":
                    pub,

                "source":
                    source_name
            })

        return items

    except Exception:

        return []


def get_news():

    cached = cache_get(
        "arabic_news"
    )

    if cached is not None:
        return cached

    all_items = []

    for source_name, url in (
        ARABIC_RSS
    ):

        items = fetch_rss(
            source_name,
            url
        )

        all_items.extend(
            items
        )

        if len(all_items) >= 30:
            break

    # إزالة التكرار
    unique = []

    seen = set()

    for item in all_items:

        key = (
            item.get(
                "title",
                ""
            )
            .strip()
            .lower()
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)

        unique.append(
            item
        )

    unique = unique[:30]

    payload = {

        "ok": True,

        "source":
            "أخبار عربية",

        "results":
            unique,

        "count":
            len(unique),

        "updated":
            now_iso()
    }

    cache_set(
        "arabic_news",
        payload,
        300
    )

    return payload


@app.get(
    "/api/news"
)
def news():

    return jsonify(
        get_news()
    )


# =========================================================
# MARKET OVERVIEW
# =========================================================

@app.get(
    "/api/markets/overview"
)
def markets_overview():

    return jsonify({

        "ok": True,

        "updated":
            now_iso(),

        "markets": {

            "crypto": {

                "name":
                    "العملات الرقمية",

                "source":
                    "OKX Spot",

                "endpoint":
                    "/api/okx/scan"
            },

            "saudi": {

                "name":
                    "السوق السعودي",

                "source":
                    "SAHMK",

                "fallback":
                    "Yahoo Finance",

                "endpoint":
                    "/api/saudi/scan"
            },

            "usmarket": {

                "name":
                    "السوق الأمريكي",

                "source":
                    "Yahoo Finance",

                "endpoint":
                    "/api/usmarket/signals"
            },

            "forex": {

                "name":
                    "الفوركس",

                "source":
                    "Yahoo Finance",

                "endpoint":
                    "/api/forex/signals"
            },

            "futures": {

                "name":
                    "Futures",

                "source":
                    "OKX Futures",

                "type":
                    "SWAP",

                "endpoint":
                    "/api/futures/scan"
            }
        }
    })


# =========================================================
# HEALTH
# =========================================================

@app.get(
    "/health"
)
def health():

    return jsonify({

        "ok": True,

        "status":
            "healthy",

        "service":
            "mudarib-abo-saud",

        "sources": {

            "crypto":
                "OKX Spot",

            "futures":
                "OKX Futures SWAP",

            "saudi":
                "SAHMK + Yahoo fallback",

            "us":
                "Yahoo Finance",

            "forex":
                "Yahoo Finance",

            "news":
                "Arabic RSS"
        },

        "database":
            False,

        "time":
            now_iso()
    })


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({

            "ok": False,

            "error":
                "API غير موجودة",

            "path":
                request.path

        }), 404

    try:

        return render_template(
            "index.html"
        )

    except Exception:

        return (
            "مضارب أبو سعود",
            404
        )


@app.errorhandler(500)
def server_error(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({

            "ok": False,

            "error":
                "خطأ داخلي في الخادم"

        }), 500

    return (
        "حدث خطأ في الخادم",
        500
    )


# =========================================================
# RUN
# =========================================================

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
