# -*- coding: utf-8 -*-
"""صف خروجی سبک برای همگام‌سازی با ووکامرس.

این ماژول عمداً به repo وابسته نیست تا حلقهٔ وابستگی ایجاد نشود.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from threading import local

import db

_state = local()


@contextmanager
def suppress_outbound():
    previous = getattr(_state, "suppress", False)
    _state.suppress = True
    try:
        yield
    finally:
        _state.suppress = previous


def enabled(con) -> bool:
    return (
        not getattr(_state, "suppress", False)
        and db.get_setting(con, "woo_enabled", "0") == "1"
    )


def enqueue(
    con, entity: str, local_id: int | None, action: str, payload: dict | None = None
) -> int | None:
    if not enabled(con):
        return None
    # جلوگیری از انباشت کارهای تکراریِ در انتظار
    row = con.execute(
        "SELECT id FROM woo_queue WHERE entity=? AND local_id IS ? AND action=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (entity, local_id, action),
    ).fetchone()
    now = datetime.now().isoformat(timespec="seconds")
    data = json.dumps(payload or {}, ensure_ascii=False)
    if row:
        con.execute(
            "UPDATE woo_queue SET payload=?, updated_at=? WHERE id=?",
            (data, now, row["id"]),
        )
        return row["id"]
    cur = con.execute(
        "INSERT INTO woo_queue (entity,local_id,action,payload,updated_at) VALUES (?,?,?,?,?)",
        (entity, local_id, action, data, now),
    )
    return cur.lastrowid


def log(
    con,
    direction: str,
    entity: str,
    status: str,
    message: str = "",
    remote_id: int | None = None,
    local_id: int | None = None,
) -> None:
    con.execute(
        "INSERT INTO woo_log (direction,entity,remote_id,local_id,status,message) VALUES (?,?,?,?,?,?)",
        (direction, entity, remote_id, local_id, status, message[:2000]),
    )


def set_state(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO woo_state (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def get_state(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM woo_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def map_local(con, entity: str, local_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM woo_map WHERE entity=? AND local_id=?", (entity, local_id)
    ).fetchone()


def map_remote(con, entity: str, remote_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM woo_map WHERE entity=? AND remote_id=?", (entity, remote_id)
    ).fetchone()


def put_map(
    con,
    entity: str,
    local_id: int,
    remote_id: int,
    *,
    remote_parent_id: int | None = None,
    remote_updated: str = "",
    local_hash: str = "",
    remote_hash: str = "",
) -> None:
    con.execute(
        """INSERT INTO woo_map (entity,local_id,remote_id,remote_parent_id,remote_updated,local_hash,remote_hash,last_synced)
        VALUES (?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(entity,local_id) DO UPDATE SET
            remote_id=excluded.remote_id,
            remote_parent_id=excluded.remote_parent_id,
            remote_updated=excluded.remote_updated,
            local_hash=excluded.local_hash,
            remote_hash=excluded.remote_hash,
            last_synced=datetime('now')""",
        (
            entity,
            local_id,
            remote_id,
            remote_parent_id,
            remote_updated,
            local_hash,
            remote_hash,
        ),
    )
