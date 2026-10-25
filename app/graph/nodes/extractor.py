"""Extractor node — parses transcript and extracts decisions + tasks via LLM."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.graph.state import AgentState, Decision, Evidence, LogEntry, TaskItem
from app.llm import get_llm, llm_call_with_retry
from app.logging import make_log
from app.tools.date_resolver import resolve
from app.tools.task_db import list_open
from app.tools.transcript_parser import parse


class _RawDecision(BaseModel):
    id: str = ""
    text: str
    quote: str


class _RawTask(BaseModel):
    id: str = ""
    title: str
    owner: str | None = None
    due_raw: str | None = None
    quote: str


class _ExtractionResult(BaseModel):
    decisions: list[_RawDecision] = []
    tasks: list[_RawTask] = []


def extractor(state: AgentState) -> dict[str, Any]:
    llm = get_llm()
    meeting_id = state["meeting_id"]
    meeting_date = state["meeting_date"]
    transcript = state["transcript"]
    attendees = state.get("attendees", [])
    retries = state.get("retries", 0)

    # Parse transcript into segments (always fresh)
    segments = parse(transcript)

    # Build context: open tasks for attendees to avoid re-extracting them
    from app.db.connection import get_db
    conn = get_db()
    open_tasks = list_open(attendees, conn) if attendees else []
    open_tasks_text = ""
    if open_tasks:
        open_tasks_text = "\n\nAlready tracked open tasks for attendees (DO NOT re-extract these):\n"
        for t in open_tasks:
            open_tasks_text += f"- [{t['owner_name']}] {t['title']}\n"

    # On re-extract: only fix failing items
    failing_context = ""
    if retries > 0 and state.get("tasks"):
        failing = [t for t in state["tasks"] if t.status in ("fixable",)]
        if failing:
            failing_context = "\n\nPreviously extracted items with problems (fix ONLY these):\n"
            for t in failing:
                for p in t.problems:
                    failing_context += f"- Task '{t.title}': {p.code} — {p.message}\n"

    system_msg = SystemMessage(content="""You are an expert meeting analyst. Extract ALL decisions and action items from the transcript.

Rules:
- Every item MUST include a verbatim quote from the transcript as evidence.
- A quote must be an exact substring of one speaker's turn (no paraphrasing).
- For owner: only set it when the transcript explicitly states it — name in quote ("Alice, can you...") or first-person self-commitment ("I'll do X" → that speaker's name).
- For due_raw: copy exactly as stated in the transcript (e.g., "next Friday", "by end of month"). Leave null if not mentioned.
- DO NOT extract vague ideas ("we should look into X"). Only extract concrete commitments with a clear action verb.
- Respond ONLY with valid JSON matching the schema.""")

    user_msg = HumanMessage(content=f"""Meeting: {state.get('title', 'Untitled')}
Date: {meeting_date}
Attendees: {', '.join(attendees) if attendees else 'unknown'}
{open_tasks_text}
{failing_context}

TRANSCRIPT:
{transcript}

Respond with JSON:
{{
  "decisions": [{{"id": "d1", "text": "...", "quote": "exact transcript text"}}],
  "tasks": [{{"id": "t1", "title": "...", "owner": "Name or null", "due_raw": "as stated or null", "quote": "exact transcript text"}}]
}}""")

    result = llm_call_with_retry(llm, [system_msg, user_msg], _ExtractionResult)

    # Build Decision objects
    decisions = []
    for rd in result.decisions:
        decisions.append(Decision(
            id=rd.id or str(uuid.uuid4()),
            text=rd.text,
            evidence=Evidence(quote=rd.quote),
        ))

    # Build TaskItem objects
    tasks = []
    for rt in result.tasks:
        resolved = resolve(rt.due_raw or "", meeting_date) if rt.due_raw else None
        tasks.append(TaskItem(
            id=rt.id or str(uuid.uuid4()),
            title=rt.title,
            owner=rt.owner,
            due_raw=rt.due_raw,
            due_date=resolved.date if resolved else None,
            evidence=Evidence(quote=rt.quote),
            status="valid",  # Validator will overwrite
        ))

    log_entry = make_log(
        meeting_id=meeting_id,
        actor="extractor",
        event="extraction_complete",
        ref_type="meeting",
        ref_id=str(meeting_id),
        detail={"decisions": len(decisions), "tasks": len(tasks), "retry": retries},
    )

    return {
        "segments": segments,
        "decisions": decisions,
        "tasks": tasks,
        "log": [log_entry],
    }
