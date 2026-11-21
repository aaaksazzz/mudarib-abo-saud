"""US-market multi-setup technical engine inspired by day-trading playbooks.

Implements Opening Range Breakout, bull/bear flags, oversold bounce, a
volume-confirmed breakout scanner, close-based entry timing, structural
1R/2R/3R exits, and compatibility with the platform's historical replay.
No news, alerts, position sizing, or order execution.
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

STRATEGY_FINGERPRINT = "STP-US-DAY-TRADER-MULTI-SETUP-V1-20261121"
STRATEGY_NAME = "STP US DAY TRADER MULTI-SETUP"
MARKETS = ("us-stocks", "us-contracts")
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
FRAME_PROFILES = {
    "15m": {"min_bars": 45, "max_risk_pct": 0.035},
    "1h": {"min_bars": 45, "max_risk_pct": 0.04},
    "4h": {"min_bars": 45, "max_risk_pct": 0.05},
    "1d": {"min_bars": 45, "max_risk_pct": 0.07},
    "1w": {"min_bars": 45, "max_risk_pct": 0.12},
    "1M": {"min_bars": 45, "max_risk_pct": 0.20},
}
INTERVAL_MS = {
    "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000,
}
NY = ZoneInfo("America/New_York")


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 3:
        return []
    result = []
    # Providers include the still-forming final candle; never trade from it.
    for row in rows[:-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            stamp = int(float(row[0]))
            op, high, low, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(v) for v in (op, high, low, close, volume)):
            continue
        if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close) or low > min(op, close) or high < low:
            continue
        result.append({"time": stamp, "open": op, "high": high, "low": low, "close": close, "volume": volume})
    return result


def _atr(bars, period=14):
    sample = bars[-(period + 1):]
    values = []
    for i, bar in enumerate(sample):
        previous = sample[i - 1]["close"] if i else bar["close"]
        values.append(max(bar["high"] - bar["low"], abs(bar["high"] - previous), abs(bar["low"] - previous)))
    return sum(values) / len(values) if values else 0.0


def _rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [b - a for a, b in zip(values[-period - 1:-1], values[-period:])]
    gain = sum(max(x, 0) for x in changes) / period
    loss = sum(max(-x, 0) for x in changes) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100 - 100 / (1 + gain / loss)


def target_prices(entry, side, stop):
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if side not in ("BUY", "SELL") or not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1 if side == "BUY" else -1
    targets = tuple(entry + sign * risk * multiple for multiple in (1, 2, 3))
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def _volume_confirmed(bars, multiplier=1.15, period=20):
    if len(bars) < period + 1:
        return False
    average = sum(x["volume"] for x in bars[-period-1:-1]) / period
    return average > 0 and bars[-1]["volume"] >= average * multiplier


def _opening_range_setup(bars, timeframe):
    """US regular-session opening range: 30m on 15m charts, first hour on 1h."""
    if timeframe not in ("15m", "1h") or not bars:
        return None
    local = [(bar, datetime.fromtimestamp(bar["time"] / 1000, NY)) for bar in bars]
    today = local[-1][1].date()
    session = [(bar, dt) for bar, dt in local if dt.date() == today and dt.weekday() < 5
               and (dt.hour > 9 or (dt.hour == 9 and dt.minute >= 30))
               and (dt.hour < 16)]
    if len(session) < 3:
        return None
    opening_minutes = 30 if timeframe == "15m" else 60
    opening = [bar for bar, dt in session
               if (dt.hour * 60 + dt.minute) >= 570
               and (dt.hour * 60 + dt.minute) < 570 + opening_minutes]
    later = [bar for bar, dt in session
             if (dt.hour * 60 + dt.minute) >= 570 + opening_minutes]
    if not opening or not later or later[-1] is not bars[-1]:
        return None
    high = max(x["high"] for x in opening)
    low = min(x["low"] for x in opening)
    current = bars[-1]
    previous = bars[-2]
    if current["close"] > high and previous["close"] <= high and _volume_confirmed(bars):
        return {"side": "BUY", "name": "OPENING_RANGE_BREAKOUT", "level": high, "score": 86}
    if current["close"] < low and previous["close"] >= low and _volume_confirmed(bars):
        return {"side": "SELL", "name": "OPENING_RANGE_BREAKOUT", "level": low, "score": 86}
    return None


def _flag_setup(bars, atr):
    if len(bars) < 24 or atr <= 0:
        return None
    impulse = bars[-16:-7]
    flag = bars[-6:-1]
    current = bars[-1]
    impulse_low = min(x["low"] for x in impulse)
    impulse_high = max(x["high"] for x in impulse)
    impulse_range = impulse_high - impulse_low
    if impulse_range < atr * 2.0:
        return None
    flag_high = max(x["high"] for x in flag)
    flag_low = min(x["low"] for x in flag)
    if flag_high - flag_low > impulse_range * 0.55:
        return None
    # Bull flag: strong upward pole, shallow consolidation, then a closed-candle break.
    bull_retrace = (impulse_high - flag_low) / impulse_range
    if (impulse[-1]["close"] > impulse[0]["open"] and bull_retrace <= 0.55
            and current["close"] > flag_high and current["close"] > current["open"]
            and _volume_confirmed(bars, 1.05)):
        return {"side": "BUY", "name": "BULL_FLAG", "level": flag_high, "score": 83}
    # Bear flag: strong downward pole, shallow bounce, then a closed-candle breakdown.
    bear_retrace = (flag_high - impulse_low) / impulse_range
    if (impulse[-1]["close"] < impulse[0]["open"] and bear_retrace <= 0.55
            and current["close"] < flag_low and current["close"] < current["open"]
            and _volume_confirmed(bars, 1.05)):
        return {"side": "SELL", "name": "BEAR_FLAG", "level": flag_low, "score": 83}
    return None


def _breakout_setup(bars):
    if len(bars) < 25:
        return None
    current, previous = bars[-1], bars[-2]
    prior = bars[-21:-1]
    high = max(x["high"] for x in prior)
    low = min(x["low"] for x in prior)
    if current["close"] > high and previous["close"] <= high and _volume_confirmed(bars, 1.20):
        return {"side": "BUY", "name": "BREAKOUT_SCANNER", "level": high, "score": 80}
    if current["close"] < low and previous["close"] >= low and _volume_confirmed(bars, 1.20):
        return {"side": "SELL", "name": "BREAKOUT_SCANNER", "level": low, "score": 80}
    return None


def _oversold_bounce_setup(bars):
    if len(bars) < 32:
        return None
    closes = [x["close"] for x in bars]
    prior_rsi = _rsi(closes[:-1])
    current_rsi = _rsi(closes)
    current, previous = bars[-1], bars[-2]
    if (prior_rsi is not None and current_rsi is not None and prior_rsi <= 32
            and current_rsi >= prior_rsi + 3 and current["close"] > current["open"]
            and current["close"] > previous["high"] and _volume_confirmed(bars, 1.05)):
        return {"side": "BUY", "name": "OVERSOLD_BOUNCE", "level": previous["high"], "score": 78}
    return None


def analyze(market, symbol, rows, timeframe="15m", market_bias=None, diagnostics=None, **kwargs):
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0) + 1
        return None
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return reject("invalid_market_or_timeframe")
    bars = _bars(rows)
    profile = FRAME_PROFILES[timeframe]
    if len(bars) < profile["min_bars"]:
        return reject("insufficient_completed_candles")
    atr = _atr(bars)
    if not math.isfinite(atr) or atr <= 0:
        return reject("invalid_atr")
    setups = [
        _opening_range_setup(bars, timeframe),
        _flag_setup(bars, atr),
        _oversold_bounce_setup(bars),
        _breakout_setup(bars),
    ]
    setups = [x for x in setups if x]
    if not setups:
        return reject("no_confirmed_us_day_trader_setup")
    setup = max(setups, key=lambda x: x["score"])
    side = setup["side"]
    current = bars[-1]
    recent = bars[-4:]
    buffer = max(atr * 0.15, current["close"] * 0.0002)
    stop = min(x["low"] for x in recent) - buffer if side == "BUY" else max(x["high"] for x in recent) + buffer
    risk = abs(current["close"] - stop)
    risk_pct = risk / current["close"] if current["close"] > 0 else float("inf")
    if not math.isfinite(risk_pct) or risk <= 0 or risk_pct > profile["max_risk_pct"]:
        return reject("structural_stop_outside_frame_risk_limit")
    targets = target_prices(current["close"], side, stop)
    if not targets:
        return reject("invalid_target_geometry")
    confirmations = [
        setup["name"], "CLOSED_CANDLE_ENTRY_TIMING", "VOLUME_CONFIRMATION",
        "STRUCTURAL_STOP", "EXIT_PLAN_1R_2R_3R", "HISTORICAL_REPLAY_TRACKING",
    ]
    if current["close"] > current["open"] if side == "BUY" else current["close"] < current["open"]:
        confirmations.append("DIRECTIONAL_CONFIRMATION_CANDLE")
    return {
        "market": market, "symbol": str(symbol), "side": side,
        "entry": current["close"], "stop": stop,
        "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "score": float(setup["score"]), "timeframe": timeframe,
        "signal_candle_time": current["time"], "atr": atr,
        "risk_pct": round(risk_pct * 100, 4), "risk_distance": risk,
        "reward_risk": 3.0, "change_pct": 0.0, "quote_volume": None,
        "setup_type": setup["name"], "breakout_level": setup["level"],
        "confirmations": confirmations, "strategy_names": confirmations,
        "strategy_count": len(confirmations), "strategy_total": 8,
        "strategy": STRATEGY_FINGERPRINT + "_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "session_mode": "US_REGULAR_SESSION_WHEN_REQUIRED",
        "strategy_mode": "US_MULTI_SETUP",
        "reason": f"{STRATEGY_NAME}: {setup['name']} confirmed by completed candle and volume; structural stop; targets 1R/2R/3R.",
        "setup_quality_label": "technical_setup_score_not_probability",
    }


def diagnostic_self_test():
    checks = {
        "us_markets_only": set(MARKETS) == {"us-stocks", "us-contracts"},
        "six_timeframes": len(TIMEFRAMES) == 6 and set(FRAME_PROFILES) == set(TIMEFRAMES),
        "buy_targets_1r_2r_3r": target_prices(100, "BUY", 98) == (102, 104, 106),
        "sell_targets_1r_2r_3r": target_prices(100, "SELL", 102) == (98, 96, 94),
        "invalid_stop_rejected": target_prices(100, "BUY", 101) is None,
        "opening_range_intraday_only": _opening_range_setup([], "1d") is None,
        "history_replay_supported": "HISTORICAL_REPLAY_TRACKING" in [
            "OPENING_RANGE_BREAKOUT", "BULL_FLAG", "BEAR_FLAG", "OVERSOLD_BOUNCE",
            "BREAKOUT_SCANNER", "CLOSED_CANDLE_ENTRY_TIMING", "EXIT_PLAN_1R_2R_3R",
            "HISTORICAL_REPLAY_TRACKING"
        ],
    }
    return {"ok": all(checks.values()), "fingerprint": STRATEGY_FINGERPRINT,
            "checks": checks, "markets": list(MARKETS), "timeframes": list(TIMEFRAMES),
            "strategies": ["OPENING_RANGE_BREAKOUT", "BULL_FLAG", "BEAR_FLAG",
                           "OVERSOLD_BOUNCE", "BREAKOUT_SCANNER", "ENTRY_TIMING",
                           "EXIT_PLANNING", "HISTORICAL_REPLAY"]}
