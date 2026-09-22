import os, time, json, re, html, hashlib, hmac, secrets, threading, csv, io
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests
import psycopg
from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "aaaksazzz")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
PAYMENT_ADDRESS = os.getenv("TRC20_ADDRESS", "TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6")

PLANS = {
    "7d": {"name": "7 أيام", "days": 7, "amount": 10.0},
    "15d": {"name": "15 يوم", "days": 15, "amount": 20.0},
    "30d": {"name": "30 يوم", "days": 30, "amount": 30.0},
}

# مصادر الأسواق العامة. لا توجد مفاتيح API هنا.
BYBIT_BASE = os.getenv("BYBIT_BASE", "https://api.bybit.com")
YAHOO_BASE = os.getenv("YAHOO_BASE", "https://query1.finance.yahoo.com")
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SAUDI_EXCHANGE_HOME = "https://www.saudiexchange.sa/"

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36 Mudarib-Abo-Saud/3.0"
})

MARKET_CACHE = {"ts": 0, "symbols": []}
US_CACHE = {"ts": 0, "symbols": []}
SAUDI_CACHE = {"ts": 0, "symbols": []}
SCAN_CACHE = {}
NEWS_CACHE = {"ts": 0, "items": []}
CACHE_LOCK = threading.Lock()

STABLE_BASES = {"USDT", "USDC", "FDUSD", "TUSD", "USDE", "DAI", "USDP", "USDD", "USD"}
INTERVALS = {"5m", "15m", "1h", "4h", "1d"}


def now_utc():
    return datetime.now(timezone.utc)


def db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def init_db():
    if not DATABASE_URL:
        return
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    plan TEXT,
                    plan_start TIMESTAMPTZ,
                    plan_end TIMESTAMPTZ,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    plan TEXT NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    txid TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    settings JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
        conn.commit()


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 180000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def user_row(user_id=None, username=None):
    if not DATABASE_URL:
        return None
    with db_conn() as conn:
        with conn.cursor() as cur:
            if user_id is not None:
                cur.execute("SELECT id,username,password_hash,created_at,plan,plan_start,plan_end,is_active FROM users WHERE id=%s", (user_id,))
            else:
                cur.execute("SELECT id,username,password_hash,created_at,plan,plan_start,plan_end,is_active FROM users WHERE username=%s", (username,))
            return cur.fetchone()


def user_json(row):
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "created_at": row[3].isoformat() if row[3] else None,
        "plan": row[4], "plan_start": row[5].isoformat() if row[5] else None,
        "plan_end": row[6].isoformat() if row[6] else None, "is_active": bool(row[7]),
    }


def current_user():
    uid = session.get("user_id")
    return user_row(user_id=uid) if uid else None


def is_admin():
    return bool(session.get("admin"))


def admin_required():
    return is_admin()


def subscription_active(row=None):
    row = row or current_user()
    if not row or not row[7] or not row[6]:
        return False
    return row[6] > now_utc()


def json_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def safe_json_value(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v

# ------------------------- Generic HTTP -------------------------

def http_json(url, params=None, timeout=12):
    r = HTTP.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def http_text(url, timeout=15):
    r = HTTP.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

# ------------------------- Unified analysis -------------------------

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) <= period:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i][2]); l = float(candles[i][3]); pc = float(candles[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def macd_hist(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None
    line = []
    for i in range(slow - 1, len(values)):
        e_fast = ema(values[:i + 1], fast)
        e_slow = ema(values[:i + 1], slow)
        if e_fast is not None and e_slow is not None:
            line.append(e_fast - e_slow)
    if len(line) < signal:
        return None
    sig = ema(line, signal)
    return line[-1] - sig if sig is not None else None


def normalize_candles(candles):
    out = []
    for c in candles or []:
        try:
            if isinstance(c, dict):
                t = int(c["timestamp"])
                o, h, l, cl, v = map(float, (c["open"], c["high"], c["low"], c["close"], c["volume"]))
            else:
                t = int(float(c[0]))
                o, h, l, cl, v = map(float, c[1:6])
            out.append([t, o, h, l, cl, v])
        except Exception:
            continue
    return sorted(out, key=lambda x: x[0])


def analyze_klines(klines, symbol=None, market="crypto", interval="15m"):
    candles = normalize_candles(klines)
    if len(candles) < 60:
        raise ValueError("بيانات الشموع غير كافية للتحليل")
    closes = [x[4] for x in candles]
    price = closes[-1]
    e20 = ema(closes, 20); e50 = ema(closes, 50); e200 = ema(closes, 200)
    rv = rsi(closes, 14)
    ah = atr(candles, 14)
    mh = macd_hist(closes)
    score = 50
    if e20 is not None: score += 8 if price > e20 else -8
    if e50 is not None: score += 8 if price > e50 else -8
    if e200 is not None: score += 10 if price > e200 else -10
    if rv is not None:
        if 50 <= rv <= 70: score += 8
        elif rv > 70: score += 2
        elif rv < 30: score += 3
        else: score -= 5
    if mh is not None: score += 8 if mh > 0 else -8
    score = max(0, min(100, round(score, 2)))
    if score >= 80: signal = "شراء قوي"
    elif score >= 65: signal = "شراء"
    elif score <= 20: signal = "بيع قوي"
    elif score <= 35: signal = "بيع"
    else: signal = "حيادي"
    risk = max((ah or price * 0.01) * 1.5, price * 0.01)
    direction = "BUY" if score >= 50 else "SELL"
    if direction == "BUY":
        sl = price - risk; tp1 = price + risk * 1.5; tp2 = price + risk * 2; tp3 = price + risk * 3
    else:
        sl = price + risk; tp1 = price - risk * 1.5; tp2 = price - risk * 2; tp3 = price - risk * 3
    lows = [x[3] for x in candles[-20:]]; highs = [x[2] for x in candles[-20:]]
    return {
        "symbol": symbol, "market": market, "interval": interval, "signal": signal,
        "direction": direction, "score": score, "price": price,
        "entry": price, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "support": min(lows), "resistance": max(highs), "ema20": e20, "ema50": e50,
        "ema200": e200, "rsi": rv, "atr": ah, "macd_hist": mh,
        "updated_at": now_utc().isoformat(), "candles": candles[-100:],
    }

# ------------------------- Bybit Spot -------------------------

def bybit_get(path, params=None):
    data = http_json(BYBIT_BASE + path, params=params, timeout=15)
    if data.get("retCode") != 0:
        raise RuntimeError(data.get("retMsg") or "Bybit error")
    return data.get("result", {})


def bybit_symbols():
    with CACHE_LOCK:
        if MARKET_CACHE["symbols"] and time.time() - MARKET_CACHE["ts"] < 1800:
            return MARKET_CACHE["symbols"]
    rows = []
    cursor = None
    while True:
        params = {"category": "spot", "limit": 1000}
        if cursor: params["cursor"] = cursor
        result = bybit_get("/v5/market/instruments-info", params)
        for x in result.get("list", []):
            if x.get("status") != "Trading" or x.get("quoteCoin") != "USDT":
                continue
            base = x.get("baseCoin", "")
            if base in STABLE_BASES or x.get("symbol", "").endswith("USDT") is False:
                continue
            rows.append({"symbol": x["symbol"], "base": base, "quote": "USDT", "source": "Bybit Spot"})
        cursor = result.get("nextPageCursor")
        if not cursor: break
        if len(rows) > 5000: break
    with CACHE_LOCK:
        MARKET_CACHE.update(ts=time.time(), symbols=rows)
    return rows


def bybit_tickers():
    result = bybit_get("/v5/market/tickers", {"category": "spot"})
    return result.get("list", [])


def bybit_kline(symbol, interval="15m", limit=230):
    iv = {"5m":"5", "15m":"15", "1h":"60", "4h":"240", "1d":"D"}.get(interval)
    if not iv: raise ValueError("الفاصل غير مدعوم")
    rows = bybit_get("/v5/market/kline", {"category":"spot", "symbol":symbol.upper(), "interval":iv, "limit":min(int(limit), 1000)}).get("list", [])
    # Bybit: [start, open, high, low, close, volume, turnover]
    return normalize_candles([[r[0], r[1], r[2], r[3], r[4], r[5]] for r in reversed(rows)])


def bybit_price(symbol):
    rows = bybit_get("/v5/market/tickers", {"category":"spot", "symbol":symbol.upper()}).get("list", [])
    if not rows: raise ValueError("العملة غير موجودة")
    x = rows[0]
    return {"symbol": symbol.upper(), "price": float(x.get("lastPrice", 0)), "change24h": float(x.get("price24hPcnt", 0))*100, "volume24h": float(x.get("turnover24h", 0)), "source":"Bybit Spot"}

# ------------------------- Yahoo Finance -------------------------

def yahoo_symbol(s):
    return str(s).strip().upper().replace("/", "-").replace(".", "-")


def yahoo_chart(symbol, interval="15m", limit=230):
    ys = yahoo_symbol(symbol)
    if interval == "4h":
        # Yahoo intraday 4h ليس ثابتاً؛ نجلب 1h ثم نجمعه إلى 4h.
        raw = yahoo_chart(ys, "1h", min(limit * 4, 1000))
        return aggregate_candles(raw, 4 * 60 * 60 * 1000)[-limit:]
    yiv = {"5m":"5m", "15m":"15m", "1h":"60m", "1d":"1d"}.get(interval)
    if not yiv: raise ValueError("فاصل Yahoo غير مدعوم")
    rng = "10d" if interval in {"5m","15m"} else ("60d" if interval == "1h" else "2y")
    data = http_json(f"{YAHOO_BASE}/v8/finance/chart/{ys}", {
        "interval": yiv, "range": rng, "includePrePost": "false", "events": "div,splits"
    }, timeout=15)
    result = (data.get("chart") or {}).get("result")
    if not result: raise ValueError("Yahoo لم يرجع بيانات لهذا الرمز")
    r = result[0]; ts = r.get("timestamp") or []; q = r.get("indicators", {}).get("quote", [{}])[0]
    out = []
    for i, t in enumerate(ts):
        try:
            o=q["open"][i]; h=q["high"][i]; l=q["low"][i]; c=q["close"][i]; v=q.get("volume", [0]*len(ts))[i]
            if None in (o,h,l,c): continue
            out.append([int(t)*1000, float(o), float(h), float(l), float(c), float(v or 0)])
        except Exception: pass
    return normalize_candles(out)[-limit:]


def aggregate_candles(candles, bucket_ms):
    candles = normalize_candles(candles)
    if not candles: return []
    out=[]; cur=None
    for c in candles:
        bucket=(c[0]//bucket_ms)*bucket_ms
        if cur is None or cur[0]!=bucket:
            if cur: out.append(cur)
            cur=[bucket,c[1],c[2],c[3],c[4],c[5]]
        else:
            cur[2]=max(cur[2],c[2]); cur[3]=min(cur[3],c[3]); cur[4]=c[4]; cur[5]+=c[5]
    if cur: out.append(cur)
    return out


def us_universe(force=False):
    with CACHE_LOCK:
        if not force and US_CACHE["symbols"] and time.time()-US_CACHE["ts"] < 21600:
            return US_CACHE["symbols"]
    symbols={}
    # Nasdaq-listed file
    text=http_text(NASDAQ_LISTED)
    reader=csv.DictReader(io.StringIO(text), delimiter="|")
    for r in reader:
        s=(r.get("Symbol") or "").strip()
        if not s or s.startswith("File Creation") or r.get("Test Issue")=="Y": continue
        name=(r.get("Security Name") or "").upper()
        if any(k in name for k in ("WARRANT", "UNIT", "RIGHT", "PREFERRED", "DEBENTURE", "NOTE")): continue
        symbols[s]={"symbol":s,"name":r.get("Security Name",s),"exchange":"NASDAQ","source":"Yahoo Finance"}
    # NYSE / AMEX / ARCA وغيرها
    text=http_text(OTHER_LISTED)
    reader=csv.DictReader(io.StringIO(text), delimiter="|")
    for r in reader:
        s=(r.get("ACT Symbol") or "").strip()
        if not s or s.startswith("File Creation") or r.get("Test Issue")=="Y" or r.get("ETF")=="Y": continue
        name=(r.get("Security Name") or "").upper()
        if any(k in name for k in ("WARRANT", "UNIT", "RIGHT", "PREFERRED", "DEBENTURE", "NOTE", "FUND")): continue
        symbols.setdefault(s,{"symbol":s,"name":r.get("Security Name",s),"exchange":r.get("Exchange","US"),"source":"Yahoo Finance"})
    rows=sorted(symbols.values(), key=lambda x:x["symbol"])
    with CACHE_LOCK: US_CACHE.update(ts=time.time(), symbols=rows)
    return rows

# Saudi Exchange provides current market information and listed-symbol coverage.
# For historical candles, Yahoo's public chart feed is used with the Saudi .SR convention.
def saudi_universe(force=False):
    with CACHE_LOCK:
        if not force and SAUDI_CACHE["symbols"] and time.time()-SAUDI_CACHE["ts"] < 21600:
            return SAUDI_CACHE["symbols"]
    # Stable public fallback list of common Saudi symbols; the current exchange page is authoritative for market coverage.
    # Yahoo chart works with symbols such as 1120.SR.
    codes = [
        "1010","1020","1030","1050","1060","1080","1111","1120","1150","1180","1182","1183","1201","1202","1210","1211","1301","1302","1303","1304","1320","1321","1322","1810","1820","1830","1831","1832","1833","1834","1835","2001","2010","2020","2030","2040","2050","2060","2070","2080","2090","2100","2110","2120","2130","2140","2150","2160","2170","2180","2190","2200","2210","2220","2230","2240","2250","2270","2280","2281","2290","2300","2310","2320","2330","2340","2350","2360","2370","2380","2381","2382","3001","3002","3003","3004","3005","3007","3008","3009","3010","3020","3030","3040","3050","3060","3080","3090","3091","4001","4002","4003","4004","4005","4006","4007","4008","4009","4010","4011","4012","4013","4014","4015","4016","4017","4018","4019","4020","4021","4022","4023","4030","4031","4040","4050","4061","4070","4080","4081","4090","4100","4110","4130","4141","4142","4143","4144","4145","4147","4148","4149","4150","4160","4161","4162","4163","4164","4165","4166","4167","4168","4170","4180","4190","4191","4192","4193","4194","4200","4210","4220","4230","4240","4250","4260","4261","4262","4263","4264","4265","4270","4280","4290","4291","4292","4293","4294","4295","4296","4297","4298","4299","4300","4310","4320","4330","4331","4332","4333","4334","4335","4336","4337","4338","4339","4340","4342","4344","4345","4346","4347","4348","4349","4350","4360","4370","4380","4390","4400","4410","4420","4430","4440","4450","4460","4470","4480","4490","4500","4510","4520","4530","4540","4550","4560","4570","4580","4590","4600","4610","4620","4630","4640","4650","4660","4670","4680","4690","4700","4710","4720","4730","4740","4750","4760","4770","4780","4790","4800","4810","4820","4830","4840","4850","4860","4870","4880","4890","4900","4910","4920","4930","4940","4950","4960","4970","4980","4990","5000","5010","5020","5030","5040","5050","5060","5070","5080","5090","5100","5110","5120","5130","5140","5150","5160","5170","5180","5190","5200","5210","5220","5230","5240","5250","5260","5270","5280","5290","5300","5310","5320","5330","5340","5350","5360","5370","5380","5390","5400","5410","5420","5430","5440","5450","5460","5470","5480","5490","5500","5510","5520","5530","5540","5550","5560","5570","5580","5590","5600","5610","5620","5630","5640","5650","5660","5670","5670","5680","5690","5700","5710","5720","5730","5740","5750","5760","5770","5780","5790","5800","5810","5820","5830","5840","5850","5860","5870","5880","5890","5900","5910","5920","5930","5940","5950","5960","5970","5980","5990","6000","6010","6020","6030","6040","6050","6060","6070","6080","6090","6100","6110","6120","6130","6140","6150","6160","6170","6180","6190","6200","6210","6220","6230","6240","6250","6260","6270","6280","6290","6300","6310","6320","6330","6340","6350","6360","6370","6380","6390","6400","6410","6420","6430","6440","6450","6460","6470","6480","6490","6500","6510","6520","6530","6540","6550","6560","6570","6580","6590","6600","6610","6620","6630","6640","6650","6660","6670","6680","6690","6700","6710","6720","6730","6740","6750","6760","6770","6780","6790","6800","6810","6820","6830","6840","6850","6860","6870","6880","6890","6900","6910","6920","6930","6940","6950","6960","6970","6980","6990","7000","7010","7020","7030","7040","7050","7060","7070","7080","7090","7100","7110","7120","7130","7140","7150","7160","7170","7180","7190","7200","7210","7220","7230","7240","7250","7260","7270","7280","7290","7300","7310","7320","7330","7340","7350","7360","7370","7380","7390","7400","7410","7420","7430","7440","7450","7460","7470","7480","7490","7500","7510","7520","7530","7540","7550","7560","7570","7580","7590","7600","7610","7620","7630","7640","7650","7660","7670","7680","7690","7700","7710","7720","7730","7740","7750","7760","7770","7780","7790","7800","7810","7820","7830","7840","7850","7860","7870","7880","7890","7900","7910","7920","7930","7940","7950","7960","7970","7980","7990","8000","8010","8020","8030","8040","8050","8060","8070","8080","8090","8100","8110","8120","8130","8140","8150","8160","8170","8180","8190","8200","8210","8220","8230","8240","8250","8260","8270","8280","8290","8300","8310","8320","8330","8340","8350","8360","8370","8380","8390","8400","8410","8420","8430","8440","8450","8460","8470","8480","8490","8500","8510","8520","8530","8540","8550","8560","8570","8580","8590","8600","8610","8620","8630","8640","8650","8660","8670","8680","8690","8700","8710","8720","8730","8740","8750","8760","8770","8780","8790","8800","8810","8820","8830","8840","8850","8860","8870","8880","8890","8900","8910","8920","8930","8940","8950","8960","8970","8980","8990","9000","9010","9020","9030","9040","9050","9060","9070","9080","9090","9100","9110","9120","9130","9140","9150","9160","9170","9180","9190","9200","9210","9220","9230","9240","9250","9260","9270","9280","9290","9300","9310","9320","9330","9340","9350","9360","9370","9380","9390","9400","9410","9420","9430","9440","9450","9460","9470","9480","9490","9500","9510","9520","9530","9540","9550","9560","9570","9580","9590","9600","9610","9620","9630","9640","9650","9660","9670","9680","9690","9700","9710","9720","9730","9740","9750","9760","9770","9780","9790","9800","9810","9820","9830","9840","9850","9860","9870","9880","9890","9900","9910","9920","9930","9940","9950","9960","9970","9980","9990"
    ]
    rows=[]
    for code in dict.fromkeys(codes):
        rows.append({"symbol":code, "yahoo_symbol":code+".SR", "name":code, "exchange":"Saudi Exchange", "source":"Yahoo Finance / Saudi Exchange"})
    with CACHE_LOCK: SAUDI_CACHE.update(ts=time.time(), symbols=rows)
    return rows

# ------------------------- Scan helpers -------------------------

def scan_spot():
    key="crypto_scan"
    with CACHE_LOCK:
        cached=SCAN_CACHE.get(key)
        if cached and time.time()-cached["ts"] < 60: return cached["data"]
    tickers=bybit_tickers()
    candidates=[x for x in tickers if x.get("symbol"," ").endswith("USDT") and float(x.get("turnover24h") or 0)>=1000000]
    candidates=sorted(candidates,key=lambda x:float(x.get("turnover24h") or 0),reverse=True)[:120]
    def one(x):
        try: return analyze_klines(bybit_kline(x["symbol"],"15m",230),x["symbol"],"spot","15m")
        except Exception: return None
    results=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(one,x) for x in candidates]):
            r=f.result()
            if r: results.append(r)
    results.sort(key=lambda x:(x["score"],x["symbol"]),reverse=True)
    with CACHE_LOCK: SCAN_CACHE[key]={"ts":time.time(),"data":results}
    return results


def scan_us(limit=None):
    universe=us_universe()
    symbols=[x["symbol"] for x in universe]
    if limit: symbols=symbols[:int(limit)]
    results=[]
    def one(s):
        try: return analyze_klines(yahoo_chart(s,"15m",230),s,"us","15m")
        except Exception: return None
    # Full universe is available through /api/us/markets. Scanning thousands of Yahoo symbols in one request is intentionally capped.
    symbols=symbols[:int(os.getenv("US_SCAN_LIMIT","150"))]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(one,s) for s in symbols]):
            r=f.result()
            if r: results.append(r)
    results.sort(key=lambda x:x["score"],reverse=True)
    return {"universe_count":len(universe),"scanned":len(symbols),"results":results}

# ------------------------- Auth -------------------------

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"ok":True,"time":now_utc().isoformat(),"sources":{"crypto":"Bybit Spot","us":"Yahoo Finance","saudi":"Saudi Exchange/Yahoo Finance"}})

@app.post("/api/auth/register")
def register():
    data=request.get_json(silent=True) or request.form
    username=str(data.get("username","")).strip()
    password=str(data.get("password",""))
    if len(username)<3 or len(password)<6: return json_error("اسم المستخدم أو كلمة المرور غير صحيحة")
    if not DATABASE_URL: return json_error("قاعدة البيانات غير مهيأة",500)
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users(username,password_hash) VALUES(%s,%s) RETURNING id",(username,hash_password(password)))
                uid=cur.fetchone()[0]
            conn.commit()
        session.permanent=True; session["user_id"]=uid
        return jsonify({"ok":True,"user":user_json(user_row(user_id=uid))})
    except Exception as e:
        if "duplicate" in str(e).lower(): return json_error("اسم المستخدم موجود مسبقاً")
        return json_error("تعذر إنشاء الحساب",500)

@app.post("/api/auth/login")
def login():
    data=request.get_json(silent=True) or request.form
    username=str(data.get("username","")).strip(); password=str(data.get("password",""))
    row=user_row(username=username)
    if not row or not verify_password(password,row[2]): return json_error("بيانات الدخول غير صحيحة",401)
    session.permanent=True; session["user_id"]=row[0]
    return jsonify({"ok":True,"user":user_json(row)})

@app.post("/api/auth/logout")
def logout():
    session.pop("user_id",None); return jsonify({"ok":True})

@app.get("/api/auth/me")
def auth_me():
    row=current_user(); return jsonify({"ok":True,"user":user_json(row),"authenticated":bool(row),"subscription_active":subscription_active(row)})

# ------------------------- Admin -------------------------

@app.get("/admin")
def admin_page(): return render_template("index.html")

@app.post("/api/admin/login")
def admin_login():
    data=request.get_json(silent=True) or request.form
    if str(data.get("username",""))!=ADMIN_USERNAME or not hmac.compare_digest(str(data.get("password","")),ADMIN_PASSWORD): return json_error("بيانات المدير غير صحيحة",401)
    session.permanent=True; session["admin"]=True
    return jsonify({"ok":True,"admin":True})

@app.get("/api/admin/me")
def admin_me(): return jsonify({"ok":True,"admin":is_admin()})

@app.post("/api/admin/logout")
def admin_logout(): session.pop("admin",None); return jsonify({"ok":True})

@app.get("/api/admin/stats")
def admin_stats():
    if not admin_required(): return json_error("غير مصرح",403)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users"); users=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM payments WHERE status='pending'"); pending=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM payments WHERE status='approved'"); approved=cur.fetchone()[0]
    return jsonify({"ok":True,"users":users,"pending_payments":pending,"approved_payments":approved})

@app.get("/api/admin/users")
def admin_users():
    if not admin_required(): return json_error("غير مصرح",403)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,created_at,plan,plan_start,plan_end,is_active FROM users ORDER BY id DESC")
            rows=cur.fetchall()
    return jsonify({"ok":True,"users":[{"id":r[0],"username":r[1],"created_at":safe_json_value(r[2]),"plan":r[3],"plan_start":safe_json_value(r[4]),"plan_end":safe_json_value(r[5]),"is_active":r[6]} for r in rows]})

@app.post("/api/admin/users/<int:user_id>/plan")
def admin_user_plan(user_id):
    if not admin_required(): return json_error("غير مصرح",403)
    data=request.get_json(silent=True) or {}
    plan=str(data.get("plan","")); days=PLANS.get(plan,{}).get("days")
    if not days: return json_error("الخطة غير صحيحة")
    start=now_utc(); end=start+timedelta(days=days)
    with db_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE users SET plan=%s,plan_start=%s,plan_end=%s WHERE id=%s",(plan,start,end,user_id))
        conn.commit()
    return jsonify({"ok":True})

@app.get("/api/admin/payments")
def admin_payments():
    if not admin_required(): return json_error("غير مصرح",403)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT p.id,p.user_id,u.username,p.plan,p.amount,p.txid,p.status,p.created_at,p.reviewed_at FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC")
            rows=cur.fetchall()
    return jsonify({"ok":True,"payments":[{"id":r[0],"user_id":r[1],"username":r[2],"plan":r[3],"amount":float(r[4]),"txid":r[5],"status":r[6],"created_at":safe_json_value(r[7]),"reviewed_at":safe_json_value(r[8])} for r in rows]})

@app.post("/api/admin/payments/<int:payment_id>/review")
def admin_payment_review(payment_id):
    if not admin_required(): return json_error("غير مصرح",403)
    data=request.get_json(silent=True) or {}; status=str(data.get("status",""))
    if status not in {"approved","rejected"}: return json_error("الحالة غير صحيحة")
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id,plan FROM payments WHERE id=%s",(payment_id,)); p=cur.fetchone()
            if not p: return json_error("الدفعة غير موجودة",404)
            cur.execute("UPDATE payments SET status=%s,reviewed_at=NOW() WHERE id=%s",(status,payment_id))
            if status=="approved":
                days=PLANS[p[1]]["days"]; start=now_utc(); end=start+timedelta(days=days)
                cur.execute("UPDATE users SET plan=%s,plan_start=%s,plan_end=%s WHERE id=%s",(p[1],start,end,p[0]))
        conn.commit()
    return jsonify({"ok":True})

# ------------------------- Subscription / settings -------------------------

@app.get("/api/subscription/plans")
def subscription_plans(): return jsonify({"ok":True,"plans":PLANS,"payment_address":PAYMENT_ADDRESS})

@app.post("/api/subscription/request")
def subscription_request():
    row=current_user()
    if not row: return json_error("سجل الدخول أولاً",401)
    data=request.get_json(silent=True) or {}; plan=str(data.get("plan","")); txid=str(data.get("txid","")).strip()
    if plan not in PLANS: return json_error("الخطة غير صحيحة")
    with db_conn() as conn:
        with conn.cursor() as cur: cur.execute("INSERT INTO payments(user_id,plan,amount,txid) VALUES(%s,%s,%s,%s) RETURNING id",(row[0],plan,PLANS[plan]["amount"],txid))
        pid=cur.fetchone()[0]
        conn.commit()
    return jsonify({"ok":True,"payment_id":pid})

@app.get("/api/subscription/my")
def subscription_my():
    row=current_user(); return jsonify({"ok":True,"user":user_json(row),"active":subscription_active(row),"plans":PLANS,"payment_address":PAYMENT_ADDRESS})

@app.get("/api/settings")
def get_settings():
    row=current_user()
    if not row: return json_error("سجل الدخول أولاً",401)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT settings FROM user_settings WHERE user_id=%s",(row[0],)); r=cur.fetchone()
    return jsonify({"ok":True,"settings":r[0] if r else {}})

@app.post("/api/settings")
def save_settings():
    row=current_user()
    if not row: return json_error("سجل الدخول أولاً",401)
    settings=request.get_json(silent=True) or {}
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_settings(user_id,settings) VALUES(%s,%s) ON CONFLICT(user_id) DO UPDATE SET settings=EXCLUDED.settings",(row[0],json.dumps(settings)))
        conn.commit()
    return jsonify({"ok":True,"settings":settings})

# ------------------------- Crypto routes: old /api/binance names preserved -------------------------

@app.get("/api/binance/test")
def crypto_test():
    try:
        bybit_get("/v5/market/time")
        return jsonify({"ok":True,"connected":True,"source":"Bybit Spot"})
    except Exception as e: return jsonify({"ok":False,"connected":False,"source":"Bybit Spot","error":str(e)}),502

@app.get("/api/binance/markets")
def crypto_markets():
    try: return jsonify({"ok":True,"source":"Bybit Spot","markets":bybit_symbols()})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/binance/prices")
def crypto_prices():
    try:
        rows=bybit_tickers()
        rows=[x for x in rows if x.get("symbol"," ").endswith("USDT")]
        return jsonify({"ok":True,"source":"Bybit Spot","prices":rows})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/binance/price")
def crypto_price():
    try: return jsonify({"ok":True,"data":bybit_price(request.args.get("symbol","BTCUSDT"))})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/binance/klines")
def crypto_klines():
    try:
        symbol=request.args.get("symbol","BTCUSDT"); interval=request.args.get("interval","15m")
        return jsonify({"ok":True,"source":"Bybit Spot","symbol":symbol,"interval":interval,"klines":bybit_kline(symbol,interval,int(request.args.get("limit",230)))})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/binance/analysis")
def crypto_analysis():
    try:
        symbol=request.args.get("symbol","BTCUSDT"); interval=request.args.get("interval","15m")
        return jsonify({"ok":True,"analysis":analyze_klines(bybit_kline(symbol,interval,230),symbol,"spot",interval)})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/binance/scan")
def crypto_scan():
    try: return jsonify({"ok":True,"source":"Bybit Spot","results":scan_spot()})
    except Exception as e: return json_error(str(e),502)

# ------------------------- Alpha + Futures = exactly same Spot data -------------------------

def spot_alias_analysis(kind):
    symbol=request.args.get("symbol","BTCUSDT"); interval=request.args.get("interval","15m")
    a=analyze_klines(bybit_kline(symbol,interval,230),symbol,"spot",interval)
    a["section"]=kind; a["data_source"]= "Bybit Spot"
    return jsonify({"ok":True,"analysis":a})

@app.get("/api/alpha/analysis")
def alpha_analysis():
    try: return spot_alias_analysis("alpha")
    except Exception as e: return json_error(str(e),502)

@app.get("/api/futures/analysis")
def futures_analysis():
    try: return spot_alias_analysis("futures")
    except Exception as e: return json_error(str(e),502)

@app.get("/api/alpha/scan")
def alpha_scan():
    try: return jsonify({"ok":True,"section":"alpha","source":"Bybit Spot","results":scan_spot()})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/futures/scan")
def futures_scan():
    try: return jsonify({"ok":True,"section":"futures","source":"Bybit Spot","results":scan_spot()})
    except Exception as e: return json_error(str(e),502)

# ------------------------- US market: Yahoo Finance -------------------------

@app.get("/api/us/markets")
def us_markets():
    try:
        rows=us_universe()
        return jsonify({"ok":True,"source":"Yahoo Finance","count":len(rows),"markets":rows})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/us/price")
def us_price():
    try:
        s=request.args.get("symbol","AAPL"); c=yahoo_chart(s,"1d",5)
        if not c: raise ValueError("لا توجد بيانات")
        last=c[-1]; prev=c[-2] if len(c)>1 else last
        return jsonify({"ok":True,"source":"Yahoo Finance","symbol":s.upper(),"price":last[4],"change24h":((last[4]/prev[4])-1)*100 if prev[4] else 0})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/us/klines")
def us_klines():
    try:
        s=request.args.get("symbol","AAPL"); iv=request.args.get("interval","15m")
        return jsonify({"ok":True,"source":"Yahoo Finance","symbol":s.upper(),"interval":iv,"klines":yahoo_chart(s,iv,int(request.args.get("limit",230)))})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/us/analysis")
def us_analysis():
    try:
        s=request.args.get("symbol","AAPL"); iv=request.args.get("interval","15m")
        return jsonify({"ok":True,"analysis":analyze_klines(yahoo_chart(s,iv,230),s,"us",iv)})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/us/scan")
def us_scan_route():
    try: return jsonify({"ok":True,"source":"Yahoo Finance","data":scan_us(request.args.get("limit"))})
    except Exception as e: return json_error(str(e),502)

# ------------------------- Saudi -------------------------

@app.get("/api/saudi/markets")
def saudi_markets():
    try:
        rows=saudi_universe(); return jsonify({"ok":True,"source":"Saudi Exchange / Yahoo Finance","count":len(rows),"markets":rows})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/saudi/klines")
def saudi_klines():
    try:
        s=request.args.get("symbol","1120"); iv=request.args.get("interval","15m")
        ys=s if "." in s else s+".SR"
        return jsonify({"ok":True,"source":"Yahoo Finance","symbol":s,"interval":iv,"klines":yahoo_chart(ys,iv,int(request.args.get("limit",230)))})
    except Exception as e: return json_error(str(e),502)

@app.get("/api/saudi/analysis")
def saudi_analysis():
    try:
        s=request.args.get("symbol","1120"); iv=request.args.get("interval","15m"); ys=s if "." in s else s+".SR"
        return jsonify({"ok":True,"analysis":analyze_klines(yahoo_chart(ys,iv,230),s,"saudi",iv)})
    except Exception as e: return json_error(str(e),502)

# ------------------------- News -------------------------

@app.get("/api/news")
def news():
    with CACHE_LOCK:
        if NEWS_CACHE["items"] and time.time()-NEWS_CACHE["ts"]<600:
            return jsonify({"ok":True,"items":NEWS_CACHE["items"]})
    feeds=["https://www.coindesk.com/arc/outboundfeeds/rss/"]
    items=[]
    for url in feeds:
        try:
            root=ET.fromstring(http_text(url,10))
            for item in root.findall(".//item")[:30]:
                title=item.findtext("title") or ""; link=item.findtext("link") or ""; pub=item.findtext("pubDate") or ""
                items.append({"title":html.unescape(title),"link":link,"published":pub})
        except Exception: pass
    with CACHE_LOCK: NEWS_CACHE.update(ts=time.time(),items=items[:30])
    return jsonify({"ok":True,"items":items[:30]})

# Initialize database when the module loads. Render/Gunicorn imports this file.
try:
    init_db()
except Exception as e:
    print("DB init warning:", e)

if __name__ == "__main__":
    port=int(os.getenv("PORT","10000"))
    app.run(host="0.0.0.0",port=port,debug=False)
