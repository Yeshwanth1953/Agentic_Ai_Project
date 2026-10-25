"""Mock email integration — backed by emails table."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime


def draft(
    meeting_id: int | None,
    to_addrs: list[str],
    subject: str,
    body: str,
    conn: sqlite3.Connection,
) -> int:
    cur = conn.execute(
        "INSERT INTO emails (meeting_id, to_addrs, subject, body) VALUES (?,?,?,?)",
        (meeting_id, json.dumps(to_addrs), subject, body),
    )
    conn.commit()
    return cur.lastrowid


def send(draft_id: int, conn: sqlite3.Connection) -> bool:
    conn.execute(
        "UPDATE emails SET status='sent', sent_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), draft_id),
    )
    conn.commit()
    return True
