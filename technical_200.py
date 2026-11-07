"""200-rule technical confluence overlay for SMART FLOW QUANT.

The existing strategy remains the signal generator. These 200 parameterized
technical checks rank/describe an existing setup and refine its structural
stop; they are not 200 mandatory gates and never place orders.
"""
import math

LOOKBACKS = (5, 8, 10, 12, 14, 16, 20, 24, 30, 40)


def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for x in values[period:]:
        value = alpha * x + (1.0 - alpha) * value
    return value


def _rsi(values, period):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    sample = changes[-period:]
    gains = sum(max(x, 0.0) for x in sample) / period
    losses = sum(max(-x, 0.0) for x in sample) / period
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def _sign(value, tolerance=0.0):
    if value is None or not math.isfinite(value):
        return 0
    return 1 if value > tolerance else -1 if value < -tolerance else 0


def analyze_200(rows, side, entry, original_stop, atr):
    """Return 200-rule confluence, a volatility-bounded structural stop and audit data."""
    if side not in ("BUY", "SELL") or not isinstance(rows, list) or len(rows) < 60:
        return None
    bars = rows[:-1]  # Never use a forming candle.
    try:
        o = [float(x[1]) for x in bars]
        h = [float(x[2]) for x in bars]
        l = [float(x[3]) for x in bars]
        c = [float(x[4]) for x in bars]
        v = [max(0.0, float(x[5])) for x in bars]
        entry, original_stop, atr = float(entry), float(original_stop), float(atr)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if len(c) < 60 or not all(math.isfinite(x) for x in (entry, original_stop, atr)) or min(entry, atr) <= 0:
        return None
    if any(not math.isfinite(x) for seq in (o, h, l, c, v) for x in seq):
        return None

    votes = []
    details = {}
    def add(name, period, value):
        vote = _sign(value)
        votes.append(vote)
        if vote:
            details[name] = details.get(name, 0) + (1 if vote > 0 else -1)

    for p in LOOKBACKS:
        closes, highs, lows, opens, volumes = c[-(p + 1):], h[-(p + 1):], l[-(p + 1):], o[-(p + 1):], v[-(p + 1):]
        last = closes[-1]
        mean = sum(closes[-p:]) / p
        ema = _ema(c, p)
        # 1-2: simple and exponential trend location/slope
        add("SMA trend", p, (last / mean - 1.0) if mean else 0)
        old_ema = _ema(c[:-max(2, p // 3)], p) if len(c) > p + 2 else None
        add("EMA trend", p, ((ema - old_ema) / last) if ema is not None and old_ema is not None and last else None)
        # 3: rate of change
        add("ROC momentum", p, (last / c[-p-1] - 1.0) if c[-p-1] else 0)
        # 4: RSI regime (neutral middle zone)
        rsi = _rsi(c, p)
        add("RSI regime", p, (rsi - 50.0) if rsi is not None and abs(rsi - 50.0) >= 5 else 0)
        # 5: stochastic location
        hh, ll = max(highs[:-1]), min(lows[:-1])
        stoch = ((last - ll) / (hh - ll)) if hh > ll else 0.5
        add("Stochastic", p, (stoch - 0.5) if stoch >= 0.65 or stoch <= 0.35 else 0)
        # 6: MACD-style fast/slow EMA spread
        fast = _ema(c, max(2, p // 2))
        slow = _ema(c, p)
        add("MACD spread", p, ((fast - slow) / last) if fast is not None and slow is not None and last else None)
        # 7: Bollinger-style deviation from rolling mean
        variance = sum((x - mean) ** 2 for x in closes[-p:]) / p
        sd = math.sqrt(max(0.0, variance))
        add("Band position", p, ((last - mean) / sd) if sd > 0 and abs(last - mean) > sd * 0.25 else 0)
        # 8: Donchian breakout
        add("Donchian breakout", p, 1 if last > hh else -1 if last < ll else 0)
        # 9: ATR-scaled impulse
        impulse = (last - c[-min(len(c), p + 1)]) / atr
        add("ATR impulse", p, impulse if abs(impulse) >= 0.25 else 0)
        # 10: candle body pressure
        candle_range = highs[-1] - lows[-1]
        body = (closes[-1] - opens[-1]) / candle_range if candle_range > 0 else 0
        add("Candle body", p, body if abs(body) >= 0.25 else 0)
        # 11: rejection wick
        upper = highs[-1] - max(opens[-1], closes[-1])
        lower = min(opens[-1], closes[-1]) - lows[-1]
        add("Wick rejection", p, (lower - upper) / candle_range if candle_range > 0 and abs(lower-upper) / candle_range >= 0.2 else 0)
        # 12: directional volume confirmation
        baseline = sum(volumes[:-1]) / max(1, len(volumes)-1)
        vol_ratio = volumes[-1] / baseline if baseline > 0 else 0
        add("Volume pressure", p, body if vol_ratio >= 1.05 else 0)
        # 13: price-volume trend
        pv = sum((closes[i] / closes[i-1] - 1.0) * volumes[i] for i in range(1, len(closes)) if closes[i-1] > 0)
        add("Price volume trend", p, pv if abs(pv) > 0 else 0)
        # 14: OBV direction
        obv = sum((1 if closes[i] > closes[i-1] else -1 if closes[i] < closes[i-1] else 0) * volumes[i] for i in range(1, len(closes)))
        add("OBV flow", p, obv)
        # 15: accumulation/distribution close-location flow
        ad = sum((((2*closes[i]-highs[i]-lows[i])/(highs[i]-lows[i])) if highs[i] > lows[i] else 0) * volumes[i] for i in range(len(closes)))
        add("Accumulation distribution", p, ad)
        # 16: close relative to rolling pivot
        pivot = (hh + ll + sum(closes[:-1]) / max(1, len(closes)-1)) / 3.0
        add("Rolling pivot", p, (last / pivot - 1.0) if pivot else 0)
        # 17: swing structure (higher highs/lows vs prior half)
        half = max(2, p // 2)
        recent_h, prior_h = max(highs[-half:]), max(highs[:-half])
        recent_l, prior_l = min(lows[-half:]), min(lows[:-half])
        structure = (1 if recent_h > prior_h else 0) - (1 if recent_l < prior_l else 0)
        add("Swing structure", p, structure)
        # 18: range expansion with directional close
        prior_ranges = [highs[i]-lows[i] for i in range(len(highs)-1)]
        avg_range = sum(prior_ranges) / len(prior_ranges) if prior_ranges else 0
        expansion = candle_range / avg_range if avg_range > 0 else 0
        add("Range expansion", p, body if expansion >= 1.1 and abs(body) >= 0.2 else 0)
        # 19: multi-candle trend persistence
        changes = [closes[i]-closes[i-1] for i in range(1, len(closes))]
        persistence = sum(1 if x > 0 else -1 if x < 0 else 0 for x in changes)
        add("Trend persistence", p, persistence)
        # 20: close relative to midpoint of rolling range
        midpoint = (hh + ll) / 2.0
        add("Range midpoint", p, (last / midpoint - 1.0) if midpoint else 0)

    if len(votes) != 200:
        return None
    direction = 1 if side == "BUY" else -1
    aligned = sum(1 for vote in votes if vote == direction)
    opposed = sum(1 for vote in votes if vote == -direction)
    active = aligned + opposed
    agreement = round(100.0 * aligned / active, 1) if active else 50.0

    # Structure-based stop from recent completed candles, bounded by the existing risk guardrails.
    look = min(20, len(c))
    buffer = max(atr * 0.15, entry * 0.0002)
    structural = min(l[-look:]) - buffer if side == "BUY" else max(h[-look:]) + buffer
    risk = abs(entry - structural)
    if not math.isfinite(risk) or risk < atr * 0.55 or risk > atr * 2.5:
        structural = original_stop
        risk = abs(entry - structural)
    if not math.isfinite(risk) or risk <= 0 or risk > atr * 2.5:
        return None
    targets = [entry + direction * risk * r for r in (1.0, 2.0, 3.0)]
    if min(entry, structural, *targets) <= 0:
        return None
    return {
        "rules_total": 200, "rules_aligned": aligned, "rules_opposed": opposed,
        "rules_active": active, "agreement_pct": agreement,
        "stop": structural, "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "risk_atr": round(risk / atr, 3),
        "groups": details,
    }
