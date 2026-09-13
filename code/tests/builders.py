"""Small factories for hand-built engine inputs in tests."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from engine.currency import ExchangeRate, RateTable
from engine.models import (
    Direction, Event, EventType, Flexibility, PaymentMethod, PaymentOption, Profile, Request,
    RequestContext, RequestType, Status,
)

START = date(2026, 4, 3)
_TYPES = {Direction.DEBIT: EventType.EXPENSE, Direction.CREDIT: EventType.INCOME,
          Direction.NON_CASH: EventType.INVESTMENT_VALUATION}


def event(event_id: str, day: date, amount: str | None = "100", *, description: str = "Item",
          category: str = "groceries", direction: Direction = Direction.DEBIT,
          status: Status = Status.SETTLED, currency: str = "EUR", settlement: date | None = None,
          linked: str | None = None, flexibility: Flexibility = Flexibility.FIXED,
          minimum: str | None = None) -> Event:
    return Event(
        event_id=event_id, user_id="user_x", event_type=_TYPES[direction], description=description,
        category=category, direction=direction, amount=Decimal(amount) if amount is not None else None,
        currency=currency, event_date=day,
        settlement_date=None if direction is Direction.NON_CASH else (settlement or day),
        status=status, linked_event_id=linked, flexibility=flexibility,
        minimum_allowed_amount=Decimal(minimum) if minimum is not None else None,
    )


def monthly(prefix: str, day_of_month: int, months: list[tuple[int, int]], amounts, **kwargs) -> list[Event]:
    amounts = amounts if isinstance(amounts, list) else [amounts] * len(months)
    return [event(f"{prefix}_{i}", date(y, m, day_of_month), a, **kwargs)
            for i, ((y, m), a) in enumerate(zip(months, amounts))]


def every(prefix: str, first: date, gap_days: int, amounts: list[str], **kwargs) -> list[Event]:
    return [event(f"{prefix}_{i}", first + timedelta(days=gap_days * i), a, **kwargs)
            for i, a in enumerate(amounts)]


LAST_THREE_MONTHS = [(2026, 1), (2026, 2), (2026, 3)]


def profile(balance: str = "1000", minimum: str = "100", *, protected=(), reduce=(), stop=(),
            methods=("full_payment",), max_months: int | None = None, currency: str = "EUR") -> Profile:
    return Profile(
        user_id="user_x", home_currency=currency, current_available_balance=Decimal(balance),
        minimum_balance_to_keep=Decimal(minimum), financial_priorities=(),
        protected_categories=frozenset(protected), reducible_categories=frozenset(reduce),
        stoppable_categories=frozenset(stop), payment_methods=frozenset(PaymentMethod(m) for m in methods),
        max_installment_months=max_months,
    )


def request(amount: str = "100", *, day: date = START, deadline: date | None = None,
            partial: bool = False) -> Request:
    return Request(request_id="request_x", user_id="user_x", request_date=day,
                   request_type=RequestType.PURCHASE, requested_amount=Decimal(amount),
                   desired_completion_date=deadline or day + timedelta(days=30),
                   allows_partial_payment=partial)


def option(option_id: str, method: str, amount: str, count: int, first: date,
           every_days: int | None = None, fee: str = "0") -> PaymentOption:
    total = Decimal(amount) * count
    return PaymentOption(option_id, "request_x", PaymentMethod(method), Decimal(amount), count, first,
                         every_days, Decimal(fee), total)


def context(events=(), *, prof: Profile | None = None, req: Request | None = None, options=(),
            rates=()) -> RequestContext:
    req = req or request()
    return RequestContext(request=req, profile=prof or profile(), events=tuple(events),
                          options=tuple(options) or (option("payment_option_1", "full_payment",
                                                            str(req.requested_amount), 1, req.request_date),),
                          rates=RateTable(ExchangeRate(*r) for r in rates))
