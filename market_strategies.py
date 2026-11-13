"""SMART TRADING PRO: same-timeframe EMA strength trigger, confirmed on the next higher timeframe."""
import math

STRATEGY_FINGERPRINT = "STP-EMA-STRONG-MTF-V1-20261113"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {"15m": "1m", "1h": "15m", "4h": "1h", "1d": "4h", "1w": "1d", "1M": "1w"}
INTERVAL_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}
SUPPORTED_TIMEFRAMES = tuple(INTERVAL_MS)
PROFILES = {market: {"allow_short": True} for market in
            ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")}


def _closed_rows(rows):
    parsed = []
    for row in (rows or [])[:-1]:
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


def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def _atr(highs, lows, closes, period=14):
    ranges = []
    for i in range(len(closes)):
        previous = closes[i - 1] if i else closes[i]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous), abs(lows[i] - previous)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def target_prices(entry, side, stop=None):
    """Three risk-multiple targets: 1R, 2R and 3R."""
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
    result = tuple(entry + sign * risk * n for n in (1, 2, 3))
    return result if all(math.isfinite(x) and x > 0 for x in result) else None


def _direction(bars):
    closes = [x[4] for x in bars]
    if len(closes) < 55:
        return None
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    previous20 = _ema(closes[:-3], 20)
    last = bars[-1]
    previous = bars[-2]
    if not all(math.isfinite(x) and x > 0 for x in (ema20, ema50, previous20)):
        return None
    bullish = (last[4] > ema20 > ema50 and ema20 > previous20
               and last[4] > last[1] and last[4] > previous[4])
    bearish = (last[4] < ema20 < ema50 and ema20 < previous20
               and last[4] < last[1] and last[4] < previous[4])
    if bullish:
        return {"side": "BUY", "ema20": ema20, "ema50": ema50}
    if bearish:
        return {"side": "SELL", "ema20": ema20, "ema50": ema50}
    return None


def analyze(market, symbol, rows, timeframe="15m", trigger_rows=None, microstructure=None, include_micro=False):
    """Trigger on the mapped lower frame; confirm and build the trade on timeframe."""
    profile = PROFILES.get(market)
    trigger_timeframe = SIGNAL_TIMEFRAME.get(timeframe)
    if not profile or not trigger_timeframe or not isinstance(rows, list) or not isinstance(trigger_rows, list):
        return None
    analysis_bars = _closed_rows(rows)
    trigger_bars = _closed_rows(trigger_rows)
    if not analysis_bars or not trigger_bars or len(analysis_bars) < 55 or len(trigger_bars) < 55:
        return None
    trigger = _direction(trigger_bars)
    confirmation = _direction(analysis_bars)
    if not trigger or not confirmation or trigger["side"] != confirmation["side"]:
        return None

    side = trigger["side"]
    highs = [x[2] for x in analysis_bars]
    lows = [x[3] for x in analysis_bars]
    closes = [x[4] for x in analysis_bars]
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.20:
        return None

    if side == "BUY":
        structural = min(lows[-8:])
        stop = min(structural, entry - 1.5 * atr)
    else:
        structural = max(highs[-8:])
        stop = max(structural, entry + 1.5 * atr)
    risk = entry - stop if side == "BUY" else stop - entry
    if risk <= 0 or risk > atr * 8 or risk > entry * 0.08:
        return None
    ladder = target_prices(entry, side, stop)
    if not ladder:
        return None
    previous_close = closes[-2]
    return {
        "side": side, "entry": entry, "stop": stop,
        "tp1": ladder[0], "tp2": ladder[1], "tp3": ladder[2],
        "score": 88.0, "timeframe": timeframe, "signal_timeframe": trigger_timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": (f"STP EMA STRONG MTF: {side}; {trigger_timeframe} same-frame EMA20/EMA50 trigger "
                   f"confirmed on {timeframe}; entry/stop/targets calculated on analysis timeframe"),
        "signal_candle_time": analysis_bars[-1][0], "trigger_candle_time": trigger_bars[-1][0],
        "risk_atr": round(risk / atr, 3), "reward_risk": 3.0, "atr": atr,
        "trigger_ema20": trigger["ema20"], "trigger_ema50": trigger["ema50"],
        "analysis_ema20": confirmation["ema20"], "analysis_ema50": confirmation["ema50"],
        "swing_origin": structural, "confirmations": 2, "volume_ratio": None,
        "range_expansion": None,
        "strategy_votes": {"BUY": ["same-frame bullish EMA20/EMA50 strength", "higher-frame bullish confirmation"] if side == "BUY" else [],
                           "SELL": ["same-frame bearish EMA20/EMA50 strength", "higher-frame bearish confirmation"] if side == "SELL" else []},
        "strategy": "STP_EMA_MTF_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }


def diagnostic_self_test():
    checks = {
        "six_analysis_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "lower_trigger_mapping": SIGNAL_TIMEFRAME == {"15m": "1m", "1h": "15m", "4h": "1h", "1d": "4h", "1w": "1d", "1M": "1w"},
        "all_markets_enabled": all(PROFILES[m]["allow_short"] for m in PROFILES),
        "buy_risk_ladder": target_prices(100, "BUY", 95) == (105.0, 110.0, 115.0),
        "sell_risk_ladder": target_prices(100, "SELL", 105) == (95.0, 90.0, 85.0),
        "bad_risk_rejected": target_prices(100, "BUY", 101) is None,
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()), "checks": checks,
            "timeframes": list(TIMEFRAMES), "signal_timeframes": dict(SIGNAL_TIMEFRAME),
            "rule": "same-frame strong EMA20/EMA50 trigger -> matching higher-timeframe confirmation -> 1R/2R/3R targets"}
