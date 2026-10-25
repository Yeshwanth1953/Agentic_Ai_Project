"""Parse meeting transcripts into speaker-turn segments and ground quotes."""
from __future__ import annotations

import re
from typing import TypedDict

STOP_LABELS = {
    "Note", "Action item", "Decision", "Update",
    "Agenda", "TODO", "FYI", "Re",
}

VTT_TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}")
SRT_TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
TIMESTAMPED_TURN_RE = re.compile(r"^\[(\d{2}:\d{2}(?::\d{2})?)\]\s+(.+?):\s+(.+)$")
PLAIN_TURN_RE = re.compile(r"^([A-Za-z][A-Za-z\s]{0,40}?):\s+(.+)$")


class Segment(TypedDict):
    idx: int
    speaker: str
    start_ts: str | None
    text: str


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def parse(text: str, fmt: str = "auto") -> list[Segment]:
    if fmt == "auto":
        fmt = _detect_fmt(text)

    if fmt == "vtt":
        return _parse_vtt(text)
    if fmt == "srt":
        return _parse_srt(text)
    return _parse_plain(text)


def _detect_fmt(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("WEBVTT"):
        return "vtt"
    if SRT_TIMESTAMP_RE.search(stripped[:200]):
        return "srt"
    return "plain"


def _parse_plain(text: str) -> list[Segment]:
    segments: list[Segment] = []
    current: Segment | None = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        ts_match = TIMESTAMPED_TURN_RE.match(line)
        if ts_match:
            label = ts_match.group(2).strip()
            if label in STOP_LABELS:
                if current is not None:
                    current["text"] += " " + ts_match.group(3).strip()
                continue
            if current is not None:
                segments.append(current)
            current = Segment(
                idx=len(segments),
                speaker=label,
                start_ts=ts_match.group(1),
                text=ts_match.group(3).strip(),
            )
            continue

        plain_match = PLAIN_TURN_RE.match(line)
        if plain_match:
            label = plain_match.group(1).strip()
            if label in STOP_LABELS:
                if current is not None:
                    current["text"] += " " + plain_match.group(2).strip()
                continue
            if current is not None:
                segments.append(current)
            current = Segment(
                idx=len(segments),
                speaker=label,
                start_ts=None,
                text=plain_match.group(2).strip(),
            )
            continue

        # continuation line
        if current is not None:
            current["text"] += " " + line

    if current is not None:
        segments.append(current)

    if not segments:
        segments = [Segment(idx=0, speaker="Unknown", start_ts=None, text=text.strip())]

    for i, seg in enumerate(segments):
        seg["idx"] = i
        seg["text"] = _norm_ws(seg["text"])

    return segments


def _parse_vtt(text: str) -> list[Segment]:
    segments: list[Segment] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = VTT_TIMESTAMP_RE.match(lines[i].strip())
        if m:
            ts = m.group(1)
            i += 1
            speaker = "Unknown"
            content_lines = []
            while i < len(lines) and lines[i].strip():
                content_lines.append(lines[i].strip())
                i += 1
            content = " ".join(content_lines)
            # try to extract "<Speaker>: text"
            colon_match = re.match(r"^(.+?):\s+(.+)$", content)
            if colon_match:
                speaker = colon_match.group(1).strip()
                content = colon_match.group(2).strip()
            segments.append(Segment(
                idx=len(segments),
                speaker=speaker,
                start_ts=ts,
                text=_norm_ws(content),
            ))
        else:
            i += 1

    if not segments:
        segments = [Segment(idx=0, speaker="Unknown", start_ts=None, text=text.strip())]
    return segments


def _parse_srt(text: str) -> list[Segment]:
    segments: list[Segment] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        ts_line = None
        content_start = 0
        for j, line in enumerate(lines):
            if SRT_TIMESTAMP_RE.match(line):
                ts_match = SRT_TIMESTAMP_RE.match(line)
                ts = ts_match.group(1).replace(",", ".") if ts_match else None
                ts_line = ts
                content_start = j + 1
                break
        if ts_line is None:
            continue
        content = " ".join(lines[content_start:])
        speaker = "Unknown"
        colon_match = re.match(r"^(.+?):\s+(.+)$", content)
        if colon_match:
            speaker = colon_match.group(1).strip()
            content = colon_match.group(2).strip()
        segments.append(Segment(
            idx=len(segments),
            speaker=speaker,
            start_ts=ts_line,
            text=_norm_ws(content),
        ))
    if not segments:
        segments = [Segment(idx=0, speaker="Unknown", start_ts=None, text=text.strip())]
    return segments


def ground_quote(quote: str, segments: list[Segment]) -> Segment | None:
    """Return the segment that contains the quote as a verbatim substring (whitespace-normalized, case-sensitive)."""
    norm_q = _norm_ws(quote)
    if not norm_q:
        return None
    for seg in segments:
        if norm_q in _norm_ws(seg["text"]):
            return seg
    return None
