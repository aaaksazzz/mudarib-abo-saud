"""Independent trade-quality analysis; this module does not generate orders or claim win probabilities."""
from __future__ import annotations
import math
from typing import Any, Sequence

TIMEFRAMES = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w", "1w": "1M", "1M": "1M"}

def _bars(rows: Sequence[Any]) -> list[dict[str, float]]:
    out = []
    for row in rows or []:
        try:
            # Binance kline array: open time, open, high, low, close, volume, close time...
            if isinstance(row, (list, tuple)):
                bar = {"open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
                       "close": float(row[4]), "volume": float(row[5])}
            else:
                bar = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            vals = list(bar.values())
            if not all(math.isfinite(v) for v in vals) or min(bar[k] for k in ("open","high","low","close")) <= 0 or bar["volume"] < 0:
                return []
            if bar["high"] < max(bar["open"], bar["close"], bar["low"]) or bar["low"] > min(bar["open"], bar["close"], bar["high"]):
                return []
            out.append(bar)
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            return []
    return out

def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for x in values[period:]:
        value = alpha * x + (1 - alpha) * value
    return value if math.isfinite(value) else None

def analyze_trade(candles: Sequence[Any], higher_candles: Sequence[Any], market: str, symbol: str, timeframe: str) -> dict[str, Any]:
    """Score evidence quality from closed OHLCV candles. Score is not a success probability."""
    result = {"ok": True, "market": market, "symbol": symbol, "timeframe": timeframe,
              "higher_timeframe": TIMEFRAMES.get(timeframe), "action": "WAIT", "quality_score": 0,
              "entry": None, "stop_loss": None, "take_profit_1": None, "take_profit_2": None,
              "risk_reward_gross": None, "checks": {}, "reasons": [], "probability": None}
    bars, higher = _bars(candles), _bars(higher_candles)
    if timeframe not in TIMEFRAMES:
        result.update(ok=False, reasons=["الفريم غير مدعوم"])
        return result
    if len(bars) < 60 or len(higher) < 50:
        result["reasons"] = ["بيانات الشموع المغلقة غير كافية للتحليل المستقل"]
        return result
    closes = [b["close"] for b in bars]
    hcloses = [b["close"] for b in higher]
    last, prev = bars[-1], bars[-2]
    price = last["close"]
    e20, e50, e200 = _ema(closes, 20), _ema(closes, 50), _ema(closes, 200)
    he50, he200 = _ema(hcloses, 50), _ema(hcloses, 200)
    # EMA200 is optional when the feed has fewer than 200 bars, never fabricate it.
    if e20 is None or e50 is None or he50 is None:
        result["reasons"] = ["تعذر حساب اتجاه موثوق من البيانات المتاحة"]
        return result
    trend_up = price > e50 and e20 > e50 and (e200 is None or price > e200)
    trend_down = price < e50 and e20 < e50 and (e200 is None or price < e200)
    higher_up = hcloses[-1] > he50 and (he200 is None or he50 > he200)
    higher_down = hcloses[-1] < he50 and (he200 is None or he50 < he200)
    prior = bars[-21:-1]
    support = min(b["low"] for b in prior)
    resistance = max(b["high"] for b in prior)
    tr = [max(bars[i]["high"]-bars[i]["low"], abs(bars[i]["high"]-bars[i-1]["close"]), abs(bars[i]["low"]-bars[i-1]["close"])) for i in range(len(bars)-14, len(bars))]
    atr = sum(tr) / len(tr) if tr else 0
    avgvol = sum(b["volume"] for b in bars[-21:-1]) / 20
    vol_ok = avgvol > 0 and last["volume"] >= avgvol * 1.2
    bullish = price > last["open"] and (price-last["low"]) / max(last["high"]-last["low"], 1e-12) >= .55
    bearish = price < last["open"] and (last["high"]-price) / max(last["high"]-last["low"], 1e-12) >= .55
    buy = trend_up and higher_up and bullish and vol_ok
    sell = trend_down and higher_down and bearish and vol_ok
    result["checks"] = {
        "trend_current": "صاعد" if trend_up else ("هابط" if trend_down else "مختلط"),
        "trend_higher": "صاعد" if higher_up else ("هابط" if higher_down else "مختلط"),
        "volume_confirmed": bool(vol_ok),
        "near_support": bool(abs(price-support) <= max(atr, price*.002)),
        "near_resistance": bool(abs(price-resistance) <= max(atr, price*.002)),
        "closed_candles_only": True,
        "ema200_available": e200 is not None and he200 is not None,
    }
    if buy == sell:
        reasons = []
        if not (higher_up or higher_down): reasons.append("اتجاه الفريم الأعلى غير واضح")
        if not (trend_up or trend_down): reasons.append("اتجاه الفريم الحالي غير مؤكد")
        if not vol_ok: reasons.append("حجم التداول لا يؤكد الحركة")
        if not (bullish or bearish): reasons.append("الشمعة الأخيرة لا تؤكد الاتجاه")
        result["reasons"] = reasons or ["تعارض شروط الشراء والبيع؛ الأفضل الانتظار"]
        return result
    action = "BUY" if buy else "SELL"
    direction = 1 if buy else -1
    stop = min(last["low"], min(b["low"] for b in bars[-5:])) - .1*atr if buy else max(last["high"], max(b["high"] for b in bars[-5:])) + .1*atr
    risk = abs(price-stop)
    if atr <= 0 or risk <= 0 or risk > 3*atr:
        result["reasons"] = ["وقف الخسارة غير منطقي مقارنة بالتذبذب؛ لا تُعتمد الصفقة"]
        return result
    # Quality score weights evidence, not a predicted win rate.
    checks = [trend_up if buy else trend_down, higher_up if buy else higher_down, vol_ok, bullish if buy else bearish,
              result["checks"]["near_support"] if buy else result["checks"]["near_resistance"]]
    score = round(100 * sum(bool(x) for x in checks) / len(checks))
    result.update(action=action, quality_score=score, entry=round(price, 8), stop_loss=round(stop, 8),
                  take_profit_1=round(price + direction*1.5*risk, 8),
                  take_profit_2=round(price + direction*2.0*risk, 8),
                  risk_reward_gross=2.0,
                  reasons=["توافق اتجاه الفريم الحالي والأعلى", "الزخم وحجم التداول يؤكدان الحركة" if vol_ok else "حجم التداول غير مؤكد",
                           "درجة الجودة تقيس توافق الشروط وليست احتمال نجاح الصفقة",
                           "لم تُحتسب الرسوم والانزلاق؛ تحقق منها قبل اتخاذ أي قرار"])
    return result
