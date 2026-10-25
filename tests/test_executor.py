"""Unit tests for executor — critical safety properties."""
import json
import pytest

from app.db.connection import reset_db_for_tests
from app.graph.nodes.executor import executor
from app.graph.state import AgentState, Evidence, ProposedAction, TaskItem
from datetime import date


@pytest.fixture
def conn():
    c = reset_db_for_tests()
    c.execute("INSERT INTO meetings (title, meeting_date, status) VALUES ('Test', '2026-10-25', 'done')")
    c.commit()
    return c


def _base_state(actions, conn) -> AgentState:
    return {
        "meeting_id": 1,
        "meeting_date": date(2026, 10, 25),
        "title": "Test",
        "attendees": [],
        "transcript": "",
        "segments": [],
        "decisions": [],
        "tasks": [],
        "questions": [],
        "answers": [],
        "retries": 0,
        "actions": actions,
        "log": [],
    }


def test_approved_action_creates_task(conn, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.executor.get_db", lambda: conn)
    monkeypatch.setattr("app.logging.get_db", lambda: conn)
    # Also monkeypatch persist_log_entries to avoid issues
    monkeypatch.setattr("app.graph.nodes.executor.persist_log_entries", lambda entries, conn: None)

    action = ProposedAction(
        type="create_task",
        payload={"title": "Send the report", "owner_name": "Alice", "meeting_id": 1},
        decision="approve",
    )

    state = _base_state([action], conn)
    result = executor(state)

    # Task should be in DB
    task = conn.execute("SELECT * FROM tasks WHERE title='Send the report'").fetchone()
    assert task is not None
    assert result["actions"][0].execution_status == "executed"


def test_rejected_action_not_executed(conn, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.executor.get_db", lambda: conn)
    monkeypatch.setattr("app.graph.nodes.executor.persist_log_entries", lambda e, c: None)

    action = ProposedAction(
        type="create_task",
        payload={"title": "This should not be created", "owner_name": "Bob", "meeting_id": 1},
        decision="reject",
    )

    state = _base_state([action], conn)
    result = executor(state)

    task = conn.execute("SELECT * FROM tasks WHERE title='This should not be created'").fetchone()
    assert task is None
    assert result["actions"][0].execution_status == "skipped"


def test_pending_action_not_executed(conn, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.executor.get_db", lambda: conn)
    monkeypatch.setattr("app.graph.nodes.executor.persist_log_entries", lambda e, c: None)

    action = ProposedAction(
        type="create_task",
        payload={"title": "Pending task", "owner_name": "Alice", "meeting_id": 1},
        decision="pending",  # NOT approved
    )

    state = _base_state([action], conn)
    result = executor(state)

    task = conn.execute("SELECT * FROM tasks WHERE title='Pending task'").fetchone()
    assert task is None
    assert result["actions"][0].execution_status == "not_run"


def test_idempotency_skips_already_executed(conn, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.executor.get_db", lambda: conn)
    monkeypatch.setattr("app.graph.nodes.executor.persist_log_entries", lambda e, c: None)

    action = ProposedAction(
        type="create_task",
        payload={"title": "Only once", "owner_name": "Alice", "meeting_id": 1},
        decision="approve",
        execution_status="executed",  # Already executed
    )

    state = _base_state([action], conn)
    executor(state)

    count = conn.execute("SELECT COUNT(*) FROM tasks WHERE title='Only once'").fetchone()[0]
    assert count == 0  # Not inserted again


def test_action_log_append_only(conn):
    """action_log UPDATE should be blocked by the trigger."""
    conn.execute(
        "INSERT INTO action_log (meeting_id, actor, event) VALUES (1, 'system', 'test_event')"
    )
    conn.commit()
    log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    import sqlite3
    with pytest.raises(sqlite3.OperationalError, match="append-only"):
        conn.execute("UPDATE action_log SET event='tampered' WHERE id=?", (log_id,))
        conn.commit()
