import os
import time
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

BYBIT_BASE = os.getenv("BYBIT_BASE", "https://api.bybit.com").rstrip("/")
TIMEOUT = int(os.getenv("BYBIT_TIMEOUT", "15"))

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mudarib-Abo-Saud-Bybit-Service/1.0",
    "Accept": "application/json",
})


def bybit_request(path, params=None):
    url = BYBIT_BASE + path
    r = HTTP.get(url, params=params or {}, timeout=TIMEOUT)
    content_type = r.headers.get("content-type", "")
    try:
        data = r.json()
    except Exception:
        body = r.text[:500]
        raise RuntimeError(f"Bybit HTTP {r.status_code}: {body}")

    if r.status_code != 200:
        raise RuntimeError(
            f"Bybit HTTP {r.status_code}: {data.get('retMsg') or data}"
        )
    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit retCode {data.get('retCode')}: {data.get('retMsg', 'unknown error')}"
        )
    return data


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "mudarib-abo-saud-bybit",
        "source": "Bybit Spot",
    })


@app.get("/health")
def health():
    try:
        data = bybit_request("/v5/market/time")
        return jsonify({
            "ok": True,
            "connected": True,
            "source": "Bybit Spot",
            "server_time": data.get("result", {}).get("timeNano"),
        })
    except Exception as e:
        return jsonify({"ok": False, "connected": False, "error": str(e)}), 502


@app.post("/proxy")
def proxy():
    body = request.get_json(silent=True) or {}
    path = str(body.get("path", "")).strip()
    params = body.get("params") or {}

    # Only public market-data endpoints are allowed through this service.
    allowed = {
        "/v5/market/time",
        "/v5/market/instruments-info",
        "/v5/market/tickers",
        "/v5/market/kline",
    }
    if path not in allowed:
        return jsonify({"ok": False, "error": "Endpoint not allowed"}), 400

    try:
        data = bybit_request(path, params)
        return jsonify({"ok": True, "result": data.get("result", {})})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
