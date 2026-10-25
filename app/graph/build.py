"""Build and compile the LangGraph agent graph."""
from __future__ import annotations

import os
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.approval import approval
from app.graph.nodes.clarify import clarify
from app.graph.nodes.executor import executor
from app.graph.nodes.extractor import extractor
from app.graph.nodes.planner import planner
from app.graph.nodes.validator import route_after_validator, validator
from app.graph.state import AgentState


def _re_extract_node(state: AgentState) -> dict:
    """Increment retry counter, then run extractor."""
    from app.graph.nodes.extractor import extractor as _ext
    retries = state.get("retries", 0) + 1
    result = _ext({**state, "retries": retries})
    return {**result, "retries": retries}


def build_graph():
    """Build and compile the agent graph with SqliteSaver checkpointer."""
    data_dir = os.getenv("DATA_DIR", "data/")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    checkpoints_db = str(Path(data_dir) / "checkpoints.db")

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        checkpointer = SqliteSaver.from_conn_string(checkpoints_db)
    except Exception:
        # Fallback for environments where SqliteSaver isn't available
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("extractor", extractor)
    graph.add_node("validator", validator)
    graph.add_node("re_extract", _re_extract_node)
    graph.add_node("clarify", clarify)
    graph.add_node("planner", planner)
    graph.add_node("approval", approval)
    graph.add_node("executor", executor)

    # Edges
    graph.add_edge(START, "extractor")
    graph.add_edge("extractor", "validator")
    graph.add_edge("re_extract", "validator")

    # Conditional routing after validator
    graph.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "re_extract": "re_extract",
            "clarify": "clarify",
            "plan": "planner",
        },
    )

    graph.add_edge("clarify", "validator")
    graph.add_edge("planner", "approval")
    graph.add_edge("approval", "executor")
    graph.add_edge("executor", END)

    return graph.compile(checkpointer=checkpointer)


# Singleton
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
