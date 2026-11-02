"""Credentialed public market-data adapters for Saudi and US equities.

Credentials are server-side environment variables only. Never expose them to
clients, log them, or mix providers inside a single market series.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests

SAHMK_BASE = "https://api.sahmk.sa/api/v1"
ALPACA_DATA_BASE = "https://data.alpaca.markets"
ALPACA_TRADING_BASE = "https://api.alpaca.markets"
REQUEST_TIMEOUT = (3.5, 12)


def _get_json(url, *, headers=None, params=None):
    response = requests.get(
        url, headers=headers or {}, params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise requests.RequestException("Market provider returned invalid JSON")
    return payload


def _sahmk_headers():
    key = os.environ.get("SAHMK_API_KEY", "").strip()
    if not key:
        raise requests.RequestException("SAHMK_API_KEY is not configured")
    return {"X-API-Key": key, "Accept": "application/json"}


def sahmk_symbols():
    """Return every active TASI equity; excludes ETFs, sukuk and NOMU."""
    headers = _sahmk_headers()
    symbols, offset, total = [], 0, None
    while total is None or offset < total:
        payload = _get_json(
            SAHMK_BASE + "/companies/",
            headers=headers,
            params={"market": "TASI", "limit": 500, "offset": offset},
        )
        rows = payload.get("results") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (str(row.get("status", "")).lower() == "active"
                    and str(row.get("security_type", "")).lower() == "equity"
                    and str(row.get("market", "TASI")).upper() == "TASI"):
                symbol = str(row.get("symbol") or "").strip()
                if symbol:
                    symbols.append(symbol)
        total = int(payload.get("total", offset + len(rows)))
        if not rows or len(rows) < 500:
            break
        offset += len(rows)
    if not symbols:
        raise requests.RequestException("SAHMK returned no active TASI equities")
    return list(dict.fromkeys(symbols))


def sahmk_market_tickers():
    """Fetch the complete TASI equity universe in provider-supported batches."""
    headers = _sahmk_headers()
    symbols = sahmk_symbols()
    output = []
    for offset in range(0, len(symbols), 50):
        batch = symbols[offset:offset + 50]
        payload = _get_json(
            SAHMK_BASE + "/quotes/",
            headers=headers,
            params={"symbols": ",".join(batch), "data_mode": "delayed"},
        )
        rows = payload.get("quotes") or payload.get("data") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            try:
                price = float(row.get("price") or row.get("last") or 0)
                change = float(row.get("change_percent") or row.get("changePercent") or 0)
                volume = float(row.get("volume") or 0)
                high = float(row.get("high") or row.get("day_high") or price)
                low = float(row.get("low") or row.get("day_low") or price)
            except (TypeError, ValueError):
                continue
            if symbol in batch and price > 0:
                output.append({
                    "symbol": symbol, "price": price, "volume": volume * price,
                    "change24h": change,
                    "range24h": ((high - low) / price * 100) if high >= low > 0 else 0.0,
                    "quote_age_seconds": None,
                })
    if not output:
        raise requests.RequestException("SAHMK returned no usable TASI quotes")
    return output


def _parse_stamp(value):
    if isinstance(value, (int, float)):
        return int(value if value > 10**12 else value * 1000)
    stamp = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def sahmk_candles(symbol, interval):
    headers = _sahmk_headers()
    if interval == "4h":
        provider_interval, days = "60min", 90
    elif interval == "1d":
        provider_interval, days = "1d", 90
    elif interval == "15m":
        provider_interval, days = "15min", 7
    elif interval == "1h":
        provider_interval, days = "60min", 30
    elif interval == "1w":
        provider_interval, days = "1w", 730
    elif interval == "1M":
        provider_interval, days = "1mo", 3650
    else:
        raise requests.RequestException("Unsupported SAHMK candle interval")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    payload = _get_json(
        SAHMK_BASE + f"/historical/{symbol}/",
        headers=headers,
        params={
            "interval": provider_interval, "from": start.isoformat(),
            "to": end.isoformat(), "limit": 2000, "offset": 0,
        },
    )
    rows = []
    for bar in payload.get("data") or []:
        try:
            stamp = _parse_stamp(bar.get("date"))
            row = {
                "open": float(bar["open"]), "high": float(bar["high"]),
                "low": float(bar["low"]), "close": float(bar["close"]),
                "volume": float(bar.get("volume") or 0), "time": stamp,
            }
            if row["close"] > 0 and row["high"] >= row["low"]:
                rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    rows.sort(key=lambda item: item["time"])
    if interval == "4h":
        rows = _aggregate(rows, 4 * 60 * 60 * 1000)
    return rows


def _aggregate(rows, width_ms):
    buckets = {}
    for row in rows:
        key = row["time"] // width_ms * width_ms
        current = buckets.get(key)
        if current is None:
            buckets[key] = {
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "volume": row["volume"], "time": key,
            }
        else:
            current["high"] = max(current["high"], row["high"])
            current["low"] = min(current["low"], row["low"])
            current["close"] = row["close"]
            current["volume"] += row["volume"]
    now_ms = int(time.time() * 1000)
    return [bar for _, bar in sorted(buckets.items())
            if bar["time"] + width_ms <= now_ms]


def _alpaca_credentials():
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise requests.RequestException(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY are required"
        )
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


def _alpaca_feed():
    feed = os.environ.get("ALPACA_DATA_FEED", "delayed_sip").strip().lower()
    if feed not in ("iex", "sip", "delayed_sip"):
        raise requests.RequestException("ALPACA_DATA_FEED must be iex, sip, or delayed_sip")
    return feed


def alpaca_market_tickers():
    """Screen all active tradable US equities using the configured Alpaca feed."""
    headers = _alpaca_credentials()
    feed = _alpaca_feed()
    assets = _get_json(
        ALPACA_TRADING_BASE + "/v2/assets",
        headers=headers,
        params={"status": "active", "asset_class": "us_equity"},
    )
    symbols = [
        str(row.get("symbol") or "") for row in assets
        if isinstance(row, dict) and row.get("tradable")
        and row.get("status") == "active"
        and str(row.get("exchange") or "").upper() != "OTC"
        and not ({"etf", "closed_end_fund"} & {str(v).lower() for v in (row.get("attributes") or [])})
        and row.get("symbol")
    ]
    output = []
    # Alpaca supports multi-symbol snapshots; bound batches and concurrency
    # to avoid an unbounded request burst on the small application instance.
    batches = [symbols[i:i + 100] for i in range(0, len(symbols), 100)]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def load_batch(batch):
        return _get_json(
            ALPACA_DATA_BASE + "/v2/stocks/snapshots",
            headers=headers,
            params={"symbols": ",".join(batch), "feed": feed},
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(load_batch, batch) for batch in batches]
        for job in as_completed(jobs):
            payload = job.result()
            for symbol, snap in (payload or {}).items():
                if not isinstance(snap, dict):
                    continue
                daily = snap.get("dailyBar") or {}
                previous = snap.get("prevDailyBar") or {}
                trade = snap.get("latestTrade") or {}
                try:
                    price = float(trade.get("p") or daily.get("c") or 0)
                    previous_close = float(previous.get("c") or 0)
                    volume = float(daily.get("v") or 0)
                    high = float(daily.get("h") or price)
                    low = float(daily.get("l") or price)
                except (TypeError, ValueError):
                    continue
                if price <= 0 or previous_close <= 0 or volume * price < 1_000_000:
                    continue
                output.append({
                    "symbol": symbol, "price": price, "volume": volume * price,
                    "change24h": (price / previous_close - 1) * 100,
                    "range24h": ((high - low) / price * 100) if high >= low > 0 else 0.0,
                })
    if not output:
        raise requests.RequestException("Alpaca returned no usable US stock snapshots")
    output.sort(key=lambda row: row["symbol"])
    return output


def alpaca_candles(symbol, interval):
    headers = _alpaca_credentials()
    feed = _alpaca_feed()
    if interval == "4h":
        provider_interval, days, aggregate = "1Hour", 90, True
    elif interval == "1d":
        provider_interval, days, aggregate = "1Day", 365, False
    elif interval == "15m":
        provider_interval, days, aggregate = "15Min", 7, False
    elif interval == "1h":
        provider_interval, days, aggregate = "1Hour", 30, False
    elif interval == "1w":
        provider_interval, days, aggregate = "1Week", 730, False
    elif interval == "1M":
        provider_interval, days, aggregate = "1Month", 3650, False
    else:
        raise requests.RequestException("Unsupported Alpaca candle interval")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    payload = _get_json(
        ALPACA_DATA_BASE + f"/v2/stocks/{symbol}/bars",
        headers=headers,
        params={
            "timeframe": provider_interval,
            "start": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "limit": 1000, "feed": feed, "adjustment": "all",
        },
    )
    rows = []
    for bar in payload.get("bars") or []:
        try:
            row = {
                "open": float(bar["o"]), "high": float(bar["h"]),
                "low": float(bar["l"]), "close": float(bar["c"]),
                "volume": float(bar.get("v") or 0), "time": _parse_stamp(bar["t"]),
            }
            if row["close"] > 0 and row["high"] >= row["low"]:
                rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    rows.sort(key=lambda item: item["time"])
    if aggregate:
        rows = _aggregate(rows, 4 * 60 * 60 * 1000)
    return rows


def provider_status():
    return {
        "saudi": {
            "configured": bool(os.environ.get("SAHMK_API_KEY", "").strip()),
            "provider": "SAHMK",
            "required_plan": "Pro or higher for 15m/60m historical candles",
            "coverage": "active TASI equities; no volume floor",
        },
        "us": {
            "configured": bool(os.environ.get("ALPACA_API_KEY", "").strip()
                               and os.environ.get("ALPACA_SECRET_KEY", "").strip()),
            "provider": "Alpaca Market Data",
            "feed": os.environ.get("ALPACA_DATA_FEED", "delayed_sip").strip().lower(),
            "coverage": "active tradable US equities; delayed_sip gives consolidated 15-minute delayed coverage, iex is IEX-only, sip requires entitlement",
        },
    }
