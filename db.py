import sqlite3
from pathlib import Path
from contextlib import contextmanager
DB=Path(__file__).parent/"data.db"
@contextmanager
def conn():
    c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL")
    try: yield c; c.commit()
    except: c.rollback(); raise
    finally: c.close()
def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,side TEXT NOT NULL,entry REAL NOT NULL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,ai REAL DEFAULT 0,status TEXT DEFAULT 'open',created_at TEXT DEFAULT CURRENT_TIMESTAMP,closed_at TEXT,pnl REAL DEFAULT 0,source TEXT DEFAULT 'scanner',telegram_sent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'user',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT DEFAULT '',source TEXT DEFAULT '',url TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_trades_market_tf ON trades(market,timeframe);
        """)
        cols=[r["name"] for r in c.execute("PRAGMA table_info(trades)").fetchall()]
        if "source" not in cols:c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'scanner'")
        if "telegram_sent" not in cols:c.execute("ALTER TABLE trades ADD COLUMN telegram_sent INTEGER DEFAULT 0")
        for col in ("tp1_hit_at","tp2_hit_at","tp3_hit_at","sl_hit_at"):
            if col not in cols:c.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
        if c.execute("SELECT COUNT(*) n FROM news").fetchone()["n"]==0:
            c.execute("INSERT INTO news(title,body,source) VALUES(?,?,?)",("منصة التداول الذكي PRO","المنصة جاهزة لعرض تحليلات الأسواق والصفقات ومتابعة الأداء.","النظام"))
def rows(sql,args=()):
    with conn() as c:return [dict(x) for x in c.execute(sql,args).fetchall()]
def one(sql,args=()):
    with conn() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
def execute(sql,args=()):
    with conn() as c:return c.execute(sql,args).lastrowid
