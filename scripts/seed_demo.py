"""Idempotent demo data seeder. Run once before demoing."""
from __future__ import annotations

import json
import sys
import os

# Allow running as: python scripts/seed_demo.py from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import init_db, get_db
from app.tools.task_db import fingerprint

def seed():
    init_db()
    conn = get_db()

    # ── People ────────────────────────────────────────────────────────────────
    people = [
        ("Alex Chen",   "alex.chen@company.com",   ["Alex", "Alex C"]),
        ("Ravi Kumar",  "ravi.kumar@company.com",  ["Ravi"]),
        ("Sam Johnson", "sam.j@company.com",       ["Sam"]),   # ← ambiguous alias
        ("Sam Lee",     "sam.lee@company.com",     ["Sam"]),   # ← ambiguous alias
        ("Priya Sharma","priya@company.com",       ["Priya"]),
    ]
    for name, email, aliases in people:
        existing = conn.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO people (name, email, aliases) VALUES (?,?,?)",
                (name, email, json.dumps(aliases)),
            )
            print(f"  [seed] Added person: {name}")

    conn.commit()

    # ── Open tasks (cross-meeting memory) ─────────────────────────────────────
    # Seed a placeholder meeting for these tasks
    existing_meeting = conn.execute("SELECT id FROM meetings WHERE title='[Seed] Previous Sprint'").fetchone()
    if not existing_meeting:
        conn.execute(
            "INSERT INTO meetings (title, meeting_date, attendees, transcript, status) VALUES (?,?,?,?,?)",
            ("[Seed] Previous Sprint", "2026-10-06", json.dumps(["Alex Chen","Ravi Kumar"]), "Seeded", "done"),
        )
        conn.commit()
    seed_mid = conn.execute("SELECT id FROM meetings WHERE title='[Seed] Previous Sprint'").fetchone()["id"]

    open_tasks = [
        {"title": "Set up CI/CD pipeline", "owner_name": "Alex Chen", "due_date": "2026-10-20"},
        {"title": "Write API documentation", "owner_name": "Ravi Kumar", "due_date": "2026-10-22"},
        {"title": "Review pull requests for auth module", "owner_name": "Priya Sharma", "due_date": None},
    ]
    for t in open_tasks:
        fp = fingerprint(t["title"], t.get("owner_name"))
        existing = conn.execute("SELECT id FROM tasks WHERE fingerprint=?", (fp,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO tasks (meeting_id, title, owner_name, due_date, status, fingerprint) VALUES (?,?,?,?,?,?)",
                (seed_mid, t["title"], t.get("owner_name"), t.get("due_date"), "open", fp),
            )
            print(f"  [seed] Added task: {t['title']}")

    conn.commit()

    # ── Busy calendar blocks (week of 2026-10-26) ─────────────────────────────
    busy_blocks = [
        ("Team standup", ["Alex Chen","Ravi Kumar","Priya Sharma"], "2026-10-27T09:00:00", "2026-10-27T09:30:00"),
        ("Design review",["Sam Johnson","Sam Lee"],                "2026-10-28T14:00:00", "2026-10-28T15:00:00"),
        ("1:1 with manager", ["Ravi Kumar"],                       "2026-10-29T10:00:00", "2026-10-29T10:30:00"),
    ]
    for title, attendees, start, end in busy_blocks:
        existing = conn.execute(
            "SELECT id FROM calendar_events WHERE title=? AND start_at=?", (title, start)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO calendar_events (title, attendees, start_at, end_at, source) VALUES (?,?,?,?,?)",
                (title, json.dumps(attendees), start, end, "seed"),
            )
            print(f"  [seed] Added busy block: {title}")

    conn.commit()
    print("\n✅ Seed complete!")


if __name__ == "__main__":
    seed()
