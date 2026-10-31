"""Independent evidence-based multi-factor strategy for liquid markets.

This is a rules-based research engine, not a profitability guarantee.
It combines regime, trend, momentum, structure, relative volume and volatility.
Higher-timeframe context is advisory rather than a mandatory alignment gate.
"""
from math import isfinite
from statistics import mean, pstdev

MIN_BARS = 60
MIN_SCORE = 72
MIN_EDGE = 14


def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = mean(values[:period])
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes[-period:]]
    losses = [max(-x, 0.0) for x in changes[-period:]]
    avg_gain, avg_loss = mean(gains), mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        high, low = float(bars[i]["high"]), float(bars[i]["low"])
        prev = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    return mean(trs[-period:]) if len(trs) >= period else None


def _context_state(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) < 30:
        return "UNAVAILABLE"
    closes = [float(x["close"]) for x in rows if float(x["close"]) > 0]
    if len(closes) < 30:
        return "UNAVAILABLE"
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    if fast is None or slow is None:
        return "UNAVAILABLE"
    if closes[-1] > fast > slow:
        return "BULLISH"
    if closes[-1] < fast < slow:
        return "BEARISH"
    return "MIXED"


def evaluate_setup(rows, context_rows=None, market_change_24h=0.0):
    """Return side and transparent setup-quality points from completed OHLCV bars."""
    if not isinstance(rows, (list, tuple)) or len(rows) < MIN_BARS:
        return {"accepted": False, "reason": "insufficient_candles"}
    try:
        bars = rows[-100:]
        closes = [float(x["close"]) for x in bars]
        highs = [float(x["high"]) for x in bars]
        lows = [float(x["low"]) for x in bars]
        volumes = [float(x.get("volume", 0) or 0) for x in bars]
        if any(not isfinite(x) or x <= 0 for x in closes):
            return {"accepted": False, "reason": "invalid_price_data"}
        if any(not isfinite(h) or not isfinite(l) or h < l for h, l in zip(highs, lows)):
            return {"accepted": False, "reason": "invalid_ohlc"}
        if any(not isfinite(v) or v < 0 for v in volumes):
            return {"accepted": False, "reason": "invalid_volume"}

        last = closes[-1]
        ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
        ema200 = _ema(closes, 200)
        rsi = _rsi(closes)
        atr = _atr(bars)
        if ema20 is None or ema50 is None or atr is None or atr <= 0:
            return {"accepted": False, "reason": "insufficient_indicator_history"}

        # Directional components are scored independently for BUY and SELL.
        buy, sell = 0.0, 0.0
        factors = {}
        trend_up = last > ema20 > ema50
        trend_down = last < ema20 < ema50
        if ema200 is not None:
            trend_up = trend_up and last > ema200
            trend_down = trend_down and last < ema200
        buy += 24 if trend_up else (8 if last > ema50 else 0)
        sell += 24 if trend_down else (8 if last < ema50 else 0)
        factors["trend"] = "UP" if trend_up else "DOWN" if trend_down else "MIXED"

        momentum = last / closes[-6] - 1.0
        buy += 18 if momentum > 0.008 else (9 if momentum > 0.002 else 0)
        sell += 18 if momentum < -0.008 else (9 if momentum < -0.002 else 0)
        factors["momentum_pct"] = round(momentum * 100, 3)

        prior_high = max(highs[-21:-1])
        prior_low = min(lows[-21:-1])
        breakout_up = last > prior_high
        breakout_down = last < prior_low
        # Pullback continuation is scored separately from a fresh breakout.
        pullback_up = trend_up and lows[-1] <= ema20 * 1.006 and last > ema20
        pullback_down = trend_down and highs[-1] >= ema20 * 0.994 and last < ema20
        buy += 20 if breakout_up else (14 if pullback_up else 0)
        sell += 20 if breakout_down else (14 if pullback_down else 0)
        factors["structure"] = ("BREAKOUT_UP" if breakout_up else "PULLBACK_UP" if pullback_up
                                else "BREAKOUT_DOWN" if breakout_down else "PULLBACK_DOWN" if pullback_down
                                else "RANGE")

        baseline_volume = mean(volumes[-21:-1])
        relative_volume = volumes[-1] / baseline_volume if baseline_volume > 0 else 0.0
        if relative_volume >= 1.5:
            buy += 13 if closes[-1] >= closes[-2] else 0
            sell += 13 if closes[-1] < closes[-2] else 0
        elif relative_volume >= 1.15:
            buy += 7 if closes[-1] >= closes[-2] else 0
            sell += 7 if closes[-1] < closes[-2] else 0
        factors["relative_volume"] = round(relative_volume, 2)

        # Avoid chasing statistically extreme extension and abnormally dead bars.
        extension = abs(last - ema20) / atr
        if extension <= 1.8:
            buy += 8 if momentum > 0 else 0
            sell += 8 if momentum < 0 else 0
        elif extension > 3.2:
            buy -= 8
            sell -= 8
        if 42 <= rsi <= 68:
            buy += 9 if momentum > 0 else 0
        if 32 <= rsi <= 58:
            sell += 9 if momentum < 0 else 0
        factors["rsi"] = round(rsi, 1)
        factors["extension_atr"] = round(extension, 2)

        # A directional higher timeframe adds modest confirmation, never a hard veto.
        context = _context_state(context_rows or [])
        if context == "BULLISH":
            buy += 8
            sell -= 3
        elif context == "BEARISH":
            sell += 8
            buy -= 3
        factors["context"] = context

        # Require usable participation and a non-chaotic volatility regime.
        atr_pct = atr / last * 100
        returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        recent_vol = pstdev(returns[-20:]) if len(returns) >= 20 else 0.0
        if volumes[-1] <= 0 or baseline_volume <= 0:
            buy -= 5
            sell -= 5
        if atr_pct > 12 or recent_vol > 0.12:
            buy -= 10
            sell -= 10
        factors["atr_pct"] = round(atr_pct, 3)
        factors["market_change_24h_pct"] = round(float(market_change_24h or 0), 3)

        side = "BUY" if buy >= sell else "SELL"
        best, other = (buy, sell) if side == "BUY" else (sell, buy)
        score = max(0, min(100, round(best)))
        if score < MIN_SCORE or best - other < MIN_EDGE:
            return {"accepted": False, "reason": "edge_or_quality_below_threshold",
                    "quality_score": score, "factors": factors}
        return {
            "accepted": True, "side": side, "quality_score": score,
            "factors": factors, "context_state": context,
            "explanation": "Regime, momentum, price structure, participation and volatility passed independent quality gates."
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return {"accepted": False, "reason": "invalid_ohlcv"}


def build_trade_plan(rows, side):
    """Volatility/structure-based stop and asymmetric 1.5R/2.5R/3.5R targets."""
    if side not in ("BUY", "SELL") or not isinstance(rows, (list, tuple)) or len(rows) < MIN_BARS:
        return None
    try:
        bars = rows[-30:]
        entry = float(bars[-1]["close"])
        atr = _atr(bars, 14)
        if entry <= 0 or atr is None or atr <= 0:
            return None
        swing_low = min(float(x["low"]) for x in bars[-12:])
        swing_high = max(float(x["high"]) for x in bars[-12:])
        stop = min(swing_low - 0.2 * atr, entry - 1.2 * atr) if side == "BUY" else max(swing_high + 0.2 * atr, entry + 1.2 * atr)
        risk = entry - stop if side == "BUY" else stop - entry
        risk_pct = risk / entry
        if risk <= 0 or risk_pct < 0.001 or risk_pct > 0.05:
            return None
        sign = 1 if side == "BUY" else -1
        return {
            "entry": entry, "stop_loss": stop,
            "tp1": entry + sign * risk * 1.5,
            "tp2": entry + sign * risk * 2.5,
            "tp3": entry + sign * risk * 3.5,
            "risk_percent": round(risk_pct * 100, 3),
            "reward_risk": [1.5, 2.5, 3.5],
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
