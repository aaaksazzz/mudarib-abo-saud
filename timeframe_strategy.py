"""Evidence-scored multi-timeframe strategy engine.

Scores are setup-quality points, not win probabilities. The engine uses completed
OHLCV candles only and deliberately abstains when history or directional evidence
is insufficient.
"""
from statistics import mean
from math import isfinite

TIMEFRAME_RULES = {
    "15m": ("4h", "1d"),
    "1h": ("4h", "1d"),
    "4h": ("1w", "1M"),
    "1d": ("1w", "1M"),
    "1w": ("1M",),
    "1M": (),
}
BUY_STATES = frozenset(("BUY", "STRONG_BUY"))
SELL_STATES = frozenset(("SELL", "STRONG_SELL"))


def _finite(value):
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _ema(values, period):
    if len(values) < period:
        return None
    current = mean(values[:period])
    alpha = 2.0 / (period + 1.0)
    for value in values[period:]:
        current = value * alpha + current * (1.0 - alpha)
    return current


def _rsi(closes, period=14):
    if len(closes) <= period:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes[-period:]]
    losses = [max(-change, 0.0) for change in changes[-period:]]
    avg_gain, avg_loss = mean(gains), mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def _macd_histogram(closes):
    if len(closes) < 35:
        return None
    fast_values, slow_values = [], []
    fast, slow = mean(closes[:12]), mean(closes[:26])
    fast_alpha, slow_alpha = 2 / 13, 2 / 27
    for index, close in enumerate(closes):
        if index >= 12:
            fast = close * fast_alpha + fast * (1 - fast_alpha)
        if index >= 26:
            slow = close * slow_alpha + slow * (1 - slow_alpha)
        if index >= 25:
            fast_values.append(fast)
            slow_values.append(slow)
    line = [a - b for a, b in zip(fast_values, slow_values)]
    signal = _ema(line, 9)
    return line[-1] - signal if signal is not None else None


def _normalise(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) < 60:
        return None
    bars = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        values = {key: _finite(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            return None
        if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
            return None
        if values["high"] < max(values["open"], values["close"], values["low"]):
            return None
        if values["low"] > min(values["open"], values["close"], values["high"]):
            return None
        values["volume"] = max(values["volume"] or 0.0, 0.0)
        bars.append(values)
    return bars


def assess_timeframe(rows, side=None):
    """Return directional setup points from EMA, MACD, RSI, structure and volume."""
    bars = _normalise(rows)
    if not bars:
        return {"state": "INSUFFICIENT", "score": 0.0, "buy_score": 0.0,
                "sell_score": 0.0, "reason": "need_60_valid_completed_candles"}
    closes = [bar["close"] for bar in bars]
    highs = [bar["high"] for bar in bars]
    lows = [bar["low"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    ema20, ema50, ema200 = _ema(closes, 20), _ema(closes, 50), _ema(closes, 200)
    rsi = _rsi(closes)
    macd_hist = _macd_histogram(closes)
    momentum = closes[-1] / closes[-6] - 1.0
    recent_high, prior_high = max(highs[-5:]), max(highs[-10:-5])
    recent_low, prior_low = min(lows[-5:]), min(lows[-10:-5])
    structure_up = recent_high > prior_high and recent_low > prior_low
    structure_down = recent_high < prior_high and recent_low < prior_low
    baseline_volume = mean(volumes[-21:-1]) if len(volumes) >= 21 else 0.0
    volume_ratio = volumes[-1] / baseline_volume if baseline_volume > 0 else None

    # A sweep is inferred only when a completed candle trades beyond the prior
    # 20-bar extreme and closes back inside it. This is price-action evidence,
    # not visibility into hidden resting orders.
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    last = bars[-1]
    candle_range = max(last["high"] - last["low"], 1e-12)
    body_ratio = abs(last["close"] - last["open"]) / candle_range
    bullish_sweep = last["low"] < prior_low and last["close"] > prior_low and last["close"] > last["open"]
    bearish_sweep = last["high"] > prior_high and last["close"] < prior_high and last["close"] < last["open"]
    # OHLCV-only absorption proxy: unusually high volume with a small real body
    # and a close near the directional end of the candle. It is not order-flow proof.
    bullish_absorption = bool(volume_ratio is not None and volume_ratio >= 1.5
                              and body_ratio <= 0.35
                              and last["close"] >= last["low"] + candle_range * 0.65)
    bearish_absorption = bool(volume_ratio is not None and volume_ratio >= 1.5
                              and body_ratio <= 0.35
                              and last["close"] <= last["low"] + candle_range * 0.35)

    def score_for(direction):
        score = 0.0
        if ema20 is not None and ema50 is not None:
            if direction == "BUY":
                score += 24 if closes[-1] > ema20 > ema50 else 12 if closes[-1] > ema20 else 0
            else:
                score += 24 if closes[-1] < ema20 < ema50 else 12 if closes[-1] < ema20 else 0
        if ema200 is not None:
            aligned = closes[-1] > ema200 if direction == "BUY" else closes[-1] < ema200
            score += 10 if aligned else 0
        if macd_hist is not None:
            aligned = macd_hist > 0 if direction == "BUY" else macd_hist < 0
            score += 15 if aligned else 0
        if rsi is not None:
            if direction == "BUY":
                score += 10 if 50 <= rsi <= 68 else 5 if 45 <= rsi < 50 else 0
            else:
                score += 10 if 32 <= rsi <= 50 else 5 if 50 < rsi <= 55 else 0
        structure = structure_up if direction == "BUY" else structure_down
        score += 15 if structure else 0
        directional_momentum = momentum if direction == "BUY" else -momentum
        score += 10 if directional_momentum >= 0.003 else 5 if directional_momentum > 0 else 0
        if volume_ratio is not None:
            score += 10 if volume_ratio >= 1.20 else 5 if volume_ratio >= 1.0 else 0
        if direction == "BUY":
            score += 10 if bullish_sweep else 0
            score += 6 if bullish_absorption else 0
        else:
            score += 10 if bearish_sweep else 0
            score += 6 if bearish_absorption else 0
        return round(min(100.0, score), 1)

    buy_score, sell_score = score_for("BUY"), score_for("SELL")
    selected = side if side in ("BUY", "SELL") else (
        "BUY" if buy_score >= sell_score else "SELL"
    )
    score = buy_score if selected == "BUY" else sell_score
    opposing = sell_score if selected == "BUY" else buy_score
    if score >= 78:
        state = "STRONG_BUY" if selected == "BUY" else "STRONG_SELL"
    elif score >= 64 and score - opposing >= 12:
        state = "BUY" if selected == "BUY" else "SELL"
    else:
        state = "NEUTRAL"
    return {
        "state": state, "score": score, "buy_score": buy_score,
        "sell_score": sell_score, "rsi": round(rsi, 1) if rsi is not None else None,
        "momentum_percent": round(momentum * 100, 3),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "liquidity_sweep": "BULLISH" if bullish_sweep else "BEARISH" if bearish_sweep else None,
        "absorption_proxy": "BULLISH" if bullish_absorption else "BEARISH" if bearish_absorption else None,
        "ema200_available": ema200 is not None,
        "reason": "scored_from_ohlcv_price_action_volume",
    }


def assess_strategy(histories, entry_timeframe, side=None):
    """Require a qualified entry setup and directional agreement from higher frames."""
    refs = TIMEFRAME_RULES.get(entry_timeframe)
    if refs is None:
        return {"confirmed": False, "reason": "unsupported_timeframe", "states": {}}
    histories = histories or {}
    entry = assess_timeframe(histories.get(entry_timeframe, []), side)
    if entry["state"] in ("INSUFFICIENT", "INVALID"):
        return {"confirmed": False, "reason": "insufficient_entry_history", "states": {}}
    selected_side = side or ("BUY" if entry["buy_score"] > entry["sell_score"] else "SELL")
    entry_score = entry["buy_score"] if selected_side == "BUY" else entry["sell_score"]
    opposite_score = entry["sell_score"] if selected_side == "BUY" else entry["buy_score"]
    if entry_score < 64 or entry_score - opposite_score < 12:
        return {"confirmed": False, "reason": "entry_setup_below_threshold",
                "side": selected_side, "entry": entry, "states": {}}

    states = {}
    ref_scores = []
    required_states = BUY_STATES if selected_side == "BUY" else SELL_STATES
    for timeframe in refs:
        result = assess_timeframe(histories.get(timeframe, []), selected_side)
        states[timeframe] = result["state"]
        ref_scores.append(result["score"])
        if result["state"] not in required_states or result["score"] < 58:
            return {"confirmed": False, "reason": "reference_timeframes_not_aligned",
                    "side": selected_side, "entry": entry, "states": states}
    quality = round(entry_score * 0.60 + mean(ref_scores) * 0.40, 1) if refs else round(entry_score, 1)
    return {
        "confirmed": True, "side": selected_side, "entry": entry,
        "states": states, "reference_timeframes": list(refs),
        "quality_score": quality, "reason": "confirmed",
    }


def make_trade(rows, side):
    """ATR/swing-anchored stop and transparent 1R/2R/3R targets."""
    bars = _normalise(rows)
    if side not in ("BUY", "SELL") or not bars:
        return None
    try:
        entry = bars[-1]["close"]
        true_ranges = []
        for index in range(max(1, len(bars) - 14), len(bars)):
            current, previous = bars[index], bars[index - 1]
            true_ranges.append(max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            ))
        atr = mean(true_ranges)
        swing_low = min(bar["low"] for bar in bars[-10:])
        swing_high = max(bar["high"] for bar in bars[-10:])
        stop = swing_low - atr * 0.20 if side == "BUY" else swing_high + atr * 0.20
        risk = entry - stop if side == "BUY" else stop - entry
        risk_fraction = risk / entry if entry > 0 else 0
        if risk <= 0 or risk_fraction < 0.001 or risk_fraction > 0.045:
            return None
        sign = 1 if side == "BUY" else -1
        return {
            "entry": entry, "stop_loss": stop,
            "tp1": entry + sign * risk,
            "tp2": entry + sign * risk * 2,
            "tp3": entry + sign * risk * 3,
            "risk_percent": round(risk_fraction * 100, 3),
            "reward_risk": {"tp1": 1.0, "tp2": 2.0, "tp3": 3.0},
            "atr": atr,
        }
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
