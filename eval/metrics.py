"""Eval metrics for task and decision extraction quality."""
from __future__ import annotations
import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def title_match(label: dict, pred: dict, key: str = "title", threshold: float = 0.5) -> bool:
    """Jaccard similarity on normalized word sets."""
    a = set(_norm(label.get(key, "")).split())
    b = set(_norm(pred.get(key, "")).split())
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold


def precision_recall_f1(
    labels: list[dict],
    preds: list[dict],
    match_fn,
) -> dict:
    """Compute P/R/F1 given a binary match function."""
    tp = 0
    matched_labels = set()

    for pred in preds:
        for i, label in enumerate(labels):
            if i not in matched_labels and match_fn(label, pred):
                tp += 1
                matched_labels.add(i)
                break

    precision = tp / len(preds) if preds else 0.0
    recall = tp / len(labels) if labels else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "true_positives": tp,
        "false_positives": len(preds) - tp,
        "false_negatives": len(labels) - tp,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def owner_accuracy(labels: list[dict], preds: list[dict], match_fn) -> float:
    """Among matched task pairs, fraction with correct owner."""
    correct = 0
    matched = 0
    for pred in preds:
        for label in labels:
            if match_fn(label, pred):
                matched += 1
                if _norm(label.get("owner") or "") == _norm(pred.get("owner") or ""):
                    correct += 1
                break
    return round(correct / matched, 3) if matched else 0.0


def due_date_accuracy(labels: list[dict], preds: list[dict], match_fn) -> float:
    """Among matched task pairs, fraction with correct due_date."""
    correct = 0
    matched = 0
    for pred in preds:
        for label in labels:
            if match_fn(label, pred):
                matched += 1
                if label.get("due_date") == pred.get("due_date"):
                    correct += 1
                break
    return round(correct / matched, 3) if matched else 0.0
