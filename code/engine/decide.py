"""RequestContext + amendments -> Decision. The only entry point adapters call."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Sequence

from engine.amendments import Amendment
from engine.forecast import build_forecast, earliest_full_payment, safe_amount_today
from engine.ledger import Ledger, build_ledger
from engine.models import PaymentMethod, RequestContext
from engine.plans import NOT_RECOMMENDED, Plan, Recommendation, choose, eligible_plans, rank_key
from engine.spending import cheapest_changes

CENT = Decimal("0.01")
CHANGEABLE_PLANS = (Recommendation.FULL_PAYMENT, Recommendation.INSTALLMENTS)


class Affordability(StrEnum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


@dataclass(frozen=True)
class Decision:
    request_id: str
    currency: str
    request_date: date
    deadline: date
    requested_amount: Decimal
    minimum_balance: Decimal
    amount_safe_to_pay: Decimal
    earliest_full_payment: date | None
    status: Affordability
    plan: Plan
    partial_was_possible: bool  # user accepts partial and the request allows it
    skipped_evidence: tuple[str, ...]


def decide(ctx: RequestContext, amendments: Sequence[Amendment] = ()) -> Decision:
    req, profile = ctx.request, ctx.profile
    ledger = build_ledger(ctx, amendments)
    forecast = build_forecast(profile.current_available_balance, profile.minimum_balance_to_keep,
                              ledger.items, req.request_date)
    # Round down: never report more as safe than the forecast supports.
    safe = safe_amount_today(forecast, req.requested_amount).quantize(CENT, rounding=ROUND_DOWN)
    earliest = earliest_full_payment(forecast, req.requested_amount)

    plans = eligible_plans(ctx, safe, earliest)
    plan = choose(plans, forecast, req.desired_completion_date) or _best_with_changes(ctx, ledger, plans)

    return Decision(
        request_id=req.request_id,
        currency=profile.home_currency,
        request_date=req.request_date,
        deadline=req.desired_completion_date,
        requested_amount=req.requested_amount,
        minimum_balance=profile.minimum_balance_to_keep,
        amount_safe_to_pay=safe,
        earliest_full_payment=earliest,
        status=_status(plan),
        plan=plan,
        partial_was_possible=profile.accepts(PaymentMethod.PARTIAL_PAYMENT) and req.allows_partial_payment,
        skipped_evidence=ledger.skipped,
    )


def _best_with_changes(ctx: RequestContext, ledger: Ledger, plans: list[Plan]) -> Plan:
    # Only reached when no plan is safe as-is, so any plan needing changes ranks
    # below every unchanged safe plan, exactly as the spec orders them.
    candidates = []
    for plan in plans:
        if plan.method in CHANGEABLE_PLANS:
            changes = cheapest_changes(ctx, ledger, plan.payments)
            if changes:
                candidates.append(dataclasses.replace(plan, changes=changes))
    if not candidates:
        return NOT_RECOMMENDED
    return min(candidates, key=lambda p: rank_key(p, ctx.request.desired_completion_date))


def _status(plan: Plan) -> Affordability:
    if plan.method is Recommendation.FULL_PAYMENT and not plan.changes:
        return Affordability.AFFORDABLE_NOW
    if plan.method is Recommendation.WAIT:
        return Affordability.AFFORDABLE_LATER
    if plan.method is Recommendation.NOT_RECOMMENDED:
        return Affordability.NOT_AFFORDABLE
    return Affordability.AFFORDABLE_WITH_PLAN
