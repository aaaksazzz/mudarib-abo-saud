"""Single approved multi-market strategy: SMC/ICT + Price Action + MTF structure.

Signal generation only. Uses closed OHLCV candles; candle volume is only a proxy,
not true bid/ask order flow or exchange volume-at-price. No order execution.
"""
from __future__ import annotations
from typing import Any, Sequence
import math


def _atr(candles: Sequence[dict[str, float]], n: int = 14) -> float | None:
    if len(candles) < n + 1:
        return None
    trs = []
    for prev, cur in zip(candles[-n-1:-1], candles[-n:]):
        h, l, pc = float(cur["high"]), float(cur["low"]), float(prev["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    value = sum(trs) / n
    return value if math.isfinite(value) and value > 0 else None


def _structure(candles: Sequence[dict[str, float]], window: int = 20) -> dict[str, float | bool]:
    sample = candles[-min(len(candles), window + 1):-1]
    highs = [float(x["high"]) for x in sample]
    lows = [float(x["low"]) for x in sample]
    if not highs or not lows:
        return {"high": 0.0, "low": 0.0, "bull": False, "bear": False}
    # Confirmed swing structure: compare the latest two separated pivot zones.
    mid = max(3, len(sample) // 2)
    first, second = sample[:mid], sample[mid:]
    fh = max(float(x["high"]) for x in first)
    sh = max(float(x["high"]) for x in second) if second else fh
    fl = min(float(x["low"]) for x in first)
    sl = min(float(x["low"]) for x in second) if second else fl
    return {"high": max(highs), "low": min(lows),
            "bull": sh > fh and sl > fl, "bear": sh < fh and sl < fl}


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
    """Return a single confluence BUY/SELL candidate, otherwise WAIT."""
    result: dict[str, Any] = {
        "strategy": "SMC/ICT + Price Action + MTF Structure + Volume Confirmation",
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
        fields = ("open", "high", "low", "close", "volume")
        for bar in list(candles) + list(higher_candles):
            for field in fields:
                value = float(bar.get(field, 0) or 0)
                if not math.isfinite(value) or (field != "volume" and value <= 0) or (field == "volume" and value < 0):
                    result["reasons"] = ["بيانات سعر أو حجم غير صالحة"]
                    return result
            o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
            if h < max(o, c, l) or l > min(o, c, h):
                result["reasons"] = ["شموع غير متطابقة؛ تم إيقاف الإشارة"]
                return result
        close = [float(x["close"]) for x in candles]
        high = [float(x["high"]) for x in candles]
        low = [float(x["low"]) for x in candles]
        opens = [float(x["open"]) for x in candles]
        volume = [float(x.get("volume", 0) or 0) for x in candles]
        hclose = [float(x["close"]) for x in higher_candles]
    except (KeyError, TypeError, ValueError):
        result["reasons"] = ["صيغة الشموع غير صحيحة"]
        return result

    atr = _atr(candles)
    if not atr:
        result["reasons"] = ["تعذر حساب نطاق الحركة"]
        return result
    px, op, hi, lo = close[-1], opens[-1], high[-1], low[-1]
    prev_close = close[-2]
    current = _structure(candles, 20)
    higher = _structure(higher_candles, 20)
    prior_high, prior_low = float(current["high"]), float(current["low"])
    if prior_high <= prior_low or abs(px - prev_close) > 3.5 * atr:
        result["reasons"] = ["النطاق غير مناسب أو السعر ممتد؛ لا نطارد الحركة"]
        return result

    # SMC/ICT liquidity sweep and reclaim; current closed candle must reclaim the level.
    bull_sweep = lo < prior_low and px > prior_low and px > op
    bear_sweep = hi > prior_high and px < prior_high and px < op
    # Price-action BOS/CHOCH via a decisive close beyond the prior range.
    bull_bos = px > prior_high and px > op and (px - op) >= 0.15 * atr
    bear_bos = px < prior_low and px < op and (op - px) >= 0.15 * atr
    # Three-candle fair-value-gap / displacement proxy.
    bull_fvg = len(candles) >= 3 and high[-3] < lo and px > op
    bear_fvg = len(candles) >= 3 and low[-3] > hi and px < op
    avg_vol = sum(volume[-21:-1]) / 20.0
    vol_confirm = avg_vol > 0 and volume[-1] >= 1.2 * avg_vol
    close_location = (px - lo) / max(hi - lo, 1e-12)
    bull_pressure = vol_confirm and close_location >= 0.65 and px > op
    bear_pressure = vol_confirm and close_location <= 0.35 and px < op

    # Multi-timeframe structure is a hard directional filter, not a moving-average substitute.
    higher_bull = bool(higher["bull"]) or hclose[-1] > hclose[-5] > hclose[-10]
    higher_bear = bool(higher["bear"]) or hclose[-1] < hclose[-5] < hclose[-10]
    bull_structure = bool(current["bull"]) or bull_bos
    bear_structure = bool(current["bear"]) or bear_bos

    buy_evidence = [
        ("MTF اتجاه الفريم الأعلى", higher_bull),
        ("Price Action هيكل صاعد", bull_structure),
        ("SMC سحب السيولة واستعادتها", bull_sweep),
        ("BOS اختراق هيكل بإغلاق قوي", bull_bos),
        ("ICT / FVG اندفاع سعري", bull_fvg),
        ("Order Flow proxy تأكيد الحجم والشمعة", orderflow_bull),
        ("Volume Profile proxy السعر فوق VWAP الحجمي", profile_bull),
        ("Wyckoff Spring", wyckoff_spring),
        ("CHOCH proxy انعكاس الهيكل", choch_bull),
        ("تأكيد ضغط الحجم", bull_pressure),
    ]
    sell_evidence = [
        ("MTF اتجاه الفريم الأعلى", higher_bear),
        ("Price Action هيكل هابط", bear_structure),
        ("SMC سحب السيولة وفشل الاختراق", bear_sweep),
        ("BOS كسر هيكل بإغلاق قوي", bear_bos),
        ("ICT / FVG اندفاع سعري هابط", bear_fvg),
        ("Order Flow proxy تأكيد الحجم والشمعة", orderflow_bear),
        ("Volume Profile proxy السعر تحت VWAP الحجمي", profile_bear),
        ("Wyckoff Upthrust", wyckoff_upthrust),
        ("CHOCH proxy انعكاس الهيكل", choch_bear),
        ("تأكيد ضغط الحجم", bear_pressure),
    ]
    buy_hits = [label for label, ok in buy_evidence if ok]
    sell_hits = [label for label, ok in sell_evidence if ok]
    # One unified strategy: MTF must align, and at least three distinct setup clues
    # must agree, including a structural/liquidity trigger and a volume/displacement clue.
    buy_trigger = bull_sweep or bull_bos or choch_bull
    sell_trigger = bear_sweep or bear_bos or choch_bear
    buy_confirmation_count = sum((bull_sweep, bull_bos, bull_fvg, orderflow_bull, profile_bull, wyckoff_spring, choch_bull, bull_pressure))
    sell_confirmation_count = sum((bear_sweep, bear_bos, bear_fvg, orderflow_bear, profile_bear, wyckoff_upthrust, choch_bear, bear_pressure))
    buy_setup = higher_bull and bull_structure and buy_trigger and buy_confirmation_count >= 3
    sell_setup = higher_bear and bear_structure and sell_trigger and sell_confirmation_count >= 3
    if buy_setup == sell_setup:  # neither side or conflicting signals
        result["reasons"] = ["انتظار: لم يكتمل توافق SMC/ICT والهيكل السعري والفريم الأعلى"]
        return result

    action = "BUY" if buy_setup else "SELL"
    reasons = buy_hits if buy_setup else sell_hits
    direction = 1 if action == "BUY" else -1
    if action == "BUY":
        stop = min(lo, min(low[-5:])) - 0.1 * atr
        risk = px - stop
    else:
        stop = max(hi, max(high[-5:])) + 0.1 * atr
        risk = stop - px
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

    result.update({
        "action": action, "status": "CANDIDATE", "score": min(100, 50 + 8 * len(reasons)),
        "entry": round(px, 8), "stop_loss": round(stop, 8),
        "take_profit_1": round(px + direction * 2.0 * risk, 8),
        "take_profit_2": round(px + direction * 2.5 * risk, 8),
        "risk_reward_net": round(net_rr, 2),
        "reasons": reasons + [
            "الاستراتيجية الموحدة تجمع 10 عناصر: SMC، ICT، Price Action، BOS/CHOCH، Liquidity Sweep، FVG، MTF، Order Flow proxy، Volume Profile proxy، Wyckoff",
            "Order Flow وVolume Profile هنا تقديرات من OHLCV/VWAP وليسا بيانات دفتر أوامر أو توزيع حجم سعري حقيقي",
            "المخاطرة المقترحة لا تتجاوز 0.5% من رأس المال؛ إشارة آلية وليست أمر تنفيذ"
        ]
    })
    return result
