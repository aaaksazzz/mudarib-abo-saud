import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_ranking import rank_market_assets


def test_fast_movers_rank_high_momentum_range_and_liquidity_first():
    rows = [
        {"symbol": "SLOW", "change24h": 1, "range24h": 2, "volume": 2_000_000},
        {"symbol": "FAST", "change24h": 18, "range24h": 24, "volume": 20_000_000},
        {"symbol": "MID", "change24h": 7, "range24h": 10, "volume": 8_000_000},
    ]
    ranked = rank_market_assets(rows)
    assert [row["symbol"] for row in ranked] == ["FAST", "MID", "SLOW"]
    assert ranked[0]["fast_mover_rank"] == 1
    assert ranked[0]["fast_mover_score"] > ranked[-1]["fast_mover_score"]


def test_missing_range_and_zero_volume_are_safe():
    ranked = rank_market_assets([
        {"symbol": "A", "change24h": 2},
        {"symbol": "B", "change24h": 9},
    ])
    assert ranked[0]["symbol"] == "B"
    assert all(0 <= row["fast_mover_score"] <= 100 for row in ranked)


def test_tied_universe_gets_finite_scores():
    ranked = rank_market_assets([
        {"symbol": "A", "change24h": 0, "range24h": 0, "volume": 0},
        {"symbol": "B", "change24h": 0, "range24h": 0, "volume": 0},
    ])
    assert len(ranked) == 2
    assert all(row["fast_mover_score"] == 50 for row in ranked)
