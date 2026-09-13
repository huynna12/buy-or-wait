import unittest
from datetime import date
from decimal import Decimal as D

from engine.ledger import build_ledger
from engine.models import Direction, Flexibility as F
from engine.spending import apply_changes, change_options, cheapest_changes
from tests.builders import LAST_THREE_MONTHS, START, context, monthly, profile

# Headroom 200. Streaming 47 (04-09) and backup 11 (04-12) fall before a large
# salary on 04-15, so paying 173 today needs at least 31 of savings.
STREAMING = monthly("event_20", 9, LAST_THREE_MONTHS, "47", description="Streaming subscription",
                    category="streaming", flexibility=F.REDUCIBLE_OR_STOPPABLE, minimum="23.5")
BACKUP = monthly("event_10", 12, LAST_THREE_MONTHS, "11", description="Online backup subscription",
                 category="cloud_storage", flexibility=F.STOPPABLE)
RENT = monthly("event_30", 1, [(2026, 2), (2026, 3), (2026, 4)], "500", description="Rent", category="rent",
               flexibility=F.REDUCIBLE_OR_STOPPABLE, minimum="1")
SALARY = monthly("event_40", 15, LAST_THREE_MONTHS, "5000", category="salary", direction=Direction.CREDIT)
PROFILE = profile("2000", "1800", protected=("rent",), reduce=("streaming", "rent"),
                  stop=("streaming", "cloud_storage", "rent"))
CTX = context(STREAMING + BACKUP + RENT + SALARY, prof=PROFILE)
LEDGER = build_ledger(CTX)


def described(changes):
    return [(c.action, c.event_id, c.new_amount) for c in changes]


class OptionsTest(unittest.TestCase):
    def test_only_permitted_unprotected_flexible_events(self):
        self.assertEqual(described(change_options(LEDGER, PROFILE)), [
            ("stop", "event_10_2", None),
            ("reduce_to", "event_20_2", D("23.5")),
            ("stop", "event_20_2", None),
        ])

    def test_category_must_be_listed_by_user(self):
        strict = profile("2000", "1800", stop=("cloud_storage",))
        self.assertEqual(described(change_options(LEDGER, strict)), [("stop", "event_10_2", None)])

    def test_apply_stop_and_reduce(self):
        stop, reduce = change_options(LEDGER, PROFILE)[0], change_options(LEDGER, PROFILE)[1]
        changed = apply_changes(LEDGER.items, [stop, reduce])
        self.assertFalse(any(i.category == "cloud_storage" for i in changed))
        self.assertEqual({i.amount for i in changed if i.category == "streaming"}, {D("-23.5")})


class CheapestTest(unittest.TestCase):
    def test_least_total_savings_wins_over_fewer_changes(self):
        # stop streaming alone saves 141 over the window; stop backup + reduce
        # streaming saves 103.5, so that pair is chosen (as in sample request_21).
        changes = cheapest_changes(CTX, LEDGER, [(START, D("173"))])
        self.assertEqual(described(changes), [("stop", "event_10_2", None), ("reduce_to", "event_20_2", D("23.5"))])

    def test_none_when_no_combination_is_safe(self):
        self.assertIsNone(cheapest_changes(CTX, LEDGER, [(START, D("260"))]))

    def test_same_event_is_never_stopped_and_reduced(self):
        changes = cheapest_changes(CTX, LEDGER, [(START, D("200"))])
        ids = [c.event_id for c in changes]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
