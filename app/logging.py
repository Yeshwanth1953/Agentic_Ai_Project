"""Helpers for writing LogEntry rows to action_log."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.graph.state import LogEntry


def persist_log_entries(entries: list[LogEntry], conn: sqlite3.Connection) -> None:
    for entry in entries:
        conn.execute(
            """INSERT INTO action_log (id, meeting_id, ts, actor, event, ref_type, ref_id, detail)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                entry.id,
                entry.meeting_id,
                entry.ts,
                entry.actor,
                entry.event,
                entry.ref_type,
                entry.ref_id,
                json.dumps(entry.detail),
            ),
        )
    conn.commit()


def make_log(
    meeting_id: int,
    actor: str,
    event: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> LogEntry:
    return LogEntry(
        meeting_id=meeting_id,
        actor=actor,  # type: ignore[arg-type]
        event=event,
        ref_type=ref_type,  # type: ignore[arg-type]
        ref_id=ref_id,
        detail=detail or {},
    )
