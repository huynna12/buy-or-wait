"""Candidate payment plans, their eligibility, and the spec's ranking order."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from engine.forecast import Forecast, plan_is_safe
from engine.models import PaymentMethod, RequestContext

ZERO = Decimal(0)


class Recommendation(StrEnum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


@dataclass(frozen=True)
class SpendingChange:
    action: str  # "stop" | "reduce_to"
    event_id: str
    new_amount: Decimal | None
    description: str
    category: str
    savings: Decimal  # total spending removed over the forecast window

    @property
    def event_number(self) -> int:
        return int(self.event_id.rsplit("_", 1)[1])


@dataclass(frozen=True)
class Plan:
    method: Recommendation
    payments: tuple[tuple[date, Decimal], ...]
    option_id: str | None = None
    option_number: int = 0  # numeric id, for the final tie-break
    changes: tuple[SpendingChange, ...] = ()

    @property
    def total_paid(self) -> Decimal:
        return sum((amount for _, amount in self.payments), ZERO)

    @property
    def first_day(self) -> date | None:
        return self.payments[0][0] if self.payments else None

    def completes_by(self, deadline: date) -> bool:
        return bool(self.payments) and self.payments[-1][0] <= deadline


NOT_RECOMMENDED = Plan(Recommendation.NOT_RECOMMENDED, ())


def eligible_plans(ctx: RequestContext, safe_today: Decimal, earliest: date | None) -> list[Plan]:
    """Plans the user accepts that finish by the deadline. Safety is checked separately."""
    req, profile = ctx.request, ctx.profile
    today, amount = req.request_date, req.requested_amount
    plans = []
    if profile.accepts(PaymentMethod.FULL_PAYMENT):
        plans.append(Plan(Recommendation.FULL_PAYMENT, ((today, amount),)))
        if earliest is not None and earliest > today:
            plans.append(Plan(Recommendation.WAIT, ((earliest, amount),)))
    if (profile.accepts(PaymentMethod.PARTIAL_PAYMENT) and req.allows_partial_payment
            and earliest is not None and ZERO < safe_today < amount):
        plans.append(Plan(Recommendation.PARTIAL_PAYMENT, ((today, safe_today), (earliest, amount - safe_today))))
    max_months = profile.max_installment_months  # None means installments are not considered
    if profile.accepts(PaymentMethod.INSTALLMENTS) and max_months is not None:
        for option in ctx.options:
            if option.method is PaymentMethod.INSTALLMENTS and option.number_of_payments <= max_months:
                plans.append(Plan(Recommendation.INSTALLMENTS, option.schedule(),
                                  option.payment_option_id, option.id_number))
    return [p for p in plans if p.completes_by(req.desired_completion_date)]


def rank_key(plan: Plan, deadline: date) -> tuple:
    """Spec order: finish by deadline, no spending changes, least paid, start earlier,
    fewer payments, lowest payment_option_id."""
    return (not plan.completes_by(deadline), bool(plan.changes), plan.total_paid,
            plan.first_day, len(plan.payments), plan.option_number)


def choose(plans: Iterable[Plan], forecast: Forecast, deadline: date) -> Plan | None:
    safe = [p for p in plans if plan_is_safe(forecast, p.payments)]
    return min(safe, key=lambda p: rank_key(p, deadline)) if safe else None
