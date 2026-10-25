# Meeting-to-Action Agent — Technical Documentation

## 1. Problem Statement

Meetings generate commitments, decisions, and follow-ups that are often forgotten or mis-recorded. This system extracts structured actions from meeting transcripts, validates them against the transcript, clarifies ambiguities with the meeting participants, and creates verified tasks/events/emails — with mandatory human approval at every step.

---

## 2. System Architecture

### High-Level Flow

```
Transcript Input
      │
      ▼
┌─────────────┐
│  Extractor  │  LLM extracts decisions + tasks, resolves dates deterministically
└──────┬──────┘
       │
       ▼
┌─────────────┐    fixable problems?  ┌────────────┐
│  Validator  │ ────────────────────► │ Re-extract │ (max 2 retries)
└──────┬──────┘                       └────────────┘
       │ unclear problems?
       ▼
┌─────────────┐    interrupt()
│   Clarify   │ ──────────────────────── Human answers questions
└──────┬──────┘    resume(answers)
       │
       ▼
┌─────────────┐
│   Planner   │  Creates proposed_actions (tasks, events, emails, decisions)
└──────┬──────┘
       │
       ▼
┌─────────────┐    interrupt()
│  Approval   │ ──────────────────────── Human approve/edit/reject each action
└──────┬──────┘    resume(decisions)
       │
       ▼
┌─────────────┐
│  Executor   │  Writes approved actions to DB; logs everything
└─────────────┘
```

### Technology Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| Agent framework | LangGraph 0.2+ | Graph-based control flow with interrupt/resume |
| LLM | Groq `llama-3.3-70b-versatile` | Fast inference, JSON mode |
| Persistence | SqliteSaver (LangGraph) | Graph state survives server restarts |
| Backend API | FastAPI | Async, Pydantic v2, easy background tasks |
| Frontend | Streamlit | Rapid prototyping, polling pattern |
| Database | SQLite WAL mode | Single-file, no setup, concurrent reads |
| Validation | Pydantic v2 | Structured LLM outputs and API contracts |

---

## 3. Database Schema

### Tables

**`people`** — Known meeting participants with alias resolution
```sql
id, name UNIQUE, email, aliases JSON (list of strings), created_at
```

**`meetings`** — One row per processed transcript
```sql
id, title, meeting_date, attendees JSON, transcript TEXT,
status CHECK(processing|needs_clarification|awaiting_approval|executing|done|failed),
error TEXT, created_at, updated_at
```

**`decisions`** — Extracted decisions with source attribution
```sql
id, meeting_id FK, text, quote, speaker, start_ts, created_at
```

**`tasks`** — Extracted and approved tasks
```sql
id, meeting_id FK, title, owner_id FK→people, owner_name, due_raw,
due_date TEXT, status CHECK(open|in_progress|done|cancelled),
quote, speaker, start_ts, fingerprint, created_at, updated_at
```

**`proposed_actions`** — Actions pending or decided by human
```sql
id TEXT PK (uuid), meeting_id FK, type CHECK(create_task|create_event|draft_email|record_decision),
payload JSON, original_payload JSON, source_item_ids JSON,
decision CHECK(pending|approve|edit|reject),
execution_status CHECK(not_run|executed|failed|skipped),
result JSON, decided_at, executed_at
```

**`calendar_events`**, **`emails`** — Mock backends for calendar and email

**`action_log`** — Immutable audit trail
```sql
id, meeting_id, ts TEXT, actor CHECK(system|extractor|validator|planner|user|executor),
event TEXT, ref_type, ref_id, detail JSON
-- Two triggers make this append-only:
-- BEFORE UPDATE → RAISE(ABORT)
-- BEFORE DELETE → RAISE(ABORT)
```

---

## 4. Agent Nodes

### 4.1 Extractor
- Parses transcript using `transcript_parser.parse()` into `Segment` objects
- Sends transcript + known open tasks to LLM with structured output schema
- LLM returns `decisions[]` and `tasks[]` each with a verbatim quote
- Date resolution: calls `date_resolver.resolve(due_raw, meeting_date)` — LLM never sees dates
- On re-extract: includes failing items + their error codes in prompt

### 4.2 Validator
Runs 8 checks in order for each task:

| Code | Type | Action |
|------|------|--------|
| NO_QUOTE | fixable | LLM re-extract |
| MISSING_OWNER | needs_clarification | Ask human |
| UNKNOWN_OWNER | needs_clarification | Ask human |
| AMBIGUOUS_OWNER | needs_clarification | Ask human (Q21: auto-resolve if one attendee matches) |
| MISSING_DEADLINE | needs_clarification | Ask human |
| VAGUE_DEADLINE | needs_clarification | Ask human |
| PAST_DEADLINE | needs_clarification | Ask human (not re-extract, per design) |
| DUPLICATE | needs_clarification | Ask human |

**Routing:** fixable + retries < 2 → re_extract; any unclear → clarify; all valid → plan

### 4.3 Clarify
- Builds typed `Question` objects per problem code
- Calls `interrupt({"questions": [...]})` — pauses graph execution
- API stores questions; UI displays them as form fields
- On resume: merges answers into task fields (owner, due_date, duplicate status)

### 4.4 Planner
- Creates `create_task` action for each valid task
- Creates `record_decision` action for each valid decision
- Creates `draft_email` action per unique owner (batches related tasks)
- Optionally creates `create_event` action if decision mentions sync/meeting keywords
- Checks `calendar_mock.check_availability()` and adds warnings to action payload

### 4.5 Approval
- Calls `interrupt({"actions": [...]})` — pauses graph execution
- API stores proposed actions; UI shows approve/edit/reject per action
- On resume: merges `{action_id, decision, edits?}` into actions list

### 4.6 Executor (Critical Safety Node)
**Only runs for actions where `decision in ("approve", "edit")`**
**Idempotent: skips any action with `execution_status != "not_run"`**

| Action type | Operation |
|------------|-----------|
| `create_task` | `task_db.insert_task()` → `tasks` table |
| `create_event` | `calendar_mock.create_event()` → `calendar_events` table |
| `draft_email` | `email_mock.draft()` + `send()` → `emails` table |
| `record_decision` | `INSERT INTO decisions` |

Writes `LogEntry` for every action (executed or skipped). Sets meeting status to `done`.

---

## 5. Tools Layer

### transcript_parser.py
- Supports plain (`Speaker: text`), timestamped (`[HH:MM] Speaker: text`), VTT, SRT formats
- Stop-list labels (`Note`, `Action item`, `Decision`, `Update`, `Agenda`, `TODO`, `FYI`, `Re`) continue the current speaker turn instead of starting a new segment
- `ground_quote()`: case-sensitive verbatim substring check after whitespace normalization

### date_resolver.py
Deterministic resolution — never calls LLM. Handles:
- `today`, `tomorrow`, `in N days`
- ISO dates (`YYYY-MM-DD`)
- Full weekday names (`Monday`–`Sunday`) with `this`/`next` prefix
- `by the weekend`, `by next weekend`, `end of month`
- Vague list (`soon`, `asap`, `next week`, etc.) → `kind="vague"`, `date=None`
- Abbreviated weekdays (`Mon`, `Fri`) → `None` (ambiguous)

### task_db.py
- `norm()`: lowercase, punctuation→space, collapse whitespace
- `fingerprint()`: SHA1 of `norm(title) + "|" + norm(owner)` — exact duplicate detection
- `find_similar()`: Jaccard similarity on word sets (≥0.8 = duplicate, 0.6–0.8 = suspicious)
- `resolve_person()`: returns `(count, name)` — 0=unknown, 1=resolved, ≥2=ambiguous

---

## 6. API Endpoints

### Meeting Lifecycle

```
POST   /meetings              Upload transcript → 202 Accepted, meeting_id
GET    /meetings/{id}         Poll status (processing → needs_clarification → awaiting_approval → done)
GET    /meetings/{id}/questions  Get clarification questions (status must be needs_clarification)
POST   /meetings/{id}/answers    Submit answers → resumes graph
GET    /meetings/{id}/plan    Get proposed actions (status must be awaiting_approval)
POST   /meetings/{id}/execute    Submit approval decisions → resumes graph
GET    /meetings/{id}/results    Get execution results per action
GET    /meetings/{id}/log     Full audit trail (action_log rows)
GET    /tasks                 All open tasks
GET    /health                {"status": "ok"}
```

### Status Lifecycle Enforcement
Each endpoint validates `meeting.status` and returns HTTP 409 Conflict if the meeting is in the wrong state. This prevents race conditions and double-submissions.

---

## 7. Human-in-the-Loop Design

### Interrupt/Resume Pattern
LangGraph's `interrupt()` function pauses graph execution and raises a `GraphInterrupt` exception. The API layer catches this exception and:
1. Updates `meeting.status` to `needs_clarification` or `awaiting_approval`
2. Persists questions/actions to the database so they survive server restarts
3. Returns a 200 OK to the background task

When the human submits answers/decisions, the API calls `Command(resume=payload)` which resumes the graph from the exact checkpoint where it paused.

### SqliteSaver
LangGraph's `SqliteSaver` persists the full graph state (including all node outputs) in a SQLite database at each step. The `thread_id = str(meeting_id)` connects each HTTP request to the correct conversation thread.

---

## 8. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| LLM never resolves dates | Eliminates hallucination risk; date_resolver is 100% deterministic and testable |
| Executor is the ONLY DB writer | Single writer prevents partial state; easy to audit |
| action_log is append-only | SQL triggers guarantee immutable audit trail |
| Verbatim quote grounding | Every extracted item must have a source substring; prevents hallucinated tasks |
| FakeLLM for tests | Tests run without API keys; deterministic behavior |
| Jaccard similarity for duplicates | Simple, interpretable, no LLM needed for most cases |
| FastAPI + Streamlit separation | UI never imports graph code; clean boundary between frontend and backend |

---

## 9. Running and Testing

### Setup
```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # add GROQ_API_KEY
python scripts/seed_demo.py
```

### Start Servers
```bash
uvicorn app.api.main:app --reload --port 8000
streamlit run ui/app.py   # new terminal
```

### Run Tests
```bash
pytest -q                          # all tests
pytest tests/test_date_resolver.py # specific module
pytest -k "test_approved"          # filter by name
USE_FAKE_LLM=1 pytest -q           # force FakeLLM
```

### Verify DB
```bash
python -c "from app.db.connection import init_db; init_db(); print('DB OK')"
```

---

## 10. Evaluation

The `eval/` directory contains:
- `transcripts/01_sprint_planning.txt` — demo transcript with 8 planted edge cases
- `labels/01_sprint_planning.json` — ground truth tasks, decisions, and edge case descriptions
- `run.py` — eval harness (compares agent output vs. labels)
- `metrics.py` — precision/recall/F1, owner accuracy, due_date accuracy

Edge cases covered in the demo transcript:
- `AMBIGUOUS_OWNER`: "Sam" matches two people
- `DUPLICATE`: task matching a seeded open task
- `MISSING_OWNER`: unattributed CI task
- `VAGUE_DEADLINE`: "end of next week"
- `MISSING_DEADLINE`: calendar invite task with no date
- `SELF_COMMITMENT`: "I'll prepare and send..."
- `STOP_LABEL`: "Note:" line that should not start a new segment
- `CALENDAR_EVENT`: decision referencing a sync meeting
