"""Task and people database helpers."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime


def norm(s: str) -> str:
    """Lowercase, all punctuation → space, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def fingerprint(title: str, owner: str | None) -> str:
    key = norm(title) + "|" + norm(owner or "")
    return hashlib.sha1(key.encode()).hexdigest()


def _jaccard(a: str, b: str) -> float:
    sa = set(norm(a).split())
    sb = set(norm(b).split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_similar(title: str, owner: str | None, conn: sqlite3.Connection) -> list[dict]:
    fp = fingerprint(title, owner)
    results: list[dict] = []

    # exact fingerprint match
    row = conn.execute(
        "SELECT * FROM tasks WHERE fingerprint = ? AND status IN ('open','in_progress')",
        (fp,),
    ).fetchone()
    if row:
        results.append(dict(row))
        return results

    # Jaccard on open tasks with same owner_name
    candidates = conn.execute(
        "SELECT * FROM tasks WHERE status IN ('open','in_progress')",
    ).fetchall()
    for c in candidates:
        score = _jaccard(title, c["title"])
        if score >= 0.6:
            d = dict(c)
            d["_similarity"] = score
            results.append(d)

    return results


def insert_task(data: dict, conn: sqlite3.Connection) -> int:
    fp = fingerprint(data.get("title", ""), data.get("owner_name"))
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        """INSERT INTO tasks
           (meeting_id, title, owner_id, owner_name, due_raw, due_date, quote, speaker, start_ts, fingerprint, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("meeting_id"),
            data["title"],
            data.get("owner_id"),
            data.get("owner_name"),
            data.get("due_raw"),
            data.get("due_date"),
            data.get("quote"),
            data.get("speaker"),
            data.get("start_ts"),
            fp,
            now,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_open(attendee_names: list[str], conn: sqlite3.Connection) -> list[dict]:
    if not attendee_names:
        return []
    placeholders = ",".join("?" * len(attendee_names))
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE owner_name IN ({placeholders}) AND status IN ('open','in_progress')",
        attendee_names,
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_person(name: str, conn: sqlite3.Connection) -> tuple[int, str]:
    """Returns (count_of_matches, best_matched_name). 0=unknown, 1=resolved, >=2=ambiguous."""
    norm_name = norm(name)
    rows = conn.execute("SELECT id, name, aliases FROM people").fetchall()
    matches: list[str] = []
    for row in rows:
        if norm(row["name"]) == norm_name:
            matches.append(row["name"])
            continue
        aliases = json.loads(row["aliases"] or "[]")
        for alias in aliases:
            if norm(alias) == norm_name:
                matches.append(row["name"])
                break
    if len(matches) == 0:
        return 0, name
    if len(matches) == 1:
        return 1, matches[0]
    return len(matches), matches[0]


def known_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name, aliases FROM people").fetchall()
    names: list[str] = []
    for row in rows:
        names.append(row["name"])
        aliases = json.loads(row["aliases"] or "[]")
        names.extend(aliases)
    return names
