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




def test_independent_method_test_is_recorded_and_closed_separately(tmp_path, monkeypatch):
    import json
    import time

    monkeypatch.setattr(app, "METHOD_RESULTS_PATH", tmp_path / "method-results.json")
    monkeypatch.setattr(app, "METHOD_EVALUATIONS_PATH", tmp_path / "method-evaluations.json")
    monkeypatch.setattr(app, "METHOD_RULES", {"Test Method": "test_method"})
    monkeypatch.setattr(app, "METHOD_AUXILIARY_DATA_REQUIRED", {})
    monkeypatch.setattr(app, "METHOD_RISK_ONLY_KEYS", set())

    def fake_method_signal(candles, ticker, method_key):
        if method_key != "test_method":
            return None
        return {
            **ticker, "side": "BUY", "method": method_key, "score": 70,
            "entry": 100.0, "stop": 99.0, "tp1": 102.0,
            "tp2": 102.5, "tp3": 103.0,
        }

    monkeypatch.setattr(app, "method_signal", fake_method_signal)
    ticker = {"symbol": "TESTUSDT", "price": 100.0, "change_pct": 0.0, "quote_volume": 2_000_000}
    candles = synthetic_candles()
    app.record_method_candidates("spot", ticker, "15m", candles)
    app.record_method_candidates("spot", ticker, "15m", candles)
    records = json.loads((tmp_path / "method-results.json").read_text(encoding="utf-8"))
    eval_data = json.loads((tmp_path / "method-evaluations.json").read_text(encoding="utf-8"))
    method_stats = eval_data["stats"]["spot|15m|test_method"]
    assert method_stats["evaluations"] == 1
    assert method_stats["setups"] == 1
    assert len(records) == 1
    assert records[0]["record_type"] == "method_test"
    assert records[0]["method_key"] == "test_method"
    assert records[0]["result"] == "مفتوحة"

    now = int(time.time())
    closed = app.refresh_method_test_results("spot", "15m", {"TESTUSDT": 102.0}, now)
    assert closed[0]["result"] == "TP1"
    assert closed[0]["pnl_pct"] == 1.8

    response = client.get("/api/method-performance?market=spot&interval=15m")
    assert response.status_code == 200
    ranked = response.json()["items"]
    assert len(ranked) == 1
    assert ranked[0]["method_key"] == "test_method"
    assert ranked[0]["closed"] == 1
    assert ranked[0]["sample_ready"] is False


def test_method_performance_keeps_small_samples_provisional(tmp_path, monkeypatch):
    import time
    import app as app_module

    path = tmp_path / "method-results.json"
    monkeypatch.setattr(app_module, "METHOD_RESULTS_PATH", path)
    monkeypatch.setattr(app_module, "METHOD_EVALUATIONS_PATH", tmp_path / "method-evaluations.json")
    now = int(time.time())
    app_module.write_json_file(path, [
        {"record_type": "method_test", "method_key": "small", "method": "Small Sample",
         "market": "spot", "interval": "1h", "side": "BUY", "result": "TP1",
         "pnl_pct": 1.0, "created_at": now - i}
        for i in range(2)
    ])
    response = client.get("/api/method-performance?market=spot&interval=1h")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["closed"] == 2
    assert item["sample_ready"] is False
    assert "مؤقت" in item["ranking_status"]
