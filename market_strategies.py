"""SMART TRADING PRO adaptive regime-aware trend breakout engine.

One strategy replaces the legacy false-sweep and 1,000-variant voting lab.
Signals use completed candles only, multi-horizon Donchian confirmation,
trend persistence, volatility-regime controls and structural ATR risk.
Analytical / paper-only: this module never places orders.
"""
import math

STRATEGY_FINGERPRINT = "SMART-ADAPTIVE-TREND-MTF-V1-20261114"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {frame: frame for frame in TIMEFRAMES}
INTERVAL_MS = {
    "1m": 60_000, "15m": 900_000, "1h": 3_600_000,
    "4h": 14_400_000, "1d": 86_400_000,
    "1w": 604_800_000, "1M": 2_678_400_000,
}
SUPPORTED_TIMEFRAMES = tuple(INTERVAL_MS)
PROFILES = {
    market: {"allow_short": True}
    for market in ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
}

# Three genuinely different breakout horizons; each family contributes at most
# one vote. This avoids manufacturing consensus from hundreds of near-identical
# parameter combinations.
CHANNEL_PERIODS = (20, 55, 100)
STRATEGY_CATALOG = (
    "DONCHIAN_20_BREAKOUT",
    "DONCHIAN_55_BREAKOUT",
    "DONCHIAN_100_BREAKOUT",
    "TREND_PERSISTENCE_FILTER",
    "VOLATILITY_REGIME_FILTER",
    "STRUCTURAL_ATR_RISK",
)


def _finite_rows(rows):
    """Validate OHLCV rows and exclude the still-forming final candle."""
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    parsed = []
    for row in rows[:-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return None
        try:
            stamp = int(float(row[0]))
            op, high, low, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return None
        values = (op, high, low, close, volume)
        if not all(math.isfinite(value) for value in values):
            return None
        if min(op, high, low, close) <= 0 or volume < 0:
            return None
        if high < max(op, close) or low > min(op, close) or high < low:
            return None
        parsed.append((stamp, op, high, low, close, volume))
    return parsed


def _true_ranges(highs, lows, closes):
    values = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        previous = closes[i - 1] if i else closes[i]
        values.append(max(high - low, abs(high - previous), abs(low - previous)))
    return values


def _atr(highs, lows, closes, period=14):
    ranges = _true_ranges(highs, lows, closes)
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _ema(values, period):
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return [None] * (period - 1) + result


def _efficiency_ratio(values, period=20):
    if len(values) <= period:
        return 0.0
    movement = abs(values[-1] - values[-period - 1])
    noise = sum(abs(values[i] - values[i - 1]) for i in range(len(values) - period, len(values)))
    return movement / noise if noise > 0 else 0.0


def target_prices(entry, side, stop=None):
    """Return fixed 1R / 2R / 3R targets from the structural stop."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0 or stop <= 0:
        return None
    if side not in ("BUY", "SELL"):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    direction = 1.0 if side == "BUY" else -1.0
    targets = tuple(entry + direction * risk * multiple for multiple in (1, 2, 3))
    return targets if all(math.isfinite(value) and value > 0 for value in targets) else None


def _channel_votes(highs, lows, closes, atr):
    """Evaluate 20/55/100-bar close breakouts against prior bars only."""
    votes = []
    current = closes[-1]
    buffer = max(atr * 0.05, current * 1e-8)
    for period in CHANNEL_PERIODS:
        if len(closes) < period + 2:
            continue
        upper = max(highs[-period - 1:-1])
        lower = min(lows[-period - 1:-1])
        if current > upper + buffer:
            votes.append({"name": "DONCHIAN_" + str(period), "side": "BUY", "level": upper})
        elif current < lower - buffer:
            votes.append({"name": "DONCHIAN_" + str(period), "side": "SELL", "level": lower})
    return votes


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    """Generate one adaptive trend-breakout setup from completed OHLCV candles."""
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES:
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 105:
        return None

    opens, highs, lows, closes, volumes = (
        [bar[index] for bar in bars] for index in (1, 2, 3, 4, 5)
    )
    entry = closes[-1]
    atr = _atr(highs, lows, closes, 14)
    atr_slow = _atr(highs, lows, closes, 50)
    if not math.isfinite(atr) or not math.isfinite(atr_slow) or atr <= 0 or atr_slow <= 0:
        return None
    atr_pct = atr / entry
    volatility_ratio = atr / atr_slow
    # Avoid dead markets and disorderly volatility spikes. Thresholds are
    # intentionally broad and are not fitted separately to each symbol.
    if atr_pct > 0.20 or volatility_ratio < 0.55 or volatility_ratio > 2.20:
        return None

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    if not ema20 or not ema50 or ema20[-1] is None or ema50[-1] is None:
        return None
    if ema20[-2] is None or ema50[-2] is None:
        return None

    efficiency = _efficiency_ratio(closes, 20)
    if efficiency < 0.25:
        return None

    votes = _channel_votes(highs, lows, closes, atr)
    if not votes:
        return None
    buy_votes = [vote for vote in votes if vote["side"] == "BUY"]
    sell_votes = [vote for vote in votes if vote["side"] == "SELL"]
    if len(buy_votes) >= 2 and len(buy_votes) > len(sell_votes):
        side, chosen = "BUY", buy_votes
    elif len(sell_votes) >= 2 and len(sell_votes) > len(buy_votes):
        side, chosen = "SELL", sell_votes
    else:
        return None

    # Trend persistence must agree with the breakout direction.
    trend_up = ema20[-1] > ema50[-1] and ema20[-1] >= ema20[-2] and closes[-1] > ema20[-1]
    trend_down = ema20[-1] < ema50[-1] and ema20[-1] <= ema20[-2] and closes[-1] < ema20[-1]
    if side == "BUY" and not trend_up:
        return None
    if side == "SELL" and not trend_down:
        return None

    # Reject an exhausted breakout candle rather than chasing a vertical bar.
    candle_range = max(highs[-1] - lows[-1], entry * 1e-9)
    breakout_extension = abs(entry - chosen[0]["level"])
    if breakout_extension > atr * 2.0 or candle_range > atr * 2.8:
        return None

    prior_volumes = [value for value in volumes[-21:-1] if value > 0]
    current_volume = volumes[-1]
    volume_ratio = None
    if prior_volumes and current_volume > 0:
        average_volume = sum(prior_volumes) / len(prior_volumes)
        if average_volume > 0:
            volume_ratio = current_volume / average_volume
            if volume_ratio < 0.75:
                return None

    # Structural stop beyond the recent swing, with an ATR safety buffer.
    swing_window = 10
    buffer = max(atr * 0.25, entry * 0.0002)
    stop = min(lows[-swing_window:]) - buffer if side == "BUY" else max(highs[-swing_window:]) + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    risk_atr = risk / atr
    risk_pct = risk / entry
    if risk_atr < 0.35 or risk_atr > 4.0 or risk_pct > 0.025:
        return None

    targets = target_prices(entry, side, stop)
    if not targets:
        return None

    # A transparent technical-quality score, not a win probability.
    score = 60.0 + 8.0 * len(chosen)
    if efficiency >= 0.40:
        score += 5.0
    if 0.75 <= volatility_ratio <= 1.60:
        score += 5.0
    if volume_ratio is not None and volume_ratio >= 1.20:
        score += 5.0
    if breakout_extension >= atr * 0.15:
        score += 3.0
    score = round(min(95.0, score), 1)

    previous_close = closes[-2]
    return {
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp1": targets[0],
        "tp2": targets[1],
        "tp3": targets[2],
        "score": score,
        "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": (
            "ADAPTIVE REGIME TREND: confirmed close breakout across "
            + str(len(chosen)) + "/3 Donchian horizons; trend persistence and volatility regime agree; "
            "structural swing stop; targets 1R/2R/3R"
        ),
        "signal_candle_time": bars[-1][0],
        "atr": atr,
        "atr_pct": round(atr_pct, 6),
        "risk_atr": round(risk_atr, 3),
        "risk_pct": round(risk_pct * 100.0, 4),
        "reward_risk": 3.0,
        "volatility_ratio": round(volatility_ratio, 3),
        "efficiency_ratio": round(efficiency, 3),
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "confirmations": len(chosen) + 1,
        "strategy": "ADAPTIVE_REGIME_TREND_BREAKOUT_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "strategy_count": len(chosen),
        "strategy_total": len(CHANNEL_PERIODS),
        "strategy_names": [vote["name"] for vote in chosen],
        "strategy_votes": {
            "BUY": [vote["name"] for vote in buy_votes],
            "SELL": [vote["name"] for vote in sell_votes],
        },
        "setup_quality_label": "technical_quality_not_probability",
    }


def analyze_all(market, symbol, rows, timeframe="15m"):
    """Compatibility entry point used by the market scanner."""
    return analyze(market, symbol, rows, timeframe=timeframe)


def diagnostic_self_test():
    buy = target_prices(100.0, "BUY", 95.0)
    sell = target_prices(100.0, "SELL", 105.0)
    sample = [[index, 100, 101, 99, 100, 10] for index in range(106)]
    parsed = _finite_rows(sample)
    checks = {
        "adaptive_fingerprint": STRATEGY_FINGERPRINT.startswith("SMART-ADAPTIVE-TREND-"),
        "six_market_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "all_seven_markets_supported": len(PROFILES) == 7,
        "three_distinct_breakout_horizons": CHANNEL_PERIODS == (20, 55, 100),
        "buy_targets_1R_2R_3R": buy == (105.0, 110.0, 115.0),
        "sell_targets_1R_2R_3R": sell == (95.0, 90.0, 85.0),
        "invalid_stop_rejected": target_prices(100.0, "BUY", 101.0) is None,
        "forming_candle_excluded": parsed is not None and len(parsed) == 105,
        "flat_market_efficiency_zero": _efficiency_ratio([100.0] * 30, 20) == 0.0,
    }
    return {
        "fingerprint": STRATEGY_FINGERPRINT,
        "ok": all(checks.values()),
        "checks": checks,
        "timeframes": list(TIMEFRAMES),
        "catalog": list(STRATEGY_CATALOG),
        "rule": "2/3 Donchian close breakouts + directional trend persistence + volatility regime + structural ATR stop + 1R/2R/3R",
        "score_type": "technical quality, not probability or win rate",
    }
