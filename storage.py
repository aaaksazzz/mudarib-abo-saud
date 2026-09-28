from __future__ import annotations

import json
import os
from typing import Any

try:
    import psycopg
except Exception:
    psycopg = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

def db_enabled() -> bool:
    return bool(DATABASE_URL and psycopg)

def _connect():
    if not db_enabled():
        return None
    return psycopg.connect(DATABASE_URL, connect_timeout=8)

def init_db() -> None:
    if not db_enabled():
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    state_key TEXT PRIMARY KEY,
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()

def db_load(key: str) -> Any:
    if not db_enabled():
        return None
    try:
        init_db()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state_json FROM app_state WHERE state_key=%s", (key,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None

def db_save(key: str, value: Any) -> bool:
    if not db_enabled():
        return False
    try:
        init_db()
        payload=json.dumps(value, ensure_ascii=False)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app_state(state_key,state_json,updated_at)
                    VALUES (%s,%s::jsonb,NOW())
                    ON CONFLICT(state_key)
                    DO UPDATE SET state_json=EXCLUDED.state_json, updated_at=NOW()
                """, (key, payload))
            conn.commit()
        return True
    except Exception:
        return False
