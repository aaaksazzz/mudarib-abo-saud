import pytest

import strategy_engine as engine


def candles(count=40):
    rows = []
    for index in range(count):
        close = 100 + index * 0.25
        rows.append({
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + index,
            "time": index * 900000,
        })
    return rows


def setup_engine(monkeypatch, states=None):
    states = states or {"4h": "STRONG_BUY", "1d": "BUY"}
    monkeypatch.setattr(
        engine, "assess_timeframe",
        lambda rows: {"state": states["4h"] if rows is history_4h else states["1d"], "score": 82},
    )
    history_4h = candles()
    history_daily = candles()
    history_entry = candles()
    calls = []

    def fetch(interval):
        calls.append(interval)
        return {"4h": history_4h, "1d": history_daily, "15m": history_entry}[interval]

    def liquidity(rows, price, side, market_kind, diagnostics=None):
        if diagnostics is not None:
            diagnostics["reason"] = "accepted"
        return {
            "entry": price, "stop_loss": price * 0.99,
            "tp1": price * 1.015, "tp2": price * 1.025, "tp3": price * 1.04,
            "risk_percent": 1.0, "quality_score": 80,
            "liquidity_event": "confirmed_sweep", "volume_ratio": 1.4,
            "flow_pressure": 0.6 if side == "BUY" else -0.6,
        }

    signal = engine.evaluate_candidate(
        market="spot",
        item={"symbol": "AAAUSDT", "price": 110.0, "fast_mover_score": 75, "volume": 2_000_000},
        market_direction="BUY",
        fetch_candles=fetch,
        liquidity_analyzer=liquidity,
        orderbook_analyzer=lambda side: {"status": "unavailable"},
    )
    return signal, calls


def test_canonical_pipeline_uses_4h_daily_then_15m(monkeypatch):
    signal, calls = setup_engine(monkeypatch)
    assert calls == ["4h", "1d", "15m"]
    assert signal["side"] == "BUY"
    assert signal["timeframe"] == "15m"
    assert signal["strategy_version"] == "hawk-quant-v2"
    assert signal["analysis_scope"] == "4h_daily_direction_15m_entry"


def test_conflicting_reference_timeframes_reject_before_entry(monkeypatch):
    states = {"4h": "STRONG_BUY", "1d": "STRONG_SELL"}
    monkeypatch.setattr(engine, "assess_timeframe", lambda rows: {
        "state": states["4h"] if rows is history_4h else states["1d"], "score": 85
    })
    history_4h, history_daily, history_entry = candles(), candles(), candles()
    calls = []

    def fetch(interval):
        calls.append(interval)
        return {"4h": history_4h, "1d": history_daily, "15m": history_entry}[interval]

    diagnostics = {}
    result = engine.evaluate_candidate(
        "spot", {"symbol": "AAAUSDT", "price": 110},
        "BUY", fetch, lambda *args, **kwargs: {}, lambda side: {},
        diagnostics=diagnostics,
    )
    assert result is None
    assert diagnostics["reason"] == "higher_timeframe_conflict"
    assert calls == ["4h", "1d"]


def test_market_direction_is_a_hard_gate(monkeypatch):
    history_4h, history_daily = candles(), candles()
    monkeypatch.setattr(engine, "assess_timeframe", lambda rows: {
        "state": "STRONG_BUY", "score": 85
    })
    calls = []

    def fetch(interval):
        calls.append(interval)
        return {"4h": history_4h, "1d": history_daily, "15m": candles()}[interval]

    diagnostics = {}
    result = engine.evaluate_candidate(
        "spot", {"symbol": "AAAUSDT", "price": 110},
        "SELL", fetch, lambda *args, **kwargs: {}, lambda side: {},
        diagnostics=diagnostics,
    )
    assert result is None
    assert diagnostics["reason"] == "market_direction_conflict"
    assert calls == ["4h", "1d"]


def test_missing_entry_liquidity_does_not_create_trade(monkeypatch):
    history_4h, history_daily, history_entry = candles(), candles(), candles()
    monkeypatch.setattr(engine, "assess_timeframe", lambda rows: {
        "state": "BUY", "score": 80
    })
    diagnostics = {}

    result = engine.evaluate_candidate(
        "spot", {"symbol": "AAAUSDT", "price": 110},
        "BUY",
        lambda interval: {"4h": history_4h, "1d": history_daily, "15m": history_entry}[interval],
        lambda *args, **kwargs: None,
        lambda side: {"status": "unavailable"},
        diagnostics=diagnostics,
    )
    assert result is None
    assert diagnostics["reason"] == "liquidity_setup_not_confirmed"


def test_neutral_market_and_unsupported_entry_timeframe_are_rejected(monkeypatch):
    history_4h, history_daily = candles(), candles()
    monkeypatch.setattr(engine, "assess_timeframe", lambda rows: {
        "state": "BUY", "score": 80
    })
    calls = []
    fetch = lambda interval: (calls.append(interval) or {"4h": history_4h, "1d": history_daily}[interval])
    diagnostics = {}
    result = engine.evaluate_candidate(
        "spot", {"symbol": "AAAUSDT", "price": 110},
        "NEUTRAL", fetch, lambda *args, **kwargs: {}, lambda side: {},
        diagnostics=diagnostics,
    )
    assert result is None
    assert diagnostics["reason"] == "market_direction_neutral"
    assert calls == ["4h", "1d"]

    diagnostics = {}
    result = engine.evaluate_candidate(
        "spot", {"symbol": "AAAUSDT", "price": 110},
        "BUY", fetch, lambda *args, **kwargs: {}, lambda side: {},
        diagnostics=diagnostics, timeframe="1h",
    )
    assert result is None
    assert diagnostics["reason"] == "unsupported_entry_timeframe"


def test_opportunity_ranking_uses_direction_aligned_15m_change():
    rows = [
        {"symbol": "A", "side": "BUY", "aligned_change_15m": 0.2, "quality_score": 90},
        {"symbol": "B", "side": "BUY", "aligned_change_15m": 1.4, "quality_score": 65},
        {"symbol": "C", "side": "BUY", "aligned_change_15m": -0.4, "quality_score": 95},
    ]
    assert [row["symbol"] for row in engine.rank_opportunities(rows, 3)] == ["B", "A", "C"]
