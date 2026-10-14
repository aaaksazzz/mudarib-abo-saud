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
    urls = [(SEO_BASE_URL + "/", "daily", "1.0"), (SEO_BASE_URL + "/blog", "weekly", "0.9")] + [(SEO_BASE_URL + p, "daily", "0.8") for p in ["/markets/spot", "/markets/futures", "/markets/contracts", "/markets/us-stocks", "/markets/saudi", "/markets/forex-gold", "/markets/alpha", "/radar", "/gold", "/analysis", "/results", "/news"]]
    urls.extend((SEO_BASE_URL + "/blog/" + p["slug"], "monthly", "0.7") for p in SEO_POSTS)
    urls.extend((SEO_BASE_URL + "/blog/" + slug, "monthly", "0.6") for slug in ["risk-management-stop-loss", "ema50-ema200-trend-filter", "breakout-retest-price-action", "liquidity-sweep-vs-market-structure", "risk-reward-win-rate", "backtest-trading-strategy"])
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
            posts.insert(0, {**item, "slug": slug, "description": item.get("summary") or str(item.get("body", ""))[:180], "lang": item.get("lang", "ar"), "language_name": item.get("language_name", "العربية")})
    cards = "".join(
        '<article class="post" data-lang="' + escape(str(p.get("lang") or "ar"), quote=True) + '" data-category="' + escape(str(p.get("category") or ""), quote=True).lower() + '"><p class="meta"><span class="category">' + escape(str(p.get("category", "تعليم التداول"))) + '</span><span class="lang">' + escape(str(p.get("language_name") or "العربية")) + '</span></p><h2><a href="/blog/' + escape(str(p["slug"]), quote=True) + '">' + escape(str(p["title"])) + '</a></h2><p>' + escape(str(p.get("description") or p.get("summary") or "")) + '</p><a class="read" href="/blog/' + escape(str(p["slug"]), quote=True) + '">اقرأ / Read →</a></article>'
        for p in posts
    )
    canonical = SEO_BASE_URL + "/blog"
    languages = "".join('<option value="' + escape(x["code"], quote=True) + '">' + escape(x["name"]) + '</option>' for x in BLOG_LANGS)
    blog_schema = json.dumps({"@context":"https://schema.org","@type":"Blog","name":"SMART TRADING PRO Trading Education","url":canonical,"inLanguage":[x["locale"] for x in BLOG_LANGS],"numberOfItems":len(posts)}, ensure_ascii=False).replace("</", "<\\/")
    html = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مدونة التداول | 200 مقال تعليمي بعشر لغات</title><meta name="description" content="مكتبة تعليمية متعددة اللغات عن تداول العملات الرقمية والأسهم والفوركس، التحليل الفني، حركة السعر، السيولة، اختبار الاستراتيجيات وإدارة المخاطر."><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '"><meta property="og:type" content="website"><meta property="og:locale" content="ar_SA"><meta property="og:title" content="مدونة التداول الذكي PRO | تعليم التداول بعشر لغات"><meta property="og:description" content="مقالات تعليمية عن التداول والتحليل وإدارة المخاطر بعشر لغات."><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">' + blog_schema + '</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:16px/1.9 system-ui,Tahoma,Arial}main{max-width:1120px;margin:auto;padding:24px 16px}a{color:#8dbaff;text-decoration:none}header,.filters,.post{background:#111b2a;border:1px solid #29384d;border-radius:16px;padding:20px;margin:12px 0}header{background:linear-gradient(135deg,#16243a,#101827)}h1{font-size:clamp(28px,5vw,42px);line-height:1.35;margin:0 0 8px}h2{font-size:20px;line-height:1.5;margin:6px 0}.sub{color:#b9c7da}.filters{display:flex;gap:10px;flex-wrap:wrap}.filters input,.filters select{background:#080d18;color:#edf3ff;border:1px solid #40516a;border-radius:10px;padding:12px;min-width:180px;flex:1}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:12px}.post{margin:0;padding:18px}.meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:13px}.category{color:#54ddb0}.lang{color:#e4c27a}.read{font-weight:800}.count{color:#aebbd0;font-size:13px}.post p{overflow-wrap:anywhere}footer{color:#93a0b3;padding:22px 4px;font-size:13px}</style></head><body><main><nav><a href="/">الرئيسية</a>　<a href="/blog">المدونة</a></nav><header><p class="category">SMART TRADING PRO · EDUCATION</p><h1>مدونة التداول الذكي PRO</h1><p class="sub">200 مقال تعليمي بعشر لغات: من أساسيات التداول إلى التحليل الفني والسيولة واختبار الاستراتيجيات وإدارة المخاطر.</p><p class="sub">المحتوى تعليمي فقط ولا يمثل توصية شراء أو بيع ولا يضمن الأرباح.</p></header><section class="filters"><input id="blogSearch" type="search" placeholder="ابحث عن مقال أو موضوع… / Search articles" aria-label="بحث المقالات"><select id="blogLang" aria-label="اختر اللغة"><option value="">كل اللغات / All languages</option>' + languages + '</select><select id="blogCategory" aria-label="اختر التصنيف"><option value="">كل التصنيفات / All categories</option></select><span class="count" id="blogCount">200 مقال</span></section><section class="grid" id="blogGrid">' + cards + '</section><footer>راجع المخاطر والرسوم والانزلاق دائمًا. لا تضمن الاختبارات التاريخية الأداء المستقبلي.</footer></main><script>const cards=[...document.querySelectorAll(".post")],search=document.getElementById("blogSearch"),lang=document.getElementById("blogLang"),cat=document.getElementById("blogCategory"),count=document.getElementById("blogCount");[...new Set(cards.map(x=>x.dataset.category).filter(Boolean))].sort().forEach(x=>{const o=document.createElement("option");o.value=x;o.textContent=x;cat.appendChild(o)});function filterPosts(){const q=search.value.trim().toLowerCase();let shown=0;cards.forEach(c=>{const ok=(!lang.value||c.dataset.lang===lang.value)&&(!cat.value||c.dataset.category===cat.value)&&(!q||c.innerText.toLowerCase().includes(q));c.hidden=!ok;if(ok)shown++});count.textContent=shown+" / "+cards.length+" articles"}[search,lang,cat].forEach(x=>x.addEventListener("input",filterPosts));</script></body></html>'
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
    lang_code = str(post.get("lang") or "ar")
    lang_info = next((x for x in BLOG_LANGS if x["code"] == lang_code), BLOG_LANGS[0])
    published = time.strftime("%Y-%m-%d", time.gmtime(int(post.get("published_at") or time.time())))
    topic_key = post.get("topic_key")
    alternates = "".join('<link rel="alternate" hreflang="' + escape(x["locale"], quote=True) + '" href="' + SEO_BASE_URL + '/blog/' + x["code"] + '-' + escape(str(topic_key), quote=True) + '">' for x in BLOG_LANGS) if topic_key else ""
    article_json = json.dumps({"@context":"https://schema.org","@type":"Article","headline":title,"description":description,"datePublished":published,"dateModified":published,"inLanguage":lang_info["locale"],"mainEntityOfPage":canonical,"author":{"@type":"Organization","name":"التداول الذكي PRO"},"publisher":{"@type":"Organization","name":"التداول الذكي PRO"}}, ensure_ascii=False).replace("</", "<\\/")
    paragraphs = "".join("<p>" + escape(p.strip()) + "</p>" for p in body.splitlines() if p.strip()) or "<p>" + escape(body) + "</p>"
    html = '<!doctype html><html lang="' + escape(lang_info["code"], quote=True) + '" dir="' + escape(lang_info["dir"], quote=True) + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + ' | SMART TRADING PRO</title><meta name="description" content="' + escape(description[:300], quote=True) + '"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="' + canonical + '">' + alternates + '<meta property="og:type" content="article"><meta property="og:locale" content="' + escape(lang_info["locale"].replace("-", "_"), quote=True) + '"><meta property="og:title" content="' + escape(title, quote=True) + '"><meta property="og:description" content="' + escape(description[:300], quote=True) + '"><meta property="og:url" content="' + canonical + '"><script type="application/ld+json">' + article_json + '</script><style>body{margin:0;background:#080d18;color:#edf3ff;font:17px/2 system-ui,Tahoma,Arial}main{max-width:820px;margin:auto;padding:24px 16px}a{color:#8dbaff;text-decoration:none}.crumb{font-size:13px;color:#93a0b3}.lang{color:#e4c27a;font-size:13px}article{background:#111b2a;border:1px solid #29384d;border-radius:18px;padding:clamp(20px,5vw,42px);margin-top:18px}.category{color:#54ddb0;font-size:13px;font-weight:800}h1{font-size:clamp(28px,5vw,42px);line-height:1.4}p{margin:18px 0;overflow-wrap:anywhere}footer{color:#93a0b3;font-size:13px;margin-top:24px}</style></head><body><main><p class="crumb"><a href="/">الرئيسية / Home</a> / <a href="/blog">المدونة / Blog</a></p><article><p class="category">' + escape(str(post.get("category") or "Trading Education")) + '</p><p class="lang">' + escape(lang_info["name"]) + '</p><h1>' + escape(title) + '</h1><p>' + escape(description) + '</p>' + paragraphs + '<p><strong>Important:</strong> Educational content only. This is not a buy/sell recommendation or a promise of returns.</p></article><footer><a href="/blog">← جميع المقالات / All articles</a></footer></main></body></html>'
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
def market_data(market: str, limit: int = Query(40, ge=1, le=500)):
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
    history = prune_results()
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


def prune_results(max_age_seconds=86400):
    """Keep the visible results window to the latest 24 hours."""
    now = int(time.time())
    items = read_json_file(RESULTS_PATH, [])
    fresh = [
        item for item in items
        if isinstance(item, dict)
        and isinstance(item.get("created_at"), (int, float))
        and 0 <= now - int(item["created_at"]) <= max_age_seconds
    ]
    if len(fresh) != len(items):
        write_json_file(RESULTS_PATH, fresh[-1000:])
    return fresh[-1000:]


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
    now = time.time()
    if SAUDI_SYMBOL_CACHE["symbols"] and now - SAUDI_SYMBOL_CACHE["at"] < 21600:
        return SAUDI_SYMBOL_CACHE["symbols"]
    loaded = {}
    for market_code in ("TASI", "NOMU"):
        try:
            data = fetch_json("https://api.sahmk.sa/api/v1/companies/?market=" + market_code + "&limit=500&offset=0", timeout=5)
            rows = data.get("results", []) if isinstance(data, dict) else []
            for row in rows:
                security_type = str(row.get("security_type") or row.get("type") or "").strip().lower()
                if security_type and not any(tag in security_type for tag in ("equity", "stock", "share", "سهم")):
                    continue
                raw_symbol = str(row.get("symbol") or row.get("ticker") or "").strip()
                if not raw_symbol:
                    continue
                digits = raw_symbol.split(".")[0].strip()
                if not digits.isdigit():
                    continue
                yahoo_symbol = digits.zfill(4) + ".SR"
                loaded[yahoo_symbol] = str(row.get("name_ar") or row.get("name_en") or row.get("name") or digits)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
            continue
    if loaded:
        YAHOO_MARKETS["saudi"] = sorted(loaded.keys())
        YAHOO_LABELS.update(loaded)
        SAUDI_SYMBOL_CACHE.update({"symbols": list(loaded.keys()), "at": now})
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
    from urllib.parse import urlencode
    market = market.lower().strip()
    if market not in {"all", "crypto", "us", "saudi", "forex", "contracts"}:
        market = "all"
    now = time.time()
    cached = NEWS_CACHE.get(market)
    if not refresh and cached and now - cached["at"] < 300:
        return {"ok": True, "live": True, "items": cached["items"][:limit], "cached": True, "market": market,
                "message": "اختر السوق من القائمة لتغيير نوع الأخبار؛ راجع الخبر الأصلي قبل اتخاذ القرار."}
    assets, coins, counts = _news_universe()
    if market == "crypto":
        allowed_assets = [a for a in assets if a["kind"] == "عملة رقمية"]
        queries = [("العملات الرقمية", "cryptocurrency OR Bitcoin OR Ethereum OR crypto market")]
        symbols = sorted(coins)
        for start in range(0, len(symbols), 25):
            queries.append(("العملات الرقمية", " OR ".join(symbols[start:start+25]) + " cryptocurrency crypto"))
    elif market == "us":
        allowed_assets = [a for a in assets if a["market"] == "us"]
        symbols = YAHOO_MARKETS["us"]
        queries = [("الأسهم الأمريكية", "US stocks Nasdaq S&P 500 earnings shares")]
        for start in range(0, len(symbols), 20):
            queries.append(("الأسهم الأمريكية", " OR ".join(symbols[start:start+20]) + " stock shares earnings"))
    elif market == "saudi":
        allowed_assets = [a for a in assets if a["market"] == "saudi"]
        symbols = [s.replace(".SR", "") for s in YAHOO_MARKETS["saudi"]]
        queries = [("السوق السعودي", "أسهم السوق السعودي تداول الشركات السعودية تاسي نمو")]
        for start in range(0, len(symbols), 20):
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
        for start in range(0, len(coins), 25):
            queries.append(("العملات الرقمية", " OR ".join(sorted(coins)[start:start+25]) + " cryptocurrency crypto"))
        for group_market, label in (("us", "الأسهم الأمريكية"), ("saudi", "السوق السعودي")):
            group_symbols = [s.replace(".SR", "") for s in YAHOO_MARKETS[group_market]]
            for start in range(0, len(group_symbols), 20):
                queries.append((label, " OR ".join(group_symbols[start:start+20]) + " stock shares"))
    def read_feed(entry):
        label, query = entry
        url = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "ar", "gl": "SA", "ceid": "SA:ar"})
        found = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SmartTradingPro/2.4"})
            with urllib.request.urlopen(req, timeout=4) as response:
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
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(read_feed, query) for query in queries]
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
    NEWS_CACHE[market] = {"at": now, "items": items}
    return {"ok": True, "live": bool(items), "items": items[:limit], "cached": False, "market": market, "universe": counts,
            "message": "الأخبار مفصولة حسب السوق المحدد؛ التوجه تصنيف آلي أولي من العنوان فقط وليس توصية مالية." if items else "ما لقينا أخبار في هذا التصنيف الآن؛ جرّب تحديث البحث لاحقًا."}


@app.get("/api/blog")
def blog_articles():
    return {"ok": True, "items": read_json_file(ARTICLES_PATH, [])}


@app.get("/api/results")
def signal_results(limit: int = Query(100, ge=1, le=500)):
    items = prune_results()
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
