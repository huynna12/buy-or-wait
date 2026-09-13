"""Decision -> output.csv strings, matching the published sample formatting.

- amount_safe_to_pay drops trailing zeros:        620.4, 25256
- plan and reduce_to amounts keep two decimals
  unless the amount is whole:                      620.40, 25256
"""
from __future__ import annotations

from decimal import Decimal

from engine.decide import Decision
from engine.plans import Plan, SpendingChange
from output.validate import COLUMNS

CENT = Decimal("0.01")


def plan_amount(amount: Decimal) -> str:
    q = amount.quantize(CENT)
    return f"{q.to_integral_value():f}" if q == q.to_integral_value() else f"{q:.2f}"


def plain_amount(amount: Decimal) -> str:
    text = f"{amount.quantize(CENT):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def plan_text(plan: Plan) -> str:
    if not plan.payments:
        return "none"
    return "|".join(f"{day.isoformat()}:{plan_amount(amount)}" for day, amount in plan.payments)


def changes_text(changes: tuple[SpendingChange, ...]) -> str:
    if not changes:
        return "none"
    # A stop carries no new amount; a reduce_to always does.
    return "|".join(f"stop:{c.event_id}" if c.new_amount is None
                    else f"reduce_to:{c.event_id}:{plan_amount(c.new_amount)}" for c in changes)


def to_row(decision: Decision, explanation: str) -> dict[str, str]:
    values = (
        decision.request_id,
        plain_amount(decision.amount_safe_to_pay),
        str(decision.status),
        str(decision.plan.method),
        plan_text(decision.plan),
        decision.earliest_full_payment.isoformat() if decision.earliest_full_payment else "",
        changes_text(decision.plan.changes),
        explanation,
    )
    return dict(zip(COLUMNS, values))
