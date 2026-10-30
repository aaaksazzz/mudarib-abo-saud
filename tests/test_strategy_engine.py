import strategy_engine as engine


def _bullish_frame(candle):
    return {
        "direction": "صاعد", "rsi": 60.0, "adx": 30.0, "atr": 1.0,
        "ema20": 99.0, "ema50": 98.0, "ema200": None,
        "ema50_slope_pct": 0.3, "macd_hist": 0.5,
        "previous_macd_hist": 0.2, "relative_volume": 2.0,
        "resistance": 103.0, "support": 97.0,
        "change_pct": 1.2, "close_location": 0.8, "last": candle
    }


def test_professional_engine_builds_valid_long_trade(monkeypatch):
    candles = []
    price = 100.0
    for _ in range(90):
        open_price = price
        price += 0.04
        candles.append({
            "open": open_price, "high": price + 0.4, "low": open_price - 0.2,
            "close": price, "volume": 100.0
        })
    monkeypatch.setattr(engine, "_frame_analysis", lambda rows: _bullish_frame(rows[-1]))
    items, completed, message = engine.generate_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5_000_000}],
        10, lambda market, symbol, frame: candles
    )
    assert completed is True
    assert items
    trade = items[0]
    assert trade["method"] == "multi_factor_4h_1d_rank_15m_v3"
    assert trade["direction"] == "شراء"
    assert trade["timeframe_trends"]["4h"] == "صاعد"
    assert trade["timeframe_trends"]["1d"] == "صاعد"
    assert trade["interval"] == "15m"
    assert trade["score_type"] == "درجة جودة الأدلة من 100 وليست نسبة نجاح"
    levels = trade["levels"]
    assert levels["stop_loss"] < levels["entry"] < levels["tp1"] < levels["tp2"] < levels["tp3"]
    assert trade["risk_reward_tp3"] == 3.0
    assert trade["generated_by_ai"] is False


def test_professional_engine_rejects_bad_candles():
    assert engine._frame_analysis([]) is None
    assert engine._valid_candles([{"open": 10, "high": 9, "low": 8, "close": 10, "volume": 1}]) == []


def test_strategy_requires_rsi_macd_and_trend_confirmation():
    bullish = _bullish_frame({"open": 100, "high": 102, "low": 99, "close": 101, "volume": 10})
    assert engine._frame_confirms(bullish, "شراء") is True
    assert engine._frame_confirms(dict(bullish, macd_hist=-0.1), "شراء") is False
    assert engine._frame_confirms(dict(bullish, rsi=82), "شراء") is False
    assert engine._frame_confirms(dict(bullish, adx=10), "شراء") is False


def test_15m_direction_does_not_override_4h_and_daily(monkeypatch):
    candles = []
    price = 100.0
    for _ in range(90):
        open_price = price
        price += 0.03
        candles.append({"open": open_price, "high": price + 0.3, "low": open_price - 0.1,
                        "close": price, "volume": 100.0})
    calls = {"count": 0}

    def frame_analysis(rows):
        calls["count"] += 1
        frame = _bullish_frame(rows[-1])
        if calls["count"] == 1:
            frame["direction"] = "محايد"
        return frame

    monkeypatch.setattr(engine, "_frame_analysis", frame_analysis)
    items, _, _ = engine.generate_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5_000_000}],
        10, lambda market, symbol, frame: candles
    )
    assert items
    assert items[0]["direction"] == "شراء"
    assert items[0]["timeframe_trends"]["15m"] == "محايد"


def test_new_strategy_rejects_disagreement_between_4h_and_daily(monkeypatch):
    candles = []
    price = 100.0
    for _ in range(90):
        open_price = price
        price += 0.03
        candles.append({"open": open_price, "high": price + 0.3, "low": open_price - 0.1,
                        "close": price, "volume": 100.0})
    bullish = _bullish_frame(candles[-1])
    bearish = dict(bullish, direction="هابط", rsi=40.0, macd_hist=-0.5,
                   previous_macd_hist=-0.2, ema50_slope_pct=-0.3)
    calls = {"count": 0}

    def frame_analysis(rows):
        calls["count"] += 1
        return dict(bullish if calls["count"] < 3 else bearish, last=rows[-1])

    monkeypatch.setattr(engine, "_frame_analysis", frame_analysis)
    items, completed, _ = engine.generate_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5_000_000}],
        10, lambda market, symbol, frame: candles
    )
    assert completed is True
    assert items == []


def test_large_market_scans_rotate_through_the_universe(monkeypatch):
    seen = []
    monkeypatch.setattr(
        engine, "_analyze_symbol",
        lambda market, interval, row, candle_loader: seen.append(row["symbol"]) or None
    )
    rows = [
        {"symbol": f"COIN{i}USDT", "price": 1.0, "quote_volume": 1_000_000 - i}
        for i in range(24)
    ]
    engine._SCAN_CURSORS.pop(("rotation-test", "15m"), None)
    engine.generate_signals("rotation-test", "15m", rows, 20, lambda *args: [])
    first = set(seen)
    seen.clear()
    engine.generate_signals("rotation-test", "15m", rows, 20, lambda *args: [])
    second = set(seen)
    assert len(first) == 12
    assert len(second) == 12
    assert first.isdisjoint(second)
    assert first | second == {row["symbol"] for row in rows}



def test_selected_timeframe_controls_entry_expiry_and_ranking(monkeypatch):
    candles = []
    price = 100.0
    for _ in range(90):
        open_price = price
        price += 0.04
        candles.append({
            "open": open_price, "high": price + 0.4, "low": open_price - 0.2,
            "close": price, "volume": 100.0
        })
    monkeypatch.setattr(engine, "_frame_analysis", lambda rows: _bullish_frame(rows[-1]))
    items, completed, _ = engine.generate_signals(
        "spot", "1h", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5_000_000}],
        10, lambda market, symbol, frame: candles
    )
    assert completed is True
    assert items
    trade = items[0]
    assert trade["interval"] == "1h"
    assert trade["valid_for_seconds"] == 3600
    assert trade["change_interval_pct"] == trade["timeframe_change_pct"]["1h"]
    assert trade["timeframe_trends"]["4h"] == "صاعد"
    assert trade["timeframe_trends"]["1d"] == "صاعد"
    assert trade["levels"]["entry"] > 0
