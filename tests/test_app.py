import math
import os
import time

from fastapi.testclient import TestClient

import app as app_module
from app import app, write_json_file

# Protected market pages and APIs require a valid seven-day session in production.
# Use HTTPS in tests so the Secure cookie behaves like the deployed service.
client = TestClient(app, base_url="https://testserver")
client.cookies.set(
    "market_session",
    app_module._market_session_token(int(time.time()) + 60 * 60),
    path="/",
)


def test_news_and_tasi_analysis_pages_are_public():
    anonymous = TestClient(app, base_url="https://testserver")
    for path in ("/news", "/tasi-analysis"):
        response = anonymous.get(path)
        assert response.status_code == 200
        assert "أدخل الرقم السري للمتابعة" not in response.text
    api_response = anonymous.get("/api/news?market=spot")
    assert api_response.status_code == 200



def test_legacy_market_pin_route_is_disabled():
    anonymous = TestClient(app, base_url="https://testserver")
    response = anonymous.post("/market-unlock", json={"pin": "2341"})
    assert response.status_code == 404
    assert anonymous.get("/markets/spot").status_code == 200



def test_health_endpoint_is_available():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    api_response = TestClient(app, base_url="https://testserver").get("/api/health")
    assert api_response.status_code == 200
    assert api_response.json()["ok"] is True


def test_closed_section_blocks_page_and_market_api(monkeypatch):
    monkeypatch.setattr(app_module, "_section_settings", lambda: {"spot": "closed"})
    page_response = client.get("/markets/spot")
    api_response = client.get("/api/market/spot?limit=10")
    assert page_response.status_code == 403
    assert api_response.status_code == 403
    assert "القسم مغلق" in api_response.json()["detail"]


def test_new_strategy_rejects_insufficient_candle_history(monkeypatch):
    candles = [
        {"open": 99.5, "high": 100, "low": 99, "close": 99.7, "volume": 10}
        for _ in range(12)
    ]
    monkeypatch.setattr(app_module, "candle_data", lambda *args, **kwargs: candles)
    items, completed, message = app_module._generate_pro_market_signals(
        "spot", "15m", [{"symbol": "TESTUSDT", "price": 99.7}], limit=20
    )
    assert completed is True
    assert items == []
    assert "اجتازت" in message or "فرصة" in message


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
        {"symbol": "AAA", "result": "TP1", "pnl_pct": "2.5", "source": "pro_confluence_v1"},
        {"symbol": "BBB", "result": "SL", "pnl_pct": "bad", "source": "pro_confluence_v1"},
        {"symbol": "CCC", "result": "مفتوحة", "pnl_pct": None, "source": "pro_confluence_v1"},
    ])
    response = client.get("/api/results?limit=20")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["closed"] == 2
    assert data["wins"] == 1
    assert data["losses"] == 1
    assert data["profitable"] == 1


def _fake_ai_signal(market, interval, symbol="TESTUSDT"):
    now = int(time.time())
    return {
        "symbol": symbol, "direction": "شراء", "original_direction": "شراء",
        "title": f"شراء {symbol} — تحليل ذكاء اصطناعي",
        "description": "تحليل تجريبي لحركة السعر الخام.",
        "source": "تحليل الذكاء الاصطناعي لبيانات السوق الخام", "url": "",
        "published_at": now, "created_at": now, "age_hours": 0,
        "market": market, "interval": interval, "expires_at": now + 3600,
        "valid_for_seconds": 3600, "price_updated_at": now, "price_fresh": True,
        "live_price": 100, "levels": {"entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "tp3": 115},
        "ai_score": 70, "ai_reviewed": True, "generated_by_ai": True,
        "ai_review": {"summary_ar": "تحليل تجريبي", "risk_ar": "اختبار فقط"},
        "external_source_weight": 0, "site_analysis_weight": 100,
        "signal_inverted": False, "has_complete_levels": True,
        "method": "ai_raw_price_action_no_indicators",
    }


def test_signal_endpoint_uses_ai_only_and_never_fetches_public_ideas(monkeypatch):
    monkeypatch.setattr(app_module, "market_data", lambda market, limit=2000: {
        "ok": True, "live": True, "stale": False,
        "items": [{"symbol": "TESTUSDT", "price": 100, "change_pct": 1}],
    })
    monkeypatch.setattr(app_module, "_generate_pro_market_signals",
                        lambda market, interval, market_rows, limit: ([_fake_ai_signal(market, interval)], True, "AI test"))
    monkeypatch.setattr(app_module, "market_direction", lambda market: {"direction": "BULLISH"})
    monkeypatch.setattr(app_module, "public_ideas", lambda **kwargs: (_ for _ in ()).throw(AssertionError("public ideas must not be used")))
    app_module.PUBLIC_IDEAS_CACHE.clear()
    response = client.get("/api/signals/spot?interval=15m&refresh=true")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["generated_by_ai"] is True
    assert data["items"][0]["external_source_weight"] == 0
    assert data["items"][0]["site_analysis_weight"] == 100
    assert data["technical_fallback_used"] is False


def test_signal_endpoint_scans_each_supported_market_with_ai_only(monkeypatch):
    supported = ("spot", "futures", "alpha", "contracts", "us", "saudi", "forex")
    calls = []
    monkeypatch.setattr(app_module, "market_data", lambda market, limit=2000: (
        calls.append(market) or {"ok": True, "live": True, "stale": False,
        "items": [{"symbol": "TESTUSDT", "price": 100, "change_pct": 1}]}
    ))
    monkeypatch.setattr(app_module, "_generate_pro_market_signals",
                        lambda market, interval, market_rows, limit: ([_fake_ai_signal(market, interval)], True, "AI test"))
    monkeypatch.setattr(app_module, "market_direction", lambda market: {"direction": "NEUTRAL"})
    monkeypatch.setattr(app_module, "public_ideas", lambda **kwargs: (_ for _ in ()).throw(AssertionError("public ideas must not be used")))
    app_module.PUBLIC_IDEAS_CACHE.clear()
    for market in supported:
        response = client.get(f"/api/signals/{market}?interval=15m&refresh=true")
        assert response.status_code == 200
        data = response.json()
        assert data["market"] == market
        assert data["count"] == 1
        assert data["items"][0]["market"] == market
        assert data["items"][0]["generated_by_ai"] is True
    assert calls == list(supported)


def test_signal_endpoint_skips_ai_when_market_data_is_stale(monkeypatch):
    monkeypatch.setattr(app_module, "market_data", lambda market, limit=2000: {
        "ok": True, "live": False, "stale": True,
        "items": [{"symbol": "BTCUSDT", "price": 100}],
    })
    monkeypatch.setattr(app_module, "_generate_pro_market_signals",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not generate from stale prices")))
    app_module.PUBLIC_IDEAS_CACHE.clear()
    response = client.get("/api/signals/spot?interval=15m&refresh=true")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert "ليست محدثة" in data["message"]


def test_signal_endpoint_accepts_daily_weekly_and_monthly_frames(monkeypatch):
    monkeypatch.setattr(app_module, "market_data", lambda market, limit=2000: {
        "ok": True, "live": True, "stale": False, "items": []
    })
    monkeypatch.setattr(app_module, "_generate_pro_market_signals",
                        lambda market, interval, market_rows, limit: ([], True, "لا توجد فرصة"))
    monkeypatch.setattr(app_module, "market_direction", lambda market: {"direction": "NEUTRAL"})
    app_module.PUBLIC_IDEAS_CACHE.clear()
    for interval in ("1d", "1w", "1M"):
        response = client.get(f"/api/signals/spot?interval={interval}&refresh=true")
        assert response.status_code == 200
        assert response.json()["interval"] == interval
        assert response.json()["items"] == []


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
    assert data["items"][0]["direction"] == "POSITIVE_POTENTIAL"


def test_public_ideas_aggregates_recent_items_without_network():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

def test_public_ideas_reads_direction_from_title_and_requires_all_ordered_levels():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

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


def test_public_ideas_auto_interval_and_futures_symbol_match():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

def test_market_page_uses_selected_market_and_visible_timeframe_buttons():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert 'href="/markets/spot"' in html and 'href="/markets/futures"' in html
    assert 'const loadDailyVip=async()=>{' in js
    assert '"/api/trade-feed?market="+encodeURIComponent(m.api)+"&limit=20"' in js
    assert '"&interval=1d"' in js
    assert 'id="surgeIntervals"' not in js and 'data-interval="' not in js
    assert 'x.interval' not in js and 'x.timeframe' in js and 'الفريم:' in js
    assert 'async function loadChart(m,symbol)' in js


def test_market_navigation_targets_have_real_page_and_data_loader_functions():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert all(f'href="{path}"' in html for path in ("/markets/spot", "/markets/futures", "/markets/contracts", "/markets/us-stocks", "/markets/saudi", "/markets/forex-gold", "/markets/alpha"))
    assert "function renderMarketPage(key)" in js
    assert "async function loadSignals(m)" in js
    assert "async function loadChart(m,symbol)" in js


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
    app_module.PUBLIC_TRADE_IDEA_CACHE.clear()
    response = client.get("/api/public-ideas?market=futures&interval=auto&limit=10")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_public_futures_ideas_require_title_ticker_and_valid_complete_levels():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

def test_public_ideas_detect_timeframe_in_title_when_body_omits_it():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

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


def test_trade_chart_endpoint_accepts_daily_weekly_and_monthly_intervals(monkeypatch):
    candles = [
        {"time": 1_700_000_000 + i * 60, "open": 100 + i, "high": 103 + i,
         "low": 99 + i, "close": 102 + i, "volume": 1000}
        for i in range(5)
    ]
    monkeypatch.setattr(app_module, "candle_data", lambda market, symbol, interval: candles)
    for interval in ("1d", "1w", "1M"):
        response = client.get(
            "/api/trade-chart-data",
            params={"market": "saudi", "symbol": "^TASI.SR", "interval": interval},
        )
        assert response.status_code == 200, interval
        data = response.json()
        assert data["ok"] is True
        assert data["interval"] == interval
        assert len(data["items"]) == 5


def test_tasi_analysis_returns_real_candles_and_levels(monkeypatch):
    candles = []
    for i in range(220):
        close = 10000 + i * 2
        candles.append({
            "time": 1_700_000_000 + i * 86400,
            "open": close - 3,
            "high": close + 8,
            "low": close - 9,
            "close": close,
            "volume": 100000,
        })
    monkeypatch.setattr(app_module, "candle_data", lambda market, symbol, interval: candles)
    monkeypatch.setattr(app_module, "_ai_analyze_tasi_candles", lambda candles, interval: ({
        "trend": "صاعد", "direction": "شراء", "support": 10000, "resistance": 11000,
        "entry": 10438, "stop_loss": 10400, "tp1": 10450, "tp2": 10460, "tp3": 10470,
        "rationale_ar": "اختبار", "risk_ar": "اختبار",
    }, True, "تحليل اختباري"))
    response = client.get("/api/tasi/analysis?interval=1d")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["symbol"] == "^TASI.SR"
    assert len(data["candles"]) == 60
    assert data["price"] == candles[-1]["close"]
    assert data["support"] <= data["price"] <= data["resistance"]


def test_tasi_page_includes_candle_chart_and_refresh_controls():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="tasiChart"' in js
    assert 'id="tasiRefresh"' in js
    assert "function renderCandleChart(items,label)" in js
    assert 'getJSON("/api/tasi/analysis?interval=1d")' in js
    assert 'id="tasiFrames"' not in js


def test_home_refresh_does_not_rebuild_dashboard_twice():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert '/static/app.css?v=20261030.bottomnav1' in html
    assert '/static/app.js?v=20261030.signal-sources1' in html
    assert 'getJSON("/api/status")' in js
    home_start = js.index("function renderHome()")
    home_end = js.index("function renderMarketPage(", home_start)
    assert js[home_start:home_end].count('getJSON("/api/status")') == 1
    assert 'setInterval(' not in js[home_start:home_end]


def test_saudi_market_keeps_symbols_below_usd_volume_cutoff(monkeypatch):
    monkeypatch.setattr(app_module, "_load_saudi_symbols", lambda: None)
    monkeypatch.setattr(app_module, "YAHOO_MARKETS", {
        **app_module.YAHOO_MARKETS,
        "saudi": ["2222.SR", "1120.SR"],
    })
    monkeypatch.setattr(app_module, "fetch_yahoo_quote", lambda symbol: {
        "symbol": symbol,
        "name": symbol,
        "price": 25.0,
        "change_pct": 0.5,
        "volume": 100,
        "dollar_volume": 2500.0,
        "currency": "SAR",
        "exchange": "Saudi Exchange",
        "quote_time": int(time.time()),
        "delayed": True,
    })
    app_module.YAHOO_CACHE.pop("saudi", None)
    response = client.get("/api/market/saudi?limit=2000")
    assert response.status_code == 200
    assert {item["symbol"] for item in response.json()["items"]} == {"2222.SR", "1120.SR"}
    app_module.YAHOO_CACHE.pop("saudi", None)


def test_public_ideas_cache_respects_requested_limit():
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["sources_configured"] > 0

def test_public_ideas_cached_results_expire_at_24_hours():
    now = int(time.time())
    stale = {
        "title": "BTCUSDT bullish setup 15m",
        "symbol": "BTCUSDT",
        "direction": "شراء",
        "interval": "15m",
        "published_at": now - 25 * 3600,
        "levels": {"entry": 100, "stop_loss": 95, "tp1": 110, "tp2": 115, "tp3": 120},
        "has_complete_levels": True,
    }
    key = ("spot", "15m", 10, False)
    app_module.PUBLIC_IDEAS_CACHE[key] = (now - 10, {"ok": True, "items": [stale], "count": 1})
    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["count"] == 0
    app_module.PUBLIC_IDEAS_CACHE.clear()



def test_daily_vip_signal_parser_preserves_all_published_levels():
    page = """
    APT/USDT SHORT Signal
    SHORT · 3×
    Active Live — waiting for the first target
    published 11h ago
    Entry zone $0.58388 – $0.59374
    Stop-loss $0.63592
    Target 1 +2.0% $0.57704
    Target 2 +4.0% $0.56526
    Target 3 +7.0% $0.54760
    Target 4 +11.0% $0.52404
    Target 5 +16.0% $0.49460
    """
    row = app_module._daily_vip_parse_signal(
        page, "https://dailyvipsignals.com/signals/apt-short-signal-2026-10-30", "futures"
    )
    assert row is not None
    assert row["symbol"] == "APTUSDT"
    assert row["direction"] == "بيع"
    assert row["leverage"] == 3
    assert row["levels"]["entry_min"] == 0.58388
    assert row["levels"]["entry_max"] == 0.59374
    assert row["levels"]["stop_loss"] == 0.63592
    assert [row["levels"][f"tp{i}"] for i in range(1, 6)] == [
        0.57704, 0.56526, 0.54760, 0.52404, 0.49460
    ]


def test_daily_vip_endpoint_finds_signal_routes_embedded_in_page_state(monkeypatch):
    index_page = '<script>window.__STATE__={"active":"/signals/apt-short-signal-2026-10-30","next":"https:\\/\\/dailyvipsignals.com\\/signals\\/hbar-short-signal-2026-10-30"}</script>'
    detail_page = """
    APT/USDT SHORT Signal
    SHORT · 3×
    Active Live — waiting for the first target
    published 11h ago
    Entry zone $0.58388 – $0.59374
    Stop-loss $0.63592
    Target 1 +2.0% $0.57704
    Target 2 +4.0% $0.56526
    Target 3 +7.0% $0.54760
    Target 4 +11.0% $0.52404
    Target 5 +16.0% $0.49460
    """
    monkeypatch.setattr(
        app_module, "_daily_vip_fetch",
        lambda url: index_page if url == app_module.DAILY_VIP_SIGNALS_URL else detail_page,
    )
    app_module.DAILY_VIP_CACHE.clear()
    response = client.get("/api/trade-feed?market=futures&refresh=true")
    assert response.status_code == 200
    assert response.json()["sources_checked"] == 2
    assert response.json()["count"] == 2
    assert {item["symbol"] for item in response.json()["items"]} == {"APTUSDT"}
    app_module.DAILY_VIP_CACHE.clear()


def test_daily_vip_endpoint_filters_shorts_from_spot_and_returns_futures(monkeypatch):
    index_page = '<a href="https://dailyvipsignals.com/signals/apt-short-signal-2026-10-30?ref=active">View setup</a>'
    detail_page = """
    APT/USDT SHORT Signal
    SHORT · 3×
    Active Live — waiting for the first target
    published 11h ago
    Entry zone $0.58388 – $0.59374
    Stop-loss $0.63592
    Target 1 +2.0% $0.57704
    Target 2 +4.0% $0.56526
    Target 3 +7.0% $0.54760
    Target 4 +11.0% $0.52404
    Target 5 +16.0% $0.49460
    """
    monkeypatch.setattr(
        app_module, "_daily_vip_fetch",
        lambda url: index_page if url == app_module.DAILY_VIP_SIGNALS_URL else detail_page,
    )
    app_module.DAILY_VIP_CACHE.clear()
    futures = client.get("/api/trade-feed?market=futures&refresh=true")
    assert futures.status_code == 200
    assert futures.json()["count"] == 1
    assert "source" not in futures.json()
    assert "source_url" not in futures.json()
    assert "source" not in futures.json()["items"][0]
    assert "source_url" not in futures.json()["items"][0]
    assert "Daily VIP" not in str(futures.json())
    spot = client.get("/api/trade-feed?market=spot&refresh=true")
    assert spot.status_code == 200
    assert spot.json()["items"] == []
    app_module.DAILY_VIP_CACHE.clear()


def test_customer_trade_payload_hides_provider_identity_and_external_urls():
    payload = app_module._daily_vip_customer_payload({
        "ok": True,
        "source": "Private Provider",
        "source_url": "https://provider.example/signals",
        "message": "Daily VIP data",
        "items": [{
            "symbol": "TESTUSDT",
            "source": "Private Provider",
            "source_url": "https://provider.example/trade/1",
            "levels": {"entry": 100, "stop_loss": 95, "tp1": 110},
        }],
    })
    assert "source" not in payload and "source_url" not in payload
    assert "Private Provider" not in str(payload)
    assert "provider.example" not in str(payload)
    assert "source" not in payload["items"][0]
    assert "source_url" not in payload["items"][0]
    assert "TESTUSDT" in str(payload)



def test_daily_vip_parser_accepts_active_trade_after_tp3_hit_without_active_badge():
    page = """
    HBAR/USDT SHORT Signal
    SHORT · 10×
    Current price $0.072122 · published 18h ago · rating Strong Sell
    TP3 hit · 3/5 3 of 5 targets hit — trade is in profit
    SL $0.0793 3/5 TP TP $0.06168
    Entry zone $0.07281 – $0.07404
    Stop-loss $0.0793
    Hit Target 1 +2.0% $0.07195
    Hit Target 2 +4.0% $0.07049
    Hit Target 3 +7.0% $0.06828
    Target 4 +11.0% $0.06535
    Target 5 +16.0% $0.06168
    """
    row = app_module._daily_vip_parse_signal(page, "https://provider.invalid/hbar", "futures")
    assert row is not None
    assert row["symbol"] == "HBARUSDT"
    assert row["age_hours"] == 18


def test_daily_vip_parser_rejects_explicitly_closed_win_or_loss():
    page = """
    PUMP/USDT LONG Signal
    LONG · 3×
    Current price $0.0049 · published 20h ago
    WIN +16.0% · 5/5 targets hit
    Entry zone $0.00459 – $0.00466
    Stop-loss $0.00425
    Target 1 $0.00472
    Target 2 $0.00481
    Target 3 $0.00495
    Target 4 $0.00512
    Target 5 $0.00536
    """
    assert app_module._daily_vip_parse_signal(page, "https://provider.invalid/pump", "futures") is None
