"""Market-specific, OHLCV-only strategy gates.

These rules are research candidates, not validated profitable systems. They use
completed candles only and deliberately return no trade when a market-specific
setup is absent. Provider-dependent markets remain unavailable.
"""
from statistics import mean, median
from math import isfinite


MARKET_STRATEGIES = {
    "spot": "spot_trend_breakout_long_only",
    "futures": "usd_m_trend_continuation",
    "coinm": "coin_m_liquidity_sweep_reversal",
    "alpha": "alpha_high_momentum_volume_breakout",
    "saudi": "saudi_compression_volume_breakout_long_only",
    "us": "us_equity_trend_pullback_long_only",
    "forex": "forex_range_expansion_breakout",
    "contracts": "unavailable_no_verified_provider",
}


def _valid_bars(rows):
    result = []
    for row in rows if isinstance(rows, (list, tuple)) else []:
        if not isinstance(row, dict):
            continue
        try:
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            v = max(0.0, float(row.get("volume", 0) or 0))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not all(isfinite(x) and x > 0 for x in (o, h, l, c)) or h < max(o, c, l) or l > min(o, c, h):
            continue
        result.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return result


def evaluate_market_strategy(market, rows, current_price=None):
    """Return a market-specific directional setup or a transparent rejection."""
    strategy = MARKET_STRATEGIES.get(market)
    if not strategy:
        return {"confirmed": False, "reason": "unknown_market", "strategy": None}
    if market == "contracts":
        return {"confirmed": False, "reason": "provider_required", "strategy": strategy}
    bars = _valid_bars(rows)
    if len(bars) < 35:
        return {"confirmed": False, "reason": "insufficient_candles", "strategy": strategy,
                "candles_used": len(bars)}
    close = float(current_price or bars[-1]["close"])
    if not isfinite(close) or close <= 0:
        return {"confirmed": False, "reason": "invalid_price", "strategy": strategy}

    last = bars[-1]
    prior = bars[-21:-1]
    prior12 = bars[-13:-1]
    if len(prior) < 20 or len(prior12) < 12:
        return {"confirmed": False, "reason": "insufficient_reference_window", "strategy": strategy}
    baseline_volume = median(x["volume"] for x in prior if x["volume"] > 0)
    if not baseline_volume:
        return {"confirmed": False, "reason": "missing_volume", "strategy": strategy}
    volume_ratio = last["volume"] / baseline_volume
    mean20 = mean(x["close"] for x in bars[-20:])
    momentum = close / bars[-5]["close"] - 1.0
    recent = bars[-5:]
    older = bars[-10:-5]
    rising_structure = (max(x["high"] for x in recent) > max(x["high"] for x in older)
                       and min(x["low"] for x in recent) > min(x["low"] for x in older))
    falling_structure = (max(x["high"] for x in recent) < max(x["high"] for x in older)
                        and min(x["low"] for x in recent) < min(x["low"] for x in older))
    range_high = max(x["high"] for x in prior12)
    range_low = min(x["low"] for x in prior12)
    candle_range = max(last["high"] - last["low"], close * 1e-9)
    close_position = (last["close"] - last["low"]) / candle_range
    side = None
    reason = "market_specific_setup_not_confirmed"

    if market == "spot":
        if close > mean20 and rising_structure and close > range_high and momentum > 0 and volume_ratio >= 1.15:
            side, reason = "BUY", "spot_trend_breakout_with_relative_volume"
    elif market == "futures":
        if close > mean20 and rising_structure and momentum > 0.001 and volume_ratio >= 1.10 and close_position >= 0.65:
            side, reason = "BUY", "usd_m_bullish_trend_continuation"
        elif close < mean20 and falling_structure and momentum < -0.001 and volume_ratio >= 1.10 and close_position <= 0.35:
            side, reason = "SELL", "usd_m_bearish_trend_continuation"
    elif market == "coinm":
        if last["low"] < range_low and close > range_low and last["close"] > last["open"] and volume_ratio >= 1.10:
            side, reason = "BUY", "coin_m_sell_side_sweep_reclaim"
        elif last["high"] > range_high and close < range_high and last["close"] < last["open"] and volume_ratio >= 1.10:
            side, reason = "SELL", "coin_m_buy_side_sweep_rejection"
    elif market == "alpha":
        alpha_high = max(x["high"] for x in bars[-9:-1])
        if close > alpha_high and close > mean20 and momentum >= 0.004 and volume_ratio >= 1.35 and close_position >= 0.75:
            side, reason = "BUY", "alpha_strict_momentum_volume_breakout"
        elif close < mean20 and momentum <= -0.006 and volume_ratio >= 1.50 and close_position <= 0.20:
            side, reason = "SELL", "alpha_strict_downside_momentum"
    elif market == "saudi":
        compression = (range_high - range_low) / close
        if compression <= 0.045 and close > range_high and close > mean20 and volume_ratio >= 1.20 and close_position >= 0.70:
            side, reason = "BUY", "saudi_compression_expansion_breakout"
    elif market == "us":
        if close > mean20 and rising_structure and last["close"] > last["open"] and momentum > 0 and volume_ratio >= 1.15:
            side, reason = "BUY", "us_equity_trend_pullback_recovery"
    elif market == "forex":
        if close > range_high and momentum > 0 and volume_ratio >= 1.05 and close_position >= 0.70:
            side, reason = "BUY", "forex_range_expansion_up"
        elif close < range_low and momentum < 0 and volume_ratio >= 1.05 and close_position <= 0.30:
            side, reason = "SELL", "forex_range_expansion_down"

    if not side:
        return {
            "confirmed": False, "reason": reason, "strategy": strategy,
            "volume_ratio": round(volume_ratio, 3), "momentum_percent": round(momentum * 100, 3),
            "structure": "up" if rising_structure else "down" if falling_structure else "mixed",
        }
    score = min(95.0, 55.0 + min(20.0, max(0.0, (volume_ratio - 1.0) * 20.0))
                + min(20.0, abs(momentum) * 1000.0))
    return {
        "confirmed": True, "side": side, "strategy": strategy, "reason": reason,
        "quality_score": round(score, 1), "volume_ratio": round(volume_ratio, 3),
        "momentum_percent": round(momentum * 100, 3),
        "structure": "up" if rising_structure else "down" if falling_structure else "mixed",
    }
