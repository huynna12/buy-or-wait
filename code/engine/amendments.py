"""The closed set of facts that messages and images may change.

Extraction turns untrusted text or images into these objects; anything that
does not fit one of these kinds is dropped before it reaches the engine. The
engine never reads message or image content itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class AmendmentKind(StrEnum):
    SALARY_AMOUNT = "salary_amount"            # salary credits from effective_date use `amount`
    SALARY_DAY = "salary_day"                  # payday moves to effective_date's day, from that month on
    SALARY_START = "salary_start"              # monthly salary of `amount` starts on effective_date
    INCOME_END = "income_end"                  # no salary credits after effective_date
    CONFIRMED_CREDIT = "confirmed_credit"      # one confirmed credit of `amount` on effective_date
    EXPENSE_CHANGE_PCT = "expense_change_pct"  # recurring `category` debits change by `percent` from effective_date
    EVENT_AMOUNT = "event_amount"              # fills the blank amount of `event_id`


_REQUIRED: dict[AmendmentKind, tuple[str, ...]] = {
    AmendmentKind.SALARY_AMOUNT: ("effective_date", "amount", "currency"),
    AmendmentKind.SALARY_DAY: ("effective_date",),
    AmendmentKind.SALARY_START: ("effective_date", "amount", "currency"),
    AmendmentKind.INCOME_END: ("effective_date",),
    AmendmentKind.CONFIRMED_CREDIT: ("effective_date", "amount", "currency"),
    AmendmentKind.EXPENSE_CHANGE_PCT: ("effective_date", "category", "percent"),
    AmendmentKind.EVENT_AMOUNT: ("event_id", "amount", "currency"),
}


@dataclass(frozen=True)
class Amendment:
    kind: AmendmentKind
    source_id: str  # message_id or image_id, kept for traceability
    effective_date: date | None = None
    amount: Decimal | None = None
    currency: str | None = None
    event_id: str | None = None
    category: str | None = None
    percent: Decimal | None = None

    def __post_init__(self) -> None:
        missing = [name for name in _REQUIRED[self.kind] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} from {self.source_id} is missing {missing}")
        if self.amount is not None and self.amount <= 0:
            raise ValueError(f"{self.kind} from {self.source_id} needs a positive amount")
