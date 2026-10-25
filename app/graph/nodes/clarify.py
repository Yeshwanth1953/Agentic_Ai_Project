"""Clarify node — interrupt for human clarification of unresolvable items."""
from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.graph.state import AgentState, Answer, LogEntry, Question, TaskItem
from app.logging import make_log
from app.tools.date_resolver import resolve


def clarify(state: AgentState) -> dict[str, Any]:
    meeting_id = state["meeting_id"]
    meeting_date = state["meeting_date"]
    tasks = state.get("tasks", [])

    # Build questions from items that need clarification
    questions: list[Question] = []
    for task in tasks:
        if task.status not in ("needs_clarification", "duplicate"):
            continue
        for problem in task.problems:
            q = _make_question(task, problem)
            if q:
                questions.append(q)

    log_entry = make_log(
        meeting_id=meeting_id,
        actor="validator",
        event="clarification_requested",
        detail={"question_count": len(questions)},
    )

    # Interrupt — pause graph and hand questions to user
    answers_raw: list[dict] = interrupt({"questions": [q.model_dump() for q in questions]})

    # Convert resume payload to Answer objects
    answers = [Answer(**a) if isinstance(a, dict) else a for a in (answers_raw or [])]

    # Build a lookup: question_id → answer value
    answer_map = {a.question_id: a.value for a in answers}

    # Build question → task/problem mapping
    q_to_task: dict[str, tuple[str, str]] = {}  # question_id → (task_id, problem_code)
    for q in questions:
        q_to_task[q.id] = (q.item_id, q.code)

    # Merge answers into tasks
    updated_tasks: list[TaskItem] = []
    for task in tasks:
        if task.status not in ("needs_clarification", "duplicate"):
            updated_tasks.append(task)
            continue

        resolved_problems = []
        for problem in task.problems:
            q_id = _find_question_id(questions, task.id, problem.code)
            if q_id and q_id in answer_map:
                value = answer_map[q_id].strip()
                if problem.code in ("MISSING_OWNER", "UNKNOWN_OWNER", "AMBIGUOUS_OWNER"):
                    task.owner = value if value.lower() not in ("", "unknown", "none") else None
                elif problem.code in ("MISSING_DEADLINE", "VAGUE_DEADLINE", "PAST_DEADLINE"):
                    task.due_raw = value
                    resolved = resolve(value, meeting_date)
                    task.due_date = resolved.date
                elif problem.code == "DUPLICATE":
                    if value.lower() in ("skip", "duplicate"):
                        task.status = "duplicate"
                    else:
                        task.duplicate_of = None
                # Problem considered resolved
            else:
                resolved_problems.append(problem)

        task.problems = resolved_problems
        if not resolved_problems and task.status != "duplicate":
            task.status = "valid"
        updated_tasks.append(task)

    log_after = make_log(
        meeting_id=meeting_id,
        actor="user",
        event="clarification_answered",
        detail={"answers": len(answers)},
    )

    return {
        "tasks": updated_tasks,
        "questions": questions,
        "answers": answers,
        "log": [log_entry, log_after],
    }


def _make_question(task: TaskItem, problem: Any) -> Question | None:
    if problem.code == "MISSING_OWNER":
        return Question(
            item_id=task.id,
            code=problem.code,
            text=f"Who is responsible for: \"{task.title}\"?",
            kind="text",
        )
    if problem.code in ("UNKNOWN_OWNER", "AMBIGUOUS_OWNER"):
        return Question(
            item_id=task.id,
            code=problem.code,
            text=f"Clarify owner for task \"{task.title}\": {problem.message}. Please provide the correct name.",
            kind="text",
        )
    if problem.code in ("MISSING_DEADLINE", "VAGUE_DEADLINE"):
        return Question(
            item_id=task.id,
            code=problem.code,
            text=f"What is the deadline for \"{task.title}\"? (Original: \"{task.due_raw or 'not stated'}\")",
            kind="date",
        )
    if problem.code == "PAST_DEADLINE":
        return Question(
            item_id=task.id,
            code=problem.code,
            text=f"The deadline \"{task.due_raw}\" for \"{task.title}\" appears to be in the past. Please confirm the correct date.",
            kind="date",
        )
    if problem.code == "DUPLICATE":
        return Question(
            item_id=task.id,
            code=problem.code,
            text=f"Task \"{task.title}\" may be a duplicate of an existing task. Skip it (type 'skip') or keep both (type 'keep')?",
            kind="choice",
            options=["skip", "keep"],
        )
    return None


def _find_question_id(questions: list[Question], task_id: str, code: str) -> str | None:
    for q in questions:
        if q.item_id == task_id and q.code == code:
            return q.id
    return None
