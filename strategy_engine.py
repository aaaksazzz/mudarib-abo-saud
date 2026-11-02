"""Canonical HAWK QUANT strategy pipeline.

One decision path for every market with a verified OHLCV feed:
1) 4h and 1d direction must agree.
2) The market breadth gate must agree with that direction.
3) A completed 15m candle must confirm a liquidity event.
4) Public order-book imbalance is optional, soft context only.
5) Opportunities are ranked by direction-adjusted 15m change, then quality.

Scores describe rule confluence, never win probability or expected return.
"""
from __future__ import annotations

from typing import Callable, Optional

from timeframe_strategy import assess_timeframe

ENTRY_TIMEFRAME = "15m"
REFERENCE_TIMEFRAMES = ("4h", "1d")
MIN_CANDLES = 35
BUY_STATES = {"BUY", "STRONG_BUY"}
SELL_STATES = {"SELL", "STRONG_SELL"}
STATE_LABELS = {
    "BUY": "شراء",
    "STRONG_BUY": "شراء قوي",
    "SELL": "بيع",
    "STRONG_SELL": "بيع قوي",
}


def _reject(diagnostics, reason, **details):
    if diagnostics is not None:
        diagnostics["reason"] = reason
        diagnostics.update(details)
    return None


def evaluate_candidate(
    market: str,
    item: dict,
    market_direction: Optional[str],
    fetch_candles: Callable[[str], list],
    liquidity_analyzer: Callable,
    orderbook_analyzer: Callable,
    diagnostics: Optional[dict] = None,
    timeframe: str = ENTRY_TIMEFRAME,
):
    """Evaluate one asset through the single canonical strategy pipeline."""
    if not isinstance(item, dict) or not item.get("symbol"):
        return _reject(diagnostics, "invalid_candidate")
    if timeframe != ENTRY_TIMEFRAME:
        return _reject(diagnostics, "unsupported_entry_timeframe",
                       supported_timeframe=ENTRY_TIMEFRAME)

    try:
        reference = {}
        for interval in REFERENCE_TIMEFRAMES:
            rows = fetch_candles(interval)
            if not isinstance(rows, (list, tuple)) or len(rows) < MIN_CANDLES:
                return _reject(
                    diagnostics,
                    "insufficient_" + interval + "_candles",
                    **{"candles_" + interval: len(rows) if isinstance(rows, (list, tuple)) else 0,
                       "candles_required": MIN_CANDLES},
                )
            reference[interval] = assess_timeframe(rows)

        states = {interval: result.get("state") for interval, result in reference.items()}
        if all(state in BUY_STATES for state in states.values()):
            side = "BUY"
        elif all(state in SELL_STATES for state in states.values()):
            side = "SELL"
        else:
            return _reject(diagnostics, "higher_timeframe_conflict",
                           reference_directions=states)

        if market_direction not in ("BUY", "SELL"):
            return _reject(diagnostics, "market_direction_neutral",
                           market_direction=market_direction,
                           reference_directions=states)
        if side != market_direction:
            return _reject(diagnostics, "market_direction_conflict",
                           market_direction=market_direction,
                           candidate_direction=side,
                           reference_directions=states)

        reference_score = sum(
            float(reference[interval].get("score") or 0)
            for interval in REFERENCE_TIMEFRAMES
        ) / len(REFERENCE_TIMEFRAMES)
        if reference_score < 55:
            return _reject(diagnostics, "weak_higher_timeframe_direction",
                           reference_score=round(reference_score, 1),
                           reference_directions=states)

        entry_rows = fetch_candles(ENTRY_TIMEFRAME)
        if not isinstance(entry_rows, (list, tuple)) or len(entry_rows) < MIN_CANDLES:
            return _reject(
                diagnostics, "insufficient_15m_candles",
                candles_received=len(entry_rows) if isinstance(entry_rows, (list, tuple)) else 0,
                candles_required=MIN_CANDLES,
                reference_directions=states,
            )

        if diagnostics is not None:
            diagnostics["candles_ready"] = True
            diagnostics["reference_directions"] = states

        entry_price = float(item.get("price") or entry_rows[-1]["close"])
        if entry_price <= 0:
            return _reject(diagnostics, "invalid_entry_price")
        entry_diagnostics = {}
        levels = liquidity_analyzer(
            entry_rows, entry_price, side,
            market_kind=market, diagnostics=entry_diagnostics,
        )
        if not levels:
            return _reject(
                diagnostics,
                entry_diagnostics.get("reason", "liquidity_setup_not_confirmed"),
                reference_directions=states,
            )

        previous_close = float(entry_rows[-2]["close"])
        latest_close = float(entry_rows[-1]["close"])
        if previous_close <= 0:
            return _reject(diagnostics, "invalid_15m_close")
        change_15m = (latest_close / previous_close - 1) * 100

        flow = orderbook_analyzer(side) or {"status": "unavailable"}
        flow_adjustment = (
            4 if flow.get("status") == "supportive"
            else -8 if flow.get("status") == "opposing"
            else 0
        )
        liquidity_score = float(levels.get("quality_score") or 0)
        quality_score = max(0.0, min(
            95.0, liquidity_score * 0.60 + reference_score * 0.40 + flow_adjustment
        ))
        fast_score = float(item.get("fast_mover_score") or 0)
        # Signed 15m movement is direction-aware; an adverse move never ranks first.
        aligned_change = change_15m if side == "BUY" else -change_15m
        ranking_score = quality_score * 0.65 + fast_score * 0.35

        signal = {
            **levels,
            "side": side,
            "price": entry_price,
            "symbol": str(item["symbol"]),
            "change24h": item.get("change24h", 0),
            "change_timeframe": round(change_15m, 4),
            "aligned_change_15m": round(aligned_change, 4),
            "volume": item.get("volume", 0),
            "fast_mover_score": fast_score,
            "fast_mover_rank": item.get("fast_mover_rank"),
            "timeframe": ENTRY_TIMEFRAME,
            "signal_candle_time": int(entry_rows[-1].get("time") or 0),
            "strategy": "HAWK QUANT PRO · 4h + daily · 15m liquidity entry",
            "strategy_version": "hawk-quant-v2",
            "signal_state": side,
            "signal_state_ar": STATE_LABELS[side],
            "quality_score": round(quality_score, 1),
            "ranking_score": round(ranking_score, 1),
            "entry_analysis": {
                "direction_score_4h": float(reference["4h"].get("score") or 0),
                "direction_score_daily": float(reference["1d"].get("score") or 0),
                "liquidity_event": levels.get("liquidity_event"),
                "volume_ratio": levels.get("volume_ratio"),
                "flow_pressure": levels.get("flow_pressure"),
                "risk_percent": levels.get("risk_percent"),
                "change_15m": round(change_15m, 4),
            },
            "reference_analysis": reference,
            "institutional_flow": flow,
            "orderbook_context": flow.get("status", "unavailable"),
            "orderbook_adjustment": flow_adjustment,
            "analysis_scope": "4h_daily_direction_15m_entry",
            "quality_label": "درجة توافق الشروط من 100 وليست احتمال نجاح",
            "analysis_note": (
                "اتجاه 4 ساعات واليومي متفقان؛ اتجاه السوق العام بوابة توافق؛ "
                "الدخول من حدث سيولة مؤكد على شمعة 15 دقيقة مكتملة."
            ),
        }
        if diagnostics is not None:
            diagnostics.update({
                "reason": "accepted",
                "reference_directions": states,
                "reference_score": round(reference_score, 1),
                "entry_timeframe": ENTRY_TIMEFRAME,
                "change_15m": round(change_15m, 4),
            })
        return signal
    except (TypeError, ValueError, KeyError, IndexError, ZeroDivisionError, OverflowError):
        return _reject(diagnostics, "analysis_error")


def rank_opportunities(signals, limit=3):
    """Rank only same-direction candidates by aligned 15m move, then quality."""
    rows = [dict(row) for row in (signals or []) if isinstance(row, dict)]
    rows.sort(key=lambda row: (
        float(row.get("aligned_change_15m") or 0),
        float(row.get("quality_score") or 0),
        float(row.get("ranking_score") or 0),
    ), reverse=True)
    return rows[:max(0, int(limit))]
