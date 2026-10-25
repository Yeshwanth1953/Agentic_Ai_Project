"""Resolve natural-language date phrases to concrete dates deterministically."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Kind = Literal["relative", "absolute", "end_of_month", "weekday", "weekend", "vague", "unrecognized", "empty"]

VAGUE = {
    "soon", "asap", "as soon as possible", "later", "eventually", "sometime",
    "next week sometime", "sometime next week", "next week", "this week",
    "at some point", "when possible", "whenever", "tbd", "next month",
    "later this month",
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_LEADING = re.compile(r"^(by|on|for)\s+", re.IGNORECASE)
_TRAILING = re.compile(r"[.,;:!?]+$")
_IN_N_DAYS = re.compile(r"^in\s+(\d+)\s+days?$", re.IGNORECASE)


@dataclass
class ResolvedDate:
    date: date | None
    kind: Kind
    confident: bool


def resolve(phrase: str, ref_date: date) -> ResolvedDate:
    if not phrase or not phrase.strip():
        return ResolvedDate(date=None, kind="empty", confident=False)

    phrase = _norm(phrase)

    if phrase in VAGUE:
        return ResolvedDate(date=None, kind="vague", confident=False)

    # today / tomorrow
    if phrase == "today":
        return ResolvedDate(date=ref_date, kind="relative", confident=True)
    if phrase == "tomorrow":
        return ResolvedDate(date=ref_date + timedelta(days=1), kind="relative", confident=True)

    # ISO date
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})$", phrase)
    if iso_match:
        try:
            d = date.fromisoformat(iso_match.group(1))
            return ResolvedDate(date=d, kind="absolute", confident=True)
        except ValueError:
            return ResolvedDate(date=None, kind="unrecognized", confident=False)

    # "in N days"
    in_days = _IN_N_DAYS.match(phrase)
    if in_days:
        n = int(in_days.group(1))
        return ResolvedDate(date=ref_date + timedelta(days=n), kind="relative", confident=True)

    # end of month
    if phrase == "end of month":
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        return ResolvedDate(date=ref_date.replace(day=last_day), kind="end_of_month", confident=True)

    # "end of week" → None (vague per spec)
    if phrase == "end of week":
        return ResolvedDate(date=None, kind="vague", confident=False)

    # weekend phrases
    if phrase in ("by the weekend", "by this weekend"):
        friday = _this_friday(ref_date)
        return ResolvedDate(date=friday, kind="weekend", confident=True)
    if phrase == "by next weekend":
        friday = _this_friday(ref_date) + timedelta(weeks=1)
        return ResolvedDate(date=friday, kind="weekend", confident=True)

    # "next <weekday>"
    next_wd = re.match(r"^next\s+(\w+)$", phrase)
    if next_wd:
        wd_name = next_wd.group(1).lower()
        if wd_name in WEEKDAYS:
            wd_idx = WEEKDAYS.index(wd_name)
            d = _next_weekday_after_week(ref_date, wd_idx)
            return ResolvedDate(date=d, kind="weekday", confident=True)
        return ResolvedDate(date=None, kind="unrecognized", confident=False)

    # "this <weekday>" or bare "<weekday>"
    this_wd = re.match(r"^(?:this\s+)?(\w+)$", phrase)
    if this_wd:
        wd_name = this_wd.group(1).lower()
        if wd_name in WEEKDAYS:
            wd_idx = WEEKDAYS.index(wd_name)
            d = _this_or_upcoming_weekday(ref_date, wd_idx)
            return ResolvedDate(date=d, kind="weekday", confident=True)

    return ResolvedDate(date=None, kind="unrecognized", confident=False)


def _norm(phrase: str) -> str:
    phrase = phrase.strip().lower()
    phrase = _LEADING.sub("", phrase)
    phrase = _TRAILING.sub("", phrase)
    return " ".join(phrase.split())


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _this_or_upcoming_weekday(ref: date, wd_idx: int) -> date:
    """Return this week's weekday if >= ref, else next week's."""
    monday = _week_monday(ref)
    candidate = monday + timedelta(days=wd_idx)
    if candidate >= ref:
        return candidate
    return candidate + timedelta(weeks=1)


def _next_weekday_after_week(ref: date, wd_idx: int) -> date:
    """Return the same weekday in the following week."""
    monday = _week_monday(ref)
    return monday + timedelta(weeks=1, days=wd_idx)


def _this_friday(ref: date) -> date:
    """Friday of the current week; if Sat/Sun → next week's Friday."""
    friday_idx = 4  # Monday=0 … Friday=4
    monday = _week_monday(ref)
    friday = monday + timedelta(days=friday_idx)
    if ref.weekday() >= 5:  # Sat=5, Sun=6
        friday += timedelta(weeks=1)
    return friday
