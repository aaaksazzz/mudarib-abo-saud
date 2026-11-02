import time

import external_market_data as providers


def test_aggregate_builds_closed_ohlcv_bars():
    width = 4 * 60 * 60 * 1000
    start = (int(time.time() * 1000) // width - 10) * width
    rows = [
        {"time": start + i * 60 * 60 * 1000, "open": 10 + i, "high": 12 + i,
         "low": 9 + i, "close": 11 + i, "volume": 100 + i}
        for i in range(4)
    ]
    result = providers._aggregate(rows, width)
    assert len(result) == 1
    assert result[0]["open"] == 10
    assert result[0]["close"] == 14
    assert result[0]["high"] == 15
    assert result[0]["low"] == 9
    assert result[0]["volume"] == 406


def test_sahmk_symbols_keeps_only_active_tasi_equities(monkeypatch):
    monkeypatch.setattr(providers, "_sahmk_headers", lambda: {})
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: {
        "results": [
            {"symbol": "2222", "status": "active", "security_type": "Equity", "market": "TASI"},
            {"symbol": "9999", "status": "active", "security_type": "ETF", "market": "TASI"},
            {"symbol": "1234", "status": "inactive", "security_type": "Equity", "market": "TASI"},
            {"symbol": "4321", "status": "active", "security_type": "Equity", "market": "NOMU"},
        ],
        "total": 4,
    })
    assert providers.sahmk_symbols() == ["2222"]


def test_sahmk_tickers_does_not_apply_turnover_floor(monkeypatch):
    monkeypatch.setattr(providers, "_sahmk_headers", lambda: {})
    monkeypatch.setattr(providers, "sahmk_symbols", lambda: ["2222"])
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: {
        "quotes": [{
            "symbol": "2222", "price": 2.0, "change_percent": 0.5,
            "volume": 100, "high": 2.1, "low": 1.9,
        }]
    })
    rows = providers.sahmk_market_tickers()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "2222"
    assert rows[0]["volume"] == 200


def test_alpaca_tickers_filters_by_one_million_turnover(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_DATA_FEED", "delayed_sip")

    def fake_get(url, *, headers=None, params=None):
        if url.endswith("/v2/assets"):
            return [
                {"symbol": "AAA", "tradable": True, "status": "active", "exchange": "NASDAQ"},
                {"symbol": "BBB", "tradable": True, "status": "active", "exchange": "NYSE"},
            ]
        return {"AAA": {
            "dailyBar": {"c": 20, "h": 21, "l": 19, "v": 100000},
            "prevDailyBar": {"c": 19}, "latestTrade": {"p": 20},
        }, "BBB": {
            "dailyBar": {"c": 5, "h": 5.1, "l": 4.9, "v": 1000},
            "prevDailyBar": {"c": 4.9}, "latestTrade": {"p": 5},
        }}

    monkeypatch.setattr(providers, "_get_json", fake_get)
    rows = providers.alpaca_market_tickers()
    assert [row["symbol"] for row in rows] == ["AAA"]


def test_provider_status_does_not_claim_missing_credentials(monkeypatch):
    monkeypatch.delenv("SAHMK_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    status = providers.provider_status()
    assert status["saudi"]["configured"] is False
    assert status["us"]["configured"] is False
