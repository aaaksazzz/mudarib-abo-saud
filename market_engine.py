import time
import threading
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BINANCE = "https://api.binance.com"
FUTURES = "https://fapi.binance.com"
YAHOO = "https://query1.finance.yahoo.com"
MARKETS = {
    "spot": {"name": "Binance Spot", "kind": "crypto", "base": BINANCE, "endpoint": "/api/v3"},
    "futures": {"name": "Binance Futures", "kind": "futures", "base": FUTURES, "endpoint": "/fapi/v1"},
    "us_stocks": {"name": "الأسهم الأمريكية", "kind": "yahoo", "symbols": ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","AVGO","NFLX","PLTR","JPM","LLY","WMT","COST","ORCL","CRM","UBER","COIN","MSTR"]},
    "us_options": {"name": "عقود الخيارات الأمريكية", "kind": "unsupported", "symbols": []},
    "saudi": {"name": "السوق السعودي", "kind": "yahoo", "symbols": ["2222.SR","1120.SR","1180.SR","2010.SR","2082.SR","7010.SR","1211.SR","1150.SR","1010.SR","1050.SR","1060.SR","1080.SR","2280.SR","4190.SR","4001.SR","4002.SR","4003.SR","4004.SR","4005.SR","4007.SR"]},
    "forex": {"name": "الفوركس والذهب", "kind": "yahoo", "symbols": ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F"]}
}
TIMEFRAMES = ("1m", "15m", "1h", "4h", "1d", "1w", "1M")
BINANCE_INTERVALS = {"1m":"1m","15m":"15m","1h":"1h","4h":"4h","1d":"1d","1w":"1w","1M":"1M"}
YAHOO_CONFIG = {
    "1m": ("7d", "1m"), "15m": ("60d", "15m"), "1h": ("730d", "60m"),
    "4h": ("730d", "60m"), "1d": ("10y", "1d"), "1w": ("10y", "1wk"), "1M": ("max", "1mo")
}

class MarketEngine:
    def __init__(self):
        self.cache = {}
        self.lock = threading.RLock()
        self.headers = {"User-Agent": "Mozilla/5.0 SMART-TRADING-PRO/2.2"}

    def get(self, url, params=None):
        response = requests.get(url, params=params, headers=self.headers, timeout=(4, 8))
        response.raise_for_status()
        return response.json()

    def _cached(self, key, ttl, loader):
        now = time.time()
        with self.lock:
            item = self.cache.get(key)
            if item and now - item[0] < ttl:
                return item[1]
        value = loader()
        with self.lock:
            self.cache[key] = (now, value)
        return value

    def _binance_symbols(self, market):
        cfg = MARKETS[market]
        def load():
            info = self.get(cfg["base"] + cfg["endpoint"] + "/exchangeInfo")
            ticks = self.get(cfg["base"] + cfg["endpoint"] + "/ticker/24hr")
            by_symbol = {x["symbol"]: x for x in ticks}
            excluded = {"USDT","USDC","BUSD","FDUSD","TUSD","DAI","USDP","USDE","UST","USTC"}
            out = []
            for item in info.get("symbols", []):
                if item.get("status") != "TRADING" or item.get("quoteAsset") != "USDT":
                    continue
                if item.get("baseAsset", "").upper() in excluded:
                    continue
                ticker = by_symbol.get(item["symbol"], {})
                volume = float(ticker.get("quoteVolume", 0) or 0)
                if volume >= 1_000_000:
                    out.append({"symbol": item["symbol"], "volume": volume,
                                "price": float(ticker.get("lastPrice", 0) or 0),
                                "change": float(ticker.get("priceChangePercent", 0) or 0)})
            return sorted(out, key=lambda x: (abs(x["change"]), x["volume"]), reverse=True)
        return self._cached(("universe", market), 120, load)

    def _yahoo_chart(self, symbol, timeframe):
        period, interval = YAHOO_CONFIG[timeframe]
        data = self.get(f"{YAHOO}/v8/finance/chart/{symbol}", {"range": period, "interval": interval})
        chart = data.get("chart", {})
        result = (chart.get("result") or [None])[0]
        if not result:
            raise ValueError("No chart data")
        quote = result["indicators"]["quote"][0]
        stamps = result.get("timestamp", [])
        candles = []
        for i, stamp in enumerate(stamps):
            vals = [quote.get(k, [None] * len(stamps))[i] for k in ("open","high","low","close","volume")]
            if vals[0] is not None and vals[3] is not None:
                candles.append({"t": int(stamp), "o": float(vals[0]), "h": float(vals[1]),
                                "l": float(vals[2]), "c": float(vals[3]), "v": float(vals[4] or 0)})
        if timeframe == "4h":
            buckets = {}
            for candle in candles:
                bucket = candle["t"] // 14400
                buckets.setdefault(bucket, []).append(candle)
            aggregated = []
            for bucket, group in sorted(buckets.items()):
                group.sort(key=lambda x: x["t"])
                if len(group) != 4:
                    continue
                aggregated.append({"t": bucket * 14400, "o": group[0]["o"],
                    "h": max(x["h"] for x in group), "l": min(x["l"] for x in group),
                    "c": group[-1]["c"], "v": sum(x["v"] for x in group)})
            candles = aggregated
        return candles

    def _candles(self, market, symbol, timeframe):
        key = ("candles", market, symbol, timeframe)
        def load():
            cfg = MARKETS[market]
            if cfg["kind"] in ("crypto", "futures"):
                data = self.get(cfg["base"] + cfg["endpoint"] + "/klines",
                    {"symbol": symbol, "interval": BINANCE_INTERVALS[timeframe], "limit": 300})
                return [{"t": int(x[0] / 1000), "o": float(x[1]), "h": float(x[2]),
                         "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
            return self._yahoo_chart(symbol, timeframe)
        return self._cached(key, 30 if timeframe in ("1m","15m") else 180, load)

    @staticmethod
    def _closed_candles(candles):
        if len(candles) < 2:
            return []
        # Exclude the currently forming candle; providers return it as the last row.
        return candles[:-1]

    def _signal(self, market, symbol, timeframe, direction):
        candles = self._closed_candles(self._candles(market, symbol, timeframe))
        if len(candles) < 200:
            return None
        closes = [x["c"] for x in candles]
        ma200 = sum(closes[-200:]) / 200
        last = candles[-1]
        side = "شراء" if direction == "صاعد" else "بيع"
        if side == "شراء" and not (last["c"] > ma200 and last["c"] > last["o"]):
            return None
        if side == "بيع" and not (last["c"] < ma200 and last["c"] < last["o"]):
            return None
        recent = candles[-6:-1]
        if not recent:
            return None
        if side == "شراء":
            stop = min(x["l"] for x in recent)
            risk = last["c"] - stop
            target = last["c"] + risk * 3
        else:
            stop = max(x["h"] for x in recent)
            risk = stop - last["c"]
            target = last["c"] - risk * 3
        if risk <= 0 or target <= 0:
            return None
        return {"symbol": symbol, "side": side, "entry": round(last["c"], 10),
                "stop": round(stop, 10), "target": round(target, 10), "rr": "1:3",
                "timeframe": timeframe, "direction": direction, "closed_candle": True,
                "updated": datetime.now(timezone.utc).isoformat()}

    def _analyze(self, market, item, timeframe):
        symbol = item["symbol"]
        try:
            candles = self._candles(market, symbol, timeframe)
            closed = self._closed_candles(candles)
            if len(closed) < 200:
                return {"symbol": symbol, "direction": "غير متاح", "signal": None}
            closes = [x["c"] for x in closed]
            ma200 = sum(closes[-200:]) / 200
            last = closed[-1]
            if last["c"] > ma200 and last["c"] > closed[-2]["c"]:
                direction = "صاعد"
            elif last["c"] < ma200 and last["c"] < closed[-2]["c"]:
                direction = "هابط"
            else:
                direction = "محايد"
            signal = self._signal(market, symbol, timeframe, direction) if direction in ("صاعد","هابط") else None
            return {"symbol": symbol, "direction": direction, "signal": signal}
        except Exception:
            return {"symbol": symbol, "direction": "خطأ بيانات", "signal": None}

    def scan(self, market, timeframe="15m"):
        if market not in MARKETS:
            raise ValueError("السوق غير معروف")
        if timeframe not in TIMEFRAMES:
            raise ValueError("الفريم غير مدعوم")
        cfg = MARKETS[market]
        if cfg["kind"] == "unsupported":
            raise ValueError("عقود الخيارات الفعلية تحتاج مزود بيانات لسلاسل الخيارات؛ لن نعرض الأسهم الأساسية كأنها عقود.")
        key = ("scan", market, timeframe)
        with self.lock:
            old = self.cache.get(key)
            if old and time.time() - old[0] < 60:
                return old[1]
        if cfg["kind"] in ("crypto","futures"):
            universe = self._binance_symbols(market)
        else:
            universe = [{"symbol": s, "volume": None, "price": None, "change": None} for s in cfg["symbols"]]
        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self._analyze, market, item, timeframe) for item in universe]
            for future in as_completed(futures):
                results.append(future.result())
        counts = {d: sum(x["direction"] == d for x in results)
                  for d in ("صاعد","هابط","محايد","غير متاح","خطأ بيانات")}
        signals = [x["signal"] for x in results if x["signal"]]
        signals.sort(key=lambda x: x["symbol"])
        payload = {"market": market, "name": cfg["name"], "timeframe": timeframe,
                   "universe": len(universe), "counts": counts, "signals": signals,
                   "analyzed": len(results), "updated": datetime.now(timezone.utc).isoformat(),
                   "method": f"SMA200 + candle confirmation on {timeframe}; stop from recent structure; target 3R",
                   "coverage": "قائمة محدودة/جزئية" if cfg["kind"] == "yahoo" else "أزواج USDT المؤهلة بحجم تداول 24 ساعة يتجاوز مليون دولار",
                   "note": "النتائج مبنية على شموع مغلقة فقط. لا تمثل نسبة نجاح مستقبلية ولا تنفذ أوامر تداول."}
        with self.lock:
            self.cache[key] = (time.time(), payload)
        return payload

    def market_overview(self):
        return {"markets": [{"id": k, "name": v["name"], "type": v["kind"]} for k, v in MARKETS.items()],
                "timeframes": list(TIMEFRAMES), "strategy": "SMA200 per timeframe"}

    def news(self):
        feeds = ["https://www.cnbc.com/id/100003114/device/rss/rss.html",
                 "https://feeds.bbci.co.uk/news/business/rss.xml"]
        items = []
        for url in feeds:
            try:
                root = ET.fromstring(requests.get(url, headers=self.headers, timeout=(3, 6)).text)
                for item in root.findall(".//item")[:15]:
                    items.append({"title": item.findtext("title"), "url": item.findtext("link"),
                                  "published": item.findtext("pubDate"), "source": url.split("/")[2]})
            except Exception:
                continue
        return {"items": items, "note": "أخبار بعناوينها ومصادرها؛ لا يُنسب أثر سعري آلي قبل تحليل المحتوى."}
