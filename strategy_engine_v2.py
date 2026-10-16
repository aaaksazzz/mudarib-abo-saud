"""Conservative multi-market strategy candidate: trend + liquidity sweep + reclaim.

Signal generator only; no order execution and no guarantee of profitability.
Use closed candles, realistic fees/slippage, out-of-sample walk-forward testing.
"""
from __future__ import annotations
from typing import Any, Sequence
import math


def _ema(xs: Sequence[float], n: int) -> list[float]:
    if len(xs) < n:
        return []
    a = 2.0 / (n + 1.0)
    out = [sum(xs[:n]) / n]
    for x in xs[n:]:
        out.append(a * x + (1 - a) * out[-1])
    return out


def _atr(cs: Sequence[dict[str, float]], n: int = 14) -> float | None:
    if len(cs) < n + 1:
        return None
    tr = []
    for p, c in zip(cs[-n-1:-1], cs[-n:]):
        h, l, pc = float(c["high"]), float(c["low"]), float(p["close"])
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    value = sum(tr) / n
    return value if math.isfinite(value) and value > 0 else None


def evaluate_v2(
    candles: Sequence[dict[str, float]],
    higher_candles: Sequence[dict[str, float]],
    *,
    market: str = "unknown",
    timeframe: str = "15m",
    estimated_round_trip_cost_pct: float = 0.20,
    risk_per_trade_pct: float = 0.5,
    min_net_rr: float = 2.0,
) -> dict[str, Any]:
    """Return BUY/SELL candidate or WAIT. Input candles must already be closed."""
    result: dict[str, Any] = {
        "strategy": "Confluence v2: HTF trend + liquidity sweep/reclaim",
        "market": market, "timeframe": timeframe, "action": "WAIT",
        "status": "WAIT", "score": 0, "entry": None, "stop_loss": None,
        "take_profit_1": None, "take_profit_2": None, "risk_reward_net": None,
        "risk_per_trade_pct": min(max(float(risk_per_trade_pct), 0.1), 0.5),
        "reasons": []
    }
    if len(candles) < 220 or len(higher_candles) < 50:
        result["reasons"] = ["بيانات مغلقة غير كافية: نحتاج 220 شمعة للفريم الحالي و50 للأعلى"]
        return result
    try:
        close = [float(x["close"]) for x in candles]
        high = [float(x["high"]) for x in candles]
        low = [float(x["low"]) for x in candles]
        volume = [float(x["volume"]) for x in candles]
        hclose = [float(x["close"]) for x in higher_candles]
        hhigh = [float(x["high"]) for x in candles]
        hlow = [float(x["low"]) for x in candles]
        if not all(math.isfinite(v) and v > 0 for v in close + high + low + hclose):
            result["reasons"] = ["بيانات سعر غير صالحة"]
            return result
        if not all(math.isfinite(v) and v >= 0 for v in volume):
            result["reasons"] = ["بيانات حجم غير صالحة"]
            return result
    except (KeyError, TypeError, ValueError):
        result["reasons"] = ["صيغة الشموع غير صحيحة"]
        return result

    e20, e50, e200 = _ema(close, 20), _ema(close, 50), _ema(close, 200)
    he50, he200 = _ema(hclose, 50), _ema(hclose, 200)
    # Fall back to a 50-period higher-timeframe trend when 200 candles are unavailable.
    higher_trend_up = (hclose[-1] > he200[-1] and he50[-1] > he200[-1]) if he200 else hclose[-1] > he50[-1]
    higher_trend_down = (hclose[-1] < he200[-1] and he50[-1] < he200[-1]) if he200 else hclose[-1] < he50[-1]
    atr = _atr(candles)
    if not all((e20, e50, e200, he50, atr)):
        result["reasons"] = ["تعذر حساب الاتجاه أو التذبذب"]
        return result

    px, last_open, last_high, last_low = close[-1], float(candles[-1]["open"]), high[-1], low[-1]
    if atr <= 0 or abs(px - e20[-1]) > 2.5 * atr:
        result["reasons"] = ["تذبذب غير مناسب أو السعر ممتد؛ لا نطارد الحركة"]
        return result

    # Prior 20-bar liquidity levels exclude the current candle.
    prior_low = min(low[-21:-1])
    prior_high = max(high[-21:-1])
    avg_vol = sum(volume[-21:-1]) / 20.0
    vol_confirm = avg_vol > 0 and volume[-1] >= 1.2 * avg_vol
    bullish_reclaim = last_low < prior_low and px > prior_low and px > last_open
    bearish_reclaim = last_high > prior_high and px < prior_high and px < last_open

    long_trend = px > e200[-1] and higher_trend_up
    short_trend = px < e200[-1] and higher_trend_down
    momentum_long = e20[-1] > e50[-1]
    momentum_short = e20[-1] < e50[-1]

    candidates = []
    bullish_breakout = px > prior_high and px > last_open
    bearish_breakout = px < prior_low and px < last_open
    # Allow a controlled trend-continuation setup as well as sweep/reclaim or breakout.
    # This avoids requiring a rare liquidity event on every scan while keeping multiple confirmations.
    bullish_continuation = (
        long_trend and momentum_long and px > e20[-1]
        and close[-1] > close[-2] > close[-3]
        and (vol_confirm or close[-1] > last_open)
    )
    bearish_continuation = (
        short_trend and momentum_short and px < e20[-1]
        and close[-1] < close[-2] < close[-3]
        and (vol_confirm or close[-1] < last_open)
    )
    if long_trend and (momentum_long or bullish_reclaim) and (bullish_reclaim or bullish_breakout or bullish_continuation):
        score = 4 + int(vol_confirm) + int(bullish_continuation)
        setup = "استعادة قاع سابق" if bullish_reclaim else "اختراق قمة النطاق بإغلاق صاعد" if bullish_breakout else "استمرار اتجاه صاعد بزخم متتابع"
        candidates.append(("BUY", score, ["اتجاه الفريمين صاعد", setup, "زخم السعر مؤيد"] + (["حجم التداول مؤكد"] if vol_confirm else [])))
    if short_trend and (momentum_short or bearish_reclaim) and (bearish_reclaim or bearish_breakout or bearish_continuation):
        score = 4 + int(vol_confirm) + int(bearish_continuation)
        setup = "فشل اختراق قمة سابقة" if bearish_reclaim else "كسر قاع النطاق بإغلاق هابط" if bearish_breakout else "استمرار اتجاه هابط بزخم متتابع"
        candidates.append(("SELL", score, ["اتجاه الفريمين هابط", setup, "زخم السعر مؤيد"] + (["حجم التداول مؤكد"] if vol_confirm else [])))
    if len(candidates) != 1:
        result["reasons"] = ["لا يوجد توافق فريد بين الاتجاه وسحب السيولة والإغلاق؛ انتظار"]
        return result

    action, score, reasons = candidates[0]
    direction = 1 if action == "BUY" else -1
    if action == "BUY":
        stop = min(last_low, min(low[-5:])) - 0.1 * atr
        risk = px - stop
    else:
        stop = max(last_high, max(high[-5:])) + 0.1 * atr
        risk = stop - px
    if risk <= 0 or risk > 2.5 * atr:
        result["reasons"] = ["وقف الخسارة واسع أو غير منطقي بالنسبة للتذبذب"]
        return result

    cost = px * max(0.0, float(estimated_round_trip_cost_pct)) / 100.0
    gross_reward = 2.5 * risk
    net_rr = (gross_reward - cost) / (risk + cost)
    if net_rr < min_net_rr:
        result["reasons"] = ["العائد المتوقع بعد التكلفة لا يحقق الحد الأدنى"]
        return result

    result.update({
        "action": action, "status": "CANDIDATE", "score": score,
        "entry": round(px, 8), "stop_loss": round(stop, 8),
        "take_profit_1": round(px + direction * 2.0 * risk, 8),
        "take_profit_2": round(px + direction * 2.5 * risk, 8),
        "risk_reward_net": round(net_rr, 2),
        "reasons": reasons + [
            "المخاطرة المقترحة لا تتجاوز 0.5% من رأس المال",
            "مرشح للاختبار فقط؛ ليس ضمانًا للربح ولا أمر تداول"
        ]
    })
    return result
