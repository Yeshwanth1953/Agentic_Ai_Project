import os
import sqlite3
from pathlib import Path

_conn: sqlite3.Connection | None = None


def _db_path() -> str:
    data_dir = os.getenv("DATA_DIR", "data/")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return str(Path(data_dir) / "app.db")


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _make_conn(_db_path())
    return _conn


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    conn = get_db()
    with open(schema_path, "r") as f:
        conn.executescript(f.read())
    conn.commit()


def reset_db_for_tests() -> sqlite3.Connection:
    """Return an in-memory connection with schema applied — for unit tests."""
    conn = _make_conn(":memory:")
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn
