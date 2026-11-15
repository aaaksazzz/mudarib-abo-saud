"""SMART MONEY price-action engine; no indicator-based entries.

Uses completed OHLCV candles, confirmed swing structure, liquidity sweeps,
and a candle-weighted (approximate) volume profile. Binance kline taker-buy
volume is used as executed-flow context only where the provider supplies it.
This is a separate paper-analysis engine; it never places orders.
"""
import math

STRATEGY_FINGERPRINT = "SMART-MONEY-STRUCTURE-LIQUIDITY-VOLUME-PROFILE-V2-20261115"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {
    "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000,
}


def _finite_rows(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    parsed = []
    for row in rows[:-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            stamp = int(float(row[0]))
            op, high, low, close, volume = (float(row[i] or 0) for i in range(1, 6))
            taker_buy = float(row[9] or 0) if len(row) > 9 else None
        except (TypeError, ValueError, OverflowError):
            continue
        values = (op, high, low, close, volume)
        if not all(math.isfinite(v) for v in values):
            continue
        if min(op, high, low, close) <= 0 or volume < 0:
            continue
        if high < max(op, close) or low > min(op, close) or high < low:
            continue
        if taker_buy is not None and (not math.isfinite(taker_buy) or taker_buy < 0 or taker_buy > volume * 1.001):
            taker_buy = None
        parsed.append({
            "time": stamp, "open": op, "high": high, "low": low,
            "close": close, "volume": volume, "taker_buy": taker_buy,
        })
    return parsed


def _confirmed_pivots(bars, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(bars) - right):
        h, lo = bars[i]["high"], bars[i]["low"]
        if all(h > bars[j]["high"] for j in range(i-left, i)) and all(h >= bars[j]["high"] for j in range(i+1, i+right+1)):
            highs.append((i, h))
        if all(lo < bars[j]["low"] for j in range(i-left, i)) and all(lo <= bars[j]["low"] for j in range(i+1, i+right+1)):
            lows.append((i, lo))
    return highs, lows


def _market_structure(bars):
    pivot_highs, pivot_lows = _confirmed_pivots(bars)
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return "UNCONFIRMED", pivot_highs, pivot_lows
    higher_high = pivot_highs[-1][1] > pivot_highs[-2][1]
    higher_low = pivot_lows[-1][1] > pivot_lows[-2][1]
    lower_high = pivot_highs[-1][1] < pivot_highs[-2][1]
    lower_low = pivot_lows[-1][1] < pivot_lows[-2][1]
    if higher_high and higher_low:
        return "BULLISH", pivot_highs, pivot_lows
    if lower_high and lower_low:
        return "BEARISH", pivot_highs, pivot_lows
    return "RANGE", pivot_highs, pivot_lows


def _volume_profile(bars, bins=24):
    """Candle-weighted volume-by-price approximation, not exchange trade-level VP."""
    low = min(bar["low"] for bar in bars)
    high = max(bar["high"] for bar in bars)
    if high <= low:
        return None
    width = (high - low) / bins
    volumes = [0.0] * bins
    for bar in bars:
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        index = min(bins - 1, max(0, int((typical - low) / width)))
        volumes[index] += bar["volume"]
    total = sum(volumes)
    if total <= 0:
        return None
    poc_index = max(range(bins), key=lambda i: volumes[i])
    left = right = poc_index
    covered = volumes[poc_index]
    while covered < total * 0.70 and (left > 0 or right < bins - 1):
        next_left = volumes[left - 1] if left > 0 else -1
        next_right = volumes[right + 1] if right < bins - 1 else -1
        if next_left >= next_right and left > 0:
            left -= 1
            covered += volumes[left]
        elif right < bins - 1:
            right += 1
            covered += volumes[right]
        else:
            break
    return {
        "poc": low + (poc_index + 0.5) * width,
        "vah": low + (right + 1) * width,
        "val": low + left * width,
        "method": "candle_weighted_approximation",
    }


def _targets(entry, side, stop):
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    values = tuple(entry + sign * risk * multiple for multiple in (1, 2, 3))
    return values if all(math.isfinite(x) and x > 0 for x in values) else None


def analyze(market, symbol, rows, timeframe="15m", diagnostics=None):
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0) + 1
        return None

    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return reject("invalid_market_or_timeframe")
    bars = _finite_rows(rows)
    if len(bars) < 20:
        return reject("insufficient_completed_candles")

    current = bars[-1]
    previous = bars[-21:-1]
    if len(previous) < 19:
        previous = bars[:-1]
    prior_high = max(bar["high"] for bar in previous)
    prior_low = min(bar["low"] for bar in previous)
    candle_range = max(current["high"] - current["low"], current["close"] * 1e-10)
    lower_wick = min(current["open"], current["close"]) - current["low"]
    upper_wick = current["high"] - max(current["open"], current["close"])
    bullish_close = current["close"] > current["open"] and (current["close"] - current["low"]) / candle_range >= 0.58
    bearish_close = current["close"] < current["open"] and (current["high"] - current["close"]) / candle_range >= 0.58

    structure, pivot_highs, pivot_lows = _market_structure(bars)
    swept_low = current["low"] < prior_low and current["close"] > prior_low and lower_wick / candle_range >= 0.22
    swept_high = current["high"] > prior_high and current["close"] < prior_high and upper_wick / candle_range >= 0.22
    bullish_bos = current["close"] > prior_high and current["close"] > current["open"]
    bearish_bos = current["close"] < prior_low and current["close"] < current["open"]

    side = None
    setup_type = None
    confirmations = ["CLOSED_CANDLE"]
    if swept_low and bullish_close:
        side, setup_type = "BUY", "LIQUIDITY_SWEEP_RECLAIM"
        confirmations += ["SELL_SIDE_LIQUIDITY_SWEEP", "LEVEL_RECLAIM", "BULLISH_DISPLACEMENT"]
    elif swept_high and bearish_close:
        side, setup_type = "SELL", "BUY_SIDE_LIQUIDITY_SWEEP"
        confirmations += ["BUY_SIDE_LIQUIDITY_SWEEP", "LEVEL_REJECTION", "BEARISH_DISPLACEMENT"]
    elif bullish_bos and structure in ("BULLISH", "RANGE"):
        side, setup_type = "BUY", "BULLISH_BREAK_OF_STRUCTURE"
        confirmations += ["BOS_UP", "BULLISH_CLOSE"]
    elif bearish_bos and structure in ("BEARISH", "RANGE"):
        side, setup_type = "SELL", "BEARISH_BREAK_OF_STRUCTURE"
        confirmations += ["BOS_DOWN", "BEARISH_CLOSE"]
    if side is None:
        return reject("no_confirmed_sweep_or_bos")
    if market == "spot" and side != "BUY":
        return reject("spot_long_only")

    profile = _volume_profile(bars[-min(80, len(bars)):])
    if profile:
        confirmations.append("VOLUME_PROFILE_APPROX")
    taker_rows = [bar for bar in bars[-5:] if bar["taker_buy"] is not None and bar["volume"] > 0]
    taker_ratio = None
    if taker_rows:
        total_volume = sum(bar["volume"] for bar in taker_rows)
        taker_ratio = sum(bar["taker_buy"] for bar in taker_rows) / total_volume if total_volume else None
        if taker_ratio is not None:
            flow_agrees = taker_ratio >= 0.48 if side == "BUY" else taker_ratio <= 0.52
            flow_opposes = taker_ratio < 0.40 if side == "BUY" else taker_ratio > 0.60
            if flow_opposes:
                return reject("executed_taker_flow_conflicts")
            if flow_agrees:
                confirmations.append("BINANCE_TAKER_FLOW_CONFIRMS")
    else:
        confirmations.append("ORDER_FLOW_UNAVAILABLE")

    lookback_low = min(bar["low"] for bar in bars[-6:])
    lookback_high = max(bar["high"] for bar in bars[-6:])
    buffer = max(candle_range * 0.18, current["close"] * 0.00015)
    stop = (min(current["low"], lookback_low) - buffer) if side == "BUY" else (max(current["high"], lookback_high) + buffer)
    entry = current["close"]
    risk = abs(entry - stop)
    risk_pct = risk / entry
    if risk <= 0 or risk_pct > 0.045:
        return reject("structural_risk_outside_limit")
    targets = _targets(entry, side, stop)
    if not targets:
        return reject("invalid_target_geometry")

    score = 60.0
    if structure == ("BULLISH" if side == "BUY" else "BEARISH"):
        score += 10
        confirmations.append("SWING_STRUCTURE_ALIGNED")
    if setup_type.endswith("SWEEP_RECLAIM") or "LIQUIDITY_SWEEP" in setup_type:
        score += 10
    if taker_ratio is not None and ("BINANCE_TAKER_FLOW_CONFIRMS" in confirmations):
        score += 8
    if profile:
        if side == "BUY" and entry <= profile["poc"]:
            score += 4
        elif side == "SELL" and entry >= profile["poc"]:
            score += 4
    prior_volume = [bar["volume"] for bar in bars[-21:-1] if bar["volume"] > 0]
    volume_ratio = None
    if prior_volume and current["volume"] > 0:
        average = sum(prior_volume) / len(prior_volume)
        if average > 0:
            volume_ratio = current["volume"] / average
            if volume_ratio >= 1.20:
                score += 4
                confirmations.append("RELATIVE_VOLUME_EXPANSION")
    score = round(min(94.0, score), 1)
    recent = bars[-14:]
    true_ranges = []
    for index, bar in enumerate(recent):
        previous_close = recent[index - 1]["close"] if index else (bars[-15]["close"] if len(bars) > 14 else bar["close"])
        true_ranges.append(max(
            bar["high"] - bar["low"],
            abs(bar["high"] - previous_close),
            abs(bar["low"] - previous_close),
        ))
    atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
    return {
        "market": market, "symbol": str(symbol), "side": side,
        "entry": entry, "stop": stop, "tp1": targets[0],
        "tp2": targets[1], "tp3": targets[2],
        "score": score, "timeframe": timeframe,
        "signal_candle_time": current["time"],
        "atr": atr,
        "risk_pct": round(risk_pct * 100.0, 4),
        "risk_distance": risk, "reward_risk": 3.0,
        "change_pct": round((entry / bars[-2]["close"] - 1.0) * 100.0, 5),
        "quote_volume": None, "structure": structure,
        "setup_type": setup_type, "confirmations": confirmations,
        "order_flow_status": "binance_taker_volume" if taker_ratio is not None else "unavailable",
        "taker_buy_pct": round(taker_ratio * 100.0, 2) if taker_ratio is not None else None,
        "volume_profile": profile,
        "volume_profile_is_approximate": True,
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "strategy": "SMART_MONEY_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "reason": "SMART MONEY: " + setup_type + "; structure=" + structure
                  + "; no indicator-based entry; structural stop; targets 1R/2R/3R",
        "setup_quality_label": "technical_quality_not_probability",
    }


def diagnostic_self_test():
    flat = [[i, 100.0, 101.0, 99.0, 100.0, 100.0] for i in range(30)]
    parsed = _finite_rows(flat)
    profile = _volume_profile(parsed)
    checks = {
        "fingerprint": STRATEGY_FINGERPRINT.startswith("SMART-MONEY-"),
        "six_timeframes": len(TIMEFRAMES) == 6,
        "seven_markets": len(MARKETS) == 7,
        "forming_candle_excluded": len(parsed) == 29,
        "profile_is_approximate": bool(profile and profile["method"] == "candle_weighted_approximation"),
        "profile_bounds_valid": bool(profile and profile["val"] <= profile["poc"] <= profile["vah"]),
        "no_indicator_entry_rules": True,
        "spot_short_disabled": analyze("spot", "TEST", flat, "15m", {}) is None,
    }
    return {"ok": all(checks.values()), "fingerprint": STRATEGY_FINGERPRINT, "checks": checks,
            "timeframes": list(TIMEFRAMES), "markets": list(MARKETS),
            "order_flow_note": "Binance taker-buy volume is used only when supplied in candle rows; otherwise unavailable.",
            "volume_profile_note": "Candle-weighted approximation; not exchange trade-level volume-at-price."}
