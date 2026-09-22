import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ============================================================
# إعدادات
# ============================================================

CACHE_SECONDS = 1800  # تحديث كل 30 دقيقة

# أسهم سعودية رئيسية
SYMBOLS = [
    ("2222.SR", "أرامكو"),
    ("1120.SR", "الراجحي"),
    ("1180.SR", "الأهلي السعودي"),
    ("1010.SR", "الرياض"),
    ("1050.SR", "الإنماء"),
    ("1060.SR", "ساب"),
    ("1150.SR", "الإنماء"),
    ("2010.SR", "سابك"),
    ("1211.SR", "معادن"),
    ("7010.SR", "الاتصالات السعودية"),
    ("7020.SR", "موبايلي"),
    ("7030.SR", "زين السعودية"),
    ("2082.SR", "أكوا باور"),
    ("4030.SR", "البحري"),
    ("4003.SR", "إكسترا"),
    ("4190.SR", "جرير"),
    ("2280.SR", "المراعي"),
    ("2050.SR", "صافولا"),
    ("2380.SR", "بترو رابغ"),
    ("3003.SR", "أسمنت السعودية"),
    ("3040.SR", "أسمنت القصيم"),
    ("4001.SR", "أسواق العثيم"),
    ("4200.SR", "الدريس"),
    ("4240.SR", "سينومي ريتيل"),
    ("5110.SR", "كهرباء السعودية"),
    ("5110.SR", "كهرباء السعودية"),
    ("2160.SR", "أميانتيت"),
    ("2290.SR", "ينساب"),
    ("2330.SR", "المتقدمة"),
    ("2060.SR", "التصنيع"),
    ("2350.SR", "كيان السعودية"),
]

cache = {
    "signals": [],
    "updated": 0
}


# ============================================================
# Yahoo Finance
# ============================================================

def get_chart(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol
    )

    params = {
        "range": "5d",
        "interval": "15m",
        "includePrePost": "false",
        "events": "div,splits"
    }

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10
        )

        if r.status_code != 200:
            return None

        data = r.json()

        result = data.get("chart", {}).get("result")

        if not result:
            return None

        return result[0]

    except Exception:
        return None


# ============================================================
# تحليل السهم
# ============================================================

def analyze(symbol, name):
    data = get_chart(symbol)

    if not data:
        return None

    meta = data.get("meta", {})
    indicators = data.get("indicators", {})
    quote = indicators.get("quote", [])

    if not quote:
        return None

    q = quote[0]

    closes = q.get("close", [])
    highs = q.get("high", [])
    lows = q.get("low", [])
    volumes = q.get("volume", [])

    rows = []

    for i in range(len(closes)):
        if closes[i] is None:
            continue

        rows.append({
            "close": float(closes[i]),
            "high": float(highs[i]) if highs[i] is not None else float(closes[i]),
            "low": float(lows[i]) if lows[i] is not None else float(closes[i]),
            "volume": float(volumes[i]) if volumes[i] is not None else 0
        })

    if len(rows) < 25:
        return None

    last = rows[-1]
    prev = rows[-2]

    price = last["close"]
    prev_close = prev["close"]

    if prev_close <= 0:
        return None

    change = ((price - prev_close) / prev_close) * 100

    # متوسطات
    closes_only = [x["close"] for x in rows]

    ma9 = sum(closes_only[-9:]) / 9
    ma20 = sum(closes_only[-20:]) / 20

    # متوسط حجم آخر 20 شمعة
    volumes20 = [x["volume"] for x in rows[-20:]]
    avg_volume = sum(volumes20) / len(volumes20)

    volume_ratio = (
        last["volume"] / avg_volume
        if avg_volume > 0
        else 0
    )

    score = 5.0

    # اتجاه السعر
    if price > ma9:
        score += 1

    if price > ma20:
        score += 1

    # زخم
    if change >= 1:
        score += 1

    elif change <= -1:
        score -= 1

    # حجم
    if volume_ratio >= 1.5:
        score += 1

    score = max(0, min(10, round(score, 1)))

    # الإشارة
    if score >= 8:
        signal = "شراء قوي"
    elif score >= 6.5:
        signal = "شراء"
    elif score <= 3:
        signal = "بيع قوي"
    elif score <= 4.5:
        signal = "بيع"
    else:
        signal = "حيادي"

    # مستويات التحليل
    if signal in ("شراء", "شراء قوي"):
        entry = price
        tp1 = price * 1.02
        tp2 = price * 1.04
        sl = price * 0.98

    elif signal in ("بيع", "بيع قوي"):
        entry = price
        tp1 = price * 0.98
        tp2 = price * 0.96
        sl = price * 1.02

    else:
        entry = price
        tp1 = price * 1.02
        tp2 = price * 1.04
        sl = price * 0.98

    return {
        "symbol": symbol.replace(".SR", ""),
        "name": name,
        "price": round(price, 2),
        "change": round(change, 2),
        "signal": signal,
        "score": score,
        "score10": score,
        "entry": round(entry, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "sl": round(sl, 2),
        "volume_ratio": round(volume_ratio, 2),
        "ma9": round(ma9, 2),
        "ma20": round(ma20, 2)
    }


# ============================================================
# فحص السوق
# ============================================================

def scan_market():
    results = []

    for symbol, name in SYMBOLS:
        result = analyze(symbol, name)

        if result:
            results.append(result)

    # الأقوى أولاً
    results.sort(
        key=lambda x: (
            x.get("score", 0),
            abs(x.get("change", 0))
        ),
        reverse=True
    )

    return results


def get_signals(force=False):

    now = time.time()

    if (
        not force
        and cache["signals"]
        and now - cache["updated"] < CACHE_SECONDS
    ):
        return cache["signals"], True

    results = scan_market()

    cache["signals"] = results
    cache["updated"] = now

    return results, False


# ============================================================
# API
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "ok": True,
        "server": "Saudi Market Analysis",
        "api_key": False,
        "source": "Yahoo Finance",
        "interval": "15m",
        "cache_minutes": 30
    })


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "server": "Saudi Market Analysis",
        "api_key": False
    })


@app.route("/api/signals")
def signals():
    results, cached = get_signals()

    return jsonify({
        "ok": True,
        "signals": results,
        "count": len(results),
        "cached": cached,
        "updatedAt": datetime.now(
            timezone.utc
        ).isoformat()
    })


@app.route("/api/signals/refresh")
def refresh():
    results, cached = get_signals(force=True)

    return jsonify({
        "ok": True,
        "signals": results,
        "count": len(results),
        "cached": False,
        "updatedAt": datetime.now(
            timezone.utc
        ).isoformat()
    })


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
