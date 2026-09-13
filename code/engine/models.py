"""Domain models for the decision engine.

Immutable value objects. They know nothing about CSV files, LLMs, or output
formatting; the adapters in data/ and extraction/ build them.

Conventions:
- Money is Decimal, never float, so plan amounts can sum exactly.
- A blank source value is None, never 0 (a blank amount is unknown, not free).
- Enums are strict: an unknown value raises ValueError at the adapter boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from engine.currency import RateTable


class Status(StrEnum):
    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventType(StrEnum):
    EXPENSE = "expense"
    SUBSCRIPTION = "subscription"
    INCOME = "income"
    DEBT_PAYMENT = "debt_payment"
    REFUND = "refund"
    INVESTMENT_PURCHASE = "investment_purchase"
    INVESTMENT_SALE = "investment_sale"
    INVESTMENT_VALUATION = "investment_valuation"


class Flexibility(StrEnum):
    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"

    @property
    def can_reduce(self) -> bool:
        return self in (Flexibility.REDUCIBLE, Flexibility.REDUCIBLE_OR_STOPPABLE)

    @property
    def can_stop(self) -> bool:
        return self in (Flexibility.STOPPABLE, Flexibility.REDUCIBLE_OR_STOPPABLE)


class PaymentMethod(StrEnum):
    """Methods a seller can offer and a user can accept.

    `wait` and `not_recommended` are decision outcomes, not offers, so they
    belong to the decision types added in Phase 4.
    """

    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"


class RequestType(StrEnum):
    PURCHASE = "purchase"
    TRAVEL = "travel"
    EDUCATION = "education"
    FAMILY_TRANSFER = "family_transfer"
    DEBT_REPAYMENT = "debt_repayment"
    INVESTMENT = "investment"
    HOUSING = "housing"
    EMERGENCY_EXPENSE = "emergency_expense"
    OTHER = "other"


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: Direction
    amount: Decimal | None  # None = blank in source; filled from an image later
    currency: str
    event_date: date
    settlement_date: date | None  # None only for unrealized valuations
    status: Status
    linked_event_id: str | None
    flexibility: Flexibility
    minimum_allowed_amount: Decimal | None


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: tuple[str, ...]  # order kept; may matter for ranking
    protected_categories: frozenset[str]
    reducible_categories: frozenset[str]
    stoppable_categories: frozenset[str]
    payment_methods: frozenset[PaymentMethod]
    max_installment_months: int | None  # None = will not consider installments

    def accepts(self, method: PaymentMethod) -> bool:
        if method is PaymentMethod.INSTALLMENTS and self.max_installment_months is None:
            return False
        return method in self.payment_methods


@dataclass(frozen=True)
class Request:
    """A purchase/payment request.

    `request_text` is intentionally absent: the engine decides from structured
    fields only, so free text never reaches decision logic.
    """

    request_id: str
    user_id: str
    request_date: date
    request_type: RequestType
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    method: PaymentMethod
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None  # None for a single full payment
    financing_fee: Decimal
    total_payable_amount: Decimal

    def __post_init__(self) -> None:
        if self.number_of_payments < 1:
            raise ValueError(f"{self.payment_option_id}: number_of_payments must be >= 1")
        if self.number_of_payments > 1 and not self.payment_frequency_days:
            raise ValueError(f"{self.payment_option_id}: recurring payments need a frequency")

    @property
    def id_number(self) -> int:
        # Ids are zero-padded to only two digits, so "payment_option_100" sorts
        # before "payment_option_99" as a string. Tie-breaks must be numeric.
        return int(self.payment_option_id.rsplit("_", 1)[1])

    def schedule(self) -> tuple[tuple[date, Decimal], ...]:
        """Payment dates step by a fixed number of days, not calendar months."""
        step = timedelta(days=self.payment_frequency_days or 0)
        return tuple(
            (self.first_payment_date + i * step, self.payment_amount)
            for i in range(self.number_of_payments)
        )


@dataclass(frozen=True)
class RequestContext:
    """Everything the engine needs to decide one request.

    Validated amendments from messages/images are added in Phase 3.
    """

    request: Request
    profile: Profile
    events: tuple[Event, ...]
    options: tuple[PaymentOption, ...]
    rates: RateTable
