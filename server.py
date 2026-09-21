import requests

from flask import Flask, jsonify, send_from_directory, request


app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)


BINANCE_BASE = "https://api.binance.com"


# ==========================================
# الصفحة الرئيسية
# ==========================================

@app.route("/")
def home():

    return send_from_directory(
        ".",
        "index.html"
    )


# ==========================================
# Binance - جميع العملات
# ==========================================

@app.route("/api/binance/exchange-info")
def binance_exchange_info():

    try:

        response = requests.get(
            f"{BINANCE_BASE}/api/v3/exchangeInfo",
            timeout=20
        )


        response.raise_for_status()


        return jsonify(
            response.json()
        )


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ==========================================
# Binance - الشموع
# ==========================================

@app.route("/api/binance/klines")
def binance_klines():

    symbol = request.args.get(
        "symbol",
        ""
    ).upper()


    interval = request.args.get(
        "interval",
        "15m"
    )


    limit = request.args.get(
        "limit",
        "100"
    )


    if not symbol:

        return jsonify({
            "error": "symbol required"
        }), 400


    try:

        response = requests.get(

            f"{BINANCE_BASE}/api/v3/klines",

            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },

            timeout=20

        )


        response.raise_for_status()


        return jsonify(
            response.json()
        )


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ==========================================
# تشغيل
# ==========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
