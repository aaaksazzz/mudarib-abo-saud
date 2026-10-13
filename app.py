import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
app = FastAPI(title="التداول الذكي PRO", version="2.0.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

BINANCE = {
    "spot": "https://api.binance.com/api/v3/ticker/24hr",
    "futures": "https://fapi.binance.com/fapi/v1/ticker/24hr",
}
CACHE = {}
CACHE_TTL = 20
STABLES = {"USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP", "USDE"}


def fetch_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": "SmartTradingPro/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@app.get("/", response_class=HTMLResponse)
def home():
    page = BASE / "static" / "index.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "service": "smart-trading-pro", "version": "2.0.0", "timestamp": int(time.time())}


@app.get("/api/market/{market}")
def market_data(market: str, limit: int = Query(40, ge=1, le=100)):
    market = market.lower()
    if market not in BINANCE:
        return JSONResponse({
            "ok": True, "market": market, "live": False, "items": [],
            "message": "مصدر الأسعار المباشر لهذا السوق غير مربوط حاليًا؛ لم نعرض بيانات تقديرية."
        })
    now = time.time()
    cached = CACHE.get(market)
    if cached and now - cached[0] < CACHE_TTL:
        data = cached[1]
    else:
        try:
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
                rows.append({
                    "symbol": symbol, "price": price, "change_pct": change,
                    "quote_volume": quote_volume,
                })
            rows.sort(key=lambda x: x["quote_volume"], reverse=True)
            data = rows
            CACHE[market] = (now, data)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return JSONResponse({
                "ok": False, "market": market, "live": False, "items": [],
                "message": "تعذر جلب الأسعار المباشرة الآن. حاول التحديث بعد قليل."
            }, status_code=503)
    return {"ok": True, "market": market, "live": True, "updated_at": int(now), "items": data[:limit]}


@app.get("/api/status")
def status():
    return {"ok": True, "site": "ready", "markets": {"spot": "live", "futures": "live", "alpha": "not_connected", "contracts": "not_connected", "us": "not_connected", "saudi": "not_connected", "forex": "not_connected", "gold": "not_connected"}}
