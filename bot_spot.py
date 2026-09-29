import time, threading
from datetime import datetime, timezone
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import app_v2 as core

BOT_SCHEMA="""
CREATE TABLE IF NOT EXISTS bot_settings(
 id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER DEFAULT 0,
 initial_capital REAL DEFAULT 100.0, balance REAL DEFAULT 100.0,
 updated_at TEXT
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
    if not c.execute("SELECT 1 FROM bot_settings WHERE id=1").fetchone():
        c.execute("INSERT INTO bot_settings(id,enabled,initial_capital,balance,updated_at) VALUES(1,0,100,100,?)",(core.now(),))
    c.commit(); return c

def _pick_signal(c):
    # نفس إشارة السبوت 15m التي ينتجها محرك الاستراتيجية الأساسي.
    return c.execute("SELECT * FROM signals WHERE market='spot' AND side='BUY' AND timeframe='15m' AND status='open' ORDER BY confidence DESC, change15 DESC, id DESC LIMIT 1").fetchone()

def bot_step():
    c=bdb(); s=c.execute("SELECT * FROM bot_settings WHERE id=1").fetchone()
    if not s or not s["enabled"]: return
    open_trade=c.execute("SELECT * FROM bot_trades WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    if open_trade:
        try:
            candles=core.market_candles('spot',open_trade['symbol'],'15m')
            if not candles:return
            price=float(candles[-1][4]); target=float(open_trade['tp3'] or open_trade['tp2'] or open_trade['tp1'])
            exit_price=None
            # بدون وقف خسارة: البوت ينتظر الهدف فقط، ثم يضيف الربح للرصيد.
            if price>=target: exit_price=target
            if exit_price is not None:
                pnl=(exit_price-float(open_trade['entry']))/float(open_trade['entry'])*100
                amount=float(open_trade['capital'])*pnl/100
                new_balance=float(s['balance'])+amount
                c.execute("UPDATE bot_trades SET status='closed',exit_price=?,pnl_pct=?,pnl_amount=?,closed_at=? WHERE id=?",(exit_price,pnl,amount,core.now(),open_trade['id']))
                c.execute("UPDATE bot_settings SET balance=?,updated_at=? WHERE id=1",(new_balance,core.now()))
                c.commit()
        except Exception: pass
        return
    sig=_pick_signal(c)
    if not sig or float(s['balance'])<=0:return
    entry=float(sig['entry']); capital=float(s['balance']); qty=capital/entry
    c.execute("INSERT INTO bot_trades(signal_id,symbol,timeframe,entry,stop,tp1,tp2,tp3,capital,qty,status,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(sig['id'],sig['symbol'],sig['timeframe'],entry,None,sig['tp1'],sig['tp2'],sig['tp3'],capital,qty,'open',core.now()))
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
    body=f'''<section class="hero"><h1>🤖 بوت السبوت</h1><p class="muted">نفس استراتيجية السبوت 15 دقيقة، بدون وقف خسارة. عند الوصول للهدف تُغلق الصفقة، ويُضاف كامل الربح للرصيد، ثم تدخل الصفقة التالية برصيد أكبر.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><span class="pill {status_cls}">● {status}</span><span class="pill">الرصيد {float(s['balance']):.2f} USDT</span></div></section><div class="stats"><div class="statbox"><small>الرصيد الحالي</small><b class="stat">{float(s['balance']):.2f}</b></div><div class="statbox"><small>إجمالي الصفقات</small><b class="stat">{total}</b></div><div class="statbox"><small>نسبة النجاح</small><b class="stat">{winrate:.1f}%</b></div><div class="statbox"><small>إجمالي الربح</small><b class="stat {'buy' if float(pnl['a'])>=0 else 'danger'}">{float(pnl['a']):+.2f}</b></div></div><div class="card"><h2>تشغيل البوت</h2><form method="post" action="/bot/settings"><input name="capital" type="number" min="1" step="0.01" value="{float(s['balance']):.2f}" placeholder="الرصيد الابتدائي USDT"><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" name="action" value="start">تشغيل ومتابعة</button><button class="btn" name="action" value="stop">إيقاف</button><button class="btn" name="action" value="reset">إعادة الرصيد</button></div></form><p class="muted">البوت هنا للمتابعة والمحاكاة فقط؛ لا ينفذ أوامر شراء حقيقية في Binance.</p></div><h2>الصفقة الحالية</h2>{current}<h2>سجل البوت</h2><div class="grid">{history or '<div class="card muted">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>'''
    return core.page(req,'بوت السبوت',body)

@core.app.get('/bot',response_class=HTMLResponse)
def bot_route(req:Request): return bot_page(req)

@core.app.post('/bot/settings')
def bot_settings(req:Request,action:str=Form(...),capital:float=Form(100)):
    u=core.user(req)
    if not u:return RedirectResponse('/login',303)
    c=bdb(); s=c.execute("SELECT * FROM bot_settings WHERE id=1").fetchone()
    if action=='reset':
        v=max(1,float(capital)); c.execute("UPDATE bot_settings SET enabled=0,initial_capital=?,balance=?,updated_at=? WHERE id=1",(v,v,core.now()))
    elif action=='start':
        # إذا لم يوجد تداول سابق، يبدأ من رأس المال المدخل؛ وإلا يحافظ على الرصيد المتراكم.
        v=max(1,float(capital)); balance=float(s['balance']) if float(s['balance'])>0 else v
        c.execute("UPDATE bot_settings SET enabled=1,initial_capital=?,balance=?,updated_at=? WHERE id=1",(v,balance,core.now()))
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
