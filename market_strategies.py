"""Donchian 55 + EMA 8/55 + ADX 14 breakout strategy.

Research adaptation of the public 15m community strategy concept
(QuantifyMe community #203). This implementation is deterministic Python,
not the original RandomForest model. It uses closed candles only and
ATR-based 1R/2R/3R levels. No profitability claim is made.
"""
import math

PROFILES = {
    "spot": {"allow_short": False, "adx_min": 18.0},
    "alpha": {"allow_short": False, "adx_min": 20.0},
    "futures": {"allow_short": True, "adx_min": 18.0},
    "us-stocks": {"allow_short": False, "adx_min": 18.0},
    "us-contracts": {"allow_short": True, "adx_min": 18.0},
    "saudi": {"allow_short": False, "adx_min": 18.0},
    "forex": {"allow_short": True, "adx_min": 16.0},
}


def _ema(values, period):
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def _atr(highs, lows, closes, period=14):
    true_ranges = []
    for i in range(1, len(closes)):
        true_ranges.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    if len(true_ranges) < period:
        return 0.0
    return sum(true_ranges[-period:]) / period


def _adx(highs, lows, closes, period=14):
    if len(closes) < period * 2 + 1:
        return 0.0
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    dx = []
    for end in range(period, len(tr) + 1):
        tr_sum = sum(tr[end - period:end])
        if tr_sum <= 0:
            dx.append(0.0)
            continue
        pdi = 100.0 * sum(plus_dm[end - period:end]) / tr_sum
        mdi = 100.0 * sum(minus_dm[end - period:end]) / tr_sum
        denom = pdi + mdi
        dx.append(100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
    return sum(dx[-period:]) / min(period, len(dx)) if dx else 0.0


def analyze(market, symbol, rows, include_micro=False):
    """Return one 15m Donchian breakout setup, or None."""
    profile = PROFILES.get(market)
    if not profile or not isinstance(rows, list) or len(rows) < 90:
        return None
    try:
        # The last provider candle may still be forming: never trade it.
        bars = rows[:-1]
        o = [float(x[1]) for x in bars]
        h = [float(x[2]) for x in bars]
        l = [float(x[3]) for x in bars]
        c = [float(x[4]) for x in bars]
        v = [float(x[5] or 0) for x in bars]
        if not all(math.isfinite(z) for seq in (o, h, l, c, v) for z in seq):
            return None
        if any(x <= 0 for x in c[-60:]) or any(x < 0 for x in v[-60:]):
            return None

        i = len(bars) - 1
        if i < 56:
            return None
        entry = c[i]
        candle_range = h[i] - l[i]
        if entry <= 0 or candle_range <= 0:
            return None

        # Donchian boundaries are built only from candles before the signal.
        prior_high = max(h[i - 55:i])
        prior_low = min(l[i - 55:i])
        ema_fast = _ema(c, 8)[i]
        ema_slow = _ema(c, 55)[i]
        adx = _adx(h, l, c, 14)
        atr = _atr(h, l, c, 14)
        if atr <= 0 or adx < profile["adx_min"]:
            return None

        close_location = (entry - l[i]) / candle_range
        bullish = (
            entry > prior_high
            and entry > o[i]
            and ema_fast > ema_slow
            and close_location >= 0.60
        )
        bearish = (
            profile["allow_short"]
            and entry < prior_low
            and entry < o[i]
            and ema_fast < ema_slow
            and close_location <= 0.40
        )
        if not bullish and not bearish:
            return None

        side = "BUY" if bullish else "SELL"
        direction = 1.0 if bullish else -1.0
        # Volatility-normalized stop; targets are true R multiples.
        risk = 1.5 * atr
        stop = entry - direction * risk
        tp1 = entry + direction * risk
        tp2 = entry + direction * 2.0 * risk
        tp3 = entry + direction * 3.0 * risk
        if stop <= 0 or min(tp1, tp2, tp3) <= 0:
            return None

        breakout_atr = (
            (entry - prior_high) / atr if bullish
            else (prior_low - entry) / atr
        )
        trend_gap = abs(ema_fast - ema_slow) / atr
        score = min(
            95.0,
            58.0
            + min(max(adx - profile["adx_min"], 0.0), 25.0) * 0.65
            + min(max(breakout_atr, 0.0), 1.0) * 12.0
            + min(trend_gap, 1.0) * 8.0,
        )
        return {
            "side": side,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "score": round(score, 1),
            "timeframe": "15m",
            "change_pct": round((entry / c[i - 1] - 1.0) * 100.0, 5),
            "change_15m_pct": round((entry / c[i - 1] - 1.0) * 100.0, 5),
            "reason": (
                f"DONCHIAN BREAKOUT {market}: 55-candle channel, "
                f"EMA 8/55 trend, ADX {adx:.1f}, ATR stop, targets 1R/2R/3R"
            ),
            "signal_candle_time": int(float(bars[-1][0])),
            "risk_atr": round(risk / atr, 3),
            "reward_risk": 3.0,
            "adx": round(adx, 2),
            "donchian_period": 55,
            "strategy": f"DONCHIAN_EMA_ADX_{market.upper()}",
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
