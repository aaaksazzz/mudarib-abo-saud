"""MiND-Shot-inspired VWAP mean-reversion signals for all supported markets/timeframes.

The source project validates this strategy on ETH 4h only. This adaptation
generalizes its disclosed rules to our market universe; it is not the original
project's complete engine or ML model. Entries use closed candles only.
"""
import math

TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
PROFILES = {
    "spot": {"allow_short": False},
    "alpha": {"allow_short": False},
    "futures": {"allow_short": True},
    "us-stocks": {"allow_short": False},
    "us-contracts": {"allow_short": True},
    "saudi": {"allow_short": False},
    "forex": {"allow_short": True},
}


def _rma(values, period):
    out = [None] * len(values)
    alpha = 1.0 / period
    previous = None
    for i, value in enumerate(values):
        if value is None:
            out[i] = previous
            continue
        previous = value if previous is None else previous + alpha * (value - previous)
        out[i] = previous
    return out


def _atr(highs, lows, closes, period=14):
    tr = [None] * len(closes)
    if not closes:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return _rma(tr, period)


def _adx(highs, lows, closes, period=14):
    n = len(closes)
    plus_dm, minus_dm = [None] * n, [None] * n
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
    tr = [None] * n
    if n:
        tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = _rma(tr, period)
    pdm, mdm = _rma(plus_dm, period), _rma(minus_dm, period)
    dx = [None] * n
    for i in range(n):
        if atr[i] is None or pdm[i] is None or mdm[i] is None or atr[i] <= 0:
            continue
        pdi, mdi = 100.0 * pdm[i] / atr[i], 100.0 * mdm[i] / atr[i]
        denom = pdi + mdi
        dx[i] = 100.0 * abs(pdi - mdi) / denom if denom else 0.0
    return _rma(dx, period)


def _vwap_z(highs, lows, closes, volumes, period=20):
    result = [None] * len(closes)
    window = []
    tpv = vol_sum = 0.0
    for i in range(len(closes)):
        volume = max(0.0, volumes[i])
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        window.append((typical * volume, volume, closes[i]))
        tpv += typical * volume
        vol_sum += volume
        if len(window) > period:
            old_tpv, old_vol, _ = window.pop(0)
            tpv -= old_tpv
            vol_sum -= old_vol
        if len(window) < period:
            continue
        mean = sum(item[2] for item in window) / period
        variance = sum((item[2] - mean) ** 2 for item in window) / period
        std = math.sqrt(max(variance, 0.0))
        vwap = tpv / vol_sum if vol_sum > 0 else closes[i]
        result[i] = (closes[i] - vwap) / (std + 1e-12)
    return result


def analyze(market, symbol, rows, timeframe="15m", include_micro=False):
    """Return a VWAP mean-reversion setup, or None.

    Original MiND-Shot ETH 4h bracket: |VWAP z-score| >= 2, ADX < 25,
    stop 1.5 ATR and take-profit 0.75 ATR. TP2/TP3 are optional staged
    extensions for this platform and are not part of the original rule.
    """
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES or not isinstance(rows, list) or len(rows) < 65:
        return None
    try:
        # Exclude the provider's potentially-forming candle.
        bars = rows[:-1]
        if len(bars) < 64:
            return None
        o = [float(x[1]) for x in bars]
        h = [float(x[2]) for x in bars]
        l = [float(x[3]) for x in bars]
        c = [float(x[4]) for x in bars]
        v = [float(x[5] or 0) for x in bars]
        if not all(math.isfinite(z) for seq in (o, h, l, c, v) for z in seq):
            return None
        if any(x <= 0 for x in c[-64:]) or any(x < 0 for x in v[-64:]):
            return None
        i = len(bars) - 1
        atr_values = _atr(h, l, c, 14)
        adx_values = _adx(h, l, c, 14)
        z_values = _vwap_z(h, l, c, v, 20)
        atr, adx, zscore = atr_values[i], adx_values[i], z_values[i]
        if atr is None or adx is None or zscore is None or atr <= 0 or adx >= 25.0:
            return None

        # Fade only statistically extended prices while ADX confirms a range.
        bullish = zscore <= -2.0
        bearish = zscore >= 2.0 and profile["allow_short"]
        if not bullish and not bearish:
            return None
        side = "BUY" if bullish else "SELL"
        direction = 1.0 if bullish else -1.0
        entry = c[i]
        risk = 1.5 * atr
        stop = entry - direction * risk
        # TP1 preserves the source strategy's 0.75 ATR bracket.
        # TP2/TP3 are clearly labelled staged extensions for the site's 3-target UI.
        tp1 = entry + direction * 0.75 * atr
        tp2 = entry + direction * 1.00 * atr
        tp3 = entry + direction * 1.50 * atr
        if stop <= 0 or min(tp1, tp2, tp3) <= 0:
            return None

        excess = max(0.0, abs(zscore) - 2.0)
        score = min(95.0, 60.0 + min(excess, 2.0) * 10.0 + max(0.0, 25.0 - adx) * 0.4)
        interval_ms = {"15m": 900000, "1h": 3600000, "4h": 14400000,
                       "1d": 86400000, "1w": 604800000, "1M": 2592000000}[timeframe]
        previous_close = c[i - 1] if i > 0 else entry
        return {
            "side": side, "entry": entry, "stop": stop,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "score": round(score, 1), "timeframe": timeframe,
            "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
            "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
            "reason": f"VWAP REVERSION {market}: VWAP(20) z={zscore:.2f}, ADX(14)={adx:.1f}, ATR(14) stop 1.5x",
            "signal_candle_time": int(float(bars[-1][0])),
            "risk_atr": 1.5, "reward_risk": 0.5,
            "adx": round(adx, 2), "vwap_z": round(zscore, 3),
            "strategy": f"MIINDSHOT_VWAP_{market.upper()}_{timeframe}",
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
