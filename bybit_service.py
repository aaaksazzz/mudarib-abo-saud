import os
import time
import threading
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# =========================================================
# Binance Spot
# =========================================================

BINANCE_BASES = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

TIMEOUT = int(os.getenv("BINANCE_TIMEOUT", "15"))

# الوقت بين طلبات العملات
REQUEST_DELAY = float(os.getenv("BINANCE_REQUEST_DELAY", "0.35"))

# مدة صلاحية البيانات المخزنة بالثواني
CACHE_TTL = int(os.getenv("BINANCE_CACHE_TTL", "900"))

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-Binance-Service/1.0",
    "Accept": "application/json",
})


# =========================================================
# Cache
# =========================================================

CACHE = {}

CACHE_LOCK = threading.Lock()

LAST_REQUEST_TIME = 0.0


# =========================================================
# Binance Request
# =========================================================

def wait_before_request():
    global LAST_REQUEST_TIME

    with CACHE_LOCK:
        now = time.time()
        elapsed = now - LAST_REQUEST_TIME

        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

        LAST_REQUEST_TIME = time.time()


def binance_request(path, params=None, retries=4):
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

                # حماية من Rate Limit
                if status == 429:
                    retry_after = response.headers.get(
                        "Retry-After",
                        "2"
                    )

                    try:
                        delay = float(retry_after)
                    except Exception:
                        delay = 2.0

                    delay = max(delay, 2.0)

                    time.sleep(delay)

                    last_error = (
                        f"Binance HTTP 429: Rate limit "
                        f"(waited {delay}s)"
                    )

                    continue

                # حظر مؤقت
                if status == 418:
                    delay = 10 + (attempt * 5)

                    time.sleep(delay)

                    last_error = (
                        f"Binance HTTP 418: IP temporarily banned"
                    )

                    continue

                # أخطاء السيرفر
                if status >= 500:
                    last_error = (
                        f"Binance HTTP {status}"
                    )

                    time.sleep(2 + attempt)

                    continue

                try:
                    data = response.json()
                except Exception:
                    body = response.text[:500]

                    last_error = (
                        f"Binance HTTP {status}: {body}"
                    )

                    continue

                if status != 200:
                    message = (
                        data.get("msg")
                        if isinstance(data, dict)
                        else None
                    )

                    last_error = (
                        f"Binance HTTP {status}: "
                        f"{message or data}"
                    )

                    continue

                # Binance API error
                if isinstance(data, dict) and "code" in data:
                    code = data.get("code")

                    if isinstance(code, int) and code < 0:
                        last_error = (
                            f"Binance code {code}: "
                            f"{data.get('msg', 'unknown error')}"
                        )

                        continue

                return data

            except requests.RequestException as e:
                last_error = (
                    f"Binance connection error: {e}"
                )

                time.sleep(1 + attempt)

            except Exception as e:
                last_error = str(e)

                time.sleep(1 + attempt)

    raise RuntimeError(
        last_error or "تعذر الاتصال بـ Binance"
    )


# =========================================================
# Cache Helpers
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

        return max(0, time.time() - item["time"])


# =========================================================
# Binance Time
# =========================================================

def binance_time():
    return binance_request("/api/v3/time")


# =========================================================
# Symbols
# =========================================================

def get_symbols(force=False):
    cache_key = "exchange_info"

    if not force:
        cached = cache_get(cache_key)

        if cached is not None:
            return cached

    data = binance_request(
        "/api/v3/exchangeInfo"
    )

    symbols = []

    for item in data.get("symbols", []):
        try:
            symbol = item.get("symbol", "")
            status = item.get("status", "")
            quote_asset = item.get("quoteAsset", "")

            if not symbol:
                continue

            if status != "TRADING":
                continue

            if quote_asset != "USDT":
                continue

            symbols.append({
                "symbol": symbol,
                "baseAsset": item.get("baseAsset"),
                "quoteAsset": quote_asset,
                "status": status,
                "source": "Binance Spot",
            })

        except Exception:
            continue

    cache_set(cache_key, symbols)

    return symbols


# =========================================================
# Tickers
# =========================================================

def get_tickers(force=False):
    cache_key = "tickers"

    if not force:
        cached = cache_get(cache_key)

        if cached is not None:
            return cached

    data = binance_request(
        "/api/v3/ticker/24hr"
    )

    tickers = []

    for item in data:
        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        try:
            price = float(item.get("lastPrice", 0))
            volume = float(item.get("volume", 0))
            quote_volume = float(
                item.get("quoteVolume", 0)
            )
            change = float(
                item.get("priceChangePercent", 0)
            )
        except Exception:
            continue

        tickers.append({
            "symbol": symbol,
            "price": price,
            "change24h": change,
            "volume24h": volume,
            "quoteVolume24h": quote_volume,
            "source": "Binance Spot",
        })

    cache_set(cache_key, tickers)

    return tickers


# =========================================================
# Klines
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


def normalize_kline(row):
    return {
        "time": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }


def get_klines(
    symbol,
    interval="15m",
    limit=230,
    force=False,
):
    symbol = str(symbol).upper().strip()
    interval = str(interval).strip()

    if interval not in INTERVALS:
        raise RuntimeError(
            f"الفاصل غير مدعوم: {interval}"
        )

    try:
        limit = int(limit)
    except Exception:
        limit = 230

    limit = max(1, min(limit, 1000))

    cache_key = (
        f"klines:{symbol}:{interval}:{limit}"
    )

    if not force:
        cached = cache_get(cache_key)

        if cached is not None:
            return cached

    data = binance_request(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": INTERVALS[interval],
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

    cache_set(cache_key, candles)

    return candles


# =========================================================
# Price
# =========================================================

def get_price(symbol):
    symbol = str(symbol).upper().strip()

    data = binance_request(
        "/api/v3/ticker/24hr",
        {
            "symbol": symbol
        },
    )

    return {
        "symbol": symbol,
        "price": float(
            data.get("lastPrice", 0)
        ),
        "change24h": float(
            data.get("priceChangePercent", 0)
        ),
        "volume24h": float(
            data.get("volume", 0)
        ),
        "quoteVolume24h": float(
            data.get("quoteVolume", 0)
        ),
        "source": "Binance Spot",
    }


# =========================================================
# Main
# =========================================================

@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud-binance",
        "source": "Binance Spot",
        "mode": "sequential",
        "cache": True,
    })


# =========================================================
# Health
# =========================================================

@app.get("/health")
def health():
    try:
        data = binance_time()

        return jsonify({
            "ok": True,
            "connected": True,
            "source": "Binance Spot",
            "server_time": data.get("serverTime"),
            "cached_items": len(CACHE),
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "connected": False,
            "source": "Binance Spot",
            "error": str(e),
        }), 502


# =========================================================
# Symbols
# =========================================================

@app.get("/symbols")
def symbols():
    try:
        force = request.args.get(
            "force",
            "0"
        ) == "1"

        data = get_symbols(
            force=force
        )

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


# =========================================================
# Tickers
# =========================================================

@app.get("/tickers")
def tickers():
    try:
        force = request.args.get(
            "force",
            "0"
        ) == "1"

        data = get_tickers(
            force=force
        )

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


# =========================================================
# Price
# =========================================================

@app.get("/price")
def price():
    symbol = request.args.get(
        "symbol",
        "BTCUSDT"
    ).upper().strip()

    try:
        data = get_price(symbol)

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


# =========================================================
# Klines
# =========================================================

@app.get("/klines")
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
                "230"
            )
        )
    except Exception:
        limit = 230

    force = request.args.get(
        "force",
        "0"
    ) == "1"

    try:
        data = get_klines(
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
            "count": len(data),
            "candles": data,
            "cache_age": cache_age(
                f"klines:{symbol}:{interval}:{max(1, min(limit, 1000))}"
            ),
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# Proxy
# =========================================================

@app.post("/proxy")
def proxy():
    body = request.get_json(
        silent=True
    ) or {}

    path = str(
        body.get("path", "")
    ).strip()

    params = body.get("params") or {}

    # فقط Public Spot Market Data
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
            params
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
# Cache Status
# =========================================================

@app.get("/cache")
def cache_status():
    with CACHE_LOCK:
        items = []

        for key, value in CACHE.items():
            age = time.time() - value["time"]

            items.append({
                "key": key,
                "age_seconds": round(
                    age,
                    2
                ),
                "expired": age > CACHE_TTL,
            })

    return jsonify({
        "ok": True,
        "source": "Binance Spot",
        "cache_ttl": CACHE_TTL,
        "request_delay": REQUEST_DELAY,
        "items": items,
    })


# =========================================================
# Run
# =========================================================

if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
