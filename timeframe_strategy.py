"""Multi-timeframe alignment strategy for all supported markets.

15m/1h -> 4h + 1d; 4h/1d/1w -> 1w + 1M.
Only completed OHLCV candles are expected from provider adapters.
"""
from statistics import mean

TIMEFRAME_RULES = {
    "15m": ("4h", "1d"),
    "1h": ("4h", "1d"),
    "4h": ("1w", "1M"),
    "1d": ("1w", "1M"),
    "1w": ("1w", "1M"),
    "1M": ("1M",),
}
BUY_STATES = frozenset(("BUY", "STRONG_BUY"))
SELL_STATES = frozenset(("SELL", "STRONG_SELL"))


def _state(rows):
    """Classify one reference timeframe from candle structure and momentum."""
    if not isinstance(rows, (list, tuple)) or len(rows) < 12:
        return "INSUFFICIENT"
    try:
        bars = rows[-12:]
        closes = [float(x["close"]) for x in bars]
        highs = [float(x["high"]) for x in bars]
        lows = [float(x["low"]) for x in bars]
        if any(x <= 0 for x in closes) or any(h < l for h, l in zip(highs, lows)):
            return "INVALID"

        momentum = closes[-1] / closes[-5] - 1
        recent_high, prior_high = mean(highs[-4:]), mean(highs[-8:-4])
        recent_low, prior_low = mean(lows[-4:]), mean(lows[-8:-4])
        rising = recent_high > prior_high and recent_low > prior_low
        falling = recent_high < prior_high and recent_low < prior_low

        if momentum > 0.001 and rising:
            return "STRONG_BUY" if momentum >= 0.01 and closes[-1] > closes[-2] else "BUY"
        if momentum < -0.001 and falling:
            return "STRONG_SELL" if momentum <= -0.01 and closes[-1] < closes[-2] else "SELL"
        return "NEUTRAL"
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return "INVALID"


def assess_strategy(histories, entry_timeframe, side=None):
    """Classify the selected timeframe on its own; never borrow another frame's state."""
    if entry_timeframe not in ("15m", "1h", "4h", "1d", "1w", "1M"):
        return {"confirmed": False, "reason": "unsupported_timeframe", "states": {}}
    rows = (histories or {}).get(entry_timeframe, [])
    state = _state(rows)
    buy_aligned = state in BUY_STATES
    sell_aligned = state in SELL_STATES
    if side == "BUY":
        confirmed, selected_side = buy_aligned, "BUY"
    elif side == "SELL":
        confirmed, selected_side = sell_aligned, "SELL"
    elif buy_aligned:
        confirmed, selected_side = True, "BUY"
    elif sell_aligned:
        confirmed, selected_side = True, "SELL"
    else:
        confirmed, selected_side = False, None
    return {
        "confirmed": confirmed,
        "side": selected_side,
        "states": {entry_timeframe: state},
        "analysis_timeframe": entry_timeframe,
        "reason": "confirmed" if confirmed else "timeframe_setup_not_confirmed",
    }
def make_trade(rows, side):
    """Calculate entry, SL and 1R/2R/3R targets from entry-timeframe candles."""
    if side not in ("BUY", "SELL") or not isinstance(rows, (list, tuple)) or len(rows) < 20:
        return None
    try:
        bars = rows[-20:]
        entry = float(bars[-1]["close"])
        ranges = []
        for index, bar in enumerate(bars[-14:]):
            previous_close = float(bars[-15 + index]["close"])
            high, low = float(bar["high"]), float(bar["low"])
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        atr = sum(ranges) / len(ranges)
        if entry <= 0 or atr <= 0:
            return None

        swing_low = min(float(x["low"]) for x in bars[-8:])
        swing_high = max(float(x["high"]) for x in bars[-8:])
        stop = swing_low - atr * 0.15 if side == "BUY" else swing_high + atr * 0.15
        risk = entry - stop if side == "BUY" else stop - entry
        if risk <= 0 or risk / entry > 0.045:
            return None

        sign = 1 if side == "BUY" else -1
        return {
            "entry": entry,
            "stop_loss": stop,
            "tp1": entry + sign * risk,
            "tp2": entry + sign * risk * 2,
            "tp3": entry + sign * risk * 3,
            "risk_percent": round(risk / entry * 100, 3),
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
