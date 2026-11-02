import app as app_module


def test_public_status_endpoints_report_live_configuration():
    with app_module.app.test_client() as client:
        health = client.get("/api/health")
        providers = client.get("/api/providers")
    assert health.status_code == 200
    assert health.get_json()["ok"] is True
    assert health.get_json()["database"] == "ok"
    assert providers.status_code == 200
    ids = {row["id"] for row in providers.get_json()["markets"]}
    assert {"spot", "futures", "coinm", "alpha", "saudi", "us", "contracts", "forex"} <= ids
