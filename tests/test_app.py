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
    assert set(health.json["live_markets"]) == {"spot", "futures", "alpha"}

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

def test_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_CACHE_ENTRIES", 3)
    for index in range(5):
        module.cached(f"bounded-cache-{index}", 60, lambda i=index: i)
    assert len([key for key in module.CACHE if key.startswith("bounded-cache-")]) <= 3
    for key in list(module.CACHE):
        if key.startswith("bounded-cache-"):
            module.CACHE.pop(key, None)
            module.CACHE_KEY_LOCKS.pop(key, None)


def test_only_one_open_trade_per_market_symbol_across_timeframes(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "dedupe.sqlite3")
    first = {"symbol":"DUPUSDT","timeframe":"15m","side":"BUY","entry":100,
             "stop_loss":95,"tp1":105,"tp2":110,"tp3":115}
    second = {"symbol":"DUPUSDT","timeframe":"1h","side":"BUY","entry":101,
              "stop_loss":96,"tp1":106,"tp2":111,"tp3":116}
    module.save_new_trades("spot", [first])
    module.save_new_trades("spot", [second])
    with module.db() as connection:
        rows = connection.execute(
            "SELECT symbol,timeframe FROM trades WHERE market='spot' AND status='OPEN'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["timeframe"] == "15m"
