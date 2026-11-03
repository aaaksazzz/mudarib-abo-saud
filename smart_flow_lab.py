import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, jsonify, request, send_from_directory
import requests

lab = Blueprint("smart_flow_lab", __name__)
BASE = "https://fapi.binance.com"
CACHE = {"at": 0, "payload": None}
LOCK = threading.Lock()
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "SMART-FLOW-LAB/1.0"})

def api(path, params=None):
    response = HTTP.get(BASE + path, params=params, timeout=(3, 7))
    response.raise_for_status()
    return response.json()

def finite(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default

def analyze_symbol(symbol):
    try:
        candles = api("/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 32})
        if len(candles) < 24:
            return None
        # Binance's last kline is still forming; use the last fully closed candle.
        closed = candles[:-1]
        bar = closed[-1]
        prior = closed[-21:-1]
        if len(prior) < 15:
            return None
        high = max(finite(x[2]) for x in prior)
        low = min(finite(x[3]) for x in prior)
        o, h, l, c = (finite(bar[i]) for i in (1, 2, 3, 4))
        volume = finite(bar[5])
        quote_volume = finite(bar[7])
        taker_buy = finite(bar[9])
        taker_ratio = taker_buy / volume if volume > 0 else 0.5
        candle_range = max(h - l, c * 0.0001)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        # Require a sweep beyond a recent 20-candle extreme and a close back inside.
        long_sweep = l < low and c > low and lower_wick / candle_range >= 0.20
        short_sweep = h > high and c < high and upper_wick / candle_range >= 0.20
        if not long_sweep and not short_sweep:
            return None
        side = "BUY" if long_sweep else "SELL"
        depth = api("/fapi/v1/depth", {"symbol": symbol, "limit": 20})
        bids = sum(finite(x[1]) for x in depth.get("bids", []))
        asks = sum(finite(x[1]) for x in depth.get("asks", []))
        imbalance = bids / (bids + asks) if bids + asks else 0.5
        # Keep a sweep only when at least one live flow measure agrees with its direction.
        flow_agrees = (taker_ratio >= 0.50 or imbalance >= 0.50) if side == "BUY" else (taker_ratio <= 0.50 or imbalance <= 0.50)
        if not flow_agrees:
            return None
        oi_now = finite(api("/fapi/v1/openInterest", {"symbol": symbol}).get("openInterest"))
        oi_change = 0.0
        # Public derivatives positioning proxy: taker buy/sell ratio plus live funding.
        # This is NOT private trader-wallet data or the API-key-gated top-trader feed.
        taker_flow_ratio = None
        funding_rate = None
        try:
            flow_rows = api("/futures/data/takerlongshortRatio", {"symbol": symbol, "period": "15m", "limit": 2})
            if flow_rows:
                taker_flow_ratio = finite(flow_rows[-1].get("buySellRatio"), 1.0)
        except Exception:
            pass
        try:
            premium = api("/fapi/v1/premiumIndex", {"symbol": symbol})
            funding_rate = finite(premium.get("lastFundingRate"), 0.0)
        except Exception:
            pass
        try:
            hist = api("/futures/data/openInterestHist", {"symbol": symbol, "period": "15m", "limit": 2})
            if len(hist) >= 2:
                old = finite(hist[-2].get("sumOpenInterest"))
                new = finite(hist[-1].get("sumOpenInterest"))
                oi_change = ((new / old) - 1) * 100 if old else 0.0
        except Exception:
            pass
        confirmations = []
        score = 48
        if side == "BUY":
            if taker_ratio >= 0.53: score += 16; confirmations.append("ضغط شراء من صفقات السوق")
            if imbalance >= 0.54: score += 12; confirmations.append("دفتر الأوامر يميل للطلبات")
            if lower_wick / candle_range >= 0.42: score += 8; confirmations.append("رفض سعري أسفل النطاق")
            if oi_change > 0: score += 5; confirmations.append("ارتفاع العقود المفتوحة")
        else:
            if taker_ratio <= 0.47: score += 16; confirmations.append("ضغط بيع من صفقات السوق")
            if imbalance <= 0.46: score += 12; confirmations.append("دفتر الأوامر يميل للعروض")
            if upper_wick / candle_range >= 0.42: score += 8; confirmations.append("رفض سعري أعلى النطاق")
            if oi_change > 0: score += 5; confirmations.append("ارتفاع العقود المفتوحة")
        # Crowd-trap confirmation: extreme taker-side crowding + matching funding bias,
        # confirmed by a sweep against the crowded side. This is a public-data proxy,
        # not proof of whale identities or guaranteed future liquidations.
        crowd_trap = False
        if taker_flow_ratio is not None and funding_rate is not None:
            if side == "BUY" and taker_flow_ratio <= 0.75 and funding_rate < 0:
                crowd_trap = True
                score += 10
                confirmations.append("احتمال ضغط مراكز بيع: تدفق taker يميل للبيع والتمويل سلبي")
            elif side == "SELL" and taker_flow_ratio >= 1.35 and funding_rate > 0:
                crowd_trap = True
                score += 10
                confirmations.append("احتمال ضغط مراكز شراء: تدفق taker يميل للشراء والتمويل إيجابي")
        # Use sweep extreme as invalidation; ATR-like range from recent closed bars sets a minimum buffer.
        ranges = [max(finite(x[2])-finite(x[3]), 0) for x in closed[-14:]]
        atr = sum(ranges) / max(len(ranges), 1)
        entry = c
        buffer = max(atr * 0.22, entry * 0.0015)
        stop = (l - buffer) if side == "BUY" else (h + buffer)
        risk = abs(entry - stop)
        if not risk or risk / entry > 0.035:
            return None
        direction = 1 if side == "BUY" else -1
        return {
            "symbol": symbol, "side": side, "score": min(score, 89),
            "entry": entry, "stop": stop,
            "tp1": entry + direction * risk,
            "tp2": entry + direction * risk * 1.8,
            "tp3": entry + direction * risk * 2.7,
            "taker_buy_ratio": round(taker_ratio * 100, 1),
            "book_imbalance": round(imbalance * 100, 1),
            "oi_change_pct": round(oi_change, 3),
            "open_interest": oi_now,
            "taker_flow_ratio": round(taker_flow_ratio, 4) if taker_flow_ratio is not None else None,
            "funding_rate_pct": round(funding_rate * 100, 5) if funding_rate is not None else None,
            "crowd_trap": crowd_trap,
            "quote_volume": quote_volume,
            "sweep": "سحب سيولة أسفل قاع سابق" if side == "BUY" else "سحب سيولة أعلى قمة سابقة",
            "confirmations": confirmations or ["تم رصد السحب؛ التأكيدات الإضافية محدودة"],
            "closed_candle_time": int(bar[6])
        }
    except Exception:
        return None

@lab.get("/smart-flow-lab")
def page():
    return send_from_directory(".", "smart-flow-lab.html")

@lab.get("/smart-flow-lab/assets/<path:name>")
def assets(name):
    if name not in ("smart-flow-lab.css", "smart-flow-lab.js"):
        return ("Not found", 404)
    return send_from_directory(".", name)

@lab.get("/smart-flow-lab/api/status")
def status():
    return jsonify({"ok": True, "source": "Binance USDⓈ-M public Futures API", "timeframe": "15m", "paper_only": True})

@lab.get("/smart-flow-lab/api/scan")
def scan():
    now = time.time()
    with LOCK:
        if CACHE["payload"] and now - CACHE["at"] < 45:
            return jsonify(CACHE["payload"])
    try:
        exchange = api("/fapi/v1/exchangeInfo")
        eligible = {x["symbol"] for x in exchange.get("symbols", [])
                    if x.get("status") == "TRADING" and x.get("contractType") == "PERPETUAL"
                    and x.get("quoteAsset") == "USDT"}
        tickers = api("/fapi/v1/ticker/24hr")
        # Prioritize the fastest / most actively traded contracts first:
        # high 24h turnover, then larger absolute 24h move. Continue down
        # the ranked list in batches until 3 valid setups are found or all
        # eligible contracts have been checked.
        universe = sorted(
            [x for x in tickers if x.get("symbol") in eligible and finite(x.get("quoteVolume")) >= 1_000_000],
            key=lambda x: (finite(x.get("quoteVolume")), abs(finite(x.get("priceChangePercent")))),
            reverse=True
        )
        batch_size = 36
        found = []
        scanned_count = 0
        for start in range(0, len(universe), batch_size):
            batch = universe[start:start + batch_size]
            with ThreadPoolExecutor(max_workers=12) as pool:
                futures = [pool.submit(analyze_symbol, item["symbol"]) for item in batch]
                for future in as_completed(futures):
                    scanned_count += 1
                    item = future.result()
                    if item:
                        found.append(item)
            # Move to lighter-volume contracts only when fewer than 3 setups exist.
            if len(found) >= 3:
                break
        found.sort(key=lambda x: (x["score"], x["quote_volume"]), reverse=True)
        payload = {
            "ok": True, "source": "Binance USDⓈ-M public Futures API",
            "timeframe": "15m", "universe_count": len(universe),
            "scanned_count": scanned_count, "signals": found[:3],
            "scan_batch_size": batch_size,
            "checked_at": int(time.time()), "cached_seconds": 45,
            "note": "يبدأ الفحص بالعقود الأسرع والأعلى تداولاً، ثم ينتقل تدريجياً إلى العقود الأقل نشاطاً عند الحاجة حتى تظهر 3 فرص أو ينتهي السوق المؤهل. الحد الأدنى لحجم 24 ساعة: 1 مليون USDT."
        }
        with LOCK:
            CACHE.update({"at": time.time(), "payload": payload})
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": "تعذر جلب بيانات Binance حالياً", "detail": str(exc)[:180]}), 502

def register_smart_flow_lab(app):
    app.register_blueprint(lab)
