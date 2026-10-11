"""AZO experimental multi-method analysis and evidence-gated public release."""
import json, os, sqlite3, time
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

router = APIRouter()
DB = "/data/trading.db" if os.path.isdir("/data") else "trading.db"
PIN_ENV = "AZO_ADMIN_PIN"
RETENTION = 86400
MIN_CLOSED = 30
MIN_WIN_RATE = 55.0
MIN_PROFIT_FACTOR = 1.20
MARKETS = {
    "spot": "سبوت", "futures": "فيوتشر", "contracts": "العقود الأمريكية",
    "us": "الأسهم الأمريكية", "saudi": "السوق السعودي", "forex": "الفوركس والذهب",
    "alpha": "Binance Alpha"
}

def _db():
    c = sqlite3.connect(DB, timeout=12)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=12000")
    c.execute("""CREATE TABLE IF NOT EXISTS azo_signals(
      id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL, symbol TEXT NOT NULL,
      direction TEXT NOT NULL, timeframe TEXT NOT NULL, entry REAL NOT NULL,
      tp1 REAL, tp2 REAL, tp3 REAL, sl REAL NOT NULL, score REAL NOT NULL,
      method_votes TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, updated REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'OPEN', hit_target INTEGER DEFAULT 0,
      result_r REAL, result_price REAL, UNIQUE(market,symbol,direction,timeframe,entry,created))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_azo_created_status ON azo_signals(created,status)")
    c.commit()
    return c

def _closed_stats(c):
    cutoff = time.time() - RETENTION
    rows = c.execute("SELECT status,result_r FROM azo_signals WHERE created>=? AND status IN ('WIN','LOSS')", (cutoff,)).fetchall()
    wins = sum(1 for r in rows if r["status"] == "WIN")
    losses = sum(1 for r in rows if r["status"] == "LOSS")
    gross_win = sum(max(0.0, float(r["result_r"] or 0)) for r in rows if r["status"] == "WIN")
    gross_loss = sum(abs(min(0.0, float(r["result_r"] or 0))) for r in rows if r["status"] == "LOSS")
    rate = wins * 100.0 / len(rows) if rows else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    unlocked = len(rows) >= MIN_CLOSED and rate >= MIN_WIN_RATE and pf >= MIN_PROFIT_FACTOR
    return {"closed":len(rows),"wins":wins,"losses":losses,"win_rate":round(rate,1),
            "profit_factor":round(pf,2),"gross_win_r":round(gross_win,2),"gross_loss_r":round(gross_loss,2),
            "unlocked":unlocked,"minimum_closed":MIN_CLOSED,"required_win_rate":MIN_WIN_RATE,
            "required_profit_factor":MIN_PROFIT_FACTOR}

def _is_lab(request):
    return bool(request.session.get("azo_lab_unlocked"))

def _score(row):
    votes = row.get("methods") or row.get("method_votes") or {}
    if isinstance(votes, str):
        try: votes = json.loads(votes)
        except Exception: votes = {}
    vals = []
    positive = negative = 0
    for value in (votes.values() if isinstance(votes, dict) else []):
        try: v = max(-1.0, min(1.0, float(value)))
        except Exception: continue
        if abs(v) < 0.15: continue
        vals.append(v)
        if v > 0: positive += 1
        else: negative += 1
    direction = str(row.get("direction") or row.get("side") or "").upper()
    aligned = [v for v in vals if (direction == "BUY" and v > 0) or (direction == "SELL" and v < 0)]
    opposed = [v for v in vals if (direction == "BUY" and v < 0) or (direction == "SELL" and v > 0)]
    base = row.get("recommendation_score", row.get("ai_pct", row.get("base_score", 0))) or 0
    try: base = max(0.0, min(100.0, float(base)))
    except Exception: base = 0.0
    agreement = (len(aligned) / max(1, len(aligned) + len(opposed))) * 100.0 if vals else 0.0
    score = min(100.0, max(0.0, base * 0.35 + agreement * 0.50 + min(len(aligned), 5) * 3.0 - min(len(opposed), 5) * 4.0))
    return round(score, 1), len(aligned), len(opposed), votes if isinstance(votes, dict) else {}

def _quote(core, market, symbol):
    raw = str(symbol or "").replace("/USDT", "USDT").replace("/", "")
    try:
        if market == "spot":
            q = core._binance_json("https://api.binance.com/api/v3/ticker/price?symbol="+raw, timeout=3, timeframe="15m", spot_fallback=True)
            return float(q.get("price") or 0)
        if market == "futures":
            q = core._binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/price?symbol="+raw, timeout=3)
            return float(q.get("price") or 0)
        candles = core._yahoo_chart(symbol, "15m", "5d", "15m")
        return float(candles[-1][0]) if candles else 0
    except Exception:
        return 0.0

def _refresh_outcomes(c, core, cutoff):
    rows = c.execute("SELECT * FROM azo_signals WHERE created>=? AND status='OPEN' ORDER BY created DESC LIMIT 250", (cutoff,)).fetchall()
    updated = 0
    for row in rows:
        price = _quote(core, row["market"], row["symbol"])
        if price <= 0: continue
        entry, sl = float(row["entry"]), float(row["sl"])
        side = row["direction"]
        hit = 0
        status = "OPEN"
        if (side == "BUY" and price <= sl) or (side == "SELL" and price >= sl):
            status = "LOSS"
            result_r = -1.0
        else:
            targets = [row["tp1"], row["tp2"], row["tp3"]]
            for i, target in enumerate(targets, 1):
                if target is None: continue
                if (side == "BUY" and price >= float(target)) or (side == "SELL" and price <= float(target)):
                    hit = i
            if hit:
                target = float(targets[hit-1])
                risk = abs(entry-sl)
                status = "WIN"
                result_r = abs(target-entry)/risk if risk else 0.0
            elif time.time()-float(row["created"]) >= RETENTION:
                status = "EXPIRED"
                result_r = 0.0
            else:
                result_r = None
        if status != "OPEN":
            c.execute("UPDATE azo_signals SET status=?,hit_target=?,result_r=?,result_price=?,updated=? WHERE id=?",
                      (status,hit,result_r,price,time.time(),row["id"]))
            updated += 1
    c.execute("DELETE FROM azo_signals WHERE created<?", (cutoff,))
    c.commit()
    return updated

def _leaderboard(c):
    cutoff = time.time() - RETENTION
    # Every market competes on completed outcomes, not on signal volume or confidence claims.
    rows = c.execute("""SELECT market,
      SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) wins,
      SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) losses,
      SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) opened
      FROM recommendation_results WHERE created>=? GROUP BY market""", (cutoff,)).fetchall()
    raw = {str(r["market"]):r for r in rows}
    out = []
    for key, label in MARKETS.items():
        r = raw.get(key)
        wins = int(r["wins"] or 0) if r else 0
        losses = int(r["losses"] or 0) if r else 0
        opened = int(r["opened"] or 0) if r else 0
        closed = wins + losses
        rate = wins * 100.0 / closed if closed else 0.0
        # Shrink small samples toward 50%, and require evidence before a section can lead.
        score = ((wins + 5.0) / (closed + 10.0) * 100.0) if closed else 0.0
        out.append({"key":key,"name":label,"wins":wins,"losses":losses,"open":opened,
                    "closed":closed,"win_rate":round(rate,1),"score":round(score,1),
                    "eligible":closed>=8})
    out.sort(key=lambda x:(x["eligible"], x["score"], x["closed"]), reverse=True)
    for i, item in enumerate(out, 1):
        item["rank"] = i
        item["rank_label"] = "المركز الأول" if i == 1 and item["eligible"] else ("بانتظار عينة كافية" if not item["eligible"] else "منافس")
    return out

@router.get("/api/azo/status")
def azo_status(request: Request):
    c = _db()
    try:
        stats = _closed_stats(c)
        board = _leaderboard(c)
        latest = c.execute("SELECT MAX(updated) FROM azo_signals").fetchone()[0]
        return {"ok":True,"name":"AZO","public":stats["unlocked"],"lab_unlocked":_is_lab(request),
                "state":"public" if stats["unlocked"] else "learning",
                "message":"تحليل AZO اجتاز شروط النشر التجريبية" if stats["unlocked"] else "قسم AZO مقفل للجمهور حتى يثبت نتائج كافية بعد الأهداف والوقف",
                "stats":stats,"leaderboard":board,"updated":latest}
    finally:
        c.close()

@router.post("/api/azo/lab/unlock")
def azo_lab_unlock(request: Request, pin: str = Form(...)):
    expected = os.getenv(PIN_ENV, "").strip()
    if not expected:
        return JSONResponse({"ok":False,"message":"اضبط AZO_ADMIN_PIN في متغيرات بيئة الاستضافة أولاً."}, status_code=503)
    if not __import__("hmac").compare_digest(str(pin).strip(), expected):
        return JSONResponse({"ok":False,"message":"الرقم السري غير صحيح."}, status_code=403)
    request.session["azo_lab_unlocked"] = True
    return {"ok":True,"message":"تم فتح مختبر AZO الخاص على هذا المتصفح."}

@router.post("/api/azo/lab/lock")
def azo_lab_lock(request: Request):
    request.session.pop("azo_lab_unlocked", None)
    return {"ok":True}

@router.get("/api/azo/scan")
def azo_scan(request: Request, market: str = "spot", timeframe: str = "15m"):
    c = _db()
    try:
        stats = _closed_stats(c)
        lab = _is_lab(request)
        if not stats["unlocked"] and not lab:
            return {"ok":True,"locked":True,"public":False,"message":"تحليل AZO ما زال تحت الاختبار الخاص.","opportunities":[]}
        import app as core
        cutoff = time.time() - RETENTION
        try:
            _refresh_outcomes(c, core, cutoff)
        except Exception as exc:
            print("[AZO] outcome refresh:",str(exc)[:120],flush=True)
        try:
            rows = core.opportunities(market, timeframe)
        except TypeError:
            try: rows = core.opportunities(market)
            except Exception: rows = []
        except Exception:
            rows = []
        results = []
        for row in rows or []:
            if not isinstance(row, dict): continue
            side = str(row.get("direction") or row.get("side") or "").upper()
            entry = row.get("entry")
            sl = row.get("sl") or row.get("stop_loss")
            tps = [row.get("tp1"),row.get("tp2"),row.get("tp3")]
            try:
                entry, sl = float(entry), float(sl)
                if side not in ("BUY","SELL") or entry <= 0 or sl <= 0 or abs(entry-sl) <= 0: continue
            except Exception: continue
            score, aligned, opposed, votes = _score(row)
            if aligned < 2 or opposed > aligned or score < 50: continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol: continue
            try:
                c.execute("""INSERT OR IGNORE INTO azo_signals(market,symbol,direction,timeframe,entry,tp1,tp2,tp3,sl,score,method_votes,created,updated)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (market,symbol,side,timeframe,entry,*[float(x) if x not in (None,"") else None for x in tps],sl,score,
                   json.dumps(votes,ensure_ascii=False,separators=(",",":")),time.time(),time.time()))
            except Exception:
                pass
            results.append({"market":market,"symbol":symbol,"direction":side,"timeframe":timeframe,"entry":entry,
                "tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"azo_score":score,
                "aligned_methods":aligned,"opposed_methods":opposed,"created":row.get("detected_at") or time.time()})
        c.commit()
        # Refresh the gate after new signals/outcomes have been processed.
        stats = _closed_stats(c)
        published = stats["unlocked"]
        if not published and not lab:
            results = []
        results.sort(key=lambda x:(x["azo_score"],x["aligned_methods"],-x["opposed_methods"]),reverse=True)
        return {"ok":True,"locked":not published and not lab,"public":published,"state":"public" if published else "learning",
                "stats":stats,"opportunities":results[:60],"message":"فرص AZO التجريبية؛ لا تُعد نتائجها مثبتة قبل اجتياز شروط النشر."}
    finally:
        c.close()

@router.get("/api/azo/leaderboard")
def azo_leaderboard():
    c = _db()
    try: return {"ok":True,"leaderboard":_leaderboard(c),"window_hours":24}
    finally: c.close()
