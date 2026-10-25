"""Mock calendar integration — backed by calendar_events table."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta


def check_availability(
    attendees: list[str],
    start_at: str,
    end_at: str,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Return busy blocks that overlap with the requested time for any attendee."""
    rows = conn.execute(
        "SELECT * FROM calendar_events WHERE start_at < ? AND end_at > ?",
        (end_at, start_at),
    ).fetchall()

    conflicts = []
    for row in rows:
        event_attendees = json.loads(row["attendees"] or "[]")
        overlap = [a for a in attendees if a in event_attendees]
        if overlap:
            conflicts.append({**dict(row), "conflicting_attendees": overlap})
    return conflicts


def suggest_slots(
    attendees: list[str],
    duration_min: int,
    after_date: str,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Suggest up to 3 available 9–17 slots on weekdays after after_date."""
    try:
        start = datetime.fromisoformat(after_date)
    except ValueError:
        start = datetime.utcnow()

    slots: list[dict] = []
    current = start.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)

    while len(slots) < 3:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        slot_end = current + timedelta(minutes=duration_min)
        if slot_end.hour > 17:
            current = current.replace(hour=9) + timedelta(days=1)
            continue
        conflicts = check_availability(
            attendees,
            current.isoformat(),
            slot_end.isoformat(),
            conn,
        )
        if not conflicts:
            slots.append({"start": current.isoformat(), "end": slot_end.isoformat()})
        current += timedelta(minutes=30)

    return slots


def create_event(
    title: str,
    attendees: list[str],
    start_at: str,
    end_at: str,
    agenda: str | None,
    meeting_id: int | None,
    conn: sqlite3.Connection,
) -> int:
    cur = conn.execute(
        """INSERT INTO calendar_events (title, attendees, start_at, end_at, agenda, source, meeting_id)
           VALUES (?,?,?,?,?,?,?)""",
        (title, json.dumps(attendees), start_at, end_at, agenda, "agent", meeting_id),
    )
    conn.commit()
    return cur.lastrowid
