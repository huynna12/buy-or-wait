"""Fixed, dated exchange rates.

A rate is looked up by exact date and the stated from->to direction, and never
inverted. Recorded events always use their exact settlement date. Projected
items (a future salary that is not a row in the data) may opt in to the most
recent earlier rate, since no row can exist for a date we invented.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable


class MissingRateError(LookupError):
    pass


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


class RateTable:
    def __init__(self, rates: Iterable[ExchangeRate]) -> None:
        self._rates: dict[tuple[date, str, str], Decimal] = {}
        for r in rates:
            key = (r.rate_date, r.from_currency, r.to_currency)
            if key in self._rates and self._rates[key] != r.rate:
                raise ValueError(f"conflicting rates for {key}")
            self._rates[key] = r.rate
        self._dates: dict[tuple[str, str], list[date]] = defaultdict(list)
        for day, frm, to in sorted(self._rates):
            self._dates[(frm, to)].append(day)

    def convert(self, amount: Decimal, from_currency: str, to_currency: str, on: date,
                *, allow_earlier: bool = False) -> Decimal:
        if from_currency == to_currency:
            return amount
        rate = self._rates.get((on, from_currency, to_currency))
        if rate is None and allow_earlier:
            dates = self._dates.get((from_currency, to_currency), [])
            i = bisect.bisect_right(dates, on)
            if i:
                rate = self._rates[(dates[i - 1], from_currency, to_currency)]
        if rate is None:
            raise MissingRateError(f"no {from_currency}->{to_currency} rate on {on.isoformat()}")
        return amount * rate
