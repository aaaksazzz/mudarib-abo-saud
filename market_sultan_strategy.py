"""SULTAN multi-timeframe price-action strategy.

Direction is established on weekly, daily and 4-hour completed candles.
A 15-minute completed-candle setup is the only execution trigger.
No indicators, synthetic news scores, or automated order execution.
"""
import math

TIMEFRAMES = ("1w", "1d", "4h", "15m")
DIRECTION_TIMEFRAMES = ("1w", "1d", "4h")
ENTRY_TIMEFRAME = "15m"
FINGERPRINT = "SULTAN-PRICE-ACTION-W-D-4H-15M-V1-20261109"
CASH_MARKETS = frozenset(("spot", "alpha", "us-stocks", "saudi"))


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 25:
        return []
    out = []
    # Exclude the provider's still-forming candle.
    for row in rows[:-1]:
        try:
            if len(row) < 6:
                continue
            stamp = int(float(row[0]))
            op, hi, lo, close, volume = (float(row[i] or 0) for i in range(1, 6))
            if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)):
                continue
            if min(op, hi, lo, close) <= 0 or volume < 0:
                continue
            if hi < max(op, close) or lo > min(op, close) or hi < lo:
                continue
            out.append((stamp, op, hi, lo, close, volume))
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    return out


def _direction(rows):
    """Return UP/DOWN/NEUTRAL from price structure and closed-candle momentum."""
    bars = _bars(rows)
    if len(bars) < 22:
        return "NEUTRAL"
    highs = [x[2] for x in bars]
    lows = [x[3] for x in bars]
    closes = [x[4] for x in bars]

    pivot_highs, pivot_lows = [], []
    for i in range(2, len(bars) - 2):
        if highs[i] >= max(highs[i-2:i]) and highs[i] > max(highs[i+1:i+3]):
            pivot_highs.append(highs[i])
        if lows[i] <= min(lows[i-2:i]) and lows[i] < min(lows[i+1:i+3]):
            pivot_lows.append(lows[i])

    higher_highs = len(pivot_highs) >= 2 and pivot_highs[-1] > pivot_highs[-2]
    higher_lows = len(pivot_lows) >= 2 and pivot_lows[-1] > pivot_lows[-2]
    lower_highs = len(pivot_highs) >= 2 and pivot_highs[-1] < pivot_highs[-2]
    lower_lows = len(pivot_lows) >= 2 and pivot_lows[-1] < pivot_lows[-2]

    # Require structure plus momentum; a single large candle cannot set the trend.
    recent_mid = sum(closes[-5:]) / 5
    prior_mid = sum(closes[-15:-5]) / 10
    if higher_highs and higher_lows and recent_mid > prior_mid and closes[-1] > closes[-6]:
        return "UP"
    if lower_highs and lower_lows and recent_mid < prior_mid and closes[-1] < closes[-6]:
        return "DOWN"
    return "NEUTRAL"


def direction_stack(weekly, daily, four_hour):
    directions = {
        "1w": _direction(weekly),
        "1d": _direction(daily),
        "4h": _direction(four_hour),
    }
    up = sum(value == "UP" for value in directions.values())
    down = sum(value == "DOWN" for value in directions.values())
    # Two aligned timeframes are enough only when the third is neutral.
    # Any opposing higher-timeframe direction blocks the setup.
    if up >= 2 and down == 0:
        return "BUY", directions
    if down >= 2 and up == 0:
        return "SELL", directions
    return None, directions


def inspect(item, market, klines_fn, pattern_fn, atr_fn, levels_fn):
    symbol = str(item.get("symbol") or "").strip()
    if not symbol:
        return None
    candles = {}
    for timeframe, limit in (("1w", 120), ("1d", 120), ("4h", 120), ("15m", 120)):
        try:
            rows = klines_fn(market, symbol, timeframe, limit)
        except Exception as exc:
            raise RuntimeError(timeframe + " candle provider failed: " + type(exc).__name__) from exc
        if len(_bars(rows)) < 22:
            raise RuntimeError("Insufficient completed " + timeframe + " candles")
        candles[timeframe] = rows

    bias, directions = direction_stack(candles["1w"], candles["1d"], candles["4h"])
    if not bias:
        return None
    pattern = pattern_fn(candles[ENTRY_TIMEFRAME])
    if not pattern or pattern.get("side") != bias:
        return None
    if bias == "SELL" and market in CASH_MARKETS:
        return None

    bars = _bars(candles[ENTRY_TIMEFRAME])
    entry_close = float(pattern.get("entry") or bars[-1][4])
    entry = float(item.get("price") or entry_close)
    atr = float(atr_fn(candles[ENTRY_TIMEFRAME]) or 0)
    if not all(math.isfinite(x) and x > 0 for x in (entry, entry_close, atr)):
        return None
    # Reject late entries when the live quote has already moved too far from
    # the completed 15m trigger candle.
    if abs(entry - entry_close) > atr * 0.60:
        return None

    pad = max(atr * 0.08, entry * 0.0003)
    invalidation = float(pattern["invalidation"])
    stop = invalidation - pad if bias == "BUY" else invalidation + pad
    levels = levels_fn(entry, stop, bias, candles[ENTRY_TIMEFRAME])
    if not levels:
        return None

    aligned = sum(value == ("UP" if bias == "BUY" else "DOWN") for value in directions.values())
    score = min(96, 68 + aligned * 5 + int(pattern.get("strength") or 0) * 3)
    return {
        "market": market, "symbol": symbol, "side": bias,
        "timeframe": ENTRY_TIMEFRAME, "entry_timeframe": ENTRY_TIMEFRAME,
        "direction_timeframes": directions,
        "pattern": pattern.get("kind", "تأكيد حركة السعر"),
        "entry": round(entry, 10), "stop": round(levels["stop"], 10),
        "tp1": round(levels["tp1"], 10), "tp2": round(levels["tp2"], 10),
        "tp3": round(levels["tp3"], 10),
        "risk_pct": round(levels["risk_pct"], 3),
        "reward_risk_tp3": round(levels["reward_risk_tp3"], 2),
        "confirmations": aligned, "score": score,
        "quote_volume": item.get("quote_volume"),
        "change_pct_24h": item.get("change_pct"),
        "analysis": "اتجاه أسبوعي + يومي + 4 ساعات، ودخول بعد تأكيد شمعة 15 دقيقة مكتملة",
        "news_context": "راجع الأخبار والأحداث المؤثرة قبل التنفيذ؛ لم تُحتسب عناوين غير مرتبطة بالأصل كإشارة",
        "strategy_fingerprint": FINGERPRINT,
    }
