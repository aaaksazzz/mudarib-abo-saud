import os
import time
import math
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from flask import Flask, jsonify
from flask_cors import CORS


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": "*"
        }
    }
)


# ============================================================
# SETTINGS
# ============================================================

CACHE_SECONDS = int(
    os.getenv("CACHE_SECONDS", "1800")
)

HISTORY_PERIOD = os.getenv(
    "HISTORY_PERIOD",
    "1y"
)

INTERVAL = os.getenv(
    "INTERVAL",
    "1d"
)

MAX_STOCKS = int(
    os.getenv("MAX_STOCKS", "120")
)


# ============================================================
# SAUDI MARKET
# ============================================================
#
# Tadawul / Saudi Exchange symbols.
#
# Yahoo Finance uses the .SR suffix.
#
# Example:
# 2222.SR = Saudi Aramco
#
# The list can be expanded later without changing
# the frontend.
# ============================================================

SAUDI_STOCKS = [
    ("1010.SR", "الرياض"),
    ("1020.SR", "الجزيرة"),
    ("1030.SR", "الاستثمار"),
    ("1050.SR", "الإنماء"),
    ("1060.SR", "ساب"),
    ("1080.SR", "العربي"),
    ("1120.SR", "الراجحي"),
    ("1140.SR", "البلاد"),
    ("1150.SR", "الإنماء"),
    ("1180.SR", "الأهلي السعودي"),
    ("1182.SR", "مصرف الراجحي"),
    ("2010.SR", "سابك"),
    ("2020.SR", "سابك للمغذيات"),
    ("2030.SR", "المصافي"),
    ("2040.SR", "الخزف"),
    ("2050.SR", "صناعات كهربائية"),
    ("2060.SR", "التصنيع"),
    ("2070.SR", "الدوائية"),
    ("2080.SR", "الغاز"),
    ("2090.SR", "الجبس"),
    ("2100.SR", "وفرة"),
    ("2110.SR", "الكابلات"),
    ("2120.SR", "متطورة"),
    ("2130.SR", "صدق"),
    ("2140.SR", "أيان"),
    ("2150.SR", "زجاج"),
    ("2160.SR", "أميانتيت"),
    ("2170.SR", "اللجين"),
    ("2180.SR", "فيبكو"),
    ("2190.SR", "سيسكو"),
    ("2200.SR", "أنابيب"),
    ("2210.SR", "نماء"),
    ("2220.SR", "معدنية"),
    ("2222.SR", "أرامكو"),
    ("2230.SR", "الكيميائية"),
    ("2240.SR", "الزامل"),
    ("2250.SR", "المجموعة السعودية"),
    ("2270.SR", "سدافكو"),
    ("2280.SR", "المراعي"),
    ("2290.SR", "ينساب"),
    ("2300.SR", "صناعة الورق"),
    ("2310.SR", "سبكيم"),
    ("2320.SR", "البابطين"),
    ("2330.SR", "المتقدمة"),
    ("2350.SR", "كيان"),
    ("2360.SR", "الفخارية"),
    ("2370.SR", "مسك"),
    ("2380.SR", "بترو رابغ"),
    ("2381.SR", "الحبيب"),
    ("2382.SR", "الحبيب الطبية"),
    ("3002.SR", "أسمنت نجران"),
    ("3003.SR", "أسمنت المدينة"),
    ("3004.SR", "أسمنت الشمالية"),
    ("3005.SR", "أسمنت أم القرى"),
    ("3007.SR", "أسمنت الجنوب"),
    ("3008.SR", "أسمنت السعودية"),
    ("3010.SR", "أسمنت العربية"),
    ("3020.SR", "أسمنت اليمامة"),
    ("3030.SR", "أسمنت السعودية"),
    ("3040.SR", "أسمنت القصيم"),
    ("3050.SR", "أسمنت ينبع"),
    ("3060.SR", "أسمنت تبوك"),
    ("3080.SR", "أسمنت الشرقية"),
    ("3090.SR", "أسمنت الجوف"),
    ("3091.SR", "أسمنت الرياض"),
    ("4001.SR", "أسواق العثيم"),
    ("4002.SR", "المواساة"),
    ("4003.SR", "إكسترا"),
    ("4004.SR", "دله الصحية"),
    ("4005.SR", "رعاية"),
    ("4007.SR", "الحمادي"),
    ("4008.SR", "ساكو"),
    ("4013.SR", "سليمان الحبيب"),
    ("4014.SR", "دار المعدات"),
    ("4015.SR", "جمجوم فارما"),
    ("4016.SR", "أفالون فارما"),
    ("4020.SR", "العقارية"),
    ("4030.SR", "البحري"),
    ("4031.SR", "الخدمات الأرضية"),
    ("4040.SR", "سابتكو"),
    ("4050.SR", "ساسكو"),
    ("4061.SR", "أنابيب الشرق"),
    ("4071.SR", "العربية للأنابيب"),
    ("4072.SR", "مجموعة تداول"),
    ("4080.SR", "العربية"),
    ("4090.SR", "طيبة"),
    ("4100.SR", "مكة"),
    ("4110.SR", "باتك"),
    ("4130.SR", "الباحة"),
    ("4140.SR", "صادرات"),
    ("4141.SR", "العمران"),
    ("4142.SR", "كابلات الرياض"),
    ("4150.SR", "التعمير"),
    ("4160.SR", "ثمار"),
    ("4161.SR", "جاهز"),
    ("4170.SR", "شمس"),
    ("4180.SR", "مجموعة فتيحي"),
    ("4190.SR", "جرير"),
    ("4191.SR", "أبو معطي"),
    ("4192.SR", "السيف غاليري"),
    ("4193.SR", "نايس ون"),
    ("4200.SR", "الدريس"),
    ("4210.SR", "الأبحاث والإعلام"),
    ("4220.SR", "إعمار"),
    ("4230.SR", "البحر الأحمر"),
    ("4240.SR", "الحكير"),
    ("4260.SR", "بدجت السعودية"),
    ("4261.SR", "ذيب"),
    ("4262.SR", "لومي"),
    ("4263.SR", "سال"),
    ("4264.SR", "طيران ناس"),
    ("4270.SR", "طباعة وتغليف"),
    ("4280.SR", "المملكة"),
    ("4290.SR", "الخدمات الأرضية"),
    ("4300.SR", "دار الأركان"),
    ("4310.SR", "مدينة المعرفة"),
    ("4320.SR", "الأندلس"),
    ("4321.SR", "المراكز العربية"),
    ("4322.SR", "رتال"),
    ("4323.SR", "سمو"),
    ("4330.SR", "الرياض للتعمير"),
    ("4331.SR", "مدينة المعرفة"),
    ("4333.SR", "المعذر"),
    ("4340.SR", "العبداللطيف"),
    ("4342.SR", "جدوى ريت"),
    ("4344.SR", "سويكورب"),
    ("4345.SR", "الراجحي ريت"),
    ("4346.SR", "مشاركة ريت"),
    ("4347.SR", "بنيان ريت"),
    ("4348.SR", "الخبير ريت"),
    ("4349.SR", "ملكية ريت"),
    ("5110.SR", "السعودي الفرنسي"),
    ("6001.SR", "حلواني إخوان"),
    ("6010.SR", "نادك"),
    ("6020.SR", "جاكو"),
    ("6040.SR", "تبوك الزراعية"),
    ("6050.SR", "الأسماك"),
    ("6060.SR", "الشرقية للتنمية"),
    ("6070.SR", "الجوف الزراعية"),
    ("6090.SR", "جازادكو"),
    ("7010.SR", "اتصالات السعودية"),
    ("7020.SR", "اتحاد اتصالات"),
    ("7030.SR", "زين السعودية"),
    ("7040.SR", "عذيب"),
    ("7200.SR", "الدوائية الرقمية"),
    ("7201.SR", "بحر العرب"),
    ("7202.SR", "سلوشنز"),
    ("7203.SR", "علم"),
    ("7204.SR", "توبي"),
    ("8010.SR", "التعاونية"),
    ("8012.SR", "جزيرة تكافل"),
    ("8020.SR", "ملاذ للتأمين"),
    ("8030.SR", "ميدغلف"),
    ("8040.SR", "أليانز السعودي الفرنسي"),
    ("8050.SR", "سلامة"),
    ("8060.SR", "ولاء"),
    ("8070.SR", "الدرع العربي"),
    ("8100.SR", "سايكو"),
    ("8120.SR", "اتحاد الخليج"),
    ("8150.SR", "أسيج"),
    ("8160.SR", "التأمين العربية"),
    ("8170.SR", "الاتحاد للتأمين"),
    ("8180.SR", "الصقر للتأمين"),
    ("8190.SR", "المتحدة للتأمين"),
    ("8200.SR", "الإعادة السعودية"),
    ("8210.SR", "بوبا العربية"),
    ("8230.SR", "تكافل الراجحي"),
    ("8240.SR", "تشب العربية"),
    ("8250.SR", "جبل عمر"),
    ("8260.SR", "الخليجية العامة"),
    ("8270.SR", "بروج للتأمين"),
    ("8280.SR", "العالمية"),
    ("8300.SR", "الوطنية للتأمين"),
]


# ============================================================
# CACHE
# ============================================================

cache = {
    "signals": [],
    "updated_at": None,
    "error": None
}

cache_lock = threading.Lock()


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=0.0):

    try:

        if value is None:
            return default

        value = float(value)

        if not math.isfinite(value):
            return default

        return value

    except Exception:

        return default


def clean_symbol(symbol):

    symbol = str(symbol or "").strip().upper()

    if not symbol:
        return ""

    if symbol.endswith(".SR"):
        return symbol

    if symbol.isdigit():
        return f"{symbol}.SR"

    return symbol


def round_value(value):

    value = safe_float(value)

    if value == 0:
        return 0

    if abs(value) >= 100:
        return round(value, 2)

    if abs(value) >= 1:
        return round(value, 3)

    return round(value, 4)


# ============================================================
# INDICATORS
# ============================================================

def calculate_rsi(close, period=14):

    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi.fillna(50)


def add_indicators(df):

    df = df.copy()

    df["EMA20"] = (
        df["Close"]
        .ewm(span=20, adjust=False)
        .mean()
    )

    df["EMA50"] = (
        df["Close"]
        .ewm(span=50, adjust=False)
        .mean()
    )

    df["EMA200"] = (
        df["Close"]
        .ewm(span=200, adjust=False)
        .mean()
    )

    df["RSI"] = calculate_rsi(
        df["Close"],
        14
    )

    df["VOL_AVG20"] = (
        df["Volume"]
        .rolling(20)
        .mean()
    )

    return df


# ============================================================
# ANALYSIS
# ============================================================

def analyze_dataframe(df, symbol, name):

    if df is None or df.empty:
        return None

    df = df.dropna(
        subset=["Close"]
    ).copy()

    if len(df) < 60:
        return None

    df = add_indicators(df)

    last = df.iloc[-1]

    close = safe_float(
        last["Close"]
    )

    previous_close = safe_float(
        df["Close"].iloc[-2]
    )

    ema20 = safe_float(
        last["EMA20"]
    )

    ema50 = safe_float(
        last["EMA50"]
    )

    ema200 = safe_float(
        last["EMA200"]
    )

    rsi = safe_float(
        last["RSI"],
        50
    )

    volume = safe_float(
        last["Volume"]
    )

    volume_avg = safe_float(
        last["VOL_AVG20"]
    )

    change = 0

    if previous_close:
        change = (
            (close - previous_close)
            / previous_close
        ) * 100

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 50
    reasons = []

    # Trend
    if close > ema200:

        score += 15

        reasons.append(
            "السعر فوق EMA200"
        )

    else:

        score -= 15

        reasons.append(
            "السعر تحت EMA200"
        )

    # EMA20 / EMA50
    if ema20 > ema50:

        score += 10

        reasons.append(
            "EMA20 فوق EMA50"
        )

    else:

        score -= 10

        reasons.append(
            "EMA20 تحت EMA50"
        )

    # RSI
    if 50 <= rsi <= 70:

        score += 10

        reasons.append(
            "RSI يدعم الاتجاه الصاعد"
        )

    elif rsi > 70:

        score -= 3

        reasons.append(
            "RSI مرتفع"
        )

    elif rsi < 35:

        score += 3

        reasons.append(
            "السهم في منطقة تشبع بيعي"
        )

    else:

        score -= 3

        reasons.append(
            "RSI ضعيف"
        )

    # Volume
    if volume_avg > 0:

        volume_ratio = (
            volume / volume_avg
        )

        if volume_ratio >= 1.5:

            score += 10

            reasons.append(
                "حجم التداول أعلى من المتوسط"
            )

        elif volume_ratio >= 1.0:

            score += 5

            reasons.append(
                "حجم التداول طبيعي"
            )

        else:

            score -= 3

            reasons.append(
                "حجم التداول أقل من المتوسط"
            )

    # Daily movement
    if change > 2:

        score += 5

        reasons.append(
            "زخم صاعد"
        )

    elif change < -2:

        score -= 5

        reasons.append(
            "ضغط بيعي"
        )

    score = max(
        0,
        min(100, int(round(score)))
    )

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if score >= 80:

        signal = "شراء قوي"

    elif score >= 65:

        signal = "شراء"

    elif score <= 30:

        signal = "بيع قوي"

    elif score <= 45:

        signal = "بيع"

    else:

        signal = "حيادي"

    # --------------------------------------------------------
    # LEVELS
    # --------------------------------------------------------

    entry = close

    if signal in ("شراء", "شراء قوي"):

        tp1 = close * 1.03
        tp2 = close * 1.06
        sl = close * 0.97

    elif signal in ("بيع", "بيع قوي"):

        tp1 = close * 0.97
        tp2 = close * 0.94
        sl = close * 1.03

    else:

        tp1 = close * 1.02
        tp2 = close * 1.04
        sl = close * 0.98

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {
        "symbol": symbol.replace(".SR", ""),
        "ticker": symbol,
        "name": name,

        "price": round_value(close),
        "change": round(change, 2),

        "signal": signal,
        "score10": round(score / 10, 1),
        "score": score,

        "entry": round_value(entry),
        "tp1": round_value(tp1),
        "tp2": round_value(tp2),
        "sl": round_value(sl),

        "rsi": round(rsi, 2),
        "ema20": round_value(ema20),
        "ema50": round_value(ema50),
        "ema200": round_value(ema200),

        "volume": int(
            safe_float(volume)
        ),

        "volumeAvg20": int(
            safe_float(volume_avg)
        ),

        "reasons": reasons
    }


# ============================================================
# DOWNLOAD ONE STOCK
# ============================================================

def download_stock(symbol, name):

    try:

        ticker = yf.Ticker(symbol)

        df = ticker.history(
            period=HISTORY_PERIOD,
            interval=INTERVAL,
            auto_adjust=False
        )

        if df is None or df.empty:
            return None

        return analyze_dataframe(
            df,
            symbol,
            name
        )

    except Exception as e:

        print(
            f"[SAUDI] {symbol} ERROR: {e}",
            flush=True
        )

        return None


# ============================================================
# BUILD MARKET SIGNALS
# ============================================================

def build_signals():

    print(
        "[SAUDI] Starting market analysis...",
        flush=True
    )

    results = []

    stocks = SAUDI_STOCKS[
        :MAX_STOCKS
    ]

    for index, (symbol, name) in enumerate(stocks, 1):

        print(
            f"[SAUDI] {index}/{len(stocks)} {symbol}",
            flush=True
        )

        result = download_stock(
            symbol,
            name
        )

        if result:

            results.append(result)

        # Small pause to reduce pressure
        # on the data provider.
        time.sleep(0.15)

    # --------------------------------------------------------
    # Sort:
    # strong buys first, then buys, neutral, sells
    # --------------------------------------------------------

    rank = {
        "شراء قوي": 5,
        "شراء": 4,
        "حيادي": 3,
        "بيع": 2,
        "بيع قوي": 1
    }

    results.sort(
        key=lambda x: (
            rank.get(
                x["signal"],
                3
            ),
            x.get("score", 0),
            x.get("change", 0)
        ),
        reverse=True
    )

    print(
        f"[SAUDI] Analysis completed: {len(results)} stocks",
        flush=True
    )

    return results


# ============================================================
# CACHE REFRESH
# ============================================================

def get_signals(force=False):

    now = time.time()

    with cache_lock:

        updated = cache["updated_at"]

        if (
            not force
            and updated
            and now - updated < CACHE_SECONDS
            and cache["signals"]
        ):

            return (
                cache["signals"],
                True,
                cache["error"]
            )

    # Build outside lock
    try:

        results = build_signals()

        with cache_lock:

            cache["signals"] = results
            cache["updated_at"] = time.time()
            cache["error"] = None

        return (
            results,
            False,
            None
        )

    except Exception as e:

        print(
            f"[SAUDI] CACHE ERROR: {e}",
            flush=True
        )

        with cache_lock:

            cache["error"] = str(e)

            old = cache["signals"]

        if old:

            return (
                old,
                True,
                str(e)
            )

        return (
            [],
            False,
            str(e)
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    with cache_lock:

        updated = cache["updated_at"]
        count = len(
            cache["signals"]
        )
        error = cache["error"]

    return jsonify({

        "ok": True,

        "service": "saudi-market",

        "market": "Tadawul / Saudi Exchange",

        "stocks": count,

        "cacheSeconds": CACHE_SECONDS,

        "updatedAt":
            datetime.fromtimestamp(
                updated,
                tz=timezone.utc
            ).isoformat()
            if updated
            else None,

        "error": error

    })


# ============================================================
# MARKET
# ============================================================

@app.get("/api/market")
def market():

    signals, cached, error = get_signals()

    return jsonify({

        "ok": True,

        "market": "السوق السعودي",

        "signals": signals,

        "count": len(signals),

        "cached": cached,

        "error": error,

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat()

    })


# ============================================================
# SIGNALS
# ============================================================

@app.get("/api/signals")
def signals():

    signals_data, cached, error = get_signals()

    return jsonify({

        "ok": True,

        "market": "السوق السعودي",

        "signals": signals_data,

        "count": len(signals_data),

        "cached": cached,

        "error": error,

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat()

    })


# ============================================================
# FORCE REFRESH
# ============================================================

@app.get("/api/signals/refresh")
def refresh_signals():

    signals_data, cached, error = get_signals(
        force=True
    )

    return jsonify({

        "ok": True,

        "market": "السوق السعودي",

        "signals": signals_data,

        "count": len(signals_data),

        "cached": cached,

        "error": error,

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat()

    })


# ============================================================
# SINGLE STOCK
# ============================================================

@app.get("/api/stock/<symbol>")
def stock(symbol):

    symbol = clean_symbol(symbol)

    found_name = symbol

    for ticker, name in SAUDI_STOCKS:

        if ticker == symbol:

            found_name = name
            break

    result = download_stock(
        symbol,
        found_name
    )

    if not result:

        return jsonify({

            "ok": False,

            "message":
                "تعذر الحصول على بيانات السهم"

        }), 404

    return jsonify({

        "ok": True,

        "market": "السوق السعودي",

        "stock": result,

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat()

    })


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def home():

    return jsonify({

        "ok": True,

        "service": "مضارب أبو سعود — السوق السعودي",

        "market": "Tadawul",

        "endpoints": [

            "/api/health",

            "/api/signals",

            "/api/signals/refresh",

            "/api/market",

            "/api/stock/2222"

        ],

        "cacheSeconds":
            CACHE_SECONDS

    })


# ============================================================
# STARTUP
# ============================================================

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
        debug=False
    )
