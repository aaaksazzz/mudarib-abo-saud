import os, sqlite3, secrets, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from ai_engine import analyze as ai_analyze

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
PORT = int(os.getenv("PORT", "8080"))
DB = os.getenv("SQLITE_FILE", "mudarib.db")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent":"Mozilla/5.0 Mudarib-Abo-Saud/6.0"})
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "aaaksazzz").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
TRC20_ADDRESS = os.getenv("TRC20_ADDRESS", "").strip()
BINANCE_PAY_ID = os.getenv("BINANCE_PAY_ID", "").strip()

PLANS = {"7d":{"name":"7 أيام","days":7,"amount":10},"30d":{"name":"30 يوم","days":30,"amount":20},"90d":{"name":"90 يوم","days":90,"amount":30}}
MARKETS = {
 "saudi":[("2222.SR","أرامكو"),("2010.SR","سابك"),("1120.SR","الراجحي"),("1180.SR","الأهلي السعودي"),("1150.SR","مصرف الإنماء"),("7010.SR","STC"),("1211.SR","معادن"),("2380.SR","بترو رابغ"),("4003.SR","إكسترا"),("4200.SR","الدريس")],
 "usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("GOOGL","Alphabet"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],
 "forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("XAUUSD=X","Gold")]
}

def db():
    c=sqlite3.connect(DB, timeout=20, check_same_thread=False); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL,plan TEXT NOT NULL,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """); c.commit(); c.close()

def json_ok(**x): return jsonify({"ok":True,**x})
def user_name(): return session.get("user")
def is_admin(): return bool(session.get("admin"))

def yahoo(symbol, interval="1d", range_="3mo"):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+symbol
    r=HTTP.get(url,params={"interval":interval,"range":range_},timeout=12); r.raise_for_status()
    res=r.json()["chart"]["result"][0]; q=res["indicators"]["quote"][0]; ts=res.get("timestamp",[])
    rows=[]
    for i,t in enumerate(ts):
        try:
            rows.append({"time":t,"open":float(q["open"][i]),"high":float(q["high"][i]),"low":float(q["low"][i]),"close":float(q["close"][i]),"volume":float(q.get("volume",[0]*len(ts))[i] or 0)})
        except: pass
    return rows

def okx(inst_type="SPOT"):
    r=HTTP.get("https://www.okx.com/api/v5/market/tickers",params={"instType":inst_type},timeout=12); r.raise_for_status()
    return r.json().get("data",[])

def okx_candles(inst, bar="15m", limit=100):
    r=HTTP.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":limit},timeout=12); r.raise_for_status()
    out=[]
    for x in reversed(r.json().get("data",[])):
        try: out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except: pass
    return out

def analyze(candles, symbol, market, interval="15m"):
    if not candles or len(candles) < 70:
        return None
    normalized=[]
    for x in candles:
        try:
            normalized.append({"t":x["time"],"o":float(x["open"]),"h":float(x["high"]),"l":float(x["low"]),"c":float(x["close"]),"v":float(x.get("volume",0) or 0)})
        except (KeyError,TypeError,ValueError):
            continue
    if len(normalized) < 70:
        return None
    result=ai_analyze(normalized,symbol,market,interval)
    result["price"]=result.get("price",result.get("entry"))
    return result

