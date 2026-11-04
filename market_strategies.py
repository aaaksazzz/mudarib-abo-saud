"""Lightweight market-specific 15m volume-impulse strategies.

Research candidate adapted to the data available in each market. It does not
claim a win rate; validate with out-of-sample backtests before production use.
"""
import math

# Thresholds reflect differences in reported volume: exchange volume for crypto,
# exchange-reported share/contract volume, and tick volume for FX/metals.
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


def analyze(market, symbol, rows, include_micro=False):
    """Return one 15m setup from a closed high-volume impulse candle, or None."""
    profile = PROFILES.get(market)
    if not profile or not isinstance(rows, list) or len(rows) < 45:
        return None
    # Match the application's established convention: ignore the final,
    # potentially still-forming 15m candle.
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
        if atr <= 0:
            return None
        close_location = (close - lo) / candle_range

        # A decisive close in the upper/lower half is the core setup.
        # Avoid a 20-candle breakout gate that would suppress valid impulses.
        bullish = close > op and close_location >= 0.60
        bearish = close < op and close_location <= 0.40
        if bullish:
            side = "BUY"
            stop = close - 1.5 * atr
            tp1, tp2, tp3 = close + atr, close + 2.0 * atr, close + 3.0 * atr
        elif bearish and not profile["long_only"]:
            side = "SELL"
            stop = close + 1.5 * atr
            tp1, tp2, tp3 = close - atr, close - 2.0 * atr, close - 3.0 * atr
        else:
            return None

        risk = close - stop if side == "BUY" else stop - close
        if risk <= 0 or stop <= 0 or tp3 <= 0:
            return None

        location_score = close_location if side == "BUY" else 1.0 - close_location
        score = min(95.0, 55.0 + min(volume_ratio - profile["volume_ratio"], 2.0) * 10.0
                    + max(0.0, location_score - 0.65) * 40.0)
        return {
            "side": side,
            "entry": close,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "score": round(score, 1),
            "timeframe": "15m",
            "change_pct": round((close / c[i - 1] - 1.0) * 100.0, 5),
            "change_15m_pct": round((close / c[i - 1] - 1.0) * 100.0, 5),
            "reason": (f"VOLUME IMPULSE {market}: volume {volume_ratio:.2f}x; "
                       f"15m close in directional half of candle; SL 1.5x ATR; "
                       f"TP1/TP2/TP3 at 1x/2x/3x ATR"),
            "signal_candle_time": int(float(bars[-1][0])),
            "risk_atr": round(risk / atr, 3),
            "reward_risk": 2.0,
            "volume_ratio": round(volume_ratio, 3),
            "strategy": f"VOLUME_IMPULSE_{market.upper()}",
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
