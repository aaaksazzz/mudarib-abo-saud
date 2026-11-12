from fastapi.testclient import TestClient
from app.main import create_app


def test_liveness_is_fast_and_independent_of_providers():
    client = TestClient(create_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_market_shell_returns_all_seven_markets_without_provider_calls():
    client = TestClient(create_app())
    response = client.get("/api/v2/markets")
    assert response.status_code == 200
    assert len(response.json()) == 7
    assert response.json()[0]["stale"] is True


def test_market_snapshot_has_explicit_stale_state():
    client = TestClient(create_app())
    response = client.get("/api/v2/markets/binance-futures/snapshot")
    assert response.status_code == 200
    assert response.json()["market"] == "binance-futures"
    assert response.json()["stale"] is True
