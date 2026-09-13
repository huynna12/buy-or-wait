"""Fixed, dated exchange rates.

A rate is looked up by exact date and the stated from->to direction. We never
invert a rate or borrow a neighbouring date: a missing row is an error, not a
guess.
"""
from __future__ import annotations

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

    def convert(self, amount: Decimal, from_currency: str, to_currency: str, on: date) -> Decimal:
        if from_currency == to_currency:
            return amount
        rate = self._rates.get((on, from_currency, to_currency))
        if rate is None:
            raise MissingRateError(f"no {from_currency}->{to_currency} rate on {on.isoformat()}")
        return amount * rate
