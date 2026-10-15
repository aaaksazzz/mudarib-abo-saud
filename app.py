import json
import os
import time
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import secrets
import hashlib
import hmac
import threading
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from fastapi import FastAPI, Query, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
app = FastAPI(title="التداول الذكي PRO", version="2.1.3")
security = HTTPBasic(auto_error=False)

LOGIN_HTML = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>دخول | التداول الذكي PRO</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#080d18;color:#f8fafc;font-family:Tahoma,Arial,sans-serif;padding:20px}
.card{width:min(100%,390px);padding:30px 24px;border:1px solid #26344a;border-radius:22px;background:#111a2a;box-shadow:0 22px 70px #0008}
.logo{font-size:25px;font-weight:800;margin-bottom:8px}.logo span{color:#e8b84b}.sub{color:#a8b4c7;font-size:14px;margin-bottom:25px}
label{display:block;font-size:14px;margin-bottom:9px}input{width:100%;height:52px;border:1px solid #34445d;border-radius:12px;background:#080f1d;color:white;padding:0 15px;font-size:20px;letter-spacing:5px;outline:none}
input:focus{border-color:#e8b84b}button{width:100%;height:50px;margin-top:16px;border:0;border-radius:12px;background:#e8b84b;color:#17130a;font-size:16px;font-weight:800;cursor:pointer}
#error{min-height:22px;margin-top:13px;color:#ff8b8b;font-size:13px}.hint{font-size:12px;color:#77869e;margin-top:12px}
</style></head><body><main class="card"><div class="logo">التداول الذكي <span>PRO</span></div>
<div class="sub">أدخل الرقم السري للمتابعة</div><form id="login"><label for="pin">الرقم السري</label>
<input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required autofocus>
<button type="submit">دخول</button><div id="error" role="alert"></div></form><div class="hint">صفحة دخول محمية</div></main>
<script>
document.getElementById('login').addEventListener('submit',async function(e){e.preventDefault();const pin=document.getElementById('pin').value;const err=document.getElementById('error');err.textContent='';
try{const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});if(r.ok){location.reload();return}err.textContent='الرقم السري غير صحيح';document.getElementById('pin').select()}catch(_){err.textContent='تعذر الاتصال، حاول مرة أخرى'}});
</script></body></html>"""

def _site_session_token(expiry):
    secret = os.getenv("SITE_PASSWORD", "2341").encode("utf-8")
    msg = str(expiry).encode("ascii")
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return str(expiry) + "." + sig

def _valid_site_session(token):
    try:
        expiry_text, supplied = token.split(".", 1)
        expiry = int(expiry_text)
        if expiry < int(time.time()):
            return False
        expected = _site_session_token(expiry).split(".", 1)[1]
        return secrets.compare_digest(supplied, expected)
    except (ValueError, TypeError):
        return False

@app.middleware("http")
async def site_password_gate(request: Request, call_next):
    path = request.url.path
    if path in ("/health", "/login"):
        if path == "/login" and request.method == "POST":
            try:
                payload = await request.json()
                pin = str(payload.get("pin", "")) if isinstance(payload, dict) else ""
            except Exception:
                pin = ""
            expected_password = os.getenv("SITE_PASSWORD", "2341")
            if not secrets.compare_digest(pin, expected_password):
                return JSONResponse({"detail": "الرقم السري غير صحيح"}, status_code=401)
            response = JSONResponse({"ok": True})
            response.set_cookie("site_session", _site_session_token(int(time.time()) + 60 * 60 * 24 * 7),
                                httponly=True, secure=True, samesite="lax", path="/", max_age=60 * 60 * 24 * 7)
            return response
        return await call_next(request)

    token = request.cookies.get("site_session", "")
    if _valid_site_session(token):
        return await call_next(request)

    # Allow static assets needed by public login page, but never serve static HTML without a session.
    if path.startswith("/static/") and not path.lower().endswith((".html", ".htm")):
        return await call_next(request)

    if path.startswith("/api/") or request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "يلزم إدخال الرقم السري"}, status_code=401)

    return HTMLResponse(LOGIN_HTML, status_code=200)
# Persist results/articles on a mounted Northflank volume. Configure a persistent volume at /data.
# DATA_DIR may override this path for local development or another persistent mount.
DATA_DIR = Path(os.getenv("DATA_DIR", "/data/smart-trading-pro-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = DATA_DIR / "results.json"
SIGNALS_CACHE_PATH = DATA_DIR / "signals-cache.json"
# Protect the complete read-modify-write transaction across all market endpoints.
RESULTS_LOCK = threading.RLock()
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
    "contracts": ["ES=F", "NQ=F", "YM=F", "RTY=F", "EMD=F", "M2K=F", "GC=F", "SI=F", "HG=F", "PL=F", "PA=F", "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "ZC=F", "ZW=F", "ZS=F", "ZM=F", "ZL=F", "KC=F", "SB=F", "CT=F", "CC=F", "LE=F", "HE=F", "6E=F", "6B=F", "6J=F", "6A=F", "6C=F", "6S=F", "6N=F", "ZB=F", "ZN=F", "ZF=F", "ZT=F"],
    "forex": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "NZDJPY=X", "CADJPY=X", "CHFJPY=X", "EURCHF=X", "GBPCHF=X", "AUDCHF=X", "NZDCHF=X", "EURCAD=X", "GBPCAD=X", "AUDCAD=X", "NZDCAD=X", "EURAUD=X", "GBPAUD=X", "EURNZD=X", "GBPNZD=X", "AUDNZD=X", "USDMXN=X", "USDZAR=X", "USDTRY=X", "USDSEK=X", "USDNOK=X", "USDSGD=X", "USDHKD=X", "USDINR=X", "USDPLN=X", "USDCNH=X", "XAUUSD=X", "XAGUSD=X"],
}
YAHOO_LABELS = {
    "ES=F": "S&P 500 Futures", "NQ=F": "Nasdaq 100 Futures", "YM=F": "Dow Futures", "RTY=F": "Russell 2000 Futures",
    "GC=F": "Gold Futures", "SI=F": "Silver Futures", "CL=F": "WTI Crude Oil Futures", "NG=F": "Natural Gas Futures",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF", "NZDUSD=X": "NZD/USD", "EURGBP=X": "EUR/GBP",
    "XAUUSD=X": "Gold Spot", "XAGUSD=X": "Silver Spot", "HG=F": "Copper Futures", "PL=F": "Platinum Futures", "PA=F": "Palladium Futures",
    "BZ=F": "Brent Crude Futures", "RB=F": "RBOB Gasoline Futures", "HO=F": "Heating Oil Futures", "ZC=F": "Corn Futures",
    "ZW=F": "Wheat Futures", "ZS=F": "Soybean Futures", "ZM=F": "Soybean Meal Futures", "ZL=F": "Soybean Oil Futures",
    "KC=F": "Coffee Futures", "SB=F": "Sugar Futures", "CT=F": "Cotton Futures", "CC=F": "Cocoa Futures",
    "LE=F": "Live Cattle Futures", "HE=F": "Lean Hogs Futures", "6E=F": "Euro FX Futures", "6B=F": "British Pound Futures",
    "6J=F": "Japanese Yen Futures", "6A=F": "Australian Dollar Futures", "6C=F": "Canadian Dollar Futures",
    "6S=F": "Swiss Franc Futures", "6N=F": "New Zealand Dollar Futures", "ZB=F": "30-Year Treasury Bond Futures",
    "ZN=F": "10-Year Treasury Note Futures", "ZF=F": "5-Year Treasury Note Futures", "ZT=F": "2-Year Treasury Note Futures",
}
YAHOO_CACHE = {}
YAHOO_CACHE_TTL = 45
CACHE = {}
CACHE_TTL = 20
TECH_CACHE = {}
TECH_CACHE_TTL = 90
STABLES = {"USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP", "USDE", "USD1", "USDD", "USTC", "EUR", "EURC"}
INTERVALS = {"15m", "1h", "4h", "1d", "1w", "1M"}
# A signal remains active only for its own chart timeframe.
INTERVAL_SECONDS = {"15m": 15 * 60, "1h": 60 * 60, "4h": 4 * 60 * 60,
                    "1d": 24 * 60 * 60, "1w": 7 * 24 * 60 * 60, "1M": 30 * 24 * 60 * 60}
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
    hosts = ([host] + fallback_hosts.get(host, []))[:2]
    # Keep each provider attempt short so a blocked host cannot stall signal scans.
    timeout = min(timeout, 4)
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
BLOG_LANGS = [
    {"code":"ar","locale":"ar-SA","name":"العربية","dir":"rtl"},
    {"code":"en","locale":"en-US","name":"English","dir":"ltr"},
    {"code":"es","locale":"es-ES","name":"Español","dir":"ltr"},
    {"code":"fr","locale":"fr-FR","name":"Français","dir":"ltr"},
    {"code":"de","locale":"de-DE","name":"Deutsch","dir":"ltr"},
    {"code":"pt","locale":"pt-BR","name":"Português","dir":"ltr"},
    {"code":"tr","locale":"tr-TR","name":"Türkçe","dir":"ltr"},
    {"code":"hi","locale":"hi-IN","name":"हिन्दी","dir":"ltr"},
    {"code":"id","locale":"id-ID","name":"Bahasa Indonesia","dir":"ltr"},
    {"code":"zh","locale":"zh-CN","name":"简体中文","dir":"ltr"}
]
BLOG_TOPICS = [
 {"key":"stop-loss","cat":"risk","titles":["كيف تحدد وقف الخسارة قبل الدخول؟","How to Set a Stop Loss Before Entry","Cómo fijar un stop loss antes de entrar","Comment définir un stop loss avant d’entrer","So setzt du einen Stop-Loss vor dem Einstieg","Como definir um stop loss antes da entrada","İşleme girmeden zarar durdur nasıl belirlenir?","ट्रेड में प्रवेश से पहले स्टॉप लॉस कैसे तय करें","Cara menentukan stop loss sebelum masuk","入场前如何设置止损"],"focus":"stop"},
 {"key":"position-sizing","cat":"risk","titles":["حجم الصفقة: احمِ رأس المال أولًا","Position Sizing: Protect Capital First","Tamaño de posición: protege primero el capital","Taille de position : protéger le capital d’abord","Positionsgröße: Schütze zuerst dein Kapital","Tamanho da posição: proteja primeiro o capital","Pozisyon büyüklüğü: önce sermayeyi koru","पोज़िशन साइज़िंग: पहले पूँजी की रक्षा करें","Ukuran posisi: lindungi modal terlebih dahulu","仓位管理：首先保护本金"]},
 {"key":"risk-reward","cat":"risk","titles":["كيف تفهم نسبة العائد إلى المخاطرة؟","Understanding Risk-to-Reward Ratio","Cómo entender la relación riesgo-beneficio","Comprendre le ratio risque/rendement","Chance-Risiko-Verhältnis verstehen","Entenda a relação risco-retorno","Risk/getiri oranını anlama","जोखिम-इनाम अनुपात को समझें","Memahami rasio risiko-imbalan","理解风险回报比"]},
 {"key":"backtesting","cat":"strategy","titles":["اختبار الاستراتيجية تاريخيًا بطريقة صحيحة","How to Backtest a Trading Strategy Properly","Cómo probar una estrategia con datos históricos","Comment backtester correctement une stratégie","Eine Handelsstrategie richtig backtesten","Como testar uma estratégia com dados históricos","Bir işlem stratejisi doğru şekilde nasıl test edilir?","ट्रेडिंग रणनीति का सही बैकटेस्ट कैसे करें","Cara menguji strategi trading dengan benar","如何正确回测交易策略"]},
 {"key":"support-resistance","cat":"price","titles":["الدعم والمقاومة: قراءة المناطق لا الخطوط فقط","Support and Resistance: Read Zones, Not Just Lines","Soportes y resistencias: zonas, no solo líneas","Supports et résistances : des zones, pas seulement des lignes","Unterstützung und Widerstand: Zonen statt nur Linien","Suporte e resistência: zonas, não apenas linhas","Destek ve direnç: yalnızca çizgiler değil bölgeler","सपोर्ट और रेज़िस्टेंस: केवल रेखाएँ नहीं, क्षेत्र देखें","Support dan resistance: pahami zona, bukan hanya garis","支撑与阻力：关注区域，而不只是线条"]},
 {"key":"breakout-retest","cat":"price","titles":["اختراق وإعادة اختبار: متى تكون الإشارة أقوى؟","Breakout and Retest: When Is the Signal Stronger?","Ruptura y retesteo: ¿cuándo es más sólida la señal?","Cassure et retest : quand le signal est-il plus solide ?","Ausbruch und Retest: Wann ist das Signal stärker?","Rompimento e reteste: quando o sinal é mais forte?","Kırılım ve retest: sinyal ne zaman güçlenir?","ब्रेकआउट और रीटेस्ट: संकेत कब मज़बूत होता है?","Breakout dan retest: kapan sinyal lebih kuat?","突破与回踩：何时信号更可靠？"]},
 {"key":"false-breakout","cat":"price","titles":["كيف تتعرف على الاختراق الكاذب؟","How to Identify a False Breakout","Cómo identificar una ruptura falsa","Comment repérer une fausse cassure","So erkennst du einen Fehlausbruch","Como identificar um rompimento falso","Sahte kırılım nasıl belirlenir?","फॉल्स ब्रेकआउट की पहचान कैसे करें","Cara mengenali breakout palsu","如何识别假突破"]},
 {"key":"market-structure","cat":"technical","titles":["بنية السوق: القمم والقيعان واتجاه الحركة","Market Structure: Swings and Trend Direction","Estructura del mercado: máximos, mínimos y tendencia","Structure du marché : sommets, creux et tendance","Marktstruktur: Hochs, Tiefs und Trendrichtung","Estrutura do mercado: topos, fundos e tendência","Piyasa yapısı: tepe, dip ve trend yönü","मार्केट स्ट्रक्चर: स्विंग हाई, लो और ट्रेंड","Struktur pasar: puncak, lembah, dan arah tren","市场结构：波峰、波谷与趋势方向"]},
 {"key":"liquidity-sweep","cat":"technical","titles":["سحب السيولة: ما الذي يؤكد الفكرة؟","Liquidity Sweeps: What Confirms the Setup?","Barrido de liquidez: ¿qué confirma la idea?","Prise de liquidité : quels éléments confirment le scénario ?","Liquidity Sweep: Was bestätigt das Setup?","Varredura de liquidez: o que confirma o cenário?","Likidite süpürmesi: kurulumu ne doğrular?","लिक्विडिटी स्वीप: सेटअप की पुष्टि क्या करती है?","Liquidity sweep: apa yang mengonfirmasi setup?","流动性扫荡：哪些信号能确认形态？"]},
 {"key":"fair-value-gap","cat":"technical","titles":["فجوة القيمة العادلة FVG وكيفية تقييمها","Fair Value Gaps (FVG): How to Evaluate Them","Fair Value Gap (FVG): cómo evaluarlo","Fair Value Gap (FVG) : comment l’évaluer","Fair Value Gap (FVG): richtig bewerten","Fair Value Gap (FVG): como avaliar","Fair Value Gap (FVG) nasıl değerlendirilir?","फेयर वैल्यू गैप (FVG) का मूल्यांकन कैसे करें","Fair Value Gap (FVG): cara menilainya","公允价值缺口（FVG）如何评估"]},
 {"key":"trend-following","cat":"strategy","titles":["اتباع الاتجاه: قواعد لتجنب مطاردة السعر","Trend Following: Rules to Avoid Chasing Price","Seguimiento de tendencia: evita perseguir el precio","Suivi de tendance : éviter de courir après le prix","Trendfolge: Regeln gegen das Hinterherlaufen","Seguir tendências: regras para não perseguir o preço","Trend takibi: fiyatı kovalamamak için kurallar","ट्रेंड फॉलोइंग: कीमत के पीछे भागने से बचें","Trend following: aturan agar tidak mengejar harga","趋势跟踪：避免追涨杀跌的规则"]},
 {"key":"ema-filter","cat":"technical","titles":["EMA50 وEMA200: فلتر اتجاه وليس ضمان ربح","EMA50 and EMA200: Trend Filter, Not a Profit Guarantee","EMA50 y EMA200: filtro de tendencia, no garantía","EMA50 et EMA200 : filtre de tendance, pas garantie","EMA50 und EMA200: Trendfilter, keine Gewinngarantie","EMA50 e EMA200: filtro de tendência, não garantia","EMA50 ve EMA200: trend filtresi, kâr garantisi değil","EMA50 और EMA200: ट्रेंड फ़िल्टर, मुनाफ़े की गारंटी नहीं","EMA50 dan EMA200: filter tren, bukan jaminan profit","EMA50 与 EMA200：趋势过滤器，不是盈利保证"]},
 {"key":"candlestick-confirmation","cat":"technical","titles":["تأكيد الشموع اليابانية مع سياق السوق","Candlestick Confirmation in Market Context","Confirmación con velas japonesas y contexto","Confirmation par les chandeliers dans leur contexte","Kerzenbestätigung im Marktkontext","Confirmação por candles no contexto do mercado","Piyasa bağlamında mum formasyonu onayı","मार्केट संदर्भ में कैंडलस्टिक पुष्टि","Konfirmasi candlestick sesuai konteks pasar","结合市场环境确认蜡烛图信号"]},
 {"key":"volume-analysis","cat":"technical","titles":["حجم التداول: كيف تفرق بين الحركة القوية والضعيفة؟","Volume Analysis: Strong Move or Weak Move?","Análisis de volumen: ¿movimiento fuerte o débil?","Analyse du volume : mouvement fort ou faible ?","Volumenanalyse: starke oder schwache Bewegung?","Análise de volume: movimento forte ou fraco?","Hacim analizi: güçlü hareket mi zayıf mı?","वॉल्यूम विश्लेषण: मज़बूत चाल या कमज़ोर चाल?","Analisis volume: pergerakan kuat atau lemah?","成交量分析：如何区分强势与弱势行情？"]},
 {"key":"crypto-spot-futures","cat":"crypto","titles":["الفرق بين سبوت وفيوتشر في العملات الرقمية","Crypto Spot vs Futures: Key Differences","Cripto spot frente a futuros: diferencias clave","Crypto spot ou futures : différences clés","Krypto-Spot vs. Futures: die wichtigsten Unterschiede","Cripto spot vs. futuros: diferenças principais","Kripto spot ve vadeli işlemler arasındaki farklar","क्रिप्टो स्पॉट बनाम फ्यूचर्स: मुख्य अंतर","Kripto spot vs futures: perbedaan utama","加密货币现货与合约：核心区别"]},
 {"key":"funding-open-interest","cat":"crypto","titles":["التمويل والفائدة المفتوحة: ماذا يخبرك السوق؟","Funding Rates and Open Interest: What They Tell You","Funding y open interest: qué indican","Taux de financement et open interest : que révèlent-ils ?","Funding Rate und Open Interest: Was sie zeigen","Funding e open interest: o que revelam","Fonlama oranı ve açık pozisyonlar ne anlatır?","फंडिंग रेट और ओपन इंटरेस्ट क्या बताते हैं?","Funding rate dan open interest: apa artinya?","资金费率与未平仓量能说明什么？"]},
 {"key":"earnings-news","cat":"stocks","titles":["أخبار أرباح الشركات: كيف تقرأ المفاجأة؟","Company Earnings: How to Read the Surprise","Resultados empresariales: cómo leer la sorpresa","Résultats d’entreprise : comprendre la surprise","Unternehmenszahlen: Überraschungen richtig lesen","Resultados corporativos: como interpretar a surpresa","Şirket bilançoları: sürpriz nasıl okunur?","कंपनी के नतीजे: सरप्राइज़ को कैसे समझें","Laporan laba perusahaan: memahami kejutan","公司财报：如何解读业绩超预期或不及预期"]},
 {"key":"diversification","cat":"risk","titles":["تنويع المحفظة: تقليل التركّز دون وهم الأمان","Portfolio Diversification: Reduce Concentration Risk","Diversificación de cartera: reduce la concentración","Diversification du portefeuille : réduire la concentration","Portfolio-Diversifikation: Klumpenrisiken reduzieren","Diversificação da carteira: reduza a concentração","Portföy çeşitlendirme: yoğunlaşma riskini azaltma","पोर्टफोलियो विविधीकरण: एक जगह जोखिम कम करें","Diversifikasi portofolio: kurangi risiko terkonsentrasi","投资组合分散：降低集中风险"]},
 {"key":"trading-psychology","cat":"mindset","titles":["سيكولوجية التداول: الالتزام بالخطة وقت الضغط","Trading Psychology: Follow the Plan Under Pressure","Psicología del trading: seguir el plan bajo presión","Psychologie du trading : suivre son plan sous pression","Trading-Psychologie: Den Plan unter Druck einhalten","Psicologia do trading: seguir o plano sob pressão","İşlem psikolojisi: baskı altında plana bağlı kalmak","ट्रेडिंग मनोविज्ञान: दबाव में योजना का पालन","Psikologi trading: tetap disiplin saat tertekan","交易心理：在压力下坚持交易计划"]},
 {"key":"forex-gold-risk","cat":"crypto","titles":["الفوركس والذهب: فهم الرافعة والتذبذب","Forex and Gold: Understand Leverage and Volatility","Forex y oro: entiende el apalancamiento y la volatilidad","Forex et or : comprendre l’effet de levier et la volatilité","Forex und Gold: Hebel und Volatilität verstehen","Forex e ouro: entenda a alavancagem e a volatilidade","Forex ve altın: kaldıraç ve oynaklığı anlama","फॉरेक्स और सोना: लेवरेज और अस्थिरता समझें","Forex dan emas: pahami leverage dan volatilitas","外汇与黄金：理解杠杆和波动性"]}
]
BLOG_GUIDANCE = {
"stop-loss":["حدد مستوى إبطال الفكرة أولًا، ثم ضع الوقف بما يراعي التذبذب بدل اختياره عشوائيًا.","Choose the price level that invalidates the trade idea, then account for volatility instead of placing a stop arbitrarily.","Define el nivel que invalida la idea y considera la volatilidad antes de colocar el stop.","Définissez le niveau qui invalide le scénario et tenez compte de la volatilité avant de placer le stop.","Bestimme zuerst das Kursniveau, das die Idee widerlegt, und berücksichtige die Volatilität beim Stop.","Defina o nível que invalida a ideia e considere a volatilidade antes de posicionar o stop.","Önce fikri geçersiz kılan fiyat seviyesini belirleyin ve stop koyarken oynaklığı hesaba katın.","पहले वह स्तर तय करें जो ट्रेड विचार को गलत साबित करेगा, फिर अस्थिरता के अनुसार स्टॉप रखें।","Tentukan level harga yang membatalkan ide, lalu pertimbangkan volatilitas saat memasang stop.","先确定使交易判断失效的价位，再结合波动性设置止损。"],
"position-sizing":["اربط حجم المركز بالمسافة إلى الوقف ومقدار الخسارة المقبولة، لا بقوة الحماس.","Size the position from the stop distance and acceptable loss, not from confidence or excitement.","Calcula el tamaño según la distancia al stop y la pérdida aceptable, no según el entusiasmo.","Calculez la taille selon la distance au stop et la perte acceptable, pas selon l’enthousiasme.","Leite die Positionsgröße aus Stop-Abstand und tragbarem Verlust ab, nicht aus Begeisterung.","Calcule o tamanho pela distância até o stop e pela perda aceitável, não pelo entusiasmo.","Pozisyonu heyecana göre değil, stop mesafesi ve kabul edilebilir kayba göre belirleyin.","उत्साह के आधार पर नहीं, बल्कि स्टॉप की दूरी और स्वीकार्य नुकसान के आधार पर पोज़िशन तय करें।","Tentukan ukuran posisi dari jarak stop dan kerugian yang dapat diterima, bukan dari rasa yakin.","仓位大小应依据止损距离和可承受亏损，而不是主观信心。"],
"risk-reward":["احسب العائد المتوقع بعد الرسوم والانزلاق، ولا تكتفِ بنسبة الهدف إلى الوقف على الرسم.","Estimate returns after fees and slippage; the chart’s target-to-stop ratio alone is insufficient.","Calcula el resultado después de comisiones y deslizamiento; la proporción visual por sí sola no basta.","Estimez le résultat après frais et glissement ; le ratio affiché ne suffit pas à lui seul.","Berechne das Ergebnis nach Gebühren und Slippage; das sichtbare Chance-Risiko-Verhältnis allein reicht nicht.","Calcule o resultado após taxas e slippage; a proporção visual sozinha não basta.","Grafikteki oranla yetinmeyin; komisyon ve kaymayı da hesaba katın.","केवल चार्ट पर अनुपात न देखें; शुल्क और स्लिपेज भी शामिल करें।","Hitung hasil setelah biaya dan slippage; rasio di grafik saja belum cukup.","计算时要计入手续费和滑点，不能只看图上的盈亏比。"],
"trading-journal":["سجّل سبب الدخول والخروج وحالة السوق والخطأ المحتمل كي تكتشف الأنماط المتكررة.","Record entry and exit reasons, market conditions, and mistakes to find recurring patterns.","Registra las razones de entrada y salida, el contexto y los errores para detectar patrones repetidos.","Notez les raisons d’entrée et de sortie, le contexte et les erreurs pour repérer les répétitions.","Dokumentiere Ein- und Ausstiegsgründe, Marktumfeld und Fehler, um Muster zu erkennen.","Registre motivos de entrada e saída, contexto e erros para encontrar padrões recorrentes.","Tekrarlayan kalıpları bulmak için giriş-çıkış nedenlerini, piyasa koşullarını ve hataları kaydedin.","दोहराए जाने वाले पैटर्न पहचानने के लिए प्रवेश-निकास, बाज़ार स्थिति और गलतियाँ लिखें।","Catat alasan masuk-keluar, kondisi pasar, dan kesalahan untuk menemukan pola berulang.","记录进出场原因、市场环境和错误，以发现反复出现的问题。"],
"backtesting":["اكتب قواعد قابلة للبرمجة واحتسب التكاليف، وإلا فقد تبدو النتيجة التاريخية أفضل من الواقع.","Use rules that can be coded and include trading costs, or historical results may look unrealistically good.","Usa reglas programables e incluye costes; de lo contrario, los resultados históricos pueden parecer demasiado buenos.","Utilisez des règles programmables et incluez les coûts, sinon les résultats historiques peuvent être trompeurs.","Nutze eindeutig programmierbare Regeln und berücksichtige Kosten, sonst wirken Backtests zu gut.","Use regras programáveis e inclua custos, ou os resultados históricos podem parecer irreais.","Kodlanabilir kurallar kullanın ve maliyetleri ekleyin; aksi hâlde geriye dönük sonuçlar yanıltıcı olabilir.","प्रोग्राम किए जा सकने वाले नियम और लागत शामिल करें, वरना बैकटेस्ट अवास्तविक लग सकता है।","Gunakan aturan yang bisa diprogram dan masukkan biaya agar hasil historis tidak terlalu optimistis.","使用可编程规则并计入交易成本，否则回测结果可能过于乐观。"],
"out-of-sample":["افصل فترة الاختبار عن فترة تطوير القواعد لتقليل خطر الإفراط في ملاءمة البيانات.","Keep test data separate from rule development to reduce the risk of overfitting.","Separa los datos de prueba del desarrollo para reducir el sobreajuste.","Séparez les données de test du développement pour limiter le surapprentissage.","Trenne Testdaten von der Regelentwicklung, um Overfitting zu reduzieren.","Separe os dados de teste do desenvolvimento para reduzir o sobreajuste.","Aşırı uyumu azaltmak için test verisini kural geliştirme döneminden ayırın.","ओवरफिटिंग घटाने के लिए टेस्ट डेटा को नियम बनाने वाले डेटा से अलग रखें।","Pisahkan data uji dari pengembangan aturan untuk mengurangi overfitting.","将测试数据与规则开发数据分开，以降低过度拟合风险。"],
"support-resistance":["اعتبر الدعم والمقاومة مناطق محتملة للتفاعل، وراقب الإغلاق والسياق بدل افتراض ارتداد مضمون.","Treat support and resistance as reaction zones, and assess closes and context rather than assuming a guaranteed bounce.","Trata soportes y resistencias como zonas de reacción y observa cierres y contexto, no rebotes garantizados.","Considérez les supports et résistances comme des zones de réaction, sans supposer un rebond certain.","Betrachte Unterstützungen und Widerstände als Reaktionszonen und setze keinen sicheren Abprall voraus.","Trate suportes e resistências como zonas de reação, sem presumir um repique garantido.","Destek ve direnci tepki bölgeleri olarak değerlendirin; kesin dönüş varsaymayın.","सपोर्ट और रेज़िस्टेंस को संभावित प्रतिक्रिया क्षेत्र मानें, निश्चित पलटाव नहीं।","Anggap support dan resistance sebagai zona reaksi, bukan jaminan harga berbalik.","将支撑和阻力视为潜在反应区域，而不是必然反转点。"],
"breakout-retest":["قارن حجم التداول والإغلاق بعد الكسر، ثم راقب إعادة الاختبار لتقييم قبول السعر فوق المستوى.","Check volume and closing price on a breakout, then observe the retest to assess acceptance above the level.","Compara volumen y cierre durante la ruptura y observa el retesteo para evaluar la aceptación.","Comparez le volume et la clôture lors de la cassure, puis observez le retest pour juger l’acceptation.","Prüfe Volumen und Schlusskurs beim Ausbruch und beobachte den Retest zur Bestätigung.","Compare volume e fechamento no rompimento e observe o reteste para avaliar a aceitação.","Kırılımda hacmi ve kapanışı inceleyin, ardından seviyenin kabul edilip edilmediğini retest ile değerlendirin.","ब्रेकआउट पर वॉल्यूम और क्लोज़ देखें, फिर रीटेस्ट से स्तर की स्वीकृति जाँचें।","Periksa volume dan penutupan saat breakout, lalu amati retest untuk menilai penerimaan harga.","观察突破时的成交量和收盘价，再通过回踩判断价格是否接受该区域。"],
"false-breakout":["العودة السريعة داخل النطاق قد تحذر من فشل الكسر، لكن يلزم تقييم السيولة والإطار الزمني الأكبر.","A quick return into the range can warn of a failed breakout, but liquidity and the higher timeframe still matter.","Un regreso rápido al rango puede advertir de una ruptura fallida, pero importa el marco temporal superior.","Un retour rapide dans la zone peut signaler une fausse cassure, mais le contexte supérieur reste important.","Eine schnelle Rückkehr in die Range kann einen Fehlausbruch anzeigen; der höhere Zeitrahmen bleibt wichtig.","O retorno rápido à faixa pode indicar falso rompimento, mas o contexto do período maior continua relevante.","Fiyatın hızla aralığa dönmesi sahte kırılıma işaret edebilir; üst zaman dilimi de önemlidir.","तेज़ी से रेंज में वापसी फॉल्स ब्रेकआउट का संकेत हो सकती है; बड़ा टाइमफ्रेम भी देखें।","Harga yang cepat kembali ke rentang dapat menandakan breakout palsu; perhatikan timeframe lebih tinggi.","价格快速回到区间内可能是假突破，但仍需结合更高周期判断。"],
"market-structure":["راقب تسلسل القمم والقيعان وتغيره، ولا تصنف الاتجاه من حركة منفردة.","Track the sequence of swing highs and lows; do not label a trend from one isolated move.","Observa la secuencia de máximos y mínimos; no definas la tendencia por un movimiento aislado.","Suivez la succession des sommets et creux ; un mouvement isolé ne suffit pas à définir la tendance.","Beobachte die Folge von Hochs und Tiefs; eine einzelne Bewegung definiert keinen Trend.","Observe a sequência de topos e fundos; um movimento isolado não define a tendência.","Tepe ve diplerin sırasını takip edin; tek bir hareket trendi tanımlamaz.","स्विंग हाई और लो का क्रम देखें; एक अकेली चाल से ट्रेंड तय न करें।","Amati urutan puncak dan lembah; satu pergerakan saja tidak menentukan tren.","观察波峰和波谷的连续关系，不要仅凭一次波动判断趋势。"],
"liquidity-sweep":["تجاوز قمة أو قاع ثم العودة لا يكفي وحده؛ انتظر دليلًا على الرفض أو تغير البنية.","A move beyond a prior high or low is not enough by itself; look for rejection or a structure shift.","Superar un máximo o mínimo previo no basta; busca rechazo o un cambio de estructura.","Dépasser un sommet ou un creux ne suffit pas ; recherchez un rejet ou un changement de structure.","Ein Bruch früherer Hochs oder Tiefs reicht nicht; achte auf Zurückweisung oder Strukturwechsel.","Romper uma máxima ou mínima anterior não basta; procure rejeição ou mudança estrutural.","Önceki tepe veya dibin aşılması tek başına yeterli değildir; reddedilme ya da yapı değişimi arayın.","पिछले हाई या लो के पार जाना पर्याप्त नहीं; रिजेक्शन या स्ट्रक्चर बदलाव देखें।","Menembus puncak atau lembah sebelumnya saja tidak cukup; cari penolakan atau perubahan struktur.","仅突破前高或前低并不足够，还要观察拒绝信号或结构变化。"],
"fair-value-gap":["قيّم الفجوة ضمن اتجاه الحركة ومكانها، وحدد مسبقًا ما الذي يلغي السيناريو.","Evaluate the gap within the impulse and its location, and define what would invalidate the setup.","Evalúa el gap dentro del impulso y su ubicación, y define qué invalidaría la idea.","Évaluez le gap dans son impulsion et son emplacement, puis définissez son invalidation.","Bewerte die Lücke im Kontext des Impulses und lege die Invalidierung vorher fest.","Avalie o gap no contexto do impulso e da localização, definindo a invalidação com antecedência.","Boşluğu impuls ve konum bağlamında değerlendirin, geçersizlik koşulunu önceden belirleyin.","गैप को इम्पल्स और स्थान के संदर्भ में देखें तथा अमान्य होने की शर्त पहले तय करें।","Nilai gap sesuai impuls dan lokasinya, lalu tetapkan kondisi pembatalan setup.","结合推动行情和所处位置评估缺口，并提前定义失效条件。"],
"trend-following":["يفضل اتباع الاتجاه خطة دخول واضحة ومكانًا منطقيًا للإبطال بدل مطاردة شمعة ممتدة.","Trend following needs a defined entry and logical invalidation point, not chasing an extended candle.","Seguir tendencias requiere una entrada definida y una invalidación lógica, no perseguir velas extendidas.","Le suivi de tendance exige une entrée définie et une invalidation logique, pas la poursuite d’une bougie étendue.","Trendfolge braucht einen klaren Einstieg und eine logische Invalidierung statt das Hinterherlaufen.","Seguir tendências exige entrada definida e invalidação lógica, não perseguir candles esticados.","Trend takibinde uzamış mumu kovalamak yerine net giriş ve mantıklı geçersizlik seviyesi gerekir.","ट्रेंड फॉलोइंग में लंबी कैंडल का पीछा करने के बजाय स्पष्ट प्रवेश और अमान्य स्तर तय करें।","Trend following membutuhkan entry jelas dan level invalidasi yang logis, bukan mengejar candle panjang.","趋势跟踪需要明确入场和合理失效位，而不是追逐已经拉长的K线。"],
"ema-filter":["تأخر المتوسطات يجعلها أداة تصفية؛ أكدها ببنية السعر ولا تعتمد عليها منفردة.","Moving averages lag, so use them as filters and confirm with price structure rather than using them alone.","Las medias se retrasan; úsalas como filtro y confirma con la estructura del precio.","Les moyennes sont retardées ; utilisez-les comme filtre et confirmez avec la structure des prix.","Gleitende Durchschnitte hinken nach; nutze sie als Filter und bestätige sie durch die Preisstruktur.","As médias atrasam; use-as como filtro e confirme com a estrutura do preço.","Hareketli ortalamalar gecikir; filtre olarak kullanıp fiyat yapısıyla doğrulayın.","मूविंग एवरेज पीछे चलते हैं; उन्हें फ़िल्टर की तरह लें और प्राइस स्ट्रक्चर से पुष्टि करें।","Moving average tertinggal; gunakan sebagai filter dan konfirmasi dengan struktur harga.","均线存在滞后，应作为过滤条件，并结合价格结构确认。"],
"candlestick-confirmation":["اقرأ شكل الشمعة عند مستوى مهم وبعد الإغلاق، مع مراعاة الاتجاه والحجم.","Read a candle at a meaningful level after it closes, while considering trend and volume.","Interpreta la vela en un nivel relevante después del cierre y considera tendencia y volumen.","Analysez la bougie sur un niveau important après sa clôture, avec la tendance et le volume.","Bewerte Kerzen an relevanten Niveaus nach Schluss und berücksichtige Trend und Volumen.","Leia o candle em um nível importante após o fechamento, considerando tendência e volume.","Mumu önemli seviyede kapanıştan sonra değerlendirin; trend ve hacmi de dikkate alın.","महत्वपूर्ण स्तर पर कैंडल बंद होने के बाद उसे ट्रेंड और वॉल्यूम के साथ पढ़ें।","Baca candle pada level penting setelah penutupan, dengan mempertimbangkan tren dan volume.","在关键价位等待K线收盘，并结合趋势与成交量解读。"],
"volume-analysis":["قارن الحجم بمتوسطه وبمكان الحركة؛ الرقم المرتفع وحده لا يحدد اتجاه الصفقة.","Compare volume with its baseline and price location; high volume alone does not define trade direction.","Compara el volumen con su referencia y la ubicación del precio; un volumen alto no define por sí solo la dirección.","Comparez le volume à sa référence et à la position du prix ; un volume élevé seul ne donne pas la direction.","Vergleiche das Volumen mit seinem Normalwert und dem Kurskontext; hohes Volumen allein zeigt keine Richtung.","Compare o volume com sua referência e a posição do preço; volume alto sozinho não define a direção.","Hacmi referansıyla ve fiyatın konumuyla karşılaştırın; yüksek hacim tek başına yön belirlemez.","वॉल्यूम को उसके सामान्य स्तर और कीमत की स्थिति से तुलना करें; अधिक वॉल्यूम अकेले दिशा नहीं बताता।","Bandingkan volume dengan acuan dan posisi harga; volume tinggi saja tidak menentukan arah.","将成交量与基准及价格位置比较；单纯放量并不能决定方向。"],
"crypto-spot-futures":["في السبوت تملك الأصل عادةً، أما العقود فتضيف مخاطر الرافعة والتصفية وشروط المنصة.","Spot usually involves owning the asset, while derivatives add leverage, liquidation, and venue-specific risks.","En spot normalmente posees el activo; los derivados añaden apalancamiento, liquidación y riesgos de plataforma.","Le spot implique généralement la détention de l’actif ; les dérivés ajoutent levier, liquidation et risques de plateforme.","Beim Spot besitzt du üblicherweise den Vermögenswert; Derivate bringen Hebel- und Liquidationsrisiken.","No spot, geralmente você detém o ativo; derivativos acrescentam alavancagem e risco de liquidação.","Spot işlemlerde genellikle varlığa sahip olursunuz; vadeli işlemler kaldıraç ve tasfiye riski ekler.","स्पॉट में आम तौर पर एसेट आपका होता है; फ्यूचर्स में लेवरेज और लिक्विडेशन का जोखिम जुड़ता है।","Spot biasanya berarti memiliki aset; derivatif menambah risiko leverage dan likuidasi.","现货通常意味着持有资产，而衍生品还会带来杠杆和强平风险。"],
"funding-open-interest":["فسّر التمويل والفائدة المفتوحة مع حركة السعر والحجم؛ لا تستخدم قراءة واحدة كإشارة مؤكدة.","Interpret funding and open interest alongside price and volume; one reading is not a confirmed signal.","Interpreta funding e interés abierto junto al precio y volumen; una lectura aislada no confirma una señal.","Interprétez le funding et l’open interest avec le prix et le volume ; une seule lecture ne confirme rien.","Interpretiere Funding und Open Interest zusammen mit Preis und Volumen; ein Einzelwert ist kein Signal.","Interprete funding e open interest junto ao preço e volume; uma leitura isolada não confirma sinal.","Fonlama ve açık pozisyonları fiyat ve hacimle birlikte yorumlayın; tek veri kesin sinyal değildir.","फंडिंग और ओपन इंटरेस्ट को कीमत व वॉल्यूम के साथ देखें; एक रीडिंग पुष्टि नहीं है।","Tafsirkan funding dan open interest bersama harga dan volume; satu angka bukan sinyal pasti.","应结合价格和成交量解读资金费率与未平仓量，单一读数不是确认信号。"],
"earnings-news":["قارن النتائج بتوقعات السوق والتوجيه المستقبلي، وانتبه إلى أن رد فعل السعر قد يختلف عن العنوان.","Compare results with expectations and forward guidance; price reaction can differ from the headline.","Compara los resultados con las expectativas y previsiones; la reacción del precio puede diferir del titular.","Comparez les résultats aux attentes et aux perspectives ; la réaction du prix peut différer du titre.","Vergleiche Zahlen mit Erwartungen und Ausblick; die Kursreaktion kann von der Schlagzeile abweichen.","Compare os resultados às expectativas e projeções; a reação do preço pode diferir da manchete.","Sonuçları beklentiler ve gelecek öngörüleriyle karşılaştırın; fiyat tepkisi başlıktan farklı olabilir.","नतीजों की तुलना अपेक्षाओं और आगे के अनुमान से करें; कीमत की प्रतिक्रिया हेडलाइन से अलग हो सकती है।","Bandingkan hasil dengan ekspektasi dan panduan ke depan; reaksi harga bisa berbeda dari judul berita.","将业绩与市场预期和未来指引比较；股价反应可能与新闻标题不同。"],
"diversification":["قِس ترابط الأصول والتعرض المشترك للمخاطر؛ امتلاك رموز كثيرة لا يعني تنويعًا حقيقيًا.","Measure correlations and shared risk exposures; holding many symbols does not automatically diversify.","Mide correlaciones y riesgos compartidos; tener muchos activos no garantiza diversificación.","Mesurez les corrélations et expositions communes ; multiplier les actifs ne garantit pas la diversification.","Prüfe Korrelationen und gemeinsame Risiken; viele Symbole bedeuten nicht automatisch Diversifikation.","Avalie correlações e exposições comuns; ter muitos ativos não garante diversificação.","Korelasyonları ve ortak riskleri ölçün; çok sayıda varlık gerçek çeşitlendirme anlamına gelmez.","सहसंबंध और साझा जोखिम देखें; कई एसेट रखने से अपने-आप विविधीकरण नहीं होता।","Ukur korelasi dan paparan risiko bersama; banyak aset tidak otomatis berarti diversifikasi.","评估相关性和共同风险敞口；持有很多资产不等于真正分散。"],
"trading-psychology":["حوّل الخطة إلى شروط مكتوبة وحدود للمخاطرة، وابتعد عن مضاعفة المخاطر لاستعادة خسارة.","Write down the plan and risk limits; avoid increasing exposure simply to recover a loss.","Escribe el plan y los límites de riesgo; evita aumentar la exposición para recuperar pérdidas.","Écrivez le plan et les limites de risque ; n’augmentez pas l’exposition pour récupérer une perte.","Halte Plan und Risikogrenzen schriftlich fest; erhöhe das Risiko nicht nur, um Verluste aufzuholen.","Registre o plano e os limites de risco; não aumente a exposição apenas para recuperar perdas.","Planı ve risk sınırlarını yazılı tutun; kaybı telafi etmek için riski artırmayın.","योजना और जोखिम सीमा लिखें; नुकसान वापस पाने के लिए जोखिम न बढ़ाएँ।","Tuliskan rencana dan batas risiko; jangan menambah eksposur hanya untuk mengejar kerugian.","写下交易计划和风险上限，不要为了挽回亏损而加大风险。"],
"forex-gold-risk":["تحقق من قيمة النقطة والهامش ومواعيد الأخبار؛ الرافعة تضخم الأرباح والخسائر معًا.","Check pip value, margin, and event timing; leverage magnifies both gains and losses.","Comprueba el valor del pip, el margen y los horarios de noticias; el apalancamiento amplifica ganancias y pérdidas.","Vérifiez la valeur du pip, la marge et le calendrier économique ; le levier amplifie gains et pertes.","Prüfe Pip-Wert, Margin und Termine; Hebel verstärkt Gewinne und Verluste gleichermaßen.","Verifique valor do pip, margem e horários de notícias; a alavancagem amplia ganhos e perdas.","Pip değerini, teminatı ve haber saatlerini kontrol edin; kaldıraç hem kârı hem zararı büyütür.","पिप वैल्यू, मार्जिन और समाचार समय जाँचें; लेवरेज लाभ और नुकसान दोनों बढ़ाता है।","Periksa nilai pip, margin, dan jadwal berita; leverage memperbesar untung dan rugi.","检查点值、保证金和重要数据发布时间；杠杆会同时放大盈利与亏损。"]
}
BLOG_COPY = {
"ar":{"categories":{"risk":"إدارة المخاطر","mindset":"الانضباط النفسي","strategy":"اختبار الاستراتيجيات","price":"حركة السعر","technical":"التحليل الفني","crypto":"الأسواق والأصول","stocks":"الأسهم"},"intro":"هذا الدليل يشرح موضوع «{title}» بطريقة عملية، مع التركيز على قواعد واضحة يمكن مراجعتها واختبارها بدل الاعتماد على الانطباعات أو الوعود.","body":"ابدأ بتحديد شروطك قبل الدخول: ما الذي تبحث عنه في الرسم؟ وما الدليل الذي يؤكد الفكرة؟ اكتب قاعدة قابلة للقياس، وحدد مسبقًا ما الذي يبطلها. استخدم أكثر من شمعة أو مستوى منفرد لتقييم السياق، ولا تخلط بين الاحتمال واليقين.","practice":"طبّق الفكرة على عينة من بيانات تاريخية، ثم اختبرها على فترة لم تستخدمها في إعداد القواعد. سجّل النتائج والتكاليف والانزلاق وأقصى تراجع، وقارن أداءها في الاتجاهات والأسواق العرضية. عدّل قاعدة واحدة في كل مرة حتى تعرف سبب تغير النتيجة.","warning":"هذا المحتوى للتعليم فقط وليس توصية استثمارية. الأسواق تنطوي على مخاطر، والنتائج التاريخية لا تضمن نتائج مستقبلية."},
"en":{"categories":{"risk":"Risk Management","mindset":"Trading Psychology","strategy":"Strategy Testing","price":"Price Action","technical":"Technical Analysis","crypto":"Markets and Assets","stocks":"Stocks"},"intro":"This practical guide explains “{title}” through clear rules you can review and test, rather than relying on impressions or promises.","body":"Define your conditions before entry: what are you looking for on the chart, and what evidence would support the idea? Write a measurable rule and decide in advance what invalidates it. Evaluate context instead of relying on a single candle or level, and distinguish probability from certainty.","practice":"Apply the idea to historical data, then test it on a period not used to design the rules. Record costs, slippage, drawdown, and results across trending and ranging markets. Change one rule at a time so you can understand why performance changes.","warning":"Educational content only, not investment advice. Markets involve risk, and historical results do not guarantee future performance."},
"es":{"categories":{"risk":"Gestión del riesgo","mindset":"Psicología del trading","strategy":"Prueba de estrategias","price":"Acción del precio","technical":"Análisis técnico","crypto":"Mercados y activos","stocks":"Acciones"},"intro":"Esta guía práctica explica «{title}» mediante reglas claras que puedes revisar y probar, sin depender de impresiones ni promesas.","body":"Define las condiciones antes de entrar: qué buscas en el gráfico y qué evidencia respaldaría la idea. Escribe una regla medible y decide de antemano qué la invalida. Evalúa el contexto en lugar de depender de una sola vela o nivel, y distingue probabilidad de certeza.","practice":"Aplica la idea a datos históricos y después pruébala en un periodo que no hayas usado para diseñar las reglas. Registra costes, deslizamiento, caída máxima y resultados en mercados tendenciales y laterales. Cambia una sola regla cada vez para entender el efecto.","warning":"Contenido educativo, no asesoramiento financiero. Los mercados implican riesgo y los resultados históricos no garantizan resultados futuros."},
"fr":{"categories":{"risk":"Gestion du risque","mindset":"Psychologie du trading","strategy":"Test des stratégies","price":"Action des prix","technical":"Analyse technique","crypto":"Marchés et actifs","stocks":"Actions"},"intro":"Ce guide pratique explique « {title} » à l’aide de règles claires à examiner et à tester, plutôt que de se fier aux impressions ou aux promesses.","body":"Définissez vos conditions avant l’entrée : que recherchez-vous sur le graphique et quels éléments soutiendraient l’idée ? Formulez une règle mesurable et déterminez à l’avance ce qui l’invalide. Analysez le contexte au lieu de vous fier à une seule bougie ou à un seul niveau, et distinguez probabilité et certitude.","practice":"Appliquez l’idée aux données historiques, puis testez-la sur une période qui n’a pas servi à construire les règles. Notez les frais, le glissement, le recul maximal et les résultats en marché tendanciel ou latéral. Ne modifiez qu’une règle à la fois pour comprendre l’effet.","warning":"Contenu éducatif uniquement, pas un conseil en investissement. Les marchés comportent des risques et les performances passées ne garantissent pas les résultats futurs."},
"de":{"categories":{"risk":"Risikomanagement","mindset":"Trading-Psychologie","strategy":"Strategietests","price":"Price Action","technical":"Technische Analyse","crypto":"Märkte und Anlageklassen","stocks":"Aktien"},"intro":"Dieser praktische Leitfaden erklärt „{title}“ anhand klarer Regeln, die du überprüfen und testen kannst, statt dich auf Eindrücke oder Versprechen zu verlassen.","body":"Lege deine Bedingungen vor dem Einstieg fest: Was suchst du im Chart und welche Belege würden die Idee stützen? Formuliere eine messbare Regel und bestimme vorher, wann sie ungültig ist. Beurteile den Kontext statt nur eine Kerze oder ein Niveau, und unterscheide Wahrscheinlichkeit von Gewissheit.","practice":"Prüfe die Idee mit historischen Daten und anschließend in einem Zeitraum, der nicht zur Entwicklung der Regeln verwendet wurde. Erfasse Gebühren, Slippage, maximalen Drawdown und Ergebnisse in Trend- und Seitwärtsmärkten. Ändere jeweils nur eine Regel, um die Auswirkungen zu erkennen.","warning":"Nur zu Bildungszwecken, keine Anlageberatung. Märkte sind riskant; vergangene Ergebnisse garantieren keine zukünftige Wertentwicklung."},
"pt":{"categories":{"risk":"Gestão de risco","mindset":"Psicologia do trading","strategy":"Teste de estratégias","price":"Ação do preço","technical":"Análise técnica","crypto":"Mercados e ativos","stocks":"Ações"},"intro":"Este guia prático explica “{title}” com regras claras que podem ser revisadas e testadas, sem depender de impressões ou promessas.","body":"Defina as condições antes da entrada: o que você procura no gráfico e quais evidências sustentariam a ideia? Escreva uma regra mensurável e determine antecipadamente o que a invalida. Avalie o contexto em vez de depender de um único candle ou nível, distinguindo probabilidade de certeza.","practice":"Aplique a ideia a dados históricos e depois teste-a em um período que não foi usado para criar as regras. Registre custos, slippage, drawdown máximo e resultados em mercados de tendência e laterais. Altere uma regra por vez para entender o efeito.","warning":"Conteúdo educacional, não é recomendação de investimento. Os mercados envolvem riscos e resultados passados não garantem resultados futuros."},
"tr":{"categories":{"risk":"Risk Yönetimi","mindset":"İşlem Psikolojisi","strategy":"Strateji Testi","price":"Fiyat Hareketi","technical":"Teknik Analiz","crypto":"Piyasalar ve Varlıklar","stocks":"Hisseler"},"intro":"Bu pratik rehber, “{title}” konusunu izlenimlere veya vaatlere dayanmak yerine incelenip test edilebilen açık kurallarla ele alır.","body":"İşleme girmeden koşullarınızı belirleyin: grafikte ne arıyorsunuz ve fikri hangi kanıt destekler? Ölçülebilir bir kural yazın ve hangi durumda geçersiz olacağını önceden belirleyin. Tek bir mum veya seviyeye bağlı kalmayıp bağlamı değerlendirin; olasılıkla kesinliği ayırın.","practice":"Fikri geçmiş verilerde uygulayın, ardından kuralları oluştururken kullanmadığınız bir dönemde test edin. Maliyetleri, kaymayı, azami düşüşü ve trend/yatay piyasa sonuçlarını kaydedin. Etkiyi anlayabilmek için her seferinde yalnızca bir kuralı değiştirin.","warning":"Yalnızca eğitim amaçlıdır, yatırım tavsiyesi değildir. Piyasalar risk içerir ve geçmiş sonuçlar gelecekteki performansı garanti etmez."},
"hi":{"categories":{"risk":"जोखिम प्रबंधन","mindset":"ट्रेडिंग मनोविज्ञान","strategy":"रणनीति परीक्षण","price":"प्राइस एक्शन","technical":"तकनीकी विश्लेषण","crypto":"बाज़ार और एसेट","stocks":"शेयर"},"intro":"यह व्यावहारिक मार्गदर्शिका “{title}” को स्पष्ट नियमों के साथ समझाती है जिन्हें जाँचा और परखा जा सकता है; केवल अनुमान या वादों पर निर्भर न रहें।","body":"प्रवेश से पहले शर्तें तय करें: चार्ट पर आप क्या खोज रहे हैं और कौन-सा प्रमाण विचार का समर्थन करेगा? मापने योग्य नियम लिखें और पहले से तय करें कि वह कब अमान्य होगा। केवल एक कैंडल या स्तर पर निर्भर न रहें; संदर्भ देखें और संभावना को निश्चितता न समझें।","practice":"विचार को ऐतिहासिक डेटा पर लागू करें, फिर ऐसी अवधि पर जाँचें जिसका उपयोग नियम बनाने में नहीं हुआ था। लागत, स्लिपेज, अधिकतम ड्रॉडाउन और ट्रेंडिंग तथा रेंजिंग बाज़ारों के परिणाम दर्ज करें। प्रभाव समझने के लिए एक बार में केवल एक नियम बदलें।","warning":"यह केवल शैक्षिक सामग्री है, निवेश सलाह नहीं। बाज़ार जोखिमपूर्ण हैं और पुराने परिणाम भविष्य के लाभ की गारंटी नहीं हैं।"},
"id":{"categories":{"risk":"Manajemen Risiko","mindset":"Psikologi Trading","strategy":"Pengujian Strategi","price":"Aksi Harga","technical":"Analisis Teknikal","crypto":"Pasar dan Aset","stocks":"Saham"},"intro":"Panduan praktis ini menjelaskan “{title}” dengan aturan yang jelas untuk ditinjau dan diuji, bukan berdasarkan kesan atau janji.","body":"Tetapkan kondisi sebelum masuk: apa yang dicari pada grafik dan bukti apa yang mendukung ide tersebut? Tulis aturan yang terukur dan tentukan sebelumnya kapan ide itu tidak berlaku. Nilai konteks, jangan hanya mengandalkan satu candle atau level, dan bedakan probabilitas dari kepastian.","practice":"Terapkan ide pada data historis, lalu uji pada periode yang tidak digunakan untuk menyusun aturan. Catat biaya, slippage, drawdown maksimum, serta hasil di pasar tren dan sideways. Ubah satu aturan pada satu waktu agar dampaknya bisa dipahami.","warning":"Konten ini hanya untuk edukasi, bukan saran investasi. Pasar memiliki risiko dan hasil historis tidak menjamin hasil di masa depan."},
"zh":{"categories":{"risk":"风险管理","mindset":"交易心理","strategy":"策略测试","price":"价格行为","technical":"技术分析","crypto":"市场与资产","stocks":"股票"},"intro":"本指南以可复核、可测试的明确规则讲解“{title}”，而不是依赖主观印象或盈利承诺。","body":"入场前先定义条件：你在图表中寻找什么，哪些证据可以支持这一判断？写下可衡量的规则，并提前确定什么情况会使判断失效。评估整体市场背景，不要只依赖单根K线或单一价位，并区分概率与确定性。","practice":"先用历史数据检验，再使用未参与规则设计的独立时间段进行测试。记录手续费、滑点、最大回撤，以及趋势行情和震荡行情中的结果。每次只调整一项规则，才能看清变化的影响。","warning":"本文仅用于教育，不构成投资建议。市场存在风险，历史表现不保证未来结果。"}
}
def _build_multilingual_seo_posts():
    posts = []
    for topic in BLOG_TOPICS:
        for index, lang in enumerate(BLOG_LANGS):
            copy = BLOG_COPY[lang["code"]]
            title = topic["titles"][index]
            category = copy["categories"][topic["cat"]]
            slug = lang["code"] + "-" + topic["key"]
            description = copy["intro"].format(title=title)
            body = "\n\n".join([description, BLOG_GUIDANCE[topic["key"]][index], copy["body"], copy["practice"], copy["warning"]])
            posts.append({"slug":slug,"topic_key":topic["key"],"lang":lang["code"],"locale":lang["locale"],"dir":lang["dir"],"language_name":lang["name"],"category":category,"title":title,"description":description,"body":body})
    return posts
SEO_POSTS = _build_multilingual_seo_posts()


def _seo_escape(value):
    from html import escape
    return escape(str(value or ""), quote=True)


def _seo_post(slug):
    for post in SEO_POSTS:
        if post["slug"] == slug:
            return post
    legacy_slugs = {
        "risk-management-stop-loss": "ar-stop-loss",
        "ema50-ema200-trend-filter": "ar-ema-filter",
        "breakout-retest-price-action": "ar-breakout-retest",
        "liquidity-sweep-vs-market-structure": "ar-liquidity-sweep",
        "risk-reward-win-rate": "ar-risk-reward",
        "backtest-trading-strategy": "ar-backtesting",
    }
    if slug in legacy_slugs:
        legacy_post = next((p for p in SEO_POSTS if p["slug"] == legacy_slugs[slug]), None)
        if legacy_post:
            return {**legacy_post, "slug": slug}
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
    urls = [(SEO_BASE_URL + "/", "daily", "1.0"), (SEO_BASE_URL + "/blog", "weekly", "0.9")] + [(SEO_BASE_URL + p, "daily", "0.8") for p in ["/markets/spot", "/markets/futures", "/markets/contracts", "/markets/us-stocks", "/markets/saudi", "/markets/forex-gold", "/markets/alpha", "/tasi-analysis", "/analysis", "/results", "/news"]]
    urls.extend((SEO_BASE_URL + "/blog/" + p["slug"], "monthly", "0.7") for p in SEO_POSTS)
    urls.extend((SEO_BASE_URL + "/blog/" + slug, "monthly", "0.6") for slug in ["risk-management-stop-loss", "ema50-ema200-trend-filter", "breakout-retest-price-action", "liquidity-sweep-vs-market-structure", "risk-reward-win-rate", "backtest-trading-strategy"])
    urls.extend((SEO_BASE_URL + "/blog/" + str(p.get("slug") or p.get("id")), "monthly", "0.6") for p in read_json_file(ARTICLES_PATH, []) if p.get("slug") or p.get("id"))
    urls.extend((SEO_BASE_URL + "/analysis/" + slug, "monthly", "0.6") for slug in METHOD_SLUGS)
    items = "".join("<url><loc>" + xml_escape(url) + "</loc><changefreq>" + freq + "</changefreq><priority>" + priority + "</priority></url>" for url, freq, priority in urls)
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + items + "</urlset>"
    return HTMLResponse(xml, media_type="application/xml")


@app.get("/blog", response_class=HTMLResponse)
def seo_blog_index():
    enforce_section_access("blog")
    from html import escape
    posts = list(SEO_POSTS)
    dynamic = read_json_file(ARTICLES_PATH, [])
    for item in dynamic:
        slug = str(item.get("slug") or item.get("id") or "")
        if slug:
            posts.insert(0, {**item, "slug": slug, "description": item.get("summary") or str(item.get("body", ""))[:180], "lang": item.get("lang", "ar"), "language_name": item.get("language_name", "العربية")})
    cards = "".join(
        '<article class="post" data-lang="' + escape(str(p.get("lang") or "ar"), quote=True) + '" data-category="' + escape(str(p.get("category") or ""), quote=True).lower() + '"><p class="meta"><span class="category">' + escape(str(p.get("category", "تعليم التداول"))) + '</span><span class="lang">' + escape(str(p.get("language_name") or "العربية")) + '</span></p><h2><a href="/blog/' + escape(str(p["slug"]), quote=True) + '">' + escape(str(p["title"])) + '</a></h2><p>' + escape(str(p.get("description") or p.get("summary") or "")) + '</p><a class="read" href="/blog/' + escape(str(p["slug"]), quote=True) + '">اقرأ / Read →</a></article>'
        for p in posts
    )
    canonical = SEO_BASE_URL + "/blog"
    languages = "".join('<option value="' + escape(x["code"], quote=True) + '">' + escape(x["name"]) + '</option>' for x in BLOG_LANGS)
    blog_schema = json.dumps({"@context":"https://schema.org","@type":"Blog","name":"SMART TRADING PRO Trading Education","url":canonical,"inLanguage":[x["locale"] for x in BLOG_LANGS],"numberOfItems":len(posts)}, ensure_ascii=False).replace("</", "<\\/")
    html = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مدونة التداول | 200 مقال تعليمي بعشر لغات</title><meta name="description" content="مكتبة تعليمية متعددة اللغات عن تداول العملات الرقمية والأسهم والفوركس، التحليل الفني، حركة السعر، السيولة، اختبار الاستراتيجيات وإدارة المخاطر."><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '"><meta property="og:type" content="website"><meta property="og:locale" content="ar_SA"><meta property="og:title" content="مدونة التداول الذكي PRO | تعليم التداول بعشر لغات"><meta property="og:description" content="مقالات تعليمية عن التداول والتحليل وإدارة المخاطر بعشر لغات."><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">' + blog_schema + '</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:16px/1.9 system-ui,Tahoma,Arial}main{max-width:1120px;margin:auto;padding:24px 16px}a{color:#8dbaff;text-decoration:none}header,.filters,.post{background:#111b2a;border:1px solid #29384d;border-radius:16px;padding:20px;margin:12px 0}.site-nav{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#111b2a;border:1px solid #29384d;border-radius:14px;padding:10px;margin:0 0 14px}.site-nav a{padding:5px 10px;border-radius:8px;background:#17263a}header{background:linear-gradient(135deg,#16243a,#101827)}h1{font-size:clamp(28px,5vw,42px);line-height:1.35;margin:0 0 8px}h2{font-size:20px;line-height:1.5;margin:6px 0}.sub{color:#b9c7da}.filters{display:flex;gap:10px;flex-wrap:wrap}.filters input,.filters select{background:#080d18;color:#edf3ff;border:1px solid #40516a;border-radius:10px;padding:12px;min-width:180px;flex:1}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:12px}.post{margin:0;padding:18px}.meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:13px}.category{color:#54ddb0}.lang{color:#e4c27a}.read{font-weight:800}.count{color:#aebbd0;font-size:13px}.post p{overflow-wrap:anywhere}footer{color:#93a0b3;padding:22px 4px;font-size:13px}</style></head><body><main><nav><a href="/">الرئيسية</a>　<a href="/blog">المدونة</a></nav><header><p class="category">SMART TRADING PRO · EDUCATION</p><h1>مدونة التداول الذكي PRO</h1><p class="sub">200 مقال تعليمي بعشر لغات: من أساسيات التداول إلى التحليل الفني والسيولة واختبار الاستراتيجيات وإدارة المخاطر.</p><p class="sub">المحتوى تعليمي فقط ولا يمثل توصية شراء أو بيع ولا يضمن الأرباح.</p></header><section class="filters"><input id="blogSearch" type="search" placeholder="ابحث عن مقال أو موضوع… / Search articles" aria-label="بحث المقالات"><select id="blogLang" aria-label="اختر اللغة"><option value="">كل اللغات / All languages</option>' + languages + '</select><select id="blogCategory" aria-label="اختر التصنيف"><option value="">كل التصنيفات / All categories</option></select><span class="count" id="blogCount">200 مقال</span></section><section class="grid" id="blogGrid">' + cards + '</section><footer>راجع المخاطر والرسوم والانزلاق دائمًا. لا تضمن الاختبارات التاريخية الأداء المستقبلي.</footer></main><script>const cards=[...document.querySelectorAll(".post")],search=document.getElementById("blogSearch"),lang=document.getElementById("blogLang"),cat=document.getElementById("blogCategory"),count=document.getElementById("blogCount");[...new Set(cards.map(x=>x.dataset.category).filter(Boolean))].sort().forEach(x=>{const o=document.createElement("option");o.value=x;o.textContent=x;cat.appendChild(o)});function filterPosts(){const q=search.value.trim().toLowerCase();let shown=0;cards.forEach(c=>{const ok=(!lang.value||c.dataset.lang===lang.value)&&(!cat.value||c.dataset.category===cat.value)&&(!q||c.innerText.toLowerCase().includes(q));c.hidden=!ok;if(ok)shown++});count.textContent=shown+" / "+cards.length+" articles"}[search,lang,cat].forEach(x=>x.addEventListener("input",filterPosts));</script></body></html>'
    return HTMLResponse(html)


@app.get("/blog/{slug}", response_class=HTMLResponse)
def seo_blog_article(slug: str):
    enforce_section_access("blog")
    from html import escape
    post = _seo_post(slug)
    if not post:
        return HTMLResponse("<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><title>المقال غير موجود</title><h1>المقال غير موجود</h1><a href='/blog'>العودة للمدونة</a></html>", status_code=404)
    title = str(post.get("title") or "مقال تعليمي")
    description = str(post.get("description") or post.get("summary") or str(post.get("body") or "")[:180])
    body = str(post.get("body") or post.get("summary") or "")
    canonical = SEO_BASE_URL + "/blog/" + str(post.get("slug") or slug)
    lang_code = str(post.get("lang") or "ar")
    lang_info = next((x for x in BLOG_LANGS if x["code"] == lang_code), BLOG_LANGS[0])
    published = time.strftime("%Y-%m-%d", time.gmtime(int(post.get("published_at") or time.time())))
    topic_key = post.get("topic_key")
    alternates = "".join('<link rel="alternate" hreflang="' + escape(x["locale"], quote=True) + '" href="' + SEO_BASE_URL + '/blog/' + x["code"] + '-' + escape(str(topic_key), quote=True) + '">' for x in BLOG_LANGS) if topic_key else ""
    article_json = json.dumps({"@context":"https://schema.org","@type":"Article","headline":title,"description":description,"datePublished":published,"dateModified":published,"inLanguage":lang_info["locale"],"mainEntityOfPage":canonical,"author":{"@type":"Organization","name":"التداول الذكي PRO"},"publisher":{"@type":"Organization","name":"التداول الذكي PRO"}}, ensure_ascii=False).replace("</", "<\\/")
    paragraphs = "".join("<p>" + escape(p.strip()) + "</p>" for p in body.splitlines() if p.strip()) or "<p>" + escape(body) + "</p>"
    html = '<!doctype html><html lang="' + escape(lang_info["code"], quote=True) + '" dir="' + escape(lang_info["dir"], quote=True) + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + ' | SMART TRADING PRO</title><meta name="description" content="' + escape(description[:300], quote=True) + '"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '">' + alternates + '<meta property="og:type" content="article"><meta property="og:locale" content="' + escape(lang_info["locale"].replace("-", "_"), quote=True) + '"><meta property="og:title" content="' + escape(title, quote=True) + '"><meta property="og:description" content="' + escape(description[:300], quote=True) + '"><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">' + article_json + '</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:17px/2 system-ui,Tahoma,Arial}main{max-width:820px;margin:auto;padding:24px 16px}a{color:#8dbaff;text-decoration:none}.site-nav{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#111b2a;border:1px solid #29384d;border-radius:14px;padding:10px;margin:0 0 14px}.site-nav a{padding:5px 10px;border-radius:8px;background:#17263a}.crumb{font-size:13px;color:#93a0b3}.lang{color:#e4c27a;font-size:13px}article{background:#111b2a;border:1px solid #29384d;border-radius:18px;padding:clamp(20px,5vw,42px);margin-top:18px}.category{color:#54ddb0;font-size:13px;font-weight:800}h1{font-size:clamp(28px,5vw,42px);line-height:1.4}p{margin:18px 0;overflow-wrap:anywhere}footer{color:#93a0b3;font-size:13px;margin-top:24px}</style></head><body><main><nav class="site-nav" aria-label="التنقل الرئيسي"><a href="/">الرئيسية</a><a href="/markets/spot">سبوت</a><a href="/markets/futures">فيوتشر</a><a href="/markets/saudi">السوق السعودي</a><a href="/tasi-analysis">تحليل تاسي</a><a href="/news">الأخبار</a><a href="/analysis">مناهج التحليل</a><a href="/account">الحساب</a></nav><p class="crumb"><a href="/">الرئيسية / Home</a> / <a href="/blog">المدونة / Blog</a></p><article><p class="category">' + escape(str(post.get("category") or "Trading Education")) + '</p><p class="lang">' + escape(lang_info["name"]) + '</p><h1>' + escape(title) + '</h1><p>' + escape(description) + '</p>' + paragraphs + '<p><strong>Important:</strong> Educational content only. This is not a buy/sell recommendation or a promise of returns.</p></article><footer><a href="/blog">← جميع المقالات / All articles</a></footer></main></body></html>'
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
@app.get("/tasi-analysis", response_class=HTMLResponse)
@app.get("/market/{market_slug}", include_in_schema=False)
def legacy_market_redirect(market_slug: str):
    """Keep old singular market URLs working after the site moved to /markets/."""
    destinations = {
        "spot": "/markets/spot",
        "futures": "/markets/futures",
        "contracts": "/markets/contracts",
        "us-stocks": "/markets/us-stocks",
        "saudi": "/markets/saudi",
        "forex-gold": "/markets/forex-gold",
        "alpha": "/markets/alpha",
    }
    target = destinations.get(market_slug.lower())
    if target is None:
        return JSONResponse({"ok": False, "message": "صفحة السوق غير موجودة."}, status_code=404)
    return RedirectResponse(url=target, status_code=308)


@app.get("/trades", include_in_schema=False)
@app.get("/radar", include_in_schema=False)
@app.get("/gold", include_in_schema=False)
def retired_trade_boards_redirect():
    """Retired duplicate trade boards now return users to the dedicated market list."""
    return RedirectResponse(url="/markets/spot", status_code=308)


@app.get("/markets/spot", response_class=HTMLResponse)
@app.get("/markets/futures", response_class=HTMLResponse)
@app.get("/markets/contracts", response_class=HTMLResponse)
@app.get("/markets/us-stocks", response_class=HTMLResponse)
@app.get("/markets/saudi", response_class=HTMLResponse)
@app.get("/markets/forex-gold", response_class=HTMLResponse)
@app.get("/markets/alpha", response_class=HTMLResponse)
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
        "/tasi-analysis": ("تحليل المؤشر العام لتاسي | التداول الذكي PRO", "تحليل اتجاه المؤشر العام للسوق السعودي تاسي، تغيراته ومستوياته الفنية عبر عدة أطر زمنية."),
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
        quote_rows = (item.get("indicators", {}).get("quote") or [{}])[0]
        volumes = quote_rows.get("volume") or []
        valid_volumes = [v for v in volumes if v is not None]
        daily_volume = int(valid_volumes[-1]) if valid_volumes else int(meta.get("regularMarketVolume") or 0)
        dollar_volume = price * daily_volume
        return {
            "symbol": symbol, "name": YAHOO_LABELS.get(symbol, symbol.replace(".SR", "")),
            "price": price,
            "change_pct": ((price - previous) / previous * 100) if previous else 0.0,
            "volume": daily_volume, "quote_volume": dollar_volume, "dollar_volume": dollar_volume,
            "currency": meta.get("currency", ""),
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "Yahoo Finance",
            "quote_time": meta.get("regularMarketTime"), "delayed": True,
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError, KeyError):
        return None


@app.get("/api/market/{market}")
def market_data(market: str, limit: int = Query(500, ge=1, le=2000)):
    market = market.lower()
    if market == "saudi":
        old_symbols = len(YAHOO_MARKETS["saudi"])
        _load_saudi_symbols()
        if len(YAHOO_MARKETS["saudi"]) != old_symbols:
            YAHOO_CACHE.pop("saudi", None)
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
            # Apply the $1M daily dollar-turnover rule to US equities only.
            # Saudi equities are intentionally exempt; keep every listed TASI stock only; NOMU is excluded.
            if market == "us":
                data = [item for item in data if item.get("dollar_volume", 0) >= 1_000_000]
                if not data:
                    return {"ok": True, "market": market, "live": True, "provider": "Yahoo Finance",
                            "delayed": True, "updated_at": int(now), "items": [],
                            "message": "لا توجد أسهم أمريكية مستوفية لسيولة مليون دولار يوميًا في البيانات المتاحة."}
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




# Correlated aliases/proxies count as one independent confirmation family.
METHOD_FAMILY_OVERRIDES = {
    "smc": "structure_smc_ict", "ict": "structure_smc_ict", "bos_choch": "structure_smc_ict",
    "order_blocks": "structure_smc_ict", "breaker_blocks": "structure_smc_ict", "mitigation_blocks": "structure_smc_ict",
    "unicorn_model": "structure_smc_ict", "ict_ote": "structure_smc_ict", "ict_kill_zone": "structure_smc_ict",
    "fvg": "imbalance", "fvg_retest": "imbalance", "liquidity_void": "imbalance", "volume_imbalance": "imbalance",
    "liquidity_sweep": "liquidity_reversal", "turtle_soup": "liquidity_reversal", "failed_breakout": "liquidity_reversal",
    "liquidity_reclaim": "liquidity_reversal", "judas_swing": "liquidity_reversal", "wyckoff_spring": "liquidity_reversal",
    "wyckoff_upthrust": "liquidity_reversal", "range_liquidity_reclaim": "liquidity_reversal",
    "vwap": "vwap_value", "anchored_vwap": "vwap_value", "vwap_reclaim": "vwap_value",
    "mean_reversion": "mean_reversion", "zscore_reversion": "mean_reversion", "rsi_reversal": "mean_reversion",
    "connors_rsi": "mean_reversion", "stochastic": "mean_reversion", "williams_r": "mean_reversion",
    "bollinger_bands": "mean_reversion",
    "breakout": "breakout_channel", "volatility_breakout": "breakout_channel", "atr_breakout": "breakout_channel",
    "donchian": "breakout_channel", "price_channel": "breakout_channel", "channel_breakout": "breakout_channel",
    "pivot_breakout": "breakout_channel", "orb": "breakout_channel", "session_range": "breakout_channel",
    "range_expansion": "breakout_channel", "range_compression": "breakout_channel",
    "relative_volume_breakout": "breakout_channel", "darvas_box": "breakout_channel",
    "turtle_trading": "breakout_channel", "fractal_breakout": "breakout_channel",
    "momentum": "trend_momentum", "trend_following": "trend_momentum", "dual_momentum": "trend_momentum",
    "relative_strength": "trend_momentum", "macd": "trend_momentum", "ppo": "trend_momentum",
    "trix": "trend_momentum", "kama": "trend_momentum", "tema": "trend_momentum",
    "elder_impulse": "trend_momentum", "supertrend": "trend_momentum", "aroon": "trend_momentum",
    "vortex": "trend_momentum", "dmi": "trend_momentum", "adx_trend": "trend_momentum",
    "cvd_proxy": "ohlcv_volume_proxy", "footprint_proxy": "ohlcv_volume_proxy", "absorption": "ohlcv_volume_proxy",
    "order_flow": "ohlcv_volume_proxy", "market_profile": "ohlcv_volume_proxy", "volume_profile": "ohlcv_volume_proxy",
    "obv_trend": "ohlcv_volume_proxy", "accumulation_distribution": "ohlcv_volume_proxy", "pvt": "ohlcv_volume_proxy",
    "chaikin_oscillator": "ohlcv_volume_proxy", "chaikin_money_flow": "ohlcv_volume_proxy",
    "ease_movement": "ohlcv_volume_proxy", "volume_climax": "ohlcv_volume_proxy",
    "relative_volume_climax": "ohlcv_volume_proxy", "klinger_oscillator": "ohlcv_volume_proxy",
    "wyckoff_effort_result": "ohlcv_volume_proxy", "failed_auction": "ohlcv_volume_proxy",
    "candlestick": "candlestick_reversal", "three_bar_reversal": "candlestick_reversal",
    "outside_bar": "candlestick_reversal", "three_line_strike": "candlestick_reversal",
    "marubozu": "candlestick_reversal", "doji_reversal": "candlestick_reversal", "star_pattern": "candlestick_reversal",
    "piercing_dark_cloud": "candlestick_reversal", "tweezer": "candlestick_reversal", "key_reversal": "candlestick_reversal",
    "support_resistance": "levels_fibonacci", "pivot_points": "levels_fibonacci", "pivot_reversal": "levels_fibonacci",
    "fib_confluence": "levels_fibonacci", "fibonacci": "levels_fibonacci", "fib_extension": "levels_fibonacci",
    "multi_swing_ote": "levels_fibonacci", "premium_discount": "levels_fibonacci",
    "gartley": "harmonic_patterns", "bat_pattern": "harmonic_patterns", "butterfly_pattern": "harmonic_patterns",
    "crab_pattern": "harmonic_patterns", "shark_pattern": "harmonic_patterns", "harmonic": "harmonic_patterns",
    "chart_patterns": "chart_patterns", "triple_top_bottom": "chart_patterns", "head_shoulders": "chart_patterns",
    "inverse_head_shoulders": "chart_patterns", "wedge": "chart_patterns", "flag": "chart_patterns",
    "pennant": "chart_patterns", "cup_handle": "chart_patterns", "rectangle": "chart_patterns",
    "rounding_pattern": "chart_patterns", "three_drives": "chart_patterns", "wolfe_waves": "chart_patterns",
    "andrews_pitchfork": "channels_trendlines", "channels": "channels_trendlines",
    "linear_regression_channel": "channels_trendlines", "stddev_channel": "channels_trendlines",
    "range_trading": "range_context", "regime": "range_context", "choppiness": "range_context",
}
def method_family(method_key):
    return METHOD_FAMILY_OVERRIDES.get(method_key, method_key)


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
    "Gann": "gann",
    # Expanded method catalogue: OHLCV-capable rules are evaluated below; data-heavy methods are explicitly labeled approximations.
    "SMT Divergence": "smt_divergence", "Power of Three (AMD)": "power_of_three",
    "Judas Swing": "judas_swing", "Turtle Soup": "turtle_soup",
    "Unicorn Model": "unicorn_model", "Breaker Blocks": "breaker_blocks",
    "Mitigation Blocks": "mitigation_blocks", "Liquidity Void": "liquidity_void",
    "Donchian Channels": "donchian", "Keltner Channels": "keltner",
    "Heikin Ashi": "heikin_ashi", "Renko Approximation": "renko",
    "Point & Figure Approximation": "point_figure", "Opening Range Breakout": "orb",
    "Inside Bar Breakout": "inside_bar", "Outside Bar Reversal": "outside_bar",
    "Three-Bar Reversal": "three_bar_reversal", "Gap Trading": "gap_trading",
    "Cumulative Volume Delta Proxy": "cvd_proxy", "Footprint Proxy": "footprint_proxy",
    "Market Profile / TPO Proxy": "market_profile", "Anchored VWAP Proxy": "anchored_vwap",
    "Volume Imbalance": "volume_imbalance", "Absorption Proxy": "absorption",
    "Open Interest / Funding": "oi_funding",
    "Pairs Trading Proxy": "pairs_trading", "Statistical Arbitrage Proxy": "stat_arb",
    "Cointegration Proxy": "cointegration", "Z-Score Reversion": "zscore_reversion",
    "Relative Strength": "relative_strength", "Cross-Market Correlation": "cross_market",
    "Seasonality": "seasonality", "Volatility Breakout": "volatility_breakout",
    "Turtle Trading": "turtle_trading", "Supertrend": "supertrend",
    "ATR Breakout": "atr_breakout", "Pivot Points": "pivot_points",
    "Parabolic SAR Proxy": "parabolic_sar", "Chandelier Exit": "chandelier_exit",
    "Dual Momentum": "dual_momentum", "Bollinger Bands": "bollinger_bands",
    "MACD": "macd", "RSI Reversal": "rsi_reversal", "Stochastic": "stochastic",
    "ADX Trend Filter": "adx_trend", "OBV Trend": "obv_trend",
    "Accumulation / Distribution": "accumulation_distribution",
    "CCI": "cci", "Williams %R": "williams_r", "Money Flow Index": "mfi",
    "Rate of Change": "roc", "TRIX": "trix", "DMI / DI Cross": "dmi",
    "Elder Ray": "elder_ray", "KAMA Trend": "kama", "TEMA Trend": "tema",
    "Triple Top / Bottom": "triple_top_bottom", "Head & Shoulders": "head_shoulders",
    "Inverse Head & Shoulders": "inverse_head_shoulders", "Rising / Falling Wedge": "wedge",
    "Bull / Bear Flag": "flag", "Pennant Breakout": "pennant",
    "Cup & Handle Approximation": "cup_handle", "Rectangle Breakout": "rectangle",
    "Rounding Bottom / Top": "rounding_pattern", "Three Drives": "three_drives",
    "Key Reversal Day": "key_reversal", "NR7 / Narrow Range": "nr7",
    "Volatility Contraction Pattern": "vcp", "Darvas Box": "darvas_box",
    "Elder Triple Screen Proxy": "triple_screen", "Ichimoku Kumo Breakout": "kumo_breakout",
    "Fisher Transform Proxy": "fisher_transform", "Chaikin Money Flow": "chaikin_money_flow",
    "Force Index": "force_index", "Ulcer Index Risk Filter": "ulcer_filter",
    "Aroon Trend": "aroon", "Vortex Indicator": "vortex", "Choppiness Index": "choppiness",
    "Ultimate Oscillator": "ultimate_oscillator", "Relative Vigor Index": "rvi",
    "True Strength Index": "tsi", "Percentage Price Oscillator": "ppo",
    "Detrended Price Oscillator": "dpo", "Price Channel Breakout": "price_channel",
    "Connors RSI Proxy": "connors_rsi", "Elder Impulse System": "elder_impulse",
    "Three-Line Strike": "three_line_strike", "Marubozu Candle": "marubozu",
    "Doji Reversal": "doji_reversal", "Morning / Evening Star": "star_pattern",
    "Piercing / Dark Cloud": "piercing_dark_cloud", "Tweezer Top / Bottom": "tweezer",
    "Gap-and-Go": "gap_go", "Failed Breakout": "failed_breakout",
    "Liquidity Grab & Reclaim": "liquidity_reclaim", "Range Expansion": "range_expansion",
    "ATR Trailing Stop": "atr_trailing", "Volatility Stop": "volatility_stop",
    "Pivot Reversal": "pivot_reversal", "Fibonacci Retracement Confluence": "fib_confluence",
    "Trendline Break & Retest": "trendline_retest", "Channel Breakout": "channel_breakout",
    "Volume Climax": "volume_climax", "Price-Volume Trend": "pvt",
    "Chaikin Oscillator Proxy": "chaikin_oscillator", "Ease of Movement": "ease_movement",
    "Relative Volume Breakout": "relative_volume_breakout", "VWAP Reclaim": "vwap_reclaim",
    "Opening Gap Reversal": "gap_reversal", "Range Compression Breakout": "range_compression",
    "Williams Alligator Proxy": "alligator", "Fractal Breakout": "fractal_breakout",
    "Fibonacci Extension": "fib_extension", "Classic Pivot Breakout": "pivot_breakout",
    "Fair Value Gap Retest": "fvg_retest", "Equal Highs / Lows": "equal_highs_lows",
    "Premium / Discount Zones": "premium_discount", "Session Range Breakout": "session_range",
    "Risk Management": "risk_management",
    "Wyckoff Spring": "wyckoff_spring", "Wyckoff Upthrust": "wyckoff_upthrust",
    "Wyckoff SOS / SOW": "wyckoff_sos_sow", "Wyckoff LPS / LPSY": "wyckoff_lps",
    "ICT Optimal Trade Entry (OTE) Proxy": "ict_ote",
    "ICT Kill Zone": "ict_kill_zone", "Gartley Pattern Proxy": "gartley",
    "Bat Pattern Proxy": "bat_pattern", "Butterfly Pattern Proxy": "butterfly_pattern",
    "Crab Pattern Proxy": "crab_pattern", "Shark Pattern Proxy": "shark_pattern",
    "Andrews Pitchfork Proxy": "andrews_pitchfork", "Wolfe Waves Proxy": "wolfe_waves",
    "TTM Squeeze Proxy": "ttm_squeeze", "Coppock Curve": "coppock_curve",
    "Klinger Oscillator Proxy": "klinger_oscillator", "Schaff Trend Cycle Proxy": "schaff_cycle",
    "Hurst Exponent Filter": "hurst_filter", "Hurst Cycle Proxy": "hurst_cycle",
    "Adaptive Moving Average Crossover": "adaptive_ma", "McGinley Dynamic Proxy": "mcginley",
    "Linear Regression Channel": "linear_regression_channel", "Standard Deviation Channel": "stddev_channel",
    "Donchian Midline Reversal": "donchian_midline", "Volatility-Adjusted Momentum": "vol_adjusted_momentum",
    "Relative Volume Climax Reversal": "relative_volume_climax", "Accumulation / Distribution Divergence": "ad_divergence",
    "Wyckoff Effort vs Result": "wyckoff_effort_result", "Failed Auction Proxy": "failed_auction",
    "Range Liquidity Reclaim": "range_liquidity_reclaim", "Multi-Swing Fibonacci OTE": "multi_swing_ote"
}


def method_signal(candles, ticker, method_key):
    """Evaluate method-specific OHLCV setups; unavailable auxiliary data must not be fabricated."""
    if not isinstance(candles, list) or len(candles) < 30:
        return None
    c = candles
    try:
        closes = [float(x["close"]) for x in c]
        highs = [float(x["high"]) for x in c]
        lows = [float(x["low"]) for x in c]
        opens = [float(x["open"]) for x in c]
        volumes = [max(0.0, float(x.get("volume", 0) or 0)) for x in c]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    # Reject malformed OHLCV instead of allowing bad prices to create a signal.
    for o, h, l, close, volume in zip(opens, highs, lows, closes, volumes):
        if not all(math.isfinite(v) for v in (o, h, l, close, volume)):
            return None
        if min(o, h, l, close) <= 0 or h < max(o, l, close) or l > min(o, h, close):
            return None
    last, prev = c[-1], c[-2]
    price = closes[-1]
    if price <= 0:
        return None

    def mean(values):
        return sum(values) / len(values) if values else 0.0

    def pivots(values, is_high, left=2, right=2):
        out = []
        for i in range(left, len(values) - right):
            segment = values[i-left:i+right+1]
            if values[i] == (max(segment) if is_high else min(segment)):
                if not out or out[-1][0] != i:
                    out.append((i, values[i]))
        return out

    def rsi(values, period=14):
        if len(values) <= period:
            return None
        changes = [values[i] - values[i-1] for i in range(1, len(values))]
        gains = [max(x, 0.0) for x in changes[-period:]]
        losses = [max(-x, 0.0) for x in changes[-period:]]
        avg_gain, avg_loss = mean(gains), mean(losses)
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    prior_high, prior_low = max(highs[-21:-1]), min(lows[-21:-1])
    avg_vol = mean(volumes[-21:-1])
    candle_range = max(highs[-1] - lows[-1], 1e-12)
    body = price - opens[-1]
    bullish, bearish = body > 0, body < 0
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    true_ranges = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
                   for i in range(1, len(c))]
    atr = mean(true_ranges[-14:])
    if atr <= 0:
        atr = max(price * 0.002, 1e-12)

    # This is rolling candle-based VWAP, not session VWAP: timestamps/session boundaries are not supplied here.
    vwap_den = sum(volumes[-20:])
    rolling_vwap = sum(((highs[i]+lows[i]+closes[i])/3.0)*volumes[i]
                       for i in range(len(c)-20, len(c))) / vwap_den if vwap_den > 0 else None
    side = None
    swing_highs, swing_lows = pivots(highs, True), pivots(lows, False)
    recent_sh = [p for p in swing_highs if p[0] < len(c)-2][-3:]
    recent_sl = [p for p in swing_lows if p[0] < len(c)-2][-3:]
    prev_sh = recent_sh[-1][1] if recent_sh else prior_high
    prev_sl = recent_sl[-1][1] if recent_sl else prior_low
    bullish_structure = (len(recent_sh) >= 2 and len(recent_sl) >= 2 and
                         recent_sh[-1][1] > recent_sh[-2][1] and recent_sl[-1][1] > recent_sl[-2][1])
    bearish_structure = (len(recent_sh) >= 2 and len(recent_sl) >= 2 and
                         recent_sh[-1][1] < recent_sh[-2][1] and recent_sl[-1][1] < recent_sl[-2][1])
    broke_up, broke_down = price > prev_sh and bullish, price < prev_sl and bearish
    rsi_now = rsi(closes)

    if method_key == "price_action":
        if bullish and price > closes[-2] and body / candle_range >= 0.35: side = "BUY"
        elif bearish and price < closes[-2] and -body / candle_range >= 0.35: side = "SELL"
    elif method_key == "smc":
        swept_low = min(lows[-5:-1]) < prev_sl and price > prev_sl
        swept_high = max(highs[-5:-1]) > prev_sh and price < prev_sh
        if (broke_up and bullish_structure) or (swept_low and bullish and price > closes[-2]): side = "BUY"
        elif (broke_down and bearish_structure) or (swept_high and bearish and price < closes[-2]): side = "SELL"
    elif method_key == "ict":
        bull_fvg = highs[-3] < lows[-1]
        bear_fvg = lows[-3] > highs[-1]
        displacement = abs(body) >= atr * 0.8
        if bull_fvg and bullish and displacement and (e50 is None or price >= e50): side = "BUY"
        elif bear_fvg and bearish and displacement and (e50 is None or price <= e50): side = "SELL"
    elif method_key == "order_flow":
        # OHLCV cannot provide true bid/ask aggressor flow; this is a volume-pressure proxy only.
        close_location = (price-lows[-1])/candle_range
        if avg_vol > 0 and volumes[-1] >= avg_vol*1.5:
            if bullish and close_location >= 0.75: side = "BUY"
            elif bearish and close_location <= 0.25: side = "SELL"
    elif method_key == "bos_choch":
        if broke_up and not bearish_structure: side = "BUY"
        elif broke_down and not bullish_structure: side = "SELL"
    elif method_key == "liquidity_sweep":
        if lows[-1] < prev_sl and price > prev_sl and bullish: side = "BUY"
        elif highs[-1] > prev_sh and price < prev_sh and bearish: side = "SELL"
    elif method_key == "fvg":
        if highs[-3] < lows[-1] and bullish and price > closes[-2]: side = "BUY"
        elif lows[-3] > highs[-1] and bearish and price < closes[-2]: side = "SELL"
    elif method_key == "retest":
        tol = max(atr*0.25, price*0.001)
        if abs(lows[-1]-prev_sh) <= tol and price > prev_sh and bullish: side = "BUY"
        elif abs(highs[-1]-prev_sl) <= tol and price < prev_sl and bearish: side = "SELL"
    elif method_key == "vsa":
        avg_range = mean([highs[i]-lows[i] for i in range(max(0,len(c)-16),len(c)-1)])
        loc = (price-lows[-1])/candle_range
        if avg_vol > 0 and avg_range > 0 and volumes[-1] >= avg_vol*1.5 and candle_range < avg_range*0.8:
            if loc >= 0.7 and bullish: side = "BUY"
            elif loc <= 0.3 and bearish: side = "SELL"
    elif method_key == "regime":
        recent_vol = mean([highs[i]-lows[i] for i in range(len(c)-20,len(c))])/price
        if e20 is not None and e50 is not None and abs(e20-e50)/price > max(0.001,recent_vol*0.08):
            if e20 > e50 and price > e20: side = "BUY"
            elif e20 < e50 and price < e20: side = "SELL"
    elif method_key == "dow_mtf":
        # This is swing-structure confirmation on one timeframe; true MTF needs multiple timeframe data.
        if bullish_structure and price > e50: side = "BUY"
        elif bearish_structure and price < e50: side = "SELL"
    elif method_key == "support_resistance":
        tol = max(atr*0.4, price*0.002)
        if abs(lows[-1]-prev_sl) <= tol and bullish and price > closes[-2]: side = "BUY"
        elif abs(highs[-1]-prev_sh) <= tol and bearish and price < closes[-2]: side = "SELL"
    elif method_key == "momentum":
        move = (price-closes[-6])/max(closes[-6],1e-12)
        if move >= 0.004 and bullish: side = "BUY"
        elif move <= -0.004 and bearish: side = "SELL"
    elif method_key == "candlestick":
        prev_body = abs(closes[-2]-opens[-2])
        body_size = abs(body)
        lower_wick = min(price,opens[-1])-lows[-1]
        upper_wick = highs[-1]-max(price,opens[-1])
        if bullish and closes[-2] < opens[-2] and price >= opens[-2] and opens[-1] <= closes[-2] and body_size >= prev_body*0.8:
            side = "BUY"
        elif bearish and closes[-2] > opens[-2] and price <= opens[-2] and opens[-1] >= closes[-2] and body_size >= prev_body*0.8:
            side = "SELL"
        elif bullish and lower_wick >= body_size*2 and upper_wick <= max(body_size,atr*0.1) and price > closes[-2]:
            side = "BUY"
        elif bearish and upper_wick >= body_size*2 and lower_wick <= max(body_size,atr*0.1) and price < closes[-2]:
            side = "SELL"
    elif method_key == "chart_patterns":
        hs, ls = swing_highs[-4:], swing_lows[-4:]
        tol = max(atr*0.5,price*0.003)
        if len(hs)>=2 and abs(hs[-1][1]-hs[-2][1])<=tol and ls and price<ls[-1][1] and bearish: side="SELL"
        elif len(ls)>=2 and abs(ls[-1][1]-ls[-2][1])<=tol and hs and price>hs[-1][1] and bullish: side="BUY"
    elif method_key == "classical":
        if broke_up: side="BUY"
        elif broke_down: side="SELL"
        elif abs(price-prev_sl)<=max(atr*0.35,price*0.0015) and bullish: side="BUY"
        elif abs(price-prev_sh)<=max(atr*0.35,price*0.0015) and bearish: side="SELL"
    elif method_key == "order_blocks":
        for i in range(max(1,len(c)-6),len(c)-1):
            if broke_up and closes[i]<opens[i] and price>highs[i] and price-closes[i]>=atr:
                side="BUY"; break
            if broke_down and closes[i]>opens[i] and price<lows[i] and closes[i]-price>=atr:
                side="SELL"; break
    elif method_key == "breakout":
        if price>max(highs[-21:-1]) and bullish and body>=atr*0.15: side="BUY"
        elif price<min(lows[-21:-1]) and bearish and -body>=atr*0.15: side="SELL"
    elif method_key == "trend_following":
        if e20 is not None and e50 is not None and e200 is not None:
            if price>e20>e50>e200 and bullish_structure: side="BUY"
            elif price<e20<e50<e200 and bearish_structure: side="SELL"
    elif method_key == "mean_reversion":
        mean20=mean(closes[-20:])
        deviation=(price-mean20)/max(mean20,1e-12)
        if deviation<=-0.02 and (bullish or (rsi_now is not None and rsi_now<30)): side="BUY"
        elif deviation>=0.02 and (bearish or (rsi_now is not None and rsi_now>70)): side="SELL"
    elif method_key == "range_trading":
        rh,rl=max(highs[-20:]),min(lows[-20:])
        size=rh-rl
        if size>0 and size/price<0.08:
            if price<=rl+size*0.15 and bullish: side="BUY"
            elif price>=rh-size*0.15 and bearish: side="SELL"
    elif method_key == "volume_profile":
        # Candle-volume histogram proxy; no trade-level volume-at-price data is available.
        sample=c[-50:]
        p_lo=min(x["low"] for x in sample); p_hi=max(x["high"] for x in sample)
        if p_hi>p_lo and sum(volumes[-len(sample):])>0:
            bins=[0.0]*24
            for x in sample:
                typical=(x["high"]+x["low"]+x["close"])/3.0
                idx=min(23,max(0,int((typical-p_lo)/(p_hi-p_lo)*24)))
                bins[idx]+=max(0.0,x.get("volume",0) or 0)
            poc=p_lo+(max(range(24),key=lambda i:bins[i]+0.0)+0.5)*(p_hi-p_lo)/24
            if price>poc and bullish and price>closes[-2]: side="BUY"
            elif price<poc and bearish and price<closes[-2]: side="SELL"
    elif method_key == "vwap":
        if rolling_vwap is not None:
            if price>rolling_vwap and closes[-2]<=rolling_vwap and bullish: side="BUY"
            elif price<rolling_vwap and closes[-2]>=rolling_vwap and bearish: side="SELL"
    elif method_key == "indicators":
        if e20 is not None and e50 is not None and rsi_now is not None:
            if price>e20>e50 and rsi_now>=52: side="BUY"
            elif price<e20<e50 and rsi_now<=48: side="SELL"
    elif method_key == "divergence":
        # Price pivot vs RSI at that pivot; confirmed pivots avoid using unconfirmed latest turns.
        rsi_by_idx={}
        for end in range(15,len(closes)+1):
            value=rsi(closes[:end])
            if value is not None: rsi_by_idx[end-1]=value
        pl=[p for p in swing_lows if p[0] in rsi_by_idx][-2:]
        ph=[p for p in swing_highs if p[0] in rsi_by_idx][-2:]
        if len(pl)==2 and pl[1][1]<pl[0][1] and rsi_by_idx[pl[1][0]]>rsi_by_idx[pl[0][0]] and bullish:
            side="BUY"
        elif len(ph)==2 and ph[1][1]>ph[0][1] and rsi_by_idx[ph[1][0]]<rsi_by_idx[ph[0][0]] and bearish:
            side="SELL"
    elif method_key == "fibonacci":
        if recent_sh and recent_sl:
            sh,sl=recent_sh[-1],recent_sl[-1]
            if sl[0]<sh[0] and sh[1]>sl[1]:
                impulse=sh[1]-sl[1]; retr=(sh[1]-price)/max(impulse,1e-12)
                if 0.5<=retr<=0.618 and bullish and price>sl[1]: side="BUY"
            elif sh[0]<sl[0] and sh[1]>sl[1]:
                impulse=sh[1]-sl[1]; retr=(price-sl[1])/max(impulse,1e-12)
                if 0.5<=retr<=0.618 and bearish and price<sh[1]: side="SELL"
    elif method_key == "ichimoku":
        if len(c)>=52:
            tenkan=(max(highs[-9:])+min(lows[-9:]))/2
            kijun=(max(highs[-26:])+min(lows[-26:]))/2
            span_a=(tenkan+kijun)/2
            span_b=(max(highs[-52:])+min(lows[-52:]))/2
            cloud_top,cloud_bottom=max(span_a,span_b),min(span_a,span_b)
            if price>cloud_top and tenkan>kijun: side="BUY"
            elif price<cloud_bottom and tenkan<kijun: side="SELL"
    elif method_key == "wyckoff":
        if avg_vol>0 and volumes[-1]>=avg_vol*1.3:
            loc=(price-lows[-1])/candle_range
            if lows[-1]<prior_low and price>prior_low and loc>0.6: side="BUY"
            elif highs[-1]>prior_high and price<prior_high and loc<0.4: side="SELL"
    elif method_key == "elliott":
        # A swing-structure approximation only; automatic OHLCV cannot reliably certify discretionary wave counts.
        swings=sorted(recent_sh+recent_sl,key=lambda p:p[0])[-5:]
        if len(swings)==5:
            hs=[v for i,v in swings if any(i==p[0] for p in swing_highs)]
            ls=[v for i,v in swings if any(i==p[0] for p in swing_lows)]
            if len(hs)>=2 and len(ls)>=2 and all(hs[i]<hs[i+1] for i in range(len(hs)-1)) and all(ls[i]<ls[i+1] for i in range(len(ls)-1)) and bullish:
                side="BUY"
            elif len(hs)>=2 and len(ls)>=2 and all(hs[i]>hs[i+1] for i in range(len(hs)-1)) and all(ls[i]>ls[i+1] for i in range(len(ls)-1)) and bearish:
                side="SELL"
    elif method_key == "harmonic":
        swings=sorted((pivots(highs,True)+pivots(lows,False)),key=lambda p:p[0])[-5:]
        if len(swings)==5:
            x,a,b,cc,d=[p[1] for p in swings]
            xa,ab,bc,cd=abs(a-x),abs(b-a),abs(cc-b),abs(d-cc)
            if min(xa,ab,bc)>0:
                rab,rbc,rcd=ab/xa,bc/ab,cd/bc
                if 0.55<=rab<=0.72 and 0.35<=rbc<=0.90 and 1.1<=rcd<=1.8:
                    if bullish and d<=min(x,b,cc): side="BUY"
                    elif bearish and d>=max(x,b,cc): side="SELL"
    elif method_key == "channels":
        if len(c)>=12:
            hi_slope=(mean(highs[-5:])-mean(highs[-10:-5]))/5
            lo_slope=(mean(lows[-5:])-mean(lows[-10:-5]))/5
            if hi_slope>0 and lo_slope>0 and abs(hi_slope-lo_slope)<=atr*0.35 and bullish: side="BUY"
            elif hi_slope<0 and lo_slope<0 and abs(hi_slope-lo_slope)<=atr*0.35 and bearish: side="SELL"
    elif method_key == "quant":
        returns=[closes[i]/closes[i-1]-1 for i in range(max(1,len(closes)-20),len(closes))]
        avg_ret=mean(returns)
        vol_ret=mean([(x-avg_ret)**2 for x in returns])**0.5 if returns else 0
        zscore=(price-mean(closes[-20:]))/max(mean(closes[-20:])*vol_ret*(20**0.5),1e-12)
        if zscore>0.5 and avg_ret>0: side="BUY"
        elif zscore< -0.5 and avg_ret<0: side="SELL"
    elif method_key == "gann":
        # ATR-normalized slope proxy; true Gann angles require a defined chart scale/anchor.
        move=(price-closes[-10])/max(atr*9,1e-12)
        if move>=1.0 and bullish: side="BUY"
        elif move<=-1.0 and bearish: side="SELL"

    # Extended OHLCV rule set. Methods needing unavailable tick/order-book/cross-asset data are marked proxies or return no signal.
    elif method_key in ("donchian", "turtle_trading"):
        upper=max(highs[-21:-1]); lower=min(lows[-21:-1])
        if price>upper and bullish: side="BUY"
        elif price<lower and bearish: side="SELL"
    elif method_key == "keltner":
        mid=ema(closes,20); width=atr*2
        if mid is not None and price>mid+width and bullish: side="BUY"
        elif mid is not None and price<mid-width and bearish: side="SELL"
    elif method_key in ("heikin_ashi","renko","point_figure"):
        up=sum(closes[i]>opens[i] for i in range(-4,0))
        down=sum(closes[i]<opens[i] for i in range(-4,0))
        if up>=3 and price>e20: side="BUY"
        elif down>=3 and price<e20: side="SELL"
    elif method_key in ("orb","session_range"):
        # Session timestamps are not supplied; uses the recent candle range as an explicitly labeled proxy.
        if price>prior_high and bullish: side="BUY"
        elif price<prior_low and bearish: side="SELL"
    elif method_key == "inside_bar":
        if highs[-2]<highs[-3] and lows[-2]>lows[-3]:
            if price>highs[-2] and bullish: side="BUY"
            elif price<lows[-2] and bearish: side="SELL"
    elif method_key == "outside_bar":
        if highs[-1]>highs[-2] and lows[-1]<lows[-2]:
            if bullish and price>closes[-2]: side="BUY"
            elif bearish and price<closes[-2]: side="SELL"
    elif method_key == "three_bar_reversal":
        if closes[-3]<opens[-3] and closes[-2]<opens[-2] and bullish and price>highs[-2]: side="BUY"
        elif closes[-3]>opens[-3] and closes[-2]>opens[-2] and bearish and price<lows[-2]: side="SELL"
    elif method_key == "gap_trading":
        gap=(opens[-1]-closes[-2])/max(closes[-2],1e-12)
        if gap>0.005 and bullish: side="BUY"
        elif gap< -0.005 and bearish: side="SELL"
    elif method_key in ("smt_divergence","pairs_trading","stat_arb","cointegration","cross_market","oi_funding"):
        # Requires a second symbol, confirmed funding/OI, or paired series not present in this function.
        side=None
    elif method_key in ("power_of_three","judas_swing","turtle_soup","unicorn_model","breaker_blocks","mitigation_blocks","liquidity_void","fvg_retest","equal_highs_lows","premium_discount"):
        if lows[-1]<prior_low and price>prior_low and bullish and price>closes[-2]: side="BUY"
        elif highs[-1]>prior_high and price<prior_high and bearish and price<closes[-2]: side="SELL"
        elif method_key in ("breaker_blocks","mitigation_blocks","unicorn_model") and broke_up and bullish_structure: side="BUY"
        elif method_key in ("breaker_blocks","mitigation_blocks","unicorn_model") and broke_down and bearish_structure: side="SELL"
    elif method_key in ("cvd_proxy","footprint_proxy","volume_imbalance","absorption","market_profile","anchored_vwap","obv_trend","accumulation_distribution"):
        # OHLCV-only volume proxy; not true bid/ask delta, footprint, TPO, or anchored VWAP.
        loc=(price-lows[-1])/candle_range
        if avg_vol>0 and volumes[-1]>=avg_vol*1.4 and bullish and loc>=0.7: side="BUY"
        elif avg_vol>0 and volumes[-1]>=avg_vol*1.4 and bearish and loc<=0.3: side="SELL"
    elif method_key in ("zscore_reversion","mean_reversion"):
        m=mean(closes[-20:]); sd=mean([(x-m)**2 for x in closes[-20:]])**0.5
        z=(price-m)/max(sd,1e-12)
        if z<=-1.5 and (bullish or (rsi_now is not None and rsi_now<35)): side="BUY"
        elif z>=1.5 and (bearish or (rsi_now is not None and rsi_now>65)): side="SELL"
    elif method_key in ("relative_strength","dual_momentum","momentum"):
        move=(price-closes[-10])/max(closes[-10],1e-12)
        if move>0.015 and bullish and (e20 is None or price>e20): side="BUY"
        elif move< -0.015 and bearish and (e20 is None or price<e20): side="SELL"
    elif method_key == "seasonality":
        # Calendar seasonality requires reliable timestamps and a historical seasonal sample; no unsupported signal.
        side=None
    elif method_key in ("volatility_breakout","atr_breakout"):
        if price>prior_high and bullish and body>=atr*0.2: side="BUY"
        elif price<prior_low and bearish and -body>=atr*0.2: side="SELL"
    elif method_key == "supertrend":
        if e20 is not None and price>e20+atr*1.5 and bullish: side="BUY"
        elif e20 is not None and price<e20-atr*1.5 and bearish: side="SELL"
    elif method_key == "pivot_points":
        pp=(highs[-2]+lows[-2]+closes[-2])/3
        if price>pp and closes[-2]<=pp and bullish: side="BUY"
        elif price<pp and closes[-2]>=pp and bearish: side="SELL"
    elif method_key in ("parabolic_sar","chandelier_exit"):
        trail_high=max(highs[-22:-1])-atr*3
        trail_low=min(lows[-22:-1])+atr*3
        if price>trail_high and bullish: side="BUY"
        elif price<trail_low and bearish: side="SELL"
    elif method_key == "bollinger_bands":
        m=mean(closes[-20:]); sd=mean([(x-m)**2 for x in closes[-20:]])**0.5
        if price<m-2*sd and bullish: side="BUY"
        elif price>m+2*sd and bearish: side="SELL"
    elif method_key == "macd":
        fast=ema(closes,12); slow=ema(closes,26)
        prev_fast=ema(closes[:-1],12); prev_slow=ema(closes[:-1],26)
        if fast is not None and slow is not None and prev_fast is not None and prev_slow is not None:
            if fast>slow and prev_fast<=prev_slow: side="BUY"
            elif fast<slow and prev_fast>=prev_slow: side="SELL"
    elif method_key == "rsi_reversal":
        if rsi_now is not None and rsi_now<30 and bullish: side="BUY"
        elif rsi_now is not None and rsi_now>70 and bearish: side="SELL"
    elif method_key == "stochastic":
        lo=min(lows[-14:]); hi=max(highs[-14:]); k=100*(price-lo)/max(hi-lo,1e-12)
        prev_k=100*(closes[-2]-min(lows[-14:-1]))/max(max(highs[-14:-1])-min(lows[-14:-1]),1e-12)
        if k>20 and prev_k<=20 and bullish: side="BUY"
        elif k<80 and prev_k>=80 and bearish: side="SELL"
    elif method_key == "fisher_transform":
        changes=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        z=changes[-5:]
        if mean(z)>0 and bullish and price>e20: side="BUY"
        elif mean(z)<0 and bearish and price<e20: side="SELL"
    elif method_key == "aroon":
        window_high=highs[-25:]; window_low=lows[-25:]
        up=100*(window_high.index(max(window_high)))/24
        down=100*(window_low.index(min(window_low)))/24
        if up>=70 and down<=30 and bullish: side="BUY"
        elif down>=70 and up<=30 and bearish: side="SELL"
    elif method_key == "vortex":
        vp=sum(abs(highs[i]-lows[i-1]) for i in range(-14,0))
        vm=sum(abs(lows[i]-highs[i-1]) for i in range(-14,0))
        if vp>vm*1.1 and bullish: side="BUY"
        elif vm>vp*1.1 and bearish: side="SELL"
    elif method_key == "choppiness":
        trsum=sum(true_ranges[-14:])
        choppy=100*__import__("math").log10(max(trsum/max(max(highs[-14:])-min(lows[-14:]),1e-12),1e-12))/__import__("math").log10(14)
        if choppy<45 and price>e20 and bullish: side="BUY"
        elif choppy<45 and price<e20 and bearish: side="SELL"
    elif method_key == "ultimate_oscillator":
        bp=[]; tr=[]
        for i in range(-28,0):
            prev_close=closes[i-1]
            bp.append(closes[i]-min(lows[i],prev_close))
            tr.append(max(highs[i],prev_close)-min(lows[i],prev_close))
        uo=100*(4*sum(bp[-7:])/max(sum(tr[-7:]),1e-12)+2*sum(bp[-14:])/max(sum(tr[-14:]),1e-12)+sum(bp[-28:])/max(sum(tr[-28:]),1e-12))/7
        if uo>55 and bullish: side="BUY"
        elif uo<45 and bearish: side="SELL"
    elif method_key == "rvi":
        numerator=mean([closes[i]-opens[i] for i in range(-10,0)])
        denominator=mean([highs[i]-lows[i] for i in range(-10,0)])
        rvi=numerator/max(denominator,1e-12)
        if rvi>0.15 and bullish: side="BUY"
        elif rvi< -0.15 and bearish: side="SELL"
    elif method_key == "tsi":
        mom=[closes[i]-closes[i-1] for i in range(1,len(closes))]
        fast=ema(mom,13); slow=ema(mom,25)
        tsi=fast/max(abs(slow or 0),1e-12) if fast is not None else 0
        if tsi>0.1 and bullish and price>e20: side="BUY"
        elif tsi< -0.1 and bearish and price<e20: side="SELL"
    elif method_key == "ppo":
        e12,e26=ema(closes,12),ema(closes,26)
        ppo=100*(e12-e26)/max(abs(e26 or price),1e-12) if e12 is not None and e26 is not None else 0
        if ppo>0 and bullish: side="BUY"
        elif ppo<0 and bearish: side="SELL"
    elif method_key == "dpo":
        shift=10
        dpo=price-mean(closes[-21:-11])
        if dpo>0 and bullish: side="BUY"
        elif dpo<0 and bearish: side="SELL"
    elif method_key == "price_channel":
        if price>prior_high and bullish: side="BUY"
        elif price<prior_low and bearish: side="SELL"
    elif method_key == "connors_rsi":
        short_rsi=rsi(closes,3)
        if short_rsi is not None and short_rsi<10 and price>e200 and bullish: side="BUY"
        elif short_rsi is not None and short_rsi>90 and price<e200 and bearish: side="SELL"
    elif method_key == "elder_impulse":
        if e20 is not None and e50 is not None and price>e20>e50 and bullish: side="BUY"
        elif e20 is not None and e50 is not None and price<e20<e50 and bearish: side="SELL"
    elif method_key in ("three_line_strike","marubozu","doji_reversal","star_pattern","piercing_dark_cloud","tweezer"):
        prev_body=abs(closes[-2]-opens[-2]); prev_prev_body=abs(closes[-3]-opens[-3])
        upper=highs[-1]-max(opens[-1],closes[-1]); lower=min(opens[-1],closes[-1])-lows[-1]
        if method_key=="marubozu" and bullish and upper<candle_range*0.08 and lower<candle_range*0.08: side="BUY"
        elif method_key=="marubozu" and bearish and upper<candle_range*0.08 and lower<candle_range*0.08: side="SELL"
        elif method_key=="doji_reversal" and abs(body)<=candle_range*0.1 and lower>upper*1.8 and price>closes[-2]: side="BUY"
        elif method_key=="doji_reversal" and abs(body)<=candle_range*0.1 and upper>lower*1.8 and price<closes[-2]: side="SELL"
        elif method_key=="three_line_strike" and bullish and all(closes[i]>opens[i] for i in range(-4,-1)) and price<opens[-4] and price>closes[-4]: side="BUY"
        elif method_key in ("star_pattern","piercing_dark_cloud","tweezer") and bullish and price>closes[-2] and lower>prev_body*0.7: side="BUY"
        elif method_key in ("star_pattern","piercing_dark_cloud","tweezer") and bearish and price<closes[-2] and upper>prev_body*0.7: side="SELL"
    elif method_key in ("gap_go","gap_reversal","gap_trading"):
        gap=(opens[-1]-closes[-2])/max(closes[-2],1e-12)
        if gap>0.005 and price>opens[-1] and bullish: side="BUY"
        elif gap< -0.005 and price<opens[-1] and bearish: side="SELL"
        elif method_key=="gap_reversal" and gap>0.01 and price<opens[-1] and bearish: side="SELL"
        elif method_key=="gap_reversal" and gap< -0.01 and price>opens[-1] and bullish: side="BUY"
    elif method_key in ("failed_breakout","liquidity_reclaim"):
        if highs[-1]>prior_high and price<prior_high and bearish: side="SELL"
        elif lows[-1]<prior_low and price>prior_low and bullish: side="BUY"
    elif method_key in ("range_expansion","range_compression","relative_volume_breakout"):
        avg_range=mean([highs[i]-lows[i] for i in range(-20,-1)])
        if method_key=="range_expansion" and candle_range>avg_range*1.5 and bullish and price>closes[-2]: side="BUY"
        elif method_key=="range_expansion" and candle_range>avg_range*1.5 and bearish and price<closes[-2]: side="SELL"
        elif method_key=="range_compression" and candle_range<avg_range*0.6 and price>prior_high and bullish: side="BUY"
        elif method_key=="range_compression" and candle_range<avg_range*0.6 and price<prior_low and bearish: side="SELL"
        elif method_key=="relative_volume_breakout" and volumes[-1]>avg_vol*1.5 and price>prior_high and bullish: side="BUY"
        elif method_key=="relative_volume_breakout" and volumes[-1]>avg_vol*1.5 and price<prior_low and bearish: side="SELL"
    elif method_key in ("atr_trailing","volatility_stop"):
        stop=price-atr*3
        if price>stop and price>e20 and bullish: side="BUY"
        elif price<e20 and bearish: side="SELL"
    elif method_key in ("pivot_reversal","pivot_breakout"):
        pivot=(highs[-2]+lows[-2]+closes[-2])/3
        if price>pivot and bullish: side="BUY"
        elif price<pivot and bearish: side="SELL"
    elif method_key in ("fib_confluence","trendline_retest","channel_breakout"):
        mid=(max(highs[-20:])+min(lows[-20:]))/2
        if price>mid and bullish and price>e20: side="BUY"
        elif price<mid and bearish and price<e20: side="SELL"
    elif method_key in ("pvt","chaikin_oscillator","ease_movement","volume_climax"):
        signed_volume=volumes[-1]*(1 if price>closes[-2] else -1 if price<closes[-2] else 0)
        if method_key=="volume_climax" and volumes[-1]>avg_vol*2 and candle_range>atr*1.5:
            if bullish: side="BUY"
            elif bearish: side="SELL"
        elif signed_volume>0 and bullish and price>e20: side="BUY"
        elif signed_volume<0 and bearish and price<e20: side="SELL"
    elif method_key in ("vwap_reclaim","anchored_vwap"):
        if rolling_vwap is not None and price>rolling_vwap and closes[-2]<=rolling_vwap and bullish: side="BUY"
        elif rolling_vwap is not None and price<rolling_vwap and closes[-2]>=rolling_vwap and bearish: side="SELL"
    elif method_key == "wyckoff_spring":
        if lows[-1] < prior_low and price > prior_low and bullish and volumes[-1] >= avg_vol*0.8: side="BUY"
    elif method_key == "wyckoff_upthrust":
        if highs[-1] > prior_high and price < prior_high and bearish and volumes[-1] >= avg_vol*0.8: side="SELL"
    elif method_key == "wyckoff_sos_sow":
        if price > prior_high and bullish and volumes[-1] > avg_vol*1.3: side="BUY"
        elif price < prior_low and bearish and volumes[-1] > avg_vol*1.3: side="SELL"
    elif method_key == "wyckoff_lps":
        tol=max(atr*0.4,price*0.002)
        if abs(lows[-1]-prev_sh)<tol and price>e20 and bullish: side="BUY"
        elif abs(highs[-1]-prev_sl)<tol and price<e20 and bearish: side="SELL"
    elif method_key in ("ict_ote","multi_swing_ote"):
        swing_hi=max(highs[-30:]); swing_lo=min(lows[-30:]); span=swing_hi-swing_lo
        if span>0:
            buy_zone=swing_hi-span*0.79 <= price <= swing_hi-span*0.62
            sell_zone=swing_lo+span*0.62 <= price <= swing_lo+span*0.79
            if buy_zone and bullish and price>e20: side="BUY"
            elif sell_zone and bearish and price<e20: side="SELL"
    elif method_key == "ict_kill_zone":
        # ICT kill zones in New York local time; zone conversion accounts for daylight saving.
        stamp = last.get("time", last.get("timestamp"))
        if stamp is not None:
            try:
                stamp = float(stamp)
                if stamp > 1e12:
                    stamp /= 1000.0
                local_time = datetime.fromtimestamp(stamp, timezone.utc).astimezone(ZoneInfo("America/New_York"))
                minute = local_time.hour * 60 + local_time.minute
                in_kill_zone = (120 <= minute < 300) or (420 <= minute < 600)
                if in_kill_zone and bullish and price > e20 and abs(body) >= atr * 0.5: side = "BUY"
                elif in_kill_zone and bearish and price < e20 and abs(body) >= atr * 0.5: side = "SELL"
            except (ValueError, TypeError, OverflowError):
                side = None
    elif method_key in ("gartley","bat_pattern","butterfly_pattern","crab_pattern","shark_pattern"):
        # Approximate harmonic completion from recent swing ratios; requires independent validation before production use.
        swings=(recent_sl[-2][1],recent_sh[-2][1],recent_sl[-1][1],recent_sh[-1][1]) if len(recent_sl)>=2 and len(recent_sh)>=2 else None
        if swings:
            a,b,cc,d=swings
            ab=abs(b-a); bc=abs(cc-b); cd=abs(d-cc)
            ratio=cd/max(bc,1e-12)
            if 0.5<=ratio<=1.9 and price>e20 and bullish: side="BUY"
            elif 0.5<=ratio<=1.9 and price<e20 and bearish: side="SELL"
    elif method_key in ("andrews_pitchfork","wolfe_waves","linear_regression_channel","stddev_channel"):
        # Channel proxy based on recent range; not a geometrically fitted pitchfork or Wolfe-wave detector.
        mid=(max(highs[-20:])+min(lows[-20:]))/2
        if price>mid and bullish and price>e20: side="BUY"
        elif price<mid and bearish and price<e20: side="SELL"
    elif method_key in ("ttm_squeeze","range_compression"):
        short_range=max(highs[-6:])-min(lows[-6:])
        long_range=max(highs[-20:])-min(lows[-20:])
        if long_range>0 and short_range/long_range<0.35 and price>prior_high and bullish: side="BUY"
        elif long_range>0 and short_range/long_range<0.35 and price<prior_low and bearish: side="SELL"
    elif method_key == "coppock_curve":
        roc11=(price-closes[-12])/max(closes[-12],1e-12)
        roc14=(price-closes[-15])/max(closes[-15],1e-12)
        if roc11+roc14>0 and bullish: side="BUY"
        elif roc11+roc14<0 and bearish: side="SELL"
    elif method_key in ("klinger_oscillator","wyckoff_effort_result","relative_volume_climax","failed_auction"):
        if avg_vol>0 and volumes[-1]>avg_vol*1.7 and candle_range>atr:
            loc=(price-lows[-1])/candle_range
            if loc>0.75 and bullish: side="BUY"
            elif loc<0.25 and bearish: side="SELL"
    elif method_key in ("schaff_cycle","adaptive_ma","mcginley","donchian_midline","vol_adjusted_momentum","volatility_adjusted_momentum"):
        if price>e20 and e20>e50 and bullish: side="BUY"
        elif price<e20 and e20<e50 and bearish: side="SELL"
    elif method_key in ("hurst_filter","hurst_cycle"):
        # Lightweight lag-1 persistence proxy, not a statistically rigorous Hurst exponent.
        returns=[closes[i]/max(closes[i-1],1e-12)-1 for i in range(-20,0)]
        persistence=sum(1 for a,b in zip(returns,returns[1:]) if a*b>0)/max(len(returns)-1,1)
        if persistence>0.65 and price>e20 and bullish: side="BUY"
        elif persistence>0.65 and price<e20 and bearish: side="SELL"
    elif method_key in ("volatility_adjusted_momentum","range_liquidity_reclaim"):
        if lows[-1]<prior_low and price>prior_low and bullish: side="BUY"
        elif highs[-1]>prior_high and price<prior_high and bearish: side="SELL"
    elif method_key == "cci":
        typical=[(highs[i]+lows[i]+closes[i])/3 for i in range(len(c))]
        m=mean(typical[-20:]); md=mean([abs(x-m) for x in typical[-20:]])
        cci=(typical[-1]-m)/max(0.015*md,1e-12)
        if cci>100 and bullish: side="BUY"
        elif cci< -100 and bearish: side="SELL"
    elif method_key == "williams_r":
        hh=max(highs[-14:]); ll=min(lows[-14:]); wr=-100*(hh-price)/max(hh-ll,1e-12)
        if wr>-80 and rsi_now is not None and rsi_now<40 and bullish: side="BUY"
        elif wr< -20 and rsi_now is not None and rsi_now>60 and bearish: side="SELL"
    elif method_key == "mfi":
        pos=neg=0.0
        for i in range(-14,0):
            flow=((highs[i]+lows[i]+closes[i])/3)*volumes[i]
            prevtyp=(highs[i-1]+lows[i-1]+closes[i-1])/3
            if (highs[i]+lows[i]+closes[i])/3>prevtyp: pos+=flow
            else: neg+=flow
        mfi=100-100/(1+pos/max(neg,1e-12))
        if mfi<20 and bullish: side="BUY"
        elif mfi>80 and bearish: side="SELL"
    elif method_key == "roc":
        roc=(price-closes[-11])/max(closes[-11],1e-12)
        if roc>0.02 and bullish: side="BUY"
        elif roc< -0.02 and bearish: side="SELL"
    elif method_key == "trix":
        e1=[ema(closes[:i],15) for i in range(1,len(closes)+1)]
        e1=[x for x in e1 if x is not None]
        e2=[ema(e1[:i],15) for i in range(1,len(e1)+1)]
        e2=[x for x in e2 if x is not None]
        e3=[ema(e2[:i],15) for i in range(1,len(e2)+1)]
        if len(e3)>1:
            if e3[-1]>e3[-2] and bullish: side="BUY"
            elif e3[-1]<e3[-2] and bearish: side="SELL"
    elif method_key == "dmi":
        plus=sum(max(highs[i]-highs[i-1],0) for i in range(-14,0))
        minus=sum(max(lows[i-1]-lows[i],0) for i in range(-14,0))
        if plus>minus*1.25 and bullish: side="BUY"
        elif minus>plus*1.25 and bearish: side="SELL"
    elif method_key == "elder_ray":
        bull=highs[-1]-(e20 or price); bear=lows[-1]-(e20 or price)
        if bull>0 and bear<0 and bullish: side="BUY"
        elif bear<0 and bull<0 and bearish: side="SELL"
    elif method_key in ("kama","tema","alligator","triple_screen"):
        # Smoothing/screening approximations; not a substitute for full platform-specific indicator calculation.
        if e20 is not None and e50 is not None and price>e20>e50 and bullish: side="BUY"
        elif e20 is not None and e50 is not None and price<e20<e50 and bearish: side="SELL"
    elif method_key == "chaikin_money_flow":
        mfv=sum((((closes[i]-lows[i])-(highs[i]-closes[i]))/max(highs[i]-lows[i],1e-12))*volumes[i] for i in range(-20,0))
        cmf=mfv/max(sum(volumes[-20:]),1e-12)
        if cmf>0.15 and bullish: side="BUY"
        elif cmf< -0.15 and bearish: side="SELL"
    elif method_key == "ad_divergence":
        signed_now=volumes[-1]*(1 if closes[-1]>closes[-2] else -1 if closes[-1]<closes[-2] else 0)
        signed_prev=volumes[-6]*(1 if closes[-6]>closes[-7] else -1 if closes[-6]<closes[-7] else 0)
        if price>closes[-6] and signed_now>signed_prev and bullish: side="BUY"
        elif price<closes[-6] and signed_now<signed_prev and bearish: side="SELL"
    elif method_key == "force_index":
        force=(closes[-1]-closes[-2])*volumes[-1]
        if force>0 and volumes[-1]>=avg_vol and bullish: side="BUY"
        elif force<0 and volumes[-1]>=avg_vol and bearish: side="SELL"
    elif method_key == "ulcer_filter":
        peak=max(closes[-14:]); drawdown=(price-peak)/max(peak,1e-12)
        if drawdown> -0.02 and price>e20 and bullish: side="BUY"
        elif drawdown< -0.08 and price<e20 and bearish: side="SELL"
    elif method_key in ("triple_top_bottom","head_shoulders","inverse_head_shoulders","wedge","flag","pennant","cup_handle","rectangle","rounding_pattern","three_drives","key_reversal","nr7","vcp","darvas_box","fractal_breakout","pivot_breakout","kumo_breakout","fib_extension"):
        # Pattern-family proxy using confirmed swing structure and compression/breakout; full discretionary geometry is not claimed.
        recent_range=max(highs[-10:])-min(lows[-10:])
        earlier_range=max(highs[-20:-10])-min(lows[-20:-10])
        compressed=earlier_range>0 and recent_range<earlier_range*0.75
        if (method_key in ("flag","pennant","vcp","nr7","darvas_box","rectangle","fractal_breakout","pivot_breakout","kumo_breakout") or compressed) and price>prior_high and bullish: side="BUY"
        elif (method_key in ("flag","pennant","vcp","nr7","darvas_box","rectangle","fractal_breakout","pivot_breakout","kumo_breakout") or compressed) and price<prior_low and bearish: side="SELL"
        elif method_key in ("triple_top_bottom","head_shoulders") and bearish_structure and price<prev_sl and bearish: side="SELL"
        elif method_key in ("triple_top_bottom","inverse_head_shoulders") and bullish_structure and price>prev_sh and bullish: side="BUY"
    elif method_key == "adx_trend":
        if e20 is not None and e50 is not None and abs(e20-e50)/price>0.003:
            if e20>e50 and price>e20 and bullish: side="BUY"
            elif e20<e50 and price<e20 and bearish: side="SELL"
    
    if side is None or method_key == "risk_management":
        return None
    entry=price
    risk=max(atr*1.5,entry*0.002)
    if side=="BUY":
        stop,tp1,tp2,tp3=entry-risk,entry+risk,entry+2*risk,entry+3*risk
    else:
        stop,tp1,tp2,tp3=entry+risk,entry-risk,entry-2*risk,entry-3*risk
    if stop<=0 or min(tp1,tp2,tp3)<=0:
        return None
    # Evidence score: trend, structure, relative volume and RSI; not a historical win probability.
    evidence=sum((price>e20 if e20 is not None else False) if side=="BUY" else (price<e20 if e20 is not None else False) for _ in [0])
    evidence+=int((bullish_structure if side=="BUY" else bearish_structure))
    evidence+=int(avg_vol>0 and volumes[-1]>=avg_vol*1.5)
    evidence+=int(rsi_now is not None and ((side=="BUY" and rsi_now>=50) or (side=="SELL" and rsi_now<=50)))
    score=min(90,58+8*evidence)
    return {**ticker,"side":side,"method":method_key,"score_type":"rule_evidence_not_probability",
            "score_label":"قوة الشواهد وليست احتمال ربح","entry":entry,"stop":stop,
            "tp1":tp1,"tp2":tp2,"tp3":tp3,
            "stop_pct":abs(entry-stop)/entry*100,"tp1_pct":abs(tp1-entry)/entry*100,
            "score":score,
            "status":"إشارة حسب قاعدة المنهج — درجة توافق فنية وليست احتمال ربح مضمون",
            "change_pct":ticker["change_pct"]}



@app.get("/api/tasi/analysis")
def tasi_index_analysis(interval: str = Query("1d")):
    enforce_section_access("tasi")
    """Broad analysis of the TASI benchmark index, not an individual Saudi stock."""
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "message": "الفريم غير مدعوم."}, status_code=422)
    try:
        candles = candle_data("tasi_index", "^TASI.SR", interval)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError):
        candles = []
    if len(candles) < 2:
        return JSONResponse({"ok": False, "live": False, "items": [],
                             "message": "تعذر جلب بيانات مؤشر تاسي من المصدر العام الآن؛ لم نعرض تحليلًا تقديريًا."}, status_code=503)
    closes = [float(c["close"]) for c in candles]
    last, prev = candles[-1], candles[-2]
    def sma(n):
        vals = closes[-n:]
        return round(sum(vals) / len(vals), 2) if len(vals) >= n else None
    change = ((last["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0
    window = candles[-20:]
    support = min(c["low"] for c in window)
    resistance = max(c["high"] for c in window)
    s20, s50, s200 = sma(20), sma(50), sma(200)
    # ATR-based scenario levels are calculated from this exact timeframe's candles.
    ranges = []
    for i, candle in enumerate(candles[-15:]):
        prev_close = candles[-16 + i]["close"] if len(candles) >= 16 and i >= 0 else candle["close"]
        ranges.append(max(candle["high"] - candle["low"], abs(candle["high"] - prev_close), abs(candle["low"] - prev_close)))
    atr = sum(ranges) / len(ranges) if ranges else max(last["high"] - last["low"], last["close"] * 0.01)
    if s20 is not None and s50 is not None and last["close"] > s20 > s50:
        trend = "صاعد"
        side = "سيناريو صاعد"
        entry = last["close"]
        stop = min(support, entry - 1.5 * atr)
        risk = max(entry - stop, atr)
        targets = [entry + risk * multiple for multiple in (1, 2, 3)]
    elif s20 is not None and s50 is not None and last["close"] < s20 < s50:
        trend = "هابط"
        side = "سيناريو هابط"
        entry = last["close"]
        stop = max(resistance, entry + 1.5 * atr)
        risk = max(stop - entry, atr)
        targets = [entry - risk * multiple for multiple in (1, 2, 3)]
    else:
        trend = "عرضي / مختلط"
        side = "سيناريو مشروط"
        entry = last["close"]
        bullish = last["close"] >= (s20 if s20 is not None else last["close"])
        stop = min(support, entry - 1.5 * atr) if bullish else max(resistance, entry + 1.5 * atr)
        risk = max(abs(entry - stop), atr)
        targets = [entry + risk * n if bullish else entry - risk * n for n in (1, 2, 3)]
    return {"ok": True, "live": True, "symbol": "^TASI.SR", "name": "المؤشر العام للسوق السعودي — تاسي",
            "provider": "Yahoo Finance", "delayed": True, "interval": interval,
            "price": round(last["close"], 2), "change_pct": round(change, 2),
            "trend": trend, "open": round(last["open"], 2), "high": round(last["high"], 2),
            "low": round(last["low"], 2), "close": round(last["close"], 2),
            "support": round(support, 2), "resistance": round(resistance, 2),
            "atr": round(atr, 2), "scenario": side, "entry": round(entry, 2),
            "stop_loss": round(stop, 2), "tp1": round(targets[0], 2), "tp2": round(targets[1], 2), "tp3": round(targets[2], 2),
            "risk_reward": "1:1 / 1:2 / 1:3", "sma20": s20, "sma50": s50, "sma200": s200,
            "candles": [{"time": c.get("time"), "open": round(c["open"], 2), "high": round(c["high"], 2),
                         "low": round(c["low"], 2), "close": round(c["close"], 2), "volume": c.get("volume", 0)}
                        for c in candles[-60:]],
            "message": "تحليل فني للمؤشر العام، وليس توصية على سهم منفرد. بيانات Yahoo قد تكون متأخرة."}

# Method audit endpoint: exposes implementation/data limits instead of implying every catalogue entry is fully validated.
METHOD_AUXILIARY_DATA_REQUIRED = {
    "smt_divergence": "مقارنة أصلين مترابطين على الأقل",
    "pairs_trading": "سلسلة أسعار أصلين",
    "stat_arb": "سلاسل أسعار متعددة واختبار إحصائي",
    "cointegration": "سلاسل أسعار متعددة واختبار تكامل مشترك",
    "cross_market": "بيانات سوق/أصل مقارن",
    "oi_funding": "بيانات الفائدة المفتوحة والتمويل",
}
METHOD_RISK_ONLY_KEYS = {"risk_management"}
METHOD_PROXY_KEYS = {
    key for label, key in METHOD_RULES.items()
    if "proxy" in label.lower() or "approximation" in label.lower()
} | {
    "cvd_proxy", "footprint_proxy", "market_profile", "anchored_vwap", "absorption",
    "parabolic_sar", "connors_rsi", "fisher_transform", "chaikin_oscillator",
    "triple_screen", "alligator", "hurst_cycle", "mcginley", "failed_auction",
}


@app.get("/api/methods/catalog")
def method_catalog():
    items = []
    for label, key in METHOD_RULES.items():
        if key in METHOD_RISK_ONLY_KEYS:
            status = "risk_tool"
            signal_capable = False
            note = "أداة لإدارة المخاطر وليست مولّد إشارة دخول."
        elif key in METHOD_AUXILIARY_DATA_REQUIRED:
            status = "needs_auxiliary_data"
            signal_capable = False
            note = METHOD_AUXILIARY_DATA_REQUIRED[key]
        elif key in METHOD_PROXY_KEYS:
            status = "approximation"
            signal_capable = True
            note = "تقريب مبني على OHLCV؛ لا يعادل بيانات الأوامر/الجلسات الأصلية ولا يُعد مثبت الربحية."
        else:
            status = "ohlcv_rule_unvalidated"
            signal_capable = True
            note = "قاعدة شموع/سعر/حجم؛ يلزم اختبار تاريخي مستقل قبل اعتمادها."
        items.append({
            "name": label, "key": key, "status": status,
            "signal_capable": signal_capable, "note": note,
            "score_is_probability": False,
        })
    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "ok": True, "count": len(items), "counts": counts, "items": items,
        "message": "وجود المنهج في القائمة لا يعني اجتيازه اختبار ربحية. score يقيس شواهد القاعدة فقط، وليس احتمال الربح.",
    }


@app.get("/api/methods/{market}")
def method_filter(market: str, method: str = Query(...), interval: str = Query("15m"), limit: int = Query(40, ge=1, le=100)):
    market = market.lower()
    enforce_section_access(market)
    if market not in BINANCE and market not in YAHOO_MARKETS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "مصدر هذا السوق غير مربوط حاليًا."})
    if interval not in INTERVALS:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "الفريم غير مدعوم."}, status_code=422)
    method_key = METHOD_RULES.get(method)
    if not method_key:
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "المنهج غير معروف."}, status_code=422)
    try:
        if market in BINANCE:
            tickers = market_tickers(market)[:limit]
        else:
            if market == "saudi":
                _load_saudi_symbols()
            symbols = YAHOO_MARKETS[market]
            with ThreadPoolExecutor(max_workers=8) as pool:
                quotes = [future.result() for future in as_completed(
                    [pool.submit(fetch_yahoo_quote, symbol) for symbol in symbols]
                )]
            tickers = [q for q in quotes if q]
            tickers.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
            tickers = tickers[:limit]
            for ticker in tickers:
                ticker.setdefault("quote_volume", 0)
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
    found.sort(key=lambda x: (x.get("score", 0), x.get("quote_volume", 0), abs(x.get("change_pct", 0))), reverse=True)
    return {"ok": True, "live": True, "market": market, "method": method, "interval": interval,
            "scanned": len(tickers), "analyzed": len(tickers), "count": len(found),
            "updated_at": int(time.time()), "items": found,
            "message": "تم فحص الشموع المباشرة وفق شرط أولي خاص بالمنهج المختار. بعض المناهج المركبة تحتاج تأكيدًا بصريًا/سياقيًا؛ النتيجة ليست ضمانًا أو توصية آلية مكتملة."}



@app.get("/api/risk/position-size")
def risk_position_size(
    equity: float = Query(..., gt=0),
    risk_pct: float = Query(1.0, gt=0, le=5),
    entry: float = Query(..., gt=0),
    stop: float = Query(..., gt=0),
):
    """Position sizing from supplied equity and stop; excludes costs and leverage constraints."""
    if not all(math.isfinite(v) for v in (equity, risk_pct, entry, stop)) or entry == stop:
        return JSONResponse({"ok": False, "message": "تحقق من رأس المال وسعر الدخول والوقف؛ يجب أن يختلف الوقف عن الدخول."}, status_code=422)
    distance = abs(entry - stop)
    risk_amount = equity * (risk_pct / 100.0)
    quantity = risk_amount / distance
    notional = quantity * entry
    return {
        "ok": True, "equity": equity, "risk_pct": risk_pct,
        "risk_amount": round(risk_amount, 8), "entry": entry, "stop": stop,
        "stop_distance_pct": round(distance / entry * 100.0, 6),
        "quantity_before_costs": round(quantity, 8),
        "notional_before_leverage": round(notional, 8),
        "disclaimer": "حساب نظري قبل الرسوم والانزلاق والتمويل وحدود المنصة؛ لا يضمن الخسارة القصوى الفعلية."
    }


SIGNAL_CACHE = {}
SIGNAL_CACHE_TTL = 75


def candle_data(market: str, symbol: str, interval: str):
    from urllib.parse import urlencode, quote
    if market in BINANCE:
        url = KLINES[market] + "?" + urlencode({"symbol": symbol, "interval": interval, "limit": 220})
        raw = fetch_json(url, timeout=8)
        return [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                for k in raw if len(k) > 6 and int(k[6]) < int(time.time() * 1000)]
    if market not in YAHOO_MARKETS and market != "tasi_index":
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


def telegram_send_signal(signal: dict) -> bool:
    """Telegram notifications stay disabled unless explicitly enabled in service settings."""
    if os.getenv("ENABLE_TELEGRAM_SIGNALS", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    import html
    medal_labels = {"gold": "🥇 ذهبي", "silver": "🥈 فضي", "bronze": "🥉 برونزي"}
    medal = medal_labels.get(signal.get("medal"), "📌 توصية")
    side = "شراء 🟢" if signal.get("side") == "BUY" else "بيع 🔴"
    market_labels = {"spot": "سبوت", "futures": "فيوتشر", "contracts": "العقود الأمريكية",
                     "us": "الأسهم الأمريكية", "saudi": "السوق السعودي", "forex": "الفوركس والذهب"}
    symbol = html.escape(str(signal.get("symbol", "")))
    market = html.escape(market_labels.get(signal.get("market"), str(signal.get("market", ""))))
    interval = html.escape(str(signal.get("interval", "")))
    def price(key):
        try:
            return f"{float(signal[key]):.8f}".rstrip("0").rstrip(".")
        except (KeyError, TypeError, ValueError):
            return "—"
    message = (
        f"<b>{medal} | التداول الذكي PRO</b>\n"
        f"<b>الأصل:</b> <code>{symbol}</code>\n"
        f"<b>السوق:</b> {market} | <b>الفريم:</b> {interval}\n"
        f"<b>الاتجاه:</b> {side}\n"
        f"<b>الدخول:</b> <code>{price('entry')}</code>\n"
        f"<b>TP1:</b> <code>{price('tp1')}</code> | <b>TP2:</b> <code>{price('tp2')}</code> | <b>TP3:</b> <code>{price('tp3')}</code>\n"
        f"<b>وقف الخسارة:</b> <code>{price('stop')}</code>\n"
        f"<b>قوة الإشارة:</b> {int(signal.get('score', 0) or 0)}% | <b>توافق العائلات:</b> {signal.get('method_count', 0)}\n"
        f"<i>إشارة آلية وليست ضمانًا للربح. تحقق من السعر قبل الدخول.</i>"
    )
    from urllib.parse import urlencode
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return bool(json.loads(response.read().decode("utf-8")).get("ok"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


@app.get("/api/telegram/status")
def telegram_status():
    """Report configuration presence only; never expose the bot token."""
    configured = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())
    return {"configured": configured, "destination": "Telegram channel" if configured else None,
            "message": "Telegram notification settings are configured." if configured else "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the service environment."}


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
    method_families = sorted({method_family(METHOD_RULES[name]) for name in method_hits})
    method_count_raw = len(method_hits)
    method_count = len(method_families)
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
        "leverage": "1x" if market == "futures" else None,
        "entry": entry, "stop": stop, "tp1": t1, "tp2": t2, "tp3": t3,
        "stop_pct": abs(entry-stop)/entry*100, "tp1_pct": abs(t1-entry)/entry*100,
        "tp2_pct": abs(t2-entry)/entry*100, "tp3_pct": abs(t3-entry)/entry*100,
        "score": min(98, score), "confirmations": confirmations,
        "method_count": method_count, "method_count_raw": method_count_raw,
        "method_families": method_families,
        "importance": ("صفقة مهمة جدًا" if method_count >= 7 else "صفقة مهمة" if method_count >= 5 else "توافق متوسط" if method_count >= 3 else "إشارة أولية"),
        "methods": active, "method_hits": method_hits,
        "quote_volume": ticker.get("quote_volume", 0), "updated_at": int(time.time()),
        "method": "ترتيب حسب توافق المناهج مع اتجاه السعر",
        "status": "عدد المناهج المتوافقة يرفع ترتيب الإشارة؛ الإشارة الأولية تحتاج تحققًا إضافيًا"
    }

@app.get("/api/signals/{market}")
def signal_cards(market: str, interval: str = Query("15m"), limit: int = Query(20, ge=1, le=20)):
    market = market.lower()
    enforce_section_access(market)
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
    # Reuse a recent scan persisted on the mounted data volume after page reloads
    # or process restarts; do not make every visitor rescan the whole market.
    with RESULTS_LOCK:
        persisted_scans = read_json_file(SIGNALS_CACHE_PATH, {})
    persisted = persisted_scans.get("|".join((market, interval, str(limit)))) if isinstance(persisted_scans, dict) else None
    if isinstance(persisted, dict):
        cached_at = int(persisted.get("_cached_at") or 0)
        cached_result = persisted.get("result")
        if cached_at and now - cached_at < 180 and isinstance(cached_result, dict):
            restored = dict(cached_result)
            restored["cached"] = True
            restored["live"] = False
            restored["stale"] = True
            restored["message"] = "نعرض آخر فحص محفوظ لتجنب إعادة البحث المتكرر؛ قد تتأخر الأسعار حتى اكتمال التحديث التالي."
            SIGNAL_CACHE[key] = (now, restored)
            return restored
    try:
        if market in BINANCE:
            # Inspect a larger liquidity-ranked batch before selecting eligible signals.
            tickers = market_tickers(market)[:max(100, limit * 10)]
        else:
            # Load the full TASI equity directory before building Saudi signals; otherwise
            # the fallback list silently limits the signal page to only a few stocks.
            if market == "saudi":
                _load_saudi_symbols()
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
            # Scan the full configured futures and forex universes; keep other large markets bounded for responsiveness.
            if market not in ("contracts", "forex"):
                tickers = tickers[:max(20, limit)]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # If a provider is temporarily unavailable, keep showing unexpired signals
        # already saved for this exact market/timeframe instead of blanking the page.
        with RESULTS_LOCK:
            saved_history = read_json_file(RESULTS_PATH, [])
        saved_items = [
            dict(item) for item in saved_history
            if isinstance(item, dict)
            and item.get("result") == "مفتوحة"
            and item.get("market") == market
            and item.get("interval") == interval
            and int(item.get("expires_at") or 0) > int(now)
        ]
        saved_items.sort(key=lambda x: (x.get("score", 0), x.get("method_count", 0),
                                        x.get("confirmations", 0), x.get("quote_volume", 0)), reverse=True)
        if saved_items:
            medals = ["gold", "silver", "bronze"]
            for i, item in enumerate(saved_items[:limit]):
                item["rank"] = i + 1
                item["medal"] = medals[i] if i < len(medals) else None
            result = {
                "ok": True, "live": False, "stale": True, "market": market, "interval": interval,
                "scanned": 0, "count": len(saved_items[:limit]), "updated_at": int(now),
                "items": saved_items[:limit],
                "message": "تعذر تحديث الأسعار مؤقتًا؛ نعرض الصفقات المحفوظة غير المنتهية حتى يعود المصدر."
            }
            SIGNAL_CACHE[key] = (now, result)
            return result
        return JSONResponse({"ok": False, "live": False, "items": [], "message": "تعذر جلب أسعار السوق الآن ولا توجد صفقات محفوظة صالحة."}, status_code=503)

    found = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        jobs = [pool.submit(build_signal, market, ticker, interval) for ticker in tickers]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    found.append(item)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, IndexError, TypeError, ZeroDivisionError):
                continue
    # Use a balanced eligibility gate so the board does not stay empty when
    # strict high-confluence thresholds reject every otherwise valid candidate.
    # Still require multiple independent method families and directional confirmation.
    found = [x for x in found if x.get("score", 0) >= 50 and x.get("method_count", 0) >= 2 and x.get("confirmations", 0) >= 4]
    found.sort(key=lambda x: (x.get("score", 0), x.get("method_count", 0), x["confirmations"], x["quote_volume"]), reverse=True)
    found = found[:limit]
    medals = ["gold", "silver", "bronze"]
    for i, item in enumerate(found):
        item["rank"] = i + 1
        item["medal"] = medals[i] if i < len(medals) else None
    new_telegram_signals = []
    with RESULTS_LOCK:
        history = prune_results()
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
            elif int(now) >= int(record.get("expires_at") or (record.get("created_at", int(now)) + INTERVAL_SECONDS.get(record.get("interval"), 86400))):
                record["result"] = "انتهت المدة"
                record["closed_at"] = int(record.get("expires_at") or now)
                record["expiry_reason"] = "انتهت مدة الفريم"
        # Expired open signals are deleted after their own timeframe, not kept as stale cards.
        history = [record for record in history if record.get("result") != "انتهت المدة"]
        active_map = {
            (x.get("market"), x.get("interval"), x.get("symbol")): x
            for x in history if x.get("result") == "مفتوحة"
        }
        active_keys = set(active_map)
        for item in found:
            ident = (market, interval, item["symbol"])
            existing = active_map.get(ident)
            if existing:
                # Preserve original expiry; rescanning must not extend a signal lifetime.
                item["id"] = existing.get("id")
                item["created_at"] = existing.get("created_at")
                item["expires_at"] = existing.get("expires_at")
                continue
            created_at = int(now)
            item["created_at"] = created_at
            item["expires_at"] = created_at + INTERVAL_SECONDS[interval]
            record = {**item, "id": str(int(now*1000)) + "-" + item["symbol"],
                      "last_price": ticker_prices.get(item["symbol"], item["entry"]), "result": "مفتوحة",
                      "reached": None, "pnl_pct": 0.0}
            history.append(record)
            new_telegram_signals.append(dict(item))
            active_keys.add(ident)
        write_json_file(RESULTS_PATH, history[-1000:])
    # Notify only when a new signal is first saved; rescans do not resend active signals.
    for telegram_signal in new_telegram_signals:
        telegram_send_signal(telegram_signal)
    # Return all still-open saved signals for this timeframe, not just candidates
    # rediscovered in this scan. This prevents valid saved cards from disappearing.
    with RESULTS_LOCK:
        display_items = [
            dict(record) for record in history
            if record.get("result") == "مفتوحة"
            and record.get("market") == market
            and record.get("interval") == interval
            and int(record.get("expires_at") or 0) > int(now)
        ]
    display_items.sort(key=lambda x: (x.get("score", 0), x.get("method_count", 0),
                                      x.get("confirmations", 0), x.get("quote_volume", 0)), reverse=True)
    medals = ["gold", "silver", "bronze"]
    for i, item in enumerate(display_items[:limit]):
        item["rank"] = i + 1
        item["medal"] = medals[i] if i < len(medals) else None
    result = {"ok": True, "live": True, "market": market, "interval": interval,
              "scanned": len(tickers), "count": len(display_items[:limit]), "updated_at": int(now),
              "items": display_items[:limit], "message": "الصفقات المفتوحة محفوظة لكل فريم حتى انتهاء مدته. قد تتأخر الأسعار المعروضة إذا تعذر تحديث مصدر السوق؛ لا توجد نسبة ربح تاريخية موثقة."}
    SIGNAL_CACHE[key] = (now, result)
    with RESULTS_LOCK:
        persisted_scans = read_json_file(SIGNALS_CACHE_PATH, {})
        if not isinstance(persisted_scans, dict):
            persisted_scans = {}
        persisted_scans["|".join((market, interval, str(limit)))] = {
            "_cached_at": int(now), "result": result
        }
        # Bound the cache file; keep only the latest 100 market/timeframe combinations.
        if len(persisted_scans) > 100:
            persisted_scans = dict(sorted(
                persisted_scans.items(),
                key=lambda pair: int(pair[1].get("_cached_at") or 0) if isinstance(pair[1], dict) else 0,
                reverse=True
            )[:100])
        write_json_file(SIGNALS_CACHE_PATH, persisted_scans)
    return result


def read_json_file(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json_file(path, data):
    """Atomically persist JSON using a unique temp file for concurrent requests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # A shared fixed .tmp filename races when multiple signal endpoints save together.
    # Unique names prevent one request from deleting another request's pending file.
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def prune_results(max_age_seconds=86400):
    """Keep open signals for their timeframe; retain closed results for 24 hours."""
    with RESULTS_LOCK:
        now = int(time.time())
        items = read_json_file(RESULTS_PATH, [])
        fresh = []
        changed = False
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("created_at"), (int, float)):
                continue
            created_at = int(item["created_at"])
            if created_at > now:
                continue
            if item.get("result") == "مفتوحة":
                duration = INTERVAL_SECONDS.get(item.get("interval"), max_age_seconds)
                expires_at = item.get("expires_at")
                if not isinstance(expires_at, (int, float)):
                    expires_at = created_at + duration
                    item["expires_at"] = int(expires_at)
                    changed = True
                expires_at = int(expires_at)
                if now >= expires_at:
                    # Timeframe expiry means remove this signal completely.
                    changed = True
                else:
                    fresh.append(item)
                continue
            if item.get("result") == "انتهت المدة":
                changed = True
                continue
            closed_at = item.get("closed_at")
            retention_anchor = int(closed_at) if isinstance(closed_at, (int, float)) else created_at
            if 0 <= now - retention_anchor <= max_age_seconds:
                fresh.append(item)
        if len(fresh) != len(items):
            changed = True
        if changed:
            write_json_file(RESULTS_PATH, fresh[-1000:])
        return fresh[-1000:]



SECTION_CATALOG = [{"id":"spot","label":"سبوت"},{"id":"futures","label":"فيوتشر"},{"id":"contracts","label":"العقود الأمريكية"},{"id":"us","label":"الأسهم الأمريكية"},{"id":"saudi","label":"السوق السعودي"},{"id":"forex","label":"الفوركس والذهب"},{"id":"alpha","label":"Binance Alpha"},{"id":"analysis","label":"مناهج التحليل"},{"id":"tasi","label":"تحليل تاسي العام"},{"id":"results","label":"النتائج"},{"id":"news","label":"الأخبار"},{"id":"blog","label":"المدونة"},{"id":"account","label":"الحساب والاشتراك"}]
SECTION_SETTINGS_PATH = DATA_DIR / "section_settings.json"
SECTION_SETTINGS_LOCK = threading.RLock()

def read_section_settings():
    with SECTION_SETTINGS_LOCK:
        raw = read_json_file(SECTION_SETTINGS_PATH, {})
        allowed = {item["id"] for item in SECTION_CATALOG}
        return {key: value for key, value in raw.items() if key in allowed and value in ("public", "subscription", "closed")}

def section_mode(section_id):
    return read_section_settings().get(section_id, "public")

def enforce_section_access(section_id):
    mode = section_mode(section_id)
    if mode == "closed":
        from fastapi import HTTPException
        raise HTTPException(status_code=423, detail="هذا القسم مغلق مؤقتًا من إدارة المنصة.")
    if mode == "subscription":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="هذا القسم يتطلب اشتراكًا. نظام التحقق من اشتراكات الأعضاء غير مفعّل بعد.")

@app.get("/api/site/sections")
def public_section_settings():
    settings = read_section_settings()
    return {"ok": True, "sections": settings, "catalog": SECTION_CATALOG}

@app.get("/api/admin/sections")
def admin_get_section_settings(credentials: HTTPBasicCredentials = Depends(security)):
    require_admin(credentials)
    return {"ok": True, "sections": read_section_settings(), "catalog": SECTION_CATALOG}

@app.post("/api/admin/sections")
def admin_save_section_settings(payload: dict, credentials: HTTPBasicCredentials = Depends(security)):
    require_admin(credentials)
    submitted = payload.get("sections", {})
    if not isinstance(submitted, dict):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="صيغة إعدادات الأقسام غير صحيحة.")
    allowed = {item["id"] for item in SECTION_CATALOG}
    normalized = {}
    for key, value in submitted.items():
        if key not in allowed or value not in ("public", "subscription", "closed"):
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="يوجد قسم أو وضع وصول غير صالح.")
        normalized[key] = value
    with SECTION_SETTINGS_LOCK:
        write_json_file(SECTION_SETTINGS_PATH, normalized)
    return {"ok": True, "sections": normalized}

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


NEWS_CACHE = {}
NEWS_UNIVERSE_CACHE = {"at": 0, "assets": [], "coins": {}, "counts": {}}
SAUDI_SYMBOL_CACHE = {"at": 0, "symbols": []}

def _load_saudi_symbols():
    """Load the complete TASI listed-equity universe, paging until the directory ends."""
    now = time.time()
    if SAUDI_SYMBOL_CACHE["symbols"] and now - SAUDI_SYMBOL_CACHE["at"] < 21600:
        return SAUDI_SYMBOL_CACHE["symbols"]

    loaded = {}
    # Keep paging: a single page can silently omit listed companies when the directory grows.
    page_size = 200
    for offset in range(0, 2000, page_size):
        try:
            url = (
                "https://api.sahmk.sa/api/v1/companies/?market=TASI"
                f"&limit={page_size}&offset={offset}"
            )
            data = fetch_json(url, timeout=8)
            rows = data.get("results", []) if isinstance(data, dict) else []
            if not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                security_type = str(row.get("security_type") or row.get("type") or "").strip().lower()
                # This directory is filtered to TASI; when a type is provided, retain equities only.
                if security_type and not any(tag in security_type for tag in ("equity", "stock", "share", "سهم")):
                    continue
                raw_symbol = str(row.get("symbol") or row.get("ticker") or "").strip()
                digits = raw_symbol.split(".")[0].strip()
                if not digits.isdigit():
                    continue
                yahoo_symbol = digits.zfill(4) + ".SR"
                loaded[yahoo_symbol] = str(
                    row.get("name_ar") or row.get("name_en") or row.get("name") or digits
                )

            if len(rows) < page_size:
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
            # Preserve any symbols collected from earlier pages and use the existing fallback if none loaded.
            break

    if loaded:
        symbols = sorted(loaded.keys())
        YAHOO_MARKETS["saudi"] = symbols
        YAHOO_LABELS.update(loaded)
        SAUDI_SYMBOL_CACHE.update({"symbols": symbols, "at": now})
    return SAUDI_SYMBOL_CACHE["symbols"] or YAHOO_MARKETS["saudi"]

def _news_universe():
    now = time.time()
    if NEWS_UNIVERSE_CACHE["assets"] and now - NEWS_UNIVERSE_CACHE["at"] < 60:
        return NEWS_UNIVERSE_CACHE["assets"], NEWS_UNIVERSE_CACHE["coins"], NEWS_UNIVERSE_CACHE["counts"]
    _load_saudi_symbols()
    coins, counts = {}, {"spot_pairs": 0, "futures_pairs": 0}
    for market in ("spot", "futures"):
        try:
            rows = market_tickers(market)
            counts["spot_pairs" if market == "spot" else "futures_pairs"] = len(rows)
            for row in rows:
                symbol = str(row.get("symbol", ""))
                if symbol.endswith("USDT"):
                    base = symbol[:-4]
                    coins[base] = {"symbol": base, "name": base, "kind": "عملة رقمية", "market": market}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue
    assets = list(coins.values())
    for market in ("us", "saudi", "contracts", "forex"):
        for symbol in YAHOO_MARKETS.get(market, []):
            clean = symbol.replace(".SR", "").replace("=F", "").replace("=X", "")
            assets.append({"symbol": clean, "name": YAHOO_LABELS.get(symbol, clean), "kind": "سهم" if market in ("us", "saudi") else ("عقد" if market == "contracts" else "فوركس/ذهب"), "market": market})
    counts.update({"unique_coins": len(coins), "us_stocks": len(YAHOO_MARKETS["us"]),
        "saudi_stocks": len(YAHOO_MARKETS["saudi"]), "total_stocks": len(YAHOO_MARKETS["us"]) + len(YAHOO_MARKETS["saudi"]),
        "contracts": len(YAHOO_MARKETS["contracts"]), "forex_gold": len(YAHOO_MARKETS["forex"]),
        "saudi_universe_source": "directory" if SAUDI_SYMBOL_CACHE["symbols"] else "fallback"})
    NEWS_UNIVERSE_CACHE.update({"at": now, "assets": assets, "coins": coins, "counts": counts})
    return assets, coins, counts

@app.get("/api/universe-counts")
def universe_counts():
    assets, coins, counts = _news_universe()
    return {"ok": True, **counts, "filters": "Binance USDT pairs with 24h quote volume >= $1M; excludes configured stablecoins",
            "stock_symbols": YAHOO_MARKETS["us"] + YAHOO_MARKETS["saudi"]}

def _news_direction(title):
    t = title.lower()
    buy_words = ("يرتفع", "ارتفاع", "صعود", "يقفز", "مكاسب", "شراء", "إيجابي", "نمو قوي", "اختراق صاعد", "surge", "rally", "gains", "bullish", "upgrade", "beat estimates", "record high", "jumps", "soars")
    sell_words = ("يهبط", "هبوط", "تراجع", "انخفاض", "خسائر", "بيع", "سلبي", "انهيار", "هبوط حاد", "falls", "drop", "decline", "losses", "bearish", "downgrade", "misses estimates", "sell-off", "plunges", "slumps")
    buy, sell = any(w in t for w in buy_words), any(w in t for w in sell_words)
    if buy and not sell:
        return {"direction": "BUY", "direction_ar": "توجه صاعد / شراء محتمل"}
    if sell and not buy:
        return {"direction": "SELL", "direction_ar": "توجه هابط / بيع محتمل"}
    return {"direction": "UNCLEAR", "direction_ar": "غير واضح — الخبر وحده لا يحدد شراء أو بيع"}

@app.get("/api/news")
def market_news(limit: int = Query(30, ge=1, le=100), market: str = Query("all"), refresh: bool = Query(False)):
    enforce_section_access("news")
    from urllib.parse import urlencode
    market = market.lower().strip()
    if market not in {"all", "crypto", "us", "saudi", "forex", "contracts"}:
        market = "all"
    now = time.time()
    cached = NEWS_CACHE.get(market)
    if not refresh and cached and now - cached["at"] < 300:
        return {"ok": True, "live": True, "items": cached["items"][:limit], "cached": True, "market": market,
                "message": "اختر السوق من القائمة لتغيير نوع الأخبار؛ راجع الخبر الأصلي قبل اتخاذ القرار."}
    if NEWS_UNIVERSE_CACHE["assets"] and now - NEWS_UNIVERSE_CACHE["at"] < 600:
        assets, coins, counts = NEWS_UNIVERSE_CACHE["assets"], NEWS_UNIVERSE_CACHE["coins"], NEWS_UNIVERSE_CACHE["counts"]
    else:
        assets, coins, counts = [], {}, {}
    if market == "crypto":
        allowed_assets = [a for a in assets if a["kind"] == "عملة رقمية"]
        queries = [("العملات الرقمية", "cryptocurrency OR Bitcoin OR Ethereum OR crypto market")]
        symbols = sorted(coins)
        for start in range(0, min(len(symbols), 50), 25):
            queries.append(("العملات الرقمية", " OR ".join(symbols[start:start+25]) + " cryptocurrency crypto"))
    elif market == "us":
        allowed_assets = [a for a in assets if a["market"] == "us"]
        symbols = YAHOO_MARKETS["us"]
        queries = [("الأسهم الأمريكية", "US stocks Nasdaq S&P 500 earnings shares")]
        for start in range(0, min(len(symbols), 40), 20):
            queries.append(("الأسهم الأمريكية", " OR ".join(symbols[start:start+20]) + " stock shares earnings"))
    elif market == "saudi":
        allowed_assets = [a for a in assets if a["market"] == "saudi"]
        symbols = [s.replace(".SR", "") for s in YAHOO_MARKETS["saudi"]]
        queries = [("السوق السعودي", "أسهم السوق السعودي تداول الشركات السعودية تاسي نمو")]
        for start in range(0, min(len(symbols), 40), 20):
            queries.append(("السوق السعودي", " OR ".join(symbols[start:start+20]) + " سهم تداول شركة السعودية"))
    elif market == "forex":
        allowed_assets = [a for a in assets if a["market"] == "forex"]
        queries = [("الفوركس والذهب", "forex EURUSD GBPUSD USDJPY gold XAUUSD dollar currency market")]
    elif market == "contracts":
        allowed_assets = [a for a in assets if a["market"] == "contracts"]
        queries = [("العقود الأمريكية", "S&P 500 futures Nasdaq futures Dow futures gold oil futures ES NQ GC CL")]
    else:
        allowed_assets = assets
        queries = [("العملات الرقمية", "cryptocurrency OR Bitcoin OR Ethereum OR crypto market"),
            ("الأسهم الأمريكية", "US stocks OR Nasdaq OR S&P 500 earnings shares"),
            ("السوق السعودي", "أسهم السوق السعودي تداول شركات السعودية تاسي نمو"),
            ("الفوركس والذهب", "forex OR gold OR dollar currency market"),
            ("العقود الأمريكية", "S&P 500 futures Nasdaq futures Dow futures gold oil futures")]
        # Small curated query set keeps the endpoint fast and prevents upstream feed storms.
        queries.extend([
            ("العملات الرقمية", "Bitcoin Ethereum Solana cryptocurrency market"),
            ("الأسهم الأمريكية", "Nasdaq S&P 500 US stocks earnings"),
            ("السوق السعودي", "السوق السعودي تاسي تداول الشركات نتائج"),
            ("الفوركس والذهب", "forex gold XAUUSD dollar market"),
            ("العقود الأمريكية", "S&P 500 futures Nasdaq futures gold oil")
        ])
    def read_feed(entry):
        label, query = entry
        url = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "ar", "gl": "SA", "ceid": "SA:ar"})
        found = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SmartTradingPro/2.4"})
            with urllib.request.urlopen(req, timeout=2.5) as response:
                root = ET.fromstring(response.read())
            for node in root.findall("./channel/item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                pub = (node.findtext("pubDate") or "").strip()
                source = node.findtext("source") or "Google News"
                if title and link:
                    found.append({"title": title, "url": link, "published": pub, "source": source, "category": label})
        except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError, ValueError):
            pass
        return found
    items, seen = [], set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_feed, query) for query in queries[:8]]
        for future in as_completed(futures):
            try:
                rows = future.result()
            except Exception:
                rows = []
            for item in rows:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                title_lower = item["title"].lower()
                matched = []
                import re
                for asset in allowed_assets:
                    symbol, name = asset["symbol"], asset["name"]
                    symbol_match = len(symbol) >= 3 and re.search(r"(?<![A-Za-z0-9])" + re.escape(symbol) + r"(?![A-Za-z0-9])", item["title"], re.I)
                    name_match = len(name) >= 4 and name.lower() in title_lower
                    if symbol_match or name_match:
                        matched.append({"symbol": symbol, "name": name, "kind": asset["kind"], "market": asset["market"]})
                    if len(matched) >= 8:
                        break
                item["assets"] = matched
                item["asset_labels"] = [x["symbol"] for x in matched] or ["لم يُحدد أصل بعينه"]
                item.update(_news_direction(item["title"]))
                items.append(item)
    items.sort(key=lambda x: x["published"], reverse=True)
    if not items and cached and cached.get("items"):
        return {"ok": True, "live": True, "items": cached["items"][:limit], "cached": True, "stale": True, "market": market, "universe": counts,
                "message": "مصدر الأخبار تأخر؛ نعرض آخر أخبار محفوظة مؤقتًا."}
    NEWS_CACHE[market] = {"at": now, "items": items}
    return {"ok": True, "live": bool(items), "items": items[:limit], "cached": False, "market": market, "universe": counts,
            "message": "الأخبار مفصولة حسب السوق المحدد؛ التوجه تصنيف آلي أولي من العنوان فقط وليس توصية مالية." if items else "ما لقينا أخبار في هذا التصنيف الآن؛ جرّب تحديث البحث لاحقًا."}


@app.get("/api/blog")
def blog_articles():
    enforce_section_access("blog")
    return {"ok": True, "items": read_json_file(ARTICLES_PATH, [])}


def refresh_open_result_prices(items):
    """Refresh open trade P&L and TP/SL outcomes when the results page is opened."""
    open_items = [x for x in items if x.get("result") == "مفتوحة"]
    if not open_items:
        return items

    prices = {}
    markets = {x.get("market") for x in open_items}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {}
        for market in markets:
            if market in BINANCE:
                jobs[pool.submit(market_tickers, market)] = ("binance", market)
        for record in open_items:
            market, symbol = record.get("market"), record.get("symbol")
            if market in YAHOO_MARKETS and symbol:
                jobs[pool.submit(fetch_yahoo_quote, symbol)] = ("yahoo", symbol)
        for future in as_completed(jobs):
            kind, key = jobs[future]
            try:
                value = future.result()
            except Exception:
                continue
            if kind == "binance":
                for ticker in value:
                    prices[(key, ticker.get("symbol"))] = ticker.get("price")
            elif value:
                prices[(next((x.get("market") for x in open_items if x.get("symbol") == key and x.get("market") in YAHOO_MARKETS), ""), key)] = value.get("price")

    now = int(time.time())
    changed = False
    for record in open_items:
        price = prices.get((record.get("market"), record.get("symbol")))
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        entry = record.get("entry")
        if not isinstance(entry, (int, float)) or entry <= 0:
            continue
        record["last_price"] = float(price)
        direction = 1 if record.get("side") == "BUY" else -1
        record["pnl_pct"] = round((price - entry) / entry * 100 * direction, 4)
        side = record.get("side")
        stop, tp1, tp2, tp3 = (record.get(k) for k in ("stop", "tp1", "tp2", "tp3"))
        hit = None
        if side == "BUY":
            if isinstance(stop, (int, float)) and price <= stop: hit = "SL"
            elif isinstance(tp3, (int, float)) and price >= tp3: hit = "TP3"
            elif isinstance(tp2, (int, float)) and price >= tp2: record["reached"] = "TP2"
            elif isinstance(tp1, (int, float)) and price >= tp1: record["reached"] = "TP1"
        else:
            if isinstance(stop, (int, float)) and price >= stop: hit = "SL"
            elif isinstance(tp3, (int, float)) and price <= tp3: hit = "TP3"
            elif isinstance(tp2, (int, float)) and price <= tp2: record["reached"] = "TP2"
            elif isinstance(tp1, (int, float)) and price <= tp1: record["reached"] = "TP1"
        if hit:
            record["result"] = hit
            record["closed_at"] = now
        changed = True
    if changed:
        write_json_file(RESULTS_PATH, items[-1000:])
    return items


@app.get("/api/results")
def signal_results(limit: int = Query(100, ge=1, le=500)):
    enforce_section_access("results")
    with RESULTS_LOCK:
        items = prune_results()
        items = refresh_open_result_prices(items)
        items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        closed = [x for x in items if x.get("result") in ("TP1", "TP2", "TP3", "SL")]
        wins = [x for x in closed if x.get("result") in ("TP1", "TP2", "TP3")]
        return {"ok": True, "items": items[:limit], "total": len(items), "closed": len(closed),
                "wins": len(wins), "losses": len(closed)-len(wins),
                "win_rate": round(len(wins)*100/len(closed), 1) if closed else None,
                "message": "الأداء يتحدث من آخر سعر متاح عند فتح النتائج؛ قد تتأخر أسعار Yahoo، وإعادة تشغيل الخدمة قد تفقد السجل ما لم يُضبط DATA_DIR على تخزين دائم."}


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
