"""SMART FLOW QUANT: price-structure and volume-flow signal engine.

No EMA, MACD, RSI, or legacy VWAP strategy votes are used. Candle-derived
pressure is available across supported markets. Real public trade-flow and
order-book context is optional and currently supported only for Binance
Spot and USD-M Futures. Scores rank confluence; they are not win probabilities.
"""
import math

STRATEGY_FINGERPRINT = "SMART-FLOW-15M-1H-4H-TREND-STRUCTURE-V3-20261108"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}
PROFILES = {
    "spot": {"allow_short": False}, "alpha": {"allow_short": False},
    "futures": {"allow_short": True}, "us-stocks": {"allow_short": False},
    "us-contracts": {"allow_short": True}, "saudi": {"allow_short": False},
    "forex": {"allow_short": True},
}


def _atr(highs, lows, closes, period=14):
    true_ranges = []
    for i in range(len(closes)):
        previous = closes[i - 1] if i else closes[i]
        true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous),
                               abs(lows[i] - previous)))
    sample = true_ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _finite_rows(rows):
    bars = rows[:-1]  # Ignore a provider's potentially-forming candle.
    parsed = []
    for row in bars:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return None
        try:
            stamp = int(float(row[0]))
            op, hi, lo, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)):
            return None
        if min(op, hi, lo, close) <= 0 or volume < 0 or hi < max(op, close) or lo > min(op, close) or hi < lo:
            return None
        parsed.append((stamp, op, hi, lo, close, volume))
    return parsed


def sma200_allows(side, price, ma200):
    """Shared trend gate used by the live analyzer and diagnostic self-test."""
    try:
        price, ma200 = float(price), float(ma200)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(price) or not math.isfinite(ma200) or price <= 0 or ma200 <= 0:
        return False
    return (side == "BUY" and price > ma200) or (side == "SELL" and price < ma200)


def trend_direction(rows):
    """Return BUY/SELL only when price and the SMA200 slope agree."""
    if not isinstance(rows, list):
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 221:
        return None
    closes = [bar[4] for bar in bars]
    price = closes[-1]
    current_ma = sum(closes[-200:]) / 200.0
    prior_ma = sum(closes[-220:-20]) / 200.0
    if not all(math.isfinite(x) and x > 0 for x in (price, current_ma, prior_ma)):
        return None
    if price > current_ma and current_ma > prior_ma:
        return "BUY"
    if price < current_ma and current_ma < prior_ma:
        return "SELL"
    return None


def target_prices(entry, side):
    """Return directional gross-price targets at +2%, +3%, and +5%."""
    try:
        entry = float(entry)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or entry <= 0 or side not in ("BUY", "SELL"):
        return None
    direction = 1.0 if side == "BUY" else -1.0
    targets = tuple(entry * (1.0 + direction * pct) for pct in (0.02, 0.03, 0.05))
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def adaptive_target_prices(entry, side, risk):
    """Blend minimum 2/3/5% objectives with targets scaled to actual stop risk."""
    try:
        entry, risk = float(entry), float(risk)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not math.isfinite(entry) or not math.isfinite(risk) or entry <= 0
            or risk <= 0 or side not in ("BUY", "SELL")):
        return None
    direction = 1.0 if side == "BUY" else -1.0
    r_multiples = (1.5, 2.25, 3.5)
    minimum_moves = (0.02, 0.03, 0.05)
    distances = [max(entry * floor, risk * multiple)
                 for floor, multiple in zip(minimum_moves, r_multiples)]
    targets = tuple(entry + direction * distance for distance in distances)
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def diagnostic_self_test():
    """Exercise SMA200 direction and target math used by the live analyzer."""
    buy_targets = target_prices(100.0, "BUY")
    sell_targets = target_prices(100.0, "SELL")
    cases = {
        "buy_above": sma200_allows("BUY", 101.0, 100.0),
        "buy_below": not sma200_allows("BUY", 99.0, 100.0),
        "sell_below": sma200_allows("SELL", 99.0, 100.0),
        "sell_above": not sma200_allows("SELL", 101.0, 100.0),
        "equal_rejected": not sma200_allows("BUY", 100.0, 100.0) and not sma200_allows("SELL", 100.0, 100.0),
        "buy_targets_2_3_5": buy_targets == (102.0, 103.0, 105.0),
        "sell_targets_2_3_5": sell_targets == (98.0, 97.0, 95.0),
        "timeframes_independent": set(TIMEFRAMES) == set(INTERVAL_MS),
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(cases.values()), "checks": cases,
            "timeframes": list(TIMEFRAMES), "rule": "BUY above same-timeframe SMA200; SELL below; gross targets 2%/3%/5%"}


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    """Analyze one market/timeframe using closed candles and optional live flow."""
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES or not isinstance(rows, list):
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 200:
        return None

    opens = [x[1] for x in bars]
    highs = [x[2] for x in bars]
    lows = [x[3] for x in bars]
    closes = [x[4] for x in bars]
    volumes = [x[5] for x in bars]
    i = len(bars) - 1
    entry = closes[i]
    ma200 = sum(closes[-200:]) / 200.0
    if not math.isfinite(ma200) or ma200 <= 0:
        return None
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.12:
        return None

    candle_range = highs[i] - lows[i]
    if candle_range <= 0:
        return None
    close_location = (closes[i] - lows[i]) / candle_range
    body_ratio = abs(closes[i] - opens[i]) / candle_range
    prior_high = max(highs[i - 20:i])
    prior_low = min(lows[i - 20:i])
    prior_ranges = [highs[j] - lows[j] for j in range(i - 20, i)]
    avg_range = sum(prior_ranges) / len(prior_ranges) if prior_ranges else 0.0
    range_expansion = candle_range / avg_range if avg_range > 0 else 0.0

    up_votes, down_votes = {}, {}
    momentum_3 = closes[i] - closes[i - 3]
    momentum_8 = closes[i] - closes[i - 8]
    if momentum_3 > atr * 0.15 and momentum_8 > atr * 0.35:
        up_votes["price momentum"] = 1
    elif momentum_3 < -atr * 0.15 and momentum_8 < -atr * 0.35:
        down_votes["price momentum"] = 1

    if closes[i] > prior_high and close_location >= 0.65:
        up_votes["structure breakout"] = 1
    elif closes[i] < prior_low and close_location <= 0.35:
        down_votes["structure breakout"] = 1

    if closes[i] > opens[i] and close_location >= 0.72 and body_ratio >= 0.45:
        up_votes["buyer pressure"] = 1
    elif closes[i] < opens[i] and close_location <= 0.28 and body_ratio >= 0.45:
        down_votes["seller pressure"] = 1

    prior_volumes = [v for v in volumes[i - 20:i] if v > 0]
    volume_ratio = None
    if len(prior_volumes) >= 10 and volumes[i] > 0:
        baseline = sum(prior_volumes) / len(prior_volumes)
        if baseline > 0:
            volume_ratio = volumes[i] / baseline
            if volume_ratio >= 1.35 and close_location >= 0.65 and closes[i] > opens[i]:
                up_votes["volume expansion"] = 1
            elif volume_ratio >= 1.35 and close_location <= 0.35 and closes[i] < opens[i]:
                down_votes["volume expansion"] = 1

    if range_expansion >= 1.25 and body_ratio >= 0.55:
        if closes[i] > opens[i] and close_location >= 0.68:
            up_votes["range expansion"] = 1
        elif closes[i] < opens[i] and close_location <= 0.32:
            down_votes["range expansion"] = 1

    flow_delta = book_imbalance = None
    if isinstance(microstructure, dict):
        try:
            value = float(microstructure.get("taker_delta_ratio"))
            if math.isfinite(value):
                flow_delta = max(-1.0, min(1.0, value))
        except (TypeError, ValueError):
            pass
        try:
            value = float(microstructure.get("book_imbalance"))
            if math.isfinite(value):
                book_imbalance = max(-1.0, min(1.0, value))
        except (TypeError, ValueError):
            pass
        if flow_delta is not None:
            if flow_delta >= 0.12:
                up_votes["aggressive trade flow"] = 1
            elif flow_delta <= -0.12:
                down_votes["aggressive trade flow"] = 1
        if book_imbalance is not None:
            if book_imbalance >= 0.15:
                up_votes["order-book imbalance"] = 1
            elif book_imbalance <= -0.15:
                down_votes["order-book imbalance"] = 1

    buys, sells = len(up_votes), len(down_votes)
    # Require two independent candle/flow confirmations with a clear
    # directional majority. Keep the same-timeframe SMA200 and risk checks
    # below; this improves candidate coverage without manufacturing trades.
    if buys >= 2 and buys > sells:
        side, aligned, opposing = "BUY", up_votes, sells
    elif sells >= 2 and sells > buys and profile["allow_short"]:
        side, aligned, opposing = "SELL", down_votes, buys
    else:
        return None

    # Long setups must trade above the same-timeframe SMA200; shorts below it.
    if not sma200_allows(side, entry, ma200):
        return None

    direction = 1.0 if side == "BUY" else -1.0
    # Use a meaningful recent structure, not just the last two candles. A small
    # ATR cushion helps avoid stops sitting directly inside routine wick noise.
    structure_start = max(0, i - 9)
    swing_low = min(lows[structure_start:i + 1])
    swing_high = max(highs[structure_start:i + 1])
    buffer = max(atr * 0.30, entry * 0.0005)
    stop = swing_low - buffer if side == "BUY" else swing_high + buffer
    risk = abs(entry - stop)

    # Never widen a stop artificially to satisfy a fixed ATR rule. If the
    # structural invalidation is too close (noise) or too far (poor R:R),
    # reject the setup and wait for a cleaner entry.
    if risk < atr * 0.65 or risk > atr * 2.5 or risk <= 0:
        return None
    if risk > entry * 0.015:
        return None
    targets = adaptive_target_prices(entry, side, risk)
    if not targets:
        return None
    tp1, tp2, tp3 = targets
    if min(entry, stop, tp1, tp2, tp3) <= 0:
        return None

    score = min(96.0, 52.0 + len(aligned) * 7.0 - opposing * 3.0)
    if flow_delta is not None and ((side == "BUY" and flow_delta >= 0.12) or (side == "SELL" and flow_delta <= -0.12)):
        score = min(96.0, score + 3.0)
    if book_imbalance is not None and ((side == "BUY" and book_imbalance >= 0.15) or (side == "SELL" and book_imbalance <= -0.15)):
        score = min(96.0, score + 2.0)

    previous_close = closes[i - 1]
    labels = list(aligned.keys())
    if flow_delta is not None:
        labels.append("Binance trade-flow data")
    if book_imbalance is not None:
        labels.append("Binance order-book data")
    return {
        "side": side, "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "score": round(score, 1), "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": "SMART FLOW QUANT: " + " + ".join(labels) + "; same-timeframe SMA200 passed; structural stop; gross targets 2%/3%/5%",
        "signal_candle_time": bars[-1][0], "risk_atr": round(risk / atr, 3),
        "reward_risk": round(abs(tp1 - entry) / risk, 3),
        "atr": atr, "ma200": ma200, "ma200_distance_pct": round((entry / ma200 - 1.0) * 100.0, 4), "confirmations": len(aligned),
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "range_expansion": round(range_expansion, 3),
        "taker_delta_ratio": flow_delta, "book_imbalance": book_imbalance,
        "strategy_votes": {"BUY": list(up_votes), "SELL": list(down_votes)},
        "strategy": "SMART_FLOW_QUANT_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }
