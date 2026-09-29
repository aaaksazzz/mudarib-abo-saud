import os, json, time, threading, urllib.parse, urllib.request

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT=os.getenv("TELEGRAM_CHAT_ID","@tadol1").strip()


def _send(text):
    if not TOKEN or not CHAT:
        return False
    try:
        data=urllib.parse.urlencode({"chat_id":CHAT,"text":text,"parse_mode":"HTML","disable_web_page_preview":"true"}).encode()
        req=urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",data=data,method="POST")
        with urllib.request.urlopen(req,timeout=15) as r:
            return json.loads(r.read().decode()).get("ok",False)
    except Exception:
        return False


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f"{x:,.2f}"
        if abs(x)>=1:return f"{x:.4f}".rstrip("0").rstrip(".")
        return f"{x:.8f}".rstrip("0").rstrip(".")
    except Exception:
        return "—"


def _trade_message(t,closed=False):
    side="بيع" if t["side"]=="SELL" else "شراء"
    emoji="🔴" if t["side"]=="SELL" else "🟢"
    if closed:
        pnl=float(t["pnl_pct"] or 0)
        return (f"{emoji} <b>إغلاق صفقة</b>\\n\\n"
                f"💠 <b>{t['symbol']}</b> · {t['market']} · {t['timeframe']}\\n"
                f"الاتجاه: <b>{side}</b>\\n"
                f"الدخول: <code>{_fmt(t['entry'])}</code>\\n"
                f"الخروج: <code>{_fmt(t['exit_price'])}</code>\\n"
                f"النتيجة: <b>{pnl:+.2f}%</b>")
    parts=[f"{emoji} <b>صفقة جديدة</b>\\n",f"💠 <b>{t['symbol']}</b> · {t['market']} · {t['timeframe']}",f"الاتجاه: <b>{side}</b>",f"الدخول: <code>{_fmt(t['entry'])}</code>",f"🛑 الوقف: <code>{_fmt(t['stop'])}</code>"]
    for n in (1,2,3):
        v=t[f"tp{n}"]
        if v is not None: parts.append(f"🎯 TP{n}: <code>{_fmt(v)}</code>")
    parts.append(f"🤖 AI: <b>{float(t['confidence'] or 0):.0f}%</b>")
    parts.append(f"📈 التغير: <b>{float(t['change15'] or 0):+.2f}%</b>")
    return "\\n".join(parts)


def _ensure():
    c=core.db()
    c.execute("CREATE TABLE IF NOT EXISTS telegram_events(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_id INTEGER,event TEXT,created_at TEXT,UNIQUE(trade_id,event))")
    c.commit()
    return c


def _worker():
    while True:
        try:
            c=_ensure()
            if TOKEN and CHAT:
                rows=c.execute("SELECT * FROM trades WHERE status='open' ORDER BY id ASC").fetchall()
                for t in rows:
                    if c.execute("SELECT 1 FROM telegram_events WHERE trade_id=? AND event='open'",(t['id'],)).fetchone(): continue
                    if _send(_trade_message(t)):
                        c.execute("INSERT OR IGNORE INTO telegram_events(trade_id,event,created_at) VALUES(?,?,?)",(t['id'],'open',core.now())); c.commit()
                rows=c.execute("SELECT * FROM trades WHERE status!='open' AND closed_at IS NOT NULL ORDER BY id ASC").fetchall()
                for t in rows:
                    if c.execute("SELECT 1 FROM telegram_events WHERE trade_id=? AND event='close'",(t['id'],)).fetchone(): continue
                    if _send(_trade_message(t,True)):
                        c.execute("INSERT OR IGNORE INTO telegram_events(trade_id,event,created_at) VALUES(?,?,?)",(t['id'],'close',core.now())); c.commit()
        except Exception:
            pass
        time.sleep(15)


def start():
    threading.Thread(target=_worker,name="telegram-publisher",daemon=True).start()

try:
    import app_v2 as core
    start()
except Exception:
    pass
