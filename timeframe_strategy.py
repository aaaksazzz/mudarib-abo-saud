"""OHLCV-only directional confirmation; the live strategy calls this on 15m candles.

This module intentionally avoids EMA, MACD, RSI, and external AI/API keys.
It classifies directional structure; the entry trigger is handled separately by
the liquidity sweep/absorption engine.
"""
from statistics import mean, median
from math import isfinite


def _number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _normalise(rows):
    if not isinstance(rows, (list, tuple)):
        return []
    bars = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = {key: _number(row.get(key)) for key in
                  ("open", "high", "low", "close", "volume")}
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            continue
        if min(values[key] for key in ("open", "high", "low", "close")) <= 0:
            continue
        if values["high"] < max(values["open"], values["close"], values["low"]):
            continue
        if values["low"] > min(values["open"], values["close"], values["high"]):
            continue
        values["volume"] = max(values["volume"] or 0.0, 0.0)
        bars.append(values)
    return bars


def assess_timeframe(rows):
    """Classify BUY/SELL structure from completed candles, momentum and volume."""
    bars = _normalise(rows)
    if len(bars) < 35:
        return {
            "state": "INSUFFICIENT", "score": 0.0, "buy_score": 0.0,
            "sell_score": 0.0, "reason": "need_35_valid_completed_candles",
            "candles_used": len(bars),
        }

    closes = [bar["close"] for bar in bars]
    highs = [bar["high"] for bar in bars]
    lows = [bar["low"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    recent_high, prior_high = max(highs[-5:]), max(highs[-10:-5])
    recent_low, prior_low = min(lows[-5:]), min(lows[-10:-5])
    structure_up = recent_high > prior_high and recent_low > prior_low
    structure_down = recent_high < prior_high and recent_low < prior_low
    momentum = closes[-1] / closes[-6] - 1.0 if closes[-6] else 0.0
    bullish_count = sum(1 for bar in bars[-10:] if bar["close"] > bar["open"])
    bearish_count = sum(1 for bar in bars[-10:] if bar["close"] < bar["open"])
    last = bars[-1]
    candle_range = max(last["high"] - last["low"], 1e-12)
    close_position = (last["close"] - last["low"]) / candle_range
    baseline = median(volumes[-21:-1]) if len(volumes) >= 21 else 0.0
    volume_ratio = volumes[-1] / baseline if baseline > 0 else None
    average_close = mean(closes[-20:])

    def score_for(side):
        score = 0.0
        if side == "BUY":
            score += 20 if closes[-1] > average_close else 0
            score += 25 if structure_up else 0
            score += 20 if momentum >= 0.005 else 10 if momentum > 0 else 0
            score += 10 if bullish_count >= 7 else 5 if bullish_count >= 6 else 0
            score += 10 if close_position >= 0.70 else 5 if close_position >= 0.55 else 0
            score += 15 if volume_ratio is not None and volume_ratio >= 1.10 and last["close"] > last["open"] else 0
        else:
            score += 20 if closes[-1] < average_close else 0
            score += 25 if structure_down else 0
            score += 20 if momentum <= -0.005 else 10 if momentum < 0 else 0
            score += 10 if bearish_count >= 7 else 5 if bearish_count >= 6 else 0
            score += 10 if close_position <= 0.30 else 5 if close_position <= 0.45 else 0
            score += 15 if volume_ratio is not None and volume_ratio >= 1.10 and last["close"] < last["open"] else 0
        return round(min(100.0, score), 1)

    buy_score, sell_score = score_for("BUY"), score_for("SELL")
    if buy_score >= 70 and buy_score - sell_score >= 12:
        state, score = "STRONG_BUY", buy_score
    elif sell_score >= 70 and sell_score - buy_score >= 12:
        state, score = "STRONG_SELL", sell_score
    elif buy_score >= 45 and buy_score - sell_score >= 5:
        state, score = "BUY", buy_score
    elif sell_score >= 45 and sell_score - buy_score >= 5:
        state, score = "SELL", sell_score
    else:
        state, score = "NEUTRAL", max(buy_score, sell_score)

    return {
        "state": state, "score": score, "buy_score": buy_score,
        "sell_score": sell_score, "momentum_percent": round(momentum * 100, 3),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "structure_up": structure_up, "structure_down": structure_down,
        "candles_used": len(bars), "reason": "completed_ohlcv_structure_momentum_volume",
    }


def assess_signal(rows):
    """Compatibility helper returning a directional confirmation."""
    analysis = assess_timeframe(rows)
    state = analysis.get("state")
    if state not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
        return {"confirmed": False, "reason": analysis.get("reason", "no_clear_direction"),
                "state": state, "analysis": analysis}
    return {
        "confirmed": True, "state": state,
        "side": "BUY" if state in ("BUY", "STRONG_BUY") else "SELL",
        "quality_score": analysis["score"], "analysis": analysis,
        "reason": "completed_ohlcv_direction",
    }



def make_trade(rows, side, timeframe="15m"):
    """Compatibility risk model: ATR-buffered structure stop and 1R/2R/3R targets."""
    if side not in ("BUY", "SELL"):
        return None
    bars = _normalise(rows)
    if len(bars) < 35:
        return None
    confirmation = assess_signal(rows)
    if not confirmation.get("confirmed") or confirmation.get("side") != side:
        return None
    recent = bars[-15:]
    true_ranges = []
    for index, bar in enumerate(recent):
        previous_close = bars[-16 + index]["close"]
        true_ranges.append(max(
            bar["high"] - bar["low"],
            abs(bar["high"] - previous_close),
            abs(bar["low"] - previous_close),
        ))
    atr = mean(true_ranges)
    entry = bars[-1]["close"]
    buffer = max(atr * 0.12, entry * 0.0005)
    stop = min(bar["low"] for bar in recent) - buffer if side == "BUY" else max(
        bar["high"] for bar in recent
    ) + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if risk <= 0 or risk / entry > 0.045:
        return None
    sign = 1 if side == "BUY" else -1
    return {
        "side": side, "timeframe": timeframe, "entry": entry, "stop_loss": stop,
        "tp1": entry + sign * risk, "tp2": entry + sign * risk * 2,
        "tp3": entry + sign * risk * 3,
        "risk_percent": round(risk / entry * 100, 3),
        "risk_per_unit": risk, "target_method": "1R_2R_3R",
    }
