import sys
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
    assert set(health.json["live_markets"]) == {"spot", "futures", "alpha", "forex"}

def test_timeframe_validation():
    response = client.get("/api/market/spot?timeframe=5m")
    assert response.status_code == 400

def test_unconfigured_markets_are_not_fabricated():
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
    assert markets["saudi"]["status"] == "provider_required"
    assert markets["us"]["status"] == "provider_required"
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
