"""Practical same-timeframe reversal engine for public OHLCV markets.

Scores are setup-quality points, not probabilities. Only completed candles should
be passed by the market adapter. Missing optional indicators do not invalidate
otherwise usable price history.
"""
from statistics import mean
from math import isfinite

BUY_STATES = frozenset(("BUY", "STRONG_BUY"))
SELL_STATES = frozenset(("SELL", "STRONG_SELL"))
MIN_CANDLES = 35


def _finite(value):
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _normalise(rows):
    if not isinstance(rows, (list, tuple)):
        return []
    bars = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = {key: _finite(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            continue
        if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
            continue
        if values["high"] < max(values["open"], values["close"], values["low"]):
            continue
        if values["low"] > min(values["open"], values["close"], values["high"]):
            continue
        values["volume"] = max(values["volume"] or 0.0, 0.0)
        bars.append(values)
    return bars


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
    recent = changes[-period:]
    gains = [max(change, 0.0) for change in recent]
    losses = [max(-change, 0.0) for change in recent]
    avg_gain, avg_loss = mean(gains), mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _macd_histogram(closes):
    if len(closes) < 35:
        return None
    fast, slow = mean(closes[:12]), mean(closes[:26])
    fast_alpha, slow_alpha = 2.0 / 13.0, 2.0 / 27.0
    line = []
    for index, close in enumerate(closes):
        if index >= 12:
            fast = close * fast_alpha + fast * (1.0 - fast_alpha)
        if index >= 26:
            slow = close * slow_alpha + slow * (1.0 - slow_alpha)
        if index >= 25:
            line.append(fast - slow)
    signal = _ema(line, 9)
    return line[-1] - signal if signal is not None else None


def assess_timeframe(rows, side=None):
    """Score both directions from EMA, MACD, RSI, structure, momentum and volume."""
    bars = _normalise(rows)
    if len(bars) < MIN_CANDLES:
        return {
            "state": "INSUFFICIENT", "score": 0.0, "buy_score": 0.0,
            "sell_score": 0.0, "reason": "need_35_valid_completed_candles",
            "candles_used": len(bars),
        }

    closes = [bar["close"] for bar in bars]
    highs = [bar["high"] for bar in bars]
    lows = [bar["low"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    ema9, ema21, ema50 = (_ema(closes, period) for period in (9, 21, 50))
    rsi = _rsi(closes)
    macd_hist = _macd_histogram(closes)
    momentum = closes[-1] / closes[-6] - 1.0 if closes[-6] else 0.0

    recent_high, prior_high = max(highs[-5:]), max(highs[-10:-5])
    recent_low, prior_low = min(lows[-5:]), min(lows[-10:-5])
    structure_up = recent_high > prior_high and recent_low > prior_low
    structure_down = recent_high < prior_high and recent_low < prior_low
    baseline_volume = mean(volumes[-21:-1])
    volume_ratio = volumes[-1] / baseline_volume if baseline_volume > 0 else None
    candle_up = closes[-1] > bars[-1]["open"]
    candle_down = closes[-1] < bars[-1]["open"]

    def score_for(direction):
        score = 0.0
        if ema9 is not None and ema21 is not None:
            aligned = closes[-1] > ema9 > ema21 if direction == "BUY" else closes[-1] < ema9 < ema21
            price_aligned = closes[-1] > ema21 if direction == "BUY" else closes[-1] < ema21
            score += 20 if aligned else 12 if price_aligned else 0
        if ema50 is not None:
            aligned = closes[-1] > ema50 if direction == "BUY" else closes[-1] < ema50
            score += 12 if aligned else 0
        if macd_hist is not None:
            aligned = macd_hist > 0 if direction == "BUY" else macd_hist < 0
            score += 12 if aligned else 0
        if rsi is not None:
            if direction == "BUY":
                score += 10 if 50 <= rsi <= 70 else 5 if 45 <= rsi < 50 else 0
            else:
                score += 10 if 30 <= rsi <= 50 else 5 if 50 < rsi <= 55 else 0
        structure = structure_up if direction == "BUY" else structure_down
        score += 12 if structure else 0
        directional_momentum = momentum if direction == "BUY" else -momentum
        score += 12 if directional_momentum >= 0.002 else 6 if directional_momentum > 0 else 0
        if volume_ratio is not None:
            score += 10 if volume_ratio >= 1.10 else 5 if volume_ratio >= 0.80 else 0
        candle_aligned = candle_up if direction == "BUY" else candle_down
        score += 6 if candle_aligned else 0
        return round(min(100.0, score), 1)

    buy_score, sell_score = score_for("BUY"), score_for("SELL")
    selected = side if side in ("BUY", "SELL") else ("BUY" if buy_score >= sell_score else "SELL")
    score = buy_score if selected == "BUY" else sell_score
    opposing = sell_score if selected == "BUY" else buy_score
    if score >= 70 and score - opposing >= 15:
        state = "STRONG_BUY" if selected == "BUY" else "STRONG_SELL"
    elif score >= 55 and score - opposing >= 8:
        state = "BUY" if selected == "BUY" else "SELL"
    else:
        state = "NEUTRAL"

    return {
        "state": state, "score": score, "buy_score": buy_score,
        "sell_score": sell_score, "rsi": round(rsi, 1) if rsi is not None else None,
        "momentum_percent": round(momentum * 100, 3),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "ema50_available": ema50 is not None, "candles_used": len(bars),
        "reason": "scored_from_completed_ohlcv",
    }


def assess_reversal(rows):
    """Reverse the detected direction while preserving signal strength."""
    analysis = assess_timeframe(rows)
    source_state = analysis.get("state")
    reverse = {
        "BUY": ("SELL", "SELL"),
        "STRONG_BUY": ("SELL", "STRONG_SELL"),
        "SELL": ("BUY", "BUY"),
        "STRONG_SELL": ("BUY", "STRONG_BUY"),
    }
    if source_state not in reverse:
        return {
            "confirmed": False, "reason": analysis.get("reason", "no_clear_direction"),
            "source_state": source_state, "analysis": analysis,
        }
    trade_side, trade_state = reverse[source_state]
    return {
        "confirmed": True, "source_state": source_state, "side": trade_side,
        "trade_state": trade_state, "quality_score": analysis["score"],
        "analysis": analysis, "reason": "same_timeframe_reversal",
    }


def make_trade(rows, side, timeframe="15m"):
    """Build ATR/swing stops and 1R/2R/3R targets without arbitrary narrow caps."""
    bars = _normalise(rows)
    if side not in ("BUY", "SELL") or len(bars) < MIN_CANDLES:
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
        if not isfinite(atr) or atr <= 0:
            return None
        swing_low = min(bar["low"] for bar in bars[-10:])
        swing_high = max(bar["high"] for bar in bars[-10:])
        if side == "BUY":
            stop = min(swing_low - atr * 0.15, entry - atr * 1.20)
            risk = entry - stop
            sign = 1
        else:
            stop = max(swing_high + atr * 0.15, entry + atr * 1.20)
            risk = stop - entry
            sign = -1
        risk_fraction = risk / entry if entry > 0 else 0.0
        max_risk = {"15m": 0.08, "1h": 0.10, "4h": 0.15,
                    "1d": 0.22, "1w": 0.32, "1M": 0.45}.get(timeframe, 0.08)
        if risk <= 0 or risk_fraction < 0.0005 or risk_fraction > max_risk:
            return None
        return {
            "entry": entry, "stop_loss": stop,
            "tp1": entry + sign * risk,
            "tp2": entry + sign * risk * 2.0,
            "tp3": entry + sign * risk * 3.0,
            "risk_percent": round(risk_fraction * 100.0, 3),
            "reward_risk": {"tp1": 1.0, "tp2": 2.0, "tp3": 3.0},
            "atr": atr,
        }
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
