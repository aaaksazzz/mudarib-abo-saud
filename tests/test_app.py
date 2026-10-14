import time

from fastapi.testclient import TestClient

from app import app, prune_results, write_json_file

client = TestClient(app)


def test_health_endpoint_is_available():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_home_is_arabic_rtl_and_has_root_canonical():
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="ar" dir="rtl"' in response.text
    assert '<link rel="canonical" href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/">' in response.text
    assert "الرئيسية للتعريف والتنقل فقط، بدون توصيات أو إشارات تداول" in response.text


def test_market_sections_have_unique_canonical_and_metadata():
    paths = {
        "/markets/spot": "سوق السبوت",
        "/markets/futures": "سوق الفيوتشر",
        "/markets/saudi": "السوق السعودي",
        "/markets/us-stocks": "الأسهم الأمريكية",
        "/radar": "رادار الأسواق",
        "/gold": "الصفقات الذهبية",
        "/results": "نتائج الإشارات",
    }
    for path, expected_title in paths.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert f"<title>{expected_title} | التداول الذكي PRO</title>" in response.text, path
        assert f'<link rel="canonical" href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run{path}">' in response.text, path
        assert f'<meta property="og:url" content="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run{path}">' in response.text, path



def test_legacy_singular_market_urls_redirect_to_canonical_market_pages():
    paths = {
        "/market/spot": "/markets/spot",
        "/market/futures": "/markets/futures",
        "/market/saudi": "/markets/saudi",
        "/market/us-stocks": "/markets/us-stocks",
        "/market/contracts": "/markets/contracts",
        "/market/forex-gold": "/markets/forex-gold",
        "/market/alpha": "/markets/alpha",
    }
    for path, destination in paths.items():
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 308, path
        assert response.headers["location"] == destination, path


def test_analysis_ui_loads_full_method_catalog_dynamically():
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="methodSearch"' in response.text
    assert "loadMethodCatalog()" in response.text
    assert 'getJson("/api/methods/catalog")' in response.text


def test_blog_and_method_pages_have_distinct_canonicals():
    blog = client.get("/blog")
    article = client.get("/blog/risk-management-stop-loss")
    method = client.get("/analysis/price-action")
    assert blog.status_code == 200
    assert article.status_code == 200
    assert method.status_code == 200
    assert 'href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/blog"' in blog.text
    assert 'href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/blog/risk-management-stop-loss"' in article.text
    assert 'href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/analysis/price-action"' in method.text


def test_robots_and_sitemap_are_served():
    robots = client.get("/robots.txt")
    sitemap = client.get("/sitemap.xml")
    assert robots.status_code == 200
    assert "Sitemap: https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text
    assert "/markets/spot" in sitemap.text
    assert "/blog/risk-management-stop-loss" in sitemap.text



def test_result_history_expires_after_24_hours(tmp_path, monkeypatch):
    results_path = tmp_path / "results.json"
    monkeypatch.setattr("app.RESULTS_PATH", results_path)
    now = int(time.time())
    write_json_file(results_path, [
        {"id": "old", "created_at": now - 86401, "result": "TP1"},
        {"id": "fresh", "created_at": now - 3600, "result": "مفتوحة"},
    ])
    items = prune_results()
    assert [item["id"] for item in items] == ["fresh"]
    assert [item["id"] for item in __import__("json").loads(results_path.read_text(encoding="utf-8"))] == ["fresh"]

def test_multilingual_blog_publishes_200_localized_articles():
    blog = client.get("/blog")
    assert blog.status_code == 200
    assert "200 مقال" in blog.text
    assert 'id="blogLang"' in blog.text
    assert blog.text.count('class="post"') == 200
    english = client.get("/blog/en-stop-loss")
    chinese = client.get("/blog/zh-stop-loss")
    arabic = client.get("/blog/ar-stop-loss")
    assert english.status_code == 200
    assert '<html lang="en" dir="ltr">' in english.text
    assert 'hreflang="ar-SA"' in english.text
    assert chinese.status_code == 200
    assert '<html lang="zh" dir="ltr">' in chinese.text
    assert arabic.status_code == 200
    assert '<html lang="ar" dir="rtl">' in arabic.text

def test_open_signals_expire_at_their_own_timeframe(tmp_path, monkeypatch):
    import json

    results_path = tmp_path / "results.json"
    monkeypatch.setattr("app.RESULTS_PATH", results_path)
    now = 2_000_000_000
    monkeypatch.setattr("app.time.time", lambda: now)
    write_json_file(results_path, [
        {"id": "expired-15m", "market": "spot", "symbol": "AAAUSDT", "interval": "15m",
         "created_at": now - 901, "result": "مفتوحة"},
        {"id": "active-weekly", "market": "spot", "symbol": "BBBUSDT", "interval": "1w",
         "created_at": now - 2 * 86400, "expires_at": now + 5 * 86400, "result": "مفتوحة"},
        {"id": "closed-old", "created_at": now - 3 * 86400, "closed_at": now - 2 * 86400,
         "result": "TP1"},
    ])

    items = prune_results()
    by_id = {item["id"]: item for item in items}
    assert by_id["expired-15m"]["result"] == "انتهت المدة"
    assert by_id["expired-15m"]["expires_at"] == now - 901 + 15 * 60
    assert by_id["active-weekly"]["result"] == "مفتوحة"
    assert by_id["active-weekly"]["expires_at"] == now + 5 * 86400
    assert "closed-old" not in by_id

    saved = json.loads(results_path.read_text(encoding="utf-8"))
    assert next(x for x in saved if x["id"] == "expired-15m")["result"] == "انتهت المدة"


def test_signal_timeframe_durations_are_defined():
    from app import INTERVAL_SECONDS

    assert INTERVAL_SECONDS == {
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1w": 604800,
        "1M": 2592000,
    }

