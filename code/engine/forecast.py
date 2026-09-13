"""The 90-day headroom curve and the two numbers it answers exactly.

headroom[d] = end-of-day balance on day d - minimum_balance_to_keep

- A payment today lowers every later day by the same amount, so the most that
  is safe today is min(headroom).
- A payment on day D lowers only days >= D, so it is safe exactly when
  min(headroom[D:]) >= amount. That suffix minimum never decreases as D moves
  later, so the first day that clears is the earliest safe date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from engine.ledger import HORIZON_DAYS, CashItem

ZERO = Decimal(0)


@dataclass(frozen=True)
class Forecast:
    start: date
    headroom: tuple[Decimal, ...]  # index = days after start, inclusive of day HORIZON_DAYS

    @property
    def end(self) -> date:
        return self.start + timedelta(days=len(self.headroom) - 1)

    @property
    def lowest(self) -> Decimal:
        return min(self.headroom)

    @property
    def lowest_day(self) -> date:
        return self.start + timedelta(days=self.headroom.index(self.lowest))


def build_forecast(opening_balance: Decimal, minimum_balance: Decimal, items: Iterable[CashItem],
                   start: date, horizon_days: int = HORIZON_DAYS) -> Forecast:
    deltas = [ZERO] * (horizon_days + 1)
    for item in items:
        index = (item.day - start).days
        if 0 <= index <= horizon_days:
            deltas[index] += item.amount
    running = opening_balance - minimum_balance
    headroom = []
    for delta in deltas:
        running += delta
        headroom.append(running)
    return Forecast(start, tuple(headroom))


def safe_amount_today(forecast: Forecast, cap: Decimal) -> Decimal:
    return max(ZERO, min(forecast.lowest, cap))


def earliest_full_payment(forecast: Forecast, amount: Decimal) -> date | None:
    suffix_min = list(forecast.headroom)
    for i in range(len(suffix_min) - 2, -1, -1):
        suffix_min[i] = min(suffix_min[i], suffix_min[i + 1])
    for i, lowest_after in enumerate(suffix_min):
        if lowest_after >= amount:
            return forecast.start + timedelta(days=i)
    return None


def plan_is_safe(forecast: Forecast, payments: Iterable[tuple[date, Decimal]]) -> bool:
    """True if headroom never goes negative after the payments.

    Payments after the forecast window cannot affect it and are not checked;
    a payment before the start date is never safe.
    """
    paid = [ZERO] * len(forecast.headroom)
    for day, amount in payments:
        index = (day - forecast.start).days
        if index < 0:
            return False
        if index < len(paid):
            paid[index] += amount
    cumulative = ZERO
    for headroom, payment in zip(forecast.headroom, paid):
        cumulative += payment
        if headroom - cumulative < 0:
            return False
    return True
