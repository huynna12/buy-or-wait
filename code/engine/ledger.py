"""Build the dated cash items the forecast runs on.

`current_available_balance` already includes every settled event, so settled
history is never replayed; it is only evidence of what recurs.

Rules (where the spec is silent, calibrated against sample_requests.csv):
- pending debit                  -> reserved on its settlement date
- pending credit                 -> ignored until it settles
- scheduled debit or credit      -> on its settlement date
- failed, cancelled, unrealized  -> ignored
- monthly series, debit          -> projected at the mean of past amounts
- monthly series, credit         -> projected at the lowest past amount (a pay
                                    cut or temporary pay is never overstated)
- scheduled salary, no salary series -> repeats monthly (new hires)
- categories with a dominant interval (e.g. groceries every 10 days) -> projected
  at the smallest past amount from the day after the request (today's balance
  already reflects today's habits). A one-off extra purchase does not hide the
  habit; spending with no dominant interval is not projected
- amendments from messages and images are applied in the order given, so
  pass them oldest first and the newest fact wins
"""
from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean
from typing import Callable, Iterable, Sequence, TypeVar

from engine.amendments import Amendment, AmendmentKind
from engine.models import Direction, Event, RequestContext, Status
from engine.recurrence import detect_series, monthly_dates, on_day

HORIZON_DAYS = 90
SALARY = "salary"
MIN_CADENCE_EVENTS = 3
CADENCE_SHARE = 0.75  # the most common gap must cover at least this share of gaps

ToHome = Callable[[Decimal, str, date], Decimal]
T = TypeVar("T")


@dataclass(frozen=True)
class CashItem:
    day: date
    amount: Decimal  # signed, home currency: credit > 0, debit < 0
    label: str
    category: str
    kind: str  # pending | scheduled | series | variable | amendment
    target_event_id: str | None = None  # the real event a spending change would act on

    @property
    def is_salary(self) -> bool:
        return self.amount > 0 and self.category == SALARY


@dataclass(frozen=True)
class Ledger:
    start: date
    end: date
    items: tuple[CashItem, ...]
    events: tuple[Event, ...]  # after image amounts were filled in
    skipped: tuple[str, ...]  # human-readable reasons, e.g. a blank amount with no image

    def event(self, event_id: str) -> Event | None:
        return next((e for e in self.events if e.event_id == event_id), None)


def build_ledger(ctx: RequestContext, amendments: Sequence[Amendment] = ()) -> Ledger:
    start = ctx.request.request_date
    end = start + timedelta(days=HORIZON_DAYS)
    home = ctx.profile.home_currency

    def to_home(amount: Decimal, currency: str, on: date) -> Decimal:
        return ctx.rates.convert(amount, currency, home, on, allow_earlier=True)

    events = _fill_event_amounts(ctx.events, amendments)
    skipped: list[str] = []
    items = _recorded_items(events, start, end, to_home, skipped)
    items += _recurring_items(events, items, start, end, to_home)
    items += _cadence_items(events, start, end, to_home)
    items = _apply_amendments(items, amendments, start, end, to_home)
    items.sort(key=lambda i: (i.day, i.label))
    return Ledger(start, end, tuple(items), tuple(events), tuple(skipped))


def _fill_event_amounts(events: Iterable[Event], amendments: Sequence[Amendment]) -> list[Event]:
    fills = {a.event_id: a for a in amendments if a.kind is AmendmentKind.EVENT_AMOUNT}
    filled = []
    for e in events:
        fill = fills.get(e.event_id)
        if e.amount is None and fill is not None:
            e = dataclasses.replace(e, amount=_present(fill.amount), currency=_present(fill.currency))
        filled.append(e)
    return filled


def _recorded_items(events, start, end, to_home: ToHome, skipped: list[str]) -> list[CashItem]:
    items = []
    for e in events:
        pending_debit = e.status is Status.PENDING and e.direction is Direction.DEBIT
        scheduled = e.status is Status.SCHEDULED and e.direction is not Direction.NON_CASH
        if not (pending_debit or scheduled) or e.settlement_date is None:
            continue
        if e.amount is None:
            skipped.append(f"{e.event_id} ({e.description}) has no amount")
            continue
        day = max(start, e.settlement_date)
        if day > end:
            continue
        amount = to_home(e.amount, e.currency, e.settlement_date)
        signed = amount if e.direction is Direction.CREDIT else -amount
        items.append(CashItem(day, signed, e.description, e.category, str(e.status), e.event_id))
    return items


def _recurring_items(events, recorded: list[CashItem], start, end, to_home: ToHome) -> list[CashItem]:
    series = [s for s in detect_series(events) if s.is_active(start) and s.amounts]
    salary_months = {(i.day.year, i.day.month) for i in recorded if i.is_salary}
    items = []
    for s in series:
        amount = min(s.amounts) if s.direction is Direction.CREDIT else mean(s.amounts)
        for day in s.occurrences_between(max(start, s.last_event.event_date + timedelta(days=1)), end):
            if s.direction is Direction.CREDIT:
                if s.category == SALARY and (day.year, day.month) in salary_months:
                    continue  # the scheduled salary row already covers this month
                items.append(CashItem(day, to_home(amount, s.currency, day), s.description,
                                      s.category, "series", s.last_event.event_id))
            else:
                items.append(CashItem(day, -to_home(amount, s.currency, day), s.description,
                                      s.category, "series", s.last_event.event_id))

    has_salary_series = any(s.direction is Direction.CREDIT and s.category == SALARY for s in series)
    if not has_salary_series:
        for e in events:
            if e.status is Status.SCHEDULED and e.direction is Direction.CREDIT \
                    and e.category == SALARY and e.amount is not None and e.settlement_date:
                for day in monthly_dates(e.settlement_date + timedelta(days=1), end, e.settlement_date.day):
                    items.append(CashItem(day, to_home(e.amount, e.currency, day), e.description,
                                          SALARY, "series", e.event_id))
    return items


def _cadence_items(events, start, end, to_home: ToHome) -> list[CashItem]:
    in_series = {e.event_id for s in detect_series(events) for e in s.events}
    by_category: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.status is Status.SETTLED and e.direction is Direction.DEBIT and e.amount is not None \
                and e.linked_event_id is None and e.event_id not in in_series:
            by_category[e.category].append(e)

    items = []
    for category, group in by_category.items():
        cadence = _cadence(group)
        if cadence is None:
            continue
        gap, regular = cadence
        last = regular[-1]
        if last.event_date + 2 * gap < start:
            continue  # the habit stopped before the request
        amount = min(e.amount for e in regular if e.amount is not None)
        day = last.event_date + gap
        while day <= end:
            if day > start:
                items.append(CashItem(day, -to_home(amount, last.currency, day),
                                      f"{category} (every {gap.days} days)", category,
                                      "variable", last.event_id))
            day += gap
    return items


def _cadence(group: list[Event]) -> tuple[timedelta, list[Event]] | None:
    """A habit's dominant interval, tolerating one-off extras.

    An extra purchase on the same day as another is ignored, and the most
    common gap only has to cover CADENCE_SHARE of the gaps, so a single bulk
    buy does not hide a weekly grocery habit.
    """
    ordered = sorted(group, key=lambda e: e.event_date)
    regular = [ordered[0]] + [b for a, b in zip(ordered, ordered[1:]) if b.event_date != a.event_date]
    if len(regular) < MIN_CADENCE_EVENTS:
        return None
    gaps = [(b.event_date - a.event_date).days for a, b in zip(regular, regular[1:])]
    days, count = Counter(gaps).most_common(1)[0]
    if count < CADENCE_SHARE * len(gaps):
        return None
    return timedelta(days=days), regular


def _apply_amendments(items: list[CashItem], amendments: Sequence[Amendment], start, end,
                      to_home: ToHome) -> list[CashItem]:
    for a in amendments:
        if a.kind is AmendmentKind.EVENT_AMOUNT:
            continue  # already applied to the events before projecting
        effective = _present(a.effective_date)
        if a.kind is AmendmentKind.SALARY_AMOUNT:
            amount, currency = _present(a.amount), _present(a.currency)
            items = [dataclasses.replace(i, amount=to_home(amount, currency, i.day))
                     if i.is_salary and i.day >= effective else i for i in items]
        elif a.kind is AmendmentKind.SALARY_DAY:
            first_month = (effective.year, effective.month)
            items = [dataclasses.replace(i, day=on_day(i.day.year, i.day.month, effective.day))
                     if i.is_salary and (i.day.year, i.day.month) >= first_month else i for i in items]
        elif a.kind is AmendmentKind.SALARY_START:
            amount, currency = _present(a.amount), _present(a.currency)
            new_days = monthly_dates(effective, end, effective.day)
            months = {(d.year, d.month) for d in new_days}
            items = [i for i in items if not (i.is_salary and (i.day.year, i.day.month) in months)]
            items += [CashItem(d, to_home(amount, currency, d), "Confirmed salary", SALARY, "amendment")
                      for d in new_days if d >= start]
        elif a.kind is AmendmentKind.INCOME_END:
            items = [i for i in items if not (i.is_salary and i.day > effective)]
        elif a.kind is AmendmentKind.CONFIRMED_CREDIT:
            amount, currency = _present(a.amount), _present(a.currency)
            if start <= effective <= end:
                items.append(CashItem(effective, to_home(amount, currency, effective),
                                      "Confirmed payment", "income", "amendment"))
        elif a.kind is AmendmentKind.EXPENSE_CHANGE_PCT:
            factor = 1 + _present(a.percent) / 100
            items = [dataclasses.replace(i, amount=i.amount * factor)
                     if i.amount < 0 and i.category == a.category and i.kind in ("series", "scheduled")
                     and i.day >= effective else i for i in items]
    return [i for i in items if start <= i.day <= end]


def _present(value: T | None) -> T:
    """Narrow an Amendment field that Amendment.__post_init__ already requires for its kind."""
    if value is None:
        raise ValueError("amendment is missing a field its kind requires")
    return value
