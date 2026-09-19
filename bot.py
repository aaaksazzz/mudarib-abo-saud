import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
import requests

from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "state.json"
)

TRAIL_START = 0.012       # +1.2%
TRAIL_DISTANCE = 0.006    # 0.6%

session = requests.Session()

if API_KEY:
    session.headers.update({
        "X-MBX-APIKEY": API_KEY
    })


# =========================
# WEB SERVER & DASHBOARD
# =========================

class WebHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        state = load_state() or {}
        in_position = state.get("in_position", False)
        
        usdt_balance = state.get("usdt_balance", 0.0)
        binance_status = state.get("binance_status", "🔴 غير متصل")
        last_scanned = state.get("last_scanned_symbol", "-")
        total_symbols = state.get("total_symbols", 0)

        if in_position:
            symbol = state.get("symbol", "-")
            entry = state.get("entry", 0)
            highest = state.get("highest", entry)

            try:
                price = get_price(symbol)
                profit = ((price / entry) - 1) * 100 if entry else 0
                trail = highest * (1 - TRAIL_DISTANCE)

                position_html = f"""
                <div class="card active-position">
                    <h2>🟢 صفقة مفتوحة حالياً</h2>
                    <div class="grid">
                        <div class="item"><span>💎 العملة:</span> <strong>{symbol}</strong></div>
                        <div class="item"><span>📍 سعر الدخول:</span> <strong>{entry:.8f} USDT</strong></div>
                        <div class="item"><span>💰 السعر الحالي:</span> <strong>{price:.8f} USDT</strong></div>
                        <div class="item"><span>📈 نسبة الربح:</span> <strong style="color: {'#00ff88' if profit >= 0 else '#ff4d4d'};">{profit:.2f}%</strong></div>
                        <div class="item"><span>🔝 أعلى سعر وصل له:</span> <strong>{highest:.8f} USDT</strong></div>
                        <div class="item"><span>🛡️ سعر تأمين الربح:</span> <strong>{trail:.8f} USDT</strong></div>
                    </div>
                </div>
                """
            except Exception:
                position_html = """
                <div class="card">
                    <h2>⚠️ جاري تحديث أسعار الصفقة الحالية من Binance...</h2>
                </div>
                """
        else:
            position_html = f"""
            <div class="card no-position">
                <h2>🟡 لا توجد صفقة مفتوحة حالياً</h2>
                <p>البوت يقوم بفحص السوق بحثاً عن إشارات الدخول...</p>
                <div class="item">🔍 آخر عملة تم فحصها: <strong>{last_scanned}</strong> ({total_symbols} عملة إجمالاً)</div>
            </div>
            """

        page = f"""
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="refresh" content="10">
            <title>مضارب أبو سعود V2</title>
            <style>
                body {{
                    background-color: #0d1117;
                    color: #e6edf3;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 700px;
                    margin: 0 auto;
                }}
                .header {{
                    text-align: center;
                    border-bottom: 2px solid #21262d;
                    padding-bottom: 15px;
                    margin-bottom: 20px;
                }}
                .header h1 {{
                    color: #00ff88;
                    margin: 0 0 5px 0;
                }}
                .card {{
                    background: #161b22;
                    border: 1px solid #30363d;
                    border-radius: 12px;
                    padding: 20px;
                    margin-bottom: 20px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }}
                .active-position {{
                    border-right: 5px solid #00ff88;
                }}
                .no-position {{
                    border-right: 5px solid #e3b341;
                }}
                .grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 15px;
                    margin-top: 15px;
                }}
                @media (max-width: 500px) {{
                    .grid {{ grid-template-columns: 1fr; }}
                }}
                .item {{
                    background: #21262d;
                    padding: 12px;
                    border-radius: 8px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                .footer {{
                    text-align: center;
                    font-size: 0.85em;
                    color: #8b949e;
                    margin-top: 15px;
                }}
                .badge {{
                    background: #238636;
                    color: white;
                    padding: 3px 8px;
                    border-radius: 12px;
                    font-size: 0.8em;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 مضارب أبو سعود V2</h1>
                    <p>نظام التداول الآلي والمتابعة المباشرة <span class="badge">شغال ONLINE</span></p>
                </div>

                <div class="card">
                    <h3>💵 الرصيد واتصال المنصة</h3>
                    <div class="grid">
                        <div class="item"><span>حالة منصة Binance:</span> <strong>{binance_status}</strong></div>
                        <div class="item"><span>رصيد USDT المتاح:</span> <strong>{usdt_balance:.2f} USDT</strong></div>
                        <div class="item"><span>الفريمات المستهدفة:</span> <strong>15m / 1h</strong></div>
                        <div class="item"><span>تأمين الربح (Trailing):</span> <strong>+{TRAIL_START*100}%</strong></div>
                    </div>
                </div>

                {position_html}

                <div class="footer">
                    ⏱️ تحديث تلقائي للصفحة كل 10 ثوانٍ
                </div>
            </div>
        </body>
        </html>
        """

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format, *args):
        return


def start_web():
    server = HTTPServer(("0.0.0.0", PORT), WebHandler)
    print(f"🌐 Render Port: {PORT}")
    server.serve_forever()


# =========================
# BINANCE API & STATE
# =========================

def public(path, params=None):
    while True:
        try:
            r = session.get(BASE + path, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("\n⚠️ اتصال Binance:", e)
            time.sleep(15)


def signed(method, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    r = session.request(method, BASE + path, params=params, timeout=15)
    data = r.json()
    if r.status_code >= 400:
        raise Exception(data)
    return data


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def update_state(data):
    current = load_state()
    current.update(data)
    save_state(current)


def get_usdt():
    data = signed("GET", "/api/v3/account")
    for b in data["balances"]:
        if b["asset"] == "USDT":
            return float(b["free"])
    return 0.0


def get_symbols():
    data = public("/api/v3/exchangeInfo")
    result = []
    for x in data["symbols"]:
        if x["status"] == "TRADING" and x["quoteAsset"] == "USDT" and x.get("isSpotTradingAllowed", False):
            filters = {f["filterType"]: f for f in x["filters"]}
            lot = filters.get("LOT_SIZE")
            if lot:
                result.append({"symbol": x["symbol"], "step": lot["stepSize"]})
    return result


def get_price(symbol):
    data = public("/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"])


# =========================
# MAIN
# =========================

def main():
    print("=============================================")
    print("مضارب أبو سعود V2 🤖")
    print("=============================================")

    if not API_KEY or not API_SECRET:
        print("❌ مفاتيح Binance غير موجودة")
        update_state({"binance_status": "❌ المفاتيح مفقودة"})
        return

    try:
        account = signed("GET", "/api/v3/account")
        if account.get("canTrade"):
            print("✅ Binance متصل | ✅ التداول مفعّل")
            update_state({"binance_status": "🟢 متصل والتداول مفعّل"})
        else:
            print("⚠️ Binance متصل بدون صلاحية تداول")
            update_state({"binance_status": "⚠️ اتصال بدون صلاحية تداول"})
    except Exception as e:
        print("❌ فشل الاتصال بـ Binance:", e)
        update_state({"binance_status": f"❌ خطأ اتصال: {str(e)[:20]}"})
        return

    symbols = get_symbols()
    update_state({"total_symbols": len(symbols)})

    while True:
        try:
            usdt_balance = get_usdt()
            update_state({"usdt_balance": usdt_balance, "binance_status": "🟢 متصل"})
        except Exception as e:
            update_state({"binance_status": "⚠️ خطأ قراءة الرصيد"})

        for i, info in enumerate(symbols, 1):
            symbol = info["symbol"]
            update_state({"last_scanned_symbol": symbol})
            time.sleep(1)


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web, daemon=True)
    web_thread.start()
    main()
