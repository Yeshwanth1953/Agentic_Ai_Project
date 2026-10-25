"""Planner node — converts validated items into ProposedActions."""
from __future__ import annotations

from typing import Any

from app.graph.state import AgentState, LogEntry, ProposedAction
from app.logging import make_log
from app.tools import calendar_mock


def planner(state: AgentState) -> dict[str, Any]:
    from app.db.connection import get_db
    conn = get_db()

    meeting_id = state["meeting_id"]
    meeting_date = state["meeting_date"]
    actions: list[ProposedAction] = []
    log_entries: list[LogEntry] = []

    # 1. create_task for each valid task
    for task in state.get("tasks", []):
        if task.status != "valid":
            continue

        action = ProposedAction(
            type="create_task",
            source_item_ids=[task.id],
            payload={
                "title": task.title,
                "owner_name": task.owner,
                "due_raw": task.due_raw,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "meeting_id": meeting_id,
                "quote": task.evidence.quote,
                "speaker": task.evidence.speaker,
                "start_ts": task.evidence.start_ts,
            },
        )
        actions.append(action)

        # Draft email if there's an owner
        if task.owner:
            email_action = ProposedAction(
                type="draft_email",
                source_item_ids=[task.id],
                payload={
                    "to": [task.owner],
                    "subject": f"Action item from meeting: {state.get('title', 'Meeting')}",
                    "body": (
                        f"Hi {task.owner},\n\n"
                        f"This is a follow-up from our meeting on {meeting_date}.\n\n"
                        f"You have an action item:\n"
                        f"  **{task.title}**\n"
                        + (f"  Due: {task.due_date}\n" if task.due_date else "")
                        + f"\nContext: \"{task.evidence.quote}\"\n\n"
                        "Please let us know if you have any questions.\n\nThanks"
                    ),
                    "meeting_id": meeting_id,
                },
            )
            actions.append(email_action)

    # 2. record_decision for each decision
    for dec in state.get("decisions", []):
        action = ProposedAction(
            type="record_decision",
            source_item_ids=[dec.id],
            payload={
                "text": dec.text,
                "quote": dec.evidence.quote,
                "speaker": dec.evidence.speaker,
                "start_ts": dec.evidence.start_ts,
                "meeting_id": meeting_id,
            },
        )
        actions.append(action)

    # 3. Optionally propose create_event for tasks that mention a meeting/sync
    tasks_needing_sync = [
        t for t in state.get("tasks", [])
        if t.status == "valid" and _mentions_meeting(t.title)
    ]
    if tasks_needing_sync:
        attendees = state.get("attendees", [])
        warnings: list[str] = []
        if attendees and tasks_needing_sync[0].due_date:
            start_at = f"{tasks_needing_sync[0].due_date}T10:00:00"
            end_at = f"{tasks_needing_sync[0].due_date}T11:00:00"
            busy = calendar_mock.check_availability(attendees, start_at, end_at, conn)
            if busy:
                warnings.append(f"Some attendees busy at {start_at}; consider rescheduling.")

        event_action = ProposedAction(
            type="create_event",
            source_item_ids=[t.id for t in tasks_needing_sync],
            payload={
                "title": f"Follow-up: {state.get('title', 'Meeting')}",
                "attendees": attendees,
                "start_at": f"{tasks_needing_sync[0].due_date}T10:00:00" if tasks_needing_sync[0].due_date else "",
                "end_at": f"{tasks_needing_sync[0].due_date}T11:00:00" if tasks_needing_sync[0].due_date else "",
                "agenda": "; ".join(t.title for t in tasks_needing_sync),
                "meeting_id": meeting_id,
            },
            warnings=warnings,
        )
        actions.append(event_action)

    log_entries.append(make_log(
        meeting_id=meeting_id,
        actor="planner",
        event="plan_created",
        detail={"action_count": len(actions)},
    ))

    return {"actions": actions, "log": log_entries}


def _mentions_meeting(title: str) -> bool:
    kw = {"sync", "meeting", "call", "review", "check-in", "checkin", "standup"}
    return any(k in title.lower() for k in kw)
