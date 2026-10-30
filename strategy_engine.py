"""Confluence-based multi-timeframe trading engine.

This is a deterministic technical-analysis engine, not an AI model or a profit guarantee.
"""
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

FRAME_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
                 "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2592000}
FRAME_SETS = {
    "15m": ("15m", "1h", "4h", "1d"),
    "30m": ("30m", "1h", "4h", "1d"),
    "1h": ("1h", "4h", "1d"),
    "2h": ("2h", "4h", "1d"),
    "4h": ("4h", "1d", "1w"),
    "1d": ("1d", "1w", "1M"),
    "1w": ("1w", "1d", "1M"),
    "1M": ("1M", "1w", "1d"),
}
RISK_CAP = {"15m": .018, "30m": .022, "1h": .03, "2h": .04,
            "4h": .055, "1d": .08, "1w": .12, "1M": .18}


def _ema(values, period):
    alpha = 2.0 / (period + 1.0)
    out = values[0]
    for value in values[1:]:
        out = alpha * value + (1.0 - alpha) * out
    return out


def _rsi(values, period=14):
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(0.0, x) for x in changes[-period:]]
    losses = [max(0.0, -x) for x in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss <= 1e-15:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(candles, period=14):
    trs = []
    for i, candle in enumerate(candles):
        high, low = candle["high"], candle["low"]
        prev = candles[i-1]["close"] if i else candle["close"]
        trs.append(max(high-low, abs(high-prev), abs(low-prev)))
    return sum(trs[-period:]) / min(period, len(trs))


def _adx(candles, period=14):
    if len(candles) < period + 2:
        return 0.0
    plus, minus, tr = [], [], []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i-1]
        up, down = cur["high"]-prev["high"], prev["low"]-cur["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        tr.append(max(cur["high"]-cur["low"], abs(cur["high"]-prev["close"]),
                      abs(cur["low"]-prev["close"])))
    dx_values = []
    for end in range(period, len(tr) + 1):
        p = sum(plus[end-period:end]) / period
        m = sum(minus[end-period:end]) / period
        t = sum(tr[end-period:end]) / period
        if t <= 0 or p + m <= 0:
            dx_values.append(0.0)
        else:
            plus_di, minus_di = 100.0*p/t, 100.0*m/t
            dx_values.append(abs(plus_di-minus_di)/(plus_di+minus_di)*100.0)
    return sum(dx_values[-period:]) / min(period, len(dx_values)) if dx_values else 0.0


def _valid_candles(raw):
    rows = []
    for candle in raw[-240:] if isinstance(raw, list) else []:
        try:
            row = {key: float(candle[key]) for key in ("open", "high", "low", "close", "volume")}
            if (all(math.isfinite(row[k]) and row[k] > 0 for k in ("open", "high", "low", "close"))
                and math.isfinite(row["volume"]) and row["volume"] >= 0
                and row["high"] >= max(row["open"], row["close"])
                and row["low"] <= min(row["open"], row["close"])
                and row["high"] >= row["low"]):
                rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return rows


def _frame_analysis(candles):
    if len(candles) < 60:
        return None
    closes = [c["close"] for c in candles]
    last = candles[-1]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 205 else None
    rsi = _rsi(closes)
    atr = _atr(candles)
    adx = _adx(candles)
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    macd = fast - slow
    # MACD histogram momentum uses a smoothed signal line.
    macd_series = []
    e12, e26 = closes[0], closes[0]
    for value in closes:
        e12 = value*(2/13) + e12*(11/13)
        e26 = value*(2/27) + e26*(25/27)
        macd_series.append(e12-e26)
    signal = _ema(macd_series, 9)
    hist = macd - signal
    previous_hist = (_ema(macd_series[:-1], 9) if len(macd_series) > 1 else signal)
    previous_hist = macd_series[-2] - previous_hist
    recent = candles[-20:-1]
    resistance = max(c["high"] for c in recent)
    support = min(c["low"] for c in recent)
    volume_avg = sum(c["volume"] for c in candles[-21:-1]) / 20
    rel_volume = last["volume"] / volume_avg if volume_avg > 0 else 0
    change = (closes[-1] / closes[-5] - 1.0) * 100.0
    up = last["close"] > ema20 > ema50
    down = last["close"] < ema20 < ema50
    if ema200 is not None:
        up = up and last["close"] > ema200
        down = down and last["close"] < ema200
    direction = "صاعد" if up else "هابط" if down else "محايد"
    return {"direction": direction, "rsi": rsi, "adx": adx, "atr": atr,
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "macd_hist": hist, "previous_macd_hist": previous_hist,
            "relative_volume": rel_volume, "resistance": resistance,
            "support": support, "change_pct": change, "last": last}


def _analyze_symbol(market, interval, row, candle_loader):
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    frames = FRAME_SETS.get(interval, (interval, "1h", "4h", "1d"))
    analyses, raw_by_frame = {}, {}
    for frame in frames:
        try:
            raw_by_frame[frame] = _valid_candles(candle_loader(market, symbol, frame))
        except Exception:
            raw_by_frame[frame] = []
        analyses[frame] = _frame_analysis(raw_by_frame[frame]) if raw_by_frame[frame] else None
    main = analyses.get(interval)
    if not main:
        return None
    valid = [a for a in analyses.values() if a]
    if len(valid) < min(2, len(frames)):
        return None

    long_score = short_score = 0.0
    evidence = []
    for frame, analysis in analyses.items():
        if not analysis:
            continue
        weight = 1.0 if frame == interval else 0.7
        direction = analysis["direction"]
        if direction == "صاعد":
            long_score += 16 * weight
            evidence.append(frame + ":صاعد")
        elif direction == "هابط":
            short_score += 16 * weight
            evidence.append(frame + ":هابط")
        if analysis["macd_hist"] > 0 and analysis["macd_hist"] > analysis["previous_macd_hist"]:
            long_score += 7 * weight
        elif analysis["macd_hist"] < 0 and analysis["macd_hist"] < analysis["previous_macd_hist"]:
            short_score += 7 * weight
    if main["rsi"] >= 52 and main["rsi"] <= 70:
        long_score += 10
    elif main["rsi"] <= 48 and main["rsi"] >= 30:
        short_score += 10
    if main["adx"] >= 20:
        if main["direction"] == "صاعد":
            long_score += min(10, (main["adx"]-20)*0.5)
        elif main["direction"] == "هابط":
            short_score += min(10, (main["adx"]-20)*0.5)
    if main["relative_volume"] >= 1.15:
        if main["last"]["close"] >= main["last"]["open"]:
            long_score += min(8, main["relative_volume"]*2)
        else:
            short_score += min(8, main["relative_volume"]*2)

    # Breakout confirmation is rewarded, but never used alone to create a trade.
    last = main["last"]
    if last["close"] > main["resistance"]:
        long_score += 8
    elif last["close"] < main["support"]:
        short_score += 8
    side = "شراء" if long_score >= short_score else "بيع"
    score = int(min(98, max(long_score, short_score)))
    if score < 72 or abs(long_score-short_score) < 18 or main["adx"] < 16:
        return None
    if side == "شراء" and (main["direction"] != "صاعد" or main["rsi"] > 72):
        return None
    if side == "بيع" and (main["direction"] != "هابط" or main["rsi"] < 28):
        return None

    close, atr = last["close"], main["atr"]
    swing = raw_by_frame[interval][-12:]
    raw_risk = max(atr*1.5, close*0.002)
    if side == "شراء":
        stop = min(close-raw_risk, min(c["low"] for c in swing)-atr*0.15)
        risk = close-stop
    else:
        stop = max(close+raw_risk, max(c["high"] for c in swing)+atr*0.15)
        risk = stop-close
    if risk <= 0 or risk/close > RISK_CAP.get(interval, .05):
        return None
    entry = close
    tp1, tp2, tp3 = ((entry+risk, entry+2*risk, entry+3*risk) if side == "شراء"
                    else (entry-risk, entry-2*risk, entry-3*risk))
    if tp3 <= 0:
        return None
    now = int(time.time())
    lifetime = FRAME_SECONDS.get(interval, 900)
    digits = 10 if entry < .001 else 8 if entry < 1 else 5 if entry < 100 else 3 if entry < 10000 else 2
    aligned = sum(1 for a in valid if a["direction"] == ("صاعد" if side == "شراء" else "هابط"))
    trend_map = {frame: (analysis["direction"] if analysis else "غير متاح")
                 for frame, analysis in analyses.items()}
    changes = {frame: round(analysis["change_pct"], 3) for frame, analysis in analyses.items() if analysis}
    profit_pct = abs(tp3-entry)/entry*100
    loss_pct = abs(stop-entry)/entry*100
    rationale = (f"توافق اتجاه EMA20/50 مع MACD وRSI وADX والحجم وبنية السعر؛ "
                 f"توافق {aligned}/{len(valid)} فريمات. درجة الأدلة {score}/100 وليست احتمال نجاح.")
    return {
        "id": f"pro-{market}-{symbol}-{interval}-{now}", "symbol": symbol,
        "direction": side, "title": f"{side} {symbol} — تحليل متعدد العوامل PRO",
        "description": rationale, "source": "محرك التحليل متعدد العوامل PRO",
        "url": "", "published_at": now, "created_at": now, "age_hours": 0,
        "market": market, "interval": interval, "expires_at": now+lifetime,
        "valid_for_seconds": lifetime, "price_updated_at": now, "price_fresh": True,
        "freshness_label": "آخر إغلاق شمعة متاح",
        "live_price": round(float(row.get("price") or close), digits),
        "levels": {"entry": round(entry,digits), "stop_loss": round(stop,digits),
                   "tp1": round(tp1,digits), "tp2": round(tp2,digits), "tp3": round(tp3,digits)},
        "ai_score": score, "combined_score": score, "method_score": score,
        "score_type": "درجة توافق فني وليست نسبة نجاح",
        "ai_reviewed": False, "generated_by_ai": False,
        "ai_review": {"summary_ar": rationale,
                      "risk_ar": "قد تتغير ظروف السوق بسرعة؛ احسب الرسوم والانزلاق قبل التنفيذ.",
                      "verdict": "توافق فني متعدد العوامل", "score_type": "درجة أدلة وليست نسبة ربح"},
        "timeframes_aligned": aligned, "timeframe_trends": trend_map,
        "timeframe_change_pct": changes,
        "timeframe_alignment_label": f"{aligned}/{len(valid)} فريمات متوافقة",
        "trend_strength": score, "potential_profit_pct": round(profit_pct,2),
        "potential_loss_pct": round(loss_pct,2),
        "tp1_profit_pct": round(abs(tp1-entry)/entry*100,2),
        "tp2_profit_pct": round(abs(tp2-entry)/entry*100,2),
        "tp3_profit_pct": round(profit_pct,2),
        "risk_reward_tp3": round(profit_pct/loss_pct,2) if loss_pct else None,
        "external_source_weight": 0, "site_analysis_weight": 100,
        "has_complete_levels": True, "level_source_note": "المستويات مبنية على ATR وبنية القمم والقيعان.",
        "method": "pro_confluence_v1"
    }


def generate_signals(market, interval, market_rows, limit, candle_loader):
    unique = {}
    for row in market_rows if isinstance(market_rows, list) else []:
        if isinstance(row, dict) and row.get("symbol"):
            unique.setdefault(str(row["symbol"]).upper(), row)
    def priority(row):
        try:
            volume = float(row.get("quote_volume") or row.get("dollar_volume") or row.get("volume") or 0)
            change = abs(float(row.get("change_pct") or 0))
            return (math.log10(1+max(0,volume)) * (1+min(change,25)/25), change)
        except (TypeError, ValueError, OverflowError):
            return (0,0)
    candidates = sorted(unique.values(), key=priority, reverse=True)[:min(30,max(12,limit*2))]
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(_analyze_symbol, market, interval, row, candle_loader) for row in candidates]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    results.append(item)
            except Exception:
                continue
    results.sort(key=lambda item: (item["combined_score"], item["timeframes_aligned"],
                                   item["risk_reward_tp3"],
                                   abs(item["timeframe_change_pct"].get(interval,0))), reverse=True)
    return results[:limit], True, ("تم التحليل متعدد العوامل وترتيب الفرص حسب قوة الأدلة والتوافق والمخاطرة."
                                   if results else "لم تظهر فرصة اجتازت شروط الجودة والتوافق حاليًا.")
