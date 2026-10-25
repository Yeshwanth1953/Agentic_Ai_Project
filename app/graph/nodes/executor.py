"""Executor node — the ONLY node that writes to external state. Only approved items."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.graph.state import AgentState, LogEntry, ProposedAction
from app.logging import make_log, persist_log_entries
from app.tools import calendar_mock, email_mock, task_db


def executor(state: AgentState) -> dict[str, Any]:
    from app.db.connection import get_db
    conn = get_db()

    meeting_id = state["meeting_id"]
    actions = state.get("actions", [])
    log_entries: list[LogEntry] = []

    updated_actions: list[ProposedAction] = []

    for action in actions:
        # CRITICAL: skip anything not explicitly approved or edited
        if action.decision not in ("approve", "edit"):
            if action.decision == "reject":
                action.execution_status = "skipped"
                log_entries.append(make_log(
                    meeting_id=meeting_id,
                    actor="executor",
                    event="action_skipped_rejected",
                    ref_type="action",
                    ref_id=action.id,
                    detail={"type": action.type},
                ))
            updated_actions.append(action)
            continue

        # Idempotency: skip already-executed
        if action.execution_status != "not_run":
            updated_actions.append(action)
            continue

        try:
            result = _execute_action(action, meeting_id, conn)
            action.execution_status = "executed"
            action.result = result
            action.payload["_executed_at"] = datetime.utcnow().isoformat()

            log_entries.append(make_log(
                meeting_id=meeting_id,
                actor="executor",
                event=f"action_executed_{action.type}",
                ref_type="action",
                ref_id=action.id,
                detail={"type": action.type, "result": result},
            ))

            # Sync to proposed_actions table
            conn.execute(
                """UPDATE proposed_actions
                   SET execution_status='executed', result=?, executed_at=?
                   WHERE id=?""",
                (json.dumps(result), datetime.utcnow().isoformat(), action.id),
            )
            conn.commit()

        except Exception as exc:
            action.execution_status = "failed"
            action.result = {"error": str(exc)}
            log_entries.append(make_log(
                meeting_id=meeting_id,
                actor="executor",
                event="action_failed",
                ref_type="action",
                ref_id=action.id,
                detail={"type": action.type, "error": str(exc)},
            ))

        updated_actions.append(action)

    log_entries.append(make_log(
        meeting_id=meeting_id,
        actor="executor",
        event="execution_complete",
        detail={
            "executed": sum(1 for a in updated_actions if a.execution_status == "executed"),
            "failed": sum(1 for a in updated_actions if a.execution_status == "failed"),
            "skipped": sum(1 for a in updated_actions if a.execution_status == "skipped"),
        },
    ))

    # Persist log immediately (not deferred — executor IS the writer)
    persist_log_entries(log_entries, conn)

    # Update meeting status to done
    conn.execute(
        "UPDATE meetings SET status='done', updated_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), meeting_id),
    )
    conn.commit()

    return {"actions": updated_actions, "log": log_entries}


def _execute_action(action: ProposedAction, meeting_id: int, conn: Any) -> dict:
    p = action.payload

    if action.type == "create_task":
        task_id = task_db.insert_task(
            {
                "meeting_id": p.get("meeting_id", meeting_id),
                "title": p["title"],
                "owner_name": p.get("owner_name"),
                "due_raw": p.get("due_raw"),
                "due_date": p.get("due_date"),
                "quote": p.get("quote"),
                "speaker": p.get("speaker"),
                "start_ts": p.get("start_ts"),
            },
            conn,
        )
        return {"task_id": task_id}

    if action.type == "create_event":
        event_id = calendar_mock.create_event(
            title=p["title"],
            attendees=p.get("attendees", []),
            start_at=p["start_at"],
            end_at=p["end_at"],
            agenda=p.get("agenda"),
            meeting_id=p.get("meeting_id", meeting_id),
            conn=conn,
        )
        return {"event_id": event_id}

    if action.type == "draft_email":
        draft_id = email_mock.draft(
            meeting_id=p.get("meeting_id", meeting_id),
            to_addrs=p.get("to", []),
            subject=p["subject"],
            body=p["body"],
            conn=conn,
        )
        email_mock.send(draft_id, conn)
        return {"email_id": draft_id, "status": "sent"}

    if action.type == "record_decision":
        cur = conn.execute(
            """INSERT INTO decisions (meeting_id, text, quote, speaker, start_ts)
               VALUES (?,?,?,?,?)""",
            (
                p.get("meeting_id", meeting_id),
                p["text"],
                p.get("quote"),
                p.get("speaker"),
                p.get("start_ts"),
            ),
        )
        conn.commit()
        return {"decision_id": cur.lastrowid}

    raise ValueError(f"Unknown action type: {action.type}")
