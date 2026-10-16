import math

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def synthetic_candles(count=260):
    """Deterministic, valid OHLCV candles for regression/contract testing only."""
    candles = []
    previous = 100.0
    for i in range(count):
        drift = 0.08 if (i // 35) % 2 == 0 else -0.025
        wave = math.sin(i / 3.0) * 0.55
        close = max(10.0, previous + drift + wave)
        open_price = previous
        high = max(open_price, close) + 0.35
        low = min(open_price, close) - 0.35
        candles.append({
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0 + (i % 11) * 120.0,
            "time": 1_700_000_000 + i * 900,
        })
        previous = close
    return candles


def test_method_catalog_covers_every_registered_method_and_discloses_limits():
    response = client.get("/api/methods/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["count"] == len(app.METHOD_RULES) == 200
    assert {item["name"] for item in payload["items"]} == set(app.METHOD_RULES)
    assert all(item["score_is_probability"] is False for item in payload["items"])
    assert payload["counts"]["needs_auxiliary_data"] == len(app.METHOD_AUXILIARY_DATA_REQUIRED)
    risk = next(item for item in payload["items"] if item["key"] == "risk_management")
    assert risk["signal_capable"] is False
    assert risk["status"] == "risk_tool"


def test_all_registered_methods_are_safe_on_valid_ohlcv_input():
    candles = synthetic_candles()
    ticker = {
        "symbol": "TESTUSDT",
        "price": candles[-1]["close"],
        "change_pct": 0.5,
        "quote_volume": 2_000_000.0,
    }
    assert set(app.METHOD_RULES.values()) <= {
        item["key"] for item in client.get("/api/methods/catalog").json()["items"]
    }

    for method_name, method_key in app.METHOD_RULES.items():
        signal = app.method_signal(candles, ticker, method_key)
        if method_key in app.METHOD_AUXILIARY_DATA_REQUIRED or method_key in app.METHOD_RISK_ONLY_KEYS:
            assert signal is None, f"{method_name} must not fabricate missing data or an entry signal"
        if signal is None:
            continue

        assert signal["method"] == method_key, method_name
        assert signal["side"] in {"BUY", "SELL"}, method_name
        entry, stop = signal["entry"], signal["stop"]
        targets = [signal["tp1"], signal["tp2"], signal["tp3"]]
        assert all(math.isfinite(float(value)) and float(value) > 0 for value in [entry, stop, *targets]), method_name
        if signal["side"] == "BUY":
            assert stop < entry < targets[0] < targets[1] < targets[2], method_name
        else:
            assert targets[2] < targets[1] < targets[0] < entry < stop, method_name
        assert signal["score_type"] == "rule_evidence_not_probability", method_name
        assert signal["score_label"] == "قوة الشواهد وليست احتمال ربح", method_name


def test_method_signal_rejects_short_or_malformed_candle_history():
    ticker = {"symbol": "TESTUSDT", "price": 100.0, "change_pct": 0.0, "quote_volume": 1_000_000.0}
    assert app.method_signal(synthetic_candles(20), ticker, "price_action") is None

    malformed = synthetic_candles()
    malformed[-1]["low"] = malformed[-1]["high"] + 1
    assert app.method_signal(malformed, ticker, "price_action") is None


def test_data_dependent_methods_are_explicitly_blocked_without_required_inputs():
    candles = synthetic_candles()
    ticker = {"symbol": "TESTUSDT", "price": candles[-1]["close"], "change_pct": 0.0, "quote_volume": 1_000_000.0}
    for key in app.METHOD_AUXILIARY_DATA_REQUIRED:
        assert app.method_signal(candles, ticker, key) is None, key

def test_candle_data_fetches_extra_bar_before_filtering_open_candle(monkeypatch):
    import time

    now_ms = int(time.time() * 1000)
    raw = []
    for i in range(250):
        close_time = now_ms - (250 - i) * 60_000
        if i == 249:
            close_time = now_ms + 60_000  # exchange's currently open candle
        raw.append([
            1_700_000_000_000 + i * 60_000, "100", "101", "99", "100.5",
            "1000", close_time, "100000", 10, "500", "50000", "0"
        ])

    requested = {}
    def fake_fetch_json(url, timeout=8):
        requested["url"] = url
        return raw

    monkeypatch.setattr(app, "fetch_json", fake_fetch_json)
    candles = app.candle_data("spot", "TESTUSDT", "15m")

    assert "limit=250" in requested["url"]
    assert len(candles) == 249
    assert len(candles) >= 220

