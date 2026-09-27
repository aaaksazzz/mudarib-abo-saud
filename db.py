import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

# Production persistence: Northflank should mount a persistent volume at /data.
# DATA_DIR can override this path. Local development keeps data beside the app.
_default_dir = "/data" if os.getenv("NORTHFLANK") or os.getenv("PORT") else str(Path(__file__).parent)
DB = Path(os.getenv("DATA_DIR", _default_dir)) / "data.db"

@contextmanager
def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            tp1 REAL, tp2 REAL, tp3 REAL, sl REAL,
            ai REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT,
            pnl REAL DEFAULT 0,
            source TEXT DEFAULT 'scanner',
            telegram_sent INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS news(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            source TEXT DEFAULT '',
            url TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS binance_connections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            api_key_enc TEXT NOT NULL,
            api_secret_enc TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS user_orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'MARKET',
            quantity REAL,
            quote_amount REAL,
            leverage REAL DEFAULT 1,
            entry_price REAL,
            binance_order_id TEXT,
            status TEXT DEFAULT 'NEW',
            pnl REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            timeframe TEXT DEFAULT '15m',
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            sl REAL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_trades_market_tf ON trades(market,timeframe);
        CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
        CREATE INDEX IF NOT EXISTS idx_trades_status_market ON trades(status,market);
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users(lower(email));
        CREATE INDEX IF NOT EXISTS idx_user_orders_user ON user_orders(user_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_user_orders_status ON user_orders(user_id,status);
        """)

        trade_cols = {r["name"] for r in c.execute("PRAGMA table_info(trades)").fetchall()}
        order_cols = {r["name"] for r in c.execute("PRAGMA table_info(user_orders)").fetchall()}

        trade_migrations = {
            "timeframe": "TEXT DEFAULT '15m'",
            "tp1": "REAL",
            "tp2": "REAL",
            "tp3": "REAL",
            "sl": "REAL",
            "source": "TEXT DEFAULT 'scanner'",
            "telegram_sent": "INTEGER DEFAULT 0",
            "tp1_hit_at": "TEXT",
            "tp2_hit_at": "TEXT",
            "tp3_hit_at": "TEXT",
            "sl_hit_at": "TEXT",
        }
        for col, typ in trade_migrations.items():
            if col not in trade_cols:
                c.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")

        order_migrations = {
            "timeframe": "TEXT DEFAULT '15m'",
            "tp1": "REAL",
            "tp2": "REAL",
            "tp3": "REAL",
            "sl": "REAL",
        }
        for col, typ in order_migrations.items():
            if col not in order_cols:
                c.execute(f"ALTER TABLE user_orders ADD COLUMN {col} {typ}")

        # One-time clean reset of the old platform trade journal.
        # This intentionally deletes ONLY platform strategy trades; users,
        # sessions, Binance connections, and personal Binance orders remain untouched.
        reset_key = "tracker_reset_2026_09_27"
        if c.execute("SELECT 1 FROM settings WHERE key=?", (reset_key,)).fetchone() is None:
            c.execute("DELETE FROM trades")
            c.execute(
                "INSERT INTO settings(key,value) VALUES(?,?)",
                (reset_key, "done"),
            )

        if c.execute("SELECT COUNT(*) n FROM news").fetchone()["n"] == 0:
            c.execute(
                "INSERT INTO news(title,body,source) VALUES(?,?,?)",
                (
                    "منصة التداول الذكي PRO",
                    "المنصة جاهزة لعرض تحليلات الأسواق والصفقات ومتابعة الأداء.",
                    "النظام",
                ),
            )

def rows(sql, args=()):
    with conn() as c:
        return [dict(x) for x in c.execute(sql, args).fetchall()]

def one(sql, args=()):
    with conn() as c:
        x = c.execute(sql, args).fetchone()
        return dict(x) if x else None

def execute(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).lastrowid
