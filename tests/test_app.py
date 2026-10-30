from app import app

def test_health():
    r=app.test_client().get("/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

def test_home():
    r=app.test_client().get("/")
    assert r.status_code == 200
    assert b"SMART" not in r.data

def test_unknown_market_is_explicit():
    r=app.test_client().get("/api/market/saudi")
    assert r.status_code == 503
    assert r.get_json()["status"] == "provider_required"

def test_bad_timeframe():
    r=app.test_client().get("/api/market/spot?timeframe=5m")
    assert r.status_code == 400
