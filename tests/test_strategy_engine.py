import strategy_engine as engine


def test_professional_engine_builds_valid_long_trade(monkeypatch):
    candles = []
    price = 100.0
    for i in range(90):
        open_price = price
        price += 0.04
        candles.append({
            "open": open_price, "high": price + 0.4, "low": open_price - 0.2,
            "close": price, "volume": 100.0
        })
    fake = {
        "direction": "صاعد", "rsi": 60.0, "adx": 30.0, "atr": 1.0,
        "ema20": 99.0, "ema50": 98.0, "ema200": None,
        "macd_hist": 0.5, "previous_macd_hist": 0.2,
        "relative_volume": 2.0, "resistance": 103.0,
        "support": 97.0, "change_pct": 1.2, "last": candles[-1]
    }
    monkeypatch.setattr(engine, "_frame_analysis", lambda rows: dict(fake, last=rows[-1]))
    items, completed, message = engine.generate_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5_000_000}],
        10, lambda market, symbol, frame: candles
    )
    assert completed is True
    assert items
    trade = items[0]
    assert trade["method"] == "trend_4h_1d_rank_15m_v2"
    assert trade["direction"] == "شراء"
    assert trade["timeframe_trends"]["4h"] == "صاعد"
    assert trade["timeframe_trends"]["1d"] == "صاعد"
    assert trade["interval"] == "15m"
    levels = trade["levels"]
    assert levels["stop_loss"] < levels["entry"] < levels["tp1"] < levels["tp2"] < levels["tp3"]
    assert trade["risk_reward_tp3"] == 3.0
    assert trade["generated_by_ai"] is False


def test_professional_engine_rejects_bad_candles():
    assert engine._frame_analysis([]) is None
    assert engine._valid_candles([{"open": 10, "high": 9, "low": 8, "close": 10, "volume": 1}]) == []

def test_new_strategy_rejects_disagreement_between_4h_and_daily(monkeypatch):
    candles = []
    price = 100.0
    for _ in range(90):
        op = price
        price += 0.03
        candles.append({"open": op, "high": price + 0.3, "low": op - 0.1,
                        "close": price, "volume": 100.0})
    bullish = {"direction": "صاعد", "rsi": 60.0, "adx": 30.0, "atr": 0.5,
               "ema20": 100, "ema50": 99, "ema200": 98, "macd_hist": .5,
               "previous_macd_hist": .2, "relative_volume": 1.5,
               "resistance": 110, "support": 90, "change_pct": 1.5, "last": candles[-1]}
    bearish = dict(bullish, direction="هابط", change_pct=-1.5)
    calls = {"n": 0}
    def frame_analysis(rows):
        calls["n"] += 1
        return dict(bullish if calls["n"] < 3 else bearish, last=rows[-1])
    monkeypatch.setattr(engine, "_frame_analysis", frame_analysis)
    def loader(market, symbol, frame):
        return candles
    items, completed, _ = engine.generate_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": price, "quote_volume": 5000000}],
        10, loader
    )
    assert completed is True
    assert items == []
