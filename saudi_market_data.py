"""Saudi Exchange public market-watch adapter.

Uses the Exchange's own public market-watch JSON endpoint; no API key is
required. Yahoo and the legacy TradingView adapter remain as fallbacks.
"""
import math
import re
import time

import requests

BASE_URL = "https://www.saudiexchange.sa/wps/portal/saudiexchange/ourmarkets/main-market-watch"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SMART-TRADING-PRO/1.0)",
    "Accept": "application/json,text/html,*/*",
    "Referer": "https://www.saudiexchange.sa/",
}
DETAILS_PATH = (
    "/p0/IZ7_IPG41I82KGASC06S67RB9A0080="
    "CZ6_5A602H80O8DDC0QFK8HJ0O2067=NJgetMainNomucMarketDetails=/"
)
DETAILS_QUERY = (
    "sectorParameter=&tableViewParameter=1&iswatchListSelected=NO"
    "&requestLocale=en&_="
)


def _key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        raw = str(value).strip().replace(",", "").replace("%", "")
        if not raw or raw in ("-", "--", "N/A", "null"):
            return None
        result = float(raw)
    return result if math.isfinite(result) else None


def _pick(row, names):
    indexed = {_key(k): v for k, v in row.items()}
    for name in names:
        value = indexed.get(_key(name))
        if value not in (None, ""):
            parsed = _number(value)
            if parsed is not None:
                return parsed
    return None


def _payload_rows(payload):
    if not isinstance(payload, dict):
        raise ValueError("Saudi Exchange market-watch response is not an object")
    rows = payload.get("data") or payload.get("results") or payload.get("rows") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("results") or []
    if not isinstance(rows, list):
        raise ValueError("Saudi Exchange market-watch rows are missing")
    return [row for row in rows if isinstance(row, dict)]


def _market_watch_url(session):
    page = session.get(BASE_URL, timeout=(5, 15))
    page.raise_for_status()
    location = page.headers.get("content-location") or page.headers.get("Content-Location") or page.url
    match = re.search(r"/z1/(.+?)/dz(?:[/?#]|$)", location, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Saudi Exchange did not provide a market-watch session path")
    session_path = match.group(1)
    return (
        BASE_URL.rstrip("/") + "/!ut/p/z1/" + session_path
        + DETAILS_PATH + "?" + DETAILS_QUERY + str(int(time.time() * 1000))
    )


def official_saudi_quotes(allowed_symbols=None):
    """Return normalized TASI quote rows from the official public exchange feed."""
    session = requests.Session()
    session.headers.update(HEADERS)
    url = _market_watch_url(session)
    response = session.get(url, timeout=(5, 20))
    response.raise_for_status()
    rows = _payload_rows(response.json())
    allowed = set(allowed_symbols or ())
    output = []
    for item in rows:
        symbol = str(
            item.get("companySymbol") or item.get("symbol")
            or item.get("ticker") or item.get("securityCode") or ""
        ).strip()
        if not re.fullmatch(r"\d{4}", symbol):
            continue
        if allowed and symbol + ".SR" not in allowed and symbol not in allowed:
            continue
        market_type = str(
            item.get("market_type") or item.get("marketType")
            or item.get("marketSegment") or ""
        ).strip().lower()
        if market_type and market_type not in ("m", "main", "main market", "tasi"):
            continue

        price = _pick(item, (
            "lastTradePrice", "lastTradedPrice", "lastPrice",
            "currentPrice", "closePrice", "close", "price",
        ))
        if price is None or price <= 0:
            continue
        volume = _pick(item, (
            "volumeTraded", "totalVolume", "tradedVolume",
            "totalTradedVolume", "volume", "quantityTraded",
        )) or 0.0
        change_pct = _pick(item, (
            "changePercent", "changePercentage", "changePct",
            "percentageChange", "changePercentValue",
        ))
        if change_pct is None:
            change = _pick(item, ("change", "priceChange", "netChange"))
            previous = _pick(item, (
                "previousClosePrice", "previousClose", "prevClose",
                "previousDayClose", "previousClosingPrice",
            ))
            if previous and previous > 0:
                change_pct = (price / previous - 1.0) * 100.0
            elif change is not None and price - change > 0:
                change_pct = (price / (price - change) - 1.0) * 100.0
            else:
                change_pct = 0.0
        if not all(math.isfinite(x) for x in (price, change_pct, volume)):
            continue
        output.append({
            "symbol": symbol + ".SR",
            "price": price,
            "change_pct": change_pct,
            "quote_volume": max(0.0, price * max(0.0, volume)),
            "volume": max(0.0, volume),
            "currency": "SAR",
            "source": "Saudi Exchange",
        })
    if not output:
        raise ValueError(
            "Saudi Exchange market-watch returned no usable TASI quotes "
            f"(rows={len(rows)})"
        )
    return output
