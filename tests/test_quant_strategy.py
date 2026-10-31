import math
from quant_strategy import evaluate_setup, build_trade_plan


def trending_rows(direction=1, n=100):
    rows=[]
    price=100.0
    for i in range(n):
        price *= 1 + direction * (0.002 + (0.0003 if i % 3 == 0 else 0))
        rows.append({"open":price*0.998,"high":price*1.004,"low":price*0.996,
                     "close":price,"volume":1000 + (900 if i == n-1 else 0),"time":i})
    return rows


def test_independent_engine_detects_directional_trend():
    rows=trending_rows(1)
    result=evaluate_setup(rows, context_rows=[])
    assert result["accepted"]
    assert result["side"] == "BUY"
    assert 72 <= result["quality_score"] <= 100


def test_engine_can_detect_downtrend():
    result=evaluate_setup(trending_rows(-1), context_rows=[])
    assert result["accepted"]
    assert result["side"] == "SELL"


def test_context_is_advisory_not_a_veto():
    rows=trending_rows(1)
    opposing=trending_rows(-1)
    result=evaluate_setup(rows, context_rows=opposing)
    assert result["accepted"] is True or result["reason"] == "edge_or_quality_below_threshold"


def test_trade_plan_is_directionally_consistent():
    rows=trending_rows(1)
    plan=build_trade_plan(rows,"BUY")
    assert plan
    assert plan["stop_loss"] < plan["entry"] < plan["tp1"] < plan["tp2"] < plan["tp3"]
    assert math.isclose(plan["risk_percent"], (plan["entry"]-plan["stop_loss"])/plan["entry"]*100, rel_tol=1e-5)


def test_insufficient_history_rejected():
    assert evaluate_setup(trending_rows(1, 40))["reason"] == "insufficient_candles"
