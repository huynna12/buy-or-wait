"""Detect recurring cash flows from settled history.

Phase 1 handles fixed series only: same description, category, direction and
currency, on the same day of every consecutive month. Rotating descriptions
(dining, groceries) need a category-level model, added in Phase 3.

Detection uses event_date, not settlement_date: settlement occasionally slips
a day or two, which would break an otherwise clean monthly series.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from engine.models import Direction, Event, EventType, Flexibility, Status

MIN_OCCURRENCES = 3


@dataclass(frozen=True)
class RecurringSeries:
    events: tuple[Event, ...]  # chronological, at least MIN_OCCURRENCES
    day_of_month: int

    @property
    def last_event(self) -> Event:
        return self.events[-1]

    @property
    def description(self) -> str:
        return self.last_event.description

    @property
    def category(self) -> str:
        return self.last_event.category

    @property
    def event_type(self) -> EventType:
        return self.last_event.event_type

    @property
    def direction(self) -> Direction:
        return self.last_event.direction

    @property
    def currency(self) -> str:
        return self.last_event.currency

    @property
    def flexibility(self) -> Flexibility:
        # Newest record wins when records disagree (spec conflict rule 2).
        return self.last_event.flexibility

    @property
    def minimum_allowed_amount(self) -> Decimal | None:
        return self.last_event.minimum_allowed_amount

    @property
    def amounts(self) -> tuple[Decimal, ...]:
        """Known amounts, oldest first. Blank amounts are skipped, not zeroed."""
        return tuple(e.amount for e in self.events if e.amount is not None)

    @property
    def has_constant_amount(self) -> bool:
        return len(set(self.amounts)) == 1

    def next_after(self, day: date) -> date:
        """First occurrence strictly after `day`."""
        candidate = _on_day(day.year, day.month, self.day_of_month)
        if candidate <= day:
            year, month = _next_month(day.year, day.month)
            candidate = _on_day(year, month, self.day_of_month)
        return candidate

    def is_active(self, as_of: date) -> bool:
        """False if the series already missed an occurrence before `as_of`."""
        return self.next_after(self.last_event.event_date) >= as_of

    def occurrences_between(self, start: date, end: date) -> list[date]:
        """Occurrence dates in [start, end], inclusive."""
        return monthly_dates(start, end, self.day_of_month)


def monthly_dates(start: date, end: date, day_of_month: int) -> list[date]:
    """Dates on `day_of_month` (clamped to month end) in [start, end], inclusive."""
    dates = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        day = _on_day(year, month, day_of_month)
        if start <= day <= end:
            dates.append(day)
        year, month = _next_month(year, month)
    return dates


def on_day(year: int, month: int, day: int) -> date:
    return _on_day(year, month, day)


def detect_series(events: Iterable[Event]) -> list[RecurringSeries]:
    groups: dict[tuple[str, str, Direction, str], list[Event]] = defaultdict(list)
    for e in events:
        if e.status is Status.SETTLED and e.direction is not Direction.NON_CASH:
            groups[(e.description, e.category, e.direction, e.currency)].append(e)

    series = []
    for group in groups.values():
        if len(group) < MIN_OCCURRENCES:
            continue
        group.sort(key=lambda e: e.event_date)
        day = _monthly_day([e.event_date for e in group])
        if day is not None:
            series.append(RecurringSeries(tuple(group), day))
    return sorted(series, key=lambda s: (s.day_of_month, s.description))


def _monthly_day(dates: list[date]) -> int | None:
    """Shared day of month if `dates` fall on it in consecutive months, else None.

    The anchor is the largest day seen, so a 31st series still matches Feb 28/29.
    """
    for prev, cur in zip(dates, dates[1:]):
        if _month_index(cur) - _month_index(prev) != 1:
            return None
    anchor = max(d.day for d in dates)
    if any(d != _on_day(d.year, d.month, anchor) for d in dates):
        return None
    return anchor


def _on_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _month_index(d: date) -> int:
    return d.year * 12 + d.month
