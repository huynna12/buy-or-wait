import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from engine.forecast import build_forecast, earliest_full_payment, plan_is_safe, safe_amount_today
from engine.ledger import CashItem
from tests.builders import START


def item(days_after: int, amount: str) -> CashItem:
    return CashItem(START + timedelta(days=days_after), D(amount), "x", "x", "series")


# headroom: 900 until day 4, 600 from day 5 (rent), 2600 from day 12 (salary)
ITEMS = [item(5, "-300"), item(12, "2000")]
FORECAST = build_forecast(D("1000"), D("100"), ITEMS, START)


class CurveTest(unittest.TestCase):
    def test_headroom_accumulates_items(self):
        self.assertEqual(FORECAST.headroom[0], D("900"))
        self.assertEqual(FORECAST.headroom[5], D("600"))
        self.assertEqual(FORECAST.headroom[90], D("2600"))
        self.assertEqual(len(FORECAST.headroom), 91)

    def test_items_outside_window_ignored(self):
        f = build_forecast(D("1000"), D("100"), [item(-1, "-50"), item(91, "-50")], START)
        self.assertEqual(set(f.headroom), {D("900")})

    def test_lowest_point(self):
        self.assertEqual((FORECAST.lowest, FORECAST.lowest_day), (D("600"), START + timedelta(days=5)))


class SafeAmountTest(unittest.TestCase):
    def test_is_minimum_headroom(self):
        self.assertEqual(safe_amount_today(FORECAST, D("5000")), D("600"))

    def test_capped_at_requested_amount(self):
        self.assertEqual(safe_amount_today(FORECAST, D("250")), D("250"))

    def test_never_negative(self):
        f = build_forecast(D("100"), D("500"), [], START)
        self.assertEqual(safe_amount_today(f, D("50")), D("0"))


class EarliestDateTest(unittest.TestCase):
    def test_today_when_affordable_now(self):
        self.assertEqual(earliest_full_payment(FORECAST, D("600")), START)

    def test_later_dip_blocks_earlier_day(self):
        # 800 fits on day 0 (900) but not on day 5 (600): must wait for salary.
        self.assertEqual(earliest_full_payment(FORECAST, D("800")), START + timedelta(days=12))

    def test_none_when_never_safe(self):
        self.assertIsNone(earliest_full_payment(FORECAST, D("3000")))


class PlanSafetyTest(unittest.TestCase):
    def test_payments_accumulate(self):
        self.assertTrue(plan_is_safe(FORECAST, [(START, D("300")), (START + timedelta(days=1), D("300"))]))
        self.assertFalse(plan_is_safe(FORECAST, [(START, D("300")), (START + timedelta(days=1), D("301"))]))

    def test_payment_after_window_not_checked(self):
        self.assertTrue(plan_is_safe(FORECAST, [(START + timedelta(days=120), D("99999"))]))

    def test_payment_before_start_is_unsafe(self):
        self.assertFalse(plan_is_safe(FORECAST, [(START - timedelta(days=1), D("1"))]))


if __name__ == "__main__":
    unittest.main()
