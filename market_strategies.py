"""Independent, closed-candle strategy ensemble for SMART TRADING PRO.

Methodology references:
- NFI: volume/momentum confirmation and regime-aware filtering (adapted conceptually).
- Paul Csapak's MIT-licensed Freqtrade strategy examples: EMA, MACD and RSI trend rules.
This is a clean-room implementation, not a vendored copy of either trading bot.
Scores are confluence scores, not probabilities of profit.
"""
import math

TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
INTERVAL_MS = {
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}
PROFILES = {
    "spot": {"allow_short": False},
    "alpha": {"allow_short": False},
    "futures": {"allow_short": True},
    "us-stocks": {"allow_short": False},
    "us-contracts": {"allow_short": True},
    "saudi": {"allow_short": False},
    "forex": {"allow_short": True},
}


def _ema(values, period):
    out = [None] * len(values)
    if not values:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = None
    for i, value in enumerate(values):
        seed = value if seed is None else alpha * value + (1.0 - alpha) * seed
        out[i] = seed
    return out


def _rsi(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    for i in range(period, len(values)):
        if i > period:
            avg_gain = ((period - 1) * avg_gain + gains[i]) / period
            avg_loss = ((period - 1) * avg_loss + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _atr(highs, lows, closes, period=14):
    out = [None] * len(closes)
    if not closes:
        return out
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    alpha = 1.0 / period
    value = None
    for i, item in enumerate(tr):
        value = item if value is None else value + alpha * (item - value)
        out[i] = value
    return out


def _macd(values):
    fast, slow = _ema(values, 12), _ema(values, 26)
    line = [a - b for a, b in zip(fast, slow)]
    signal = _ema(line, 9)
    return line, signal


def _volume_breakout_vote(highs, lows, closes, volumes, index):
    if index < 21:
        return None
    sample = volumes[index - 20:index]
    positive = [v for v in sample if v > 0]
    current_volume = volumes[index]
    if not positive or current_volume <= 0:
        return None
    average = sum(positive) / len(positive)
    if average <= 0 or current_volume / average < 1.35:
        return None
    candle_range = highs[index] - lows[index]
    if candle_range <= 0:
        return None
    close_location = (closes[index] - lows[index]) / candle_range
    prior_high = max(highs[index - 20:index])
    prior_low = min(lows[index - 20:index])
    if closes[index] > prior_high and close_location >= 0.70:
        return "BUY"
    if closes[index] < prior_low and close_location <= 0.30:
        return "SELL"
    return None


def analyze(market, symbol, rows, timeframe="15m", include_micro=False):
    """Analyze one market and one timeframe independently; only closed candles count."""
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES or not isinstance(rows, list) or len(rows) < 55:
        return None
    try:
        bars = rows[:-1]  # Exclude the provider's potentially-forming candle.
        if len(bars) < 50:
            return None
        o = [float(x[1]) for x in bars]
        h = [float(x[2]) for x in bars]
        l = [float(x[3]) for x in bars]
        c = [float(x[4]) for x in bars]
        v = [float(x[5] or 0) for x in bars]
        if not all(math.isfinite(z) for seq in (o, h, l, c, v) for z in seq):
            return None
        if any(x <= 0 for x in c[-55:]) or any(x < 0 for x in v[-55:]):
            return None
        i = len(bars) - 1
        atr_values = _atr(h, l, c, 14)
        atr = atr_values[i]
        if atr is None or atr <= 0:
            return None

        fast = _ema(c, 9)
        slow = _ema(c, 21)
        trend_period = min(100, max(30, len(c) // 2))
        trend = _ema(c, trend_period)
        macd_line, macd_signal = _macd(c)
        rsi = _rsi(c, 14)
        if any(x is None for x in (fast[i], slow[i], trend[i], macd_line[i],
                                    macd_signal[i], rsi[i])):
            return None

        votes = {}
        if fast[i] > slow[i] and c[i] > trend[i]:
            votes["EMA trend"] = "BUY"
        elif fast[i] < slow[i] and c[i] < trend[i]:
            votes["EMA trend"] = "SELL"

        if macd_line[i] > macd_signal[i] and c[i] > trend[i]:
            votes["MACD trend"] = "BUY"
        elif macd_line[i] < macd_signal[i] and c[i] < trend[i]:
            votes["MACD trend"] = "SELL"

        if rsi[i] >= 52 and c[i] > trend[i]:
            votes["RSI trend"] = "BUY"
        elif rsi[i] <= 48 and c[i] < trend[i]:
            votes["RSI trend"] = "SELL"

        volume_vote = _volume_breakout_vote(h, l, c, v, i)
        if volume_vote:
            votes["NFI-style volume breakout"] = volume_vote

        buys = sum(1 for side in votes.values() if side == "BUY")
        sells = sum(1 for side in votes.values() if side == "SELL")
        if buys >= 2 and buys > sells:
            side, confirmations = "BUY", buys
        elif sells >= 2 and sells > buys and profile["allow_short"]:
            side, confirmations = "SELL", sells
        else:
            return None

        entry = c[i]
        risk = atr
        direction = 1.0 if side == "BUY" else -1.0
        stop = entry - direction * risk
        tp1 = entry + direction * risk
        tp2 = entry + direction * risk * 2.0
        tp3 = entry + direction * risk * 3.0
        if min(entry, stop, tp1, tp2, tp3) <= 0:
            return None

        aligned = [name for name, vote in votes.items() if vote == side]
        score = min(96.0, 60.0 + confirmations * 8.0 + (5.0 if volume_vote == side else 0.0))
        previous_close = c[i - 1] if i > 0 else entry
        return {
            "side": side, "entry": entry, "stop": stop,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "score": round(score, 1), "timeframe": timeframe,
            "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
            "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
            "reason": "OPEN_SOURCE ENSEMBLE: " + " + ".join(aligned) + "; ATR(14) stop 1R, targets 1R/2R/3R",
            "signal_candle_time": int(float(bars[-1][0])),
            "risk_atr": 1.0, "reward_risk": 3.0,
            "atr": atr, "confirmations": confirmations,
            "strategy_votes": votes,
            "strategy": "OPEN_SOURCE_ENSEMBLE_" + market.upper() + "_" + timeframe,
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
