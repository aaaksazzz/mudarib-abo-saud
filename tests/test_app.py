import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as module

client = module.app.test_client()

def test_health_and_home():
    assert client.get("/health").json["ok"] is True
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="ar" dir="rtl"' in response.text
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["database"] == "ok"
    assert set(health.json["live_markets"]) == {"spot", "futures", "coinm", "alpha", "forex"}

def test_market_api_accepts_only_15m_strategy_timeframe(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "timeframe-support.sqlite3")
    module.CACHE.pop("spot:universe", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 2.0, "volume": 2_000_000, "change24h": 1.0}
    ])
    monkeypatch.setattr(module, "analyse_candidate", lambda *args: None)
    accepted = client.get("/api/market/spot?timeframe=15m")
    assert accepted.status_code == 200
    assert accepted.json["timeframe"] == "15m"
    # Legacy links and cached browser tabs are normalized to the single
    # supported strategy timeframe instead of surfacing an unsupported error.
    for timeframe in ("5m", "1h", "4h", "1d", "1w", "1M"):
        response = client.get("/api/market/spot?timeframe=" + timeframe)
        assert response.status_code == 200
        assert response.json["timeframe"] == "15m"
    assert module.SCAN_INTERVAL == "15m"

def test_unconfigured_markets_are_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "unconfigured.sqlite3")
    response = client.get("/api/market/saudi")
    assert response.status_code == 503
    assert response.json["status"] == "provider_required"
    assert response.json["signals"] == []

def test_market_list_is_explicit():
    response = client.get("/api/markets")
    assert response.status_code == 200
    statuses = {item["id"]: item["status"] for item in response.json["markets"]}
    assert statuses["spot"] == "live"
    assert statuses["futures"] == "live"
    assert statuses["alpha"] == "live"
    assert statuses["saudi"] == "provider_required"

def test_trade_tracker_marks_targets_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "trades.sqlite3")
    signal = {"symbol":"TESTUSDT","timeframe":"15m","side":"BUY","entry":100,
              "stop_loss":95,"tp1":105,"tp2":110,"tp3":115}
    module.save_new_trades("spot", [signal])
    module.update_open_trades("spot", {"TESTUSDT":106})
    with module.db() as connection:
        row = connection.execute("SELECT * FROM trades").fetchone()
    assert row["tp1_hit"] == 1
    assert row["tp3_hit"] == 0
    assert row["status"] == "OPEN"
    module.update_open_trades("spot", {"TESTUSDT":116})
    with module.db() as connection:
        row = connection.execute("SELECT * FROM trades").fetchone()
    assert row["tp3_hit"] == 1
    assert row["status"] == "TP3"



def test_open_trade_expires_after_24_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "trade-expiry.sqlite3")
    signal = {"symbol":"OLDUSDT","timeframe":"15m","side":"BUY","entry":100,
              "stop_loss":95,"tp1":105,"tp2":110,"tp3":115}
    module.save_new_trades("spot", [signal])
    with module.db() as connection:
        created = connection.execute("SELECT created_at FROM trades").fetchone()["created_at"]
    monkeypatch.setattr(module.time, "time", lambda: created + 24 * 60 * 60 + 1)
    module.update_open_trades("spot", {"OLDUSDT": 101})
    with module.db() as connection:
        row = connection.execute("SELECT status,closed_at FROM trades").fetchone()
    assert row["status"] == "EXPIRED"
    assert row["closed_at"] == created + 24 * 60 * 60 + 1


def test_invalid_trade_levels_are_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "trades.sqlite3")
    invalid = {"symbol":"BADUSDT","timeframe":"15m","side":"BUY","entry":100,
               "stop_loss":105,"tp1":104,"tp2":110,"tp3":115}
    module.save_new_trades("spot", [invalid])
    with module.db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_cache_reuses_successful_value():
    key = "test-cache-reuse"
    module.CACHE.pop(key, None)
    calls = []
    def loader():
        calls.append(1)
        return {"value": 7}
    assert module.cached(key, 60, loader) == {"value": 7}
    assert module.cached(key, 60, loader) == {"value": 7}
    assert len(calls) == 1


def test_market_response_includes_breadth_and_real_movers(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "market-test.sqlite3")
    module.CACHE.pop("spot:universe", None)
    rows = [
        {"symbol":"AAAUSDT","price":2.0,"volume":3_000_000,"change24h":8.0},
        {"symbol":"BBBUSDT","price":1.0,"volume":2_000_000,"change24h":-4.0},
        {"symbol":"CCCUSDT","price":3.0,"volume":1_500_000,"change24h":0.0},
    ]
    monkeypatch.setattr(module, "market_tickers", lambda kind: rows)
    monkeypatch.setattr(module, "analyse_candidate", lambda *args: None)
    response = client.get("/api/market/spot?timeframe=15m")
    assert response.status_code == 200
    payload = response.json
    assert payload["up"] == 1
    assert payload["down"] == 1
    assert payload["flat"] == 1
    assert payload["total"] == 3
    assert {x["symbol"] for x in payload["movers"]} == {"AAAUSDT", "BBBUSDT"}
    assert payload["fast_movers"][0]["fast_mover_score"] >= payload["fast_movers"][-1]["fast_mover_score"]
    assert payload["fast_movers"][0]["fast_mover_rank"] == 1


def test_alpha_public_universe_uses_only_trading_usdt_pairs(monkeypatch):
    module.CACHE.pop('alpha:tokens', None)
    module.CACHE.pop('alpha:exchange-info', None)
    token_payload = {'success': True, 'data': [
        {'alphaId':'ALPHA_175','symbol':'GORILLA','price':'0.01','percentChange24h':'12.5','volume24h':'250000','offline':False},
        {'alphaId':'ALPHA_176','symbol':'OTHER','price':'0.02','percentChange24h':'-2','volume24h':'150000','offline':False},
    ]}
    info_payload = {'success': True, 'data': {'symbols': [
        {'symbol':'ALPHA_175USDT','status':'TRADING','quoteAsset':'USDT'},
        {'symbol':'ALPHA_176USDT','status':'BREAK','quoteAsset':'USDT'},
    ]}}
    def fake_fetch(url, params=None):
        return token_payload if url.endswith('/token/list') else info_payload
    monkeypatch.setattr(module, 'fetch_json', fake_fetch)
    rows = module.alpha_market_tickers()
    assert len(rows) == 1
    assert rows[0]['symbol'] == 'ALPHA_175USDT'
    assert rows[0]['volume'] == 250000.0

def test_alpha_candles_parse_public_kline_payload(monkeypatch):
    module.CACHE.pop('alpha:ALPHA_175USDT:15m', None)
    raw = [[1700000000000,'1.0','1.2','0.9','1.1','500',1700000899999,'550']]
    monkeypatch.setattr(module, 'fetch_json', lambda *args, **kwargs: {'success':True,'data':raw})
    rows = module.candles('alpha','ALPHA_175USDT','15m')
    assert rows[0]['open'] == 1.0
    assert rows[0]['high'] == 1.2
    assert rows[0]['low'] == 0.9
    assert rows[0]['close'] == 1.1

def test_alpha_market_endpoint_accepts_public_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DB_PATH', tmp_path / 'alpha.sqlite3')
    rows = [{'symbol':'ALPHA_175USDT','price':0.01,'volume':250000,'change24h':12.5}]
    monkeypatch.setattr(module, 'market_tickers', lambda kind: rows)
    monkeypatch.setattr(module, 'analyse_candidate', lambda *args: None)
    response = client.get('/api/market/alpha?timeframe=15m')
    assert response.status_code == 200
    assert response.json['market'] == 'alpha'
    assert response.json['source'] == 'Binance Alpha public market data'
    assert response.json['total'] == 1


def test_provider_registry_is_honest_and_lists_real_fallbacks():
    response = client.get("/api/providers")
    assert response.status_code == 200
    markets = {item["id"]: item for item in response.json["markets"]}
    assert markets["spot"]["status"] == "configured"
    assert "api-gcp.binance.com" in markets["spot"]["fallbacks"]
    assert markets["forex"]["primary"] == "BiQuote public REST"
    assert markets["saudi"]["status"] == "optional_disabled"
    assert markets["us"]["status"] == "optional_disabled"
    assert markets["contracts"]["status"] == "provider_required"


def test_biquote_candles_ignore_open_bar(monkeypatch):
    module.CACHE.pop("forex:EURUSD:15m", None)
    payload = {"bars": [
        {"openTime": "2026-10-31T10:00:00Z", "open": 1.0, "high": 1.2,
         "low": 0.9, "close": 1.1, "tickVolume": 10, "isOpen": False},
        {"openTime": "2026-10-31T10:15:00Z", "open": 1.1, "high": 1.3,
         "low": 1.0, "close": 1.2, "tickVolume": 8, "isOpen": True},
    ]}
    monkeypatch.setattr(module, "fetch_json", lambda *args, **kwargs: payload)
    rows = module.candles("forex", "EURUSD", "15m")
    assert len(rows) == 1
    assert rows[0]["close"] == 1.1
    assert rows[0]["volume"] == 10


def test_biquote_market_tickers_reject_stale_and_closed_quotes(monkeypatch):
    module.CACHE.pop("biquote:active-symbols", None)
    module.CACHE.pop("biquote:latest:EURUSD,XAUUSD,GBPUSD", None)
    def fake_fetch(url, params=None):
        if url.endswith("/api/active"):
            return [
                {"name": "EURUSD", "type": "Forex"},
                {"name": "XAUUSD", "type": "Commodity"},
                {"name": "GBPUSD", "type": "Forex"},
            ]
        return [
            {"symbol": "EURUSD", "mid": 1.1, "dayDiffPercent": 0.5,
             "quoteAgeSeconds": 2, "marketState": "open", "stale": False},
            {"symbol": "XAUUSD", "mid": 2000, "dayDiffPercent": 0.2,
             "quoteAgeSeconds": 900, "marketState": "open", "stale": True},
            {"symbol": "GBPUSD", "mid": 1.25, "dayDiffPercent": -0.3,
             "quoteAgeSeconds": 0, "marketState": "closed", "stale": False},
        ]
    monkeypatch.setattr(module, "fetch_json", fake_fetch)
    rows = module.biquote_market_tickers()
    assert [row["symbol"] for row in rows] == ["EURUSD"]


def test_binance_candles_drop_unfinished_bar(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(module.time, "time", lambda: now)
    module.CACHE.pop("spot:AAAUSDT:15m", None)
    payload = [
        [now * 1000 - 900000, "10", "12", "9", "11", "100", now * 1000 - 1],
        [now * 1000, "11", "13", "10", "12", "80", now * 1000 + 899999],
    ]
    monkeypatch.setattr(module, "fetch_json", lambda *args, **kwargs: payload)
    rows = module.candles("spot", "AAAUSDT", "15m")
    assert len(rows) == 1
    assert rows[0]["close"] == 11.0


def test_signal_uses_completed_entry_timeframe_candles_and_live_quote_separately(monkeypatch):
    import math
    bars = []
    for i in range(80):
        close = 100 + i * 0.1 + math.sin(i / 3) * 0.12
        bars.append({"open": close - 0.03, "high": close + 0.55,
                     "low": close - 0.55, "close": close, "volume": 1000 + (i % 5) * 20,
                     "time": i * 900000})
    monkeypatch.setattr(module, "candles", lambda *args: bars)
    monkeypatch.setattr(module, "analyse_orderbook_flow", lambda *args, **kwargs: {"status": "unavailable"})
    monkeypatch.setattr(module, "analyse_liquidity_candidate", lambda *args, **kwargs: {
        "entry": 110.0, "stop_loss": 108.0, "tp1": 112.0, "tp2": 114.0,
        "tp3": 116.0, "risk_percent": 1.82, "quality_score": 80.0,
        "liquidity_event": "test_sweep", "volume_ratio": 1.4, "flow_pressure": 0.5,
    })
    candidate = {"symbol": "AAAUSDT", "price": 110.0, "change24h": 4.0, "volume": 2_000_000}
    signal = module.analyse_candidate("spot", candidate, "BUY", timeframe="15m")
    assert signal is not None
    assert signal["entry"] == 110.0
    assert signal["price"] == 110.0
    assert signal["quality_score"] >= 64
    assert signal["quality_score"] != 90.0


def test_yahoo_provider_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "yahoo-disabled.sqlite3")
    original = module.YAHOO_ENABLED
    try:
        module.YAHOO_ENABLED = False
        response = client.get("/api/market/us")
        assert response.status_code == 503
        assert response.json["status"] == "provider_required"
    finally:
        module.YAHOO_ENABLED = original


def test_yahoo_candles_drop_forming_bar(monkeypatch):
    import pandas as pd
    now = int(module.time.time() * 1000)
    index = pd.to_datetime([now - 30 * 60 * 1000, now - 5 * 60 * 1000], unit="ms", utc=True)
    frame = pd.DataFrame({
        "Open": [10.0, 11.0], "High": [12.0, 13.0],
        "Low": [9.0, 10.0], "Close": [11.0, 12.0], "Volume": [100, 200],
    }, index=index)
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
        def history(self, **kwargs):
            assert kwargs["interval"] == "15m"
            return frame
    class FakeYahoo:
        Ticker = FakeTicker
    monkeypatch.setattr(module, "yf", FakeYahoo)
    monkeypatch.setattr(module, "YAHOO_ENABLED", True)
    rows = module.yahoo_candles("AAPL", "15m")
    assert len(rows) == 1
    assert rows[0]["close"] == 11.0


def test_independent_pages_are_served():
    paths = [
        "/markets/spot", "/markets/futures", "/markets/alpha",
        "/markets/saudi", "/markets/us", "/markets/contracts",
        "/markets/forex", "/sections/direction",
        "/sections/opportunities", "/sections/open-trades", "/sections/history",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="homePage"' in response.text
    for path in ("/blog", "/news", "/admin"):
        assert client.get(path).status_code == 404

def test_invalid_market_page_is_not_found():
    assert client.get("/markets/not-a-market").status_code == 404

def test_market_scan_reports_candidate_rejection_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "scan-diagnostics.sqlite3")
    module.CACHE.pop("spot:universe", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 1.0, "volume": 2_000_000, "change24h": 2.0},
        {"symbol": "BBBUSDT", "price": 2.0, "volume": 3_000_000, "change24h": 1.0},
    ])
    def reject(kind, item, direction, diagnostics, timeframe="15m"):
        diagnostics["candles_ready"] = True
        diagnostics["reason"] = "no_sweep_or_absorption"
        return None
    monkeypatch.setattr(module, "analyse_candidate", reject)
    response = client.get("/api/market/spot")
    assert response.status_code == 200
    details = response.json["scan_diagnostics"]
    assert details["universe_size"] == 2
    assert details["candidates_scanned"] == 2
    assert details["candles_ready"] == 2
    assert details["accepted_before_top3"] == 0
    assert details["rejected_by_reason"] == {"no_sweep_or_absorption": 2}


def test_gammapro_reports_specific_rejection_reason():
    from gamma_engine import analyse_liquidity_candidate
    diagnostics = {}
    assert analyse_liquidity_candidate([], 100.0, "BUY", diagnostics=diagnostics) is None
    assert diagnostics["reason"] == "insufficient_candles"


def test_no_key_analysis_method_has_clear_non_options_description():
    response = client.get("/api/analysis/method")
    assert response.status_code == 200
    payload = response.json
    assert payload["mode"] == "ohlcv_liquidity_proxy"
    assert "بدون أي مفاتيح API" in payload["message"]
    assert "Gamma Exposure" in payload["message"]
    legacy = client.get("/api/gamma/crypto")
    assert legacy.status_code == 200
    assert legacy.json["mode"] == payload["mode"]


def test_candidate_worker_failure_does_not_abort_market_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "worker-failure.sqlite3")
    module.CACHE.pop("spot:universe", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 2.0, "volume": 2_000_000, "change24h": 2.0},
        {"symbol": "BBBUSDT", "price": 1.0, "volume": 2_000_000, "change24h": 1.0},
    ])
    def flaky(kind, row, direction, diagnostics=None, timeframe="15m"):
        if row["symbol"] == "AAAUSDT":
            raise RuntimeError("simulated adapter failure")
        if diagnostics is not None:
            diagnostics["reason"] = "no_sweep_or_absorption"
        return None
    monkeypatch.setattr(module, "analyse_candidate", flaky)
    response = client.get("/api/market/spot")
    assert response.status_code == 200
    assert response.json["scan_diagnostics"]["rejected_by_reason"]["analysis_error"] == 1

def test_coinm_uses_contract_status_field(monkeypatch):
    module.CACHE.pop("coinm:exchange-info", None)
    payload = {"symbols": [
        {"symbol": "BTCUSD_PERP", "contractStatus": "TRADING",
         "quoteAsset": "USD", "contractType": "PERPETUAL"},
        {"symbol": "ETHUSD_PERP", "contractStatus": "DELIVERING",
         "quoteAsset": "USD", "contractType": "PERPETUAL"},
        {"symbol": "OLDUSD_PERP", "status": "TRADING",
         "quoteAsset": "USD", "contractType": "PERPETUAL"},
    ]}
    monkeypatch.setattr(module, "fetch_first_json", lambda urls: payload)
    assert module.binance_active_symbols("coinm") == {"BTCUSD_PERP"}

def test_candidate_uses_only_15m_for_direction_and_entry(monkeypatch):
    import timeframe_strategy
    bars = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
             "volume": 1000.0, "time": i * 900000} for i in range(35)]
    candle_calls = []
    monkeypatch.setattr(module, "candles", lambda kind, symbol, interval: (candle_calls.append(interval) or bars))
    monkeypatch.setattr(timeframe_strategy, "assess_timeframe", lambda rows, side=None: {
        "state": "STRONG_SELL", "score": 75.0,
        "analysis": {"candles_used": len(rows)}
    })
    monkeypatch.setattr(module, "analyse_liquidity_candidate", lambda *args, **kwargs: {
        "entry": 100.5, "stop_loss": 102.0, "tp1": 99.0, "tp2": 97.5,
        "tp3": 96.0, "risk_percent": 1.49, "quality_score": 75.0,
        "liquidity_event": "test_sweep", "volume_ratio": 1.3, "flow_pressure": -0.5,
    })
    monkeypatch.setattr(module, "analyse_orderbook_flow", lambda *args, **kwargs: {"status": "unavailable"})
    candidate = {"symbol": "AAAUSDT", "price": 100.5, "change24h": 1.0, "volume": 2_000_000}
    accepted = module.analyse_candidate("spot", candidate, timeframe="15m")
    assert accepted is not None
    assert accepted["side"] == "SELL"
    assert accepted["timeframe"] == "15m"
    assert accepted["analysis_scope"] == "single_timeframe_15m"
    assert accepted["reference_analysis"]["15m"]["state"] == "STRONG_SELL"
    assert candle_calls == ["15m"]

    candle_calls.clear()
    accepted_with_bullish_breadth = module.analyse_candidate(
        "spot", candidate, market_direction="BUY", timeframe="15m"
    )
    assert accepted_with_bullish_breadth is not None
    assert accepted_with_bullish_breadth["side"] == "SELL"
    assert candle_calls == ["15m"]

    monkeypatch.setattr(module, "candles", lambda kind, symbol, interval: bars[:34])
    diagnostics = {}
    rejected = module.analyse_candidate("spot", candidate, diagnostics=diagnostics, timeframe="15m")
    assert rejected is None
    assert diagnostics["reason"] == "insufficient_candles"
    assert diagnostics["candles_received"] == 34

def test_open_confirmed_trade_remains_in_opportunity_cards_after_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "persistent-cards.sqlite3")
    module.CACHE.pop("spot:universe", None)
    module.SCAN_CURSORS.pop("spot", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 105.0, "volume": 2_000_000, "change24h": 5.0}
    ])
    monkeypatch.setattr(module, "analyse_candidate", lambda *args: None)
    now = int(time.time())
    with module.db() as connection:
        connection.execute(
            """INSERT INTO trades
               (market,symbol,timeframe,side,entry,stop_loss,tp1,tp2,tp3,status,
                created_at,updated_at,signal_candle_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("spot", "AAAUSDT", "15m", "BUY", 100.0, 98.0, 102.0, 104.0,
             106.0, "OPEN", now - 300, now - 300, now - 900)
        )
    response = client.get("/api/market/spot?timeframe=15m")
    assert response.status_code == 200
    assert len(response.json["signals"]) == 1
    card = response.json["signals"][0]
    assert card["symbol"] == "AAAUSDT"
    assert card["persisted"] is True
    assert card["entry"] == 100.0
    assert card["stop_loss"] == 98.0
    assert card["tp3"] == 106.0

def test_market_page_does_not_crash_when_optional_refresh_button_is_absent():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="refreshMarket"' in html
    assert 'function marketLoad()' in js
    assert 'clean-core-1' in html

def test_market_direction_and_open_trades_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "persistent-market-state.sqlite3")
    module.save_market_snapshot("spot", "BUY", 8, 3, 1, 12, "test-feed")
    snapshot = module.load_market_snapshot("spot")
    assert snapshot["direction"] == "BUY"
    assert snapshot["up"] == 8
    assert snapshot["down"] == 3
    assert snapshot["total"] == 12
    assert snapshot["source"] == "test-feed"

    now = int(time.time())
    with module.db() as connection:
        connection.execute(
            """INSERT INTO trades
               (market,symbol,timeframe,side,entry,stop_loss,tp1,tp2,tp3,status,
                created_at,updated_at,signal_candle_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("spot", "AAAUSDT", "15m", "BUY", 100.0, 98.0, 102.0, 104.0,
             106.0, "OPEN", now, now, now),
        )
    signals, opened = module.load_saved_market_trades("spot", "15m")
    assert len(signals) == 1
    assert len(opened) == 1
    assert signals[0]["symbol"] == "AAAUSDT"
    assert signals[0]["persisted"] is True

def test_market_api_restores_last_direction_when_provider_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "stale-market-state.sqlite3")
    module.CACHE.pop("spot:universe", None)
    module.save_market_snapshot("spot", "SELL", 2, 9, 1, 12, "test-feed")

    def unavailable(_kind):
        raise module.requests.RequestException("simulated provider outage")

    monkeypatch.setattr(module, "market_tickers", unavailable)
    response = client.get("/api/market/spot?timeframe=15m")
    assert response.status_code == 200
    assert response.json["snapshot_stale"] is True
    assert response.json["direction"] == "SELL"
    assert response.json["up"] == 2
    assert response.json["down"] == 9


def test_home_page_shows_market_radar_and_keeps_news_inside_the_site():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="marketOverview"' in html
    assert 'id="fastMovers"' in html
    assert 'id="tradeCards"' in html
    assert 'async function home()' in js
    assert 'authForm' not in html
    assert 'subscriptionPanel' not in html
    assert 'href="/blog"' not in html
    assert 'href="/news"' not in html
