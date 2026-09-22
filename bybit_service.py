import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request


# ============================================================
# APP
# ============================================================

app = Flask(__name__)


# ============================================================
# CONFIG
# ============================================================

BYBIT_BASE_URL = os.getenv(
    "BYBIT_BASE_URL",
    "https://api.bybit.com"
)

BYBIT_TIMEOUT = float(
    os.getenv("BYBIT_TIMEOUT", "10")
)

REQUEST_DELAY = float(
    os.getenv("BYBIT_REQUEST_DELAY", "0.30")
)

CACHE_TTL = int(
    os.getenv("BYBIT_CACHE_TTL", "300")
)

KLINE_CACHE_TTL = int(
    os.getenv("BYBIT_KLINE_CACHE_TTL", "120")
)

CACHE_FILE = os.getenv(
    "BYBIT_CACHE_FILE",
    "bybit_service_cache.json"
)

# ============================================================
# Saudi market source
#
# ضع رابط API السعودي هنا إذا عندك مصدر API رسمي/موثوق.
#
# مثال:
# SAUDI_MARKET_URL=https://example.com/api/saudi
#
# إذا لم يوضع، يرجع القسم السعودي كـ "غير متصل"
# بدل إعطاء بيانات وهمية.
# ============================================================

SAUDI_MARKET_URL = os.getenv(
    "SAUDI_MARKET_URL",
    ""
)

SAUDI_TIMEOUT = float(
    os.getenv(
        "SAUDI_TIMEOUT",
        "10"
    )
)


# ============================================================
# HTTP
# ============================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent":
        "Mudarib-Abo-Saud/Bybit-Service/1.0",

    "Accept":
        "application/json"
})


# ============================================================
# CACHE
# ============================================================

CACHE = {}

CACHE_LOCK = threading.Lock()

LAST_REQUEST = 0.0

TICKER_CACHE = {
    "ts": 0,
    "data": []
}

US_INSTRUMENT_CACHE = {
    "ts": 0,
    "data": []
}


# ============================================================
# INTERVALS
# ============================================================

INTERVALS = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}


# ============================================================
# LOAD CACHE
# ============================================================

def load_cache():

    global CACHE

    try:

        if not os.path.exists(
            CACHE_FILE
        ):
            return

        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict
        ):

            with CACHE_LOCK:
                CACHE = data

        print(
            "Bybit cache loaded:",
            len(CACHE)
        )

    except Exception as e:

        print(
            "Cache load error:",
            e
        )


# ============================================================
# SAVE CACHE
# ============================================================

def save_cache():

    try:

        with CACHE_LOCK:
            data = dict(CACHE)

        tmp = (
            CACHE_FILE
            + ".tmp"
        )

        with open(
            tmp,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False
            )

        os.replace(
            tmp,
            CACHE_FILE
        )

    except Exception as e:

        print(
            "Cache save error:",
            e
        )


# ============================================================
# BYBIT GET
# ============================================================

def bybit_get(
    path,
    params=None,
    timeout=None
):

    global LAST_REQUEST

    if timeout is None:
        timeout = BYBIT_TIMEOUT

    last_error = (
        "تعذر الاتصال بـ Bybit"
    )

    try:

        with CACHE_LOCK:

            elapsed = (
                time.time()
                - LAST_REQUEST
            )

        if elapsed < REQUEST_DELAY:

            time.sleep(
                REQUEST_DELAY
                - elapsed
            )

        response = HTTP.get(
            BYBIT_BASE_URL + path,
            params=params or {},
            timeout=timeout
        )

        with CACHE_LOCK:

            LAST_REQUEST = time.time()

        if response.status_code == 200:

            data = response.json()

            if data.get(
                "retCode"
            ) == 0:

                return data

            last_error = str(
                data.get(
                    "retMsg",
                    "Bybit API error"
                )
            )

        elif response.status_code == 429:

            time.sleep(2)

            last_error = (
                "Bybit HTTP 429"
            )

        else:

            last_error = (
                f"Bybit HTTP "
                f"{response.status_code}"
            )

    except Exception as e:

        last_error = str(e)

    raise RuntimeError(
        last_error
    )


# ============================================================
# BYBIT INSTRUMENTS
# ============================================================

def get_bybit_instruments():

    now = time.time()

    with CACHE_LOCK:

        if (
            US_INSTRUMENT_CACHE["data"]
            and
            now -
            US_INSTRUMENT_CACHE["ts"]
            <
            CACHE_TTL
        ):

            return (
                US_INSTRUMENT_CACHE["data"]
            )

    all_items = []

    cursor = None

    while True:

        params = {
            "category":
                "linear",

            "status":
                "Trading",

            "limit":
                1000
        }

        if cursor:

            params["cursor"] = cursor

        data = bybit_get(
            "/v5/market/instruments-info",
            params,
            timeout=10
        )

        result = data.get(
            "result",
            {}
        )

        items = result.get(
            "list",
            []
        )

        for item in items:

            market_region = str(
                item.get(
                    "marketRegion",
                    ""
                )
            ).upper()

            symbol_type = str(
                item.get(
                    "symbolType",
                    ""
                )
            ).lower()

            # ----------------------------------------
            # US TradFi
            # ----------------------------------------

            if (
                market_region == "US"
                or
                symbol_type == "stock"
            ):

                all_items.append({

                    "symbol":
                        item.get(
                            "symbol",
                            ""
                        ),

                    "symbolType":
                        item.get(
                            "symbolType",
                            ""
                        ),

                    "marketRegion":
                        market_region,

                    "underlyingTicker":
                        item.get(
                            "underlyingTicker",
                            ""
                        ),

                    "fullName":
                        item.get(
                            "fullName",
                            ""
                        ),

                    "baseCoin":
                        item.get(
                            "baseCoin",
                            ""
                        ),

                    "quoteCoin":
                        item.get(
                            "quoteCoin",
                            ""
                        ),

                    "status":
                        item.get(
                            "status",
                            ""
                        ),

                    "leverageFilter":
                        item.get(
                            "leverageFilter",
                            {}
                        ),

                    "launchTime":
                        item.get(
                            "launchTime"
                        ),

                    "deliveryTime":
                        item.get(
                            "deliveryTime"
                        )
                })

        cursor = result.get(
            "nextPageCursor"
        )

        if not cursor:
            break

        if not items:
            break

    # Remove duplicates

    unique = {}

    for item in all_items:

        symbol = item.get(
            "symbol",
            ""
        )

        if symbol:

            unique[symbol] = item

    result = list(
        unique.values()
    )

    with CACHE_LOCK:

        US_INSTRUMENT_CACHE.update({
            "ts":
                time.time(),

            "data":
                result
        })

    return result


# ============================================================
# BYBIT TICKERS
# ============================================================

def get_bybit_tickers():

    now = time.time()

    with CACHE_LOCK:

        if (
            TICKER_CACHE["data"]
            and
            now -
            TICKER_CACHE["ts"]
            <
            CACHE_TTL
        ):

            return (
                TICKER_CACHE["data"]
            )

    data = bybit_get(
        "/v5/market/tickers",
        {
            "category":
                "linear"
        },
        timeout=10
    )

    items = (
        data
        .get("result", {})
        .get("list", [])
    )

    with CACHE_LOCK:

        TICKER_CACHE.update({

            "ts":
                time.time(),

            "data":
                items
        })

    return items


# ============================================================
# US MARKET
# ============================================================

def get_us_market():

    instruments = (
        get_bybit_instruments()
    )

    tickers = (
        get_bybit_tickers()
    )

    ticker_map = {}

    for ticker in tickers:

        symbol = str(
            ticker.get(
                "symbol",
                ""
            )
        ).upper()

        if symbol:

            ticker_map[
                symbol
            ] = ticker

    result = []

    for item in instruments:

        symbol = item.get(
            "symbol",
            ""
        )

        ticker = ticker_map.get(
            symbol,
            {}
        )

        try:

            price = float(
                ticker.get(
                    "lastPrice",
                    0
                )
            )

        except Exception:

            price = 0.0

        try:

            change = float(
                ticker.get(
                    "price24hPcnt",
                    0
                )
            ) * 100

        except Exception:

            change = 0.0

        try:

            volume = float(
                ticker.get(
                    "turnover24h",
                    0
                )
            )

        except Exception:

            volume = 0.0

        result.append({

            **item,

            "price":
                price,

            "change":
                change,

            "volume":
                volume,

            "market":
                "US",

            "source":
                "Bybit"
        })

    result.sort(
        key=lambda x:
            x.get(
                "volume",
                0
            ),
        reverse=True
    )

    return result


# ============================================================
# US PRICE
# ============================================================

def get_us_price(
    symbol
):

    symbol = symbol.upper()

    market = get_us_market()

    for item in market:

        if (
            item.get(
                "symbol"
            )
            ==
            symbol
        ):

            return item

    raise RuntimeError(
        "الأداة غير موجودة في Bybit"
    )


# ============================================================
# US KLINES
# ============================================================

def get_us_klines(
    symbol,
    interval="15m",
    limit=230
):

    symbol = symbol.upper()

    bybit_interval = (
        INTERVALS.get(
            interval
        )
    )

    if not bybit_interval:

        raise RuntimeError(
            "الفريم غير مدعوم"
        )

    key = (
        "US:"
        + symbol
        + ":"
        + interval
    )

    now = time.time()

    with CACHE_LOCK:

        cached = CACHE.get(
            key
        )

    if cached:

        cached_ts = float(
            cached.get(
                "ts",
                0
            )
        )

        candles = cached.get(
            "klines",
            []
        )

        if (
            candles
            and
            now -
            cached_ts
            <
            KLINE_CACHE_TTL
        ):

            return (
                candles,
                True
            )

    data = bybit_get(
        "/v5/market/kline",
        {
            "category":
                "linear",

            "symbol":
                symbol,

            "interval":
                bybit_interval,

            "limit":
                min(
                    int(limit),
                    1000
                )
        },
        timeout=10
    )

    rows = (
        data
        .get("result", {})
        .get("list", [])
    )

    # Bybit returns newest first.

    rows.reverse()

    candles = []

    for row in rows:

        if len(row) < 6:
            continue

        candles.append({

            "t":
                int(row[0]),

            "o":
                float(row[1]),

            "h":
                float(row[2]),

            "l":
                float(row[3]),

            "c":
                float(row[4]),

            "v":
                float(row[5]),

            "turnover":
                float(row[6])
                if len(row) > 6
                else 0.0
        })

    with CACHE_LOCK:

        CACHE[key] = {

            "ts":
                time.time(),

            "klines":
                candles
        }

    save_cache()

    return (
        candles,
        False
    )


# ============================================================
# TECHNICAL ANALYSIS
# ============================================================

def ema(
    values,
    period
):

    if not values:
        return None

    period = min(
        period,
        len(values)
    )

    seed = (
        sum(
            values[:period]
        )
        /
        period
    )

    result = seed

    multiplier = (
        2
        /
        (period + 1)
    )

    for value in values[period:]:

        result = (
            value
            *
            multiplier
            +
            result
            *
            (
                1
                -
                multiplier
            )
        )

    return result


def rsi(
    values,
    period=14
):

    if len(values) <= period:

        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            -
            values[i - 1]
        )

        gains.append(
            max(
                diff,
                0
            )
        )

        losses.append(
            max(
                -diff,
                0
            )
        )

    avg_gain = (
        sum(
            gains[:period]
        )
        /
        period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                *
                (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                *
                (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:

        return 100.0

    rs = (
        avg_gain
        /
        avg_loss
    )

    return (
        100
        -
        (
            100
            /
            (1 + rs)
        )
    )


def atr(
    candles,
    period=14
):

    if len(candles) < 2:

        return 0.0

    true_ranges = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]

        previous = candles[i - 1]

        high = current["h"]

        low = current["l"]

        previous_close = previous["c"]

        tr = max(

            high - low,

            abs(
                high
                -
                previous_close
            ),

            abs(
                low
                -
                previous_close
            )
        )

        true_ranges.append(
            tr
        )

    if not true_ranges:

        return 0.0

    selected = true_ranges[
        -period:
    ]

    return (
        sum(selected)
        /
        len(selected)
    )


def analyze_us(
    candles
):

    if not candles:

        raise RuntimeError(
            "لا توجد شموع"
        )

    closes = [
        x["c"]
        for x in candles
    ]

    highs = [
        x["h"]
        for x in candles
    ]

    lows = [
        x["l"]
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

    current_rsi = rsi(
        closes,
        14
    )

    score = 50

    reasons = []

    if (
        ema20 is not None
        and
        price > ema20
    ):

        score += 10

        reasons.append(
            "السعر فوق EMA20"
        )

    else:

        score -= 10

        reasons.append(
            "السعر تحت EMA20"
        )

    if (
        ema50 is not None
        and
        price > ema50
    ):

        score += 10

        reasons.append(
            "السعر فوق EMA50"
        )

    else:

        score -= 10

        reasons.append(
            "السعر تحت EMA50"
        )

    if (
        ema200 is not None
        and
        price > ema200
    ):

        score += 10

        reasons.append(
            "السعر فوق EMA200"
        )

    else:

        score -= 10

        reasons.append(
            "السعر تحت EMA200"
        )

    if 50 <= current_rsi <= 70:

        score += 10

        reasons.append(
            "RSI إيجابي"
        )

    elif current_rsi > 70:

        score += 3

        reasons.append(
            "RSI مرتفع"
        )

    elif current_rsi < 30:

        score += 3

        reasons.append(
            "RSI منخفض"
        )

    else:

        score -= 5

        reasons.append(
            "RSI محايد"
        )

    score = max(
        0,
        min(
            100,
            score
        )
    )

    if score >= 80:

        signal = "شراء قوي"

        direction = "buy"

    elif score >= 65:

        signal = "شراء"

        direction = "buy"

    elif score <= 20:

        signal = "بيع قوي"

        direction = "sell"

    elif score <= 35:

        signal = "بيع"

        direction = "sell"

    else:

        signal = "حيادي"

        direction = "neutral"

    current_atr = atr(
        candles,
        14
    )

    risk = max(
        current_atr * 1.5,
        price * 0.01
    )

    if direction == "buy":

        sl = max(
            price - risk,
            0
        )

        tp1 = (
            price
            +
            risk * 1.5
        )

        tp2 = (
            price
            +
            risk * 2
        )

        tp3 = (
            price
            +
            risk * 3
        )

    elif direction == "sell":

        sl = (
            price
            +
            risk
        )

        tp1 = max(
            price
            -
            risk * 1.5,
            0
        )

        tp2 = max(
            price
            -
            risk * 2,
            0
        )

        tp3 = max(
            price
            -
            risk * 3,
            0
        )

    else:

        sl = None

        tp1 = None

        tp2 = None

        tp3 = None

    return {

        "signal":
            signal,

        "direction":
            direction,

        "score":
            score,

        "score10":
            round(
                score / 10,
                1
            ),

        "price":
            price,

        "entry":
            price,

        "tp1":
            tp1,

        "tp2":
            tp2,

        "tp3":
            tp3,

        "sl":
            sl,

        "rsi":
            current_rsi,

        "ema20":
            ema20,

        "ema50":
            ema50,

        "ema200":
            ema200,

        "atr":
            current_atr,

        "support":
            min(
                lows[-20:]
            ),

        "resistance":
            max(
                highs[-20:]
            ),

        "reasons":
            reasons,

        "candles":
            candles[-100:]
    }


# ============================================================
# US ANALYSIS
# ============================================================

def us_analysis(
    symbol,
    interval="15m"
):

    candles, cached = (
        get_us_klines(
            symbol,
            interval
        )
    )

    result = analyze_us(
        candles
    )

    market = get_us_price(
        symbol
    )

    result.update({

        "symbol":
            symbol.upper(),

        "market":
            "US",

        "source":
            "Bybit",

        "cached":
            cached,

        "name":
            market.get(
                "fullName",
                ""
            ),

        "underlyingTicker":
            market.get(
                "underlyingTicker",
                ""
            ),

        "change":
            market.get(
                "change",
                0
            ),

        "volume":
            market.get(
                "volume",
                0
            ),

        "updatedAt":
            int(
                time.time()
                * 1000
            )
    })

    return result


# ============================================================
# US SCAN
# ============================================================

def scan_us(
    interval="15m",
    limit=40
):

    market = get_us_market()

    selected = market[
        :max(
            1,
            min(
                int(limit),
                40
            )
        )
    ]

    results = []

    # Sequential scan

    for item in selected:

        symbol = item.get(
            "symbol"
        )

        if not symbol:

            continue

        try:

            analysis = us_analysis(
                symbol,
                interval
            )

            results.append(
                analysis
            )

        except Exception as e:

            print(
                "US scan error:",
                symbol,
                e
            )

            continue

    return {

        "ok":
            True,

        "market":
            "US",

        "source":
            "Bybit",

        "interval":
            interval,

        "count":
            len(results),

        "results":
            results
    }


# ============================================================
# SAUDI MARKET
# ============================================================

def get_saudi_market():

    """
    السوق السعودي.

    ما نستخدم بيانات وهمية.

    لازم تحدد SAUDI_MARKET_URL
    في Render Environment Variables
    إذا عندك API سعودي موثوق.

    نتوقع JSON قريب من:

    {
        "results": [
            {
                "symbol": "2222",
                "name": "أرامكو",
                "price": 25.50,
                "change": 1.20,
                "volume": 1234567
            }
        ]
    }

    أو:

    {
        "data": [...]
    }
    """

    if not SAUDI_MARKET_URL:

        return {

            "ok":
                False,

            "market":
                "SA",

            "source":
                "Saudi Market",

            "configured":
                False,

            "message":
                "لم يتم ضبط SAUDI_MARKET_URL"
        }

    try:

        response = requests.get(
            SAUDI_MARKET_URL,
            timeout=SAUDI_TIMEOUT,
            headers={
                "User-Agent":
                    "Mudarib-Abo-Saud/1.0",
                "Accept":
                    "application/json"
            }
        )

        response.raise_for_status()

        data = response.json()

        if isinstance(
            data,
            list
        ):

            items = data

        elif isinstance(
            data,
            dict
        ):

            items = (
                data.get(
                    "results"
                )
                or
                data.get(
                    "data"
                )
                or
                data.get(
                    "items"
                )
                or
                []
            )

        else:

            items = []

        result = []

        for item in items:

            if not isinstance(
                item,
                dict
            ):

                continue

            symbol = str(
                item.get(
                    "symbol"
                    ,
                    item.get(
                        "ticker",
                        ""
                    )
                )
            )

            name = str(
                item.get(
                    "name",
                    item.get(
                        "company",
                        ""
                    )
                )
            )

            try:

                price = float(
                    item.get(
                        "price",
                        0
                    )
                )

            except Exception:

                price = 0.0

            try:

                change = float(
                    item.get(
                        "change",
                        item.get(
                            "changePercent",
                            0
                        )
                    )
                )

            except Exception:

                change = 0.0

            try:

                volume = float(
                    item.get(
                        "volume",
                        0
                    )
                )

            except Exception:

                volume = 0.0

            result.append({

                "symbol":
                    symbol,

                "name":
                    name,

                "price":
                    price,

                "change":
                    change,

                "volume":
                    volume,

                "market":
                    "SA",

                "source":
                    "Saudi Market"
            })

        return {

            "ok":
                True,

            "market":
                "SA",

            "source":
                "Saudi Market",

            "configured":
                True,

            "count":
                len(result),

            "results":
                result
        }

    except Exception as e:

        return {

            "ok":
                False,

            "market":
                "SA",

            "source":
                "Saudi Market",

            "configured":
                True,

            "message":
                str(e)
        }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({

        "ok":
            True,

        "service":
            "bybit_service",

        "bybit":
            True,

        "us":
            True,

        "saudi":
            bool(
                SAUDI_MARKET_URL
            ),

        "cache":
            len(CACHE),

        "time":
            int(
                time.time()
            )
    })


# ============================================================
# US SYMBOLS
# ============================================================

@app.get("/us/symbols")
def us_symbols():

    try:

        data = (
            get_bybit_instruments()
        )

        return jsonify({

            "ok":
                True,

            "market":
                "US",

            "source":
                "Bybit",

            "count":
                len(data),

            "symbols":
                data
        })

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# US MARKET
# ============================================================

@app.get("/us/market")
def us_market():

    try:

        data = get_us_market()

        return jsonify({

            "ok":
                True,

            "market":
                "US",

            "source":
                "Bybit",

            "count":
                len(data),

            "results":
                data
        })

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# US PRICE
# ============================================================

@app.get("/us/price")
def us_price():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    if not symbol:

        return jsonify({

            "ok":
                False,

            "message":
                "symbol مطلوب"

        }), 400

    try:

        return jsonify({

            "ok":
                True,

            **get_us_price(
                symbol
            ),

            "market":
                "US",

            "source":
                "Bybit"
        })

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# US KLINES
# ============================================================

@app.get("/us/klines")
def us_klines():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if not symbol:

        return jsonify({

            "ok":
                False,

            "message":
                "symbol مطلوب"

        }), 400

    try:

        candles, cached = (
            get_us_klines(
                symbol,
                interval
            )
        )

        return jsonify({

            "ok":
                True,

            "market":
                "US",

            "source":
                "Bybit",

            "symbol":
                symbol,

            "interval":
                interval,

            "cached":
                cached,

            "klines":
                candles
        })

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# US ANALYSIS
# ============================================================

@app.get("/us/analysis")
def us_analysis_route():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()

    interval = request.args.get(
        "interval",
        "15m"
    )

    if not symbol:

        return jsonify({

            "ok":
                False,

            "message":
                "symbol مطلوب"

        }), 400

    if interval not in INTERVALS:

        return jsonify({

            "ok":
                False,

            "message":
                "الفريم غير صحيح"

        }), 400

    try:

        result = us_analysis(
            symbol,
            interval
        )

        return jsonify({

            "ok":
                True,

            **result
        })

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# US SCAN
# ============================================================

@app.get("/us/scan")
def us_scan_route():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        limit = int(
            request.args.get(
                "limit",
                40
            )
        )

    except Exception:

        limit = 40

    if interval not in INTERVALS:

        return jsonify({

            "ok":
                False,

            "message":
                "الفريم غير صحيح"

        }), 400

    try:

        return jsonify(
            scan_us(
                interval,
                limit
            )
        )

    except Exception as e:

        return jsonify({

            "ok":
                False,

            "message":
                str(e)

        }), 503


# ============================================================
# SAUDI MARKET
# ============================================================

@app.get("/saudi/market")
def saudi_market():

    return jsonify(
        get_saudi_market()
    )


# ============================================================
# COMBINED MARKET
# ============================================================

@app.get("/markets")
def markets():

    try:

        us = get_us_market()

    except Exception as e:

        us = []

        print(
            "US market error:",
            e
        )

    saudi = (
        get_saudi_market()
    )

    return jsonify({

        "ok":
            True,

        "us": {

            "market":
                "US",

            "source":
                "Bybit",

            "count":
                len(us),

            "results":
                us
        },

        "saudi":
            saudi,

        "updatedAt":
            int(
                time.time()
                * 1000
            )
    })


# ============================================================
# COMBINED SCAN
# ============================================================

@app.get("/scan")
def combined_scan():

    interval = request.args.get(
        "interval",
        "15m"
    )

    try:

        limit = int(
            request.args.get(
                "limit",
                40
            )
        )

    except Exception:

        limit = 40

    if interval not in INTERVALS:

        return jsonify({

            "ok":
                False,

            "message":
                "الفريم غير صحيح"

        }), 400

    try:

        us = scan_us(
            interval,
            limit
        )

    except Exception as e:

        us = {

            "ok":
                False,

            "market":
                "US",

            "source":
                "Bybit",

            "results":
                [],

            "message":
                str(e)
        }

    saudi = (
        get_saudi_market()
    )

    return jsonify({

        "ok":
            True,

        "interval":
            interval,

        "us":
            us,

        "saudi":
            saudi,

        "updatedAt":
            int(
                time.time()
                * 1000
            )
    })


# ============================================================
# CACHE
# ============================================================

@app.get("/cache")
def cache_status():

    with CACHE_LOCK:

        keys = list(
            CACHE.keys()
        )

    return jsonify({

        "ok":
            True,

        "count":
            len(keys),

        "keys":
            keys[:200]
    })


# ============================================================
# STARTUP
# ============================================================

load_cache()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10001"
            )
        ),
        debug=False
    )
