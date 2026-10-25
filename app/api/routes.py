"""FastAPI route handlers."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.schemas import (
    ActionDecision,
    AnswersPayload,
    BulkDecisionPayload,
    MeetingStatus,
    TaskUpdate,
    UploadMeetingJson,
)
from app.db.connection import get_db
from app.graph.state import AgentState

router = APIRouter()

# In-memory set of running graph tasks (meeting_id)
_running: set[int] = set()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok"}


# ── Meetings ──────────────────────────────────────────────────────────────────

@router.post("/meetings", status_code=202)
async def create_meeting(
    background_tasks: BackgroundTasks,
    request: Request,
):
    content_type = request.headers.get("content-type", "")
    conn = get_db()
    now = datetime.utcnow().isoformat()

    if "multipart" in content_type:
        form = await request.form()
        file: UploadFile = form.get("file")
        if not file:
            raise HTTPException(400, "No file uploaded")
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ("txt", "vtt", "srt"):
            raise HTTPException(400, "File must be .txt, .vtt, or .srt")
        transcript = (await file.read()).decode("utf-8", errors="replace")
        title = str(form.get("title", "Untitled Meeting"))
        meeting_date = str(form.get("meeting_date", date.today().isoformat()))
        attendees_raw = str(form.get("attendees", ""))
        attendees = [a.strip() for a in attendees_raw.split(",") if a.strip()]
    else:
        body = UploadMeetingJson(**(await request.json()))
        transcript = body.transcript
        title = body.title
        meeting_date = body.meeting_date or date.today().isoformat()
        attendees = body.attendees

    cur = conn.execute(
        "INSERT INTO meetings (title, meeting_date, attendees, transcript, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (title, meeting_date, json.dumps(attendees), transcript, "processing", now, now),
    )
    conn.commit()
    meeting_id = cur.lastrowid

    # Write initial log
    conn.execute(
        "INSERT INTO action_log (meeting_id, actor, event, ref_type, ref_id, detail) VALUES (?,?,?,?,?,?)",
        (meeting_id, "system", "meeting_created", "meeting", str(meeting_id), json.dumps({"title": title})),
    )
    conn.commit()

    background_tasks.add_task(_run_graph, meeting_id, title, meeting_date, attendees, transcript)
    return {"meeting_id": meeting_id, "status": "processing"}


async def _run_graph(
    meeting_id: int,
    title: str,
    meeting_date: str,
    attendees: list[str],
    transcript: str,
):
    from app.graph.build import get_graph
    from app.logging import persist_log_entries
    conn = get_db()

    _running.add(meeting_id)
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": str(meeting_id)}}

        initial_state: AgentState = {
            "meeting_id": meeting_id,
            "meeting_date": date.fromisoformat(meeting_date),
            "title": title,
            "attendees": attendees,
            "transcript": transcript,
            "segments": [],
            "decisions": [],
            "tasks": [],
            "questions": [],
            "answers": [],
            "retries": 0,
            "actions": [],
            "log": [],
        }

        # Run until interrupt or completion
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _invoke_graph(graph, initial_state, config)
        )

        if result.get("interrupted"):
            interrupt_data = result["interrupt_data"]
            if "questions" in interrupt_data:
                _set_meeting_status(conn, meeting_id, "needs_clarification")
                _persist_questions(conn, meeting_id, interrupt_data["questions"])
            elif "actions" in interrupt_data:
                _set_meeting_status(conn, meeting_id, "awaiting_approval")
                _persist_actions(conn, meeting_id, interrupt_data["actions"])
        else:
            _set_meeting_status(conn, meeting_id, "done")

        # Persist any log entries from this graph run
        log_entries = result.get("log", [])
        if log_entries:
            persist_log_entries(log_entries, conn)

    except Exception as exc:
        conn.execute(
            "UPDATE meetings SET status='failed', error=?, updated_at=? WHERE id=?",
            (str(exc), datetime.utcnow().isoformat(), meeting_id),
        )
        conn.commit()
    finally:
        _running.discard(meeting_id)


def _invoke_graph(graph, initial_state, config):
    """Synchronously run the graph, returning interrupt data if hit."""
    from langgraph.errors import GraphInterrupt
    try:
        result = graph.invoke(initial_state, config)
        return {"log": result.get("log", [])}
    except GraphInterrupt as gi:
        # gi.value is the interrupt payload
        interrupt_data = gi.value[0].value if gi.value else {}
        return {"interrupted": True, "interrupt_data": interrupt_data, "log": []}


def _set_meeting_status(conn, meeting_id, status):
    conn.execute(
        "UPDATE meetings SET status=?, updated_at=? WHERE id=?",
        (status, datetime.utcnow().isoformat(), meeting_id),
    )
    conn.commit()


def _persist_questions(conn, meeting_id, questions):
    for q in questions:
        conn.execute(
            """INSERT OR REPLACE INTO action_log (meeting_id, actor, event, ref_type, ref_id, detail)
               VALUES (?,?,?,?,?,?)""",
            (meeting_id, "validator", "question_created", "meeting", str(meeting_id), json.dumps(q)),
        )
    conn.commit()


def _persist_actions(conn, meeting_id, actions):
    for a in actions:
        existing = conn.execute(
            "SELECT id FROM proposed_actions WHERE id=?", (a["id"],)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO proposed_actions (id, meeting_id, type, payload, original_payload, source_item_ids)
                   VALUES (?,?,?,?,?,?)""",
                (
                    a["id"],
                    meeting_id,
                    a["type"],
                    json.dumps(a.get("payload", {})),
                    json.dumps(a.get("payload", {})),
                    json.dumps(a.get("source_item_ids", [])),
                ),
            )
    conn.commit()


@router.get("/meetings")
def list_meetings():
    conn = get_db()
    rows = conn.execute("SELECT id, title, meeting_date, status, created_at FROM meetings ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Meeting not found")
    m = dict(row)
    m["attendees"] = json.loads(m.get("attendees") or "[]")
    counts = {
        "decisions": conn.execute("SELECT COUNT(*) FROM decisions WHERE meeting_id=?", (meeting_id,)).fetchone()[0],
        "tasks": conn.execute("SELECT COUNT(*) FROM tasks WHERE meeting_id=?", (meeting_id,)).fetchone()[0],
        "open_questions": _count_pending_questions(conn, meeting_id),
        "actions": conn.execute("SELECT COUNT(*) FROM proposed_actions WHERE meeting_id=?", (meeting_id,)).fetchone()[0],
    }
    return {**m, "counts": counts}


def _count_pending_questions(conn, meeting_id):
    rows = conn.execute(
        "SELECT detail FROM action_log WHERE meeting_id=? AND event='question_created'", (meeting_id,)
    ).fetchall()
    return len(rows)


@router.get("/meetings/{meeting_id}/items")
def get_items(meeting_id: int):
    conn = get_db()
    tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks WHERE meeting_id=?", (meeting_id,)).fetchall()]
    decisions = [dict(r) for r in conn.execute("SELECT * FROM decisions WHERE meeting_id=?", (meeting_id,)).fetchall()]
    return {"tasks": tasks, "decisions": decisions}


# ── Clarification ─────────────────────────────────────────────────────────────

@router.get("/meetings/{meeting_id}/questions")
def get_questions(meeting_id: int):
    conn = get_db()
    meeting = conn.execute("SELECT status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    rows = conn.execute(
        "SELECT detail FROM action_log WHERE meeting_id=? AND event='question_created' ORDER BY id",
        (meeting_id,),
    ).fetchall()
    questions = [json.loads(r["detail"]) for r in rows]
    return {"questions": questions}


@router.post("/meetings/{meeting_id}/answers", status_code=202)
async def submit_answers(meeting_id: int, body: AnswersPayload, background_tasks: BackgroundTasks):
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if meeting["status"] != "needs_clarification":
        raise HTTPException(409, f"Meeting is in status '{meeting['status']}', not 'needs_clarification'")

    answers = [a.model_dump() for a in body.answers]
    _set_meeting_status(conn, meeting_id, "processing")
    background_tasks.add_task(_resume_graph, meeting_id, answers)
    return {"status": "processing"}


async def _resume_graph(meeting_id: int, resume_payload: Any):
    from app.graph.build import get_graph
    conn = get_db()
    _running.add(meeting_id)
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": str(meeting_id)}}
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _invoke_graph_resume(graph, config, resume_payload),
        )
        if result.get("interrupted"):
            interrupt_data = result["interrupt_data"]
            if "questions" in interrupt_data:
                _set_meeting_status(conn, meeting_id, "needs_clarification")
                _persist_questions(conn, meeting_id, interrupt_data["questions"])
            elif "actions" in interrupt_data:
                _set_meeting_status(conn, meeting_id, "awaiting_approval")
                _persist_actions(conn, meeting_id, interrupt_data["actions"])
        else:
            _set_meeting_status(conn, meeting_id, "done")
    except Exception as exc:
        conn.execute(
            "UPDATE meetings SET status='failed', error=?, updated_at=? WHERE id=?",
            (str(exc), datetime.utcnow().isoformat(), meeting_id),
        )
        conn.commit()
    finally:
        _running.discard(meeting_id)


def _invoke_graph_resume(graph, config, resume_payload):
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Command
    try:
        result = graph.invoke(Command(resume=resume_payload), config)
        return {"log": result.get("log", [])}
    except GraphInterrupt as gi:
        interrupt_data = gi.value[0].value if gi.value else {}
        return {"interrupted": True, "interrupt_data": interrupt_data, "log": []}


# ── Plan / Approval ───────────────────────────────────────────────────────────

@router.get("/meetings/{meeting_id}/plan")
def get_plan(meeting_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM proposed_actions WHERE meeting_id=? ORDER BY rowid",
        (meeting_id,),
    ).fetchall()
    actions = []
    for r in rows:
        a = dict(r)
        a["payload"] = json.loads(a.get("payload") or "{}")
        a["source_item_ids"] = json.loads(a.get("source_item_ids") or "[]")
        actions.append(a)
    return {"actions": actions}


@router.post("/meetings/{meeting_id}/actions/{action_id}/decision")
def decide_action(meeting_id: int, action_id: str, body: ActionDecision):
    conn = get_db()
    meeting = conn.execute("SELECT status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if meeting["status"] != "awaiting_approval":
        raise HTTPException(409, f"Meeting is in status '{meeting['status']}', not 'awaiting_approval'")

    existing = conn.execute(
        "SELECT id FROM proposed_actions WHERE id=? AND meeting_id=?", (action_id, meeting_id)
    ).fetchone()
    if not existing:
        raise HTTPException(404, "Action not found")

    payload_update = ""
    params: list = [body.decision, datetime.utcnow().isoformat()]
    if body.edits and body.decision == "edit":
        # Merge edits into existing payload
        row = conn.execute("SELECT payload FROM proposed_actions WHERE id=?", (action_id,)).fetchone()
        current = json.loads(row["payload"] or "{}")
        current.update(body.edits)
        params = [body.decision, datetime.utcnow().isoformat(), json.dumps(current), action_id]
        conn.execute(
            "UPDATE proposed_actions SET decision=?, decided_at=?, payload=? WHERE id=?",
            params,
        )
    else:
        conn.execute(
            "UPDATE proposed_actions SET decision=?, decided_at=? WHERE id=?",
            [body.decision, datetime.utcnow().isoformat(), action_id],
        )
    conn.commit()
    return {"action_id": action_id, "decision": body.decision}


@router.post("/meetings/{meeting_id}/decisions")
def bulk_decide(meeting_id: int, body: BulkDecisionPayload):
    conn = get_db()
    for item in body.decisions:
        conn.execute(
            "UPDATE proposed_actions SET decision=?, decided_at=? WHERE id=? AND meeting_id=?",
            (item.decision, datetime.utcnow().isoformat(), item.action_id, meeting_id),
        )
    conn.commit()
    return {"updated": len(body.decisions)}


@router.post("/meetings/{meeting_id}/execute", status_code=202)
async def execute_plan(meeting_id: int, background_tasks: BackgroundTasks):
    conn = get_db()
    meeting = conn.execute("SELECT status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if meeting["status"] != "awaiting_approval":
        raise HTTPException(409, f"Meeting is in status '{meeting['status']}', expected 'awaiting_approval'")

    # Check for any pending (undecided) actions
    pending = conn.execute(
        "SELECT id FROM proposed_actions WHERE meeting_id=? AND decision='pending'", (meeting_id,)
    ).fetchall()
    if pending:
        raise HTTPException(422, {"detail": "Pending actions must be decided", "pending_ids": [r["id"] for r in pending]})

    # Build approval payload for graph resume
    rows = conn.execute("SELECT * FROM proposed_actions WHERE meeting_id=?", (meeting_id,)).fetchall()
    approval_payload = [
        {"action_id": r["id"], "decision": r["decision"], "edits": json.loads(r["payload"] or "{}")}
        for r in rows
    ]

    _set_meeting_status(conn, meeting_id, "executing")
    background_tasks.add_task(_resume_graph, meeting_id, approval_payload)
    return {"status": "executing"}


@router.get("/meetings/{meeting_id}/results")
def get_results(meeting_id: int):
    conn = get_db()
    rows = conn.execute("SELECT * FROM proposed_actions WHERE meeting_id=?", (meeting_id,)).fetchall()
    results = []
    for r in rows:
        a = dict(r)
        a["result"] = json.loads(a.get("result") or "null")
        results.append(a)
    return {"results": results}


@router.get("/meetings/{meeting_id}/log")
def get_log(meeting_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM action_log WHERE meeting_id=? ORDER BY ts, id", (meeting_id,)
    ).fetchall()
    entries = []
    for r in rows:
        e = dict(r)
        e["detail"] = json.loads(e.get("detail") or "{}")
        entries.append(e)
    return {"log": entries}


# ── Tasks tracker ─────────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(status: str | None = None, owner: str | None = None, meeting_id: int | None = None):
    conn = get_db()
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list = []
    if status:
        query += " AND status=?"
        params.append(status)
    if owner:
        query += " AND owner_name=?"
        params.append(owner)
    if meeting_id:
        query += " AND meeting_id=?"
        params.append(meeting_id)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate):
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
        (body.status, datetime.utcnow().isoformat(), task_id),
    )
    conn.commit()
    return {"task_id": task_id, "status": body.status}


# ── Calendar / Emails ─────────────────────────────────────────────────────────

@router.get("/calendar/events")
def list_events():
    conn = get_db()
    rows = conn.execute("SELECT * FROM calendar_events ORDER BY start_at").fetchall()
    return [dict(r) for r in rows]


@router.get("/emails")
def list_emails():
    conn = get_db()
    rows = conn.execute("SELECT * FROM emails ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        e = dict(r)
        e["to_addrs"] = json.loads(e.get("to_addrs") or "[]")
        result.append(e)
    return result
