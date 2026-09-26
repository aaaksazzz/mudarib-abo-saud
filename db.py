import sqlite3
from pathlib import Path
from contextlib import contextmanager
DB=Path(__file__).parent/"data.db"
@contextmanager
def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    try: yield c; c.commit()
    finally: c.close()
def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,side TEXT NOT NULL,entry REAL NOT NULL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,ai REAL DEFAULT 0,status TEXT DEFAULT 'open',created_at TEXT DEFAULT CURRENT_TIMESTAMP,closed_at TEXT,pnl REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'user',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
def rows(sql,args=()):
    with conn() as c:return [dict(x) for x in c.execute(sql,args).fetchall()]
def one(sql,args=()):
    with conn() as c:
        x=c.execute(sql,args).fetchone()
        return dict(x) if x else None
