"""Find the smallest permitted spending changes that make a plan safe.

A change targets the latest real event behind a projected recurring item. It
is legal only when the category is not protected, the event's flexibility
allows the action, and the user listed the category as one they will reduce or
stop. Stopping and reducing the same event are mutually exclusive.

Among safe combinations of up to three changes, the one removing the least
total spending wins (then fewer changes): ask the user to give up as little as
possible. This matches the published samples, which prefer "stop a small
subscription and reduce another" over "stop the bigger one".
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from itertools import combinations
from typing import Sequence

from engine.forecast import build_forecast, plan_is_safe
from engine.ledger import CashItem, Ledger
from engine.models import Profile, RequestContext
from engine.plans import ZERO, SpendingChange

MAX_CHANGES = 3
CHANGEABLE_KINDS = ("series", "variable")


def change_options(ledger: Ledger, profile: Profile) -> list[SpendingChange]:
    items_by_event: dict[str, list[CashItem]] = defaultdict(list)
    for item in ledger.items:
        if item.kind in CHANGEABLE_KINDS and item.amount < 0 and item.target_event_id:
            items_by_event[item.target_event_id].append(item)

    options = []
    for event_id, items in items_by_event.items():
        event = ledger.event(event_id)
        if event is None or event.category in profile.protected_categories:
            continue
        if event.flexibility.can_stop and event.category in profile.stoppable_categories:
            spend = sum((-i.amount for i in items), ZERO)
            options.append(SpendingChange("stop", event_id, None, event.description, event.category, spend))
        floor = event.minimum_allowed_amount
        if event.flexibility.can_reduce and event.category in profile.reducible_categories and floor is not None:
            savings = sum((max(ZERO, -i.amount - floor) for i in items), ZERO)
            if savings > 0:
                options.append(SpendingChange("reduce_to", event_id, floor, event.description,
                                              event.category, savings))
    return sorted(options, key=lambda c: (c.event_number, c.event_id, c.action))


def apply_changes(items: Sequence[CashItem], changes: Sequence[SpendingChange]) -> list[CashItem]:
    by_event = {c.event_id: c for c in changes}
    result = []
    for item in items:
        target = item.target_event_id
        changeable = target is not None and item.kind in CHANGEABLE_KINDS and item.amount < 0
        change = by_event.get(target) if changeable and target is not None else None
        if change is None:
            result.append(item)
        elif change.new_amount is not None:  # reduce_to always carries the new amount
            result.append(dataclasses.replace(item, amount=-min(-item.amount, change.new_amount)))
        # "stop" has no new amount: the item is dropped
    return result


def cheapest_changes(ctx: RequestContext, ledger: Ledger, payments,
                     max_changes: int = MAX_CHANGES) -> tuple[SpendingChange, ...] | None:
    profile = ctx.profile
    options = change_options(ledger, profile)
    best, best_key = None, None
    for size in range(1, max_changes + 1):
        for combo in combinations(options, size):
            if len({c.event_id for c in combo}) < size:
                continue
            key = (sum((c.savings for c in combo), ZERO), size)
            if best_key is not None and key >= best_key:
                continue
            forecast = build_forecast(profile.current_available_balance, profile.minimum_balance_to_keep,
                                      apply_changes(ledger.items, combo), ledger.start)
            if plan_is_safe(forecast, payments):
                best, best_key = combo, key
    return tuple(sorted(best, key=lambda c: (c.event_number, c.event_id))) if best else None
