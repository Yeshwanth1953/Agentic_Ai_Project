# Meeting-to-Action Agent

An agentic AI system that converts meeting transcripts into verified, human-approved follow-up actions — tasks, calendar events, and draft emails — using a LangGraph pipeline with mandatory human-in-the-loop approval gates.

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate    # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env and add your GROQ_API_KEY

# 4. Seed demo data (people, open tasks, calendar blocks)
python scripts/seed_demo.py

# 5. Start the API server
uvicorn app.api.main:app --reload --port 8000

# 6. In a new terminal, start the UI
streamlit run ui/app.py
```

Open http://localhost:8501 in your browser.

## Run Tests

```bash
pytest -q
```

## Project Structure

```
app/
  api/          FastAPI backend (routes, schemas, main)
  graph/        LangGraph pipeline
    nodes/      Six agent nodes: extractor, validator, clarify, planner, approval, executor
    state.py    Shared state Pydantic models
    build.py    Graph wiring with SqliteSaver checkpointer
  tools/        Deterministic tools (transcript parser, date resolver, task DB, calendar, email)
  db/           SQLite schema and connection singleton
  llm.py        Groq LLM wrapper with FakeLLM for tests
ui/app.py       Streamlit single-page app
tests/          Unit tests (pytest)
eval/           Evaluation transcripts, labels, and harness
scripts/        seed_demo.py — idempotent demo data seeder
docs/           Technical documentation and faculty guide
```

## Architecture Overview

```
Transcript
    │
    ▼
[Extractor] ──LLM──► segments + decisions + tasks (with date resolution)
    │
    ▼
[Validator] ──────► checks 8 rules (quote grounding, owner, deadline, duplicate)
    │
    ├──fixable?──► [Re-extract] (max 2 retries)
    ├──unclear?──► [Clarify] ──interrupt──► Human answers questions ──resume──►
    └──all valid?► [Planner] ──────────► proposed_actions list
                                              │
                                        [Approval] ──interrupt──► Human approve/edit/reject ──resume──►
                                              │
                                        [Executor] ──────────► DB writes (tasks, events, emails, decisions)
```

**Key guarantees:**
- Nothing is written to the database without explicit human approval
- `action_log` table is append-only (SQL trigger enforces this)
- Verbatim quote grounding: every extracted item must have a verbatim substring from the transcript
- Date resolution is 100% deterministic — LLM never resolves dates

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /meetings | Upload transcript (multipart or JSON) |
| GET | /meetings/{id} | Get meeting status |
| GET | /meetings/{id}/questions | Get clarification questions |
| POST | /meetings/{id}/answers | Submit answers |
| GET | /meetings/{id}/plan | Get proposed actions |
| POST | /meetings/{id}/execute | Submit approval decisions |
| GET | /meetings/{id}/results | Get execution results |
| GET | /meetings/{id}/log | Get full audit log |
| GET | /tasks | List all open tasks |
| GET | /health | Health check |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| GROQ_API_KEY | Yes | — | Groq API key |
| LLM_MODEL | No | llama-3.3-70b-versatile | Groq model ID |
| DATA_DIR | No | data/ | Directory for SQLite database |
| USE_FAKE_LLM | No | — | Set to 1 to use FakeLLM (tests) |
