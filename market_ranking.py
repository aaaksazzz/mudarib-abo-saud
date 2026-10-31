"""Fast-mover ranking for market universes.

The score is a relative screening priority, not a prediction or probability.
"""
from math import isfinite, log1p


def _number(row, key):
    try:
        value = float(row.get(key, 0) or 0)
        return value if isfinite(value) and value >= 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _percentile(values):
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.5] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        percentile = 0.5 if len(values) == 1 else ((index + end - 1) / 2) / (len(values) - 1)
        for position in range(index, end):
            ranks[ordered[position][0]] = percentile
        index = end
    return ranks


def rank_market_assets(assets):
    """Rank fast movers by absolute momentum, daily range, and liquidity."""
    rows = [dict(row) for row in (assets or []) if isinstance(row, dict)]
    if not rows:
        return []
    features = {
        "momentum": [abs(_number(row, "change24h")) for row in rows],
        "range": [_number(row, "range24h") for row in rows],
        "liquidity": [log1p(_number(row, "volume")) for row in rows],
    }
    weights = {"momentum": 0.50, "range": 0.30, "liquidity": 0.20}
    ranks, active = {}, {}
    for name, values in features.items():
        if len(set(values)) > 1:
            ranks[name] = _percentile(values)
            active[name] = weights[name]
    if not active:
        ranks["momentum"] = _percentile(features["momentum"])
        active["momentum"] = 1.0
    total = sum(active.values())
    for i, row in enumerate(rows):
        row["fast_mover_score"] = round(
            sum(ranks[name][i] * weight for name, weight in active.items()) / total * 100, 1
        )
    rows.sort(key=lambda row: (
        row["fast_mover_score"], abs(_number(row, "change24h")),
        _number(row, "volume"), str(row.get("symbol", "")),
    ), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["fast_mover_rank"] = rank
    return rows
