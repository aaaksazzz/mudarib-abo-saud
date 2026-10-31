import app as app_module


def test_system_status_reports_safe_local_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "trades.sqlite3")
    monkeypatch.setattr(app_module, "GAMMAFLIP_API_KEY", "")
    with app_module.app.test_client() as client:
        response = client.get("/api/system/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["database"] == "ok"
    assert payload["trades"]["total"] == 0
    assert payload["gamma"]["configured"] is False
    assert {row["id"] for row in payload["markets"]} >= {
        "spot", "futures", "alpha", "saudi", "us", "contracts", "forex", "gammaflip"
    }
    assert "GAMMAFLIP_API_KEY" not in response.get_data(as_text=True)
