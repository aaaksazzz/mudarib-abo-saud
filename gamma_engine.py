"""Cross-market liquidity engine. Observable OHLCV only; options GEX remains provider-specific."""
from statistics import median
import time

MARKET_PROFILES = {
    "spot": {"label": "Crypto Spot", "volume_source": "base_asset_volume", "min_volume_ratio": 1.05},
    "futures": {"label": "Crypto Perpetual Futures", "volume_source": "contract_base_volume", "min_volume_ratio": 1.05},
    "alpha": {"label": "Binance Alpha", "volume_source": "base_asset_volume", "min_volume_ratio": 1.10},
    "us": {"label": "US Equities", "volume_source": "shares_volume", "min_volume_ratio": 1.15},
    "saudi": {"label": "Saudi Equities", "volume_source": "shares_volume", "min_volume_ratio": 1.15},
    "forex": {"label": "FX and Metals", "volume_source": "tick_volume", "min_volume_ratio": 1.00},
    "contracts": {"label": "US Listed Contracts", "volume_source": "provider_volume", "min_volume_ratio": 1.15},
}


def analyse_liquidity_candidate(rows, current_price, side, market_kind="spot"):
    """Return a confirmed liquidity sweep/absorption setup or None.

    Each instrument is compared only with its own native-volume baseline.
    Rows must be normalized to open/high/low/close/volume/time.
    """
    profile = MARKET_PROFILES.get(market_kind, MARKET_PROFILES["spot"])
    if side not in ("BUY", "SELL") or not isinstance(rows, (list, tuple)) or len(rows) < 25:
        return None
    bars, signal = rows[-21:], rows[-1]
    prior = bars[:-1]
    try:
        current = float(current_price)
        high, low = float(signal["high"]), float(signal["low"])
        open_price, close = float(signal["open"]), float(signal["close"])
        volume = max(0.0, float(signal.get("volume", 0) or 0))
        prior_volumes = [max(0.0, float(x.get("volume", 0) or 0)) for x in prior]
        if min(current, high, low, open_price, close) <= 0 or high < low:
            return None
        volume_base = median(prior_volumes) if prior_volumes else 0.0
        if volume_base <= 0 or volume <= 0:
            return None
        volume_ratio = volume / volume_base

        recent_rows, true_ranges = rows[-15:], []
        for index, bar in enumerate(recent_rows):
            prev = float(recent_rows[index - 1]["close"]) if index else float(rows[-16]["close"])
            bar_high, bar_low = float(bar["high"]), float(bar["low"])
            true_ranges.append(max(bar_high - bar_low, abs(bar_high - prev), abs(bar_low - prev)))
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        if atr <= 0:
            return None

        pool_low = min(float(x["low"]) for x in prior)
        pool_high = max(float(x["high"]) for x in prior)
        candle_range = max(high - low, 1e-12)
        body = abs(close - open_price)
        lower_wick, upper_wick = min(open_price, close) - low, high - max(open_price, close)
        pressure = max(-1.0, min(1.0, (2.0 * close - high - low) / candle_range))
        sweep_buy, sweep_sell = low < pool_low and close > pool_low, high > pool_high and close < pool_high
        threshold = profile["min_volume_ratio"]
        absorb_buy = (close <= pool_low + 0.30 * atr and lower_wick >= max(body * 1.5, 0.20 * atr)
                      and volume_ratio >= threshold)
        absorb_sell = (close >= pool_high - 0.30 * atr and upper_wick >= max(body * 1.5, 0.20 * atr)
                       and volume_ratio >= threshold)
        if side == "BUY":
            event = "سحب سيولة بيع واسترداد" if sweep_buy else "امتصاص بيع قرب الدعم"
            valid_event, confirmation, extreme = sweep_buy or absorb_buy, close > open_price and pressure >= -0.05, low
        else:
            event = "سحب سيولة شراء ورفض" if sweep_sell else "امتصاص شراء قرب المقاومة"
            valid_event, confirmation, extreme = sweep_sell or absorb_sell, close < open_price and pressure <= 0.05, high
        if not valid_event or not confirmation or volume_ratio < threshold:
            return None

        buffer = max(atr * 0.12, current * 0.0005)
        stop = extreme - buffer if side == "BUY" else extreme + buffer
        if stop <= 0:
            return None
        risk = current - stop if side == "BUY" else stop - current
        if risk <= 0 or risk / current > 0.045:
            return None
        sign = 1 if side == "BUY" else -1
        score = 55 + (18 if (sweep_buy if side == "BUY" else sweep_sell) else 10)
        score += min(12, max(0, (volume_ratio - 1.0) * 8)) + min(10, abs(pressure) * 10) + 5
        return {
            "side": side, "entry": current, "stop_loss": stop,
            "tp1": current + sign * risk, "tp2": current + sign * risk * 2,
            "tp3": current + sign * risk * 3, "risk_percent": round(risk / current * 100, 3),
            "quality_score": round(min(95, score), 1), "liquidity_event": event,
            "volume_ratio": round(volume_ratio, 2), "flow_pressure": round(pressure, 3),
            "flow_label": "ضغط سعري تقديري من OHLCV؛ ليس Delta منفذاً",
            "liquidity_engine": "GAMMA PRO Cross-Market", "market_profile": profile["label"],
            "volume_source": profile["volume_source"],
            "gamma_status": "يتطلب مزود خيارات مستقل؛ غير متاح لهذا الأصل/السوق",
            "gamma_exposure": None, "created_at": int(time.time()),
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
