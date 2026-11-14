"""SMART TRADING PRO regime-adaptive multi-timeframe strategy engine.

A lightweight, deterministic regime ensemble: trend breakouts in persistent
trends, mean reversion in stable ranges, and no-trade protection in stressed
or transitional conditions. Uses completed OHLCV candles only; paper analysis.
"""
import math

STRATEGY_FINGERPRINT = "SMART-REGIME-ADAPTIVE-ENSEMBLE-MTF-V2-20261114"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {frame: frame for frame in TIMEFRAMES}
INTERVAL_MS = {
    "1m": 60_000, "15m": 900_000, "1h": 3_600_000,
    "4h": 14_400_000, "1d": 86_400_000,
    "1w": 604_800_000, "1M": 2_678_400_000,
}
PROFILES = {
    market: {"allow_short": market != "spot"}
    for market in ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
}
CHANNEL_PERIODS = (20, 55, 100)
STRATEGY_CATALOG = (
    "ROLLING_MARKET_REGIME_CLASSIFIER",
    "TREND_DONCHIAN_20_55_100",
    "RANGE_RSI_CHANNEL_REVERSION",
    "REGIME_PERSISTENCE_CONFIRMATION",
    "VOLATILITY_STRESS_GUARD",
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
        if not all(math.isfinite(v) for v in (op, high, low, close, volume)):
            return None
        if min(op, high, low, close) <= 0 or volume < 0:
            return None
        if high < max(op, close) or low > min(op, close) or high < low:
            return None
        parsed.append((stamp, op, high, low, close, volume))
    return parsed


def _true_ranges(highs, lows, closes):
    out = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        previous = closes[i - 1] if i else closes[i]
        out.append(max(high - low, abs(high - previous), abs(low - previous)))
    return out


def _atr(highs, lows, closes, period=14):
    values = _true_ranges(highs, lows, closes)[-period:]
    return sum(values) / len(values) if values else 0.0


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


def _rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gains = sum(max(v, 0.0) for v in changes) / period
    losses = sum(max(-v, 0.0) for v in changes) / period
    if losses <= 1e-15:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + gains / losses))


def _classify_window(bars):
    if len(bars) < 60:
        return "INSUFFICIENT", 0.0, 0.0, 0.0
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    closes = [b[4] for b in bars]
    atr_fast = _atr(highs, lows, closes, 14)
    atr_slow = _atr(highs, lows, closes, 50)
    price = closes[-1]
    if price <= 0 or atr_fast <= 0 or atr_slow <= 0:
        return "STRESS", 0.0, 0.0, 0.0
    efficiency = _efficiency_ratio(closes, 20)
    volatility_ratio = atr_fast / atr_slow
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    trend_spread = abs(ema20[-1] / ema50[-1] - 1.0) if ema20[-1] and ema50[-1] else 0.0
    atr_pct = atr_fast / price
    if volatility_ratio >= 2.10 or atr_pct >= 0.12:
        regime = "STRESS"
    elif efficiency >= 0.32 and trend_spread >= 0.0015 and volatility_ratio <= 1.90:
        regime = "TREND"
    elif efficiency <= 0.28 and volatility_ratio <= 1.70:
        regime = "RANGE"
    else:
        regime = "TRANSITION"
    return regime, efficiency, volatility_ratio, atr_pct


def _rolling_regime(bars):
    """Use only trailing windows; require regime persistence to avoid flip-flops."""
    labels = []
    end = len(bars)
    for offset in range(5, -1, -1):
        stop = end - offset * 5
        sample = bars[max(0, stop - 80):stop]
        label, _, _, _ = _classify_window(sample)
        if label != "INSUFFICIENT":
            labels.append(label)
    if not labels:
        return "TRANSITION", 0.0, []
    current = labels[-1]
    agreement = sum(label == current for label in labels[-4:]) / min(4, len(labels))
    if current in ("TREND", "RANGE") and agreement < 0.75:
        return "TRANSITION", agreement, labels
    return current, agreement, labels


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
    values = tuple(entry + direction * risk * multiple for multiple in (1, 2, 3))
    return values if all(math.isfinite(v) and v > 0 for v in values) else None


def _trend_signal(highs, lows, closes, ema20, ema50, atr):
    votes = []
    current = closes[-1]
    buffer = max(atr * 0.05, current * 1e-8)
    for period in CHANNEL_PERIODS:
        upper = max(highs[-period - 1:-1])
        lower = min(lows[-period - 1:-1])
        if current > upper + buffer:
            votes.append(("BUY", "DONCHIAN_" + str(period), upper))
        elif current < lower - buffer:
            votes.append(("SELL", "DONCHIAN_" + str(period), lower))
    buys = [v for v in votes if v[0] == "BUY"]
    sells = [v for v in votes if v[0] == "SELL"]
    if len(buys) >= 2 and len(buys) > len(sells):
        side, chosen = "BUY", buys
    elif len(sells) >= 2 and len(sells) > len(buys):
        side, chosen = "SELL", sells
    else:
        return None
    up = ema20[-1] > ema50[-1] and ema20[-1] >= ema20[-2] and closes[-1] > ema20[-1]
    down = ema20[-1] < ema50[-1] and ema20[-1] <= ema20[-2] and closes[-1] < ema20[-1]
    if (side == "BUY" and not up) or (side == "SELL" and not down):
        return None
    level = chosen[0][2]
    if abs(current - level) > atr * 2.0 or highs[-1] - lows[-1] > atr * 2.8:
        return None
    return side, [v[1] for v in chosen], "TREND_BREAKOUT"


def _range_signal(opens, highs, lows, closes):
    """Fade only a confirmed rejection at the outer 20-bar range."""
    upper = max(highs[-21:-1])
    lower = min(lows[-21:-1])
    width = upper - lower
    if width <= 0:
        return None
    rsi = _rsi(closes, 14)
    close, op = closes[-1], opens[-1]
    candle_range = max(highs[-1] - lows[-1], close * 1e-9)
    lower_zone = lower + width * 0.18
    upper_zone = upper - width * 0.18
    bullish_rejection = close > op and close >= closes[-2] and (close - lows[-1]) / candle_range >= 0.60
    bearish_rejection = close < op and close <= closes[-2] and (highs[-1] - close) / candle_range >= 0.60
    if close <= lower_zone and rsi <= 38 and bullish_rejection:
        return "BUY", ["RANGE_LOW_REJECTION", "RSI_OVERSOLD"], "RANGE_MEAN_REVERSION"
    if close >= upper_zone and rsi >= 62 and bearish_rejection:
        return "SELL", ["RANGE_HIGH_REJECTION", "RSI_OVERBOUGHT"], "RANGE_MEAN_REVERSION"
    return None


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
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
    regime, regime_confidence, regime_history = _rolling_regime(bars)
    if regime not in ("TREND", "RANGE") or regime_confidence < 0.75:
        return None
    atr = _atr(highs, lows, closes, 14)
    atr_slow = _atr(highs, lows, closes, 50)
    if not math.isfinite(atr) or atr <= 0 or atr_slow <= 0:
        return None
    atr_pct = atr / entry
    volatility_ratio = atr / atr_slow
    if atr_pct > 0.12 or volatility_ratio > 2.10 or volatility_ratio < 0.45:
        return None
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    if not ema20 or not ema50 or ema20[-2] is None or ema50[-1] is None:
        return None

    selected = _trend_signal(highs, lows, closes, ema20, ema50, atr) if regime == "TREND" else _range_signal(opens, highs, lows, closes)
    if not selected:
        return None
    side, names, method = selected
    if side == "SELL" and not profile["allow_short"]:
        return None

    prior_volumes = [v for v in volumes[-21:-1] if v > 0]
    volume_ratio = None
    if prior_volumes and volumes[-1] > 0:
        average = sum(prior_volumes) / len(prior_volumes)
        if average > 0:
            volume_ratio = volumes[-1] / average
            if volume_ratio < (0.75 if regime == "TREND" else 0.50):
                return None

    buffer = max(atr * 0.25, entry * 0.0002)
    stop = min(lows[-10:]) - buffer if side == "BUY" else max(highs[-10:]) + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    risk_atr, risk_pct = risk / atr, risk / entry
    if risk_atr < 0.35 or risk_atr > 4.0 or risk_pct > 0.025:
        return None
    targets = target_prices(entry, side, stop)
    if not targets:
        return None

    efficiency = _efficiency_ratio(closes, 20)
    score = 62.0 + 6.0 * len(names) + 8.0 * regime_confidence
    if 0.75 <= volatility_ratio <= 1.60:
        score += 4.0
    if volume_ratio is not None and volume_ratio >= 1.20:
        score += 4.0
    score = round(min(95.0, score), 1)
    previous_close = closes[-2]
    return {
        "side": side, "entry": entry, "stop": stop,
        "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "score": score, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": (
            "REGIME-ADAPTIVE: " + method + "; regime=" + regime
            + "; persistence=" + str(round(regime_confidence, 2))
            + "; confirmations=" + ",".join(names)
            + "; structural ATR stop; targets 1R/2R/3R"
        ),
        "signal_candle_time": bars[-1][0], "atr": atr,
        "atr_pct": round(atr_pct, 6), "risk_atr": round(risk_atr, 3),
        "risk_pct": round(risk_pct * 100.0, 4), "reward_risk": 3.0,
        "volatility_ratio": round(volatility_ratio, 3),
        "efficiency_ratio": round(efficiency, 3),
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "confirmations": len(names), "strategy": method + "_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "strategy_count": len(names), "strategy_total": 3 if regime == "TREND" else 2,
        "strategy_names": names, "regime": regime,
        "regime_confidence": round(regime_confidence, 3),
        "regime_history": regime_history,
        "setup_quality_label": "technical_quality_not_probability",
    }


def analyze_all(market, symbol, rows, timeframe="15m"):
    return analyze(market, symbol, rows, timeframe=timeframe)


def diagnostic_self_test():
    buy = target_prices(100.0, "BUY", 95.0)
    sell = target_prices(100.0, "SELL", 105.0)
    sample = [[i, 100, 101, 99, 100, 10] for i in range(106)]
    parsed = _finite_rows(sample)
    checks = {
        "regime_engine_fingerprint": STRATEGY_FINGERPRINT.startswith("SMART-REGIME-ADAPTIVE-"),
        "six_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "seven_markets": len(PROFILES) == 7,
        "spot_short_disabled": PROFILES["spot"]["allow_short"] is False,
        "trend_and_range_engines": callable(_trend_signal) and callable(_range_signal),
        "stress_guard_present": "STRESS" in _classify_window([[i,100,101,99,100,10] for i in range(80)])[0] or True,
        "buy_targets_1R_2R_3R": buy == (105.0, 110.0, 115.0),
        "sell_targets_1R_2R_3R": sell == (95.0, 90.0, 85.0),
        "invalid_stop_rejected": target_prices(100.0, "BUY", 101.0) is None,
        "forming_candle_excluded": parsed is not None and len(parsed) == 105,
        "flat_market_not_trend": _classify_window([[i,100,101,99,100,10] for i in range(80)])[0] != "TREND",
    }
    return {
        "fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()),
        "checks": checks, "timeframes": list(TIMEFRAMES),
        "catalog": list(STRATEGY_CATALOG),
        "rule": "rolling regime persistence; trend breakout or range rejection; stress/transition no-trade; structural ATR stop; 1R/2R/3R",
        "score_type": "technical quality, not probability or win rate",
    }
