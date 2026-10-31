"""HAWK QUANT PRO multi-timeframe confirmation.

Uses only completed OHLC candles. It deliberately avoids claiming probability
or profitability: the score is a rule-confluence quality score, not a win rate.
"""
from statistics import mean


def _state(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) < 12:
        return "INSUFFICIENT"
    try:
        bars = rows[-12:]
        closes = [float(row["close"]) for row in bars]
        highs = [float(row["high"]) for row in bars]
        lows = [float(row["low"]) for row in bars]
        if any(value <= 0 for value in closes) or any(h < l for h, l in zip(highs, lows)):
            return "INVALID"
        recent_close = closes[-1]
        momentum = recent_close / closes[-5] - 1.0
        recent_high = mean(highs[-4:])
        prior_high = mean(highs[-8:-4])
        recent_low = mean(lows[-4:])
        prior_low = mean(lows[-8:-4])
        rising_structure = recent_high > prior_high and recent_low > prior_low
        falling_structure = recent_high < prior_high and recent_low < prior_low
        if momentum > 0.001 and rising_structure:
            return "BUY"
        if momentum < -0.001 and falling_structure:
            return "SELL"
        return "NEUTRAL"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return "INVALID"


def assess_timeframe_alignment(histories, side):
    """Require 1h, 4h and daily structure to agree with the entry direction."""
    expected = "BUY" if side == "BUY" else "SELL" if side == "SELL" else None
    states = {interval: _state(histories.get(interval, []))
              for interval in ("1h", "4h", "1d")}
    aligned = sum(state == expected for state in states.values()) if expected else 0
    opposing = "SELL" if expected == "BUY" else "BUY"
    confirmed = (
        bool(expected)
        and states["1h"] == expected
        and aligned >= 2
        and all(state != opposing for state in states.values())
    )
    return {
        "confirmed": confirmed,
        "states": states,
        "score": aligned * 100 / 3,
        "bonus": 5 if confirmed else 0,
    }
