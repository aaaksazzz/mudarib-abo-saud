# -*- coding: utf-8 -*-

import os
import time
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
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

OKX_BASE = "https://www.okx.com"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"

SAHMK_BASE = "https://api.sahmk.sa"
SAHMK_API_KEY = os.environ.get("SAHMK_API_KEY", "").strip()

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 Mudarib-Abo-Saud/3.0",
    "Accept": "application/json,text/plain,*/*"
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


def cache_set(key, value, seconds=120):
    with CACHE_LOCK:
        CACHE[key] = (
            time.time() + seconds,
            value
        )


# =========================================================
# HELPERS
# =========================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        return float(value)
    except Exception:
        return default


def round_price(value):
    value = safe_float(value)

    if value <= 0:
        return 0

    if value >= 1000:
        return round(value, 2)

    if value >= 1:
        return round(value, 4)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_html(text):
    if not text:
        return ""

    text = unescape(str(text))

    while "<" in text and ">" in text:
        start = text.find("<")
        end = text.find(">", start)

        if end == -1:
            break

        text = text[:start] + " " + text[end + 1:]

    return " ".join(text.split())


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    values = [safe_float(x) for x in values]

    if len(values) < period:
        return []

    result = [None] * (period - 1)

    sma = sum(values[:period]) / period
    result.append(sma)

    multiplier = 2 / (period + 1)
    previous = sma

    for price in values[period:]:
        current = (
            (price - previous) * multiplier
        ) + previous

        result.append(current)
        previous = current

    return result


def rsi(values, period=14):
    values = [safe_float(x) for x in values]

    if len(values) <= period:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    current_rsi = 100 - (100 / (1 + rs))

    for i in range(period, len(gains)):
        avg_gain = (
            ((avg_gain * (period - 1)) + gains[i])
            / period
        )

        avg_loss = (
            ((avg_loss * (period - 1)) + losses[i])
            / period
        )

        if avg_loss == 0:
            current_rsi = 100
        else:
            rs = avg_gain / avg_loss
            current_rsi = 100 - (100 / (1 + rs))

    return current_rsi


def atr(candles, period=14):
    if len(candles) <= period:
        return 0

    trs = []

    for i in range(1, len(candles)):
        high = safe_float(candles[i]["h"])
        low = safe_float(candles[i]["l"])
        previous_close = safe_float(candles[i - 1]["c"])

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return 0

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            ((value * (period - 1)) + tr)
            / period
        )

    return value


def macd(values):
    e12 = ema(values, 12)
    e26 = ema(values, 26)

    if not e12 or not e26:
        return {
            "macd": 0,
            "signal": 0,
            "histogram": 0
        }

    macd_values = []

    start = 25

    for i in range(start, len(values)):
        a = e12[i]
        b = e26[i]

        if a is not None and b is not None:
            macd_values.append(a - b)

    if not macd_values:
        return {
            "macd": 0,
            "signal": 0,
            "histogram": 0
        }

    signal_values = ema(macd_values, 9)

    current_macd = macd_values[-1]

    if signal_values and signal_values[-1] is not None:
        current_signal = signal_values[-1]
    else:
        current_signal = current_macd

    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_macd - current_signal
    }


def analyze_candles(candles):
    if not candles or len(candles) < 30:
        return None

    closes = [
        safe_float(x["c"])
        for x in candles
    ]

    if not closes:
        return None

    price = closes[-1]

    if price <= 0:
        return None

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    ema20 = e20[-1] if e20 and e20[-1] is not None else price
    ema50 = e50[-1] if e50 and e50[-1] is not None else price
    ema200 = e200[-1] if e200 and e200[-1] is not None else price

    current_rsi = rsi(closes)

    current_atr = atr(candles)

    macd_data = macd(closes)

    score = 50
    reasons = []

    # EMA 20
    if price > ema20:
        score += 8
        reasons.append("السعر فوق EMA20")
    else:
        score -= 8
        reasons.append("السعر تحت EMA20")

    # EMA 50
    if price > ema50:
        score += 8
        reasons.append("السعر فوق EMA50")
    else:
        score -= 8
        reasons.append("السعر تحت EMA50")

    # EMA 200
    if price > ema200:
        score += 10
        reasons.append("السعر فوق EMA200")
    else:
        score -= 10
        reasons.append("السعر تحت EMA200")

    # RSI
    if 50 <= current_rsi <= 68:
        score += 8
        reasons.append("RSI إيجابي")
    elif 32 <= current_rsi < 50:
        score -= 5
        reasons.append("RSI ضعيف")
    elif current_rsi > 72:
        score -= 4
        reasons.append("RSI مرتفع")
    elif current_rsi < 28:
        score += 3
        reasons.append("RSI منخفض")

    # MACD
    if macd_data["histogram"] > 0:
        score += 8
        reasons.append("MACD إيجابي")
    else:
        score -= 8
        reasons.append("MACD سلبي")

    # Candle
    if len(candles) >= 2:
        previous = safe_float(candles[-2]["c"])

        if price > previous:
            score += 5
            reasons.append("الشمعة الأخيرة إيجابية")
        elif price < previous:
            score -= 5
            reasons.append("الشمعة الأخيرة سلبية")

    score = max(0, min(100, score))

    if score >= 78:
        signal = "شراء قوي"
        direction = "BUY"
    elif score >= 62:
        signal = "شراء"
        direction = "BUY"
    elif score <= 22:
        signal = "بيع قوي"
        direction = "SELL"
    elif score <= 38:
        signal = "بيع"
        direction = "SELL"
    else:
        signal = "حيادي"
        direction = "NEUTRAL"

    risk = max(
        current_atr * 1.2,
        price * 0.01
    )

    if direction == "SELL":
        entry = price
        tp1 = price - risk
        tp2 = price - (risk * 1.8)
        tp3 = price - (risk * 2.5)
        sl = price + risk
    else:
        entry = price
        tp1 = price + risk
        tp2 = price + (risk * 1.8)
        tp3 = price + (risk * 2.5)
        sl = price - risk

    return {
        "signal": signal,
        "direction": direction,
        "score": score,
        "score10": round(score / 10, 1),

        "price": round_price(price),
        "entry": round_price(entry),
        "tp1": round_price(tp1),
        "tp2": round_price(tp2),
        "tp3": round_price(tp3),
        "sl": round_price(sl),

        "rsi": round(current_rsi, 2),
        "ema20": round_price(ema20),
        "ema50": round_price(ema50),
        "ema200": round_price(ema200),
        "atr": round_price(current_atr),

        "macd": round(macd_data["macd"], 8),
        "reasons": reasons,

        "candles": candles[-100:]
    }


# =========================================================
# PARALLEL SCAN
# =========================================================

def run_parallel(items, worker, max_workers=6):
    results = []

    if not items:
        return results

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        jobs = {
            executor.submit(worker, item): item
            for item in items
        }

        for future in as_completed(jobs):
            try:
                result = future.result()

                if result:
                    price = safe_float(
                        result.get("price")
                    )

                    if price > 0:
                        results.append(result)

            except Exception:
                continue

    return results


# =========================================================
# OKX HTTP
# =========================================================

def okx_get(path, params=None, timeout=8):
    try:
        response = HTTP.get(
            OKX_BASE + path,
            params=params or {},
            timeout=timeout
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            return None

        return data

    except Exception:
        return None


# =========================================================
# OKX SPOT
# =========================================================

def normalize_okx_symbol(symbol):
    s = str(symbol or "").upper().strip()

    if s.endswith("-USDT"):
        return s

    s = s.replace("/", "-")
    s = s.replace("_", "-")

    if s.endswith("-USDT"):
        return s

    compact = s.replace("-", "")

    if compact.endswith("USDT"):
        base = compact[:-4]

        if base:
            return f"{base}-USDT"

    return s


def okx_markets():
    cached = cache_get("okx_spot_markets")

    if cached is not None:
        return cached

    data = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": "SPOT"
        }
    )

    markets = []

    if data and data.get("code") == "0":

        for x in data.get("data", []):

            inst_id = str(
                x.get("instId", "")
            ).upper()

            if not inst_id.endswith("-USDT"):
                continue

            price = safe_float(x.get("last"))

            if price <= 0:
                continue

            markets.append({
                "symbol": inst_id.replace("-", ""),
                "okx_symbol": inst_id,
                "name": inst_id,
                "price": round_price(price),
                "volume24h": safe_float(
                    x.get("volCcy24h")
                ),
                "change24h": safe_float(
                    x.get("sodUtc8")
                )
            })

    markets.sort(
        key=lambda x: x["volume24h"],
        reverse=True
    )

    cache_set(
        "okx_spot_markets",
        markets,
        60
    )

    return markets


def okx_klines(
    symbol,
    interval="15m",
    limit=120
):
    inst_id = normalize_okx_symbol(symbol)

    bar_map = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D"
    }

    bar = bar_map.get(
        interval,
        "15m"
    )

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": str(
                min(int(limit), 300)
            )
        }
    )

    if not data or data.get("code") != "0":
        return []

    candles = []

    for x in reversed(
        data.get("data", [])
    ):
        try:
            candles.append({
                "t": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5])
            })

        except Exception:
            continue

    return candles


def crypto_analysis(
    symbol,
    interval="15m"
):
    candles = okx_klines(
        symbol,
        interval,
        120
    )

    result = analyze_candles(
        candles
    )

    if not result:
        return None

    result["symbol"] = symbol
    result["name"] = symbol
    result["source"] = "OKX Spot"
    result["market"] = "crypto"
    result["interval"] = interval

    return result


def crypto_scan(interval="15m"):
    cache_key = (
        f"crypto_scan_{interval}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    markets = okx_markets()

    markets = markets[:40]

    def worker(market):
        result = crypto_analysis(
            market["symbol"],
            interval
        )

        if result:
            result["name"] = market.get(
                "name",
                market["symbol"]
            )
            result["volume24h"] = market.get(
                "volume24h",
                0
            )
            result["change24h"] = market.get(
                "change24h",
                0
            )

        return result

    results = run_parallel(
        markets,
        worker,
        6
    )

    results.sort(
        key=lambda x: safe_float(
            x.get("score")
        ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "OKX Spot",
        "market": "crypto",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        cache_key,
        payload,
        90
    )

    return payload


# =========================================================
# OKX FUTURES - FIXED
# =========================================================

def normalize_okx_future(symbol):
    """
    يحول جميع الصيغ إلى:
    BTC-USDT-SWAP
    """

    s = str(symbol or "").upper().strip()

    if s.endswith("-USDT-SWAP"):
        return s

    s = s.replace("_", "-")
    s = s.replace("/", "-")

    if s.endswith("-USDT-SWAP"):
        return s

    compact = s.replace("-", "")

    # BTCUSDTSWAP
    if compact.endswith("USDTSWAP"):
        base = compact[:-8]

        if base:
            return f"{base}-USDT-SWAP"

    # BTCUSDT
    if compact.endswith("USDT"):
        base = compact[:-4]

        if base:
            return f"{base}-USDT-SWAP"

    return s


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

    markets = []

    if data and data.get("code") == "0":

        for x in data.get("data", []):

            inst_id = str(
                x.get("instId", "")
            ).upper()

            if not inst_id.endswith(
                "-USDT-SWAP"
            ):
                continue

            price = safe_float(
                x.get("last")
            )

            if price <= 0:
                continue

            compact_symbol = (
                inst_id
                .replace("-", "")
            )

            markets.append({
                "symbol": compact_symbol,
                "okx_symbol": inst_id,
                "name": inst_id,
                "price": round_price(price),
                "volume24h": safe_float(
                    x.get("volCcy24h")
                ),
                "change24h": safe_float(
                    x.get("sodUtc8")
                )
            })

    markets.sort(
        key=lambda x: x["volume24h"],
        reverse=True
    )

    cache_set(
        "okx_futures_markets",
        markets,
        60
    )

    return markets


def okx_futures_klines(
    symbol,
    interval="15m",
    limit=120
):
    inst_id = normalize_okx_future(
        symbol
    )

    bar_map = {
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D"
    }

    bar = bar_map.get(
        interval,
        "15m"
    )

    data = okx_get(
        "/api/v5/market/candles",
        {
            "instType": "SWAP",
            "instId": inst_id,
            "bar": bar,
            "limit": str(
                min(int(limit), 300)
            )
        }
    )

    if not data:
        return []

    if data.get("code") != "0":
        return []

    rows = data.get("data") or []

    candles = []

    for x in reversed(rows):
        try:
            candles.append({
                "t": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5])
            })

        except Exception:
            continue

    return candles


def futures_analysis(
    symbol,
    interval="15m",
    name=None
):
    candles = okx_futures_klines(
        symbol,
        interval,
        120
    )

    if not candles or len(candles) < 30:
        return None

    result = analyze_candles(
        candles
    )

    if not result:
        return None

    result["symbol"] = symbol
    result["name"] = name or symbol
    result["source"] = "OKX Futures"
    result["market"] = "futures"
    result["interval"] = interval

    return result


def futures_scan_data(
    interval="15m",
    limit=40
):
    cache_key = (
        f"futures_scan_{interval}_{limit}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    markets = okx_futures_markets()

    markets = markets[:limit]

    def worker(market):

        result = futures_analysis(
            market["okx_symbol"],
            interval,
            market.get("name")
        )

        # إذا ما توفرت الشموع،
        # لا نخلي الرمز يكسر الفحص كامل.
        # نرجع سعر السوق فقط بدون اختلاق إشارة.
        if not result:
            price = safe_float(
                market.get("price")
            )

            if price <= 0:
                return None

            return {
                "symbol": market["symbol"],
                "name": market.get(
                    "name",
                    market["symbol"]
                ),
                "source": "OKX Futures",
                "market": "futures",
                "interval": interval,
                "signal": "غير متاح",
                "direction": "NEUTRAL",
                "score": 50,
                "score10": 5,
                "price": round_price(price),
                "entry": round_price(price),
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
                "reasons": [
                    "بيانات الشموع غير متاحة حالياً"
                ],
                "candles": []
            }

        result["volume24h"] = market.get(
            "volume24h",
            0
        )

        result["change24h"] = market.get(
            "change24h",
            0
        )

        return result

    results = run_parallel(
        markets,
        worker,
        5
    )

    results.sort(
        key=lambda x: safe_float(
            x.get("score")
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
        cache_key,
        payload,
        90
    )

    return payload


# =========================================================
# YAHOO
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
    interval="15m"
):
    cache_key = (
        f"yahoo_candles_{symbol}_{interval}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    yahoo_interval = interval

    # Yahoo لا يوفر 4h مباشرة
    if interval == "4h":
        source = yahoo_candles(
            symbol,
            "1h"
        )

        if not source:
            return []

        grouped = {}

        for candle in source:

            timestamp = int(
                candle["t"]
            )

            bucket = (
                timestamp // 14400
            ) * 14400

            if bucket not in grouped:
                grouped[bucket] = {
                    "t": bucket,
                    "o": candle["o"],
                    "h": candle["h"],
                    "l": candle["l"],
                    "c": candle["c"],
                    "v": candle["v"]
                }

            else:
                item = grouped[bucket]

                item["h"] = max(
                    item["h"],
                    candle["h"]
                )

                item["l"] = min(
                    item["l"],
                    candle["l"]
                )

                item["c"] = candle["c"]

                item["v"] += candle["v"]

        result = sorted(
            grouped.values(),
            key=lambda x: x["t"]
        )

        cache_set(
            cache_key,
            result,
            120
        )

        return result

    range_value = YAHOO_RANGES.get(
        interval,
        "1mo"
    )

    url = (
        f"{YAHOO_CHART}/"
        f"{symbol}"
    )

    try:
        response = HTTP.get(
            url,
            params={
                "range": range_value,
                "interval": yahoo_interval,
                "includePrePost": "false",
                "events": "div,splits"
            },
            timeout=7
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
            result.get("timestamp")
            or []
        )

        quote = (
            result
            .get("indicators", {})
            .get("quote", [{}])[0]
        )

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        candles = []

        length = min(
            len(timestamps),
            len(opens),
            len(highs),
            len(lows),
            len(closes)
        )

        for i in range(length):

            try:
                o = opens[i]
                h = highs[i]
                l = lows[i]
                c = closes[i]

                if None in (
                    o,
                    h,
                    l,
                    c
                ):
                    continue

                v = (
                    volumes[i]
                    if i < len(volumes)
                    and volumes[i] is not None
                    else 0
                )

                candles.append({
                    "t": int(timestamps[i]),
                    "o": float(o),
                    "h": float(h),
                    "l": float(l),
                    "c": float(c),
                    "v": float(v)
                })

            except Exception:
                continue

        cache_set(
            cache_key,
            candles,
            120
        )

        return candles

    except Exception:
        return []


def yahoo_analysis(
    symbol,
    name,
    interval="15m"
):
    candles = yahoo_candles(
        symbol,
        interval
    )

    if not candles or len(candles) < 30:
        return None

    result = analyze_candles(
        candles
    )

    if not result:
        return None

    result["symbol"] = symbol
    result["name"] = name
    result["source"] = "Yahoo Finance"
    result["interval"] = interval

    return result


# =========================================================
# US MARKET
# =========================================================

US_STOCKS = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("GOOGL", "Alphabet"),
    ("GOOG", "Alphabet"),
    ("TSLA", "Tesla"),
    ("AVGO", "Broadcom"),
    ("AMD", "AMD"),
    ("NFLX", "Netflix"),
    ("JPM", "JPMorgan"),
    ("V", "Visa"),
    ("MA", "Mastercard"),
    ("WMT", "Walmart"),
    ("COST", "Costco"),
    ("KO", "Coca-Cola"),
    ("PEP", "PepsiCo"),
    ("XOM", "Exxon Mobil"),
    ("CVX", "Chevron"),
    ("BAC", "Bank of America"),
    ("INTC", "Intel"),
    ("QCOM", "Qualcomm"),
    ("ORCL", "Oracle"),
    ("CRM", "Salesforce"),
    ("ADBE", "Adobe"),
    ("UBER", "Uber"),
    ("PYPL", "PayPal"),
    ("PLTR", "Palantir"),
    ("COIN", "Coinbase")
]


def us_scan(interval="15m"):
    cache_key = (
        f"us_scan_{interval}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    def worker(item):

        symbol, name = item

        return yahoo_analysis(
            symbol,
            name,
            interval
        )

    results = run_parallel(
        US_STOCKS,
        worker,
        6
    )

    results.sort(
        key=lambda x: safe_float(
            x.get("score")
        ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "Yahoo Finance",
        "market": "usmarket",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        cache_key,
        payload,
        120
    )

    return payload


# =========================================================
# SAUDI MARKET
# =========================================================

SAUDI_STOCKS = [
    ("2222", "أرامكو السعودية"),
    ("1120", "مصرف الراجحي"),
    ("2010", "سابك"),
    ("1180", "الأهلي السعودي"),
    ("7010", "stc"),
    ("1211", "معادن"),
    ("1150", "مصرف الإنماء"),
    ("1060", "بنك ساب"),
    ("2020", "سابك للمغذيات الزراعية"),
    ("7020", "زين السعودية"),
    ("7030", "موبايلي"),
    ("4001", "أسواق العثيم"),
    ("4190", "جرير"),
    ("4280", "المملكة"),
    ("6010", "نادك"),
    ("4003", "إكسترا"),
    ("4002", "المواساة"),
    ("4004", "دله الصحية"),
    ("4050", "ساسكو"),
    ("4200", "الدريس"),
    ("4261", "ذيب"),
    ("4262", "بدجت السعودية"),
    ("5110", "كهرباء السعودية"),
    ("2060", "التصنيع"),
    ("2190", "سيسكو القابضة"),
    ("2290", "ينساب"),
    ("2330", "المتقدمة"),
    ("2380", "رابغ للتكرير والبتروكيماويات"),
    ("2350", "كيان السعودية"),
    ("2100", "وفرة"),
    ("3003", "أسمنت المدينة"),
    ("3010", "أسمنت العربية"),
    ("3030", "أسمنت السعودية"),
    ("3040", "أسمنت القصيم"),
    ("3050", "أسمنت الجنوب"),
    ("3060", "أسمنت ينبع"),
    ("3090", "أسمنت تبوك"),
    ("8010", "التعاونية"),
    ("8040", "ولاء"),
    ("8050", "سلامة"),
    ("8100", "سايكو"),
    ("8120", "اتحاد الخليج الأهلية")
]


def saudi_yahoo_symbol(symbol):
    return f"{symbol}.SR"


def saudi_analysis(
    symbol,
    interval="1d",
    name=None
):
    yahoo_symbol = saudi_yahoo_symbol(
        symbol
    )

    result = yahoo_analysis(
        yahoo_symbol,
        name or symbol,
        interval
    )

    if not result:
        return None

    result["symbol"] = symbol
    result["name"] = name or symbol
    result["source"] = "Yahoo Finance"
    result["market"] = "saudi"

    return result


def saudi_scan(interval="1d"):
    cache_key = (
        f"saudi_scan_{interval}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    def worker(item):

        symbol, name = item

        return saudi_analysis(
            symbol,
            interval,
            name
        )

    results = run_parallel(
        SAUDI_STOCKS,
        worker,
        6
    )

    results.sort(
        key=lambda x: safe_float(
            x.get("score")
        ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "Yahoo Finance",
        "market": "saudi",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        cache_key,
        payload,
        120
    )

    return payload


# =========================================================
# FOREX
# =========================================================

FOREX_PAIRS = [
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("USDCAD=X", "USD/CAD"),
    ("AUDUSD=X", "AUD/USD"),
    ("NZDUSD=X", "NZD/USD"),
    ("EURGBP=X", "EUR/GBP"),
    ("EURJPY=X", "EUR/JPY"),
    ("GBPJPY=X", "GBP/JPY"),
    ("AUDJPY=X", "AUD/JPY"),
    ("CADJPY=X", "CAD/JPY"),
    ("CHFJPY=X", "CHF/JPY"),
    ("EURAUD=X", "EUR/AUD"),
    ("EURCHF=X", "EUR/CHF"),
    ("GBPAUD=X", "GBP/AUD"),
    ("GBPCAD=X", "GBP/CAD"),
    ("AUDCAD=X", "AUD/CAD"),
    ("AUDCHF=X", "AUD/CHF"),
    ("NZDJPY=X", "NZD/JPY")
]


def forex_scan(interval="15m"):
    cache_key = (
        f"forex_scan_{interval}"
    )

    cached = cache_get(cache_key)

    if cached is not None:
        return cached

    def worker(item):

        symbol, name = item

        return yahoo_analysis(
            symbol,
            name,
            interval
        )

    results = run_parallel(
        FOREX_PAIRS,
        worker,
        6
    )

    results.sort(
        key=lambda x: safe_float(
            x.get("score")
        ),
        reverse=True
    )

    payload = {
        "ok": True,
        "source": "Yahoo Finance",
        "market": "forex",
        "interval": interval,
        "results": results,
        "count": len(results),
        "updated": now_iso()
    }

    cache_set(
        cache_key,
        payload,
        120
    )

    return payload


# =========================================================
# SAHMK OPTIONAL
# =========================================================

def sahmk_headers():
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mudarib-Abo-Saud/3.0"
    }

    if SAHMK_API_KEY:
        headers["Authorization"] = (
            f"Bearer {SAHMK_API_KEY}"
        )

        headers["X-API-Key"] = (
            SAHMK_API_KEY
        )

    return headers


def sahmk_get(
    path,
    timeout=5
):
    if not SAHMK_API_KEY:
        return None

    try:
        response = HTTP.get(
            SAHMK_BASE + path,
            headers=sahmk_headers(),
            timeout=timeout
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


def sahmk_value(data):
    if not data:
        return None

    if isinstance(data, dict):

        for key in (
            "price",
            "last",
            "close",
            "value",
            "currentPrice"
        ):

            if key in data:

                value = safe_float(
                    data.get(key)
                )

                if value > 0:
                    return value

        for key in (
            "data",
            "result",
            "quote"
        ):

            if key in data:

                value = sahmk_value(
                    data.get(key)
                )

                if value:
                    return value

    elif isinstance(data, list):

        for item in data:

            value = sahmk_value(
                item
            )

            if value:
                return value

    return None


def sahmk_quote(symbol):
    if not SAHMK_API_KEY:
        return None

    paths = [
        f"/api/v1/quote/{symbol}/",
        f"/api/v1/quote/{symbol}",
        f"/api/v1/stocks/{symbol}",
        f"/api/v1/stock/{symbol}"
    ]

    for path in paths:

        data = sahmk_get(path)

        value = sahmk_value(data)

        if value:
            return value

    return None


def saudi_quote(symbol):
    """
    المصدر الأساسي اختياري SAHMK
    وإذا لم يعمل نستخدم Yahoo.
    """

    value = sahmk_quote(symbol)

    if value:
        return value

    candles = yahoo_candles(
        saudi_yahoo_symbol(symbol),
        "1d"
    )

    if candles:
        return safe_float(
            candles[-1]["c"]
        )

    return 0


# =========================================================
# NEWS
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
        "اقتصاد الشرق",
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
            timeout=7
        )

        if response.status_code != 200:
            return []

        root = ET.fromstring(
            response.content
        )

        items = []

        for item in root.findall(
            ".//item"
        )[:15]:

            title = item.findtext(
                "title",
                ""
            )

            link = item.findtext(
                "link",
                ""
            )

            description = item.findtext(
                "description",
                ""
            )

            pub_date = item.findtext(
                "pubDate",
                ""
            )

            items.append({
                "source": source_name,
                "title": clean_html(title),
                "description": clean_html(
                    description
                ),
                "link": link,
                "date": pub_date
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

    news = []

    for source_name, url in ARABIC_RSS:
        news.extend(
            fetch_rss(
                source_name,
                url
            )
        )

    news = news[:40]

    payload = {
        "ok": True,
        "results": news,
        "count": len(news),
        "updated": now_iso()
    }

    cache_set(
        "arabic_news",
        payload,
        300
    )

    return payload


# =========================================================
# API ROUTES - OKX
# =========================================================

@app.route("/api/okx/test")
def api_okx_test():

    data = okx_get(
        "/api/v5/public/time"
    )

    return jsonify({
        "ok": bool(data),
        "source": "OKX",
        "data": data
    })


@app.route("/api/okx/markets")
def api_okx_markets():
    return jsonify({
        "ok": True,
        "source": "OKX Spot",
        "results": okx_markets()
    })


@app.route("/api/okx/klines")
def api_okx_klines():

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
        "symbol": symbol,
        "interval": interval,
        "results": okx_klines(
            symbol,
            interval
        )
    })


@app.route("/api/okx/analysis")
def api_okx_analysis():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    result = crypto_analysis(
        symbol,
        interval
    )

    return jsonify({
        "ok": bool(result),
        "source": "OKX Spot",
        "result": result
    })


@app.route("/api/okx/prices")
def api_okx_prices():

    markets = okx_markets()

    return jsonify({
        "ok": True,
        "source": "OKX Spot",
        "results": markets
    })


@app.route("/api/okx/price")
def api_okx_price():

    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    )

    markets = okx_markets()

    for item in markets:

        if item["symbol"] == symbol.upper():

            return jsonify({
                "ok": True,
                "result": item
            })

    return jsonify({
        "ok": False,
        "result": None
    })


@app.route("/api/okx/scan")
def api_okx_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify(
        crypto_scan(interval)
    )


# =========================================================
# FUTURES ROUTES
# =========================================================

@app.route("/api/futures/markets")
def api_futures_markets():

    markets = okx_futures_markets()

    return jsonify({
        "ok": True,
        "source": "OKX Futures",
        "type": "SWAP",
        "results": markets,
        "count": len(markets)
    })


@app.route("/api/futures/scan")
def api_futures_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:
        limit = int(
            request.args.get(
                "limit",
                "40"
            )
        )

    except Exception:
        limit = 40

    limit = max(
        5,
        min(limit, 40)
    )

    return jsonify(
        futures_scan_data(
            interval,
            limit
        )
    )


# =========================================================
# US ROUTES
# =========================================================

@app.route("/api/usmarket/markets")
def api_us_markets():

    return jsonify({
        "ok": True,
        "source": "Yahoo Finance",
        "results": [
            {
                "symbol": symbol,
                "name": name
            }
            for symbol, name
            in US_STOCKS
        ]
    })


@app.route("/api/usmarket/analysis")
def api_us_analysis():

    symbol = request.args.get(
        "symbol",
        "AAPL"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    name = symbol

    for s, n in US_STOCKS:

        if s == symbol.upper():
            name = n
            break

    result = yahoo_analysis(
        symbol.upper(),
        name,
        interval
    )

    return jsonify({
        "ok": bool(result),
        "source": "Yahoo Finance",
        "result": result
    })


@app.route("/api/usmarket/signals")
def api_us_signals():

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify(
        us_scan(interval)
    )


# =========================================================
# SAUDI ROUTES
# =========================================================

@app.route("/api/saudi/markets")
def api_saudi_markets():

    return jsonify({
        "ok": True,
        "source": "Yahoo Finance",
        "results": [
            {
                "symbol": symbol,
                "name": name
            }
            for symbol, name
            in SAUDI_STOCKS
        ]
    })


@app.route("/api/saudi/analysis")
def api_saudi_analysis():

    symbol = request.args.get(
        "symbol",
        "2222"
    )

    interval = request.args.get(
        "interval",
        "1d"
    )

    name = symbol

    for s, n in SAUDI_STOCKS:

        if s == symbol:
            name = n
            break

    result = saudi_analysis(
        symbol,
        interval,
        name
    )

    return jsonify({
        "ok": bool(result),
        "source": "Yahoo Finance",
        "result": result
    })


@app.route("/api/saudi/scan")
def api_saudi_scan():

    interval = request.args.get(
        "interval",
        "1d"
    )

    return jsonify(
        saudi_scan(interval)
    )


# =========================================================
# FOREX ROUTES
# =========================================================

@app.route("/api/forex/markets")
def api_forex_markets():

    return jsonify({
        "ok": True,
        "source": "Yahoo Finance",
        "results": [
            {
                "symbol": symbol,
                "name": name
            }
            for symbol, name
            in FOREX_PAIRS
        ]
    })


@app.route("/api/forex/analysis")
def api_forex_analysis():

    symbol = request.args.get(
        "symbol",
        "EURUSD=X"
    )

    interval = request.args.get(
        "interval",
        "15m"
    )

    name = symbol

    for s, n in FOREX_PAIRS:

        if s == symbol:
            name = n
            break

    result = yahoo_analysis(
        symbol,
        name,
        interval
    )

    return jsonify({
        "ok": bool(result),
        "source": "Yahoo Finance",
        "result": result
    })


@app.route("/api/forex/signals")
def api_forex_signals():

    interval = request.args.get(
        "interval",
        "15m"
    )

    return jsonify(
        forex_scan(interval)
    )


# =========================================================
# NEWS ROUTE
# =========================================================

@app.route("/api/news")
def api_news():
    return jsonify(
        get_news()
    )


# =========================================================
# MARKET OVERVIEW
# =========================================================

@app.route("/api/markets/overview")
def api_markets_overview():

    return jsonify({
        "ok": True,
        "markets": {
            "crypto": {
                "name": "العملات الرقمية",
                "source": "OKX Spot"
            },
            "saudi": {
                "name": "السوق السعودي",
                "source": "Yahoo Finance"
            },
            "usmarket": {
                "name": "السوق الأمريكي",
                "source": "Yahoo Finance"
            },
            "forex": {
                "name": "الفوركس",
                "source": "Yahoo Finance"
            },
            "futures": {
                "name": "الفيوتشر",
                "source": "OKX Futures",
                "type": "SWAP"
            }
        },
        "updated": now_iso()
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "ok": True,
        "database": False,
        "sources": {
            "okx_spot": True,
            "okx_futures": True,
            "yahoo": True,
            "sahmk": bool(SAHMK_API_KEY)
        },
        "updated": now_iso()
    })


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return render_template(
        "index.html"
    )


# =========================================================
# COMPATIBILITY - BINANCE
# =========================================================

@app.route("/api/binance/test")
def api_binance_test():
    return api_okx_test()


@app.route("/api/binance/markets")
def api_binance_markets():
    return api_okx_markets()


@app.route("/api/binance/klines")
def api_binance_klines():
    return api_okx_klines()


@app.route("/api/binance/analysis")
def api_binance_analysis():
    return api_okx_analysis()


@app.route("/api/binance/scan")
def api_binance_scan():
    return api_okx_scan()


@app.route("/api/binance/prices")
def api_binance_prices():
    return api_okx_prices()


@app.route("/api/binance/price")
def api_binance_price():
    return api_okx_price()


# =========================================================
# COMPATIBILITY - BYBIT
# =========================================================

@app.route("/api/bybit/test")
def api_bybit_test():
    return api_okx_test()


@app.route("/api/bybit/markets")
def api_bybit_markets():
    return api_okx_markets()


@app.route("/api/bybit/klines")
def api_bybit_klines():
    return api_okx_klines()


@app.route("/api/bybit/analysis")
def api_bybit_analysis():
    return api_okx_analysis()


@app.route("/api/bybit/scan")
def api_bybit_scan():
    return api_okx_scan()


@app.route("/api/bybit/prices")
def api_bybit_prices():
    return api_okx_prices()


@app.route("/api/bybit/price")
def api_bybit_price():
    return api_okx_price()


# =========================================================
# ERRORS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):
        return jsonify({
            "ok": False,
            "error": "API endpoint not found"
        }), 404

    return render_template(
        "index.html"
    )


@app.errorhandler(500)
def server_error(error):

    if request.path.startswith("/api/"):
        return jsonify({
            "ok": False,
            "error": "Internal server error"
        }), 500

    return "حدث خطأ في الخادم", 500


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
