"""Read-only GammaFlip GEX client with freshness checks and a conservative daily quota guard."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import threading

import requests

BASE_URL = "https://api.gammaflip.io/api/v1"
SUPPORTED_CRYPTO = ("BTC", "ETH", "SOL", "XRP", "HYPE")
DEFAULT_DAILY_BUDGET = 40  # Keep 10 of the 50-request trial quota in reserve.
_budget_lock = threading.Lock()
_budget_day = None
_budget_used = 0


def reserve_daily_requests(count, budget=DEFAULT_DAILY_BUDGET, now=None):
    """Reserve API calls by UTC day before making requests; failed calls still count."""
    global _budget_day, _budget_used
    day = (now or datetime.now(timezone.utc)).date()
    with _budget_lock:
        if _budget_day != day:
            _budget_day, _budget_used = day, 0
        if count < 1 or _budget_used + count > budget:
            return False
        _budget_used += count
        return True


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_levels(coin, api_key, timeout=(2.5, 5.0)):
    """Fetch one combined crypto options GEX snapshot; never fabricate missing levels."""
    symbol = str(coin).upper().strip()
    if symbol not in SUPPORTED_CRYPTO:
        raise ValueError("unsupported_coin")
    if not api_key or not api_key.startswith("gex_sk_"):
        raise ValueError("api_key_not_configured")
    response = requests.get(
        f"{BASE_URL}/levels/all/{symbol}",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(meta, dict):
        raise ValueError("invalid_provider_payload")
    if meta.get("market") != "crypto":
        raise ValueError("provider_market_mismatch")

    as_of = meta.get("as_of") or meta.get("timestamp")
    if not as_of:
        raise ValueError("missing_data_timestamp")
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid_data_timestamp")
    if age < -60 or age > 1800:
        raise ValueError("stale_gamma_data")

    return {
        "symbol": symbol,
        "status": "live",
        "spot": _number(data.get("spot")),
        "flip": _number(data.get("flip")),
        "regime": data.get("regime") if data.get("regime") in ("positive", "negative") else None,
        "net_gex": _number(data.get("net_gex")),
        "abs_gex": _number(data.get("abs_gex")),
        "call_gex": _number(data.get("call_gex")),
        "put_gex": _number(data.get("put_gex")),
        "p1_strike": _number(data.get("p1_strike")),
        "n1_strike": _number(data.get("n1_strike")),
        "a1_strike": _number(data.get("a1_strike")),
        "as_of": as_of,
        "exchange": meta.get("exchange_resolved") or meta.get("exchange") or "all",
        "units": data.get("units") or meta.get("units") or "USD per 1% move",
    }


def fetch_supported_crypto(api_key, budget=DEFAULT_DAILY_BUDGET):
    """Fetch all supported coins in a bounded batch; called only on explicit user refresh."""
    if not reserve_daily_requests(len(SUPPORTED_CRYPTO), budget=budget):
        return {
            "status": "daily_budget_reached",
            "message": "تم إيقاف طلبات Gamma مؤقتًا لحماية حصة API اليومية.",
            "items": [],
        }

    items = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(fetch_levels, coin, api_key): coin for coin in SUPPORTED_CRYPTO}
        for job in as_completed(jobs):
            coin = jobs[job]
            try:
                items.append(job.result())
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                code = "provider_rate_limit" if status == 429 else "provider_auth_error" if status in (401, 403) else "provider_http_error"
                items.append({"symbol": coin, "status": code})
            except requests.RequestException:
                items.append({"symbol": coin, "status": "provider_unavailable"})
            except ValueError as exc:
                items.append({"symbol": coin, "status": str(exc)})
    items.sort(key=lambda row: SUPPORTED_CRYPTO.index(row["symbol"]))
    live = sum(1 for row in items if row.get("status") == "live")
    return {
        "status": "live" if live == len(SUPPORTED_CRYPTO) else "partial" if live else "unavailable",
        "items": items,
        "updated": datetime.now(timezone.utc).isoformat(),
        "quota_cost": len(SUPPORTED_CRYPTO),
        "quota_note": "كل تحديث يستهلك حتى 5 طلبات من حصة GammaFlip اليومية.",
    }
