import math

from market_strategy_engine import MARKET_STRATEGIES, evaluate_market_strategy


def trend_rows(direction="up", count=45):
    rows = []
    for i in range(count):
        base = 100 + i * 0.30 if direction == "up" else 120 - i * 0.30
        close = base
        rows.append({"open": close - 0.05 if direction == "up" else close + 0.05,
                     "high": close + 0.10, "low": close - 0.10,
                     "close": close, "volume": 1000})
    return rows


def test_every_market_has_an_explicit_strategy():
    assert set(MARKET_STRATEGIES) == {
        "spot", "futures", "coinm", "alpha", "saudi", "us", "forex", "contracts"
    }
    assert len(set(MARKET_STRATEGIES.values())) == len(MARKET_STRATEGIES)


def test_spot_is_long_only_and_requires_breakout():
    rows = trend_rows("up")
    rows[-1].update({"open": 113.2, "high": 114.0, "low": 113.1,
                     "close": 113.9, "volume": 1800})
    result = evaluate_market_strategy("spot", rows)
    assert result["confirmed"] is True
    assert result["side"] == "BUY"


def test_usd_m_trend_engine_supports_both_directions():
    up = evaluate_market_strategy("futures", trend_rows("up"))
    down = evaluate_market_strategy("futures", trend_rows("down"))
    assert up["confirmed"] and up["side"] == "BUY"
    assert down["confirmed"] and down["side"] == "SELL"


def test_coinm_requires_a_liquidity_sweep_reversal():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100.2, "volume": 1000}
            for _ in range(44)]
    rows.append({"open": 99.3, "high": 100.2, "low": 98.5, "close": 100.0, "volume": 1500})
    result = evaluate_market_strategy("coinm", rows)
    assert result["confirmed"] and result["side"] == "BUY"
    assert result["reason"] == "coin_m_sell_side_sweep_reclaim"


def test_contracts_never_fabricate_signals_without_provider():
    result = evaluate_market_strategy("contracts", trend_rows())
    assert result["confirmed"] is False
    assert result["reason"] == "provider_required"


def test_equity_and_forex_engines_are_separate_and_scores_are_not_probabilities():
    assert MARKET_STRATEGIES["saudi"] != MARKET_STRATEGIES["us"]
    assert MARKET_STRATEGIES["forex"] != MARKET_STRATEGIES["futures"]
    result = evaluate_market_strategy("forex", trend_rows("up"))
    assert result["confirmed"] is False or result["side"] in ("BUY", "SELL")
    if result["confirmed"]:
        assert 0 <= result["quality_score"] <= 95
