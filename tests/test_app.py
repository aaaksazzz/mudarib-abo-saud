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
    assert set(health.json["live_markets"]) == {"spot", "futures", "alpha", "forex"}

def test_timeframe_is_fixed_to_15m(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "fixed-timeframe.sqlite3")
    admin_session(monkeypatch)
    module.CACHE.pop("spot:universe", None)
    monkeypatch.setattr(module, "market_tickers", lambda kind: [
        {"symbol": "AAAUSDT", "price": 2.0, "volume": 2_000_000, "change24h": 1.0}
    ])
    monkeypatch.setattr(module, "analyse_candidate", lambda *args: None)
    response = client.get("/api/market/spot?timeframe=5m")
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

def test_indicators_require_sufficient_data():
    assert module.ema([1,2,3], 5) is None
    assert module.frame_bias([{"close": 1}] * 10) is None

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


def test_signal_entry_uses_live_quote_not_previous_candle_close(monkeypatch):
    bars = []
    for i in range(60):
        close = 100 + i * 0.1
        bars.append({"open": close - 0.05, "high": close + 0.5,
                     "low": close - 0.5, "close": close, "volume": 100,
                     "time": i * 900000})
    monkeypatch.setattr(module, "candles", lambda *args: bars)
    monkeypatch.setattr(module, "frame_bias", lambda rows: "BUY")
    monkeypatch.setattr(module, "rsi", lambda values: 60.0)
    original_ema = module.ema
    monkeypatch.setattr(module, "ema", lambda values, period: 101.0 if period == 20 else 100.0)
    candidate = {"symbol": "AAAUSDT", "price": 110.0, "change24h": 4.0, "volume": 2_000_000}
    signal = module.analyse_candidate("spot", candidate, "BUY")
    assert signal is not None
    assert signal["entry"] == 110.0
    assert signal["price"] == 110.0


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


def test_public_market_access_and_admin_subscription_management(tmp_path, monkeypatch):
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
    public_market = auth_client.get("/api/market/spot")
    assert public_market.status_code == 200
    assert public_market.json["market"] == "spot"
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
    with auth_client.session_transaction() as session:
        session.clear()
        session["user_id"] = member["id"]
    status = auth_client.get("/api/auth/me")
    assert status.json["user"]["subscribed"] is True
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
        "/sections/history", "/blog", "/news",
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
