"""Unit tests for date_resolver."""
from datetime import date

import pytest

from app.tools.date_resolver import resolve

TUE = date(2026, 10, 13)  # Tuesday
SAT = date(2026, 10, 17)  # Saturday


def test_friday_from_tuesday():
    r = resolve("friday", TUE)
    assert r.date == date(2026, 10, 16)


def test_this_friday_from_tuesday():
    r = resolve("this friday", TUE)
    assert r.date == date(2026, 10, 16)


def test_next_friday_from_tuesday():
    r = resolve("next friday", TUE)
    assert r.date == date(2026, 10, 23)


def test_next_monday_from_tuesday():
    r = resolve("next monday", TUE)
    assert r.date == date(2026, 10, 19)


def test_friday_from_saturday():
    r = resolve("friday", SAT)
    assert r.date == date(2026, 10, 23)


def test_by_the_weekend_from_tuesday():
    r = resolve("by the weekend", TUE)
    assert r.date == date(2026, 10, 16)


def test_by_the_weekend_from_saturday():
    r = resolve("by the weekend", SAT)
    assert r.date == date(2026, 10, 23)


def test_soon_is_vague():
    r = resolve("soon", TUE)
    assert r.date is None
    assert r.kind == "vague"


def test_asap_is_vague():
    r = resolve("asap", TUE)
    assert r.date is None


def test_abbreviated_weekday_returns_none():
    r = resolve("fri", TUE)
    assert r.date is None


def test_today():
    r = resolve("today", TUE)
    assert r.date == TUE


def test_tomorrow():
    r = resolve("tomorrow", TUE)
    assert r.date == date(2026, 10, 14)


def test_in_3_days():
    r = resolve("in 3 days", TUE)
    assert r.date == date(2026, 10, 16)


def test_iso_date():
    r = resolve("2026-11-01", TUE)
    assert r.date == date(2026, 11, 1)


def test_past_iso_returned_as_is():
    r = resolve("2025-01-01", TUE)
    assert r.date == date(2025, 1, 1)
    assert r.kind == "absolute"


def test_end_of_month():
    r = resolve("end of month", TUE)
    assert r.date == date(2026, 10, 31)


def test_end_of_week_is_vague():
    r = resolve("end of week", TUE)
    assert r.date is None


def test_empty_phrase():
    r = resolve("", TUE)
    assert r.date is None
    assert r.kind == "empty"


def test_by_prefix_stripped():
    r = resolve("by next friday", TUE)
    assert r.date == date(2026, 10, 23)
