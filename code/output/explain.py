"""Templated decision_explanation.

Templates, not an LLM: the text narrates a decision the engine already made,
so it cannot contradict the numbers, costs nothing, and is deterministic. The
wording follows the published sample explanations.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from engine.decide import Decision
from engine.plans import Recommendation, SpendingChange

CENT = Decimal("0.01")


def money(amount: Decimal, currency: str) -> str:
    q = amount.quantize(CENT)
    number = f"{int(q):,}" if q == q.to_integral_value() else f"{q:,.2f}"
    return f"{currency} {number}"


def long_date(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def explain(d: Decision) -> str:
    cur, plan = d.currency, d.plan
    minimum = money(d.minimum_balance, cur)
    requested = money(d.requested_amount, cur)
    prefix = _changes_phrase(plan.changes, cur)

    if plan.method is Recommendation.FULL_PAYMENT:
        if plan.changes:
            return f"{prefix}, then pay {requested} today. This leaves at least {minimum} available."
        return f"Pay {requested} today. This leaves at least {minimum} available over the next 90 days."

    if plan.method is Recommendation.INSTALLMENTS:
        first_day, amount = plan.payments[0]
        action = f"use {len(plan.payments)} installments of {money(amount, cur)}, starting {long_date(first_day)}"
        action = f"{prefix}, then {action}" if plan.changes else action[0].upper() + action[1:]
        return f"{action}. This leaves at least {minimum} available."

    if plan.method is Recommendation.PARTIAL_PAYMENT:
        (_, today_amount), (later_day, later_amount) = plan.payments
        return (f"Pay {money(today_amount, cur)} today and the remaining {money(later_amount, cur)} on "
                f"{long_date(later_day)}. This completes the full request and keeps the {minimum} minimum protected.")

    if plan.method is Recommendation.WAIT:
        return (f"Pay {requested} in full on {long_date(plan.payments[0][0])}. "
                f"Paying earlier would take the balance below the {minimum} minimum.")

    if d.partial_was_possible and d.amount_safe_to_pay > 0 and d.earliest_full_payment is None:
        return (f"Do not proceed with the {requested} request. Although {money(d.amount_safe_to_pay, cur)} "
                f"is available today, the full amount cannot be completed safely within 90 days.")
    return (f"Do not make this payment by {long_date(d.deadline)}. "
            f"None of the available options keeps the {minimum} minimum protected.")


def _changes_phrase(changes: tuple[SpendingChange, ...], currency: str) -> str:
    parts = []
    for c in changes:
        name = c.description[0].lower() + c.description[1:]
        parts.append(f"stop the {name}" if c.new_amount is None
                     else f"reduce the {name} to {money(c.new_amount, currency)}")
    phrase = " and ".join(parts)
    return phrase[0].upper() + phrase[1:] if phrase else phrase
