"""Pydantic schemas for FastAPI request/response bodies."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class UploadMeetingJson(BaseModel):
    transcript: str
    title: str = "Untitled Meeting"
    meeting_date: str = ""
    attendees: list[str] = []


class MeetingStatus(BaseModel):
    meeting_id: int
    status: str
    title: str
    counts: dict[str, int] = {}
    error: str | None = None


class AnswerItem(BaseModel):
    question_id: str
    value: str


class AnswersPayload(BaseModel):
    answers: list[AnswerItem]


class ActionDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    edits: dict[str, Any] | None = None


class BulkDecisionItem(BaseModel):
    action_id: str
    decision: Literal["approve", "edit", "reject"]
    edits: dict[str, Any] | None = None


class BulkDecisionPayload(BaseModel):
    decisions: list[BulkDecisionItem]


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "done", "cancelled"]
