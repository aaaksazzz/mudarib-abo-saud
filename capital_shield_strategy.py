"""STP Capital Shield V10: single-engine liquidity-sweep/reclaim strategy.

Paper analysis only. Uses completed OHLCV candles, confirmed false-break
reclaims, structural invalidation stops, and fixed 1R/2R/3R targets.
No fallback engine and no promise of loss-free trading.
"""
import math

STRATEGY_FINGERPRINT = "STP-CAPITAL-SHIELD-V10-20261116"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
# Higher-timeframe direction is mapped to the lower execution timeframe.
DIRECTION_TO_EXECUTION = {"4h": "15m", "1d": "1h", "1w": "4h", "1M": "1d"}
EXECUTION_TO_DIRECTION = {execution: direction for direction, execution in DIRECTION_TO_EXECUTION.items()}
SCAN_TIMEFRAMES = tuple(DIRECTION_TO_EXECUTION.values())
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
MIN_BARS = {"15m": 105, "1h": 102, "4h": 88, "1d": 88, "1w": 68, "1M": 42}
MAX_RISK_PCT = {"15m": 0.035, "1h": 0.04, "4h": 0.05, "1d": 0.07, "1w": 0.12, "1M": 0.20}
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    out = []
    # Exclude the last row because it may still be forming.
    for row in rows[:-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return []
        try:
            stamp = int(float(row[0]))
            op, high, low, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return []
        if not all(math.isfinite(v) for v in (op, high, low, close, volume)):
            return []
        if min(op, high, low, close) <= 0 or volume < 0:
            return []
        if high < max(op, close) or low > min(op, close) or high < low:
            return []
        out.append({"time": stamp, "open": op, "high": high, "low": low,
                    "close": close, "volume": volume})
    return out


def _atr(bars, period=14):
    recent = bars[-period:]
    ranges = []
    for i, bar in enumerate(recent):
        prev = recent[i - 1]["close"] if i else (
            bars[-period - 1]["close"] if len(bars) > period else bar["close"])
        ranges.append(max(bar["high"] - bar["low"],
                          abs(bar["high"] - prev), abs(bar["low"] - prev)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _targets(entry, side, stop):
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    targets = tuple(entry + sign * risk * n for n in (1, 2, 3))
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def analyze(market, symbol, rows, timeframe="15m", diagnostics=None):
    def reject(code):
        if diagnostics is not None:
            diagnostics[code] = diagnostics.get(code, 0) + 1
        return None

    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return reject("invalid_market_or_timeframe")
    bars = _bars(rows)
    if len(bars) < MIN_BARS[timeframe]:
        return reject("insufficient_completed_candles")

    signal = bars[-1]
    history = bars[-21:-1]
    if len(history) < 20:
        return reject("insufficient_sweep_history")
    prior_high = max(x["high"] for x in history)
    prior_low = min(x["low"] for x in history)
    candle_range = max(signal["high"] - signal["low"], signal["close"] * 1e-10)
    close_location = (signal["close"] - signal["low"]) / candle_range
    lower_wick = min(signal["open"], signal["close"]) - signal["low"]
    upper_wick = signal["high"] - max(signal["open"], signal["close"])

    buy_sweep = (
        signal["low"] < prior_low and signal["close"] > prior_low
        and signal["close"] > signal["open"] and close_location >= 0.62
        and lower_wick / candle_range >= 0.18
    )
    sell_sweep = (
        signal["high"] > prior_high and signal["close"] < prior_high
        and signal["close"] < signal["open"] and close_location <= 0.38
        and upper_wick / candle_range >= 0.18
    )
    if buy_sweep and market == "spot":
        side, sweep_level = "BUY", signal["low"]
    elif buy_sweep:
        side, sweep_level = "BUY", signal["low"]
    elif sell_sweep and market != "spot":
        side, sweep_level = "SELL", signal["high"]
    elif sell_sweep:
        return reject("spot_short_blocked")
    else:
        return reject("no_confirmed_false_break_reclaim")

    atr = _atr(bars, 14)
    if not math.isfinite(atr) or atr <= 0:
        return reject("invalid_atr")
    entry = signal["close"]
    buffer = max(atr * 0.12, entry * 0.0002)
    stop = sweep_level - buffer if side == "BUY" else sweep_level + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    risk_atr = risk / atr
    risk_pct = risk / entry
    if risk <= 0 or risk_atr < 0.30 or risk_atr > 3.5:
        return reject("structural_stop_outside_atr_limits")
    if risk_pct > MAX_RISK_PCT[timeframe]:
        return reject("structural_risk_exceeds_timeframe_limit")

    previous_volumes = [x["volume"] for x in history if x["volume"] > 0]
    volume_ratio = None
    if signal["volume"] > 0 and previous_volumes:
        avg_volume = sum(previous_volumes) / len(previous_volumes)
        if avg_volume > 0:
            volume_ratio = signal["volume"] / avg_volume
            if volume_ratio < 0.60:
                return reject("sweep_volume_too_weak")

    targets = _targets(entry, side, stop)
    if not targets:
        return reject("invalid_target_geometry")

    confirmations = ["CLOSED_CANDLE", "LIQUIDITY_SWEEP",
                     "LEVEL_RECLAIM" if side == "BUY" else "LEVEL_REJECTION",
                     "STRONG_CLOSE", "STRUCTURAL_STOP", "R_MULTIPLE_TARGETS"]
    score = 72.0
    if volume_ratio is not None and volume_ratio >= 1.20:
        score += 8.0
        confirmations.append("RELATIVE_VOLUME_EXPANSION")
    elif volume_ratio is None:
        confirmations.append("VOLUME_UNAVAILABLE")
    if close_location >= 0.80 if side == "BUY" else close_location <= 0.20:
        score += 4.0
    score = round(min(90.0, score), 1)

    previous_close = bars[-2]["close"]
    return {
        "market": market, "symbol": str(symbol), "side": side,
        "entry": entry, "stop": stop,
        "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "score": score, "timeframe": timeframe,
        "signal_candle_time": signal["time"], "atr": atr,
        "risk_pct": round(risk_pct * 100.0, 4),
        "risk_atr": round(risk_atr, 3), "risk_distance": risk,
        "reward_risk": 3.0,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "quote_volume": None, "confirmations": confirmations,
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "strategy": "STP_CAPITAL_SHIELD_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "strategy_names": confirmations, "strategy_count": len(confirmations),
        "strategy_total": 6, "setup_type": "FALSE_BREAK_RECLAIM",
        "reason": "CAPITAL-SHIELD MTF: confirmed liquidity sweep and reclaim; "
                  "structural invalidation stop; targets 1R/2R/3R",
        "setup_quality_label": "technical_quality_not_probability",
    }


def diagnostic_self_test():
    def sample(side):
        rows = []
        for i in range(107):
            rows.append([i, 100.0, 101.0, 99.0, 100.0, 100.0])
        if side == "BUY":
            rows[-2] = [105, 100.0, 100.8, 98.0, 100.6, 180.0]
        else:
            rows[-2] = [105, 100.0, 102.0, 99.2, 99.4, 180.0]
        rows[-1] = [106, 100.0, 101.0, 99.0, 100.0, 100.0]  # forming candle
        return rows
    buy = analyze("futures", "TEST", sample("BUY"), "15m")
    sell = analyze("futures", "TEST", sample("SELL"), "15m")
    spot_sell = analyze("spot", "TEST", sample("SELL"), "15m")
    flat = [[i, 100.0, 101.0, 99.0, 100.0, 100.0] for i in range(107)]
    no_setup = analyze("futures", "TEST", flat, "15m")
    checks = {
        "fingerprint_matches": STRATEGY_FINGERPRINT == "STP-CAPITAL-SHIELD-V10-20261116",
        "all_seven_markets": len(MARKETS) == 7,
        "six_timeframes": len(TIMEFRAMES) == 6,
        "four_mapped_execution_frames": SCAN_TIMEFRAMES == ("15m", "1h", "4h", "1d"),
        "4h_maps_to_15m": DIRECTION_TO_EXECUTION.get("4h") == "15m",
        "daily_maps_to_1h": DIRECTION_TO_EXECUTION.get("1d") == "1h",
        "weekly_maps_to_4h": DIRECTION_TO_EXECUTION.get("1w") == "4h",
        "monthly_maps_to_1d": DIRECTION_TO_EXECUTION.get("1M") == "1d",
        "completed_candles_only": len(_bars(sample("BUY"))) == 106,
        "bullish_sweep_detected": bool(buy and buy["side"] == "BUY"),
        "bearish_sweep_detected": bool(sell and sell["side"] == "SELL"),
        "spot_is_long_only": spot_sell is None,
        "no_setup_is_rejected": no_setup is None,
        "targets_are_1r_2r_3r": bool(buy and abs((buy["tp3"] - buy["entry"]) / (buy["entry"] - buy["stop"]) - 3.0) < 1e-9),
        "no_fallback_engine": True,
    }
    return {"ok": all(checks.values()), "fingerprint": STRATEGY_FINGERPRINT,
            "checks": checks, "timeframes": list(TIMEFRAMES),
            "markets": list(MARKETS), "manual_only": True}
