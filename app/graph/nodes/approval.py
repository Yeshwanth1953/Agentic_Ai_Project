"""Approval node — interrupt for human approve/edit/reject of each action."""
from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.graph.state import AgentState, LogEntry, ProposedAction
from app.logging import make_log


def approval(state: AgentState) -> dict[str, Any]:
    meeting_id = state["meeting_id"]
    actions = state.get("actions", [])

    log_entry = make_log(
        meeting_id=meeting_id,
        actor="planner",
        event="awaiting_approval",
        detail={"action_count": len(actions)},
    )

    # Interrupt — pause and send plan to user
    decisions_raw: list[dict] = interrupt({
        "actions": [a.model_dump() for a in actions]
    })

    # Process user decisions
    updated_actions: list[ProposedAction] = list(actions)
    decision_map = {d["action_id"]: d for d in (decisions_raw or [])}

    for i, action in enumerate(updated_actions):
        if action.id in decision_map:
            d = decision_map[action.id]
            action.decision = d.get("decision", "pending")
            # Apply edits to payload if provided
            if d.get("edits") and action.decision == "edit":
                action.payload = {**action.payload, **d["edits"]}

    log_after = make_log(
        meeting_id=meeting_id,
        actor="user",
        event="approval_submitted",
        detail={
            "approved": sum(1 for a in updated_actions if a.decision == "approve"),
            "edited": sum(1 for a in updated_actions if a.decision == "edit"),
            "rejected": sum(1 for a in updated_actions if a.decision == "reject"),
        },
    )

    return {"actions": updated_actions, "log": [log_entry, log_after]}
