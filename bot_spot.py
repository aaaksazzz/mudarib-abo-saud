import time, threading, urllib.parse, urllib.request, json, hmac
from hashlib import sha256
from decimal import Decimal, ROUND_DOWN
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from cryptography.fernet import Fernet
import os, base64, hashlib
import app_v2 as core
from telegram_notify import send_telegram

USER_BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_bot_settings(
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    initial_capital REAL DEFAULT 100.0,
    balance REAL DEFAULT 100.0,
    target_pct REAL DEFAULT 0.5,
    api_key_enc TEXT DEFAULT '',
    api_secret_enc TEXT DEFAULT '',
    live_enabled INTEGER DEFAULT 0,
    last_scan TEXT DEFAULT '',
    last_signal TEXT DEFAULT '',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS user_bot_trades(
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    signal_id INTEGER,
    symbol TEXT,
    timeframe TEXT DEFAULT '15m',
    entry REAL,
    stop REAL,
    tp1 REAL,
    tp2 REAL,
    tp3 REAL,
    capital REAL,
    qty REAL,
    exit_price REAL,
    pnl_pct REAL,
    pnl_amount REAL,
    status TEXT DEFAULT 'open',
    opened_at TEXT,
    closed_at TEXT,
    peak REAL,
    protect_price REAL,
    exchange_order_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_bot_trades_user_status ON user_bot_trades(user_id,status);
"""

def bdb():
    c=core.db()
    c.executescript(USER_BOT_SCHEMA)
    c.commit()
    return c

def _fernet():
    raw=os.getenv("BOT_ENCRYPTION_KEY","").strip()
    if not raw:
        raw=base64.urlsafe_b64encode(hashlib.sha256((os.getenv("SECRET_KEY") or "mudarib-bot-key").encode()).digest()).decode()
    return Fernet(raw.encode())

def _enc(v):
    return _fernet().encrypt(v.encode()).decode() if v else ""

def _dec(v):
    try:
        return _fernet().decrypt(v.encode()).decode() if v else ""
    except Exception:
        return ""

def _signed(method,path,params,key,secret):
    p=dict(params or {})
    p["timestamp"]=int(time.time()*1000)
    p["recvWindow"]=5000
    q=urllib.parse.urlencode(p)
    sig=hmac.new(secret.encode(),q.encode(),sha256).hexdigest()
    req=urllib.request.Request(
        "https://api.binance.com"+path+"?"+q+"&signature="+sig,
        method=method,
        headers={"X-MBX-APIKEY":key}
    )
    with urllib.request.urlopen(req,timeout=10) as r:
        return json.loads(r.read().decode())

def _price(symbol):
    with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/price?symbol="+urllib.parse.quote(symbol),timeout=8) as r:
        return float(json.loads(r.read().decode())["price"])

def _rules(symbol,key,secret):
    x=_signed("GET","/api/v3/exchangeInfo",{"symbol":symbol},key,secret)["symbols"][0]["filters"]
    d={}
    for f in x:
        if f["filterType"]=="LOT_SIZE":
            d["step"]=float(f["stepSize"])
            d["min"]=float(f["minQty"])
    return d

def _floor(v,step):
    return float((Decimal(str(v))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step))) if step else v

def _avg(order):
    fills=order.get("fills") or []
    q=sum(float(f["qty"]) for f in fills)
    cost=sum(float(f["qty"])*float(f["price"]) for f in fills)
    return (cost/q if q else 0),q

def _ensure_user(c,user_id):
    s=c.execute("SELECT * FROM user_bot_settings WHERE user_id=?",(user_id,)).fetchone()
    if not s:
        c.execute(
            "INSERT INTO user_bot_settings(user_id,enabled,initial_capital,balance,target_pct,api_key_enc,api_secret_enc,live_enabled,last_scan,last_signal,updated_at) VALUES(?,0,100,100,0.5,'','',0,'','',?)",
            (user_id,core.now())
        )
        c.commit()
        s=c.execute("SELECT * FROM user_bot_settings WHERE user_id=?",(user_id,)).fetchone()
    return s

def _pick_signal(c):
    return c.execute(
        "SELECT * FROM signals WHERE market='spot' AND side='BUY' AND timeframe='15m' AND status='open' ORDER BY confidence DESC,change15 DESC,id DESC LIMIT 1"
    ).fetchone()

def _binance_connection(s):
    return bool(s and s["api_key_enc"] and s["api_secret_enc"])

def _live_balance(key,secret):
    x=_signed("GET","/api/v3/account",{},key,secret)
    for b in x.get("balances",[]):
        if b.get("asset")=="USDT":
            return float(b.get("free") or 0)
    return 0.0

def user_bot_step(user_id):
    c=bdb()
    s=_ensure_user(c,user_id)
    if not s["enabled"]:
        return
    key=_dec(s["api_key_enc"])
    secret=_dec(s["api_secret_enc"])
    live=bool(s["live_enabled"] and key and secret)
    t=c.execute("SELECT * FROM user_bot_trades WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
    try:
        if t:
            price=_price(t["symbol"]) if live else float(core.market_candles("spot",t["symbol"],"15m")[-1][4])
            entry=float(t["entry"])
            step=float(s["target_pct"] or 0.5)
            peak=max(float(t["peak"] or entry),price)
            levels=int(max(0,(peak/entry-1)*100)/step)
            protect=entry*(1+max(0,levels-1)*step/100)
            old_protect=float(t["protect_price"] or entry)
            c.execute("UPDATE user_bot_trades SET peak=?,protect_price=? WHERE id=?",(peak,protect,t["id"]))
            c.execute("UPDATE user_bot_settings SET last_scan=?,updated_at=? WHERE user_id=?",(core.now(),core.now(),user_id))
            c.commit()
            if protect>old_protect:
                send_telegram(f"حماية بوت مستخدم\\n{t['symbol']} | شراء\\nالحماية: {protect:.8g}\\nالصعود: {((protect/entry)-1)*100:+.2f}%")
            if levels>=1 and price<=protect:
                exit_price=price
                if live:
                    rules=_rules(t["symbol"],key,secret)
                    qty=_floor(float(t["qty"]),rules.get("step"))
                    if qty<=0 or qty<rules.get("min",0):
                        return
                    order=_signed("POST","/api/v3/order",{"symbol":t["symbol"],"side":"SELL","type":"MARKET","quantity":f"{qty:.12f}".rstrip("0").rstrip(".")},key,secret)
                    exit_price,sold=_avg(order)
                pnl=(exit_price-entry)/entry*100
                amount=float(t["capital"])*pnl/100
                new_balance=float(s["balance"])+amount
                c.execute(
                    "UPDATE user_bot_trades SET status='closed',exit_price=?,pnl_pct=?,pnl_amount=?,closed_at=?,peak=?,protect_price=? WHERE id=?",
                    (exit_price,pnl,amount,core.now(),peak,protect,t["id"])
                )
                c.execute("UPDATE user_bot_settings SET balance=?,last_scan=?,updated_at=? WHERE user_id=?",(new_balance,core.now(),core.now(),user_id))
                c.commit()
                send_telegram(f"خروج بوت المستخدم\\n{t['symbol']} | شراء\\nالدخول: {entry:.8g}\\nالخروج: {exit_price:.8g}\\nالنتيجة: {pnl:+.2f}%\\nالربح: {amount:+.2f} USDT")
            return
        sig=_pick_signal(c)
        if not sig:
            c.execute("UPDATE user_bot_settings SET last_scan=?,last_signal=?,updated_at=? WHERE user_id=?",(core.now(),"لا توجد إشارة شراء 15m",core.now(),user_id))
            c.commit()
            return
        c.execute("UPDATE user_bot_settings SET last_scan=?,last_signal=?,updated_at=? WHERE user_id=?",(core.now(),sig["symbol"],core.now(),user_id))
        c.commit()
        balance=float(s["balance"])
        if live:
            balance=_live_balance(key,secret)
        if balance<=0:
            return
        capital=balance
        entry=float(sig["entry"])
        qty=capital/entry
        oid=""
        if live:
            order=_signed("POST","/api/v3/order",{"symbol":sig["symbol"],"side":"BUY","type":"MARKET","quoteOrderQty":f"{capital:.2f}"},key,secret)
            entry,qty=_avg(order)
            oid=str(order.get("orderId",""))
        c.execute(
            "INSERT INTO user_bot_trades(user_id,signal_id,symbol,timeframe,entry,stop,tp1,tp2,tp3,capital,qty,status,opened_at,peak,protect_price,exchange_order_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id,sig["id"],sig["symbol"],sig["timeframe"],entry,None,sig["tp1"],sig["tp2"],sig["tp3"],capital,qty,"open",core.now(),entry,entry,oid)
        )
        c.commit()
        send_telegram(f"دخول بوت المستخدم\\n{sig['symbol']} | شراء | 15m\\nالدخول: {entry:.8g}\\nرأس المال: {capital:.2f} USDT")
    except Exception:
        c.rollback()

def bot_loop():
    while True:
        try:
            c=bdb()
            users=c.execute("SELECT user_id FROM user_bot_settings WHERE enabled=1").fetchall()
            for row in users:
                user_bot_step(row["user_id"])
        except Exception:
            pass
        time.sleep(15)

def _page(req,title,body):
    return core.page(req,title,body)

def bot_page(req:Request):
    u=core.user(req)
    if not u:
        return RedirectResponse("/login",303)
    c=bdb()
    s=_ensure_user(c,u["id"])
    trades=c.execute("SELECT * FROM user_bot_trades WHERE user_id=? AND status='closed' ORDER BY id DESC LIMIT 20",(u["id"],)).fetchall()
    open_trade=c.execute("SELECT * FROM user_bot_trades WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
    total=c.execute("SELECT COUNT(*) n FROM user_bot_trades WHERE user_id=? AND status='closed'",(u["id"],)).fetchone()["n"]
    wins=c.execute("SELECT COUNT(*) n FROM user_bot_trades WHERE user_id=? AND status='closed' AND pnl_pct>0",(u["id"],)).fetchone()["n"]
    pnl=c.execute("SELECT COALESCE(SUM(pnl_pct),0) p,COALESCE(SUM(pnl_amount),0) a FROM user_bot_trades WHERE user_id=? AND status='closed'",(u["id"],)).fetchone()
    winrate=wins/total*100 if total else 0
    connected=_binance_connection(s)
    mode="حقيقي" if s["live_enabled"] else "تجريبي"
    status="يعمل" if s["enabled"] else "متوقف"
    status_cls="buy" if s["enabled"] else "danger"
    conn_cls="buy" if connected else "danger"
    current='<div class="card muted">لا توجد صفقة مفتوحة حالياً.</div>'
    if open_trade:
        cur_price=float(open_trade["entry"])
        unreal=0.0
        try:
            key=_dec(s["api_key_enc"])
            secret=_dec(s["api_secret_enc"])
            if s["live_enabled"] and key and secret:
                cur_price=_price(open_trade["symbol"])
            else:
                candles=core.market_candles("spot",open_trade["symbol"],"15m") or []
                if candles:
                    cur_price=float(candles[-1][4])
            unreal=(cur_price/float(open_trade["entry"])-1)*100
        except Exception:
            pass
        ucls="buy" if unreal>=0 else "danger"
        current=f'<div class="card signal"><div class="section-title"><h2>{core.esc(open_trade["symbol"])} · شراء</h2><span class="pill">15m · مفتوحة</span></div><div class="price-row"><div class="price-box"><small>الدخول</small><b>{float(open_trade["entry"]):.8g}</b></div><div class="price-box"><small>السعر الآن</small><b>{cur_price:.8g}</b></div><div class="price-box"><small>النتيجة الآن</small><b class="{ucls}">{unreal:+.2f}%</b></div><div class="price-box"><small>الحماية</small><b class="gold">{float(open_trade["protect_price"] or open_trade["entry"]):.8g}</b></div><div class="price-box"><small>TP1</small><b class="buy">{float(open_trade["tp1"] or 0):.8g}</b></div><div class="price-box"><small>TP2</small><b class="buy">{float(open_trade["tp2"] or 0):.8g}</b></div><div class="price-box"><small>TP3</small><b class="buy">{float(open_trade["tp3"] or 0):.8g}</b></div><div class="price-box"><small>رأس المال</small><b>{float(open_trade["capital"]):.2f} USDT</b></div></div></div>'
    history="".join(f'<div class="card"><div class="section-title"><b>{core.esc(x["symbol"])}</b><b class="{"buy" if float(x["pnl_pct"] or 0)>0 else "danger"}">{float(x["pnl_pct"] or 0):+.2f}% · {float(x["pnl_amount"] or 0):+.2f} USDT</b></div><div class="muted">{x["opened_at"][:16]} · دخول {float(x["entry"]):.8g} · خروج {float(x["exit_price"] or 0):.8g}</div></div>' for x in trades)
    bot_note="إذا شغلت التنفيذ الحقيقي، استخدم مفتاح Binance بصلاحية Spot فقط وبدون السحب."
    q=req.query_params.get("binance","")
    if q=="ok":
        bot_note="<span class=\"buy\">✅ تم الاتصال بـ Binance بنجاح ومفتاح Spot صالح.</span>"
    elif q=="nosspot":
        bot_note="<span class=\"danger\">❌ المفتاح متصل لكن ما ظهرت صلاحية Spot.</span>"
    elif q=="missing":
        bot_note="<span class=\"danger\">❌ أدخل API Key وAPI Secret أولاً.</span>"
    elif q=="failed":
        bot_note="<span class=\"danger\">❌ فشل اتصال Binance. راجع المفتاح والصلاحيات.</span>"
    body=f'''<section class="hero"><h1>🤖 بوتي</h1><p class="muted">اربط حساب Binance الخاص فيك، ثم شغّل البوت. إعداداتك وصفقاتك منفصلة عن بقية المستخدمين.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><span class="pill {status_cls}">● البوت: {status}</span><span class="pill {conn_cls}">● Binance: {"مرتبط" if connected else "غير مرتبط"}</span><span class="pill">الوضع: {mode}</span></div></section>
<div class="stats"><div class="statbox"><small>الرصيد</small><b class="stat">{float(s["balance"]):.2f}</b></div><div class="statbox"><small>الصفقات المغلقة</small><b class="stat">{total}</b></div><div class="statbox"><small>نسبة النجاح</small><b class="stat">{winrate:.1f}%</b></div><div class="statbox"><small>صافي الربح</small><b class="stat {"buy" if float(pnl["a"])>=0 else "danger"}">{float(pnl["a"]):+.2f}</b></div></div>
<div class="card"><h2>🔐 ربط Binance</h2><p class="muted">المفتاح والسر يحفظان مشفّرين ولا نعرضهما بعد الحفظ.</p><form method="post" action="/bot/settings"><input name="api_key" type="password" autocomplete="off" placeholder="Binance API Key"><input name="api_secret" type="password" autocomplete="off" placeholder="Binance API Secret"><input name="capital" type="number" min="1" step="0.01" value="{float(s["initial_capital"]):.2f}" placeholder="رأس المال USDT"><input name="target_pct" type="number" min="0.5" step="0.5" value="{float(s["target_pct"] or 0.5):.1f}" placeholder="خطوة الحماية %"><label style="display:block;margin:8px 0"><input name="live" type="checkbox" {"checked" if s["live_enabled"] else ""}> تفعيل التنفيذ الحقيقي</label><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" name="action" value="save">حفظ الربط</button><button class="btn" formaction="/bot/binance-test">اختبار Binance</button></div></form><p class="muted">{bot_note}</p></div>
<div class="card"><h2>▶️ تشغيل البوت</h2><p class="muted">الاستراتيجية: سبوت BUY فقط · 15m · حماية متحركة.</p><form method="post" action="/bot/settings"><input type="hidden" name="capital" value="{float(s["initial_capital"]):.2f}"><input type="hidden" name="target_pct" value="{float(s["target_pct"] or 0.5):.1f}"><button class="btn primary" name="action" value="start">🚀 تشغيل البوت</button><button class="btn" name="action" value="stop">⏹ إيقاف البوت</button></form><p class="muted">آخر فحص: {core.esc(s["last_scan"] or "—")} · آخر إشارة: {core.esc(s["last_signal"] or "—")}</p></div>
<h2>📌 متابعة الصفقة</h2>{current}<h2>📜 سجل صفقات البوت</h2><div class="grid">{history or '<div class="card muted">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>'''
    return _page(req,"بوتي",body)

@core.app.get("/bot",response_class=HTMLResponse)
def bot_route(req:Request):
    return bot_page(req)

@core.app.post("/bot/binance-test")
def binance_test(req:Request,api_key:str=Form(""),api_secret:str=Form("")):
    u=core.user(req)
    if not u:
        return RedirectResponse("/login",303)
    c=bdb()
    s=_ensure_user(c,u["id"])
    key=api_key.strip()
    secret=api_secret.strip()
    if not key:
        key=_dec(s["api_key_enc"])
    if not secret:
        secret=_dec(s["api_secret_enc"])
    if not key or not secret:
        return RedirectResponse("/bot?binance=missing",303)
    try:
        x=_signed("GET","/api/v3/account",{},key,secret)
        ok=isinstance(x,dict) and "balances" in x
        perms=x.get("permissions") or []
        spot_ok=("SPOT" in perms) or ("ENABLE_SPOT" in perms) or not perms
        if ok and spot_ok:
            c.execute("UPDATE user_bot_settings SET api_key_enc=?,api_secret_enc=?,updated_at=? WHERE user_id=?",( _enc(key),_enc(secret),core.now(),u["id"]))
            c.commit()
        if ok and spot_ok:
            return RedirectResponse("/bot?binance=ok",303)
        if ok and not spot_ok:
            return RedirectResponse("/bot?binance=nosspot",303)
        return RedirectResponse("/bot?binance=failed",303)
    except Exception:
        return RedirectResponse("/bot?binance=failed",303)

@core.app.post("/bot/settings")
def bot_settings(req:Request,action:str=Form(...),capital:float=Form(100),target_pct:float=Form(0.5),api_key:str=Form(""),api_secret:str=Form(""),live:bool=Form(False)):
    u=core.user(req)
    if not u:
        return RedirectResponse("/login",303)
    c=bdb()
    s=_ensure_user(c,u["id"])
    key=api_key.strip()
    secret=api_secret.strip()
    if action=="save":
        if key and secret:
            c.execute("UPDATE user_bot_settings SET api_key_enc=?,api_secret_enc=?,initial_capital=?,target_pct=?,live_enabled=?,updated_at=? WHERE user_id=?",( _enc(key),_enc(secret),max(1,float(capital)),max(0.5,float(target_pct)),int(live),core.now(),u["id"]))
        else:
            c.execute("UPDATE user_bot_settings SET initial_capital=?,target_pct=?,live_enabled=?,updated_at=? WHERE user_id=?",(max(1,float(capital)),max(0.5,float(target_pct)),int(live),core.now(),u["id"]))
    elif action=="start":
        if not _binance_connection(s):
            return RedirectResponse("/bot?error=اربط Binance واختبر الاتصال أولاً",303)
        if s["live_enabled"] and not (s["api_key_enc"] and s["api_secret_enc"]):
            return RedirectResponse("/bot?error=مفاتيح Binance غير موجودة",303)
        c.execute("UPDATE user_bot_settings SET enabled=1,initial_capital=?,target_pct=?,updated_at=? WHERE user_id=?",(max(1,float(capital)),max(0.5,float(target_pct)),core.now(),u["id"]))
    elif action=="stop":
        c.execute("UPDATE user_bot_settings SET enabled=0,updated_at=? WHERE user_id=?",(core.now(),u["id"]))
    c.commit()
    return RedirectResponse("/bot",303)

@core.app.on_event("startup")
def start_bot_worker():
    try:
        bdb()
    except Exception:
        pass
    threading.Thread(target=bot_loop,daemon=True,name="user-spot-bot").start()
