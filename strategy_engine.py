"""Confluence strategy engine for SMART TRADING PRO.

This module is intentionally feed-agnostic: callers provide OHLCV candles for the
market/timeframe. It emits a candidate or WAIT; it never executes orders.
No strategy can guarantee zero losses. Backtest with fees/slippage before use.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional, Sequence
import math


@dataclass
class StrategyDecision:
    action: str
    score: int
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    risk_reward: Optional[float]
    reasons: list[str]
    strategy: str = "Multi-Market Confluence v1"
    status: str = "WAIT"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ema(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [sum(values[:period]) / period]
    for value in values[period:]:
        out.append(value * alpha + out[-1] * (1.0 - alpha))
    return out


def _atr(candles: Sequence[dict[str, float]], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    ranges = []
    for prev, cur in zip(candles[-period-1:-1], candles[-period:]):
        high, low, close_prev = float(cur["high"]), float(cur["low"]), float(prev["close"])
        ranges.append(max(high - low, abs(high - close_prev), abs(low - close_prev)))
    value = sum(ranges) / len(ranges)
    return value if math.isfinite(value) and value > 0 else None


def evaluate_signal(
    candles: Sequence[dict[str, float]],
    higher_timeframe_candles: Sequence[dict[str, float]],
    *,
    market: str = "unknown",
    timeframe: str = "15m",
    fee_slippage_pct: float = 0.20,
    min_score: int = 5,
    min_net_reward_risk: float = 1.8,
) -> dict[str, Any]:
    """Evaluate closed OHLCV candles only. Returns WAIT unless all safety gates pass.

    Candle keys: open, high, low, close, volume. Supply higher timeframe candles
    from the same symbol/market (e.g. 15m setup + 4h trend). Exclude the still-open
    candle from both sequences.
    """
    wait = StrategyDecision("WAIT", 0, None, None, None, None, None,
                            ["بيانات غير كافية أو لا يوجد توافق واضح"], status="WAIT")
    if len(candles) < 220 or len(higher_timeframe_candles) < 220:
        wait.reasons = ["ننتظر 220 شمعة مغلقة على الفريمين لتجنب قرار مبني على بيانات ناقصة"]
        return wait.to_dict()

    try:
        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        htf_closes = [float(c["close"]) for c in higher_timeframe_candles]
        if not all(math.isfinite(x) and x > 0 for x in closes + highs + lows + htf_closes):
            return wait.to_dict()
        if any(not math.isfinite(v) or v < 0 for v in volumes):
            return wait.to_dict()
    except (KeyError, TypeError, ValueError):
        wait.reasons = ["صيغة بيانات الشموع غير صحيحة"]
        return wait.to_dict()

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    htf50 = _ema(htf_closes, 50)
    htf200 = _ema(htf_closes, 200)
    atr = _atr(candles)
    if not all((ema20, ema50, ema200, htf50, htf200, atr)):
        return wait.to_dict()

    price = closes[-1]
    e20, e50, e200 = ema20[-1], ema50[-1], ema200[-1]
    higher_price, he50, he200 = htf_closes[-1], htf50[-1], htf200[-1]
    # Use only candles before the current closed candle to define the breakout range.
    lookback_high = max(highs[-21:-1])
    lookback_low = min(lows[-21:-1])
    avg_volume = sum(volumes[-21:-1]) / 20.0
    volume_ok = avg_volume > 0 and volumes[-1] >= 1.3 * avg_volume

    long_score = 0
    short_score = 0
    long_reasons: list[str] = []
    short_reasons: list[str] = []

    if price > e200 and e50 > e200:
        long_score += 2; long_reasons.append("السعر وEMA50 فوق EMA200")
    if higher_price > he200 and he50 > he200:
        long_score += 2; long_reasons.append("اتجاه الفريم الأعلى صاعد")
    if e20 > e50:
        long_score += 1; long_reasons.append("زخم الفريم الحالي إيجابي")
    if price > lookback_high:
        long_score += 1; long_reasons.append("اختراق قمة آخر 20 شمعة")
    if volume_ok:
        long_score += 1; long_reasons.append("حجم التداول أعلى من متوسطه 30%")

    if price < e200 and e50 < e200:
        short_score += 2; short_reasons.append("السعر وEMA50 تحت EMA200")
    if higher_price < he200 and he50 < he200:
        short_score += 2; short_reasons.append("اتجاه الفريم الأعلى هابط")
    if e20 < e50:
        short_score += 1; short_reasons.append("زخم الفريم الحالي سلبي")
    if price < lookback_low:
        short_score += 1; short_reasons.append("كسر قاع آخر 20 شمعة")
    if volume_ok:
        short_score += 1; short_reasons.append("حجم التداول أعلى من متوسطه 30%")

    # Avoid chasing an extended move and avoid ambiguous conflicting trends.
    if abs(price - e20) > 1.8 * atr:
        wait.reasons = ["السعر ممتد بعيدًا عن EMA20؛ لا نطارد الحركة"]
        return wait.to_dict()
    if long_score >= min_score and long_score > short_score:
        action, score, reasons = "BUY", long_score, long_reasons
        entry = price
        stop = min(lows[-7:]) - 0.15 * atr
        risk = entry - stop
        direction = 1
    elif short_score >= min_score and short_score > long_score:
        action, score, reasons = "SELL", short_score, short_reasons
        entry = price
        stop = max(highs[-7:]) + 0.15 * atr
        risk = stop - entry
        direction = -1
    else:
        wait.score = max(long_score, short_score)
        wait.reasons = ["التوافق غير كافٍ؛ لا دخول أفضل من صفقة ضعيفة"]
        return wait.to_dict()

    if not math.isfinite(risk) or risk <= 0 or risk > 2.5 * atr:
        wait.reasons = ["وقف الخسارة غير منطقي مقارنة بالتذبذب"]
        return wait.to_dict()

    # Costs are deducted from expected reward for a conservative net R:R check.
    gross_tp1 = entry + direction * 2.0 * risk
    gross_tp2 = entry + direction * 3.0 * risk
    estimated_cost = entry * max(0.0, fee_slippage_pct) / 100.0
    net_reward_risk = (2.0 * risk - estimated_cost) / (risk + estimated_cost)
    if net_reward_risk < min_net_reward_risk:
        wait.reasons = ["العائد المتوقع بعد تقدير الرسوم والانزلاق لا يحقق الحد الأدنى"]
        return wait.to_dict()

    reasons.append(f"السوق: {market} | الفريم: {timeframe}")
    reasons.append("إدارة المخاطر: مخاطرة مقترحة لا تتجاوز 0.5% من رأس المال")
    reasons.append("النتيجة مرشح للاختبار وليست ضمانًا للربح")
    return StrategyDecision(
        action=action, score=score, entry=round(entry, 8),
        stop_loss=round(stop, 8), take_profit_1=round(gross_tp1, 8),
        take_profit_2=round(gross_tp2, 8), risk_reward=round(net_reward_risk, 2),
        reasons=reasons, status="CANDIDATE"
    ).to_dict()
