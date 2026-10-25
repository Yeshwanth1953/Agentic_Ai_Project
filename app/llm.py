"""LLM provider — Groq in production, FakeLLM for tests."""
from __future__ import annotations

import json
import os
from typing import Any, Type

from langchain_core.messages import HumanMessage
from pydantic import BaseModel


class FakeLLM:
    """Returns a fixed valid response for any prompt — used in tests."""

    def __init__(self, response: dict | None = None):
        self._response = response or {
            "decisions": [
                {
                    "id": "d1",
                    "text": "We will use Python 3.11 for the project.",
                    "quote": "We will use Python 3.11 for the project.",
                }
            ],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Set up the project repository",
                    "owner": "Alice",
                    "due_raw": "next Friday",
                    "quote": "Alice, can you set up the project repository by next Friday?",
                }
            ],
        }

    def with_structured_output(self, schema: Type[BaseModel], **kwargs: Any) -> "FakeLLMBound":
        return FakeLLMBound(self._response, schema)

    def invoke(self, messages: Any) -> Any:
        class _Resp:
            content = json.dumps(self._response)
        return _Resp()


class FakeLLMBound:
    def __init__(self, response: dict, schema: Type[BaseModel]):
        self._response = response
        self._schema = schema

    def invoke(self, messages: Any) -> Any:
        return self._schema(**self._response)


def get_llm(fake: bool = False) -> Any:
    if fake or os.getenv("USE_FAKE_LLM"):
        return FakeLLM()
    from langchain_groq import ChatGroq  # type: ignore
    return ChatGroq(
        model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
    )


def llm_call_with_retry(
    llm: Any,
    messages: list,
    schema: Type[BaseModel],
    max_retries: int = 2,
) -> BaseModel:
    """Call LLM with structured output, retrying on parse failures."""
    from langchain_core.messages import HumanMessage

    bound = llm.with_structured_output(schema, method="json_mode")
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = bound.invoke(messages)
            if isinstance(result, dict):
                return schema(**result)
            return result
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                messages = messages + [
                    HumanMessage(
                        content=f"Your previous response caused a parse error: {exc}. "
                        "Please respond with valid JSON matching the required schema."
                    )
                ]

    raise RuntimeError(f"LLM failed after {max_retries + 1} attempts: {last_exc}") from last_exc
