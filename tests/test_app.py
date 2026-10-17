import time

from fastapi.testclient import TestClient

import app as app_module
from app import app, write_json_file

client = TestClient(app)


def test_health_endpoint_is_available():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_home_is_arabic_rtl_and_does_not_reference_missing_asset():
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="ar" dir="rtl"' in response.text
    assert "التداول الذكي PRO" in response.text
    assert "/static/technical.js" not in response.text


def test_market_and_section_pages_return_shell_with_distinct_canonicals():
    paths = [
        "/markets/spot", "/markets/futures", "/markets/contracts",
        "/markets/saudi", "/markets/us-stocks", "/markets/forex-gold",
        "/markets/alpha", "/results", "/news", "/analysis", "/tasi-analysis",
        "/account", "/admin",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'lang="ar" dir="rtl"' in response.text, path
        assert f'href="https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run{path}"' in response.text, path


def test_legacy_market_urls_redirect_to_canonical_pages():
    paths = {
        "/market/spot": "/markets/spot",
        "/market/futures": "/markets/futures",
        "/market/saudi": "/markets/saudi",
        "/market/us-stocks": "/markets/us-stocks",
        "/market/contracts": "/markets/contracts",
        "/market/forex-gold": "/markets/forex-gold",
        "/market/alpha": "/markets/alpha",
        "/radar": "/markets/spot",
        "/gold": "/markets/spot",
        "/trades": "/markets/spot",
    }
    for path, destination in paths.items():
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 308, path
        assert response.headers["location"] == destination, path


def test_site_section_and_universe_endpoints_exist():
    sections = client.get("/api/site/sections")
    counts = client.get("/api/universe-counts")
    assert sections.status_code == 200
    assert sections.json()["sections"]["spot"] == "public"
    assert counts.status_code == 200
    assert counts.json()["saudi_stocks"] >= 14


def test_results_endpoint_handles_empty_and_malformed_pnl(tmp_path, monkeypatch):
    path = tmp_path / "results.json"
    monkeypatch.setattr(app_module, "RESULTS_PATH", path)
    write_json_file(path, [
        {"symbol": "AAA", "result": "TP1", "pnl_pct": "2.5"},
        {"symbol": "BBB", "result": "SL", "pnl_pct": "bad"},
        {"symbol": "CCC", "result": "مفتوحة", "pnl_pct": None},
    ])
    response = client.get("/api/results?limit=20")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["closed"] == 2
    assert data["wins"] == 1
    assert data["losses"] == 1
    assert data["profitable"] == 1


def test_strategy_signal_endpoint_does_not_fabricate_trades(monkeypatch):
    # The endpoint now adapts public ideas; stub all external sources so this stays deterministic.
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: [])
    monkeypatch.setattr(app_module, "_fetch_telegram_public_channel", lambda channel: [])
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()
    response = client.get("/api/signals/spot?interval=15m")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["scanned"] == 0


def test_public_news_aggregates_recent_items_without_network(monkeypatch):
    now = int(time.time())
    fake = [{
        "source": "Test public feed",
        "title": "Bitcoin bullish BTCUSDT buy outlook",
        "description": "Public market commentary",
        "url": "https://example.com/bitcoin-outlook",
        "published_at": now,
        "_text": "Bitcoin bullish BTCUSDT buy outlook",
    }]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()
    response = client.get("/api/news?market=spot&limit=10&refresh=1")
    assert response.status_code == 200
    data = response.json()
    assert data["sources_checked"] == len(app_module.PUBLIC_IDEA_FEEDS)
    assert len(data["items"]) == 1
    assert data["items"][0]["direction"] == "BUY"


def test_public_ideas_aggregates_recent_items_without_network(monkeypatch):
    now = int(time.time())
    fake = [{
        "source": "Test public feed",
        "title": "Bitcoin bullish BTCUSDT 15m buy",
        "description": "Entry $100 stop loss $95 target 1 $110 target 2 $115 target 3 $120",
        "url": "https://example.com/bitcoin-idea",
        "published_at": now,
        "_text": "Bitcoin bullish BTCUSDT 15m buy Entry $100 stop loss $95 target 1 $110 target 2 $115 target 3 $120",
    }]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["direction"] == "شراء"
    assert data["items"][0]["levels"]["entry"] == 100


def test_robots_sitemap_and_blog_are_available():
    robots = client.get("/robots.txt")
    sitemap = client.get("/sitemap.xml")
    blog = client.get("/blog")
    article = client.get("/blog/ar-stop-loss")
    assert robots.status_code == 200
    assert "Sitemap: https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text
    assert "/markets/spot" in sitemap.text
    assert blog.status_code == 200
    assert "مدونة التداول الذكي PRO" in blog.text
    assert article.status_code == 200


def test_public_ideas_auto_interval_and_futures_symbol_match(monkeypatch):
    now = int(time.time())
    fake = [{
        "source": "Test public feed",
        "title": "BTCUSDT bullish buy setup 15m",
        "description": "Entry $100 stop loss $95 target 1 $110 target 2 $115 target 3 $120",
        "url": "https://example.com/futures-idea",
        "published_at": now,
        "_text": "BTCUSDT bullish buy setup 15m Entry $100 stop loss $95 target 1 $110 target 2 $115 target 3 $120",
    }]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()

    response = client.get("/api/public-ideas?market=futures&interval=auto&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["interval"] == "auto"
    assert len(data["items"]) == 1
    assert data["items"][0]["symbol"] == "BTCUSDT"
    assert data["items"][0]["direction"] == "شراء"


def test_market_page_uses_auto_scan_without_visible_timeframe_buttons():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert 'interval=auto&limit=50&discover=true' in html
    assert 'id="publicIdeaFrames"' not in html


def test_public_ideas_reject_mismatched_tickers_and_incomplete_trade_levels(monkeypatch):
    now = int(time.time())
    fake = [
        {
            "source": "Test public feed",
            "title": "Carvana heading back to earth after lunar launch",
            "description": "Near support, bearish below the neckline; short setup",
            "url": "https://example.com/carvana",
            "published_at": now,
            "_text": "Carvana (NYSE: CVNA) bearish short setup on the daily timeframe. Near support.",
        },
        {
            "source": "Test public feed",
            "title": "FET approaching support (4H)",
            "description": "Bullish setup, but no trade levels",
            "url": "https://example.com/fet",
            "published_at": now,
            "_text": "FETUSDT bullish 4H buy opportunity near support",
        },
    ]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()
    response = client.get("/api/public-ideas?market=futures&interval=auto&limit=10")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_public_futures_ideas_require_title_ticker_and_valid_complete_levels(monkeypatch):
    now = int(time.time())
    fake = [
        {
            "source": "Telegram — @Binance_Futures_Trades",
            "title": "#UNI /USDT - Short 4H",
            "description": "Entry 7.243 Stop Loss 7.3387 Target 1 7.19379 Target 2 7.1357 Target 3 6.92283",
            "url": "https://t.me/Binance_Futures_Trades/52918",
            "published_at": now,
            "_text": "#UNI /USDT - Short 4H Entry 7.243 Stop Loss 7.3387 Target 1 7.19379 Target 2 7.1357 Target 3 6.92283",
        },
        {
            "source": "TradingView — Trading Ideas",
            "title": "Carvana heading back to earth after lunar launch",
            "description": "The stock may fall near its peak; leverage is discussed in a separate context.",
            "url": "https://example.com/carvana",
            "published_at": now,
            "_text": "Carvana heading back to earth after lunar launch bearish near its peak leverage",
        },
        {
            "source": "TradingView — Trading Ideas",
            "title": "UNIUSDT Short 4H setup",
            "description": "Entry 7.24 Stop Loss 7.34 Target 1 7.30 Target 2 7.20 Target 3 7.10",
            "url": "https://example.com/invalid-target-order",
            "published_at": now,
            "_text": "UNIUSDT Short 4H Entry 7.24 Stop Loss 7.34 Target 1 7.30 Target 2 7.20 Target 3 7.10",
        },
    ]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()

    response = client.get("/api/public-ideas?market=futures&interval=auto&limit=10")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["symbol"] == "UNI"
    assert items[0]["direction"] == "بيع"
    assert items[0]["has_complete_levels"] is True
    assert items[0]["url"] == ""


def test_public_ideas_detect_timeframe_in_title_when_body_omits_it(monkeypatch):
    now = int(time.time())
    fake = [{
        "source": "Test public feed",
        "title": "#UNI /USDT - Short 4H",
        "description": "Entry 7.243 Stop Loss 7.3387 Target 1 7.19379 Target 2 7.1357 Target 3 6.92283",
        "url": "https://example.com/title-timeframe",
        "published_at": now,
        "_text": "#UNI /USDT - Short Entry 7.243 Stop Loss 7.3387 Target 1 7.19379 Target 2 7.1357 Target 3 6.92283",
    }]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()

    response = client.get("/api/public-ideas?market=futures&interval=4h&limit=10")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["symbol"] == "UNI"
    assert items[0]["direction"] == "بيع"
    assert items[0]["interval"] == "4h"
    assert items[0]["has_complete_levels"] is True


def test_public_idea_levels_parse_html_labels_and_numbered_target_variants():
    levels = app_module._public_idea_levels(
        "<b>Entry Price</b>: 100 "
        "<b>Stop-Loss</b>: 95 "
        "<b>TP-1</b>: 110 "
        "<b>Target #2</b>: 115 "
        "<b>Take Profit 3</b>: 120"
    )
    assert levels == {
        "entry": 100.0,
        "stop_loss": 95.0,
        "tp1": 110.0,
        "tp2": 115.0,
        "tp3": 120.0,
    }


def test_public_idea_interval_distinguishes_monthly_from_one_minute():
    assert app_module._public_idea_interval("BTCUSDT 1M") == "1M"
    assert app_module._public_idea_interval("BTCUSDT monthly") == "1M"
    assert app_module._public_idea_interval("BTCUSDT 1m") == ""
    assert app_module._public_idea_interval("BTCUSDT 15m") == "15m"


def test_public_idea_tickers_are_checked_against_the_requested_market():
    assert app_module._public_idea_symbol_matches_market("futures", "UNI", "#UNI /USDT - Short 4H")
    assert app_module._public_idea_symbol_matches_market("spot", "NEWTOKENUSDT", "NEWTOKENUSDT bullish setup")
    assert not app_module._public_idea_symbol_matches_market("spot", "AAPL", "Bitcoin mentioned in a stock article")
    assert app_module._public_idea_symbol_matches_market("us", "AAPL", "AAPL buy setup")
    assert not app_module._public_idea_symbol_matches_market("saudi", "AAPL", "AAPL buy setup")
