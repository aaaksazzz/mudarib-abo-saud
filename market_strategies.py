"""SMART FLOW SWING-50: confirmed structure breakout, 50% pullback and 3R targets."""
import math

STRATEGY_FINGERPRINT = "SMART-FLOW-SWING50-MTF-V1-20261111"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {frame: frame for frame in TIMEFRAMES}
INTERVAL_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}
SUPPORTED_TIMEFRAMES = tuple(INTERVAL_MS)
PROFILES = {market: {"allow_short": True} for market in
            ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")}


def _finite_rows(rows):
    parsed = []
    for row in (rows or [])[:-1]:
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
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous), abs(lows[i] - previous)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _pivots(highs, lows, left=3, right=3):
    pivot_highs, pivot_lows = [], []
    for i in range(left, len(highs) - right):
        if highs[i] >= max(highs[i-left:i]) and highs[i] > max(highs[i+1:i+right+1]):
            pivot_highs.append(i)
        if lows[i] <= min(lows[i-left:i]) and lows[i] < min(lows[i+1:i+right+1]):
            pivot_lows.append(i)
    return pivot_highs, pivot_lows


def target_prices(entry, side, stop=None):
    """TP1=1R, TP2=2R, TP3=3R, measured from the structural stop."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0 or stop <= 0 or side not in ("BUY", "SELL"):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    direction = 1.0 if side == "BUY" else -1.0
    result = tuple(entry + direction * risk * multiple for multiple in (1, 2, 3))
    return result if all(math.isfinite(x) and x > 0 for x in result) else None


def _buy_setup(highs, lows, opens, closes, atr):
    n = len(closes)
    pivot_highs, pivot_lows = _pivots(highs, lows)
    for pivot in reversed([p for p in pivot_highs if p >= n - 45]):
        breakout = next((j for j in range(p + 4, n - 1) if closes[j] > highs[p]), None)
        if breakout is None:
            continue
        prior_lows = [x for x in pivot_lows if x < p]
        origin_idx = prior_lows[-1] if prior_lows else max(0, p - 12)
        origin = min(lows[origin_idx:p + 1])
        impulse_high = max(highs[breakout:n])
        impulse = impulse_high - origin
        if impulse <= atr or impulse_high <= highs[p]:
            continue
        midpoint = origin + impulse * 0.5
        tolerance = max(atr * 0.25, midpoint * 0.0005)
        if (lows[-1] <= midpoint + tolerance and lows[-1] >= midpoint - tolerance * 1.5
                and closes[-1] > opens[-1] and closes[-1] > midpoint):
            return origin, midpoint, impulse_high, breakout
    return None


def _sell_setup(highs, lows, opens, closes, atr):
    n = len(closes)
    pivot_highs, pivot_lows = _pivots(highs, lows)
    for pivot in reversed([p for p in pivot_lows if p >= n - 45]):
        breakout = next((j for j in range(p + 4, n - 1) if closes[j] < lows[p]), None)
        if breakout is None:
            continue
        prior_highs = [x for x in pivot_highs if x < p]
        origin_idx = prior_highs[-1] if prior_highs else max(0, p - 12)
        origin = max(highs[origin_idx:p + 1])
        impulse_low = min(lows[breakout:n])
        impulse = origin - impulse_low
        if impulse <= atr or impulse_low >= lows[p]:
            continue
        midpoint = origin - impulse * 0.5
        tolerance = max(atr * 0.25, midpoint * 0.0005)
        if (highs[-1] >= midpoint - tolerance and highs[-1] <= midpoint + tolerance * 1.5
                and closes[-1] < opens[-1] and closes[-1] < midpoint):
            return origin, midpoint, impulse_low, breakout
    return None


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES or not isinstance(rows, list):
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 35:
        return None
    opens, highs, lows, closes = ([x[k] for x in bars] for k in (1, 2, 3, 4))
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.20:
        return None
    side = None
    setup = _buy_setup(highs, lows, opens, closes, atr)
    if setup:
        side = "BUY"
    elif profile["allow_short"]:
        setup = _sell_setup(highs, lows, opens, closes, atr)
        if setup:
            side = "SELL"
    if not setup:
        return None
    origin, midpoint, impulse_extreme, breakout_idx = setup
    buffer = max(atr * 0.10, entry * 0.0002)
    stop = origin - buffer if side == "BUY" else origin + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if risk <= 0 or risk > atr * 8 or risk > entry * 0.06:
        return None
    targets = target_prices(entry, side, stop)
    if not targets:
        return None
    tp1, tp2, tp3 = targets
    previous_close = closes[-2]
    return {
        "side": side, "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "score": 80.0, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": f"SWING-50: confirmed {side} breakout; 50% impulse retracement; reversal close; structural swing stop; targets 1R/2R/3R",
        "signal_candle_time": bars[-1][0], "risk_atr": round(risk / atr, 3),
        "reward_risk": round(abs(tp3 - entry) / risk, 3), "atr": atr,
        "retracement_price": midpoint, "swing_origin": origin,
        "breakout_candle_time": bars[breakout_idx][0], "confirmations": 3,
        "volume_ratio": None, "range_expansion": None,
        "strategy_votes": {"BUY": ["swing breakout", "50% pullback", "bullish close"] if side == "BUY" else [],
                           "SELL": ["swing breakdown", "50% pullback", "bearish close"] if side == "SELL" else []},
        "strategy": "SWING50_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }


def diagnostic_self_test():
    checks = {
        "six_independent_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "both_directions_all_markets": all(PROFILES[m]["allow_short"] for m in PROFILES),
        "each_frame_uses_itself": all(SIGNAL_TIMEFRAME[x] == x for x in TIMEFRAMES),
        "buy_targets_1r_2r_3r": target_prices(100, "BUY", 95) == (105.0, 110.0, 115.0),
        "sell_targets_1r_2r_3r": target_prices(100, "SELL", 105) == (95.0, 90.0, 85.0),
        "bad_risk_rejected": target_prices(100, "BUY", 101) is None,
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()), "checks": checks,
            "timeframes": list(TIMEFRAMES), "signal_timeframes": dict(SIGNAL_TIMEFRAME),
            "rule": "confirmed swing break -> 50% retracement -> reversal close -> structural swing stop -> TP1 1R / TP2 2R / TP3 3R"}
