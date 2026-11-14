"""Public no-key market-data routing with automatic mirror rotation.

Each mirror serves up to 20 successful JSON fetches before the next mirror
becomes preferred. A transport, rate-limit, server, or mirror-specific HTTP
failure triggers immediate failover. Mirrors are not independent vendors.
"""
import threading
import requests

ROTATE_AFTER_SUCCESSES = 20
ROUTES = {
    "binance_spot": (
        "https://api.binance.com", "https://api1.binance.com",
        "https://api2.binance.com", "https://api3.binance.com",
        "https://api4.binance.com",
    ),
    "binance_futures": (
        "https://fapi.binance.com", "https://fapi1.binance.com",
        "https://fapi2.binance.com", "https://fapi3.binance.com",
        "https://fapi4.binance.com",
    ),
    "yahoo_finance": (
        "https://query1.finance.yahoo.com",
        "https://query2.finance.yahoo.com",
    ),
    "binance_alpha": ("https://www.binance.com",),
}
_LOCK = threading.RLock()
_STATE = {key: {"index": 0, "successes": 0, "last_error": None}
          for key in ROUTES}


def _route_for(url):
    for key, hosts in ROUTES.items():
        for host in hosts:
            if url.startswith(host + "/") or url == host:
                return key, host
    return None, None


def request_json(url, params=None, timeout=(3.05, 10), headers=None, method="GET", json_body=None):
    """Fetch JSON, rotating mirrors after 20 successes and failing over immediately."""
    route, matched_host = _route_for(url)
    if not route:
        response = requests.request(method, url, params=params, json=json_body,
                                    timeout=timeout, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Unexpected market-data response")
        return payload

    with _LOCK:
        start = _STATE[route]["index"]
    hosts = ROUTES[route]
    ordered = [hosts[(start + offset) % len(hosts)] for offset in range(len(hosts))]
    errors = []
    for host in ordered:
        candidate = host + url[len(matched_host):]
        try:
            response = requests.request(method, candidate, params=params, json=json_body,
                                        timeout=timeout, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Unexpected market-data response")
            with _LOCK:
                state = _STATE[route]
                state["index"] = hosts.index(host)
                state["successes"] += 1
                state["last_error"] = None
                if state["successes"] >= ROTATE_AFTER_SUCCESSES and len(hosts) > 1:
                    state["index"] = (state["index"] + 1) % len(hosts)
                    state["successes"] = 0
            return payload
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{host}: {type(exc).__name__}")
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(status, int) and status in (400, 401, 422):
                raise
            with _LOCK:
                state = _STATE[route]
                state["index"] = (hosts.index(host) + 1) % len(hosts)
                state["successes"] = 0
                state["last_error"] = type(exc).__name__
    raise RuntimeError(f"All public mirrors failed for {route}: " + "; ".join(errors))


def provider_route_status():
    with _LOCK:
        return {
            key: {
                "hosts": list(hosts),
                "preferred_host": hosts[_STATE[key]["index"]],
                "successful_fetches_on_host": _STATE[key]["successes"],
                "rotate_after": ROTATE_AFTER_SUCCESSES,
                "last_error": _STATE[key]["last_error"],
                "requires_api_key": False,
                "independent_vendor_failover": False,
            }
            for key, hosts in ROUTES.items()
        }
