PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS people (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT UNIQUE NOT NULL,
    email     TEXT,
    aliases   TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meetings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    meeting_date TEXT NOT NULL,
    attendees    TEXT DEFAULT '[]',
    transcript   TEXT,
    status       TEXT NOT NULL DEFAULT 'processing'
                 CHECK(status IN ('processing','needs_clarification','awaiting_approval','executing','done','failed')),
    error        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    quote      TEXT,
    speaker    TEXT,
    start_ts   TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    owner_id    INTEGER REFERENCES people(id),
    owner_name  TEXT,
    due_raw     TEXT,
    due_date    TEXT,
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','in_progress','done','cancelled')),
    quote       TEXT,
    speaker     TEXT,
    start_ts    TEXT,
    fingerprint TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_name, status);
CREATE INDEX IF NOT EXISTS idx_tasks_fingerprint  ON tasks(fingerprint);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date     ON tasks(due_date);

CREATE TABLE IF NOT EXISTS proposed_actions (
    id               TEXT PRIMARY KEY,
    meeting_id       INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    type             TEXT NOT NULL
                     CHECK(type IN ('create_task','create_event','draft_email','record_decision')),
    payload          TEXT DEFAULT '{}',
    original_payload TEXT DEFAULT '{}',
    source_item_ids  TEXT DEFAULT '[]',
    decision         TEXT NOT NULL DEFAULT 'pending'
                     CHECK(decision IN ('pending','approve','edit','reject')),
    execution_status TEXT NOT NULL DEFAULT 'not_run'
                     CHECK(execution_status IN ('not_run','executed','failed','skipped')),
    result           TEXT,
    decided_at       TEXT,
    executed_at      TEXT
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    attendees  TEXT DEFAULT '[]',
    start_at   TEXT NOT NULL,
    end_at     TEXT NOT NULL,
    agenda     TEXT,
    source     TEXT NOT NULL DEFAULT 'agent' CHECK(source IN ('agent','seed')),
    meeting_id INTEGER REFERENCES meetings(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cal_time ON calendar_events(start_at, end_at);

CREATE TABLE IF NOT EXISTS emails (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER REFERENCES meetings(id),
    to_addrs   TEXT DEFAULT '[]',
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent')),
    created_at TEXT DEFAULT (datetime('now')),
    sent_at    TEXT
);

CREATE TABLE IF NOT EXISTS action_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER REFERENCES meetings(id),
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    actor      TEXT NOT NULL
               CHECK(actor IN ('system','extractor','validator','planner','user','executor')),
    event      TEXT NOT NULL,
    ref_type   TEXT CHECK(ref_type IN ('task','decision','action','meeting') OR ref_type IS NULL),
    ref_id     TEXT,
    detail     TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_log_meeting_ts ON action_log(meeting_id, ts);

-- Append-only enforcement for action_log
CREATE TRIGGER IF NOT EXISTS action_log_no_update
BEFORE UPDATE ON action_log
BEGIN
    SELECT RAISE(ABORT, 'action_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS action_log_no_delete
BEFORE DELETE ON action_log
BEGIN
    SELECT RAISE(ABORT, 'action_log is append-only');
END;
