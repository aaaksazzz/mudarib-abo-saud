"""MA200 ONLY strategy for every supported market and timeframe.

A closed candle above its 200-period simple moving average can produce BUY only.
A closed candle below its 200-period simple moving average can produce SELL only.
The score ranks setups; it is not a win-probability estimate.
"""
import math

TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_592_000_000}
PROFILES = {market: {"allow_short": True} for market in (
    "spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex"
)}


def _finite_rows(rows):
    bars = rows[:-1]
    parsed = []
    for row in bars:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return None
        try:
            stamp = int(float(row[0]))
            op, hi, lo, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)):
            return None
        if min(op, hi, lo, close) <= 0 or volume < 0 or hi < max(op, close) or lo > min(op, close) or hi < lo:
            return None
        parsed.append((stamp, op, hi, lo, close, volume))
    return parsed


def _atr(highs, lows, closes, period=14):
    ranges = []
    for i in range(len(closes)):
        previous = closes[i - 1] if i else closes[i]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous),
                          abs(lows[i] - previous)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    if market not in PROFILES or timeframe not in TIMEFRAMES or not isinstance(rows, list):
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 200:
        return None
    closes = [bar[4] for bar in bars]
    opens = [bar[1] for bar in bars]
    highs = [bar[2] for bar in bars]
    lows = [bar[3] for bar in bars]
    volumes = [bar[5] for bar in bars]
    i = len(bars) - 1
    entry = closes[i]
    ma200 = sum(closes[-200:]) / 200.0
    if not math.isfinite(ma200) or ma200 <= 0 or entry == ma200:
        return None
    side = "BUY" if entry > ma200 else "SELL"
    direction = 1.0 if side == "BUY" else -1.0
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.12:
        return None
    candle_range = highs[i] - lows[i]
    if candle_range <= 0:
        return None
    close_location = (entry - lows[i]) / candle_range
    body_ratio = abs(entry - opens[i]) / candle_range
    if side == "BUY":
        if entry <= opens[i] or close_location < 0.55 or body_ratio < 0.25:
            return None
    else:
        if entry >= opens[i] or close_location > 0.45 or body_ratio < 0.25:
            return None
    swing_low = min(lows[max(0, i - 1):i + 1])
    swing_high = max(highs[max(0, i - 1):i + 1])
    buffer = max(atr * 0.15, entry * 0.0002)
    stop = swing_low - buffer if side == "BUY" else swing_high + buffer
    risk = abs(entry - stop)
    if risk < atr * 0.5:
        risk = atr * 0.75
        stop = entry - direction * risk
    if risk > atr * 2.5 or risk <= 0:
        return None
    tp1, tp2, tp3 = (entry + direction * risk * multiple for multiple in (1.0, 2.0, 3.0))
    if min(entry, stop, tp1, tp2, tp3) <= 0:
        return None
    ma_distance_atr = abs(entry - ma200) / atr
    volume_sample = [v for v in volumes[max(0, i - 20):i] if v > 0]
    volume_ratio = None
    if volume_sample and volumes[i] > 0:
        baseline = sum(volume_sample) / len(volume_sample)
        if baseline > 0:
            volume_ratio = volumes[i] / baseline
    score = 70.0 + min(ma_distance_atr, 2.0) * 5.0
    if volume_ratio is not None and volume_ratio >= 1.25:
        score += min(8.0, (volume_ratio - 1.0) * 4.0)
    score += 5.0 if body_ratio >= 0.6 else 0.0
    score = round(min(95.0, score), 1)
    previous_close = closes[i - 1] if i else entry
    return {
        "side": side, "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "score": score, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": "SMART FLOW QUANT: MA200 direction + closed-candle confirmation; targets 1R/2R/3R",
        "signal_candle_time": bars[-1][0], "risk_atr": round(risk / atr, 3),
        "reward_risk": 3.0, "atr": atr, "confirmations": 2,
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "ma200": ma200, "ma200_distance_pct": round((entry / ma200 - 1.0) * 100.0, 5),
        "strategy_votes": {"BUY": ["price above MA200"] if side == "BUY" else [],
                           "SELL": ["price below MA200"] if side == "SELL" else []},
        "strategy": "MA200_ONLY_" + market.upper() + "_" + timeframe,
    }
