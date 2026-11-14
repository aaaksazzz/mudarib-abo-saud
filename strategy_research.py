"""Research-only event backtester for qualifying candidate strategies.

No strategy is activated by this module. Signals are generated from completed bars;
entries execute no earlier than the next bar's open. Costs are charged on entry
and exit, and ambiguous stop/target bars are resolved stop-first.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    family: str
    description: str
    entry_rule: str
    exit_rule: str
    supported_markets: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    source: str = "STP-original"
    license: str = "Original"
    enabled: bool = False

    def fingerprint(self) -> str:
        payload = {
            "family": self.family,
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "markets": sorted(self.supported_markets),
            "timeframes": sorted(self.supported_timeframes),
        }
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_catalog(specs: Iterable[StrategySpec]) -> dict[str, Any]:
    rows = list(specs)
    ids: set[str] = set()
    fingerprints: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    invalid: list[str] = []
    for spec in rows:
        if not spec.strategy_id or spec.strategy_id in ids:
            invalid.append(spec.strategy_id or "<empty-id>")
        ids.add(spec.strategy_id)
        if not spec.name or not spec.family or not spec.entry_rule or not spec.exit_rule:
            invalid.append(spec.strategy_id)
        fp = spec.fingerprint()
        if fp in fingerprints:
            duplicates.append({"first": fingerprints[fp], "duplicate": spec.strategy_id})
        else:
            fingerprints[fp] = spec.strategy_id
    return {
        "count": len(rows),
        "unique_ids": len(ids),
        "unique_logic": len(fingerprints),
        "duplicates": duplicates,
        "invalid": sorted(set(invalid)),
        "ok": len(rows) == len(ids) == len(fingerprints) and not invalid,
    }


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _bar(row: Any) -> tuple[float, float, float]:
    if isinstance(row, dict):
        values = (row.get("open"), row.get("high"), row.get("low"))
    elif isinstance(row, (list, tuple)) and len(row) >= 5:
        values = (row[1], row[2], row[3])
    else:
        raise ValueError("Invalid OHLC bar")
    if not all(_finite(v) for v in values):
        raise ValueError("Non-finite OHLC value")
    op, high, low = map(float, values)
    if min(op, high, low) <= 0 or high < low or high < op or low > op:
        raise ValueError("Invalid OHLC geometry")
    return op, high, low


def _metrics(trade_returns: list[float], equity_curve: list[float]) -> dict[str, Any]:
    count = len(trade_returns)
    wins = [x for x in trade_returns if x > 0]
    losses = [x for x in trade_returns if x < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    peak = 1.0
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return {
        "trades": count,
        "net_return_pct": round((equity_curve[-1] - 1.0) * 100, 4) if equity_curve else 0.0,
        "win_rate_pct": round(len(wins) / count * 100, 2) if count else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else (999.0 if gross_win else 0.0),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "expectancy_pct": round(sum(trade_returns) / count * 100, 5) if count else 0.0,
    }


def backtest_signals(
    bars: list[Any],
    signals: Iterable[dict[str, Any]],
    *,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    """Test one-position-at-a-time signals; signal at i fills at open of i+1.

    Signal schema: {index: int, side: BUY|SELL, stop: float, target: float}.
    Position sizing is 1x notional. Fees and slippage are charged at both ends.
    """
    if len(bars) < 3:
        raise ValueError("At least three bars are required")
    if not _finite(fee_bps) or not _finite(slippage_bps) or min(fee_bps, slippage_bps) < 0:
        raise ValueError("Costs must be finite and non-negative")
    parsed = [_bar(row) for row in bars]
    by_index: dict[int, dict[str, Any]] = {}
    for signal in signals:
        try:
            idx = int(signal["index"])
            side = signal["side"]
            stop, target = float(signal["stop"]), float(signal["target"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if idx < 0 or idx >= len(parsed) - 1 or side not in ("BUY", "SELL"):
            continue
        if not all(math.isfinite(x) and x > 0 for x in (stop, target)):
            continue
        by_index[idx] = {"side": side, "stop": stop, "target": target}

    friction = (fee_bps + slippage_bps) / 10000.0
    equity = 1.0
    curve = [equity]
    returns: list[float] = []
    i = 0
    while i < len(parsed) - 1:
        signal = by_index.get(i)
        if not signal:
            i += 1
            continue
        side, stop, target = signal["side"], signal["stop"], signal["target"]
        raw_entry = parsed[i + 1][0]
        entry = raw_entry * (1 + friction if side == "BUY" else 1 - friction)
        valid = stop < entry < target if side == "BUY" else target < entry < stop
        if not valid:
            i += 1
            continue
        exit_price = parsed[-1][0]
        exit_index = len(parsed) - 1
        for j in range(i + 1, len(parsed)):
            _, high, low = parsed[j]
            stop_hit = low <= stop if side == "BUY" else high >= stop
            target_hit = high >= target if side == "BUY" else low <= target
            if stop_hit or target_hit:
                # Conservative handling: when both levels are touched, assume stop first.
                exit_price = stop if stop_hit else target
                exit_index = j
                break
        exit_price *= (1 - friction if side == "BUY" else 1 + friction)
        gross = (exit_price / entry - 1) if side == "BUY" else (entry / exit_price - 1)
        net = gross
        if not math.isfinite(net) or net <= -1:
            net = -0.999999
        equity *= 1 + net
        returns.append(net)
        curve.append(equity)
        i = exit_index + 1
    return {"metrics": _metrics(returns, curve), "trade_returns": returns, "equity_curve": curve}


def chronological_splits(bars: list[Any], train: float = 0.60, validation: float = 0.20):
    if len(bars) < 30 or not (0 < train < 1 and 0 < validation < 1 and train + validation < 1):
        raise ValueError("Insufficient bars or invalid split ratios")
    a, b = int(len(bars) * train), int(len(bars) * (train + validation))
    return {"train": bars[:a], "validation": bars[a:b], "test": bars[b:]}


def qualification_score(test_metrics: dict[str, Any], *, min_trades: int = 30) -> dict[str, Any]:
    """Conservative gate: out-of-sample evidence is mandatory; no win-rate-only ranking."""
    trades = int(test_metrics.get("trades", 0) or 0)
    net = float(test_metrics.get("net_return_pct", 0) or 0)
    pf = float(test_metrics.get("profit_factor", 0) or 0)
    dd = float(test_metrics.get("max_drawdown_pct", 100) or 100)
    eligible = trades >= min_trades and net > 0 and pf > 1.0 and dd < 30.0
    # Ranking favours positive return and profit factor, penalises drawdown.
    score = (net * min(pf, 3.0)) / max(dd, 1.0) if eligible else 0.0
    return {"eligible": eligible, "score": round(score, 6), "reason":
            "passed_out_of_sample_gate" if eligible else "insufficient_or_weak_out_of_sample_evidence"}
