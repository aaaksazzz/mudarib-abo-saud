import os
import time
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from flask_cors import CORS


# ============================================================
# APP
# ============================================================

app = Flask(__name__)
CORS(app)


# ============================================================
# SETTINGS
# ============================================================

API_KEY = os.getenv("SAHMK_API_KEY", "").strip()

BASE_URL = "https://api.sahmk.sa/api/v1"

CACHE_SECONDS = 1800  # 30 دقيقة

REQUEST_TIMEOUT = 20


# ============================================================
# CACHE
# ============================================================

_cache = {
    "signals": [],
    "updated_at": None,
    "expires_at": 0,
    "error": None,
}

_cache_lock = threading.Lock()


# ============================================================
# HTTP
# ============================================================

def api_get(path, params=None):

    if not API_KEY:
        raise RuntimeError(
            "SAHMK_API_KEY غير موجود في إعدادات السيرفر"
        )

    url = BASE_URL + path

    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
        "User-Agent": "Mudarib-Abo-Saud/1.0",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        try:
            data = response.json()
            message = (
                data.get("error", {}).get("message")
                or data.get("message")
                or f"HTTP {response.status_code}"
            )
        except Exception:
            message = f"HTTP {response.status_code}"

        raise RuntimeError(message)

    return response.json()


# ============================================================
# HELPERS
# ============================================================

def number(value, default=0.0):

    try:
        if value is None or value == "":
            return default

        return float(value)

    except Exception:
        return default


def signal_from_change(change):

    change = number(change)

    if change >= 4:
        return "شراء قوي"

    if change >= 1:
        return "شراء"

    if change <= -4:
        return "بيع قوي"

    if change <= -1:
        return "بيع"

    return "حيادي"


def score_from_change(change):

    change = number(change)

    # تحويل التغير إلى قوة من 0 إلى 10
    score = 5 + (change * 0.8)

    return max(
        0,
        min(
            10,
            round(score, 1)
        )
    )


def targets(price, signal):

    price = number(price)

    if price <= 0:
        return 0, 0, 0

    # شراء
    if signal in ("شراء", "شراء قوي"):

        entry = price

        tp1 = price * 1.02
        tp2 = price * 1.04
        sl = price * 0.02

        return (
            round(entry, 4),
            round(tp1, 4),
            round(tp2, 4),
            round(sl, 4),
        )

    # بيع
    if signal in ("بيع", "بيع قوي"):

        entry = price

        tp1 = price * 0.98
        tp2 = price * 0.96
        sl = price * 1.02

        return (
            round(entry, 4),
            round(tp1, 4),
            round(tp2, 4),
            round(sl, 4),
        )

    return (
        round(price, 4),
        round(price, 4),
        round(price, 4),
        round(price, 4),
    )


def normalize_stock(stock):

    symbol = str(
        stock.get("symbol")
        or stock.get("ticker")
        or stock.get("code")
        or ""
    ).strip()

    name = str(
        stock.get("name")
        or stock.get("name_ar")
        or stock.get("company")
        or "السوق السعودي"
    ).strip()

    price = number(
        stock.get("price")
    )

    change = number(
        stock.get("change_percent")
        if stock.get("change_percent") is not None
        else stock.get("change")
    )

    volume = number(
        stock.get("volume")
    )

    signal = signal_from_change(change)

    score = score_from_change(change)

    entry, tp1, tp2, sl = targets(
        price,
        signal
    )

    return {
        "symbol": symbol,
        "name": name,

        "price": price,
        "change": round(change, 2),
        "changePercent": round(change, 2),

        "volume": volume,

        "signal": signal,

        "score": score,
        "score10": score,

        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,

        "market": "TASI",
        "source": "SAHMK",
    }


# ============================================================
# LOAD MARKET
# ============================================================

def fetch_market():

    """
    نستخدم endpoint واحد فقط.
    نأخذ الأسهم الأعلى من حيث قيمة التداول،
    ثم نحللها.

    هذا أخف بكثير من إرسال طلب منفصل لكل سهم.
    """

    data = api_get(
        "/market/value/",
        {
            "limit": 40,
            "index": "TASI",
            "data_mode": "delayed",
        }
    )

    stocks = (
        data.get("stocks")
        or data.get("results")
        or data.get("data")
        or []
    )

    results = []

    for stock in stocks:

        try:

            item = normalize_stock(stock)

            if not item["symbol"]:
                continue

            if item["price"] <= 0:
                continue

            results.append(item)

        except Exception:
            continue

    # ترتيب:
    # شراء قوي أولًا
    # ثم شراء
    # ثم حيادي
    # ثم بيع
    # ثم بيع قوي

    rank = {
        "شراء قوي": 5,
        "شراء": 4,
        "حيادي": 3,
        "بيع": 2,
        "بيع قوي": 1,
    }

    results.sort(
        key=lambda x: (
            rank.get(x["signal"], 3),
            x["score"],
            x["change"],
        ),
        reverse=True,
    )

    return results


# ============================================================
# REFRESH
# ============================================================

def refresh(force=False):

    now = time.time()

    with _cache_lock:

        if (
            not force
            and _cache["signals"]
            and now < _cache["expires_at"]
        ):
            return _cache["signals"]

    try:

        results = fetch_market()

        with _cache_lock:

            _cache["signals"] = results

            _cache["updated_at"] = (
                datetime.now(timezone.utc)
                .isoformat()
            )

            _cache["expires_at"] = (
                time.time() + CACHE_SECONDS
            )

            _cache["error"] = None

        return results

    except Exception as e:

        with _cache_lock:

            _cache["error"] = str(e)

            # إذا عندنا بيانات قديمة
            # نخليها موجودة بدل ما نخرب القسم.

            if _cache["signals"]:
                return _cache["signals"]

        raise


# ============================================================
# API
# ============================================================

@app.get("/")
def home():

    return jsonify({
        "ok": True,
        "service": "Mudarib Abo Saud - Saudi Market",
        "message": "السيرفر السعودي يعمل",
        "endpoint": "/api/signals",
    })


@app.get("/api/health")
def health():

    with _cache_lock:

        return jsonify({
            "ok": True,
            "service": "saudi_market",
            "cache_count": len(
                _cache["signals"]
            ),
            "updated_at": _cache["updated_at"],
            "cached": bool(
                _cache["signals"]
            ),
            "error": _cache["error"],
        })


@app.get("/api/signals")
def signals():

    try:

        results = refresh()

        with _cache_lock:

            return jsonify({
                "ok": True,

                "signals": results,

                "count": len(results),

                "updatedAt":
                    _cache["updated_at"],

                "cached": (
                    time.time()
                    < _cache["expires_at"]
                ),

                "market": "TASI",

                "source": "SAHMK",
            })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e),
            "signals": [],
        }), 503


@app.get("/api/signals/refresh")
def signals_refresh():

    try:

        results = refresh(
            force=True
        )

        with _cache_lock:

            return jsonify({
                "ok": True,
                "signals": results,
                "count": len(results),
                "updatedAt":
                    _cache["updated_at"],
                "cached": False,
            })

    except Exception as e:

        return jsonify({
            "ok": False,
            "message": str(e),
            "signals": [],
        }), 503


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
