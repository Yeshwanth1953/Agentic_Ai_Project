"""Eval harness: compare agent output against ground-truth labels."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
LABELS_DIR = Path(__file__).parent / "labels"


def load_labels(name: str) -> dict:
    path = LABELS_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def run_eval(transcript_name: str, agent_output: dict) -> dict:
    """Compare agent output dict against ground truth labels.

    agent_output expected shape:
    {
      "tasks": [{"title": ..., "owner": ..., "due_date": ...}],
      "decisions": [{"text": ...}]
    }
    """
    labels = load_labels(transcript_name)
    from eval.metrics import precision_recall_f1, title_match

    label_tasks = labels.get("tasks", [])
    pred_tasks = agent_output.get("tasks", [])

    label_decisions = labels.get("decisions", [])
    pred_decisions = agent_output.get("decisions", [])

    task_metrics = precision_recall_f1(label_tasks, pred_tasks, title_match)
    decision_metrics = precision_recall_f1(label_decisions, pred_decisions,
                                           lambda a, b: title_match(a, b, key="text"))

    return {
        "transcript": transcript_name,
        "tasks": task_metrics,
        "decisions": decision_metrics,
    }


def main():
    # Stub: print label counts for each transcript
    for label_file in sorted(LABELS_DIR.glob("*.json")):
        labels = json.loads(label_file.read_text())
        name = label_file.stem
        print(f"\n=== {name} ===")
        print(f"  Tasks:     {len(labels.get('tasks', []))}")
        print(f"  Decisions: {len(labels.get('decisions', []))}")
        print(f"  Edge cases: {len(labels.get('edge_cases_planted', []))}")
        for ec in labels.get("edge_cases_planted", []):
            print(f"    - {ec}")

    print("\n[run.py] To run a full eval, call run_eval(transcript_name, agent_output).")
    print("[run.py] agent_output should come from the API: GET /meetings/{id}/results")


if __name__ == "__main__":
    main()
