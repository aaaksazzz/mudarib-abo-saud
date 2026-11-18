"""AS Quant Intelligence v1 - independent, research-only multi-method candidate engine.

This module does not replace the production signal engine. Scores are heuristic quality
scores, never probabilities. A candidate must pass separate out-of-sample qualification
before any production activation.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev

FINGERPRINT = "AS-QUANT-INTELLIGENCE-V1-20261118"
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")

# Coverage registry: research status is explicit; no claim that unavailable feeds exist.
METHOD_CATALOG = {
    "trend_following": {"family": "trend", "required": ["OHLCV"], "status": "implemented_research"},
    "momentum_breakout": {"family": "momentum", "required": ["OHLCV"], "status": "implemented_research"},
    "mean_reversion": {"family": "mean_reversion", "required": ["OHLCV"], "status": "implemented_research"},
    "range_structure": {"family": "price_action", "required": ["OHLCV"], "status": "implemented_research"},
    "volume_confirmation": {"family": "volume", "required": ["OHLCV"], "status": "feature_confirmation"},
    "smart_money_ict": {"family": "liquidity", "required": ["OHLCV"], "status": "research_adapter_required"},
    "order_flow": {"family": "microstructure", "required": ["trades", "order_book"], "status": "data_feed_required"},
    "options_greeks": {"family": "derivatives", "required": ["options_chain"], "status": "data_feed_required"},
    "fundamental_macro": {"family": "fundamental_macro", "required": ["filings", "economic_calendar"], "status": "source_adapter_required"},
    "sentiment_news": {"family": "sentiment", "required": ["timestamped_news_or_sentiment"], "status": "source_adapter_required"},
    "portfolio_risk": {"family": "risk", "required": ["portfolio_positions"], "status": "portfolio_input_required"},
}

def _parse(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) < 61:
        return []
    out = []
    # Ignore the final row: it may still be forming.
    for row in rows[:-1]:
        try:
            if isinstance(row, dict):
                o,h,l,c,v = (float(row[k]) for k in ("open","high","low","close","volume"))
                t = row.get("time")
            else:
                t,o,h,l,c,v = row[:6]
                o,h,l,c,v = map(float, (o,h,l,c,v))
            if not all(math.isfinite(x) for x in (o,h,l,c,v)):
                continue
            if min(o,h,l,c) <= 0 or v < 0 or h < max(o,c) or l > min(o,c) or h < l:
                continue
            out.append({"time": t, "open":o, "high":h, "low":l, "close":c, "volume":v})
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
    return out

def _ema(values, period):
    alpha = 2.0 / (period + 1)
    value = values[0]
    for item in values[1:]:
        value = alpha * item + (1-alpha) * value
    return value

def _atr(bars, period=14):
    sample = bars[-(period+1):]
    tr = []
    for i, b in enumerate(sample):
        prev = sample[i-1]["close"] if i else b["close"]
        tr.append(max(b["high"]-b["low"], abs(b["high"]-prev), abs(b["low"]-prev)))
    return mean(tr) if tr else 0.0

def classify_regime(bars):
    if len(bars) < 55:
        return "unknown"
    closes = [b["close"] for b in bars]
    fast, slow = _ema(closes[-50:], 20), _ema(closes[-50:], 50)
    atr_pct = _atr(bars) / closes[-1]
    returns = [closes[i]/closes[i-1]-1 for i in range(max(1,len(closes)-20),len(closes))]
    vol = pstdev(returns) if len(returns)>1 else 0.0
    if atr_pct > 0.035 or vol > 0.025:
        return "high_volatility"
    if abs(fast/slow-1) > 0.008:
        return "trend"
    return "range"

def _candidate(market, symbol, timeframe, side, entry, stop, setup, regime, score, reasons):
    if market == "spot" and side != "BUY":
        return None
    risk = entry-stop if side == "BUY" else stop-entry
    if not math.isfinite(risk) or risk <= 0 or risk/entry > 0.08:
        return None
    sign = 1 if side == "BUY" else -1
    return {
        "market": market, "symbol": str(symbol), "timeframe": timeframe, "side": side,
        "entry": entry, "stop": stop, "tp1": entry+sign*risk,
        "tp2": entry+sign*risk*2, "tp3": entry+sign*risk*3,
        "risk_pct": round(risk/entry*100, 4), "reward_risk": 3.0,
        "strategy_id": setup, "regime": regime,
        "quality_score": round(min(100.0, max(0.0, score)), 1),
        "score_type": "heuristic_not_probability", "reasons": reasons,
        "fingerprint": FINGERPRINT, "status": "research_candidate",
    }

def analyze_candidates(market, symbol, rows, timeframe="15m"):
    """Return independent strategy candidates; no arbitrary voting or forced HTF alignment."""
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return {"ok": False, "reason": "unsupported_market_or_timeframe", "candidates": []}
    bars = _parse(rows)
    if len(bars) < 60:
        return {"ok": False, "reason": "insufficient_completed_bars", "candidates": []}
    closes = [b["close"] for b in bars]
    last, atr = bars[-1], _atr(bars)
    if atr <= 0 or not math.isfinite(atr):
        return {"ok": False, "reason": "invalid_volatility", "candidates": []}
    regime = classify_regime(bars)
    candidates = []

    # 1) Trend following / pullback: EMA alignment plus reclaim of fast average.
    ema20, ema50 = _ema(closes[-100:],20), _ema(closes[-100:],50)
    if ema20 > ema50 and last["close"] > ema20 and last["close"] >= last["open"]:
        c = _candidate(market,symbol,timeframe,"BUY",last["close"],min(last["low"],ema20)-0.2*atr,
            "trend_pullback",regime,68,["EMA20_ABOVE_EMA50","CLOSE_ABOVE_EMA20","BULLISH_CLOSED_CANDLE"])
        if c: candidates.append(c)
    if ema20 < ema50 and last["close"] < ema20 and last["close"] <= last["open"]:
        c = _candidate(market,symbol,timeframe,"SELL",last["close"],max(last["high"],ema20)+0.2*atr,
            "trend_pullback",regime,68,["EMA20_BELOW_EMA50","CLOSE_BELOW_EMA20","BEARISH_CLOSED_CANDLE"])
        if c: candidates.append(c)

    # 2) Momentum breakout: close beyond prior 20-bar range with relative volume.
    prior = bars[-21:-1]
    prior_high, prior_low = max(b["high"] for b in prior), min(b["low"] for b in prior)
    avg_volume = mean(b["volume"] for b in prior)
    volume_ok = avg_volume > 0 and last["volume"] >= 1.2*avg_volume
    if last["close"] > prior_high and volume_ok:
        c = _candidate(market,symbol,timeframe,"BUY",last["close"],min(last["low"],prior_high-0.5*atr),
            "momentum_breakout",regime,72,["CLOSE_ABOVE_20_BAR_HIGH","RELATIVE_VOLUME_1_2X"])
        if c: candidates.append(c)
    if last["close"] < prior_low and volume_ok:
        c = _candidate(market,symbol,timeframe,"SELL",last["close"],max(last["high"],prior_low+0.5*atr),
            "momentum_breakout",regime,72,["CLOSE_BELOW_20_BAR_LOW","RELATIVE_VOLUME_1_2X"])
        if c: candidates.append(c)

    # 3) Mean reversion: two-standard-deviation stretch and reversal close.
    sample = closes[-20:]
    sd = pstdev(sample)
    if sd > 0:
        mid, upper, lower = mean(sample), mean(sample)+2*sd, mean(sample)-2*sd
        if last["low"] < lower and last["close"] > lower and last["close"] > last["open"]:
            c = _candidate(market,symbol,timeframe,"BUY",last["close"],last["low"]-0.2*atr,
                "mean_reversion",regime,64,["LOWER_2SD_RECLAIM","BULLISH_REVERSAL_CLOSE"])
            if c: candidates.append(c)
        if last["high"] > upper and last["close"] < upper and last["close"] < last["open"]:
            c = _candidate(market,symbol,timeframe,"SELL",last["close"],last["high"]+0.2*atr,
                "mean_reversion",regime,64,["UPPER_2SD_REJECT","BEARISH_REVERSAL_CLOSE"])
            if c: candidates.append(c)

    # 4) Range structure: rejection at recent range boundary, deliberately independent.
    if regime == "range":
        width = prior_high-prior_low
        if width > 0 and last["low"] <= prior_low+0.08*width and last["close"] > last["open"]:
            c = _candidate(market,symbol,timeframe,"BUY",last["close"],last["low"]-0.2*atr,
                "range_structure",regime,61,["RANGE_LOW_REJECTION"])
            if c: candidates.append(c)
        if width > 0 and last["high"] >= prior_high-0.08*width and last["close"] < last["open"]:
            c = _candidate(market,symbol,timeframe,"SELL",last["close"],last["high"]+0.2*atr,
                "range_structure",regime,61,["RANGE_HIGH_REJECTION"])
            if c: candidates.append(c)

    # Preserve independent candidates. Conflict is surfaced, never silently blended.
    sides = {c["side"] for c in candidates}
    return {
        "ok": True, "fingerprint": FINGERPRINT, "market": market, "symbol": str(symbol),
        "timeframe": timeframe, "regime": regime, "candidates": candidates,
        "conflict": len(sides) > 1,
        "decision": "research_only_no_production_activation",
        "catalog": METHOD_CATALOG,
    }
