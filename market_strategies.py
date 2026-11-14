"""SMART FLOW: false-breakout liquidity sweep with close-confirmed reclaim.

Signals are analytical only. The engine never places orders.
"""
import math

STRATEGY_FINGERPRINT = "SMART-FLOW-FALSE-SWEEP-MTF-V2-20261114"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {frame: frame for frame in TIMEFRAMES}
INTERVAL_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}
SUPPORTED_TIMEFRAMES = tuple(INTERVAL_MS)
PROFILES = {market: {"allow_short": True} for market in
            ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")}


def _finite_rows(rows):
    parsed = []
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    for row in rows[:-1]:  # Exclude the still-forming final candle.
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return None
        try:
            stamp = int(float(row[0]))
            op, hi, lo, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)):
            return None
        if min(op, hi, lo, close) <= 0 or volume < 0 or hi < max(op, close) or lo > min(op, close) or hi < lo:
            return None
        parsed.append((stamp, op, hi, lo, close, volume))
    return parsed


def _atr(highs, lows, closes, period=14):
    ranges = []
    for i in range(len(closes)):
        previous = closes[i - 1] if i else closes[i]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous), abs(lows[i] - previous)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def target_prices(entry, side, stop=None):
    """Return fixed 1R / 2R / 3R targets from one entry and structural stop."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0 or stop <= 0 or side not in ("BUY", "SELL"):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    result = tuple(entry + sign * risk * multiple for multiple in (1, 2, 3))
    return result if all(math.isfinite(x) and x > 0 for x in result) else None


def _find_sweep_setup(highs, lows, opens, closes, volumes, atr, lookback=20, recent=6):
    """Find a recent stop-run, reclaim candle, then a later close beyond the sweep candle."""
    n = len(closes)
    first = max(lookback, n - recent - 1)
    for i in range(n - 2, first - 1, -1):
        prior_high = max(highs[i - lookback:i])
        prior_low = min(lows[i - lookback:i])
        candle_range = max(highs[i] - lows[i], closes[i] * 1e-8)
        lower_wick = min(opens[i], closes[i]) - lows[i]
        upper_wick = highs[i] - max(opens[i], closes[i])
        bullish = lows[i] < prior_low and closes[i] > prior_low and closes[i] > opens[i] and lower_wick / candle_range >= 0.20
        bearish = highs[i] > prior_high and closes[i] < prior_high and closes[i] < opens[i] and upper_wick / candle_range >= 0.20
        if bullish and closes[-1] > highs[i]:
            if any(closes[j] <= lows[i] for j in range(i + 1, n)):
                continue
            return {"side": "BUY", "sweep_index": i, "sweep_extreme": lows[i],
                    "broken_level": prior_low, "wick_ratio": lower_wick / candle_range,
                    "sweep_volume": volumes[i]}
        if bearish and closes[-1] < lows[i]:
            if any(closes[j] >= highs[i] for j in range(i + 1, n)):
                continue
            return {"side": "SELL", "sweep_index": i, "sweep_extreme": highs[i],
                    "broken_level": prior_high, "wick_ratio": upper_wick / candle_range,
                    "sweep_volume": volumes[i]}
    return None


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES:
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 40:
        return None
    opens, highs, lows, closes, volumes = ([x[k] for x in bars] for k in (1, 2, 3, 4, 5))
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.20:
        return None
    setup = _find_sweep_setup(highs, lows, opens, closes, volumes, atr)
    if not setup or (setup["side"] == "SELL" and not profile["allow_short"]):
        return None
    side = setup["side"]
    buffer = max(atr * 0.12, entry * 0.0002)
    stop = setup["sweep_extreme"] - buffer if side == "BUY" else setup["sweep_extreme"] + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0 or risk > atr * 8 or risk > entry * 0.025:
        return None
    ladder = target_prices(entry, side, stop)
    if not ladder:
        return None

    sweep_idx = setup["sweep_index"]
    prior_volumes = volumes[max(0, sweep_idx - 20):sweep_idx]
    avg_volume = sum(prior_volumes) / max(1, len(prior_volumes))
    volume_ratio = setup["sweep_volume"] / avg_volume if avg_volume > 0 else 1.0
    score = 58.0 + min(14.0, max(0.0, (setup["wick_ratio"] - 0.20) * 30.0))
    if volume_ratio >= 1.5:
        score += 10.0
    elif volume_ratio >= 1.15:
        score += 5.0
    reclaim_distance = abs(entry - (highs[sweep_idx] if side == "BUY" else lows[sweep_idx]))
    if reclaim_distance >= atr * 0.25:
        score += 8.0
    if risk <= atr * 2.5:
        score += 5.0
    score = round(min(95.0, score), 1)

    previous_close = closes[-2]
    reason = (
        f"FALSE-SWEEP: {side} liquidity sweep beyond prior {'low' if side == 'BUY' else 'high'}; "
        "reclaim candle closed back inside range; later completed candle closed beyond sweep candle; "
        "stop beyond sweep extreme; maximum stop distance 2.5%; targets fixed at 1R/2R/3R"
    )
    return {
        "side": side, "entry": entry, "stop": stop,
        "tp1": ladder[0], "tp2": ladder[1], "tp3": ladder[2],
        "score": score, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": reason, "signal_candle_time": bars[-1][0],
        "risk_atr": round(risk / atr, 3), "reward_risk": 3.0, "atr": atr,
        "sweep_extreme": setup["sweep_extreme"], "broken_level": setup["broken_level"],
        "sweep_candle_time": bars[sweep_idx][0],
        "sweep_wick_ratio": round(setup["wick_ratio"], 3), "volume_ratio": round(volume_ratio, 3),
        "confirmations": 3,
        "strategy_votes": {
            "BUY": ["سحب سيولة أسفل قاع سابق", "إغلاق استعادة صاعد", "إغلاق لاحق فوق شمعة السحب"] if side == "BUY" else [],
            "SELL": ["سحب سيولة أعلى قمة سابقة", "إغلاق استعادة هابط", "إغلاق لاحق تحت شمعة السحب"] if side == "SELL" else [],
        },
        "strategy": "FALSE_SWEEP_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }


def diagnostic_self_test():
    buy, sell = target_prices(100, "BUY", 95), target_prices(100, "SELL", 105)
    checks = {
        "six_independent_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "all_markets_supported": all(PROFILES[m]["allow_short"] for m in PROFILES),
        "each_frame_uses_itself": all(SIGNAL_TIMEFRAME[x] == x for x in TIMEFRAMES),
        "buy_risk_ladder_1_2_3R": buy == (105.0, 110.0, 115.0),
        "sell_risk_ladder_1_2_3R": sell == (95.0, 90.0, 85.0),
        "bad_risk_rejected": target_prices(100, "BUY", 101) is None,
        "forming_candle_excluded": len(_finite_rows([[i, 10, 11, 9, 10, 1] for i in range(41)])) == 40,
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()), "checks": checks,
            "timeframes": list(TIMEFRAMES), "signal_timeframes": dict(SIGNAL_TIMEFRAME),
            "rule": "liquidity sweep -> reclaim close -> later close beyond sweep candle -> structural stop -> 1R/2R/3R"}
