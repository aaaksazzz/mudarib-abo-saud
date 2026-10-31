import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hawk_quant_engine import assess_timeframe_alignment


def trend_rows(direction, count=24):
    rows = []
    for index in range(count):
        if direction == "BUY":
            close = 100 + index * 0.8
        else:
            close = 120 - index * 0.8
        rows.append({
            "open": close - 0.2 if direction == "BUY" else close + 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        })
    return rows


def test_hawk_quant_requires_all_higher_timeframes_to_align():
    histories = {key: trend_rows("BUY") for key in ("1h", "4h", "1d")}
    result = assess_timeframe_alignment(histories, "BUY")
    assert result["confirmed"] is True
    assert result["score"] == 100
    assert result["states"] == {"1h": "BUY", "4h": "BUY", "1d": "BUY"}


def test_hawk_quant_rejects_mixed_timeframe_direction():
    histories = {
        "1h": trend_rows("BUY"),
        "4h": trend_rows("BUY"),
        "1d": trend_rows("SELL"),
    }
    result = assess_timeframe_alignment(histories, "BUY")
    assert result["confirmed"] is False
    assert result["states"]["1d"] == "SELL"


def test_hawk_quant_rejects_missing_higher_timeframe_history():
    result = assess_timeframe_alignment({"1h": trend_rows("BUY")}, "BUY")
    assert result["confirmed"] is False
    assert result["states"]["4h"] == "INSUFFICIENT"


def test_hawk_quant_rejects_invalid_side():
    result = assess_timeframe_alignment({}, "NEUTRAL")
    assert result["confirmed"] is False

 
def test_alignment_allows_neutral_daily_if_hourly_and_four_hour_agree():
    from hawk_quant_engine import assess_timeframe_alignment
    rising = []
    for i in range(12):
        base = 100 + i * 0.4
        rising.append({"open": base, "high": base + 0.6,
                       "low": base - 0.1, "close": base + 0.4})
    neutral = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(12)]
    result = assess_timeframe_alignment({"1h": rising, "4h": rising, "1d": neutral}, "BUY")
    assert result["confirmed"] is True
    assert result["score"] == 200 / 3
