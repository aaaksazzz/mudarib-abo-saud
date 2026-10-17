"""Unified multi-timeframe strategy for SMART TRADING PRO.
Signal generation only; never submits orders. Uses closed OHLCV candles.
"""
from __future__ import annotations
from typing import Any, Sequence
import math


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = float(item) * alpha + value * (1.0 - alpha)
    return value if math.isfinite(value) else None


def _ema_series(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value = float(values[i]) * alpha + value * (1.0 - alpha)
        out[i] = value
    return out


def _rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(float(values[i]) - float(values[i - 1]), 0.0) for i in range(1, len(values))]
    losses = [max(float(values[i - 1]) - float(values[i]), 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def value(g: float, l: float) -> float:
        if l <= 1e-15:
            return 100.0 if g > 1e-15 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)
    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def _atr(candles: Sequence[dict[str, float]], n: int = 14) -> float | None:
    if len(candles) < n + 1:
        return None
    trs = []
    for prev, cur in zip(candles[-n-1:-1], candles[-n:]):
        h, l, pc = float(cur["high"]), float(cur["low"]), float(prev["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    value = sum(trs) / n
    return value if math.isfinite(value) and value > 0 else None


def evaluate_v2(
    candles: Sequence[dict[str, float]],
    higher_candles: Sequence[dict[str, float]],
    *,
    market: str = "unknown",
    timeframe: str = "15m",
    estimated_round_trip_cost_pct: float = 0.20,
    risk_per_trade_pct: float = 0.5,
    min_net_rr: float = 1.6,
) -> dict[str, Any]:
    """Return BUY/SELL only when timeframe setup, volume and higher-timeframe trend agree."""
    result: dict[str, Any] = {
        "strategy": "EMA20/50 + RSI Bounce + Volume + Higher-Timeframe Trend/Support",
        "market": market, "timeframe": timeframe, "action": "WAIT",
        "status": "WAIT", "score": 0, "entry": None, "stop_loss": None,
        "take_profit_1": None, "take_profit_2": None, "risk_reward_net": None,
        "risk_per_trade_pct": min(max(float(risk_per_trade_pct), 0.1), 0.5),
        "reasons": []
    }
    if len(candles) < 60 or len(higher_candles) < 30:
        result["reasons"] = ["بيانات الشموع المغلقة غير كافية للفريم الحالي والفريم الأعلى"]
        return result
    try:
        for bar in list(candles) + list(higher_candles):
            values = [float(bar[k]) for k in ("open", "high", "low", "close", "volume")]
            o, h, l, c, v = values
            if any(not math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or v < 0:
                result["reasons"] = ["بيانات سعر أو حجم غير صالحة"]
                return result
            if h < max(o, c, l) or l > min(o, c, h):
                result["reasons"] = ["شموع غير متطابقة؛ تم إيقاف الإشارة"]
                return result
        closes = [float(x["close"]) for x in candles]
        highs = [float(x["high"]) for x in candles]
        lows = [float(x["low"]) for x in candles]
        opens = [float(x["open"]) for x in candles]
        volumes = [float(x["volume"]) for x in candles]
        hcloses = [float(x["close"]) for x in higher_candles]
    except (KeyError, TypeError, ValueError):
        result["reasons"] = ["صيغة الشموع غير صحيحة"]
        return result

    atr = _atr(candles)
    if not atr:
        result["reasons"] = ["تعذر حساب نطاق الحركة"]
        return result

    e20s, e50s = _ema_series(closes, 20), _ema_series(closes, 50)
    rsi = _rsi(closes, 14)
    he20 = _ema(hcloses, 20)
    he50 = _ema(hcloses, 50)
    if e20s[-1] is None or e50s[-1] is None or e20s[-2] is None or e50s[-2] is None or rsi[-1] is None or rsi[-2] is None or he20 is None:
        result["reasons"] = ["المؤشرات تحتاج شموعًا أكثر"]
        return result

    px, op, hi, lo = closes[-1], opens[-1], highs[-1], lows[-1]
    prev_e20, prev_e50 = float(e20s[-2]), float(e50s[-2])
    e20, e50 = float(e20s[-1]), float(e50s[-1])
    current_rsi, previous_rsi = float(rsi[-1]), float(rsi[-2])
    higher_bull = hcloses[-1] > he20 and (he50 is None or he20 >= he50)
    higher_bear = hcloses[-1] < he20 and (he50 is None or he20 <= he50)

    # Each timeframe has its own RSI rebound zone and volume threshold.
    profiles = {
        "15m": (35.0, 65.0, 1.50),
        "1h": (40.0, 60.0, 1.35),
        "4h": (42.0, 58.0, 1.25),
        "1d": (45.0, 55.0, 1.20),
        "1w": (48.0, 52.0, 1.15),
        "1M": (48.0, 52.0, 1.10),
    }
    oversold, overbought, volume_multiple = profiles.get(timeframe, profiles["15m"])
    avg_volume = sum(volumes[-21:-1]) / 20.0
    volume_ok = avg_volume > 0 and volumes[-1] >= avg_volume * volume_multiple

    # RSI must turn up from the lower zone (buy), or turn down from the upper zone (sell).
    rsi_bounce_up = previous_rsi <= oversold and current_rsi > previous_rsi
    rsi_bounce_down = previous_rsi >= overbought and current_rsi < previous_rsi
    cross_up = prev_e20 <= prev_e50 and e20 > e50
    cross_down = prev_e20 >= prev_e50 and e20 < e50

    # For 15m, require the actual EMA crossover. Higher intervals can continue an established trend.
    ema_buy = cross_up if timeframe == "15m" else (e20 > e50 and (cross_up or closes[-2] <= prev_e20 or rsi_bounce_up))
    ema_sell = cross_down if timeframe == "15m" else (e20 < e50 and (cross_down or closes[-2] >= prev_e20 or rsi_bounce_down))

    # Support/resistance is measured from prior closed candles, excluding the current candle.
    support = min(lows[-21:-1])
    resistance = max(highs[-21:-1])
    near_support = lo <= support + 1.5 * atr or abs(px - e20) <= atr
    near_resistance = hi >= resistance - 1.5 * atr or abs(px - e20) <= atr
    bullish_candle = px > op and (px - lo) / max(hi - lo, 1e-12) >= 0.55
    bearish_candle = px < op and (hi - px) / max(hi - lo, 1e-12) >= 0.55

    buy_setup = higher_bull and ema_buy and rsi_bounce_up and volume_ok and near_support and bullish_candle
    sell_setup = higher_bear and ema_sell and rsi_bounce_down and volume_ok and near_resistance and bearish_candle
    if buy_setup == sell_setup:
        missing = []
        if not (higher_bull or higher_bear): missing.append("اتجاه الفريم الأعلى")
        if not (ema_buy or ema_sell): missing.append("اتجاه/تقاطع EMA20/50")
        if not (rsi_bounce_up or rsi_bounce_down): missing.append("ارتداد RSI")
        if not volume_ok: missing.append("حجم تداول مؤكد")
        if not (near_support or near_resistance): missing.append("دعم/مقاومة")
        result["reasons"] = ["انتظار: الشروط غير مكتملة — " + "، ".join(missing or ["تعارض شروط الشراء والبيع"])]
        return result

    action = "BUY" if buy_setup else "SELL"
    direction = 1 if action == "BUY" else -1
    if action == "BUY":
        stop = min(lo, min(lows[-5:])) - 0.1 * atr
        risk = px - stop
        reasons = ["اتجاه الفريم الأعلى صاعد", "EMA20/50 صاعد", "RSI ارتد من منطقة منخفضة", "حجم تداول مؤكد", "السعر عند دعم/إعادة اختبار", "شمعة صاعدة مؤكدة"]
    else:
        stop = max(hi, max(highs[-5:])) + 0.1 * atr
        risk = stop - px
        reasons = ["اتجاه الفريم الأعلى هابط", "EMA20/50 هابط", "RSI ارتد هبوطًا من منطقة مرتفعة", "حجم تداول مؤكد", "السعر عند مقاومة/إعادة اختبار", "شمعة هابطة مؤكدة"]

    if risk <= 0 or risk > 3.0 * atr:
        result["reasons"] = ["وقف الخسارة واسع أو غير منطقي بالنسبة للتذبذب"]
        return result
    cost_pct = max(0.0, float(estimated_round_trip_cost_pct))
    cost = px * cost_pct / 100.0
    gross_reward = 2.5 * risk
    net_rr = (gross_reward - cost) / (risk + cost)
    if net_rr < float(min_net_rr):
        result["reasons"] = ["العائد إلى المخاطرة بعد الرسوم والانزلاق لا يحقق الحد الأدنى"]
        return result

    score = 50 + 8 * len(reasons) + (5 if volume_ok else 0)
    result.update({
        "action": action, "status": "CANDIDATE", "score": min(98, score),
        "entry": round(px, 8), "stop_loss": round(stop, 8),
        "take_profit_1": round(px + direction * 2.0 * risk, 8),
        "take_profit_2": round(px + direction * 2.5 * risk, 8),
        "risk_reward_net": round(net_rr, 2),
        "reasons": reasons + [
            "تُستخدم الشموع المغلقة فقط؛ لا يوجد تنفيذ آلي للأوامر",
            "النتائج تحتاج اختبارًا تاريخيًا ورسومًا وانزلاقًا واقعيًا قبل الاعتماد"
        ]
    })
    return result
