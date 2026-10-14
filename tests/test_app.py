from fastapi.testclient import TestClient

from app import app

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
