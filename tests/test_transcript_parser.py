"""Unit tests for transcript_parser."""
import pytest

from app.tools.transcript_parser import ground_quote, parse


def test_plain_parse_two_speakers():
    text = "Alice: Let's plan the sprint.\nBob: I'll handle the API."
    segs = parse(text)
    assert len(segs) == 2
    assert segs[0]["speaker"] == "Alice"
    assert segs[1]["speaker"] == "Bob"
    assert "Let's plan the sprint." in segs[0]["text"]


def test_stop_label_continues_turn():
    text = "Alice: We need to ship by Friday.\nNote: This was discussed earlier.\nBob: Agreed."
    segs = parse(text)
    # "Note:" should continue Alice's turn, not start a new segment
    assert len(segs) == 2
    assert segs[0]["speaker"] == "Alice"
    assert "This was discussed earlier." in segs[0]["text"]
    assert segs[1]["speaker"] == "Bob"


def test_timestamped_format():
    text = "[10:00] Alice: Good morning everyone.\n[10:01] Bob: Let's get started."
    segs = parse(text)
    assert len(segs) == 2
    assert segs[0]["start_ts"] == "10:00"
    assert segs[1]["speaker"] == "Bob"


def test_fallback_single_segment():
    text = "This is a meeting transcript without any speaker labels."
    segs = parse(text)
    assert len(segs) == 1
    assert segs[0]["speaker"] == "Unknown"


def test_ground_quote_exact_match():
    segs = parse("Alice: Can you send the report by Friday?\nBob: Sure, I'll do it.")
    result = ground_quote("Can you send the report by Friday?", segs)
    assert result is not None
    assert result["speaker"] == "Alice"


def test_ground_quote_whitespace_normalized():
    segs = parse("Alice: Can you   send the report by  Friday?")
    # quote with extra spaces should still match
    result = ground_quote("Can you send the report by Friday?", segs)
    assert result is not None


def test_ground_quote_no_match():
    segs = parse("Alice: Hello everyone.")
    result = ground_quote("This text does not exist in transcript", segs)
    assert result is None


def test_ground_quote_case_sensitive():
    segs = parse("Alice: Hello World.")
    # Case-sensitive: lowercase won't match
    result = ground_quote("hello world.", segs)
    assert result is None


def test_vtt_format():
    text = """WEBVTT

00:00:01.000 --> 00:00:05.000
Alice: We need to finalize the API design.

00:00:06.000 --> 00:00:10.000
Bob: I agree, let's do it by Friday.
"""
    segs = parse(text)
    assert len(segs) == 2
    assert segs[0]["speaker"] == "Alice"
    assert segs[1]["speaker"] == "Bob"


def test_multiple_stop_labels():
    text = "Alice: Let's review the metrics.\nAction item: Review Q3 data.\nDecision: We will use the new dashboard.\nBob: Sounds good."
    segs = parse(text)
    assert len(segs) == 2
    assert segs[0]["speaker"] == "Alice"
    assert "Review Q3 data." in segs[0]["text"]
    assert "We will use the new dashboard." in segs[0]["text"]
