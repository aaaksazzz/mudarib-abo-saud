import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__, template_folder="templates", static_folder="static")

# =========================================================
# إعدادات
# =========================================================

BYBIT_SERVICE_URL = os.getenv(
    "BYBIT_SERVICE_URL",
    ""
).strip().rstrip("/")

BYBIT_DIRECT = "https://api.bybit.com"

TIMEOUT = 8
CACHE_SECONDS = 30
MAX_CANDLES = 100
MAX_RESULTS = 20
MAX_WORKERS = 5

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mudarib-Abo-Saud/1.0",
    "Accept": "application/json",
})

CACHE = {}
CACHE_LOCK = threading.Lock()

INTERVALS = {
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

# أهم العملات أولاً لتخفيف الضغط
CRYPTO = [
    ("BTCUSDT", "Bitcoin"),
    ("ETHUSDT", "Ethereum"),
    ("SOLUSDT", "Solana"),
    ("XRPUSDT", "XRP"),
    ("BNBUSDT", "BNB"),
    ("DOGEUSDT", "Dogecoin"),
    ("ADAUSDT", "Cardano"),
    ("AVAXUSDT", "Avalanche"),
    ("LINKUSDT", "Chainlink"),
    ("SUIUSDT", "Sui"),
    ("TRXUSDT", "TRON"),
    ("DOTUSDT", "Polkadot"),
    ("LTCUSDT", "Litecoin"),
    ("NEARUSDT", "NEAR"),
    ("APTUSDT", "Aptos"),
]

MARKET_LABEL = {
    "crypto": "العملات الرقمية",
}


# =========================================================
# CACHE
# =========================================================

def cache_get(key):
    with CACHE_LOCK:
        item = CACHE.get(key)

    if not item:
        return None

    if time.time() - item["time"] > CACHE_SECONDS:
        return None

    return item["data"]


def cache_set(key, data):
    with CACHE_LOCK:
        CACHE[key] = {
            "time": time.time(),
            "data": data,
        }


# =========================================================
# BYBIT
# =========================================================

def bybit_direct(path, params=None):
    r = HTTP.get(
        BYBIT_DIRECT + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    r.raise_for_status()

    data = r.json()

    if data.get("retCode") != 0:
        raise RuntimeError(
            data.get("retMsg") or "Bybit error"
        )

    return data.get("result", {})


def bybit_service(path, params=None):
    if not BYBIT_SERVICE_URL:
        return bybit_direct(
            path,
            params
        )

    r = HTTP.post(
        BYBIT_SERVICE_URL + "/proxy",
        json={
            "path": path,
            "params": params or {},
        },
        timeout=TIMEOUT + 3,
    )

    r.raise_for_status()

    data = r.json()

    if not data.get("ok"):
        raise RuntimeError(
            data.get("error") or
            "Bybit service error"
        )

    return data.get("result", {})


def get_kline(symbol, interval):
    iv = INTERVALS.get(interval)

    if not iv:
        raise ValueError(
            "الفاصل غير مدعوم"
        )

    key = f"kline:{symbol}:{interval}"

    old = cache_get(key)

    if old:
        return old

    result = bybit_service(
        "/v5/market/kline",
        {
            "category": "spot",
            "symbol": symbol,
            "interval": iv,
            "limit": MAX_CANDLES,
        },
    )

    rows = result.get("list", [])

    if not rows:
        raise RuntimeError(
            f"لا توجد بيانات لـ {symbol}"
        )

    candles = []

    for x in reversed(rows):

        if len(x) < 6:
            continue

        try:
            candles.append({
                "t": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5]),
            })
        except Exception:
            continue

    if len(candles) < 20:
        raise RuntimeError(
            "بيانات غير كافية"
        )

    cache_set(
        key,
        candles
    )

    return candles


def get_price(symbol):
    key = f"price:{symbol}"

    old = cache_get(key)

    if old:
        return old

    result = bybit_service(
        "/v5/market/tickers",
        {
            "category": "spot",
            "symbol": symbol,
        },
    )

    rows = result.get("list", [])

    if not rows:
        raise RuntimeError(
            "السعر غير متوفر"
        )

    x = rows[0]

    data = {
        "symbol": symbol,
        "price": float(
            x.get("lastPrice") or 0
        ),
        "change": round(
            float(
                x.get("price24hPcnt") or 0
            ) * 100,
            3,
        ),
        "volume": float(
            x.get("turnover24h") or 0
        ),
    }

    cache_set(
        key,
        data
    )

    return data


# =========================================================
# المؤشرات
# =========================================================

def ema(values, period):
    if len(values) < period:
        return None

    value = sum(
        values[:period]
    ) / period

    multiplier = 2 / (
        period + 1
    )

    for price in values[period:]:
        value = (
            (price - value)
            * multiplier
        ) + value

    return value


def calculate_rsi(values, period=14):
    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        period + 1
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
        sum(gains) / period
    )

    avg_loss = (
        sum(losses) / period
    )

    for i in range(
        period + 1,
        len(values)
    ):
        change = (
            values[i]
            - values[i - 1]
        )

        gain = max(
            change,
            0
        )

        loss = max(
            -change,
            0
        )

        avg_gain = (
            (avg_gain * (period - 1))
            + gain
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + loss
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def calculate_atr(candles, period=14):
    if len(candles) <= period:
        return 0

    trs = []

    for i in range(
        1,
        len(candles)
    ):
        high = candles[i]["h"]
        low = candles[i]["l"]
        previous = candles[i - 1]["c"]

        trs.append(
            max(
                high - low,
                abs(high - previous),
                abs(low - previous),
            )
        )

    return sum(
        trs[-period:]
    ) / period


# =========================================================
# التحليل
# =========================================================

def analyze(symbol, name, interval, candles):

    closes = [
        x["c"]
        for x in candles
    ]

    volumes = [
        x["v"]
        for x in candles
    ]

    price = closes[-1]

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

    rsi = calculate_rsi(
        closes
    )

    atr = calculate_atr(
        candles
    )

    score = 50

    reasons = []

    # الاتجاه
    if ema20:

        if price > ema20:
            score += 10
            reasons.append(
                "السعر فوق EMA20"
            )
        else:
            score -= 10

    if ema50:

        if price > ema50:
            score += 10
            reasons.append(
                "السعر فوق EMA50"
            )
        else:
            score -= 10

    if ema200:

        if price > ema200:
            score += 12
            reasons.append(
                "الاتجاه فوق EMA200"
            )
        else:
            score -= 12

    # RSI
    if 50 <= rsi <= 68:
        score += 8
        reasons.append(
            "RSI إيجابي"
        )

    elif rsi >= 72:
        score -= 5
        reasons.append(
            "RSI مرتفع"
        )

    elif rsi <= 30:
        score += 3
        reasons.append(
            "RSI منخفض"
        )

    # الزخم
    if len(closes) >= 6:

        momentum = (
            (
                closes[-1]
                - closes[-6]
            )
            / closes[-6]
        ) * 100

        if momentum > 0:
            score += 8
            reasons.append(
                "زخم صاعد"
            )
        elif momentum < 0:
            score -= 8
            reasons.append(
                "زخم هابط"
            )

    # الحجم
    volume_ratio = 1

    if len(volumes) >= 21:

        average_volume = (
            sum(volumes[-21:-1])
            / 20
        )

        if average_volume > 0:

            volume_ratio = (
                volumes[-1]
                / average_volume
            )

            if volume_ratio >= 1.5:
                score += 8
                reasons.append(
                    "حجم مرتفع"
                )

    score = max(
        0,
        min(
            100,
            round(score)
        )
    )

    # الإشارة
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
        signal = "محايد"
        direction = "NEUTRAL"

    # الدعم والمقاومة
    recent = candles[-20:]

    support = min(
        x["l"]
        for x in recent
    )

    resistance = max(
        x["h"]
        for x in recent
    )

    # الهدف والوقف
    risk = max(
        atr * 1.2,
        price * 0.01
    )

    if direction == "SELL":

        stop = price + risk
        target = price - (
            risk * 2
        )

    else:

        stop = price - risk
        target = price + (
            risk * 2
        )

    change = 0

    if len(closes) >= 2:

        change = (
            (
                closes[-1]
                - closes[-2]
            )
            / closes[-2]
        ) * 100

    return {
        "symbol": symbol,
        "name": name,

        "market": "crypto",
        "marketName":
            MARKET_LABEL["crypto"],

        "interval": interval,

        "signal": signal,
        "direction": direction,

        "score": score,
        "score10":
            round(score / 10, 1),

        "price": round(
            price,
            10
        ),

        "entry": round(
            price,
            10
        ),

        "target": round(
            target,
            10
        ),

        "tp": round(
            target,
            10
        ),

        "stop": round(
            stop,
            10
        ),

        "sl": round(
            stop,
            10
        ),

        "change":
            round(change, 3),

        "change_percent":
            round(change, 3),

        "rsi":
            round(rsi, 2),

        "ema20":
            round(ema20, 10)
            if ema20 else None,

        "ema50":
            round(ema50, 10)
            if ema50 else None,

        "ema200":
            round(ema200, 10)
            if ema200 else None,

        "atr":
            round(atr, 10),

        "support":
            round(support, 10),

        "resistance":
            round(resistance, 10),

        "volume_ratio":
            round(
                volume_ratio,
                2
            ),

        "reasons":
            reasons[:5],

        "source":
            "Bybit Spot",

        "updatedAt":
            int(time.time() * 1000),
    }


# =========================================================
# تحليل عملة واحدة
# =========================================================

def analyze_one(item, interval):

    symbol, name = item

    try:

        candles = get_kline(
            symbol,
            interval
        )

        return analyze(
            symbol,
            name,
            interval,
            candles
        )

    except Exception as e:

        return {
            "symbol": symbol,
            "name": name,
            "market": "crypto",
            "marketName":
                "العملات الرقمية",
            "interval": interval,
            "signal": "غير متاح",
            "direction": "ERROR",
            "score": 0,
            "price": 0,
            "source": "Bybit Spot",
            "error": str(e),
        }


# =========================================================
# SCAN
# =========================================================

def scan_crypto(interval):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                analyze_one,
                item,
                interval
            )
            for item in CRYPTO
        ]

        for job in as_completed(jobs):

            try:

                result = job.result()

                if result.get(
                    "direction"
                ) != "ERROR":

                    results.append(
                        result
                    )

            except Exception:
                pass

    results.sort(
        key=lambda x:
            x.get("score", 0),
        reverse=True
    )

    return results[:MAX_RESULTS]


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route("/health")
def health():

    try:

        result = bybit_service(
            "/v5/market/time"
        )

        return jsonify({
            "ok": True,
            "online": True,
            "source": "Bybit",
            "serverTime":
                result.get(
                    "timeNano"
                ),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "online": False,
            "source": "Bybit",
            "error": str(e),
        }), 502


@app.route("/api/scan")
def api_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    market = request.args.get(
        "market",
        "crypto"
    )

    if interval not in INTERVALS:
        interval = "15m"

    if market in (
        "all",
        "crypto",
        "",
    ):

        results = scan_crypto(
            interval
        )

    else:

        results = []

    return jsonify({
        "ok": True,
        "cached": False,

        "source":
            "Bybit Spot",

        "interval":
            interval,

        "market":
            market,

        "count":
            len(results),

        "results":
            results,

        "signals":
            results,

        "updatedAt":
            int(time.time() * 1000),
    })


@app.route("/api/signals")
def api_signals():

    return api_scan()


@app.route("/api/market-signals")
def api_market_signals():

    return api_scan()


@app.route("/api/analysis/<symbol>")
def api_analysis(symbol):

    interval = request.args.get(
        "interval",
        "15m"
    )

    symbol = symbol.upper()

    found = None

    for item in CRYPTO:

        if item[0] == symbol:

            found = item
            break

    if not found:

        return jsonify({
            "ok": False,
            "error":
                "العملة غير موجودة"
        }), 404

    result = analyze_one(
        found,
        interval
    )

    if result.get(
        "direction"
    ) == "ERROR":

        return jsonify({
            "ok": False,
            "error":
                result.get(
                    "error",
                    "فشل التحليل"
                ),
        }), 502

    return jsonify({
        "ok": True,
        "result": result,
    })


@app.route("/api/price/<symbol>")
def api_price(symbol):

    try:

        data = get_price(
            symbol.upper()
        )

        return jsonify({
            "ok": True,
            "source":
                "Bybit Spot",
            **data,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 502


# =========================================================
# التشغيل
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
        threaded=True
    )
