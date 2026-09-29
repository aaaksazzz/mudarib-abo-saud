import time, threading, urllib.parse, urllib.request, json, hmac
from hashlib import sha256
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from cryptography.fernet import Fernet
import os, base64, hashlib
import app_v2 as core

BOT_SCHEMA="""
CREATE TABLE IF NOT EXISTS bot_settings(
 id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER DEFAULT 0,
 initial_capital REAL DEFAULT 100.0, balance REAL DEFAULT 100.0,
 target_pct REAL DEFAULT 0.5, api_key_enc TEXT DEFAULT '', api_secret_enc TEXT DEFAULT '',
 live_enabled INTEGER DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS bot_trades(
 id INTEGER PRIMARY KEY, signal_id INTEGER, symbol TEXT, timeframe TEXT DEFAULT '15m',
 entry REAL, stop REAL, tp1 REAL, tp2 REAL, tp3 REAL, capital REAL, qty REAL,
 exit_price REAL, pnl_pct REAL, pnl_amount REAL, status TEXT DEFAULT 'open',
 opened_at TEXT, closed_at TEXT
);
"""

def bdb():
    c=core.db(); c.executescript(BOT_SCHEMA)
    cols={x[1] for x in c.execute("PRAGMA table_info(bot_settings)").fetchall()}
    if 'target_pct' not in cols: c.execute("ALTER TABLE bot_settings ADD COLUMN target_pct REAL DEFAULT 0.5")
    if 'api_key_enc' not in cols: c.execute("ALTER TABLE bot_settings ADD COLUMN api_key_enc TEXT DEFAULT ''")
    if 'api_secret_enc' not in cols: c.execute("ALTER TABLE bot_settings ADD COLUMN api_secret_enc TEXT DEFAULT ''")
    if 'live_enabled' not in cols: c.execute("ALTER TABLE bot_settings ADD COLUMN live_enabled INTEGER DEFAULT 0")
    if not c.execute("SELECT 1 FROM bot_settings WHERE id=1").fetchone():
        c.execute("INSERT INTO bot_settings(id,enabled,initial_capital,balance,target_pct,api_key_enc,api_secret_enc,updated_at) VALUES(1,0,100,100,0.5,'','',0,?)",(core.now(),))
    c.commit(); return c

def _fernet():
    raw=os.getenv('BOT_ENCRYPTION_KEY','').strip()
    if not raw:
        raw=base64.urlsafe_b64encode(hashlib.sha256((os.getenv('SECRET_KEY') or 'mudarib-bot-key').encode()).digest()).decode()
    return Fernet(raw.encode())

def _enc(v):
    return _fernet().encrypt(v.encode()).decode() if v else ''

def _dec(v):
    try: return _fernet().decrypt(v.encode()).decode() if v else ''
    except Exception: return ''

def _signed(method,path,params,key,secret):
    p=dict(params or {})
    p['timestamp']=int(time.time()*1000); p['recvWindow']=5000
    q=urllib.parse.urlencode(p)
    sig=hmac.new(secret.encode(),q.encode(),sha256).hexdigest()
    req=urllib.request.Request('https://api.binance.com'+path+'?'+q+'&signature='+sig,method=method,headers={'X-MBX-APIKEY':key})
    with urllib.request.urlopen(req,timeout=10) as r: return json.loads(r.read().decode())

def _price(symbol):
    with urllib.request.urlopen('https://api.binance.com/api/v3/ticker/price?symbol='+symbol,timeout=8) as r:
        return float(json.loads(r.read().decode())['price'])

def _rules(symbol,key,secret):
    x=_signed('GET','/api/v3/exchangeInfo',{'symbol':symbol},key,secret)['symbols'][0]['filters']
    d={}
    for f in x:
        if f['filterType']=='LOT_SIZE': d['step']=float(f['stepSize']); d['min']=float(f['minQty'])
    return d

def _floor(v,step):
    return float((Decimal(str(v))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step))) if step else v

def _avg(order):
    fills=order.get('fills') or []
    q=sum(float(f['qty']) for f in fills); cost=sum(float(f['qty'])*float(f['price']) for f in fills)
    return (cost/q if q else 0),q

def _pick_signal(c):
    # نفس إشارة السبوت 15m التي ينتجها محرك الاستراتيجية الأساسي.
    return c.execute("SELECT * FROM signals WHERE market='spot' AND side='BUY' AND timeframe='15m' AND status='open' ORDER BY confidence DESC, change15 DESC, id DESC LIMIT 1").fetchone()

def bot_step():
    c=bdb(); s=c.execute("SELECT * FROM bot_settings WHERE id=1").fetchone()
    if not s or not s["enabled"]: return
    t=c.execute("SELECT * FROM bot_trades WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    live=bool(s["live_enabled"] and s["api_key_enc"] and s["api_secret_enc"])
    if t:
        try:
            price=_price(t["symbol"]) if live else float(core.market_candles("spot",t["symbol"],"15m")[-1][4])
            entry=float(t["entry"]); step=float(s["target_pct"] or 0.5)
            peak=max(float(t["peak"] or entry),price)
            levels=int(max(0,(peak/entry-1)*100)/step)
            protect=entry*(1+max(0,levels-1)*step/100)
            c.execute("UPDATE bot_trades SET peak=?,protect_price=? WHERE id=?",(peak,protect,t["id"]))
            if levels>=1 and price<=protect:
                exit_price=price
                if live:
                    key=_dec(s["api_key_enc"]); secret=_dec(s["api_secret_enc"])
                    rules=_rules(t["symbol"],key,secret); qty=_floor(float(t["qty"]),rules.get("step"))
                    order=_signed("POST","/api/v3/order",{"symbol":t["symbol"],"side":"SELL","type":"MARKET","quantity":f"{qty:.12f}".rstrip("0").rstrip(".")},key,secret)
                    exit_price,sold=_avg(order)
                pnl=(exit_price-entry)/entry*100
                amount=float(t["capital"])*pnl/100
                new_balance=float(s["balance"])+amount
                c.execute("UPDATE bot_trades SET status='closed',exit_price=?,pnl_pct=?,pnl_amount=?,closed_at=?,peak=?,protect_price=? WHERE id=?",(exit_price,pnl,amount,core.now(),peak,protect,t["id"]))
                c.execute("UPDATE bot_settings SET balance=?,updated_at=? WHERE id=1",(new_balance,core.now()))
                c.commit()
        except Exception: c.rollback()
        return
    sig=_pick_signal(c)
    if not sig or float(s["balance"])<=0:return
    capital=float(s["balance"]); entry=float(sig["entry"]); qty=capital/entry; oid=""
    if live:
        try:
            key=_dec(s["api_key_enc"]); secret=_dec(s["api_secret_enc"])
            order=_signed("POST","/api/v3/order",{"symbol":sig["symbol"],"side":"BUY","type":"MARKET","quoteOrderQty":f"{capital:.2f}"},key,secret)
            entry,qty=_avg(order); oid=str(order.get("orderId",""))
        except Exception: return
    c.execute("INSERT INTO bot_trades(signal_id,symbol,timeframe,entry,stop,tp1,tp2,tp3,capital,qty,status,opened_at,peak,protect_price,exchange_order_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sig["id"],sig["symbol"],sig["timeframe"],entry,None,sig["tp1"],sig["tp2"],sig["tp3"],capital,qty,"open",core.now(),entry,entry,oid))
    c.commit()

def bot_loop():
    while True:
        try: bot_step()
        except Exception: pass
        time.sleep(15)

def bot_page(req:Request):
    u=core.user(req)
    if not u:return RedirectResponse('/login',303)
    c=bdb(); s=c.execute("SELECT * FROM bot_settings WHERE id=1").fetchone()
    open_trade=c.execute("SELECT * FROM bot_trades WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    hist=c.execute("SELECT * FROM bot_trades WHERE status='closed' ORDER BY id DESC LIMIT 20").fetchall()
    total=c.execute("SELECT COUNT(*) n FROM bot_trades WHERE status='closed'").fetchone()['n']
    wins=c.execute("SELECT COUNT(*) n FROM bot_trades WHERE status='closed' AND pnl_pct>0").fetchone()['n']
    pnl=c.execute("SELECT COALESCE(SUM(pnl_pct),0) p,COALESCE(SUM(pnl_amount),0) a FROM bot_trades WHERE status='closed'").fetchone()
    winrate=(wins/total*100) if total else 0
    status='يعمل' if s['enabled'] else 'متوقف'
    status_cls='buy' if s['enabled'] else 'danger'
    current='لا توجد صفقة حالياً'
    if open_trade:
        current=f'''<div class="card signal"><div class="section-title"><h2>{core.esc(open_trade['symbol'])} · شراء</h2><span class="pill">15m · مفتوحة</span></div><div class="price-row"><div class="price-box"><small>رأس المال</small><b>{float(open_trade['capital']):.2f} USDT</b></div><div class="price-box"><small>الدخول</small><b>{float(open_trade['entry']):.8g}</b></div><div class="price-box"><small>الحماية</small><b class="gold">بدون وقف</b></div><div class="price-box"><small>TP3</small><b class="buy">{float(open_trade['tp3'] or open_trade['tp2'] or open_trade['tp1']):.8g}</b></div></div><p class="muted">الكمية المحسوبة: {float(open_trade['qty']):.8g} · البوت يتابع السعر تلقائياً.</p></div>'''
    history=''.join(f'''<div class="card"><div class="section-title"><div><b>{core.esc(x['symbol'])}</b><div class="muted">{x['opened_at'][:16]}</div></div><b class="{'buy' if float(x['pnl_pct'] or 0)>0 else 'danger'}">{float(x['pnl_pct'] or 0):+.2f}% · {float(x['pnl_amount'] or 0):+.2f} USDT</b></div><div class="muted">دخول {float(x['entry']):.8g} · خروج {float(x['exit_price']):.8g} · رأس المال {float(x['capital']):.2f}</div></div>''' for x in hist)
    body=f'''<section class="hero"><h1>🤖 بوت السبوت</h1><p class="muted">نفس استراتيجية السبوت 15 دقيقة، حماية متحركة كل +0.5%: لا نبيع عند الربح، ونرفع الحماية تدريجياً حتى يعكس السعر ويخرج من الصفقة.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><span class="pill {status_cls}">● {status}</span><span class="pill">الرصيد {float(s['balance']):.2f} USDT</span></div></section><div class="stats"><div class="statbox"><small>الرصيد الحالي</small><b class="stat">{float(s['balance']):.2f}</b></div><div class="statbox"><small>إجمالي الصفقات</small><b class="stat">{total}</b></div><div class="statbox"><small>نسبة النجاح</small><b class="stat">{winrate:.1f}%</b></div><div class="statbox"><small>إجمالي الربح</small><b class="stat {'buy' if float(pnl['a'])>=0 else 'danger'}">{float(pnl['a']):+.2f}</b></div></div><div class="card"><h2>تشغيل البوت</h2><form method="post" action="/bot/settings"><input name="capital" type="number" min="1" step="0.01" value="{float(s['balance']):.2f}" placeholder="الرصيد الابتدائي USDT"><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" name="action" value="start">تشغيل ومتابعة</button><button class="btn" name="action" value="stop">إيقاف</button><button class="btn" name="action" value="reset">إعادة الرصيد</button></div></form><p class="muted">البوت هنا للمتابعة والمحاكاة فقط؛ لا ينفذ أوامر شراء حقيقية في Binance.</p></div><h2>الصفقة الحالية</h2>{current}<h2>سجل البوت</h2><div class="grid">{history or '<div class="card muted">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>'''
    return core.page(req,'بوت السبوت',body)

@core.app.get('/bot',response_class=HTMLResponse)
def bot_route(req:Request): return bot_page(req)

@core.app.post('/bot/settings')
def bot_settings(req:Request,action:str=Form(...),capital:float=Form(100),target_pct:float=Form(0.5),api_key:str=Form(''),api_secret:str=Form(''),live:bool=Form(False)):
    u=core.user(req)
    if not u:return RedirectResponse('/login',303)
    c=bdb(); s=c.execute("SELECT * FROM bot_settings WHERE id=1").fetchone()
    if action=='reset':
        v=max(1,float(capital)); c.execute("UPDATE bot_settings SET enabled=0,initial_capital=?,balance=?,target_pct=?,api_key_enc=?,api_secret_enc=?,live_enabled=?,updated_at=? WHERE id=1",(v,v,max(0.1,float(target_pct)),_enc(api_key),_enc(api_secret),int(live),core.now()))
    elif action=='start':
        # إذا لم يوجد تداول سابق، يبدأ من رأس المال المدخل؛ وإلا يحافظ على الرصيد المتراكم.
        v=max(1,float(capital)); balance=float(s['balance']) if float(s['balance'])>0 else v
        c.execute("UPDATE bot_settings SET enabled=1,initial_capital=?,balance=?,target_pct=?,api_key_enc=COALESCE(NULLIF(?,''),api_key_enc),api_secret_enc=COALESCE(NULLIF(?,''),api_secret_enc),live_enabled=?,updated_at=? WHERE id=1",(v,balance,max(0.1,float(target_pct)),_enc(api_key),_enc(api_secret),core.now()))
    else:
        c.execute("UPDATE bot_settings SET enabled=0,updated_at=? WHERE id=1",(core.now(),))
    c.commit(); return RedirectResponse('/bot',303)

# Add the bot to the existing top navigation without replacing the site's layout.
_original_page=core.page
def page_with_bot(req,title,body):
    html=_original_page(req,title,body)
    marker='<nav class="nav">'
    if marker in html and 'href="/bot"' not in html:
        html=html.replace(marker,marker+'<a href="/bot">🤖<span>البوت</span></a>',1)
    return html
core.page=page_with_bot

@core.app.on_event('startup')
def start_bot_worker():
    bdb()
    threading.Thread(target=bot_loop,daemon=True,name='spot-bot').start()
