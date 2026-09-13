"""Contract checks for one output row, run before output.csv is written.

The validator is independent of how the engine decided: it only checks that a
row is a legal answer for its request. It returns a list of problems (empty
means valid) instead of raising, so a full run can report every bad row.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from engine.models import PaymentMethod, RequestContext

COLUMNS = (
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
)
STATUSES = frozenset({"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"})
METHODS = frozenset({"full_payment", "partial_payment", "installments", "wait", "not_recommended"})
METHODS_BY_STATUS = {
    "affordable_now": {"full_payment"},
    "affordable_with_plan": {"full_payment", "partial_payment", "installments"},
    "affordable_later": {"wait"},
    "not_affordable": {"not_recommended"},
}
MAX_SPENDING_CHANGES = 3


def parse_plan(text: str) -> list[tuple[date, Decimal]]:
    """'none' -> []. Raises ValueError on any malformed entry."""
    if text == "none":
        return []
    plan = []
    for part in text.split("|"):
        day, sep, amount = part.partition(":")
        if not sep:
            raise ValueError(f"plan entry without ':' {part!r}")
        plan.append((date.fromisoformat(day), _decimal(amount)))
    return plan


def parse_changes(text: str) -> list[tuple[str, str, Decimal | None]]:
    """'none' -> []. Each item is (action, event_id, new_amount_or_None)."""
    if text == "none":
        return []
    changes: list[tuple[str, str, Decimal | None]] = []
    for part in text.split("|"):
        pieces = part.split(":")
        if pieces[0] == "stop" and len(pieces) == 2:
            changes.append(("stop", pieces[1], None))
        elif pieces[0] == "reduce_to" and len(pieces) == 3:
            changes.append(("reduce_to", pieces[1], _decimal(pieces[2])))
        else:
            raise ValueError(f"bad spending change {part!r}")
    return changes


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"not a number {text!r}") from None


def validate_row(row: dict[str, str], ctx: RequestContext) -> list[str]:
    request, profile = ctx.request, ctx.profile
    if tuple(row) != COLUMNS:
        return [f"columns must be exactly {COLUMNS}"]
    if row["request_id"] != request.request_id:
        return [f"request_id {row['request_id']} != {request.request_id}"]

    errors: list[str] = []
    status, method = row["affordability_status"], row["recommended_payment_method"]
    if status not in STATUSES:
        errors.append(f"unknown status {status!r}")
    if method not in METHODS:
        errors.append(f"unknown method {method!r}")
    if status in STATUSES and method in METHODS and method not in METHODS_BY_STATUS[status]:
        errors.append(f"method {method} is not valid with status {status}")

    try:
        safe = _decimal(row["amount_safe_to_pay"])
        plan = parse_plan(row["payment_plan"])
        changes = parse_changes(row["spending_changes_needed"])
        earliest = date.fromisoformat(row["earliest_date_for_full_payment"]) \
            if row["earliest_date_for_full_payment"] else None
    except ValueError as exc:
        return errors + [str(exc)]

    if not Decimal(0) <= safe <= request.requested_amount:
        errors.append(f"amount_safe_to_pay {safe} outside [0, {request.requested_amount}]")
    if [d for d, _ in plan] != sorted(d for d, _ in plan):
        errors.append("payment_plan is not chronological")
    if any(amount <= 0 for _, amount in plan):
        errors.append("payment_plan has a non-positive amount")
    if status == "affordable_now" and earliest != request.request_date:
        errors.append("affordable_now requires earliest_date_for_full_payment == request_date")

    errors += _check_plan(method, plan, safe, earliest, ctx)
    errors += _check_changes(method, status, changes, ctx)
    if method in METHODS and method not in ("wait", "not_recommended") \
            and not profile.accepts(PaymentMethod(method)):
        errors.append(f"user does not accept {method}")
    return errors


def _check_plan(method, plan, safe, earliest, ctx: RequestContext) -> list[str]:
    request = ctx.request
    total = sum((amount for _, amount in plan), Decimal(0))
    if method == "not_recommended":
        return [] if not plan else ["not_recommended must have payment_plan none"]
    if method == "full_payment":
        if len(plan) != 1 or plan[0] != (request.request_date, request.requested_amount):
            return ["full_payment must be one payment of requested_amount on request_date"]
        return []
    if method == "wait":
        if earliest is None or plan != [(earliest, request.requested_amount)]:
            return ["wait must be one payment of requested_amount on earliest_date_for_full_payment"]
        return []
    if method == "partial_payment":
        errors = []
        if not request.allows_partial_payment:
            errors.append("request does not allow partial payment")
        if not Decimal(0) < safe < request.requested_amount:
            errors.append("partial_payment needs 0 < amount_safe_to_pay < requested_amount")
        if earliest is None or earliest > request.desired_completion_date:
            errors.append("partial_payment must complete by desired_completion_date")
        if len(plan) != 2 or plan[0] != (request.request_date, safe) or plan[1][0] != earliest:
            errors.append("partial_payment must be [safe on request_date, remainder on earliest date]")
        if total != request.requested_amount:
            errors.append(f"partial_payment sums to {total}, not {request.requested_amount}")
        return errors
    if method == "installments":
        schedules = [list(o.schedule()) for o in ctx.options if o.method is PaymentMethod.INSTALLMENTS]
        return [] if plan in schedules else ["installment plan does not match any supplied option"]
    return []


def _check_changes(method, status, changes, ctx: RequestContext) -> list[str]:
    profile = ctx.profile
    errors = []
    if len(changes) > MAX_SPENDING_CHANGES:
        errors.append(f"more than {MAX_SPENDING_CHANGES} spending changes")
    event_ids = [event_id for _, event_id, _ in changes]
    if len(event_ids) != len(set(event_ids)):
        errors.append("an event is changed more than once")
    if method == "full_payment" and status == "affordable_with_plan" and not changes:
        errors.append("affordable_with_plan full_payment requires spending changes")
    events = {e.event_id: e for e in ctx.events}
    for action, event_id, new_amount in changes:
        event = events.get(event_id)
        if event is None:
            errors.append(f"spending change targets unknown event {event_id}")
            continue
        if event.category in profile.protected_categories:
            errors.append(f"{event_id} is in protected category {event.category}")
        if action == "stop":
            if not event.flexibility.can_stop or event.category not in profile.stoppable_categories:
                errors.append(f"{event_id} may not be stopped")
        else:
            if not event.flexibility.can_reduce or event.category not in profile.reducible_categories:
                errors.append(f"{event_id} may not be reduced")
            elif event.minimum_allowed_amount is not None and new_amount < event.minimum_allowed_amount:
                errors.append(f"{event_id} reduced below minimum_allowed_amount")
    return errors
