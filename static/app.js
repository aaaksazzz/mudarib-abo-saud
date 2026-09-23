import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, render_template, request


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

OKX_BASE = "https://openapi.okx.com"
YAHOO_BASE = "https://query1.finance.yahoo.com"

REQUEST_TIMEOUT = 12

# مدة التخزين المؤقت بالثواني
CACHE_SECONDS = 20

# عدد الطلبات المتوازية
MAX_WORKERS = 8

# عدد الشموع المستخدمة للتحليل
CANDLE_LIMIT = 220

cache = {}
cache_lock = threading.Lock()


MARKETS = {
    "saudi": [
        {"symbol": "2222.SR", "name": "أرامكو"},
        {"symbol": "1120.SR", "name": "الراجحي"},
        {"symbol": "2010.SR", "name": "سابك"},
        {"symbol": "1180.SR", "name": "الأهلي السعودي"},
        {"symbol": "7010.SR", "name": "الاتصالات السعودية"},
        {"symbol": "2082.SR", "name": "أكوا باور"},
        {"symbol": "1211.SR", "name": "معادن"},
        {"symbol": "1150.SR", "name": "الإنماء"},
        {"symbol": "4003.SR", "name": "إكسترا"},
        {"symbol": "7020.SR", "name": "موبايلي"},
        {"symbol": "4190.SR", "name": "جرير"},
        {"symbol": "5110.SR", "name": "كهرباء السعودية"},
    ],
    "us": [
        {"symbol": "AAPL", "name": "Apple"},
        {"symbol": "MSFT", "name": "Microsoft"},
        {"symbol": "NVDA", "name": "NVIDIA"},
        {"symbol": "AMZN", "name": "Amazon"},
        {"symbol": "META", "name": "Meta"},
        {"symbol": "GOOGL", "name": "Alphabet"},
        {"symbol": "TSLA", "name": "Tesla"},
        {"symbol": "AMD", "name": "AMD"},
        {"symbol": "NFLX", "name": "Netflix"},
        {"symbol": "PLTR", "name": "Palantir"},
    ],
    "forex": [
        {"symbol": "EURUSD=X", "name": "EUR/USD"},
        {"symbol": "GBPUSD=X", "name": "GBP/USD"},
        {"symbol": "USDJPY=X", "name": "USD/JPY"},
        {"symbol": "AUDUSD=X", "name": "AUD/USD"},
        {"symbol": "USDCAD=X", "name": "USD/CAD"},
        {"symbol": "USDCHF=X", "name": "USD/CHF"},
        {"symbol": "NZDUSD=X", "name": "NZD/USD"},
    ],
    "commodities": [
        {"symbol": "GC=F", "name": "Gold"},
        {"symbol": "SI=F", "name": "Silver"},
        {"symbol": "CL=F", "name": "Crude Oil"},
        {"symbol": "BZ=F", "name": "Brent Oil"},
        {"symbol": "NG=F", "name": "Natural Gas"},
    ],
    "indices": [
        {"symbol": "^GSPC", "name": "S&P 500"},
        {"symbol": "^NDX", "name": "Nasdaq 100"},
        {"symbol": "^DJI", "name": "Dow Jones"},
        {"symbol": "^RUT", "name": "Russell 2000"},
        {"symbol": "^FTSE", "name": "FTSE 100"},
        {"symbol": "^GDAXI", "name": "DAX"},
        {"symbol": "^N225", "name": "Nikkei 225"},
    ],
    "futures": [
        {"symbol": "ES=F", "name": "S&P 500 Futures"},
        {"symbol": "NQ=F", "name": "Nasdaq Futures"},
        {"symbol": "YM=F", "name": "Dow Futures"},
        {"symbol": "RTY=F", "name": "Russell Futures"},
        {"symbol": "GC=F", "name": "Gold Futures"},
        {"symbol": "CL=F", "name": "Crude Oil Futures"},
    ],
}


def now_ms():
    return int(time.time() * 1000)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


def clamp(value, minimum, maximum):
    return max(
        minimum,
        min(maximum, value),
    )


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 10) "
                "AppleWebKit/537.36 "
                "Chrome/140 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if not values:
        return []

    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1.0)

    result = [values[0]]

    for value in values[1:]:
        result.append(
            (
                (value - result[-1])
                * multiplier
            )
            + result[-1]
        )

    return result


def sma(values, period):
    if not values:
        return []

    result = []

    for i in range(len(values)):
        start = max(
            0,
            i - period + 1,
        )

        window = values[start:i + 1]

        result.append(
            sum(window) / len(window)
        )

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0.0)
        )

        losses.append(
            max(-change, 0.0)
        )

    avg_gain = (
        sum(gains[-period:])
        / period
    )

    avg_loss = (
        sum(losses[-period:])
        / period
    )

    if avg_loss == 0:
        if avg_gain > 0:
            return 100.0

        return 50.0

    rs = avg_gain / avg_loss

    return (
        100.0
        - (
            100.0
            / (1.0 + rs)
        )
    )


def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    trs = []

    for i in range(1, len(candles)):
        previous_close = candles[i - 1]["c"]

        high = candles[i]["h"]
        low = candles[i]["l"]

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
        return 0.0

    return (
        sum(trs[-period:])
        / period
    )


def macd(values):
    if len(values) < 35:
        return (
            0.0,
            0.0,
            0.0,
        )

    fast = ema(
        values,
        12,
    )

    slow = ema(
        values,
        26,
    )

    if not fast or not slow:
        return (
            0.0,
            0.0,
            0.0,
        )

    macd_values = []

    start = 25

    for i in range(
        start,
        len(values),
    ):
        macd_values.append(
            fast[i]
            - slow[i]
        )

    if not macd_values:
        return (
            0.0,
            0.0,
            0.0,
        )

    signal_values = ema(
        macd_values,
        9,
    )

    if not signal_values:
        return (
            macd_values[-1],
            0.0,
            macd_values[-1],
        )

    line = macd_values[-1]
    signal = signal_values[-1]
    histogram = line - signal

    return (
        line,
        signal,
        histogram,
    )


def calculate_support_resistance(candles):
    if not candles:
        return (
            0.0,
            0.0,
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

    return (
        support,
        resistance,
    )


# =========================================================
# ANALYSIS
# =========================================================

def calculate_analysis(
    candles,
    symbol,
    name=None,
):
    if len(candles) < 60:
        raise ValueError(
            "Not enough market data"
        )

    closes = [
        x["c"]
        for x in candles
    ]

    volumes = [
        x["v"]
        for x in candles
    ]

    price = closes[-1]

    ema20_values = ema(
        closes,
        20,
    )

    ema50_values = ema(
        closes,
        50,
    )

    ema200_values = ema(
        closes,
        200,
    )

    if (
        not ema20_values
        or not ema50_values
        or not ema200_values
    ):
        raise ValueError(
            "Not enough candles for EMA200"
        )

    ema20 = ema20_values[-1]
    ema50 = ema50_values[-1]
    ema200 = ema200_values[-1]

    previous_ema20 = (
        ema20_values[-2]
        if len(ema20_values) > 1
        else ema20
    )

    previous_ema50 = (
        ema50_values[-2]
        if len(ema50_values) > 1
        else ema50
    )

    rsi_value = rsi(
        closes,
        14,
    )

    atr_value = atr(
        candles,
        14,
    )

    (
        macd_line,
        macd_signal,
        macd_histogram,
    ) = macd(closes)

    volume_period = min(
        20,
        len(volumes),
    )

    volume_average = (
        sum(
            volumes[-volume_period:]
        )
        / volume_period
    )

    if volume_average > 0:
        volume_ratio = (
            volumes[-1]
            / volume_average
        )
    else:
        volume_ratio = 1.0

    momentum_period = min(
        10,
        len(closes) - 1,
    )

    old_price = closes[
        -1 - momentum_period
    ]

    if old_price > 0:
        momentum = (
            (
                (
                    price
                    - old_price
                )
                / old_price
            )
            * 100
        )
    else:
        momentum = 0.0

    current_open = candles[-1]["o"]

    if current_open > 0:
        candle_change = (
            (
                (
                    candles[-1]["c"]
                    - current_open
                )
                / current_open
            )
            * 100
        )
    else:
        candle_change = 0.0

    support, resistance = (
        calculate_support_resistance(
            candles
        )
    )

    # =====================================================
    # SCORE
    # =====================================================

    score = 50.0

    if price > ema20:
        score += 7
    else:
        score -= 7

    if price > ema50:
        score += 8
    else:
        score -= 8

    if price > ema200:
        score += 10
    else:
        score -= 10

    if ema20 > ema50:
        score += 6
    else:
        score -= 6

    if ema20 > previous_ema20:
        score += 4
    else:
        score -= 4

    if ema50 > previous_ema50:
        score += 3
    else:
        score -= 3

    if 50 <= rsi_value <= 68:
        score += 7

    elif rsi_value > 72:
        score -= 3

    elif rsi_value < 35:
        score += 2

    elif rsi_value < 45:
        score -= 3

    if macd_histogram > 0:
        score += 6
    else:
        score -= 6

    if volume_ratio >= 1.5:
        score += 7

    elif volume_ratio >= 1.1:
        score += 3

    elif volume_ratio < 0.7:
        score -= 3

    if momentum > 2:
        score += 5

    elif momentum < -2:
        score -= 5

    score = clamp(
        score,
        0,
        100,
    )

    # =====================================================
    # SIGNAL
    # =====================================================

    if score >= 72:
        signal = "شراء قوي"
        direction = "BUY"

    elif score >= 58:
        signal = "شراء"
        direction = "BUY"

    elif score <= 28:
        signal = "بيع قوي"
        direction = "SELL"

    elif score <= 42:
        signal = "بيع"
        direction = "SELL"

    else:
        signal = "حيادي"
        direction = "NEUTRAL"

    # =====================================================
    # TP / SL
    # =====================================================

    if price > 0:
        volatility_percent = (
            atr_value
            / price
        ) * 100
    else:
        volatility_percent = 1.0

    volatility_percent = clamp(
        volatility_percent,
        0.5,
        5.0,
    )

    stop_percent = clamp(
        max(
            1.0,
            volatility_percent * 1.5,
        ),
        1.0,
        4.0,
    )

    if direction == "BUY":
        target_percent = clamp(
            stop_percent * 1.8,
            1.5,
            7.0,
        )

        entry = price

        stop_loss = (
            price
            * (
                1
                - (
                    stop_percent
                    / 100
                )
            )
        )

        take_profit = (
            price
            * (
                1
                + (
                    target_percent
                    / 100
                )
            )
        )

    elif direction == "SELL":
        target_percent = clamp(
            stop_percent * 1.8,
            1.5,
            7.0,
        )

        entry = price

        stop_loss = (
            price
            * (
                1
                + (
                    stop_percent
                    / 100
                )
            )
        )

        take_profit = (
            price
            * (
                1
                - (
                    target_percent
                    / 100
                )
            )
        )

    else:
        target_percent = clamp(
            stop_percent * 1.5,
            1.5,
            6.0,
        )

        entry = price

        stop_loss = (
            price
            * (
                1
                - (
                    stop_percent
                    / 100
                )
            )
        )

        take_profit = (
            price
            * (
                1
                + (
                    target_percent
                    / 100
                )
            )
        )

    if price > 0 and support > 0:
        support_distance = (
            (
                (
                    price
                    - support
                )
                / price
            )
            * 100
        )
    else:
        support_distance = 0.0

    if price > 0 and resistance > 0:
        resistance_distance = (
            (
                (
                    resistance
                    - price
                )
                / price
            )
            * 100
        )
    else:
        resistance_distance = 0.0

    if direction == "BUY":
        trend = "صاعد"

    elif direction == "SELL":
        trend = "هابط"

    else:
        trend = "متذبذب"

    return {
        "symbol": symbol,
        "name": name or symbol,

        "price": round(
            price,
            10,
        ),

        "signal": signal,
        "direction": direction,

        "score": round(
            score,
            1,
        ),

        "score10": round(
            score / 10,
            1,
        ),

        "trend": trend,

        "entry": round(
            entry,
            10,
        ),

        "takeProfit": round(
            take_profit,
            10,
        ),

        "stopLoss": round(
            stop_loss,
            10,
        ),

        "targetPercent": round(
            target_percent,
            2,
        ),

        "stopPercent": round(
            stop_percent,
            2,
        ),

        "rsi": round(
            rsi_value,
            2,
        ),

        "ema20": round(
            ema20,
            10,
        ),

        "ema50": round(
            ema50,
            10,
        ),

        "ema200": round(
            ema200,
            10,
        ),

        "macd": round(
            macd_line,
            10,
        ),

        "macdSignal": round(
            macd_signal,
            10,
        ),

        "macdHistogram": round(
            macd_histogram,
            10,
        ),

        "volumeRatio": round(
            volume_ratio,
            2,
        ),

        "momentum": round(
            momentum,
            2,
        ),

        "candleChange": round(
            candle_change,
            2,
        ),

        "atr": round(
            atr_value,
            10,
        ),

        "volatility": round(
            volatility_percent,
            2,
        ),

        "support": round(
            support,
            10,
        ),

        "resistance": round(
            resistance,
            10,
        ),

        "supportDistance": round(
            support_distance,
            2,
        ),

        "resistanceDistance": round(
            resistance_distance,
            2,
        ),

        "updatedAt": now_ms(),
    }


# =========================================================
# OKX
# =========================================================

def okx_instruments():
    """
    يجلب جميع منتجات OKX Spot
    ثم يختار فقط:
    quoteCcy = USDT
    state = live
    """

    data = get_json(
        f"{OKX_BASE}/api/v5/public/instruments",
        params={
            "instType": "SPOT",
        },
    )

    if data.get("code") != "0":
        raise RuntimeError(
            data.get("msg")
            or "OKX instruments request failed"
        )

    rows = data.get("data") or []

    instruments = []

    for row in rows:
        inst_id = (
            row.get("instId")
            or ""
        ).upper()

        quote_ccy = (
            row.get("quoteCcy")
            or ""
        ).upper()

        state = (
            row.get("state")
            or ""
        ).lower()

        if (
            quote_ccy == "USDT"
            and state == "live"
            and inst_id.endswith(
                "-USDT"
            )
        ):
            instruments.append({
                "symbol": inst_id,
                "name": inst_id.replace(
                    "-USDT",
                    "",
                ),
                "baseCcy": row.get(
                    "baseCcy"
                ),
                "quoteCcy": quote_ccy,
                "state": state,
            })

    instruments.sort(
        key=lambda x: x["symbol"]
    )

    return instruments


def get_okx_usdt_instruments():
    key = "okx:usdt:instruments"

    with cache_lock:
        cached = cache.get(key)

    if cached:
        age = (
            time.time()
            - cached["time"]
        )

        # تحديث قائمة الأزواج كل 5 دقائق
        if age < 300:
            return cached["data"]

    instruments = okx_instruments()

    with cache_lock:
        cache[key] = {
            "time": time.time(),
            "data": instruments,
        }

    return instruments


def okx_candles(
    symbol,
    interval="15m",
    limit=CANDLE_LIMIT,
):
    data = get_json(
        f"{OKX_BASE}/api/v5/market/candles",
        params={
            "instId": symbol,
            "bar": interval,
            "limit": str(
                min(
                    limit,
                    300,
                )
            ),
        },
    )

    if data.get("code") != "0":
        raise RuntimeError(
            data.get("msg")
            or "OKX candles request failed"
        )

    rows = data.get("data") or []

    candles = []

    for row in reversed(rows):
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
            ),
        })

    return candles


def okx_ticker(symbol):
    data = get_json(
        f"{OKX_BASE}/api/v5/market/ticker",
        params={
            "instId": symbol,
        },
    )

    if data.get("code") != "0":
        raise RuntimeError(
            data.get("msg")
            or "OKX ticker request failed"
        )

    rows = data.get("data") or []

    if not rows:
        raise RuntimeError(
            "No ticker data"
        )

    row = rows[0]

    return {
        "symbol": symbol,

        "price": safe_float(
            row.get("last")
        ),

        "bid": safe_float(
            row.get("bidPx")
        ),

        "ask": safe_float(
            row.get("askPx")
        ),

        "high24h": safe_float(
            row.get("high24h")
        ),

        "low24h": safe_float(
            row.get("low24h")
        ),

        "volume24h": safe_float(
            row.get("vol24h")
        ),

        "quoteVolume24h": safe_float(
            row.get("volCcy24h")
        ),

        "timestamp": int(
            safe_float(
                row.get("ts")
            )
        ),
    }


def get_crypto_analysis(
    symbol,
    interval="15m",
):
    key = (
        f"crypto:"
        f"{symbol}:"
        f"{interval}"
    )

    with cache_lock:
        cached = cache.get(key)

    if cached:
        age = (
            time.time()
            - cached["time"]
        )

        if age < CACHE_SECONDS:
            return cached["data"]

    candles = okx_candles(
        symbol,
        interval,
        CANDLE_LIMIT,
    )

    result = calculate_analysis(
        candles,
        symbol,
        symbol.replace(
            "-USDT",
            "",
        ),
    )

    result["source"] = "OKX Spot"
    result["interval"] = interval

    with cache_lock:
        cache[key] = {
            "time": time.time(),
            "data": result,
        }

    return result


# =========================================================
# YAHOO
# =========================================================

def yahoo_chart(
    symbol,
    interval="15m",
    range_value="5d",
):
    data = get_json(
        f"{YAHOO_BASE}/v8/finance/chart/{symbol}",
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        },
    )

    result_list = (
        data
        .get("chart", {})
        .get("result")
        or []
    )

    if not result_list:
        error = (
            data
            .get("chart", {})
            .get("error")
        )

        if error:
            raise RuntimeError(
                error.get(
                    "description"
                )
                or "Yahoo request failed"
            )

        raise RuntimeError(
            "No Yahoo market data"
        )

    result = result_list[0]

    timestamps = (
        result.get(
            "timestamp"
        )
        or []
    )

    quote_list = (
        result
        .get("indicators", {})
        .get("quote", [])
    )

    if not quote_list:
        raise RuntimeError(
            "No Yahoo quote data"
        )

    quote = quote_list[0]

    opens = (
        quote.get("open")
        or []
    )

    highs = (
        quote.get("high")
        or []
    )

    lows = (
        quote.get("low")
        or []
    )

    closes = (
        quote.get("close")
        or []
    )

    volumes = (
        quote.get("volume")
        or []
    )

    candles = []

    for i, timestamp in enumerate(
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

            if (
                i < len(volumes)
                and volumes[i] is not None
            ):
                v = volumes[i]
            else:
                v = 0

            candles.append({
                "t": int(
                    timestamp
                    * 1000
                ),

                "o": float(o),
                "h": float(h),
                "l": float(l),
                "c": float(c),
                "v": float(v),
            })

        except Exception:
            continue

    return candles


def get_yahoo_analysis(
    symbol,
    name,
    interval="15m",
):
    key = (
        f"yahoo:"
        f"{symbol}:"
        f"{interval}"
    )

    with cache_lock:
        cached = cache.get(key)

    if cached:
        age = (
            time.time()
            - cached["time"]
        )

        if age < CACHE_SECONDS:
            return cached["data"]

    real_interval = interval

    if interval == "1h":
        range_value = "1mo"

    elif interval == "4h":
        range_value = "3mo"
        real_interval = "1h"

    elif interval == "1d":
        range_value = "1y"
        real_interval = "1d"

    else:
        range_value = "5d"

    candles = yahoo_chart(
        symbol,
        real_interval,
        range_value,
    )

    result = calculate_analysis(
        candles,
        symbol,
        name,
    )

    result["source"] = (
        "Yahoo Finance"
    )

    result["interval"] = (
        real_interval
    )

    with cache_lock:
        cache[key] = {
            "time": time.time(),
            "data": result,
        }

    return result


# =========================================================
# CRYPTO SCAN - ALL USDT
# =========================================================

def crypto_scan(
    interval="15m",
):
    instruments = (
        get_okx_usdt_instruments()
    )

    results = []
    errors = []

    def worker(item):
        try:
            return get_crypto_analysis(
                item["symbol"],
                interval,
            )

        except Exception as exc:
            return {
                "_error": True,
                "symbol": item[
                    "symbol"
                ],
                "name": item[
                    "name"
                ],
                "error": str(exc),
            }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item,
            )
            for item in instruments
        ]

        for future in as_completed(
            futures
        ):
            try:
                result = future.result()

                if result.get(
                    "_error"
                ):
                    errors.append({
                        "symbol": result.get(
                            "symbol"
                        ),
                        "name": result.get(
                            "name"
                        ),
                        "error": result.get(
                            "error"
                        ),
                    })

                else:
                    results.append(
                        result
                    )

            except Exception as exc:
                errors.append({
                    "error": str(exc),
                })

    # الأقوى أولاً
    results.sort(
        key=lambda x: x.get(
            "score",
            0,
        ),
        reverse=True,
    )

    signals = [
        x
        for x in results
        if x.get(
            "direction"
        ) in (
            "BUY",
            "SELL",
        )
    ]

    signals.sort(
        key=lambda x: x.get(
            "score",
            0,
        ),
        reverse=True,
    )

    return {
        "ok": True,

        "market": "crypto",

        "source": "OKX Spot",

        "interval": interval,

        "universe": "ALL USDT SPOT",

        "instrumentCount": len(
            instruments
        ),

        "count": len(
            results
        ),

        "resultCount": len(
            results
        ),

        "signalCount": len(
            signals
        ),

        "results": results,

        "signals": signals,

        "errors": errors,

        "updatedAt": now_ms(),
    }


# =========================================================
# OTHER MARKETS
# =========================================================

def market_scan(
    market="saudi",
    interval="15m",
):
    items = MARKETS.get(
        market,
        [],
    )

    results = []
    errors = []

    def worker(item):
        try:
            return get_yahoo_analysis(
                item["symbol"],
                item["name"],
                interval,
            )

        except Exception as exc:
            return {
                "_error": True,
                "symbol": item[
                    "symbol"
                ],
                "name": item[
                    "name"
                ],
                "error": str(exc),
            }

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                item,
            )
            for item in items
        ]

        for future in as_completed(
            futures
        ):
            try:
                result = future.result()

                if result.get(
                    "_error"
                ):
                    errors.append({
                        "symbol": result.get(
                            "symbol"
                        ),
                        "name": result.get(
                            "name"
                        ),
                        "error": result.get(
                            "error"
                        ),
                    })

                else:
                    results.append(
                        result
                    )

            except Exception as exc:
                errors.append({
                    "error": str(exc),
                })

    results.sort(
        key=lambda x: x.get(
            "score",
            0,
        ),
        reverse=True,
    )

    signals = [
        x
        for x in results
        if x.get(
            "direction"
        ) in (
            "BUY",
            "SELL",
        )
    ]

    return {
        "ok": True,

        "market": market,

        "source": "Yahoo Finance",

        "interval": interval,

        "count": len(
            results
        ),

        "results": results,

        "signals": signals,

        "errors": errors,

        "updatedAt": now_ms(),
    }


# =========================================================
# PAGES
# =========================================================

@app.route("/")
def index():
    try:
        return render_template(
            "index.html"
        )

    except Exception:
        return """
        <!doctype html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">
            <title>مضارب أبو سعود</title>
        </head>

        <body>
            <h2>مضارب أبو سعود</h2>
            <p>الخادم يعمل بنجاح.</p>
        </body>
        </html>
        """


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():
    result = {
        "ok": False,
        "online": False,
        "source": "OKX",
        "error": None,
        "timestamp": now_ms(),
    }

    try:
        data = get_json(
            f"{OKX_BASE}/api/v5/public/time"
        )

        if data.get(
            "code"
        ) == "0":

            result["ok"] = True
            result["online"] = True
            result["serverTime"] = (
                data.get("data")
            )

        else:
            result["error"] = (
                data.get("msg")
            )

    except Exception as exc:
        result["error"] = str(exc)

    return jsonify(result)


# =========================================================
# STATUS
# =========================================================

@app.route("/api/status")
def api_status():
    try:
        instruments = (
            get_okx_usdt_instruments()
        )

        return jsonify({
            "ok": True,
            "online": True,
            "name": "مضارب أبو سعود",

            "sources": {
                "crypto": "OKX Spot",
                "other": "Yahoo Finance",
            },

            "cryptoUniverse":
                "ALL USDT SPOT",

            "cryptoSymbols":
                len(instruments),

            "markets":
                list(MARKETS.keys()),

            "updatedAt":
                now_ms(),
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "online": True,
            "error": str(exc),
            "updatedAt": now_ms(),
        }), 502


# =========================================================
# GET ALL OKX USDT PAIRS
# =========================================================

@app.route("/api/crypto-symbols")
def api_crypto_symbols():
    try:
        instruments = (
            get_okx_usdt_instruments()
        )

        return jsonify({
            "ok": True,
            "source": "OKX Spot",
            "quote": "USDT",
            "state": "live",
            "count": len(
                instruments
            ),
            "symbols": [
                x["symbol"]
                for x in instruments
            ],
            "updatedAt": now_ms(),
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "symbols": [],
            "count": 0,
            "updatedAt": now_ms(),
        }), 502


# =========================================================
# PRICE
# =========================================================

@app.route(
    "/api/price/<path:symbol>"
)
def api_price(symbol):
    try:
        symbol = symbol.upper()

        if "-" in symbol:
            data = okx_ticker(
                symbol
            )

            return jsonify({
                "ok": True,
                "source": "OKX Spot",
                "data": data,
                "updatedAt": now_ms(),
            })

        data = get_yahoo_analysis(
            symbol,
            symbol,
            "15m",
        )

        return jsonify({
            "ok": True,
            "source":
                "Yahoo Finance",

            "data": {
                "symbol":
                    data["symbol"],

                "price":
                    data["price"],

                "updatedAt":
                    data["updatedAt"],
            },

            "updatedAt": now_ms(),
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "symbol": symbol,
            "updatedAt": now_ms(),
        }), 502


# =========================================================
# SCAN
# =========================================================

@app.route("/api/scan")
def api_scan():
    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    market = request.args.get(
        "market",
        "crypto",
    ).strip().lower()

    allowed_intervals = {
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    }

    if interval not in allowed_intervals:
        interval = "15m"

    try:
        if market == "crypto":

            result = crypto_scan(
                interval
            )

        else:

            if market not in MARKETS:
                return jsonify({
                    "ok": False,
                    "error":
                        "Unknown market",
                    "market": market,
                    "updatedAt":
                        now_ms(),
                }), 400

            result = market_scan(
                market,
                interval,
            )

        return jsonify(result)

    except Exception as exc:

        return jsonify({
            "ok": False,
            "market": market,
            "interval": interval,
            "count": 0,
            "results": [],
            "signals": [],
            "errors": [
                {
                    "error": str(exc)
                }
            ],
            "updatedAt": now_ms(),
        }), 500


# =========================================================
# CRYPTO SIGNALS
# =========================================================

@app.route("/api/signals")
def api_signals():
    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    if interval not in {
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    }:
        interval = "15m"

    try:
        result = crypto_scan(
            interval
        )

        return jsonify({
            "ok": True,

            "source": "OKX Spot",

            "universe":
                "ALL USDT SPOT",

            "interval":
                interval,

            "instrumentCount":
                result.get(
                    "instrumentCount",
                    0,
                ),

            "signals":
                result.get(
                    "signals",
                    [],
                ),

            "count":
                len(
                    result.get(
                        "signals",
                        [],
                    )
                ),

            "errors":
                result.get(
                    "errors",
                    [],
                ),

            "updatedAt":
                now_ms(),
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "source": "OKX Spot",
            "interval": interval,
            "signals": [],
            "count": 0,
            "errors": [
                {
                    "error": str(exc)
                }
            ],
            "updatedAt": now_ms(),
        }), 500


# =========================================================
# MARKET SIGNALS
# =========================================================

@app.route(
    "/api/market-signals"
)
def api_market_signals():
    market = request.args.get(
        "market",
        "saudi",
    ).strip().lower()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    if market not in MARKETS:
        return jsonify({
            "ok": False,
            "error":
                "Unknown market",
            "market": market,
            "updatedAt":
                now_ms(),
        }), 400

    if interval not in {
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    }:
        interval = "15m"

    try:
        result = market_scan(
            market,
            interval,
        )

        return jsonify(result)

    except Exception as exc:

        return jsonify({
            "ok": False,
            "market": market,
            "interval": interval,
            "results": [],
            "signals": [],
            "count": 0,
            "errors": [
                {
                    "error": str(exc)
                }
            ],
            "updatedAt":
                now_ms(),
        }), 500


# =========================================================
# SINGLE ANALYSIS
# =========================================================

@app.route(
    "/api/analysis/<path:symbol>"
)
def api_analysis(symbol):
    symbol = symbol.strip()

    interval = request.args.get(
        "interval",
        "15m",
    ).strip()

    if interval not in {
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    }:
        interval = "15m"

    try:

        if "-" in symbol:

            result = get_crypto_analysis(
                symbol.upper(),
                interval,
            )

        else:

            result = get_yahoo_analysis(
                symbol.upper(),
                symbol.upper(),
                interval,
            )

        return jsonify({
            "ok": True,
            "data": result,
            "updatedAt":
                now_ms(),
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "symbol": symbol,
            "interval": interval,
            "error": str(exc),
            "updatedAt":
                now_ms(),
        }), 502


# =========================================================
# TEST OKX
# =========================================================

@app.route("/api/test-okx")
def test_okx():
    try:

        ticker = okx_ticker(
            "BTC-USDT"
        )

        return jsonify({
            "ok": True,
            "source":
                "OKX Spot",
            "btc":
                ticker,
            "updatedAt":
                now_ms(),
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "source":
                "OKX Spot",
            "error":
                str(exc),
            "updatedAt":
                now_ms(),
        }), 502


# =========================================================
# TEST ANALYSIS
# =========================================================

@app.route("/api/test-analysis")
def test_analysis():
    try:

        result = get_crypto_analysis(
            "BTC-USDT",
            "15m",
        )

        return jsonify({
            "ok": True,
            "data":
                result,
            "updatedAt":
                now_ms(),
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error":
                str(exc),
            "updatedAt":
                now_ms(),
        }), 502


# =========================================================
# TEST ALL USDT
# =========================================================

@app.route(
    "/api/test-usdt"
)
def test_usdt():
    try:

        instruments = (
            get_okx_usdt_instruments()
        )

        sample = instruments[:10]

        return jsonify({
            "ok": True,

            "source":
                "OKX Spot",

            "quote":
                "USDT",

            "state":
                "live",

            "count":
                len(instruments),

            "first10":
                sample,

            "updatedAt":
                now_ms(),
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error":
                str(exc),
            "count": 0,
            "first10": [],
            "updatedAt":
                now_ms(),
        }), 502


# =========================================================
# ERRORS
# =========================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "ok": False,
        "error": "Not found",
        "path": request.path,
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "ok": False,
        "error":
            "Internal server error",
    }), 500


# =========================================================
# APP
# =========================================================

def create_app():
    return app


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "8080",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
