"""GAMMA PRO liquidity engine.

This module deliberately separates observable liquidity behaviour from options gamma.
It never fabricates dealer positioning or gamma exposure when no options feed exists.
"""
from statistics import median
import time


def analyse_liquidity_candidate(rows, current_price, side):
    """Return a validated 15m liquidity-sweep/absorption setup, or None."""
    if side not in ("BUY", "SELL") or len(rows) < 25:
        return None
    bars = rows[-21:]
    signal = bars[-1]
    prior = bars[:-1]
    try:
        current = float(current_price)
        high = float(signal["high"])
        low = float(signal["low"])
        open_price = float(signal["open"])
        close = float(signal["close"])
        volume = max(0.0, float(signal.get("volume", 0) or 0))
        prior_volumes = [max(0.0, float(x.get("volume", 0) or 0)) for x in prior]
        if min(current, high, low, open_price, close) <= 0 or high < low:
            return None
        volume_base = median(prior_volumes) if prior_volumes else 0.0
        volume_ratio = volume / volume_base if volume_base > 0 else 0.0
        previous_close = float(prior[-1]["close"])
        true_ranges = []
        for bar in rows[-15:]:
            prev = previous_close
            bar_high, bar_low = float(bar["high"]), float(bar["low"])
            true_ranges.append(max(bar_high - bar_low, abs(bar_high - prev), abs(bar_low - prev)))
            previous_close = float(bar["close"])
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        if atr <= 0:
            return None
        pool_low = min(float(x["low"]) for x in prior)
        pool_high = max(float(x["high"]) for x in prior)
        candle_range = max(high - low, 1e-12)
        body = abs(close - open_price)
        lower_wick = min(open_price, close) - low
        upper_wick = high - max(open_price, close)
        pressure = max(-1.0, min(1.0, (2.0 * close - high - low) / candle_range))

        sweep_buy = low < pool_low and close > pool_low
        sweep_sell = high > pool_high and close < pool_high
        absorb_buy = (close <= pool_low + 0.30 * atr
                      and lower_wick >= max(body * 1.5, 0.20 * atr)
                      and volume_ratio >= 1.25)
        absorb_sell = (close >= pool_high - 0.30 * atr
                       and upper_wick >= max(body * 1.5, 0.20 * atr)
                       and volume_ratio >= 1.25)
        if side == "BUY":
            event = "سحب سيولة بيع واسترداد" if sweep_buy else "امتصاص بيع قرب الدعم"
            valid_event = sweep_buy or absorb_buy
            confirmation = close > open_price and pressure >= -0.05
            extreme = low
        else:
            event = "سحب سيولة شراء ورفض" if sweep_sell else "امتصاص شراء قرب المقاومة"
            valid_event = sweep_sell or absorb_sell
            confirmation = close < open_price and pressure <= 0.05
            extreme = high
        if not valid_event or not confirmation:
            return None
        if volume_ratio < 1.05:
            return None

        buffer = max(atr * 0.12, current * 0.0005)
        stop = extreme - buffer if side == "BUY" else extreme + buffer
        if stop <= 0:
            return None
        risk = current - stop if side == "BUY" else stop - current
        if risk <= 0 or risk / current > 0.045:
            return None
        sign = 1 if side == "BUY" else -1
        score = 55
        score += 18 if (sweep_buy if side == "BUY" else sweep_sell) else 10
        score += min(12, max(0, (volume_ratio - 1.0) * 8))
        score += min(10, abs(pressure) * 10)
        score += 5 if confirmation else 0
        score = round(min(95, score), 1)
        return {
            "side": side,
            "entry": current,
            "stop_loss": stop,
            "tp1": current + sign * risk,
            "tp2": current + sign * risk * 2,
            "tp3": current + sign * risk * 3,
            "risk_percent": round(risk / current * 100, 3),
            "quality_score": score,
            "liquidity_event": event,
            "volume_ratio": round(volume_ratio, 2),
            "flow_pressure": round(pressure, 3),
            "flow_label": "ضغط شمعة تقديري من OHLCV، وليس Delta منفذاً",
            "gamma_status": "غير متاح: لا يوجد مصدر بيانات خيارات موثوق لهذا الأصل",
            "gamma_exposure": None,
            "created_at": int(time.time()),
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
