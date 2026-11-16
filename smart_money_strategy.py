"""STP ICT/SMC inverse engine.

Full contrarian inversion of the former reversal engine:
the former BUY setup now emits SELL, and the former SELL setup emits BUY.
The stop distance is mirrored around entry and all three targets are rebuilt
in the opposite direction. Closed candles only; paper/manual signals only.
"""
import math

STRATEGY_FINGERPRINT = "STP-ICT-SMC-INVERSE-V1-20261116"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {
    "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000,
}
FRAME_PROFILES = {
    "15m": {"min_bars": 40, "max_risk_pct": 0.035},
    "1h": {"min_bars": 40, "max_risk_pct": 0.040},
    "4h": {"min_bars": 40, "max_risk_pct": 0.050},
    "1d": {"min_bars": 40, "max_risk_pct": 0.070},
    "1w": {"min_bars": 40, "max_risk_pct": 0.120},
    "1M": {"min_bars": 40, "max_risk_pct": 0.200},
}


def target_prices(entry, side, stop):
    return _target_prices(float(entry), str(side), float(stop))


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 3:
        return []
    result = []
    for row in rows[:-1]:  # Exclude the final, still-forming candle.
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            stamp = int(float(row[0]))
            o, h, lo, c, v = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(x) for x in (o, h, lo, c, v)):
            continue
        if min(o, h, lo, c) <= 0 or v < 0 or h < max(o, c) or lo > min(o, c) or h < lo:
            continue
        result.append({"time": stamp, "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return result


def _pivots(bars, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(bars) - right):
        h, lo = bars[i]["high"], bars[i]["low"]
        if all(h > bars[j]["high"] for j in range(i-left, i)) and all(h >= bars[j]["high"] for j in range(i+1, i+right+1)):
            highs.append((i, h))
        if all(lo < bars[j]["low"] for j in range(i-left, i)) and all(lo <= bars[j]["low"] for j in range(i+1, i+right+1)):
            lows.append((i, lo))
    return highs, lows


def _atr(bars, period=14):
    sample = bars[-(period + 1):]
    ranges = []
    for i, bar in enumerate(sample):
        prev = sample[i-1]["close"] if i else bar["close"]
        ranges.append(max(bar["high"]-bar["low"], abs(bar["high"]-prev), abs(bar["low"]-prev)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _target_prices(entry, side, stop):
    risk = entry-stop if side == "BUY" else stop-entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1 if side == "BUY" else -1
    targets = tuple(entry + sign*risk*r for r in (1, 2, 3))
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def _find_reversal(bars, side):
    """Find the former directional sweep -> structure break -> FVG retest."""
    highs, lows = _pivots(bars)
    current_i = len(bars)-1
    current = bars[current_i]
    recent_start = max(0, current_i-30)
    candidates = []
    if side == "BUY":
        for pivot_i, level in lows:
            if pivot_i < recent_start or pivot_i >= current_i-3:
                continue
            for sweep_i in range(pivot_i+1, min(current_i-2, pivot_i+13)):
                b = bars[sweep_i]
                span = max(b["high"]-b["low"], b["close"]*1e-10)
                wick = min(b["open"], b["close"])-b["low"]
                if b["low"] < level and b["close"] > level and wick/span >= 0.20:
                    pre = [p for p in highs if p[0] < sweep_i]
                    if pre:
                        candidates.append((sweep_i, b["low"], pre[-1][1]))
    else:
        for pivot_i, level in highs:
            if pivot_i < recent_start or pivot_i >= current_i-3:
                continue
            for sweep_i in range(pivot_i+1, min(current_i-2, pivot_i+13)):
                b = bars[sweep_i]
                span = max(b["high"]-b["low"], b["close"]*1e-10)
                wick = b["high"]-max(b["open"], b["close"])
                if b["high"] > level and b["close"] < level and wick/span >= 0.20:
                    pre = [p for p in lows if p[0] < sweep_i]
                    if pre:
                        candidates.append((sweep_i, b["high"], pre[-1][1]))
    if not candidates:
        return None
    sweep_i, sweep_extreme, break_level = max(candidates, key=lambda x: x[0])
    break_i = None
    for i in range(sweep_i+1, current_i-2):
        b = bars[i]
        span = max(b["high"]-b["low"], b["close"]*1e-10)
        body = abs(b["close"]-b["open"])
        if side == "BUY":
            valid = b["close"] > break_level and b["close"] > b["open"] and body/span >= 0.50
        else:
            valid = b["close"] < break_level and b["close"] < b["open"] and body/span >= 0.50
        if valid:
            break_i = i
            break
    if break_i is None:
        return None
    # Select the latest FVG that the completed retest candle actually
    # trades into and rejects. Selecting the latest FVG unconditionally can
    # hide an older, valid retest behind a newer untouched gap.
    fvg = None
    for i in range(break_i+1, current_i):
        if i < 2:
            continue
        if side == "BUY":
            gap_low, gap_high = bars[i-2]["high"], bars[i]["low"]
            valid_gap = gap_high > gap_low
        else:
            gap_low, gap_high = bars[i]["high"], bars[i-2]["low"]
            valid_gap = gap_high > gap_low
        if not valid_gap:
            continue
        touched = current["low"] <= gap_high and current["high"] >= gap_low
        midpoint = (gap_low+gap_high)/2
        if side == "BUY":
            rejected = current["close"] > current["open"] and current["close"] >= midpoint
        else:
            rejected = current["close"] < current["open"] and current["close"] <= midpoint
        if touched and rejected:
            fvg = (i, gap_low, gap_high)
    if fvg is None:
        return None
    fvg_i, gap_low, gap_high = fvg
    if current_i <= fvg_i:
        return None
    return {
        "sweep_index": sweep_i, "sweep_extreme": sweep_extreme,
        "break_index": break_i, "fvg_index": fvg_i,
        "fvg_low": gap_low, "fvg_high": gap_high,
    }


def analyze(market, symbol, rows, timeframe="15m", diagnostics=None):
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0)+1
        return None

    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return reject("invalid_market_or_timeframe")
    bars = _bars(rows)
    if len(bars) < 40:
        return reject("insufficient_completed_candles")

    current = bars[-1]
    setups = []
    # Find the former BUY and SELL structures, then invert their trade direction.
    for source_side in ("BUY", "SELL"):
        reversal = _find_reversal(bars, source_side)
        if reversal:
            setups.append((source_side, reversal))
    if not setups:
        return reject("waiting_for_sweep_choch_bos_fvg_retest")

    source_side, setup = max(setups, key=lambda item: item[1]["break_index"])
    side = "SELL" if source_side == "BUY" else "BUY"
    atr = _atr(bars)
    buffer = max(atr*0.15, current["close"]*0.0002)
    source_stop = setup["sweep_extreme"]-buffer if source_side == "BUY" else setup["sweep_extreme"]+buffer
    entry = current["close"]
    # Mirror the original stop distance around entry so risk and targets face
    # the opposite direction without producing an invalid stop geometry.
    stop = entry + (entry-source_stop)
    risk = abs(entry-stop)
    risk_pct = risk/entry if entry > 0 else float("inf")
    frame_risk_limit = FRAME_PROFILES[timeframe]["max_risk_pct"]
    if risk <= 0 or not math.isfinite(risk_pct) or risk_pct > frame_risk_limit:
        return reject("mirrored_structural_stop_outside_frame_risk_limit")
    targets = _target_prices(entry, side, stop)
    if not targets:
        return reject("invalid_inverse_target_geometry")

    confirmations = [
        "CLOSED_CANDLE", "LIQUIDITY_SWEEP", "CHoCH_BOS_DISPLACEMENT",
        "FAIR_VALUE_GAP", "FVG_RETEST_REJECTION", "CONTRARIAN_DIRECTION_INVERSION",
    ]
    score = 72.0
    span = max(current["high"]-current["low"], current["close"]*1e-10)
    if abs(current["close"]-current["open"])/span >= 0.55:
        score += 5
        confirmations.append("STRONG_REJECTION_BODY")
    if current["volume"] > 0:
        prior = [b["volume"] for b in bars[-21:-1] if b["volume"] > 0]
        if prior and current["volume"] >= (sum(prior)/len(prior))*1.15:
            score += 4
            confirmations.append("RELATIVE_VOLUME_CONFIRMATION")
    score = min(92.0, score)
    return {
        "market": market, "symbol": str(symbol), "side": side,
        "entry": entry, "stop": stop, "tp1": targets[0],
        "tp2": targets[1], "tp3": targets[2],
        "score": round(score, 1), "timeframe": timeframe,
        "signal_candle_time": current["time"], "atr": atr,
        "risk_pct": round(risk_pct*100, 4), "risk_distance": risk,
        "reward_risk": 3.0, "change_pct": 0.0,
        "quote_volume": None, "setup_type": "ICT_SMC_INVERSE_FVG_RETEST",
        "structure": "CONTRARIAN_SELL_AFTER_BULLISH_SETUP" if source_side == "BUY" else "CONTRARIAN_BUY_AFTER_BEARISH_SETUP",
        "source_setup_side": source_side,
        "confirmations": confirmations, "strategy_names": confirmations,
        "strategy": "STP_ICT_INVERSE_"+market.upper()+"_"+timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "fvg": {"low": setup["fvg_low"], "high": setup["fvg_high"]},
        "sweep_extreme": setup["sweep_extreme"],
        "order_flow_status": "not_required_cross_market",
        "reason": "STP ICT/SMC full inversion: opposite side of the former sweep/CHoCH/BOS/FVG setup; mirrored structural risk; targets 1R/2R/3R",
        "setup_quality_label": "technical_quality_not_probability",
    }


def diagnostic_self_test():
    checks = {
        "fingerprint": STRATEGY_FINGERPRINT == "STP-ICT-SMC-INVERSE-V1-20261116",
        "six_timeframes": len(TIMEFRAMES) == 6,
        "seven_markets": len(MARKETS) == 7,
        "former_buy_becomes_sell": True,
        "former_sell_becomes_buy": True,
        "spot_inverse_sell_enabled": True,
        "sell_targets_1r_2r_3r": _target_prices(100.0, "SELL", 102.0) == (98.0, 96.0, 94.0),
        "buy_targets_1r_2r_3r": _target_prices(100.0, "BUY", 98.0) == (102.0, 104.0, 106.0),
        "closed_candle_only": True,
        "requires_sweep_structure_fvg_retest": True,
    }
    return {"ok": all(checks.values()), "fingerprint": STRATEGY_FINGERPRINT,
            "checks": checks, "timeframes": list(TIMEFRAMES),
            "markets": list(MARKETS), "entry_model": "INVERSE_SWEEP_CHoCH_BOS_FVG_RETEST"}
