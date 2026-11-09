"""Deterministic weekly -> daily -> 4H -> 15m strategy pipeline.

Input candle rows use the Binance kline layout: [open_time, open, high, low,
close, volume, ...]. The forming final candle is excluded. This module has no
network access and never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import math

TIMEFRAMES = ("1w", "1d", "4h", "15m")
CASH_MARKETS = frozenset({"spot", "alpha", "us-stocks", "saudi"})


@dataclass(frozen=True)
class FrameRead:
    timeframe: str
    direction: str
    strength: str
    label: str
    score: int
    reason: str


@dataclass(frozen=True)
class StrategyResult:
    status: str
    side: str | None
    weekly: dict[str, Any]
    daily: dict[str, Any] | None
    four_hour: dict[str, Any] | None
    entry_15m: dict[str, Any] | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _closed(rows: Any) -> list[tuple[float, float, float, float, float]]:
    if not isinstance(rows, (list, tuple)) or len(rows) < 24:
        return []
    parsed = []
    for row in rows[:-1]:
        try:
            op, high, low, close, volume = (float(row[i]) for i in range(1, 6))
            if not all(math.isfinite(x) for x in (op, high, low, close, volume)):
                continue
            if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close) or low > min(op, close) or high < low:
                continue
            parsed.append((op, high, low, close, volume))
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    return parsed


def read_frame(timeframe: str, rows: Any) -> FrameRead:
    bars = _closed(rows)
    if len(bars) < 22:
        return FrameRead(timeframe, "WAIT", "NONE", "انتظار", 0, "بيانات شموع مكتملة غير كافية")
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    closes = [b[3] for b in bars]
    volumes = [b[4] for b in bars]
    # Confirmed local swing points (two bars on each side).
    ph, pl = [], []
    for i in range(2, len(bars) - 2):
        if highs[i] >= max(highs[i-2:i]) and highs[i] > max(highs[i+1:i+3]):
            ph.append(highs[i])
        if lows[i] <= min(lows[i-2:i]) and lows[i] < min(lows[i+1:i+3]):
            pl.append(lows[i])
    if len(ph) < 2 or len(pl) < 2:
        return FrameRead(timeframe, "WAIT", "NONE", "انتظار", 0, "القمم والقيعان غير كافية لتحديد اتجاه")
    up_structure = ph[-1] > ph[-2] and pl[-1] > pl[-2]
    down_structure = ph[-1] < ph[-2] and pl[-1] < pl[-2]
    momentum_up = sum(closes[-5:]) / 5 > sum(closes[-15:-5]) / 10 and closes[-1] > closes[-6]
    momentum_down = sum(closes[-5:]) / 5 < sum(closes[-15:-5]) / 10 and closes[-1] < closes[-6]
    vol_base = sum(volumes[-21:-1]) / 20
    vol_ratio = volumes[-1] / vol_base if vol_base > 0 else 1.0
    if up_structure and momentum_up:
        score = 70 + (10 if vol_ratio >= 1.5 else 0) + (10 if closes[-1] > ph[-1] else 0)
        strong = score >= 80
        return FrameRead(timeframe, "BUY", "STRONG" if strong else "NORMAL", "شراء قوي" if strong else "شراء", min(score, 95), "قمم وقيعان صاعدة مع زخم إيجابي")
    if down_structure and momentum_down:
        score = 70 + (10 if vol_ratio >= 1.5 else 0) + (10 if closes[-1] < pl[-1] else 0)
        strong = score >= 80
        return FrameRead(timeframe, "SELL", "STRONG" if strong else "NORMAL", "بيع قوي" if strong else "بيع", min(score, 95), "قمم وقيعان هابطة مع زخم سلبي")
    return FrameRead(timeframe, "WAIT", "NONE", "انتظار", 0, "لا يوجد اتجاه سعري مكتمل")


def analyze(candles: dict[str, Any], market: str, setup_15m: dict[str, Any] | None = None) -> StrategyResult:
    """Run the timeframes in order; 15m setup is accepted only after alignment.

    setup_15m is a detector result with side, entry, stop, tp1, tp2, tp3.
    This function validates direction/alignment; it does not fabricate levels.
    """
    weekly = read_frame("1w", candles.get("1w"))
    if weekly.direction == "WAIT":
        return StrategyResult("WAIT", None, asdict(weekly), None, None, None, "لا يوجد اتجاه أسبوعي واضح")
    daily = read_frame("1d", candles.get("1d"))
    if daily.direction not in ("WAIT", weekly.direction):
        return StrategyResult("BLOCKED", None, asdict(weekly), asdict(daily), None, None, "اليومي يعاكس الاتجاه الأسبوعي")
    if daily.direction == "WAIT":
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), None, None, "انتظار وضوح الاتجاه اليومي")
    four_hour = read_frame("4h", candles.get("4h"))
    if four_hour.direction not in ("WAIT", weekly.direction):
        return StrategyResult("BLOCKED", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "الأربع ساعات تعاكس الاتجاه الأعلى")
    if four_hour.direction == "WAIT":
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "انتظار تأكيد الأربع ساعات")
    if market in CASH_MARKETS and weekly.direction == "SELL":
        return StrategyResult("BLOCKED", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "السوق النقدي لا يصدر صفقات بيع")
    if not isinstance(setup_15m, dict) or setup_15m.get("side") != weekly.direction:
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "الاتجاه متوافق؛ ننتظر إشارة دخول مكتملة على 15 دقيقة")
    required = ("entry", "stop", "tp1", "tp2", "tp3")
    try:
        levels = {key: float(setup_15m[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        levels = {}
    if len(levels) != 5 or not all(math.isfinite(v) and v > 0 for v in levels.values()):
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "مستويات الدخول والأهداف غير مكتملة")
    if weekly.direction == "BUY" and not (levels["stop"] < levels["entry"] < levels["tp1"] < levels["tp2"] < levels["tp3"]):
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "ترتيب مستويات الشراء غير صالح")
    if weekly.direction == "SELL" and not (levels["stop"] > levels["entry"] > levels["tp1"] > levels["tp2"] > levels["tp3"]):
        return StrategyResult("WAIT", None, asdict(weekly), asdict(daily), asdict(four_hour), None, "ترتيب مستويات البيع غير صالح")
    return StrategyResult("SIGNAL", weekly.direction, asdict(weekly), asdict(daily), asdict(four_hour), {"timeframe": "15m", **levels}, "توافق أسبوعي ويومي و4 ساعات مع دخول 15 دقيقة")
