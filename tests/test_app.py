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


def test_news_and_tasi_analysis_pages_require_market_pin():
    anonymous = TestClient(app, base_url="https://testserver")
    for path in ("/news", "/tasi-analysis"):
        response = anonymous.get(path)
        assert response.status_code == 200
        assert "أدخل الرقم السري للمتابعة" in response.text
    api_response = anonymous.get("/api/news?market=spot")
    assert api_response.status_code == 401


def test_market_pin_session_lasts_seven_days():
    anonymous = TestClient(app, base_url="https://testserver")
    response = anonymous.post("/market-unlock", json={"pin": os.getenv("MARKET_ACCESS_PASSWORD") or os.getenv("SITE_PASSWORD", "2341")})
    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert "max-age=604800" in cookie.lower()
    assert "httponly" in cookie.lower()
    assert "secure" in cookie.lower()


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
    monkeypatch.setattr(app_module, "_ai_generate_market_signals",
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
    monkeypatch.setattr(app_module, "_ai_generate_market_signals",
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
    monkeypatch.setattr(app_module, "_ai_generate_market_signals",
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
    monkeypatch.setattr(app_module, "_ai_generate_market_signals",
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



def test_public_ideas_reads_direction_from_title_and_requires_all_ordered_levels(monkeypatch):
    now = int(time.time())
    fake = [
        {
            "source": "Test public feed",
            "title": "BTCUSDT BUY idea 15m",
            "description": "Entry 100, SL 95, TP1 110, TP2 115, TP3 120",
            "url": "https://example.com/title-buy",
            "published_at": now,
            "_text": "Entry 100, SL 95, TP1 110, TP2 115, TP3 120",
        },
        {
            "source": "Test public feed",
            "title": "ETHUSDT BUY idea 15m",
            "description": "Entry 100, SL 95, TP1 110, TP2 115",
            "url": "https://example.com/incomplete-levels",
            "published_at": now,
            "_text": "Entry 100, SL 95, TP1 110, TP2 115",
        },
    ]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    monkeypatch.setattr(app_module, "_fetch_telegram_public_channel", lambda channel: [])
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()

    response = client.get("/api/public-ideas?market=spot&interval=15m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert {item["symbol"] for item in data["items"]} == {"BTCUSDT", "ETHUSDT"}
    assert all(item["direction"] == "شراء" for item in data["items"])
    assert data["diagnostics"]["levels_missing_tp3"] >= 1
    incomplete = next(item for item in data["items"] if item["symbol"] == "ETHUSDT")
    assert incomplete["has_complete_levels"] is False

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


def test_market_page_uses_selected_market_and_visible_timeframe_buttons():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert 'href="/markets/spot"' in html and 'href="/markets/futures"' in html
    assert 'async function loadSignals(m)' in js
    assert '"/api/signals/"+encodeURIComponent(m.api)+"?interval="+encodeURIComponent(frame)+"&limit=20"' in js
    assert '"/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(x.symbol)+"&interval="+encodeURIComponent(selectedInterval)' in js
    assert 'data-frame="' in js and '"15m","1h","4h","1d","1w","1M"' in js
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
    assert 'getJSON("/api/tasi/analysis?interval="+encodeURIComponent(frame))' in js


def test_home_refresh_does_not_rebuild_dashboard_twice():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert '/static/app.css?v=20261021.1' in html
    assert '/static/app.js?v=20261022.1' in html
    assert 'getJSON("/api/status")' in js
    home_start = js.index("function renderHome()")
    home_end = js.index("function renderMarketPage(", home_start)
    assert 'if($("homeMarketDashboard"))return;' in js[home_start:home_end]
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


def test_public_ideas_cache_respects_requested_limit(monkeypatch):
    now = int(time.time())
    levels = "Entry 100 SL 95 TP1 110 TP2 115 TP3 120"
    fake = [
        {
            "source": "Test public feed",
            "title": f"BTCUSDT bullish setup 15m idea {index}",
            "description": levels,
            "url": f"https://example.com/idea-{index}",
            "published_at": now - index,
            "_text": f"BTCUSDT bullish setup 15m {levels}",
        }
        for index in range(3)
    ]
    monkeypatch.setattr(app_module, "_fetch_public_idea_feed", lambda source, url: fake)
    app_module.PUBLIC_IDEAS_CACHE.clear()
    app_module.PUBLIC_TRADE_FEED_CACHE.clear()

    one = client.get("/api/public-ideas?market=spot&interval=15m&limit=1").json()
    many = client.get("/api/public-ideas?market=spot&interval=15m&limit=10").json()
    assert len(one["items"]) == 1
    assert len(many["items"]) == 3


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
