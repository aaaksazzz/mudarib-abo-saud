"""15m order-block formation with 1m retest entries.

A bullish order block is the last high-volume bearish candle before a confirmed
upward displacement. A bearish order block is the inverse. Entry is considered
only when a closed 1m candle retests the zone and confirms rejection.
"""
import math

PROFILES = {
    "spot": {"volume_ratio": 1.70, "long_only": True},
    "alpha": {"volume_ratio": 1.80, "long_only": True},
    "futures": {"volume_ratio": 1.65, "long_only": False},
    "us-stocks": {"volume_ratio": 1.55, "long_only": True},
    "us-contracts": {"volume_ratio": 1.50, "long_only": False},
    "saudi": {"volume_ratio": 1.40, "long_only": True},
    "forex": {"volume_ratio": 1.25, "long_only": False},
}


def _atr(highs, lows, closes, period=14):
    ranges = []
    for i in range(1, len(closes)):
        ranges.append(max(highs[i] - lows[i],
                          abs(highs[i] - closes[i - 1]),
                          abs(lows[i] - closes[i - 1])))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 3:
        return None
    try:
        parsed = []
        for row in rows:
            values = [float(row[i] or 0) for i in range(6)]
            if not all(math.isfinite(x) for x in values):
                return None
            timestamp, op, high, low, close, volume = values
            if min(op, high, low, close) <= 0 or volume < 0 or high < low:
                return None
            parsed.append((int(timestamp), op, high, low, close, volume))
        return parsed
    except (IndexError, TypeError, ValueError, OverflowError):
        return None


def analyze(market, symbol, rows, include_micro=False, micro_rows=None,
            use_candle_extremes=True, risk_reward=2.0,
            enable_fvg=True, enable_volume=True):
    """Find a 15m high-volume order block and confirm its retest on 1m."""
    profile = PROFILES.get(market)
    bars = _bars(rows)
    micro = _bars(micro_rows)
    if not profile or not bars or len(bars) < 45 or not micro or len(micro) < 4:
        return None

    # Ignore the still-forming final candle on both timeframes.
    bars = bars[:-1]
    micro = micro[:-1]
    if len(bars) < 25 or len(micro) < 3:
        return None

    try:
        o = [x[1] for x in bars]
        h = [x[2] for x in bars]
        l = [x[3] for x in bars]
        c = [x[4] for x in bars]
        v = [x[5] for x in bars]
        atr = _atr(h, l, c, 14)
        if atr <= 0:
            return None

        # The most recent 15m bar defines the active market context.
        current_price = c[-1]
        current_time = bars[-1][0]
        micro = [x for x in micro if x[0] >= current_time - 15 * 60 * 1000]
        if len(micro) < 3:
            return None
        trigger = micro[-1]
        previous = micro[-2]
        _, mo, mh, ml, mc, mv = trigger
        if mc <= 0:
            return None

        # Search recent closed 15m candles for the last opposite candle
        # before a meaningful displacement. The displacement must happen
        # after the candidate candle, not on the same candle.
        candidates = []
        first = max(20, len(bars) - 32)
        last = len(bars) - 3
        for i in range(first, last):
            op, hi, lo, close, volume = o[i], h[i], l[i], c[i], v[i]
            baseline = sum(v[i - 20:i]) / 20.0
            if baseline <= 0 or hi <= lo:
                continue
            ratio = volume / baseline
            if enable_volume and ratio < profile["volume_ratio"]:
                continue

            # Bullish OB: high-volume bearish candle, then strong upward
            # displacement through its high within the next four candles.
            if close < op:
                future = bars[i + 1:min(i + 5, len(bars))]
                if not future:
                    continue
                displacement = max(x[4] for x in future)
                if displacement < hi + atr * 0.35:
                    continue
                zone_low, zone_high = lo, op
                direction = "BUY"
            # Bearish OB: high-volume bullish candle, then strong downward
            # displacement through its low.
            elif close > op and not profile["long_only"]:
                future = bars[i + 1:min(i + 5, len(bars))]
                if not future:
                    continue
                displacement = min(x[4] for x in future)
                if displacement > lo - atr * 0.35:
                    continue
                zone_low, zone_high = op, hi
                direction = "SELL"
            else:
                continue

            if zone_low <= 0 or zone_high <= zone_low:
                continue
            # Require a later return to the zone; don't chase the impulse.
            if not (ml <= zone_high and mh >= zone_low):
                continue
            if direction == "BUY" and not (mc > mo and mc >= previous[4]):
                continue
            if direction == "SELL" and not (mc < mo and mc <= previous[4]):
                continue

            # 1m fair-value gap: newest closed candle vs two bars earlier.
            if enable_fvg:
                two_back = micro[-3]
                bullish_fvg = ml > two_back[2]
                bearish_fvg = mh < two_back[3]
                if direction == "BUY" and not bullish_fvg:
                    continue
                if direction == "SELL" and not bearish_fvg:
                    continue

            # If 15m relative-volume filtering is disabled, retain a 1m
            # reaction-volume check at the actual retest.
            if enable_volume and ratio < profile["volume_ratio"]:
                recent_volumes = [x[5] for x in micro[:-1]][-20:]
                volume_average = sum(recent_volumes) / max(1, len(recent_volumes))
                if volume_average <= 0 or mv < volume_average * 1.5:
                    continue
            candidates.append((i, direction, zone_low, zone_high, ratio))

        if not candidates:
            return None

        # Use the latest valid, unmitigated retest setup.
        i, side, zone_low, zone_high, volume_ratio = candidates[-1]
        entry = mc
        if not (zone_low <= entry <= zone_high):
            return None

        # Both risk and reward are anchored to the same high-volume
        # 15m order-block candle: BUY targets its high and stops at its low;
        # SELL targets its low and stops at its high.
        if use_candle_extremes:
            if side == "BUY":
                target, stop = h[i], l[i]
                if not (stop < entry < target):
                    return None
            else:
                target, stop = l[i], h[i]
                if not (target < entry < stop):
                    return None
        else:
            rr = float(risk_reward)
            if not math.isfinite(rr) or rr <= 0:
                return None
            risk_distance = entry - l[i] if side == "BUY" else h[i] - entry
            if risk_distance <= 0:
                return None
            stop = l[i] if side == "BUY" else h[i]
            target = entry + risk_distance * rr if side == "BUY" else entry - risk_distance * rr

        risk = entry - stop if side == "BUY" else stop - entry
        reward = target - entry if side == "BUY" else entry - target
        if risk <= 0 or reward <= 0 or risk > atr * 2.5:
            return None
        score = min(95.0, 60.0 + min(volume_ratio - profile["volume_ratio"], 2.0) * 12.0)

        return {
            "side": side,
            "entry": entry,
            "stop": stop,
            "tp1": target,
            "tp2": target,
            "tp3": target,
            "score": round(score, 1),
            "timeframe": "15m / 1m entry",
            "change_pct": round((entry / c[-2] - 1.0) * 100.0, 5),
            "change_15m_pct": round((entry / c[-2] - 1.0) * 100.0, 5),
            "reason": (f"{side} order-block retest: 15m high-volume opposite candle, "
                       f"1m retest entry; target and stop use that candle high/low; "
                       f"volume {volume_ratio:.2f}x"),
            "signal_candle_time": int(bars[i][0]),
            "risk_atr": round(risk / atr, 3),
            "reward_risk": round(reward / risk, 3),
            "volume_ratio": round(volume_ratio, 3),
            "order_block_low": round(zone_low, 10),
            "order_block_high": round(zone_high, 10),
            "volume_candle_high": round(h[i], 10),
            "volume_candle_low": round(l[i], 10),
            "strategy": f"FVG_ORDER_BLOCK_VOLUME_{market.upper()}",
            "fvg_enabled": bool(enable_fvg),
            "volume_enabled": bool(enable_volume),
            "candle_extremes_enabled": bool(use_candle_extremes),
            "risk_reward_setting": float(risk_reward),
        }
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
