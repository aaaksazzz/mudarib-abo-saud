"""SMART FLOW: swing breakout confirmed by a mandatory Fair Value Gap (FVG)."""
import math

STRATEGY_FINGERPRINT = "SMART-FLOW-BREAKOUT-FVG-MTF-V1-20261111"
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
    ph, pl = [], []
    for i in range(left, len(highs) - right):
        if highs[i] >= max(highs[i-left:i]) and highs[i] > max(highs[i+1:i+right+1]):
            ph.append(i)
        if lows[i] <= min(lows[i-left:i]) and lows[i] < min(lows[i+1:i+right+1]):
            pl.append(i)
    return ph, pl


def _bull_fvgs(highs, lows, start):
    # Three-candle bullish imbalance: candle C low is above candle A high.
    return [(i, highs[i-2], lows[i]) for i in range(max(2, start), len(lows))
            if lows[i] > highs[i-2]]


def _bear_fvgs(highs, lows, start):
    # Three-candle bearish imbalance: candle C high is below candle A low.
    return [(i, highs[i], lows[i-2]) for i in range(max(2, start), len(lows))
            if highs[i] < lows[i-2]]


def target_prices(entry, side, stop=None):
    """Risk ladder retained for the UI; the structural previous swing is the primary target."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0 or stop <= 0 or side not in ("BUY", "SELL"):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    result = tuple(entry + sign * risk * n for n in (1, 2, 3))
    return result if all(math.isfinite(x) and x > 0 for x in result) else None


def _buy_setup(highs, lows, opens, closes, atr, pivot_highs, pivot_lows):
    n = len(closes)
    for pivot in reversed([p for p in pivot_highs if p >= n - 60]):
        breakout = next((j for j in range(pivot + 1, n - 1) if closes[j] > highs[pivot]), None)
        if breakout is None:
            continue
        gaps = [g for g in _bull_fvgs(highs, lows, breakout) if g[2] < closes[-1] and g[1] < closes[-1]]
        if not gaps:
            continue
        gap_idx, gap_low, gap_high = gaps[-1]
        if gap_idx < n - 12 or gap_low >= gap_high:
            continue
        # Gap must remain below price; accept a touch/retest, reject a fully traded-through gap.
        if lows[-1] < gap_low or closes[-1] <= gap_high:
            continue
        lows_below_gap = [p for p in pivot_lows if p < gap_idx and lows[p] < gap_low]
        if not lows_below_gap:
            continue
        stop_anchor = lows[lows_below_gap[-1]]
        targets = [highs[p] for p in pivot_highs if p < pivot and highs[p] > closes[-1]]
        if not targets:
            continue
        return {"side": "BUY", "breakout": breakout, "gap_index": gap_idx,
                "gap_low": gap_low, "gap_high": gap_high, "stop_anchor": stop_anchor,
                "target": min(targets), "broken_level": highs[pivot], "pivot": pivot}
    return None


def _sell_setup(highs, lows, opens, closes, atr, pivot_highs, pivot_lows):
    n = len(closes)
    for pivot in reversed([p for p in pivot_lows if p >= n - 60]):
        breakdown = next((j for j in range(pivot + 1, n - 1) if closes[j] < lows[pivot]), None)
        if breakdown is None:
            continue
        gaps = [g for g in _bear_fvgs(highs, lows, breakdown) if g[1] > closes[-1] and g[2] > closes[-1]]
        if not gaps:
            continue
        gap_idx, gap_low, gap_high = gaps[-1]
        if gap_idx < n - 12 or gap_low >= gap_high:
            continue
        if highs[-1] > gap_high or closes[-1] >= gap_low:
            continue
        highs_above_gap = [p for p in pivot_highs if p < gap_idx and highs[p] > gap_high]
        if not highs_above_gap:
            continue
        stop_anchor = highs[highs_above_gap[-1]]
        targets = [lows[p] for p in pivot_lows if p < pivot and lows[p] < closes[-1]]
        if not targets:
            continue
        return {"side": "SELL", "breakout": breakdown, "gap_index": gap_idx,
                "gap_low": gap_low, "gap_high": gap_high, "stop_anchor": stop_anchor,
                "target": max(targets), "broken_level": lows[pivot], "pivot": pivot}
    return None


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES or not isinstance(rows, list):
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 40:
        return None
    opens, highs, lows, closes = ([x[k] for x in bars] for k in (1, 2, 3, 4))
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.20:
        return None
    pivot_highs, pivot_lows = _pivots(highs, lows)
    setup = _buy_setup(highs, lows, opens, closes, atr, pivot_highs, pivot_lows)
    if not setup and profile["allow_short"]:
        setup = _sell_setup(highs, lows, opens, closes, atr, pivot_highs, pivot_lows)
    if not setup:
        return None
    side = setup["side"]
    buffer = max(atr * 0.10, entry * 0.0002)
    stop = setup["stop_anchor"] - buffer if side == "BUY" else setup["stop_anchor"] + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if risk <= 0 or risk > atr * 10 or risk > entry * 0.08:
        return None
    ladder = target_prices(entry, side, stop)
    if not ladder:
        return None
    # The previous structural swing is the primary target; only expose a signal if it is ahead of entry.
    structural_target = setup["target"]
    if (side == "BUY" and structural_target <= entry) or (side == "SELL" and structural_target >= entry):
        return None
    previous_close = closes[-2]
    return {
        "side": side, "entry": entry, "stop": stop,
        "tp1": structural_target, "tp2": ladder[1], "tp3": ladder[2],
        "score": 85.0, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": f"BREAKOUT-FVG: {side} swing break confirmed; mandatory {'bullish' if side == 'BUY' else 'bearish'} FVG; nearest structural stop; previous swing target",
        "signal_candle_time": bars[-1][0], "risk_atr": round(risk / atr, 3),
        "reward_risk": round(abs(structural_target - entry) / risk, 3), "atr": atr,
        "fvg_low": setup["gap_low"], "fvg_high": setup["gap_high"],
        "fvg_candle_time": bars[setup["gap_index"]][0],
        "swing_origin": setup["stop_anchor"], "broken_level": setup["broken_level"],
        "structural_target": structural_target, "breakout_candle_time": bars[setup["breakout"]][0],
        "confirmations": 3, "volume_ratio": None, "range_expansion": None,
        "strategy_votes": {"BUY": ["swing-high breakout", "bullish FVG below price", "nearest swing-low stop"] if side == "BUY" else [],
                           "SELL": ["swing-low breakdown", "bearish FVG above price", "nearest swing-high stop"] if side == "SELL" else []},
        "strategy": "BREAKOUT_FVG_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }


def diagnostic_self_test():
    checks = {
        "six_independent_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "both_directions_all_markets": all(PROFILES[m]["allow_short"] for m in PROFILES),
        "each_frame_uses_itself": all(SIGNAL_TIMEFRAME[x] == x for x in TIMEFRAMES),
        "bullish_fvg_definition": _bull_fvgs([10, 11, 12], [9, 10, 11], 2) == [(2, 10, 11)],
        "bearish_fvg_definition": _bear_fvgs([10, 9, 8], [11, 10, 9], 2) == [(2, 8, 11)],
        "buy_risk_ladder": target_prices(100, "BUY", 95) == (105.0, 110.0, 115.0),
        "sell_risk_ladder": target_prices(100, "SELL", 105) == (95.0, 90.0, 85.0),
        "bad_risk_rejected": target_prices(100, "BUY", 101) is None,
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()), "checks": checks,
            "timeframes": list(TIMEFRAMES), "signal_timeframes": dict(SIGNAL_TIMEFRAME),
            "rule": "swing breakout -> mandatory three-candle FVG -> nearest structural stop -> previous swing target; independent timeframe scans"}
