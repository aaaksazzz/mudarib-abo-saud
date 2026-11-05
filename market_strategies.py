"""Lightweight market-specific 15m volume-impulse strategies.

Research candidate adapted to the data available in each market. It does not
claim a win rate; validate with out-of-sample tests before production use.
"""
import math

# Separate volume thresholds reflect differences in reported market volume.
PROFILES = {
    "spot": {"volume_ratio": 1.70, "long_only": True},
    "alpha": {"volume_ratio": 1.80, "long_only": True},
    "futures": {"volume_ratio": 1.65, "long_only": False},
    "us-stocks": {"volume_ratio": 1.55, "long_only": True},
    "us-contracts": {"volume_ratio": 1.50, "long_only": False},
    "saudi": {"volume_ratio": 1.40, "long_only": True},
    "forex": {"volume_ratio": 1.25, "long_only": False},
}


def _atr(highs, lows, closes, period=14):
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    sample = tr[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _ema(values, period=14):
    if len(values) < period:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def analyze(market, symbol, rows, include_micro=False):
    """Return a 15m setup from a closed high-volume impulse candle, or None."""
    profile = PROFILES.get(market)
    if not profile or not isinstance(rows, list) or len(rows) < 45:
        return None
    # Ignore the final, potentially still-forming 15m candle.
    bars = rows[:-1]
    try:
        o = [float(x[1]) for x in bars]
        h = [float(x[2]) for x in bars]
        l = [float(x[3]) for x in bars]
        c = [float(x[4]) for x in bars]
        v = [float(x[5] or 0) for x in bars]
        if not all(math.isfinite(z) for seq in (o, h, l, c, v) for z in seq):
            return None
        if any(x <= 0 for x in c[-25:]) or any(x < 0 for x in v[-25:]):
            return None

        i = len(bars) - 1
        op, hi, lo, close, volume = o[i], h[i], l[i], c[i], v[i]
        candle_range = hi - lo
        body = abs(close - op)
        if candle_range <= 0 or body <= 0 or close <= 0:
            return None

        baseline = sum(v[i - 20:i]) / 20.0
        if baseline <= 0:
            return None
        volume_ratio = volume / baseline
        if volume_ratio < profile["volume_ratio"]:
            return None

        atr = _atr(h, l, c, 14)
        ema14 = _ema(c, 14)
        if atr <= 0 or ema14 <= 0:
            return None
        close_location = (close - lo) / candle_range

        # Strong close in the directional half of the impulse candle.
        bullish = close > op and close_location >= 0.60
        bearish = close < op and close_location <= 0.40
        buffer = max(atr * 0.03, close * 0.00005)
        if bullish:
            side = "BUY"
            stop = ema14 - buffer
        elif bearish and not profile["long_only"]:
            side = "SELL"
            stop = ema14 + buffer
        else:
            return None

        # Reject setups where EMA14 is on the wrong side of entry or risk
        # is too wide; never silently move the stop to an unrelated level.
        risk = close - stop if side == "BUY" else stop - close
        if risk <= 0 or risk > atr * 2.5:
            return None
        target = close + 3.0 * risk if side == "BUY" else close - 3.0 * risk
        if stop <= 0 or target <= 0:
            return None

        location_score = close_location if side == "BUY" else 1.0 - close_location
        score = min(95.0, 55.0 + min(volume_ratio - profile["volume_ratio"], 2.0) * 10.0
                    + max(0.0, location_score - 0.65) * 40.0)
        return {
            "side": side,
            "entry": close,
            "stop": stop,
            # Restore the original single 3R target; TP labels share that level.
            "tp1": target,
            "tp2": target,
            "tp3": target,
            "score": round(score, 1),
            "timeframe": "15m",
            "change_pct": round((close / c[i - 1] - 1.0) * 100.0, 5),
            "change_15m_pct": round((close / c[i - 1] - 1.0) * 100.0, 5),
            "reason": (f"VOLUME IMPULSE {market}: volume {volume_ratio:.2f}x; "
                       "15m impulse close in directional half; EMA14 stop with ATR buffer; 3R target"),
            "signal_candle_time": int(float(bars[-1][0])),
            "risk_atr": round(risk / atr, 3),
            "ema14": round(ema14, 8),
            "reward_risk": 3.0,
            "volume_ratio": round(volume_ratio, 3),
            "strategy": f"VOLUME_IMPULSE_{market.upper()}",
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
