"""LangGraph state schema — all Pydantic models and AgentState TypedDict."""
from __future__ import annotations

import operator
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field


class Problem(BaseModel):
    code: str
    message: str
    field: str = ""


class Evidence(BaseModel):
    quote: str
    speaker: str | None = None
    start_ts: str | None = None


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    evidence: Evidence


class TaskItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    owner: str | None = None
    due_raw: str | None = None
    due_date: date | None = None
    evidence: Evidence
    status: Literal["valid", "fixable", "needs_clarification", "duplicate", "dropped"] = "valid"
    problems: list[Problem] = Field(default_factory=list)
    duplicate_of: int | None = None


class ProposedAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["create_task", "create_event", "draft_email", "record_decision"]
    source_item_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    original_payload: dict[str, Any] = Field(default_factory=dict)
    decision: Literal["pending", "approve", "edit", "reject"] = "pending"
    execution_status: Literal["not_run", "executed", "failed", "skipped"] = "not_run"
    result: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    code: str
    text: str
    kind: Literal["date", "choice", "text"] = "text"
    options: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    question_id: str
    value: str


class LogEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: int
    ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    actor: Literal["system", "extractor", "validator", "planner", "user", "executor"]
    event: str
    ref_type: Literal["task", "decision", "action", "meeting"] | None = None
    ref_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


# TypedDict — used as LangGraph state
class Segment(TypedDict):
    idx: int
    speaker: str
    start_ts: str | None
    text: str


class AgentState(TypedDict):
    meeting_id: int
    meeting_date: date
    title: str
    attendees: list[str]
    transcript: str
    segments: list[Segment]
    decisions: list[Decision]
    tasks: list[TaskItem]
    questions: list[Question]
    answers: list[Answer]
    retries: int
    actions: list[ProposedAction]
    log: Annotated[list[LogEntry], operator.add]
