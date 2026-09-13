import unittest
from datetime import date
from decimal import Decimal

from engine.amendments import Amendment, AmendmentKind as K
from engine.ledger import build_ledger
from engine.models import Direction, Status
from tests.builders import LAST_THREE_MONTHS, START, context, event, every, monthly

CREDIT = {"direction": Direction.CREDIT, "category": "salary"}


def items_of(ledger, category=None, kind=None):
    return [(i.day, i.amount) for i in ledger.items
            if (category is None or i.category == category) and (kind is None or i.kind == kind)]


class RecordedEventsTest(unittest.TestCase):
    def test_settled_history_is_not_replayed(self):
        ledger = build_ledger(context([event("e1", date(2026, 3, 20), "500")]))
        self.assertEqual(ledger.items, ())

    def test_pending_debit_reserved_pending_credit_ignored(self):
        ledger = build_ledger(context([
            event("debit", date(2026, 4, 2), "53", status=Status.PENDING, settlement=date(2026, 4, 5)),
            event("refund", date(2026, 4, 1), "80", status=Status.PENDING, direction=Direction.CREDIT,
                  category="shopping", settlement=date(2026, 4, 6)),
        ]))
        self.assertEqual(items_of(ledger), [(date(2026, 4, 5), Decimal("-53"))])

    def test_failed_cancelled_and_unrealized_ignored(self):
        ledger = build_ledger(context([
            event("f", date(2026, 4, 1), "10", status=Status.FAILED),
            event("c", date(2026, 4, 1), "10", status=Status.CANCELLED),
            event("u", date(2026, 4, 1), "999", status=Status.UNREALIZED, direction=Direction.NON_CASH,
                  category="investment"),
        ]))
        self.assertEqual(ledger.items, ())

    def test_blank_amount_is_skipped_until_an_image_fills_it(self):
        bill = event("bill", date(2026, 4, 1), None, status=Status.PENDING, settlement=date(2026, 4, 9))
        self.assertEqual(build_ledger(context([bill])).items, ())
        self.assertIn("bill", build_ledger(context([bill])).skipped[0])

        fill = Amendment(K.EVENT_AMOUNT, "image_1", event_id="bill", amount=Decimal("75"), currency="EUR")
        self.assertEqual(items_of(build_ledger(context([bill]), [fill])), [(date(2026, 4, 9), Decimal("-75"))])


class RecurringTest(unittest.TestCase):
    def test_debit_series_projected_at_mean(self):
        bills = monthly("util", 6, LAST_THREE_MONTHS, ["100", "110", "120"], category="utilities")
        self.assertEqual(items_of(build_ledger(context(bills)), "utilities"),
                         [(date(2026, 4, 6), Decimal("-110")), (date(2026, 5, 6), Decimal("-110")),
                          (date(2026, 6, 6), Decimal("-110"))])

    def test_inactive_series_not_projected(self):
        old = monthly("gym", 20, [(2025, 10), (2025, 11), (2025, 12)], "30", category="gym")
        self.assertEqual(build_ledger(context(old)).items, ())

    def test_variable_income_projected_at_lowest_amount(self):
        pay = monthly("pay", 24, LAST_THREE_MONTHS, ["1441", "1037.52", "1037.52"], **CREDIT)
        self.assertEqual({x for _, x in items_of(build_ledger(context(pay)), "salary")}, {Decimal("1037.52")})

    def test_scheduled_salary_replaces_series_month_and_series_continues(self):
        events = monthly("pay", 15, LAST_THREE_MONTHS, "2000", **CREDIT) + [
            event("next", date(2026, 4, 15), "2000", status=Status.SCHEDULED, **CREDIT)]
        self.assertEqual([d for d, _ in items_of(build_ledger(context(events)), "salary")],
                         [date(2026, 4, 15), date(2026, 5, 15), date(2026, 6, 15)])

    def test_scheduled_salary_repeats_when_no_salary_series(self):
        events = [event("first", date(2026, 3, 15), "900", **CREDIT),
                  event("next", date(2026, 4, 15), "2000", status=Status.SCHEDULED, **CREDIT)]
        self.assertEqual(items_of(build_ledger(context(events)), "salary"),
                         [(date(2026, 4, 15), Decimal("2000")), (date(2026, 5, 15), Decimal("2000")),
                          (date(2026, 6, 15), Decimal("2000"))])

    def test_foreign_salary_converted_with_latest_earlier_rate_when_projected(self):
        events = [event("next", date(2026, 4, 15), "100", status=Status.SCHEDULED, currency="USD", **CREDIT)]
        rates = [(date(2026, 4, 15), "USD", "EUR", Decimal("0.9"))]
        salary = items_of(build_ledger(context(events, rates=rates)), "salary")
        self.assertEqual(salary[0], (date(2026, 4, 15), Decimal("90.0")))
        self.assertEqual(salary[1], (date(2026, 5, 15), Decimal("90.0")))


class CadenceTest(unittest.TestCase):
    def test_fixed_cadence_projected_at_smallest_amount(self):
        groceries = every("g", date(2026, 3, 7), 10, ["80", "90", "70"])  # last on 03-27
        days = items_of(build_ledger(context(groceries)), "groceries")
        self.assertEqual(days[0], (date(2026, 4, 6), Decimal("-70")))
        self.assertEqual(days[-1][0], date(2026, 6, 25))

    def test_cadence_occurrence_on_request_day_not_reserved(self):
        groceries = every("g", date(2026, 3, 14), 10, ["80", "90", "70"])  # next would be 04-03 = START
        days = [d for d, _ in items_of(build_ledger(context(groceries)), "groceries")]
        self.assertEqual(days[0], date(2026, 4, 13))

    def test_extra_same_day_purchase_does_not_break_cadence(self):
        # Weekly groceries plus a one-off bulk buy on the same day as a regular shop.
        weekly = every("g", date(2026, 3, 6), 7, ["80", "90", "70", "85"])  # last on 03-27
        bulk = event("bulk", date(2026, 3, 20), "4000")
        days = items_of(build_ledger(context(weekly + [bulk])), "groceries")
        self.assertEqual(days[0], (date(2026, 4, 10), Decimal("-70")))

    def test_mostly_regular_cadence_is_projected(self):
        # Gaps 7, 7, 7, 10: the dominant gap covers 75% of gaps.
        dates = [date(2026, 3, 1), date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 22), date(2026, 4, 1)]
        shops = [event(f"g{i}", d, "50") for i, d in enumerate(dates)]
        self.assertEqual(items_of(build_ledger(context(shops)), "groceries")[0][0], date(2026, 4, 8))

    def test_irregular_spending_not_projected(self):
        dining = [event("a", date(2026, 3, 1), "50", category="dining"),
                  event("b", date(2026, 3, 9), "50", category="dining"),
                  event("c", date(2026, 3, 20), "50", category="dining")]
        self.assertEqual(build_ledger(context(dining)).items, ())

    def test_linked_lifecycle_rows_do_not_form_a_cadence(self):
        rows = every("x", date(2026, 3, 7), 10, ["80", "90", "70"], linked="event_0")
        self.assertEqual(build_ledger(context(rows)).items, ())


class AmendmentTest(unittest.TestCase):
    def setUp(self):
        self.salary = monthly("pay", 15, LAST_THREE_MONTHS, "2000", **CREDIT)

    def salaries(self, *amendments):
        return items_of(build_ledger(context(self.salary), list(amendments)), "salary")

    def test_salary_amount_from_effective_date(self):
        a = Amendment(K.SALARY_AMOUNT, "m1", effective_date=date(2026, 5, 1), amount=Decimal("1500"), currency="EUR")
        self.assertEqual([x for _, x in self.salaries(a)], [Decimal("2000"), Decimal("1500"), Decimal("1500")])

    def test_salary_day_moves_payday(self):
        a = Amendment(K.SALARY_DAY, "m1", effective_date=date(2026, 4, 23))
        self.assertEqual([d for d, _ in self.salaries(a)], [date(2026, 4, 23), date(2026, 5, 23), date(2026, 6, 23)])

    def test_income_end_drops_later_salary(self):
        a = Amendment(K.INCOME_END, "m1", effective_date=date(2026, 4, 30))
        self.assertEqual([d for d, _ in self.salaries(a)], [date(2026, 4, 15)])

    def test_salary_start_adds_monthly_income(self):
        a = Amendment(K.SALARY_START, "m1", effective_date=date(2026, 4, 20), amount=Decimal("1661"), currency="EUR")
        ledger = build_ledger(context([]), [a])
        self.assertEqual(items_of(ledger, "salary"), [(date(2026, 4, 20), Decimal("1661")),
                                                      (date(2026, 5, 20), Decimal("1661")),
                                                      (date(2026, 6, 20), Decimal("1661"))])

    def test_confirmed_credit_added_once(self):
        a = Amendment(K.CONFIRMED_CREDIT, "m1", effective_date=date(2026, 4, 15), amount=Decimal("300"), currency="EUR")
        self.assertEqual(items_of(build_ledger(context([]), [a])), [(date(2026, 4, 15), Decimal("300"))])

    def test_expense_change_pct(self):
        # Rent on the 2nd must include April to still be active on 04-03.
        rent = monthly("rent", 2, [(2026, 2), (2026, 3), (2026, 4)], "1000", category="rent")
        a = Amendment(K.EXPENSE_CHANGE_PCT, "m1", effective_date=date(2026, 6, 1), category="rent", percent=Decimal("12"))
        self.assertEqual([x for _, x in items_of(build_ledger(context(rent), [a]), "rent")],
                         [Decimal("-1000"), Decimal("-1120.00"), Decimal("-1120.00")])

    def test_amendment_requires_its_fields(self):
        with self.assertRaises(ValueError):
            Amendment(K.SALARY_AMOUNT, "m1", effective_date=START)


if __name__ == "__main__":
    unittest.main()
