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
    # One-candle percentage move: for the 15m scan this is the actual latest 15m change.
    change = (closes[-1] / closes[-2] - 1.0) * 100.0
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
    """4h and daily decide direction; 15m momentum ranks candidates."""
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    frames = ("15m", "4h", "1d")
    analyses, raw_by_frame = {}, {}
    for frame in frames:
        try:
            raw_by_frame[frame] = _valid_candles(candle_loader(market, symbol, frame))
        except Exception:
            raw_by_frame[frame] = []
        analyses[frame] = _frame_analysis(raw_by_frame[frame]) if raw_by_frame[frame] else None
    if any(analyses.get(frame) is None for frame in frames):
        return None
    fast, four_hour, daily = analyses["15m"], analyses["4h"], analyses["1d"]
    def frame_signal(frame):
        if frame["direction"] == "صاعد":
            return "شراء قوي" if frame["adx"] >= 25 else "شراء"
        if frame["direction"] == "هابط":
            return "بيع قوي" if frame["adx"] >= 25 else "بيع"
        return "محايد"

    four_hour_signal = frame_signal(four_hour)
    daily_signal = frame_signal(daily)
    bullish = {"شراء", "شراء قوي"}
    bearish = {"بيع", "بيع قوي"}
    if four_hour_signal in bullish and daily_signal in bullish:
        side = "شراء"
    elif four_hour_signal in bearish and daily_signal in bearish:
        side = "بيع"
    else:
        return None
    entry, atr = float(fast["last"]["close"]), float(fast["atr"])
    if not math.isfinite(entry) or entry <= 0 or not math.isfinite(atr) or atr <= 0:
        return None
    risk = max(atr * 1.5, entry * 0.002)
    if risk <= 0 or risk / entry > RISK_CAP.get("15m", .018):
        return None
    swing = raw_by_frame["15m"][-12:]
    if side == "شراء":
        stop = min(entry-risk, min(c["low"] for c in swing)-atr*.15)
        risk = entry-stop
        tp1, tp2, tp3 = entry+risk, entry+2*risk, entry+3*risk
    else:
        stop = max(entry+risk, max(c["high"] for c in swing)+atr*.15)
        risk = stop-entry
        tp1, tp2, tp3 = entry-risk, entry-2*risk, entry-3*risk
    if risk <= 0 or risk / entry > RISK_CAP.get("15m", .018) or tp3 <= 0:
        return None
    strong = four_hour_signal in {"شراء قوي", "بيع قوي"} and daily_signal in {"شراء قوي", "بيع قوي"}
    label = ("شراء قوي" if strong else "شراء") if side == "شراء" else ("بيع قوي" if strong else "بيع")
    now = int(time.time())
    digits = 10 if entry < .001 else 8 if entry < 1 else 5 if entry < 100 else 3 if entry < 10000 else 2
    changes = {frame: round(analyses[frame]["change_pct"], 3) for frame in frames}
    profit_pct, loss_pct = abs(tp3-entry)/entry*100, abs(stop-entry)/entry*100
    evidence_score = min(98, int(50 + min(25, (four_hour["adx"]+daily["adx"])/4)))
    rationale = "اتجاه 4 ساعات واليومي متفقان؛ تغير 15 دقيقة للترتيب فقط. الدرجة ليست نسبة نجاح."
    return {
        "id": f"trend-4h-1d-{market}-{symbol}-{now}", "symbol": symbol,
        "direction": side, "signal_label": label, "title": f"{label} {symbol}",
        "description": rationale, "source": "تحليل اتجاه 4 ساعات + يومي",
        "url": "", "published_at": now, "created_at": now, "age_hours": 0,
        "market": market, "interval": "15m", "expires_at": now+900,
        "valid_for_seconds": 900, "price_updated_at": now, "price_fresh": True,
        "freshness_label": "آخر إغلاق شمعة 15 دقيقة",
        "live_price": round(float(row.get("price") or entry), digits),
        "levels": {"entry": round(entry,digits), "stop_loss": round(stop,digits),
                   "tp1": round(tp1,digits), "tp2": round(tp2,digits), "tp3": round(tp3,digits)},
        "ai_score": evidence_score, "combined_score": evidence_score,
        "method_score": evidence_score, "score_type": "درجة قوة الاتجاه وليست احتمال نجاح",
        "ai_reviewed": False, "generated_by_ai": False,
        "timeframes_aligned": 2,
        "timeframe_trends": {frame: analyses[frame]["direction"] for frame in frames},
        "timeframe_signals": {"4h": four_hour_signal, "1d": daily_signal},
        "timeframe_change_pct": changes, "change_15m_pct": changes["15m"],
        "timeframe_alignment_label": "4h + يومي متفقان",
        "trend_strength": evidence_score, "potential_profit_pct": round(profit_pct,2),
        "potential_loss_pct": round(loss_pct,2),
        "tp1_profit_pct": round(abs(tp1-entry)/entry*100,2),
        "tp2_profit_pct": round(abs(tp2-entry)/entry*100,2),
        "tp3_profit_pct": round(profit_pct,2),
        "risk_reward_tp3": round(profit_pct/loss_pct,2) if loss_pct else None,
        "external_source_weight": 0, "site_analysis_weight": 100,
        "has_complete_levels": True,
        "level_source_note": "المستويات مبنية على ATR لشموع 15 دقيقة.",
        "method": "trend_4h_1d_rank_15m_v2"
    }

def generate_signals(market, interval, market_rows, limit, candle_loader):
    """4h/daily agreement determines side; 15m percentage move ranks the list."""
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
        jobs = [pool.submit(_analyze_symbol, market, "15m", row, candle_loader) for row in candidates]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    results.append(item)
            except Exception:
                continue
    results.sort(key=lambda item: (
        0 if item["direction"] == "شراء" else 1,
        -item.get("change_15m_pct", 0) if item["direction"] == "شراء"
        else item.get("change_15m_pct", 0)
    ))
    return results[:limit], True, ("تم اعتماد توافق 4 ساعات واليومي، والترتيب حسب تغير 15 دقيقة."
                                   if results else "لا توجد فرصة تحقق توافق 4 ساعات واليومي حاليًا.")
