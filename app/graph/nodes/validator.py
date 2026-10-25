"""Validator node — deterministic checks + duplicate detection."""
from __future__ import annotations

import re
from typing import Any

from app.graph.state import AgentState, Decision, LogEntry, Problem, TaskItem
from app.logging import make_log
from app.tools.task_db import find_similar, resolve_person
from app.tools.transcript_parser import ground_quote

FIXABLE_CODES = {"NO_QUOTE"}
VAGUE_PHRASES = {
    "soon", "asap", "as soon as possible", "later", "eventually", "sometime",
    "next week sometime", "sometime next week", "next week", "this week",
    "at some point", "when possible", "whenever", "tbd", "next month",
    "later this month",
}


def validator(state: AgentState) -> dict[str, Any]:
    from app.db.connection import get_db
    conn = get_db()

    meeting_id = state["meeting_id"]
    meeting_date = state["meeting_date"]
    segments = state.get("segments", [])
    attendees = state.get("attendees", [])
    retries = state.get("retries", 0)

    validated_tasks: list[TaskItem] = []
    log_entries: list[LogEntry] = []

    # Collect all speaker names from segments
    speakers = list({s["speaker"] for s in segments if s["speaker"] != "Unknown"})

    for task in state.get("tasks", []):
        problems: list[Problem] = []
        new_status = "valid"

        # 1. NO_QUOTE
        seg = ground_quote(task.evidence.quote, segments)
        if not task.evidence.quote.strip() or seg is None:
            problems.append(Problem(code="NO_QUOTE", message="Quote not found verbatim in transcript", field="evidence.quote"))
        else:
            # Enrich evidence with speaker + ts from matched segment
            task.evidence.speaker = seg["speaker"]
            task.evidence.start_ts = seg.get("start_ts")

        # 2. OWNER checks (only if no NO_QUOTE fixable problem)
        if not any(p.code == "NO_QUOTE" for p in problems):
            if task.owner:
                count, resolved_name = resolve_person(task.owner, conn)
                if count == 0:
                    # Q21 tie-break: if name matches a speaker or attendee exactly, use it
                    if _matches_attendee_or_speaker(task.owner, attendees, speakers):
                        task.owner = task.owner  # keep as-is
                    else:
                        problems.append(Problem(code="UNKNOWN_OWNER", message=f"Owner '{task.owner}' not found in people/attendees/speakers", field="owner"))
                elif count >= 2:
                    # Q21: if exactly one match is attendee/speaker, use that one
                    if _matches_attendee_or_speaker(task.owner, attendees, speakers):
                        # keep and resolve to the attendee/speaker match
                        pass
                    else:
                        problems.append(Problem(code="AMBIGUOUS_OWNER", message=f"Owner '{task.owner}' matches multiple people", field="owner"))
                else:
                    task.owner = resolved_name
            else:
                # Check if transcript implies an owner
                if not _has_explicit_owner_in_quote(task.evidence.quote, attendees + speakers):
                    problems.append(Problem(code="MISSING_OWNER", message="No owner stated in transcript", field="owner"))

        # 3. DEADLINE checks
        if not any(p.code == "NO_QUOTE" for p in problems):
            if task.due_raw:
                if _is_vague(task.due_raw):
                    problems.append(Problem(code="VAGUE_DEADLINE", message=f"Deadline '{task.due_raw}' is vague", field="due_raw"))
                elif task.due_date and task.due_date < meeting_date:
                    problems.append(Problem(code="PAST_DEADLINE", message=f"Deadline {task.due_date} is before meeting date {meeting_date}", field="due_date"))
            else:
                problems.append(Problem(code="MISSING_DEADLINE", message="No deadline stated", field="due_date"))

            # 4. DUPLICATE check
            if not problems:
                similar = find_similar(task.title, task.owner, conn)
                if similar:
                    best = similar[0]
                    task.duplicate_of = best["id"]
                    problems.append(Problem(code="DUPLICATE", message=f"Possible duplicate of task #{best['id']}: {best['title']}", field="title"))

        # Determine final status
        if problems:
            fixable = all(p.code in FIXABLE_CODES for p in problems)
            if fixable:
                new_status = "fixable"
            else:
                new_status = "needs_clarification"

        task.problems = problems
        task.status = new_status
        validated_tasks.append(task)

    # Validate decisions (only NO_QUOTE check)
    validated_decisions: list[Decision] = []
    for dec in state.get("decisions", []):
        seg = ground_quote(dec.evidence.quote, segments)
        if not dec.evidence.quote.strip() or seg is None:
            # Drop decision with log entry, after re-extract cap
            if retries >= 2:
                log_entries.append(make_log(
                    meeting_id=meeting_id,
                    actor="validator",
                    event="decision_dropped_no_quote",
                    ref_type="decision",
                    ref_id=dec.id,
                    detail={"text": dec.text},
                ))
            else:
                validated_decisions.append(dec)  # keep for re-extract
        else:
            dec.evidence.speaker = seg["speaker"]
            dec.evidence.start_ts = seg.get("start_ts")
            validated_decisions.append(dec)

    log_entries.append(make_log(
        meeting_id=meeting_id,
        actor="validator",
        event="validation_complete",
        detail={
            "valid": sum(1 for t in validated_tasks if t.status == "valid"),
            "fixable": sum(1 for t in validated_tasks if t.status == "fixable"),
            "needs_clarification": sum(1 for t in validated_tasks if t.status == "needs_clarification"),
        },
    ))

    return {
        "tasks": validated_tasks,
        "decisions": validated_decisions,
        "log": log_entries,
    }


def route_after_validator(state: AgentState) -> str:
    tasks = state.get("tasks", [])
    retries = state.get("retries", 0)

    has_fixable = any(t.status == "fixable" for t in tasks)
    has_unclear = any(t.status in ("needs_clarification", "duplicate") for t in tasks)

    if has_fixable and retries < 2:
        return "re_extract"
    if has_unclear:
        return "clarify"
    return "plan"


def _is_vague(phrase: str) -> bool:
    return phrase.strip().lower() in VAGUE_PHRASES


def _has_explicit_owner_in_quote(quote: str, names: list[str]) -> bool:
    """Check if quote contains a first-person commitment or a direct addressee."""
    q_lower = quote.lower()
    # first-person commitment
    if re.search(r"\bi('ll|'m| will| am going to)\b", q_lower):
        return True
    # direct address "Name, can you" or "Name please"
    for name in names:
        if re.search(rf"\b{re.escape(name.split()[0].lower())}\b", q_lower):
            return True
    return False


def _matches_attendee_or_speaker(name: str, attendees: list[str], speakers: list[str]) -> bool:
    norm = name.lower().strip()
    for n in attendees + speakers:
        if n.lower().strip() == norm or n.lower().split()[0] == norm.split()[0]:
            return True
    return False
