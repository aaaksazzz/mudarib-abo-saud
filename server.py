import os
import requests

from flask import (
    Flask,
    jsonify,
    send_from_directory
)


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


app = Flask(
    __name__,
    static_folder=BASE_DIR,
    static_url_path=""
)


@app.get("/")
def index():

    return send_from_directory(
        BASE_DIR,
        "index.html"
    )


@app.get("/api/binance/exchange-info")
def binance_exchange_info():

    url = (
        "https://api.binance.com"
        "/api/v3/exchangeInfo"
    )

    response = requests.get(
        url,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()


    symbols = [

        {
            "symbol": x["symbol"],
            "status": x["status"],
            "baseAsset": x["baseAsset"],
            "quoteAsset": x["quoteAsset"]
        }

        for x in data.get(
            "symbols",
            []
        )

    ]


    return jsonify({
        "symbols": symbols
    })


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
