import json
import os
import time
import secrets
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from fastapi import FastAPI, Query, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
app = FastAPI(title="التداول الذكي PRO", version="2.1.3")
security = HTTPBasic(auto_error=False)
DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/smart-trading-pro-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = DATA_DIR / "results.json"
ARTICLES_PATH = DATA_DIR / "articles.json"
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

BINANCE = {
    "spot": "https://api.binance.com/api/v3/ticker/24hr",
    "futures": "https://fapi.binance.com/fapi/v1/ticker/24hr",
}
KLINES = {
    "spot": "https://api.binance.com/api/v3/klines",
    "futures": "https://fapi.binance.com/fapi/v1/klines",
}
# Public Yahoo Finance quote universe for markets that do not use Binance.
# Quotes are last available exchange quotes and may be delayed; never fabricate prices.
YAHOO_MARKETS = {
    "us": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK-B", "JPM", "LLY", "WMT", "XOM", "AMD", "NFLX", "COST", "ORCL", "PLTR", "COIN", "INTC"],
    "saudi": ["2222.SR", "1120.SR", "2010.SR", "1180.SR", "7010.SR", "1211.SR", "2380.SR", "1150.SR", "2280.SR", "4001.SR", "2082.SR", "2223.SR", "4200.SR", "7203.SR"],
    "contracts": ["ES=F", "NQ=F", "YM=F", "RTY=F", "GC=F", "SI=F", "CL=F", "NG=F"],
    "forex": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X", "EURGBP=X", "XAUUSD=X", "XAGUSD=X"],
}
YAHOO_LABELS = {
    "ES=F": "S&P 500 Futures", "NQ=F": "Nasdaq 100 Futures", "YM=F": "Dow Futures", "RTY=F": "Russell 2000 Futures",
    "GC=F": "Gold Futures", "SI=F": "Silver Futures", "CL=F": "WTI Crude Oil Futures", "NG=F": "Natural Gas Futures",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF", "NZDUSD=X": "NZD/USD", "EURGBP=X": "EUR/GBP",
    "XAUUSD=X": "Gold Spot", "XAGUSD=X": "Silver Spot",
}
YAHOO_CACHE = {}
YAHOO_CACHE_TTL = 45
CACHE = {}
CACHE_TTL = 20
TECH_CACHE = {}
TECH_CACHE_TTL = 90
STABLES = {"USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP", "USDE", "USD1", "USDD", "USTC", "EUR", "EURC"}
INTERVALS = {"15m", "1h", "4h", "1d", "1w", "1M"}
HIGHER_INTERVAL = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w", "1w": "1M", "1M": "1M"}


def fetch_json(url: str, timeout: int = 8):
    """Fetch JSON with ordered standby hosts for the public market-data providers."""
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    fallback_hosts = {
        # Binance spot REST aliases / public market-data host.
        "api.binance.com": ["api1.binance.com", "api2.binance.com", "api3.binance.com", "api-gcp.binance.com", "data-api.binance.vision"],
        "api1.binance.com": ["api.binance.com", "api2.binance.com", "api3.binance.com", "api-gcp.binance.com", "data-api.binance.vision"],
        "api2.binance.com": ["api.binance.com", "api1.binance.com", "api3.binance.com", "api-gcp.binance.com", "data-api.binance.vision"],
        "api3.binance.com": ["api.binance.com", "api1.binance.com", "api2.binance.com", "api-gcp.binance.com", "data-api.binance.vision"],
        "api-gcp.binance.com": ["api.binance.com", "api1.binance.com", "api2.binance.com", "api3.binance.com", "data-api.binance.vision"],
        "data-api.binance.vision": ["api.binance.com", "api1.binance.com", "api2.binance.com", "api3.binance.com", "api-gcp.binance.com"],
        # Binance USD-M futures hosts.
        "fapi.binance.com": ["fapi1.binance.com", "fapi2.binance.com", "fapi3.binance.com"],
        "fapi1.binance.com": ["fapi.binance.com", "fapi2.binance.com", "fapi3.binance.com"],
        "fapi2.binance.com": ["fapi.binance.com", "fapi1.binance.com", "fapi3.binance.com"],
        "fapi3.binance.com": ["fapi.binance.com", "fapi1.binance.com", "fapi2.binance.com"],
        # Yahoo Finance public chart endpoints.
        "query1.finance.yahoo.com": ["query2.finance.yahoo.com", "query3.finance.yahoo.com", "query4.finance.yahoo.com"],
        "query2.finance.yahoo.com": ["query1.finance.yahoo.com", "query3.finance.yahoo.com", "query4.finance.yahoo.com"],
        "query3.finance.yahoo.com": ["query1.finance.yahoo.com", "query2.finance.yahoo.com", "query4.finance.yahoo.com"],
        "query4.finance.yahoo.com": ["query1.finance.yahoo.com", "query2.finance.yahoo.com", "query3.finance.yahoo.com"],
    }
    hosts = [host] + fallback_hosts.get(host, [])
    last_error = None
    for candidate in hosts:
        candidate_url = urlunsplit((parsed.scheme, candidate, parsed.path, parsed.query, parsed.fragment))
        req = urllib.request.Request(candidate_url, headers={"User-Agent": "Mozilla/5.0 SmartTradingPro/2.2"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise urllib.error.URLError("All configured market data providers failed")


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * alpha + value * (1 - alpha)
    return value


def market_tickers(market):
    raw = fetch_json(BINANCE[market])
    rows = []
    for item in raw:
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base in STABLES:
            continue
        try:
            price = float(item.get("lastPrice") or 0)
            change = float(item.get("priceChangePercent") or 0)
            quote_volume = float(item.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0 or quote_volume < 1_000_000:
            continue
        rows.append({"symbol": symbol, "price": price, "change_pct": change, "quote_volume": quote_volume})
    rows.sort(key=lambda x: x["quote_volume"], reverse=True)
    return rows


def candle_closes(market, symbol, interval):
    from urllib.parse import urlencode
    url = KLINES[market] + "?" + urlencode({"symbol": symbol, "interval": interval, "limit": 220})
    candles = fetch_json(url, timeout=7)
    return [float(candle[4]) for candle in candles if len(candle) > 6 and int(candle[6]) < int(time.time() * 1000)]


METHOD_SLUGS = {name.lower().replace(" / ", "-").replace(" ", "-").replace("/", "-"): name for name in [
    "Price Action", "SMC", "ICT", "Order Flow", "BOS / CHOCH", "Liquidity Sweep", "FVG / Imbalance", "Retest", "VSA", "Market Regime", "Dow / MTF", "Support / Resistance", "Momentum", "Candlestick Analysis", "Chart Patterns", "Classical Analysis", "Order Blocks", "Breakout Strategy", "Trend Following", "Mean Reversion", "Range Trading", "Volume Profile", "VWAP", "Indicators", "Divergence", "Fibonacci", "Ichimoku", "Wyckoff", "Elliott Wave", "Harmonic Patterns", "Channels / Trendlines", "Quant / Statistical", "Gann", "Risk Management"
]}


@app.get("/analysis/{slug}", response_class=HTMLResponse)
def standalone_method_page(slug: str):
    method = METHOD_SLUGS.get(slug.lower())
    if not method:
        return HTMLResponse("<h1>المنهج غير موجود</h1><a href='/'>العودة للموقع</a>", status_code=404)
    page = BASE / "static" / "method.html"
    html = page.read_text(encoding="utf-8").replace("__METHOD_NAME_JSON__", json.dumps(method, ensure_ascii=False)).replace("__METHOD_NAME__", method).replace("__METHOD_SLUG__", slug).replace("__METHOD_CANONICAL__", SEO_BASE_URL + "/analysis/" + slug)
    return HTMLResponse(html)



SEO_BASE_URL = "https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run"
SEO_POSTS = [
    {"slug":"risk-management-stop-loss","category":"إدارة المخاطر","title":"كيف تحدد وقف الخسارة قبل الدخول؟","description":"خطوات عملية لتحديد نقطة إبطال الفكرة وحجم المركز والمخاطرة قبل فتح الصفقة.","body":"ابدأ بتحديد المستوى الذي يثبت أن فكرة التداول لم تعد صحيحة. ضع وقف الخسارة خلف هذا المستوى مع مراعاة تذبذب الأصل، ثم احسب المسافة بين الدخول والوقف. حدّد حجم المركز بحيث لا تتجاوز الخسارة المحتملة النسبة التي اخترتها من رأس المال. لا توسّع الوقف لمجرد أن الصفقة بدأت تخسر، ولا تدخل صفقة من دون نقطة إبطال واضحة."},
    {"slug":"ema50-ema200-trend-filter","category":"قراءة السوق","title":"EMA50 وEMA200: فلتر اتجاه وليس ضمان ربح","description":"كيف تستخدم المتوسطات لفهم الاتجاه مع تجنب الاعتماد عليها وحدها في اتخاذ القرار.","body":"وجود EMA50 فوق EMA200 قد يشير إلى اتجاه صاعد، لكن المتوسطات تتأخر عن السعر وقد تعطي إشارات متكررة في السوق العرضي. افحص بنية القمم والقيعان ومناطق الدعم والمقاومة وحجم التداول. اختبر القواعد على بيانات خارج فترة بناء الاستراتيجية، واحتسب الرسوم والانزلاق قبل تقييمها."},
    {"slug":"breakout-retest-price-action","category":"حركة السعر","title":"كيف تقرأ كسر القمة وإعادة الاختبار؟","description":"خطوات لتقييم الاختراق ومراقبة الإغلاق وإعادة الاختبار وتحديد نقطة إبطال الفكرة.","body":"حدد قمة واضحة اختبرها السعر أكثر من مرة. انتظر إغلاقًا واضحًا فوقها بدل الاعتماد على ذيل شمعة فقط، ثم راقب هل يعود السعر إلى المنطقة ويجد قبولًا فوقها. إذا عاد السعر وأغلق أسفل المستوى بسرعة فقد يكون الاختراق فاشلًا. اجعل وقف الخسارة عند نقطة إبطال الفكرة، ولا تعتبر أي نموذج ضمانًا للربح."},
    {"slug":"liquidity-sweep-vs-market-structure","category":"SMC والسيولة","title":"ما الفرق بين سحب السيولة وكسر البنية؟","description":"شرح تعليمي لسحب القمم والقيعان وتغير البنية والسياق المطلوب قبل اتخاذ القرار.","body":"قد يتحرك السعر فوق قمة سابقة ثم يعود أسفلها، وهذا يسمى غالبًا سحب سيولة في بعض مدارس التحليل. لكن الحركة وحدها لا تكفي. افحص موقع السعر داخل النطاق واتجاه الفريم الأعلى والإغلاق الذي يؤكد الرفض أو تحول البنية. عرّف قواعدك بوضوح واختبرها بدل الاكتفاء باسم النموذج."},
    {"slug":"risk-reward-win-rate","category":"العائد والمخاطرة","title":"كيف تقارن بين هدف الربح ووقف الخسارة؟","description":"فهم نسبة العائد إلى المخاطرة وعلاقتها بمعدل الفوز والتكاليف والنتائج الفعلية.","body":"إذا كانت المسافة إلى الهدف ضعف المسافة إلى الوقف، فالعائد النظري إلى المخاطرة 2:1 قبل الرسوم والانزلاق. لكن النتيجة تعتمد على معدل الفوز ومتوسط الربح والخسارة الفعليين وتكاليف التداول. احسب التوقع الرياضي من سجل صفقات كافٍ، وافصل بيانات التدريب عن الاختبار، ولا تعتمد على النسبة وحدها."},
    {"slug":"backtest-trading-strategy","category":"اختبار الاستراتيجيات","title":"اختبر استراتيجية التداول قبل تشغيلها","description":"قائمة عملية للاختبار خارج العينة واحتساب الرسوم والانزلاق والتراجع وعدد الصفقات.","body":"اكتب شروط الدخول والخروج بصيغة قابلة للتنفيذ من دون تفسير شخصي. اختبر فترة تاريخية لم تستخدمها لضبط القواعد، واحتسب الرسوم والانزلاق وتأخر التنفيذ. راقب أقصى تراجع وعدد الصفقات ومتوسط الربح والخسارة والأداء حسب حالة السوق. الاختبار التاريخي لا يضمن الأداء المستقبلي."}
]


def _seo_escape(value):
    from html import escape
    return escape(str(value or ""), quote=True)


def _seo_post(slug):
    for post in SEO_POSTS:
        if post["slug"] == slug:
            return post
    for post in read_json_file(ARTICLES_PATH, []):
        if str(post.get("slug") or "") == slug:
            return post
        if str(post.get("id") or "") == slug:
            return {**post, "slug": slug, "description": post.get("summary") or post.get("body", "")[:180]}
    return None


@app.get("/robots.txt", response_class=HTMLResponse)
def robots_txt():
    return HTMLResponse("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nSitemap: " + SEO_BASE_URL + "/sitemap.xml", media_type="text/plain")


@app.get("/sitemap.xml", response_class=HTMLResponse)
def sitemap_xml():
    from xml.sax.saxutils import escape as xml_escape
    urls = [(SEO_BASE_URL + "/", "daily", "1.0"), (SEO_BASE_URL + "/blog", "weekly", "0.9")] + [(SEO_BASE_URL + p, "daily", "0.8") for p in ["/markets/spot", "/markets/futures", "/markets/contracts", "/markets/us-stocks", "/markets/saudi", "/markets/forex-gold", "/markets/alpha", "/radar", "/gold", "/analysis", "/results", "/news"]]
    urls.extend((SEO_BASE_URL + "/blog/" + p["slug"], "monthly", "0.7") for p in SEO_POSTS)
    urls.extend((SEO_BASE_URL + "/blog/" + str(p.get("slug") or p.get("id")), "monthly", "0.6") for p in read_json_file(ARTICLES_PATH, []) if p.get("slug") or p.get("id"))
    urls.extend((SEO_BASE_URL + "/analysis/" + slug, "monthly", "0.6") for slug in METHOD_SLUGS)
    items = "".join("<url><loc>" + xml_escape(url) + "</loc><changefreq>" + freq + "</changefreq><priority>" + priority + "</priority></url>" for url, freq, priority in urls)
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + items + "</urlset>"
    return HTMLResponse(xml, media_type="application/xml")


@app.get("/blog", response_class=HTMLResponse)
def seo_blog_index():
    from html import escape
    posts = list(SEO_POSTS)
    dynamic = read_json_file(ARTICLES_PATH, [])
    for item in dynamic:
        slug = str(item.get("slug") or item.get("id") or "")
        if slug:
            posts.insert(0, {**item, "slug": slug, "description": item.get("summary") or str(item.get("body", ""))[:180]})
    cards = "".join('<article class="post"><p class="category">' + escape(str(p.get("category", "تعليم التداول"))) + '</p><h2><a href="/blog/' + escape(str(p["slug"]), quote=True) + '">' + escape(str(p["title"])) + '</a></h2><p>' + escape(str(p.get("description") or p.get("summary") or "")) + '</p><a class="read" href="/blog/' + escape(str(p["slug"]), quote=True) + '">اقرأ المقال ←</a></article>' for p in posts)
    canonical = SEO_BASE_URL + "/blog"
    html = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مدونة التداول | تعليم التحليل الفني وإدارة المخاطر</title><meta name="description" content="مقالات عربية عملية عن التحليل الفني وحركة السعر والسيولة وإدارة المخاطر واختبار استراتيجيات التداول."><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '"><meta property="og:type" content="website"><meta property="og:locale" content="ar_SA"><meta property="og:title" content="مدونة التداول الذكي PRO"><meta property="og:description" content="تعلم قراءة السوق وإدارة المخاطر واختبار استراتيجيات التداول."><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">{"@context":"https://schema.org","@type":"Blog","name":"مدونة التداول الذكي PRO","url":"' + canonical + '","inLanguage":"ar-SA"}</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:16px/1.9 system-ui,Tahoma,Arial}main{max-width:1000px;margin:auto;padding:28px 18px}a{color:#7fb3ff;text-decoration:none}header,article{background:#111b2a;border:1px solid #29384d;border-radius:16px;padding:22px;margin:14px 0}h1{font-size:clamp(28px,5vw,42px);line-height:1.4}h2{font-size:22px;margin:4px 0}.category{color:#54ddb0;font-size:13px}.read{font-weight:800}nav a{margin-left:16px}</style></head><body><main><nav><a href="/">الرئيسية</a><a href="/blog">المدونة</a></nav><header><h1>مدونة التداول الذكي PRO</h1><p>محتوى تعليمي عربي يساعدك على فهم حركة السعر وبنية السوق والسيولة وإدارة المخاطر. المقالات تعليمية ولا تمثل توصيات استثمارية.</p></header>' + cards + '<footer><p>التداول ينطوي على مخاطر. اختبر أي استراتيجية على بيانات تاريخية وخارج العينة قبل استخدامها.</p></footer></main></body></html>'
    return HTMLResponse(html)


@app.get("/blog/{slug}", response_class=HTMLResponse)
def seo_blog_article(slug: str):
    from html import escape
    post = _seo_post(slug)
    if not post:
        return HTMLResponse("<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><title>المقال غير موجود</title><h1>المقال غير موجود</h1><a href='/blog'>العودة للمدونة</a></html>", status_code=404)
    title = str(post.get("title") or "مقال تعليمي")
    description = str(post.get("description") or post.get("summary") or str(post.get("body") or "")[:180])
    body = str(post.get("body") or post.get("summary") or "")
    canonical = SEO_BASE_URL + "/blog/" + str(post.get("slug") or slug)
    published = time.strftime("%Y-%m-%d", time.gmtime(int(post.get("published_at") or time.time())))
    article_json = json.dumps({"@context":"https://schema.org","@type":"Article","headline":title,"description":description,"datePublished":published,"dateModified":published,"inLanguage":"ar-SA","mainEntityOfPage":canonical,"author":{"@type":"Organization","name":"التداول الذكي PRO"},"publisher":{"@type":"Organization","name":"التداول الذكي PRO"}}, ensure_ascii=False).replace("</", "<\\/")
    paragraphs = "".join("<p>" + escape(p.strip()) + "</p>" for p in body.splitlines() if p.strip()) or "<p>" + escape(body) + "</p>"
    html = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + ' | مدونة التداول الذكي PRO</title><meta name="description" content="' + escape(description[:300], quote=True) + '"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '"><meta property="og:type" content="article"><meta property="og:locale" content="ar_SA"><meta property="og:title" content="' + escape(title, quote=True) + '"><meta property="og:description" content="' + escape(description[:300], quote=True) + '"><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">' + article_json + '</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:17px/2 system-ui,Tahoma,Arial}main{max-width:820px;margin:auto;padding:28px 18px}a{color:#7fb3ff;text-decoration:none}.crumb{font-size:13px;color:#93a0b3}article{background:#111b2a;border:1px solid #29384d;border-radius:18px;padding:clamp(20px,5vw,42px);margin-top:18px}.category{color:#54ddb0;font-size:13px;font-weight:800}h1{font-size:clamp(28px,5vw,42px);line-height:1.4}p{margin:18px 0}footer{color:#93a0b3;font-size:13px;margin-top:24px}</style></head><body><main><p class="crumb"><a href="/">الرئيسية</a> / <a href="/blog">المدونة</a> / ' + escape(title) + '</p><article><p class="category">' + escape(str(post.get("category") or "تعليم التداول")) + '</p><h1>' + escape(title) + '</h1><p>' + escape(description) + '</p>' + paragraphs + '<p><strong>تنبيه:</strong> هذا محتوى تعليمي، وليس توصية شراء أو بيع أو ضمانًا للربح.</p></article><footer><a href="/blog">← جميع المقالات</a></footer></main></body></html>'
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
def home():
    page = BASE / "static" / "index.html"
    html = page.read_text(encoding="utf-8")
    # Keep the interactive technical filter separate from the main page markup.
    if 'src="/static/technical.js"' not in html:
        html = html.replace("</body>", '<script src="/static/technical.js?v=2.1"></script></body>')
    return HTMLResponse(html)




# Serve the same app shell at stable, section-specific URLs so each page can be bookmarked/shared.
@app.get("/analysis", response_class=HTMLResponse)
@app.get("/markets/spot", response_class=HTMLResponse)
@app.get("/markets/futures", response_class=HTMLResponse)
@app.get("/markets/contracts", response_class=HTMLResponse)
@app.get("/markets/us-stocks", response_class=HTMLResponse)
@app.get("/markets/saudi", response_class=HTMLResponse)
@app.get("/markets/forex-gold", response_class=HTMLResponse)
@app.get("/markets/alpha", response_class=HTMLResponse)
@app.get("/radar", response_class=HTMLResponse)
@app.get("/gold", response_class=HTMLResponse)
@app.get("/results", response_class=HTMLResponse)
@app.get("/news", response_class=HTMLResponse)
@app.get("/account", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
def section_page(request: Request):
    page = BASE / "static" / "index.html"
    html = page.read_text(encoding="utf-8")
    if 'src="/static/technical.js"' not in html:
        html = html.replace("</body>", '<script src="/static/technical.js?v=2.1"></script></body>')

    # Give each shareable section its own canonical URL and search snippet.
    # The SPA shell is shared, but search engines must not see every section as "/".
    section_seo = {
        "/analysis": ("مناهج التحليل الفني | التداول الذكي PRO", "مكتبة مناهج التحليل الفني: حركة السعر، SMC، ICT، السيولة، النماذج، وإدارة المخاطر."),
        "/markets/spot": ("سوق السبوت | التداول الذكي PRO", "متابعة أسعار Binance Spot وفرص السوق حسب الفريم، مع توضيح أن الإشارات آلية أولية وليست ضمانًا للربح."),
        "/markets/futures": ("سوق الفيوتشر | التداول الذكي PRO", "متابعة أسعار Binance Futures وفرص العقود ببيانات السوق العامة، مع إدارة المخاطر ووقف الخسارة."),
        "/markets/contracts": ("العقود الأمريكية | التداول الذكي PRO", "متابعة العقود الأمريكية مثل S&P 500 وناسداك والذهب والنفط من أسعار عامة قد تكون متأخرة."),
        "/markets/us-stocks": ("الأسهم الأمريكية | التداول الذكي PRO", "متابعة مجموعة من الأسهم الأمريكية وأسعارها العامة؛ قد تكون البيانات متأخرة وليست أسعار تنفيذ."),
        "/markets/saudi": ("السوق السعودي | التداول الذكي PRO", "متابعة مجموعة من الأسهم السعودية وأسعارها العامة مع تنبيه إلى توقيت البيانات ومخاطر التداول."),
        "/markets/forex-gold": ("الفوركس والذهب | التداول الذكي PRO", "متابعة أزواج الفوركس والذهب والفضة من أسعار عامة قد تكون متأخرة."),
        "/markets/alpha": ("سوق Binance Alpha | التداول الذكي PRO", "حالة تغطية سوق Binance Alpha ومصادر البيانات المتاحة؛ لا تعرض المنصة أسعارًا غير متصلة أو تقديرية."),
        "/radar": ("رادار الأسواق | التداول الذكي PRO", "رصد الأسواق وفرص التحليل الفني عبر صفحات مستقلة، مع بيانات عامة وحدود واضحة لدقة الإشارات."),
        "/gold": ("الصفقات الذهبية | التداول الذكي PRO", "صفقات مرتبة وفق معايير الفحص المتاحة، مع الدخول والأهداف ووقف الخسارة عند توفر إشارة صالحة."),
        "/results": ("نتائج الإشارات | التداول الذكي PRO", "متابعة سجل نتائج الإشارات التي رصدتها الخدمة؛ النتائج السابقة لا تضمن الأداء المستقبلي."),
        "/news": ("أخبار الأسواق | التداول الذكي PRO", "متابعة أخبار الأسواق ومعلوماتها العامة لدعم فهم السياق، وليست الأخبار وحدها توصية تداول."),
        "/account": ("الحساب | التداول الذكي PRO", "صفحة الحساب في التداول الذكي PRO. قد لا تكون حسابات العملاء مفعلة في النسخة الحالية.")
    }
    path = request.url.path.rstrip("/") or "/"
    title, description = section_seo.get(path, ("التداول الذكي PRO | رادار وفرص الأسواق", "منصة عربية لمتابعة الأسواق والتحليل والنتائج والأخبار والمدونة التعليمية."))
    canonical = SEO_BASE_URL + path
    html = html.replace(
        '<title>التداول الذكي PRO | رادار وفرص الأسواق</title>',
        '<title>' + _seo_escape(title) + '</title>'
    )
    html = html.replace(
        '<meta name="description" content="منصة عربية لمتابعة فرص الأسواق وتحليلها حسب الفريم، مع صفقات وأهداف ووقف خسارة ونتائج وأخبار ومدونة تعليمية.">',
        '<meta name="description" content="' + _seo_escape(description) + '">'
    )
    html = html.replace(
        '<link rel="canonical" href="' + SEO_BASE_URL + '/">',
        '<link rel="canonical" href="' + _seo_escape(canonical) + '">'
    )
    html = html.replace(
        '<meta property="og:title" content="التداول الذكي PRO">',
        '<meta property="og:title" content="' + _seo_escape(title) + '">'
    )
    html = html.replace(
        '<meta property="og:description" content="رادار الأسواق والفرص الفنية والتحليل والنتائج والأخبار.">',
        '<meta property="og:description" content="' + _seo_escape(description) + '">'
    )
    if 'property="og:url"' not in html:
        html = html.replace("</head>", '<meta property="og:url" content="' + _seo_escape(canonical) + '"></head>')
    return HTMLResponse(html)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "service": "smart-trading-pro", "version": "2.1.3", "timestamp": int(time.time())}


def fetch_yahoo_quote(symbol: str):
    """Fetch one public Yahoo Finance quote; source may be delayed."""
    try:
        from urllib.parse import quote
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?range=5d&interval=1d"
        chart = fetch_json(url, timeout=5).get("chart", {})
        rows = chart.get("result") or []
        if not rows:
            return None
        item = rows[0]
        meta = item.get("meta") or {}
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or previous in (None, 0):
            closes = (item.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
            valid = [v for v in closes if v is not None]
            if price is None and valid:
                price = valid[-1]
            if previous in (None, 0) and len(valid) >= 2:
                previous = valid[-2]
        if price is None:
            return None
        price = float(price)
        previous = float(previous) if previous is not None else price
        return {
            "symbol": symbol, "name": YAHOO_LABELS.get(symbol, symbol.replace(".SR", "")),
            "price": price,
            "change_pct": ((price - previous) / previous * 100) if previous else 0.0,
            "quote_volume": 0, "currency": meta.get("currency", ""),
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "Yahoo Finance",
            "quote_time": meta.get("regularMarketTime"), "delayed": True,
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError, KeyError):
        return None


@app.get("/api/market/{market}")
def market_data(market: str, limit: int = Query(40, ge=1, le=100)):
    market = market.lower()
    if market in YAHOO_MARKETS:
        now = time.time()
        cached = YAHOO_CACHE.get(market)
        if cached and now - cached[0] < YAHOO_CACHE_TTL:
            data = cached[1]
        else:
            # Query symbols concurrently so a slow quote cannot block the whole market page.
            data = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(fetch_yahoo_quote, symbol) for symbol in YAHOO_MARKETS[market]]
                for future in as_completed(futures):
                    try:
                        item = future.result()
                    except Exception:
                        item = None
                    if item:
                        data.append(item)
            if not data:
                return JSONResponse({
                    "ok": False, "market": market, "live": False, "items": [],
                    "message": "تعذر جلب الأسعار من مزود السوق الآن. جرّب التحديث لاحقًا."
                }, status_code=503)
            data.sort(key=lambda x: x["change_pct"], reverse=True)
            YAHOO_CACHE[market] = (now, data)
        return {"ok": True, "market": market, "live": True, "provider": "Yahoo Finance",
                "delayed": True, "updated_at": int(now), "items": data[:limit],
                "message": "آخر أسعار متاحة من Yahoo Finance؛ قد تكون متأخرة وليست تنفيذًا لحظيًا مضمونًا."}
    if market not in BINANCE:
        return JSONResponse({
            "ok": True, "market": market, "live": False, "items": [],
            "message": "هذا السوق غير مربوط بمصدر بيانات حاليًا؛ لم نعرض أسعارًا تقديرية."
        })
    now = time.time()
    cached = CACHE.get(market)
    if cached and now - cached[0] < CACHE_TTL:
        data = cached[1]
    else:
        try:
            data = market_tickers(market)
            CACHE[market] = (now, data)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return JSONResponse({
                "ok": False, "market": market, "live": False, "items": [],
                "message": "تعذر جلب الأسعار المباشرة الآن. حاول التحديث بعد قليل."
            }, status_code=503)
    return {"ok": True, "market": market, "live": True, "provider": "Binance",
            "updated_at": int(now), "items": data[:limit]}


@app.get("/api/technical/{market}")
def technical_filter(market: str, interval: str = Query("15m"), limit: int = Query(40, ge=1, le=60)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفلتر الفني متاح حاليًا لسبوت وفيوتشر Binance فقط."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    cache_key = (market, interval, limit)
    now = time.time()
    cached = TECH_CACHE.get(cache_key)
    if cached and now - cached[0] < TECH_CACHE_TTL:
        return cached[1]
    try:
        tickers = market_tickers(market)[:limit]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب بيانات السوق المباشرة."}, status_code=503)

    higher = HIGHER_INTERVAL[interval]
    def analyze(ticker):
        try:
            closes, higher_closes = None, None
            closes = candle_closes(market, ticker["symbol"], interval)
            higher_closes = closes if higher == interval else candle_closes(market, ticker["symbol"], higher)
            e50, e200 = ema(closes, 50), ema(closes, 200)
            h50, h200 = ema(higher_closes, 50), ema(higher_closes, 200)
            if None in (e50, e200, h50, h200):
                return None
            eligible = ticker["price"] > e200 and e50 > e200 and h50 > h200
            return {**ticker, "ema50": e50, "ema200": e200, "higher_interval": higher,
                    "higher_ema50": h50, "higher_ema200": h200, "eligible": eligible}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError):
            return None

    analyzed = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(analyze, ticker) for ticker in tickers]
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                analyzed.append(item)
    analyzed.sort(key=lambda x: x["quote_volume"], reverse=True)
    eligible_items = [item for item in analyzed if item["eligible"]]
    result = {
        "ok": True, "live": True, "market": market, "interval": interval,
        "higher_interval": higher, "scanned": len(tickers), "analyzed": len(analyzed),
        "updated_at": int(now), "items": eligible_items,
        "message": "شرط الاتجاه: السعر فوق EMA200 وEMA50 فوق EMA200 على الفريم المختار، مع تأكيد EMA50 فوق EMA200 على الفريم الأعلى. هذا فلتر اتجاه وليس ضمان ربح."
    }
    TECH_CACHE[cache_key] = (now, result)
    return result




METHOD_RULES = {
    "Price Action": "price_action", "SMC": "smc", "ICT": "ict",
    "Order Flow": "order_flow", "BOS / CHOCH": "bos_choch",
    "Liquidity Sweep": "liquidity_sweep", "FVG / Imbalance": "fvg",
    "Retest": "retest", "VSA": "vsa", "Market Regime": "regime",
    "Dow / MTF": "dow_mtf", "Support / Resistance": "support_resistance",
    "Momentum": "momentum", "Candlestick Analysis": "candlestick",
    "Chart Patterns": "chart_patterns", "Classical Analysis": "classical",
    "Order Blocks": "order_blocks", "Breakout Strategy": "breakout",
    "Trend Following": "trend_following", "Mean Reversion": "mean_reversion",
    "Range Trading": "range_trading", "Volume Profile": "volume_profile",
    "VWAP": "vwap", "Indicators": "indicators", "Divergence": "divergence",
    "Fibonacci": "fibonacci", "Ichimoku": "ichimoku", "Wyckoff": "wyckoff",
    "Elliott Wave": "elliott", "Harmonic Patterns": "harmonic",
    "Channels / Trendlines": "channels", "Quant / Statistical": "quant",
    "Gann": "gann", "Risk Management": "risk_management"
}


def method_signal(candles, ticker, method_key):
    """Return a candidate only when this rule has a defensible directional trigger.
    These are rule-based approximations, not full implementations of discretionary methods.
    """
    if len(candles) < 30:
        return None
    c = candles
    closes = [x["close"] for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]
    volumes = [x["volume"] for x in c]
    last, prev = c[-1], c[-2]
    price = last["close"]
    if price <= 0:
        return None
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    avg_vol = sum(volumes[-21:-1]) / 20 if sum(volumes[-21:-1]) else 0
    candle_range = max(last["high"] - last["low"], 1e-12)
    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    vwap_den = sum(volumes[-20:])
    vwap = sum(x["close"] * x["volume"] for x in c[-20:]) / vwap_den if vwap_den > 0 else None
    side = None

    # Count only a directional trigger for the selected rule; do not count
    # neutral conditions (e.g. "small candle" or "low volatility") as a trade method.
    if method_key == "price_action":
        if bullish and price > prev["close"]: side = "BUY"
        elif bearish and price < prev["close"]: side = "SELL"
    elif method_key in ("smc", "ict", "bos_choch", "chart_patterns"):
        if price > prior_high: side = "BUY"
        elif price < prior_low: side = "SELL"
    elif method_key == "order_flow":
        if avg_vol > 0 and volumes[-1] >= avg_vol * 1.5:
            if bullish: side = "BUY"
            elif bearish: side = "SELL"
    elif method_key == "liquidity_sweep":
        if last["low"] < prior_low and price > prior_low: side = "BUY"
        elif last["high"] > prior_high and price < prior_high: side = "SELL"
    elif method_key == "fvg":
        if c[-3]["high"] < last["low"]: side = "BUY"
        elif c[-3]["low"] > last["high"]: side = "SELL"
    elif method_key == "retest":
        near_high = abs(price - prior_high) / price < 0.004
        near_low = abs(price - prior_low) / price < 0.004
        if near_high and price >= prior_high and bullish: side = "BUY"
        elif near_low and price <= prior_low and bearish: side = "SELL"
    elif method_key == "vsa":
        avg_range = sum(highs[-15+i] - lows[-15+i] for i in range(15)) / 15
        if avg_vol > 0 and volumes[-1] >= avg_vol * 1.5 and candle_range < avg_range * 0.8:
            if bullish: side = "BUY"
            elif bearish: side = "SELL"
    elif method_key == "regime":
        if e20 is not None and e50 is not None:
            if e20 > e50: side = "BUY"
            elif e20 < e50: side = "SELL"
    elif method_key == "dow_mtf":
        if e50 is not None:
            if price > e50: side = "BUY"
            elif price < e50: side = "SELL"
    elif method_key == "support_resistance":
        if abs(price - prior_low) / price < 0.003 and bullish: side = "BUY"
        elif abs(price - prior_high) / price < 0.003 and bearish: side = "SELL"
    elif method_key == "momentum":
        if len(closes) >= 5:
            move = (price - closes[-5]) / max(closes[-5], 1e-12)
            if move >= 0.003: side = "BUY"
            elif move <= -0.003: side = "SELL"
    elif method_key == "candlestick":
        if candle_range > 0 and abs(price - last["open"]) / candle_range >= 0.65:
            if bullish: side = "BUY"
            elif bearish: side = "SELL"
    elif method_key == "classical":
        # Classical chart analysis proxy: breakout or rejection around recent support/resistance.
        if price > prior_high and bullish: side = "BUY"
        elif price < prior_low and bearish: side = "SELL"
        elif abs(price-prior_low)/price < 0.0025 and bullish: side = "BUY"
        elif abs(price-prior_high)/price < 0.0025 and bearish: side = "SELL"
    elif method_key == "order_blocks":
        # Lightweight order-block proxy: impulsive close through the prior candle range.
        if bullish and price > prev["high"] and volumes[-1] >= max(avg_vol, 1e-12): side = "BUY"
        elif bearish and price < prev["low"] and volumes[-1] >= max(avg_vol, 1e-12): side = "SELL"
    elif method_key == "breakout":
        if price > prior_high and bullish: side = "BUY"
        elif price < prior_low and bearish: side = "SELL"
    elif method_key == "trend_following":
        if e20 is not None and e50 is not None and e200 is not None:
            if price > e20 > e50 > e200: side = "BUY"
            elif price < e20 < e50 < e200: side = "SELL"
    elif method_key == "mean_reversion":
        mean20 = sum(closes[-20:]) / 20
        if price < mean20 * 0.98 and bullish: side = "BUY"
        elif price > mean20 * 1.02 and bearish: side = "SELL"
    elif method_key == "range_trading":
        range_high, range_low = max(highs[-20:]), min(lows[-20:])
        if abs(price-range_low)/price < 0.003 and bullish: side = "BUY"
        elif abs(price-range_high)/price < 0.003 and bearish: side = "SELL"
    elif method_key == "volume_profile":
        if vwap is not None:
            if price > vwap and bullish: side = "BUY"
            elif price < vwap and bearish: side = "SELL"
    elif method_key == "vwap":
        if vwap is not None:
            if price > vwap: side = "BUY"
            elif price < vwap: side = "SELL"
    elif method_key == "indicators":
        if e20 is not None and e50 is not None:
            if price > e20 > e50: side = "BUY"
            elif price < e20 < e50: side = "SELL"
    elif method_key == "divergence":
        # A simple swing-reversal proxy; deliberately conservative.
        if len(closes) >= 9:
            if closes[-1] > closes[-5] and closes[-5] < closes[-9] and bullish: side = "BUY"
            elif closes[-1] < closes[-5] and closes[-5] > closes[-9] and bearish: side = "SELL"
    elif method_key == "fibonacci":
        lo, hi = min(lows[-30:]), max(highs[-30:])
        retrace = hi - (hi - lo) * 0.618
        if abs(price - retrace) / price < 0.01 and bullish: side = "BUY"
        elif abs(price - (lo + (hi - lo) * 0.618)) / price < 0.01 and bearish: side = "SELL"
    elif method_key == "ichimoku":
        if e20 is not None and e50 is not None:
            if price > e20 > e50: side = "BUY"
            elif price < e20 < e50: side = "SELL"
    elif method_key == "wyckoff":
        if avg_vol > 0 and volumes[-1] >= avg_vol * 1.3:
            if last["low"] < prior_low and price > prior_low: side = "BUY"
            elif last["high"] > prior_high and price < prior_high: side = "SELL"
    elif method_key == "elliott":
        if closes[-1] > closes[-2] > closes[-3] > closes[-4]: side = "BUY"
        elif closes[-1] < closes[-2] < closes[-3] < closes[-4]: side = "SELL"
    elif method_key == "harmonic":
        lo, hi = min(lows[-20:]), max(highs[-20:])
        if abs(price - (lo + (hi-lo)*0.618)) / price < 0.008 and bullish: side = "BUY"
        elif abs(price - (hi - (hi-lo)*0.618)) / price < 0.008 and bearish: side = "SELL"
    elif method_key == "channels":
        high_slope = highs[-1] - highs[-6]
        low_slope = lows[-1] - lows[-6]
        if high_slope > 0 and low_slope > 0 and bullish: side = "BUY"
        elif high_slope < 0 and low_slope < 0 and bearish: side = "SELL"
    elif method_key == "quant":
        mean20 = sum(closes[-20:]) / 20
        if price > mean20: side = "BUY"
        elif price < mean20: side = "SELL"
    elif method_key == "gann":
        if price > closes[-9] * 1.003: side = "BUY"
        elif price < closes[-9] * 0.997: side = "SELL"
    # Risk management is not a directional signal and must never inflate confluence.
    if side is None or method_key == "risk_management":
        return None

    tr = [max(c[i]["high"]-c[i]["low"], abs(c[i]["high"]-c[i-1]["close"]),
              abs(c[i]["low"]-c[i-1]["close"])) for i in range(1, len(c))]
    atr = sum(tr[-14:]) / max(1, len(tr[-14:]))
    entry = price
    risk = max(atr * 1.5, entry * 0.002)
    if side == "BUY":
        stop, tp1, tp2, tp3 = entry-risk, entry+risk, entry+2*risk, entry+3*risk
    else:
        stop, tp1, tp2, tp3 = entry+risk, entry-risk, entry-2*risk, entry-3*risk
    if stop <= 0 or min(tp1, tp2, tp3) <= 0:
        return None
    return {**ticker, "side": side, "method": method_key, "entry": entry, "stop": stop,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "stop_pct": abs(entry-stop)/entry*100, "tp1_pct": abs(tp1-entry)/entry*100,
            "score": min(95, 60 + int(min(abs(entry-prev["close"])/entry*100, 3)*8)),
            "status": "إشارة اجتازت شرط المنهج — تحقق آلي أولي", "change_pct": ticker["change_pct"]}


@app.get("/api/methods/{market}")
def method_filter(market: str, method: str = Query(...), interval: str = Query("15m"), limit: int = Query(40, ge=1, le=100)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "مصدر هذا السوق غير مربوط حاليًا."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    method_key = METHOD_RULES.get(method)
    if not method_key:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "المنهج غير معروف."}, status_code=422)
    try:
        tickers = market_tickers(market)[:limit]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب بيانات السوق المباشرة."}, status_code=503)
    def analyze(ticker):
        try:
            candles = candle_data(market, ticker["symbol"], interval)
            return method_signal(candles, ticker, method_key)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError, ZeroDivisionError):
            return None
    found = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for future in as_completed([pool.submit(analyze, t) for t in tickers]):
            item = future.result()
            if item:
                found.append(item)
    found.sort(key=lambda x: x["quote_volume"], reverse=True)
    return {"ok": True, "live": True, "market": market, "method": method, "interval": interval,
            "scanned": len(tickers), "analyzed": len(tickers), "count": len(found),
            "updated_at": int(time.time()), "items": found,
            "message": "تم فحص الشموع المباشرة وفق شرط أولي خاص بالمنهج المختار. بعض المناهج المركبة تحتاج تأكيدًا بصريًا/سياقيًا؛ النتيجة ليست ضمانًا أو توصية آلية مكتملة."}



SIGNAL_CACHE = {}
SIGNAL_CACHE_TTL = 75


def candle_data(market: str, symbol: str, interval: str):
    from urllib.parse import urlencode, quote
    if market in BINANCE:
        url = KLINES[market] + "?" + urlencode({"symbol": symbol, "interval": interval, "limit": 220})
        raw = fetch_json(url, timeout=8)
        return [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                for k in raw if len(k) > 6 and int(k[6]) < int(time.time() * 1000)]
    if market not in YAHOO_MARKETS:
        return []
    yahoo_interval = {"15m":"15m", "1h":"60m", "4h":"60m", "1d":"1d", "1w":"1wk", "1M":"1mo"}.get(interval)
    yahoo_range = {"15m":"60d", "1h":"730d", "4h":"730d", "1d":"5y", "1w":"10y", "1M":"max"}.get(interval)
    if not yahoo_interval:
        return []
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?" + urlencode({"interval": yahoo_interval, "range": yahoo_range})
    payload = fetch_json(url, timeout=9)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return []
    data = result[0]
    stamps = data.get("timestamp") or []
    q = ((data.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, stamp in enumerate(stamps):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            v = (q.get("volume") or [0] * len(stamps))[i] or 0
            if None in (o, h, l, c) or int(stamp) >= int(time.time()):
                continue
            out.append({"time": int(stamp), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)})
        except (IndexError, TypeError, ValueError):
            continue
    if interval == "4h":
        grouped = {}
        for candle in out:
            bucket = candle["time"] // 14400
            if bucket not in grouped:
                grouped[bucket] = {"time": bucket*14400, "open": candle["open"], "high": candle["high"], "low": candle["low"], "close": candle["close"], "volume": candle["volume"]}
            else:
                g = grouped[bucket]
                g["high"] = max(g["high"], candle["high"])
                g["low"] = min(g["low"], candle["low"])
                g["close"] = candle["close"]
                g["volume"] += candle["volume"]
        out = [grouped[k] for k in sorted(grouped)]
    return out[-500:]


def build_signal(market: str, ticker: dict, interval: str):
    candles = candle_data(market, ticker["symbol"], interval)
    if len(candles) < 205:
        return None
    closes = [k["close"] for k in candles]
    highs = [k["high"] for k in candles]
    lows = [k["low"] for k in candles]
    opens = [k["open"] for k in candles]
    volumes = [k["volume"] for k in candles]
    price, prev = closes[-1], closes[-2]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    if None in (e20, e50, e200) or price <= 0:
        return None
    tr = [max(candles[i]["high"]-candles[i]["low"],
              abs(candles[i]["high"]-candles[i-1]["close"]),
              abs(candles[i]["low"]-candles[i-1]["close"])) for i in range(1, len(candles))]
    atr = sum(tr[-14:]) / min(14, len(tr))
    if atr <= 0:
        return None
    prior_high, prior_low = max(highs[-21:-1]), min(lows[-21:-1])
    avg_vol = sum(volumes[-21:-1]) / max(1, len(volumes[-21:-1]))
    candle_range = max(highs[-1] - lows[-1], 1e-12)
    body = abs(closes[-1] - opens[-1])
    bullish = closes[-1] > opens[-1]
    bearish = closes[-1] < opens[-1]
    # Independent rule families: trend, structure, momentum, volume, candle shape and location.
    tests = {
        "الاتجاه EMA20/50": e20 > e50,
        "الاتجاه EMA50/200": e50 > e200,
        "السعر فوق EMA200": price > e200,
        "زخم 4 شمعات": price > closes[-5] if len(closes) >= 5 else False,
        "كسر قمة 20 شمعة": price > prior_high,
        "كسر قاع 20 شمعة": price < prior_low,
        "شمعة صاعدة": bullish,
        "شمعة هابطة": bearish,
        "حجم تداول مرتفع": avg_vol > 0 and volumes[-1] >= avg_vol * 1.5,
        "إغلاق قرب القمة": (highs[-1]-price)/candle_range < 0.2,
        "إغلاق قرب القاع": (price-lows[-1])/candle_range < 0.2,
        "قوة جسم الشمعة": body/candle_range >= 0.6,
        "سحب سيولة القاع": lows[-1] < prior_low and price > prior_low,
        "رفض قمة سابقة": highs[-1] > prior_high and price < prior_high,
        "قرب مقاومة": abs(price-prior_high)/price < 0.004,
        "قرب دعم": abs(price-prior_low)/price < 0.004,
        "فجوة سعرية صاعدة": candles[-3]["high"] < lows[-1],
        "فجوة سعرية هابطة": candles[-3]["low"] > highs[-1],
        "تتابع صاعد": closes[-1] > closes[-2] > closes[-3],
        "تتابع هابط": closes[-1] < closes[-2] < closes[-3],
        "VWAP تقريبي": price > (sum(closes[-20+i]*volumes[-20+i] for i in range(20))/max(sum(volumes[-20:]),1e-12)),
        "فوق منتصف النطاق": price > (max(highs[-50:])+min(lows[-50:]))/2,
        "تذبذب معقول": (highs[-1]-lows[-1])/price < 0.05,
    }
    bullish_points = sum([
        price > e200, e50 > e200, e20 > e50, price > closes[-5],
        price > prior_high, bullish, (highs[-1]-price)/candle_range < 0.2,
        lows[-1] < prior_low and price > prior_low,
        price > (sum(closes[-20+i]*volumes[-20+i] for i in range(20))/max(sum(volumes[-20:]),1e-12)),
        price > (max(highs[-50:])+min(lows[-50:]))/2,
    ])
    bearish_points = sum([
        price < e200, e50 < e200, e20 < e50, price < closes[-5],
        price < prior_low, bearish, (price-lows[-1])/candle_range < 0.2,
        highs[-1] > prior_high and price < prior_high,
        price < (sum(closes[-20+i]*volumes[-20+i] for i in range(20))/max(sum(volumes[-20:]),1e-12)),
        price < (max(highs[-50:])+min(lows[-50:]))/2,
    ])
    side = "BUY" if bullish_points > bearish_points else "SELL" if bearish_points > bullish_points else None
    if side is None:
        return None
    # Evaluate every named-method rule and make method confluence part of eligibility and score.
    method_hits = []
    for method_name, method_key in METHOD_RULES.items():
        try:
            method_result = method_signal(candles, ticker, method_key)
            if method_result and method_result.get("side") == side:
                method_hits.append(method_name)
        except (ValueError, TypeError, IndexError, ZeroDivisionError):
            continue
    confirmations = bullish_points if side == "BUY" else bearish_points
    directional_score = 100 * max(bullish_points, bearish_points) / 10
    method_count = len(method_hits)
    method_score = min(method_count, 10) * 10
    # A single valid method may surface a candidate; stronger confluence raises its rank.
    # Keep a small directional floor so an isolated rule is not presented as a strong trade.
    score = int(0.65 * directional_score + 0.35 * method_score)
    if score < 35 or confirmations < 3 or method_count < 1:
        return None
    entry = price
    risk = max(atr * 1.5, entry * 0.002)
    if side == "BUY":
        stop, t1, t2, t3 = entry-risk, entry+risk, entry+2*risk, entry+3*risk
    else:
        stop, t1, t2, t3 = entry+risk, entry-risk, entry-2*risk, entry-3*risk
    if min(stop, t1, t2, t3) <= 0:
        return None
    # These are rule hits, not proof that every discretionary concept is fully automated.
    if side == "BUY":
        directional = ["EMA20 فوق EMA50" if e20 > e50 else "EMA20 دون EMA50",
                        "EMA50 فوق EMA200" if e50 > e200 else "EMA50 دون EMA200",
                        "السعر فوق EMA200" if price > e200 else "السعر دون EMA200"]
        if price > prior_high: directional.append("كسر قمة 20 شمعة")
        if lows[-1] < prior_low and price > prior_low: directional.append("سحب سيولة القاع")
        if bullish: directional.append("شمعة صاعدة")
    else:
        directional = ["EMA20 دون EMA50" if e20 < e50 else "EMA20 فوق EMA50",
                        "EMA50 دون EMA200" if e50 < e200 else "EMA50 فوق EMA200",
                        "السعر دون EMA200" if price < e200 else "السعر فوق EMA200"]
        if price < prior_low: directional.append("كسر قاع 20 شمعة")
        if highs[-1] > prior_high and price < prior_high: directional.append("رفض القمة / سحب سيولة")
        if bearish: directional.append("شمعة هابطة")
    if avg_vol > 0 and volumes[-1] >= avg_vol * 1.5:
        directional.append("تأكيد حجم التداول")
    active = list(dict.fromkeys(directional + method_hits))
    return {
        "symbol": ticker["symbol"], "side": side, "market": market, "interval": interval,
        "entry": entry, "stop": stop, "tp1": t1, "tp2": t2, "tp3": t3,
        "stop_pct": abs(entry-stop)/entry*100, "tp1_pct": abs(t1-entry)/entry*100,
        "tp2_pct": abs(t2-entry)/entry*100, "tp3_pct": abs(t3-entry)/entry*100,
        "score": min(98, score), "confirmations": confirmations,
        "method_count": method_count, "importance": ("صفقة مهمة جدًا" if method_count >= 10 else "صفقة مهمة" if method_count >= 6 else "توافق متوسط" if method_count >= 3 else "إشارة أولية"),
        "methods": active, "method_hits": method_hits,
        "quote_volume": ticker.get("quote_volume", 0), "updated_at": int(time.time()),
        "method": "ترتيب حسب توافق المناهج مع اتجاه السعر",
        "status": "عدد المناهج المتوافقة يرفع ترتيب الإشارة؛ الإشارة الأولية تحتاج تحققًا إضافيًا"
    }

@app.get("/api/signals/{market}")
def signal_cards(market: str, interval: str = Query("15m"), limit: int = Query(12, ge=1, le=20)):
    market = market.lower()
    if market not in BINANCE and market not in YAHOO_MARKETS:
        return JSONResponse({"ok": False, "live": False, "items": [],
                             "message": "مصدر هذا السوق غير مربوط؛ لا يمكن إنشاء صفقات فعلية."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    key = (market, interval, limit)
    now = time.time()
    cached = SIGNAL_CACHE.get(key)
    if cached and now - cached[0] < SIGNAL_CACHE_TTL:
        return cached[1]
    try:
        if market in BINANCE:
            tickers = market_tickers(market)[:max(40, limit * 3)]
        else:
            tickers = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                for future in as_completed([pool.submit(fetch_yahoo_quote, symbol) for symbol in YAHOO_MARKETS[market]]):
                    try:
                        quote_item = future.result()
                    except Exception:
                        quote_item = None
                    if quote_item:
                        quote_item["quote_volume"] = 0
                        tickers.append(quote_item)
            tickers.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
            tickers = tickers[:max(20, limit)]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب أسعار السوق الآن."}, status_code=503)

    found = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(build_signal, market, ticker, interval) for ticker in tickers]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    found.append(item)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError, ZeroDivisionError):
                continue
    found.sort(key=lambda x: (x.get("method_count", 0), x["score"], x["quote_volume"]), reverse=True)
    medals = ["gold", "silver", "bronze"]
    for i, item in enumerate(found):
        item["rank"] = i + 1
        item["medal"] = medals[i] if i < 3 else "standard"
    history = read_json_file(RESULTS_PATH, [])
    active_keys = {(x.get("market"), x.get("interval"), x.get("symbol")) for x in history if x.get("result") == "مفتوحة"}
    ticker_prices = {x["symbol"]: x["price"] for x in tickers}
    for record in history:
        if record.get("result") != "مفتوحة" or record.get("market") != market or record.get("interval") != interval:
            continue
        price_now = ticker_prices.get(record.get("symbol"))
        if not price_now:
            continue
        record["last_price"] = price_now
        side = record.get("side")
        direction = 1 if side == "BUY" else -1
        record["pnl_pct"] = round((price_now - record["entry"]) / record["entry"] * 100 * direction, 4)
        hit = None
        if side == "BUY":
            if price_now <= record["stop"]: hit = "SL"
            elif price_now >= record["tp3"]: hit = "TP3"
            elif price_now >= record["tp2"]: record["reached"] = "TP2"
            elif price_now >= record["tp1"]: record["reached"] = "TP1"
        else:
            if price_now >= record["stop"]: hit = "SL"
            elif price_now <= record["tp3"]: hit = "TP3"
            elif price_now <= record["tp2"]: record["reached"] = "TP2"
            elif price_now <= record["tp1"]: record["reached"] = "TP1"
        if hit:
            record["result"] = hit
            record["closed_at"] = int(now)
    for item in found:
        ident = (market, interval, item["symbol"])
        if ident in active_keys:
            continue
        history.append({**item, "id": str(int(now*1000)) + "-" + item["symbol"], "created_at": int(now),
                        "last_price": ticker_prices.get(item["symbol"], item["entry"]), "result": "مفتوحة",
                        "reached": None, "pnl_pct": 0.0})
        active_keys.add(ident)
    write_json_file(RESULTS_PATH, history[-1000:])
    result = {"ok": True, "live": True, "market": market, "interval": interval,
              "scanned": len(tickers), "count": len(found), "updated_at": int(now),
              "items": found[:limit], "message": "الدخول والوقف والأهداف محسوبة من شموع Binance وATR. سجل النتائج يعتمد على السعر المرصود عند تحديث الخدمة، وليس سجل تداول لحظي كاملًا؛ لا توجد نسبة ربح تاريخية موثقة."}
    SIGNAL_CACHE[key] = (now, result)
    return result


def read_json_file(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json_file(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def require_admin(credentials: HTTPBasicCredentials = None):
    username = os.getenv("ADMIN_USERNAME", "")
    password = os.getenv("ADMIN_PASSWORD", "")
    if not username or not password:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="الإدارة مقفلة: عيّن ADMIN_USERNAME وADMIN_PASSWORD في متغيرات الخدمة.")
    if credentials is None or not (
        secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    ):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="بيانات دخول الإدارة غير صحيحة.", headers={"WWW-Authenticate": "Basic"})
    return True


@app.get("/api/news")
def market_news(limit: int = Query(12, ge=1, le=30)):
    from urllib.parse import urlencode
    queries = [
        "تداول العملات الرقمية OR بيتكوين OR إيثيريوم",
        "أسواق العملات المشفرة OR Binance",
    ]
    feed_urls = [
        "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "ar", "gl": "SA", "ceid": "SA:ar"})
        for query in queries
    ]
    items, seen = [], set()
    for url in feed_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SmartTradingPro/2.2"})
            with urllib.request.urlopen(req, timeout=6) as response:
                root = ET.fromstring(response.read())
            for node in root.findall("./channel/item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                pub = (node.findtext("pubDate") or "").strip()
                source = node.findtext("source") or "Google News"
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                items.append({"title": title, "url": link, "published": pub, "source": source})
        except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError, ValueError):
            continue
    items.sort(key=lambda x: x["published"], reverse=True)
    return {"ok": True, "live": bool(items), "items": items[:limit],
            "message": "عناوين مجمعة من Google News؛ افتح الخبر الأصلي للتحقق من التفاصيل." if items else "تعذر تحميل موجز الأخبار الآن؛ جرّب التحديث لاحقًا."}


@app.get("/api/blog")
def blog_articles():
    return {"ok": True, "items": read_json_file(ARTICLES_PATH, [])}


@app.get("/api/results")
def signal_results(limit: int = Query(100, ge=1, le=500)):
    items = read_json_file(RESULTS_PATH, [])
    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    closed = [x for x in items if x.get("result") in ("TP1", "TP2", "TP3", "SL")]
    wins = [x for x in closed if x.get("result") in ("TP1", "TP2", "TP3")]
    return {"ok": True, "items": items[:limit], "total": len(items), "closed": len(closed),
            "wins": len(wins), "losses": len(closed)-len(wins),
            "win_rate": round(len(wins)*100/len(closed), 1) if closed else None,
            "message": "النتائج تسجل من وقت اكتشاف الإشارة داخل الخدمة؛ إعادة تشغيل الخدمة قد تفقد السجل ما لم يُضبط DATA_DIR على تخزين دائم."}


@app.get("/api/admin/status")
def admin_status(credentials: HTTPBasicCredentials = Depends(security)):
    require_admin(credentials)
    return {"ok": True, "authenticated": True, "articles": len(read_json_file(ARTICLES_PATH, [])),
            "data_dir": str(DATA_DIR)}


@app.post("/api/admin/articles")
def admin_publish_article(payload: dict, credentials: HTTPBasicCredentials = Depends(security)):
    require_admin(credentials)
    title = str(payload.get("title", "")).strip()[:180]
    category = str(payload.get("category", "تعليم التداول")).strip()[:60]
    summary = str(payload.get("summary", "")).strip()[:600]
    body = str(payload.get("body", "")).strip()[:12000]
    if len(title) < 5 or len(body) < 30:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="أدخل عنوانًا واضحًا ومحتوى لا يقل عن 30 حرفًا.")
    articles = read_json_file(ARTICLES_PATH, [])
    article = {"id": str(int(time.time()*1000)), "title": title, "category": category,
               "summary": summary, "body": body, "published_at": int(time.time())}
    articles.insert(0, article)
    write_json_file(ARTICLES_PATH, articles[:500])
    return {"ok": True, "article": article}


@app.get("/api/admin/articles")
def admin_list_articles(credentials: HTTPBasicCredentials = Depends(security)):
    require_admin(credentials)
    return {"ok": True, "items": read_json_file(ARTICLES_PATH, [])}


@app.get("/api/status")
def status():
    return {
        "ok": True, "site": "ready",
        "markets": {
            "spot": "live_binance", "futures": "live_binance",
            "alpha": "not_connected",
            "contracts": "public_quotes_may_be_delayed",
            "us": "public_quotes_may_be_delayed",
            "saudi": "public_quotes_may_be_delayed",
            "forex": "public_quotes_may_be_delayed",
            "gold": "included_in_forex_quotes"
        },
        "note": "Yahoo Finance returns last available public quotes for selected symbols; these may be delayed. This endpoint does not claim full-universe or execution-grade real-time coverage."
    }
