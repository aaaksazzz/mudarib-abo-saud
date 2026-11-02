import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as module

client = module.app.test_client()

def admin_session(monkeypatch):
    module.app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(module, "AUTH_CONFIGURED", True)
    monkeypatch.setattr(module, "ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "test-admin-password-123")
    with module.db() as connection:
        row = connection.execute("SELECT id FROM users WHERE email=?", ("admin@example.test",)).fetchone()
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = row["id"]

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
    admin_session(monkeypatch)
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
    admin_session(monkeypatch)
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
    admin_session(monkeypatch)
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
    admin_session(monkeypatch)
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
    admin_session(monkeypatch)
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


def test_paid_market_access_and_admin_subscription_management(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "auth.sqlite3")
    module.app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(module, "AUTH_CONFIGURED", True)
    monkeypatch.setattr(module, "ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "owner-password-123")
    auth_client = module.app.test_client()
    registered = auth_client.post("/api/auth/register", json={
        "email": "member@example.test", "password": "member-password-123"
    })
    assert registered.status_code == 201
    assert registered.json["user"]["subscribed"] is False
    module.CACHE.pop("spot:universe", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 1.0, "volume": 2_000_000, "change24h": 1.0}
    ])
    monkeypatch.setattr(module, "analyse_candidate", lambda *args: None)
    unpaid_market = auth_client.get("/api/market/spot")
    assert unpaid_market.status_code == 403
    with module.db() as connection:
        admin = connection.execute("SELECT id FROM users WHERE email=?", ("owner@example.test",)).fetchone()
        member = connection.execute("SELECT id FROM users WHERE email=?", ("member@example.test",)).fetchone()
    with auth_client.session_transaction() as session:
        session.clear()
        session["user_id"] = admin["id"]
    granted = auth_client.post("/api/admin/subscription", json={
        "user_id": member["id"], "action": "grant", "days": 30
    })
    assert granted.status_code == 200
    locked = auth_client.post("/api/admin/sections", json={"section":"spot","enabled":False})
    assert locked.status_code == 200
    with auth_client.session_transaction() as session:
        session.clear()
        session["user_id"] = member["id"]
    assert auth_client.get("/api/market/spot").status_code == 403
    with auth_client.session_transaction() as session:
        session.clear()
        session["user_id"] = admin["id"]
    assert auth_client.post("/api/admin/sections",json={"section":"spot","enabled":True}).status_code == 200
    with auth_client.session_transaction() as session:
        session.clear()
        session["user_id"] = member["id"]
    status = auth_client.get("/api/auth/me")
    assert status.json["user"]["subscribed"] is True
    module.CACHE.pop("spot:universe", None)
    paid_market = auth_client.get("/api/market/spot")
    assert paid_market.status_code == 200
    assert paid_market.json["market"] == "spot"
    revoked = auth_client.post("/api/admin/subscription", json={
        "user_id": member["id"], "action": "revoke"
    })
    assert revoked.status_code == 403


def test_admin_password_rotation_updates_existing_admin_without_losing_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "admin-rotation.sqlite3")
    monkeypatch.setattr(module, "AUTH_CONFIGURED", True)
    monkeypatch.setattr(module, "ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "old-admin-password-123")
    with module.db() as connection:
        admin = connection.execute("SELECT id FROM users WHERE email=?", ("admin@example.test",)).fetchone()
        connection.execute(
            "INSERT INTO users(email,password_hash,role,subscription_expires_at,created_at) VALUES(?,?,?,?,?)",
            ("member@example.test", module.generate_password_hash("member-password-123"), "user", 2000000000, int(time.time()))
        )
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "new-admin-password-456")
    with module.db() as connection:
        admin_row = connection.execute("SELECT password_hash, role FROM users WHERE email=?", ("admin@example.test",)).fetchone()
        member = connection.execute("SELECT subscription_expires_at FROM users WHERE email=?", ("member@example.test",)).fetchone()
    assert module.check_password_hash(admin_row["password_hash"], "new-admin-password-456")
    assert not module.check_password_hash(admin_row["password_hash"], "old-admin-password-123")
    assert admin_row["role"] == "admin"
    assert member["subscription_expires_at"] == 2000000000


def test_independent_pages_are_served():
    paths = [
        "/markets/spot", "/markets/futures", "/markets/alpha",
        "/markets/saudi", "/markets/us", "/markets/contracts",
        "/markets/forex", "/sections/direction", "/sections/movers",
        "/sections/opportunities", "/sections/open-trades",
        "/sections/history", "/sections/system", "/blog", "/news", "/admin",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="mainContent"' in response.text

def test_invalid_market_page_is_not_found():
    assert client.get("/markets/not-a-market").status_code == 404

def test_news_feed_returns_clear_fallback_when_provider_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise module.requests.RequestException("offline")
    monkeypatch.setattr(module.requests, "get", fail)
    response = client.get("/api/news")
    assert response.status_code == 502
    assert response.json["items"] == []


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
    admin_session(monkeypatch)
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

def test_candidate_uses_4h_daily_direction_and_15m_entry(monkeypatch):
    import strategy_engine

    bars = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5 + i * 0.01,
             "volume": 1000.0, "time": i * 900000} for i in range(40)]
    candle_calls = []
    monkeypatch.setattr(module, "candles", lambda kind, symbol, interval: (
        candle_calls.append(interval) or bars
    ))
    monkeypatch.setattr(strategy_engine, "assess_timeframe", lambda rows: {
        "state": "STRONG_BUY", "score": 80.0,
    })
    monkeypatch.setattr(module, "analyse_liquidity_candidate", lambda *args, **kwargs: {
        "entry": 100.5, "stop_loss": 99.0, "tp1": 102.0, "tp2": 103.0,
        "tp3": 104.0, "risk_percent": 1.49, "quality_score": 80.0,
        "liquidity_event": "test_sweep", "volume_ratio": 1.3, "flow_pressure": 0.5,
    })
    monkeypatch.setattr(module, "analyse_orderbook_flow", lambda *args, **kwargs: {
        "status": "unavailable"
    })
    candidate = {"symbol": "AAAUSDT", "price": 100.5, "change24h": 1.0, "volume": 2_000_000}

    accepted = module.analyse_candidate("spot", candidate, market_direction="BUY", timeframe="15m")
    assert accepted is not None
    assert accepted["side"] == "BUY"
    assert accepted["timeframe"] == "15m"
    assert accepted["strategy_version"] == "hawk-quant-v2"
    assert accepted["analysis_scope"] == "4h_daily_direction_15m_entry"
    assert candle_calls == ["4h", "1d", "15m"]

    candle_calls.clear()
    rejected = module.analyse_candidate("spot", candidate, market_direction="SELL", timeframe="15m")
    assert rejected is None
    assert candle_calls == ["4h", "1d"]

    monkeypatch.setattr(module, "candles", lambda kind, symbol, interval: bars[:34])
    diagnostics = {}
    rejected = module.analyse_candidate(
        "spot", candidate, market_direction="BUY", diagnostics=diagnostics, timeframe="15m"
    )
    assert rejected is None
    assert diagnostics["reason"] == "insufficient_4h_candles"
    assert diagnostics["candles_4h"] == 34


def test_auth_me_reports_unconfigured_as_nonfatal_public_status(monkeypatch):
    monkeypatch.setattr(module, "AUTH_CONFIGURED", False)
    with client.session_transaction() as session:
        session.clear()
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["configured"] is False
    assert response.json["auth_available"] is False
    assert response.json["user"] is None

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
                created_at,updated_at,signal_candle_time,strategy_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("spot", "AAAUSDT", "15m", "BUY", 100.0, 98.0, 102.0, 104.0,
             106.0, "OPEN", now - 300, now - 300, now - 900, "hawk-quant-v2")
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
    assert 'const refreshButton=$("#refresh");if(refreshButton)refreshButton.hidden=true;' in js
    assert 'app.js?v=20261102.hawk-quant-v2' in html

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
                created_at,updated_at,signal_candle_time,strategy_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("spot", "AAAUSDT", "15m", "BUY", 100.0, 98.0, 102.0, 104.0,
             106.0, "OPEN", now, now, now, "hawk-quant-v2"),
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
    assert 'id="homeOverview"' in html
    assert 'id="homeMovers"' in html
    assert 'id="homeCoverage"' in html
    assert 'await loadHomeOverview();' in js
    assert 'target="_blank"' not in js
    assert "'+safe(x.url)+'" not in js


def test_subscription_checkout_requires_login_and_prices_months(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "membership.sqlite3")
    module.app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(module, "AUTH_CONFIGURED", True)
    monkeypatch.setattr(module, "ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "owner-password-123")
    client = module.app.test_client()
    assert client.get("/api/payments/options").status_code == 401
    registered = client.post("/api/auth/register", json={
        "email": "member@example.test", "password": "member-password-123"
    })
    assert registered.status_code == 201
    order = client.post("/api/payments/orders", json={"months": 3, "network": "trc20"})
    assert order.status_code == 201
    assert order.json["order"]["amount_usdt"] == 90
    assert order.json["payment"]["address"] == module.PAYMENT_WALLETS["trc20"]["address"]
    assert order.json["payment"]["automatic_verification"] is True
    assert client.get("/api/market/spot").status_code == 403
    with module.db() as connection:
        admin = connection.execute("SELECT id FROM users WHERE email=?", ("owner@example.test",)).fetchone()
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = admin["id"]
    assert client.get("/api/admin/sections").status_code == 200
    assert client.post("/api/admin/sections", json={"section":"spot","enabled":False}).status_code == 200
    assert client.get("/api/admin/payments").status_code == 200


def test_confirmed_chain_payment_activates_selected_months(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "chain-payment.sqlite3")
    module.app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(module, "AUTH_CONFIGURED", True)
    monkeypatch.setattr(module, "ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setattr(module, "ADMIN_PASSWORD", "owner-password-123")
    client = module.app.test_client()
    client.post("/api/auth/register", json={"email":"member@example.test","password":"member-password-123"})
    order = client.post("/api/payments/orders", json={"months":2,"network":"solana"})
    assert order.status_code == 201
    with module.db() as connection:
        row = connection.execute("SELECT created_at FROM payment_orders WHERE id=?",(order.json["order"]["id"],)).fetchone()
    monkeypatch.setattr(module,"verify_solana_transfer",lambda *_:{"confirmed":True,"amount":60,"timestamp":row["created_at"]-1})
    rejected = client.post("/api/payments/verify",json={"order_id":order.json["order"]["id"],"tx_hash":"A"*64})
    assert rejected.status_code == 422
    monkeypatch.setattr(module,"verify_solana_transfer",lambda *_:{"confirmed":True,"amount":60,"timestamp":int(time.time())+1})
    verified = client.post("/api/payments/verify",json={"order_id":order.json["order"]["id"],"tx_hash":"B"*64})
    assert verified.status_code == 200
    assert client.get("/api/auth/me").json["user"]["subscribed"] is True


def test_official_tron_usdt_contract_and_receiver_addresses_decode():
    assert module.tron_address_hex(module.USDT_TRC20_CONTRACT) == "a614f803b6fd780986a42c78ec9c7f77e6ded13c"
    assert len(module.tron_address_hex(module.PAYMENT_WALLETS["trc20"]["address"])) == 40
