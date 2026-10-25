"""Unit tests for task_db."""
import pytest

from app.db.connection import reset_db_for_tests
from app.tools.task_db import find_similar, fingerprint, insert_task, known_names, norm, resolve_person


@pytest.fixture
def conn():
    c = reset_db_for_tests()
    # Seed a person
    c.execute("INSERT INTO people (name, aliases) VALUES ('Alice Chen', '[\"Alice\"]')")
    c.execute("INSERT INTO people (name, aliases) VALUES ('Bob Smith', '[\"Bob\"]')")
    c.commit()
    return c


def test_norm():
    assert norm("Hello, World!") == "hello  world"
    # After further normalization
    assert " ".join(norm("Hello, World!").split()) == "hello world"


def test_fingerprint_consistent():
    fp1 = fingerprint("Set up CI pipeline", "Alice")
    fp2 = fingerprint("Set up CI pipeline", "Alice")
    assert fp1 == fp2


def test_fingerprint_different_owners():
    fp1 = fingerprint("Set up CI pipeline", "Alice")
    fp2 = fingerprint("Set up CI pipeline", "Bob")
    assert fp1 != fp2


def test_insert_and_find(conn):
    # Seed a meeting
    conn.execute("INSERT INTO meetings (title, meeting_date, status) VALUES ('Test', '2026-10-25', 'done')")
    conn.commit()
    mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    task_id = insert_task({"meeting_id": mid, "title": "Write the README", "owner_name": "Alice"}, conn)
    assert task_id > 0

    similar = find_similar("Write the README", "Alice", conn)
    assert len(similar) > 0
    assert similar[0]["title"] == "Write the README"


def test_resolve_person_known(conn):
    count, name = resolve_person("Alice", conn)
    assert count == 1
    assert name == "Alice Chen"


def test_resolve_person_by_alias(conn):
    count, name = resolve_person("Bob", conn)
    assert count == 1
    assert name == "Bob Smith"


def test_resolve_person_unknown(conn):
    count, name = resolve_person("Zara", conn)
    assert count == 0


def test_resolve_person_ambiguous(conn):
    conn.execute("INSERT INTO people (name, aliases) VALUES ('Sam Johnson', '[\"Sam\"]')")
    conn.execute("INSERT INTO people (name, aliases) VALUES ('Sam Lee', '[\"Sam\"]')")
    conn.commit()
    count, name = resolve_person("Sam", conn)
    assert count >= 2


def test_known_names(conn):
    names = known_names(conn)
    assert "Alice Chen" in names
    assert "Alice" in names
    assert "Bob" in names


def test_find_similar_duplicate(conn):
    conn.execute("INSERT INTO meetings (title, meeting_date, status) VALUES ('T', '2026-10-25', 'done')")
    conn.commit()
    mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    insert_task({"meeting_id": mid, "title": "Deploy the application to production", "owner_name": "Alice"}, conn)

    # Similar title
    similar = find_similar("Deploy application to production", "Alice", conn)
    assert len(similar) > 0
