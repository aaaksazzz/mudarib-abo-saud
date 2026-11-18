"""AS persistent research memory and hourly learning cycle.

Consumes only explicitly recorded, resolved paper-trade outcomes. It does not
invent market data, retrain a predictive model, change production parameters,
or execute orders. SQLite is the durable memory store when its volume is
persisted by the hosting environment / workflow cache.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "as_learning"
LEDGER = DATA_DIR / "paper_experiences.jsonl"
DB_PATH = Path(os.environ.get("AS_MEMORY_DB", str(DATA_DIR / "as_memory.sqlite3")))
REPORT = DATA_DIR / "latest_report.json"
FINGERPRINT = "AS-CONTINUOUS-MEMORY-HOURLY-V1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS experiences (
        experience_id TEXT PRIMARY KEY,
        recorded_at TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        regime TEXT NOT NULL,
        side TEXT NOT NULL,
        net_r REAL NOT NULL,
        outcome TEXT NOT NULL,
        source_hash TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS cycles (
        cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ran_at TEXT NOT NULL,
        ingested INTEGER NOT NULL,
        total_experiences INTEGER NOT NULL,
        strategies_seen INTEGER NOT NULL,
        status TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS strategy_memory (
        strategy_id TEXT NOT NULL,
        market TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        regime TEXT NOT NULL,
        sample_size INTEGER NOT NULL,
        wins INTEGER NOT NULL,
        losses INTEGER NOT NULL,
        net_expectancy_r REAL NOT NULL,
        profit_factor REAL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(strategy_id, market, timeframe, regime)
    )""")
    db.commit()
    return db


def read_ledger():
    if not LEDGER.exists():
        return []
    records = []
    for line_no, line in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            required = ("experience_id", "strategy_id", "market", "symbol",
                        "timeframe", "regime", "side", "net_r", "outcome")
            if any(k not in row for k in required):
                continue
            net_r = float(row["net_r"])
            if row["outcome"] not in ("win", "loss", "breakeven") or not (-100 <= net_r <= 100):
                continue
            if row["side"] not in ("BUY", "SELL"):
                continue
            row["_line"] = line_no
            row["_net_r"] = net_r
            row["_raw"] = line.strip()
            records.append(row)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return records


def refresh_memory(db: sqlite3.Connection, records):
    inserted = 0
    import hashlib
    for row in records:
        digest = hashlib.sha256(row["_raw"].encode("utf-8")).hexdigest()
        cur = db.execute("""INSERT OR IGNORE INTO experiences
            (experience_id, recorded_at, strategy_id, market, symbol, timeframe,
             regime, side, net_r, outcome, source_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(row["experience_id"]), str(row.get("recorded_at") or utc_now()),
             str(row["strategy_id"]), str(row["market"]), str(row["symbol"]),
             str(row["timeframe"]), str(row["regime"]), str(row["side"]),
             row["_net_r"], str(row["outcome"]), digest))
        inserted += cur.rowcount
    db.commit()
    return inserted


def rebuild_aggregates(db: sqlite3.Connection):
    rows = db.execute("""SELECT strategy_id, market, timeframe, regime,
        COUNT(*), SUM(CASE WHEN net_r > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN net_r < 0 THEN 1 ELSE 0 END), AVG(net_r),
        SUM(CASE WHEN net_r > 0 THEN net_r ELSE 0 END),
        ABS(SUM(CASE WHEN net_r < 0 THEN net_r ELSE 0 END))
        FROM experiences GROUP BY strategy_id, market, timeframe, regime""").fetchall()
    stamp = utc_now()
    db.execute("DELETE FROM strategy_memory")
    for r in rows:
        wins_sum, losses_abs = float(r[8] or 0), float(r[9] or 0)
        pf = (wins_sum / losses_abs) if losses_abs > 0 else (None if wins_sum == 0 else 999.0)
        db.execute("""INSERT INTO strategy_memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (r[0], r[1], r[2], r[3], r[4], r[5], r[6],
                    round(float(r[7] or 0), 6), pf, stamp))
    db.commit()
    return len(rows)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = connect()
    try:
        records = read_ledger()
        inserted = refresh_memory(db, records)
        groups = rebuild_aggregates(db)
        total = db.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        strategies = db.execute("SELECT COUNT(DISTINCT strategy_id) FROM experiences").fetchone()[0]
        status = "updated_from_resolved_paper_outcomes" if inserted else "no_new_resolved_paper_outcomes"
        db.execute("INSERT INTO cycles(ran_at, ingested, total_experiences, strategies_seen, status) VALUES (?, ?, ?, ?, ?)",
                   (utc_now(), inserted, total, strategies, status))
        db.commit()
        stats = db.execute("""SELECT strategy_id, market, timeframe, regime,
            sample_size, wins, losses, net_expectancy_r, profit_factor
            FROM strategy_memory ORDER BY sample_size DESC""").fetchall()
        report = {
            "fingerprint": FINGERPRINT,
            "generated_at": utc_now(),
            "status": status,
            "cycle_interval": "hourly",
            "memory_store": str(DB_PATH.relative_to(ROOT)) if DB_PATH.is_relative_to(ROOT) else str(DB_PATH),
            "new_experiences_ingested": inserted,
            "total_resolved_paper_experiences": total,
            "strategy_groups": groups,
            "strategies_seen": strategies,
            "memory": [
                {"strategy_id": x[0], "market": x[1], "timeframe": x[2], "regime": x[3],
                 "sample_size": x[4], "wins": x[5], "losses": x[6],
                 "net_expectancy_r": x[7], "profit_factor": x[8]}
                for x in stats
            ],
            "limitations": [
                "This cycle learns only from resolved, recorded paper-trade outcomes.",
                "No fresh market feed is fetched by this worker.",
                "No model weights or production strategy parameters are changed.",
                "Small samples are descriptive only and are not evidence of an edge.",
                "No live trading or order execution is performed."
            ]
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("fingerprint", "status", "new_experiences_ingested",
                                                  "total_resolved_paper_experiences", "strategies_seen")}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
