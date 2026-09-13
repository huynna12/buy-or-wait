import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from engine.forecast import build_forecast
from engine.ledger import CashItem
from engine.plans import Plan, Recommendation as R, SpendingChange, choose, eligible_plans, rank_key
from tests.builders import START, context, option, profile, request

DEADLINE = START + timedelta(days=60)
LATER = START + timedelta(days=12)


def methods(plans):
    return sorted((p.method.value, p.option_id) for p in plans)


class EligibilityTest(unittest.TestCase):
    def ctx(self, accepted, *, max_months=None, partial=True, options=()):
        return context(prof=profile(methods=accepted, max_months=max_months),
                       req=request("800", deadline=DEADLINE, partial=partial), options=options)

    def test_full_and_wait_need_full_payment_acceptance(self):
        self.assertEqual(methods(eligible_plans(self.ctx(("full_payment",)), D("600"), LATER)),
                         [("full_payment", None), ("wait", None)])
        self.assertEqual(eligible_plans(self.ctx(("partial_payment",), partial=False), D("600"), LATER), [])

    def test_no_wait_when_affordable_today(self):
        self.assertEqual(methods(eligible_plans(self.ctx(("full_payment",)), D("800"), START)),
                         [("full_payment", None)])

    def test_partial_rules(self):
        accepted = ("partial_payment",)
        [partial] = eligible_plans(self.ctx(accepted), D("600"), LATER)
        self.assertEqual(partial.payments, ((START, D("600")), (LATER, D("200"))))
        self.assertEqual(eligible_plans(self.ctx(accepted, partial=False), D("600"), LATER), [])
        self.assertEqual(eligible_plans(self.ctx(accepted), D("0"), LATER), [])
        self.assertEqual(eligible_plans(self.ctx(accepted), D("600"), None), [])

    def test_installments_respect_max_months(self):
        opts = (option("payment_option_2", "installments", "300", 3, START, 30),
                option("payment_option_3", "installments", "100", 9, START, 30))
        ctx = self.ctx(("installments",), max_months=3, options=opts)
        self.assertEqual(methods(eligible_plans(ctx, D("0"), None)), [("installments", "payment_option_2")])
        blank = self.ctx(("installments",), max_months=None, options=opts)
        self.assertEqual(eligible_plans(blank, D("0"), None), [])

    def test_plans_after_deadline_are_dropped(self):
        late = (option("payment_option_2", "installments", "300", 3, START + timedelta(days=45), 30),)
        ctx = self.ctx(("installments",), max_months=6, options=late)
        self.assertEqual(eligible_plans(ctx, D("0"), None), [])


class RankingTest(unittest.TestCase):
    def plan(self, payments, number=0, changes=()):
        return Plan(R.INSTALLMENTS, tuple(payments), f"payment_option_{number}", number, changes)

    def best(self, *plans):
        return min(plans, key=lambda p: rank_key(p, DEADLINE))

    def test_no_changes_beats_cheaper_plan_with_changes(self):
        change = SpendingChange("stop", "event_1", None, "x", "x", D("5"))
        cheap = self.plan([(START, D("100"))], 1, (change,))
        pricey = self.plan([(START, D("150"))], 2)
        self.assertIs(self.best(cheap, pricey), pricey)

    def test_least_paid_then_earlier_then_fewer_then_lowest_id(self):
        a = self.plan([(START, D("100"))], 9)
        b = self.plan([(START, D("110"))], 1)
        self.assertIs(self.best(a, b), a)
        early = self.plan([(START, D("100"))], 9)
        late = self.plan([(LATER, D("100"))], 1)
        self.assertIs(self.best(early, late), early)
        one = self.plan([(START, D("100"))], 9)
        two = self.plan([(START, D("50")), (START, D("50"))], 1)
        self.assertIs(self.best(one, two), one)
        self.assertEqual(self.best(self.plan([(START, D("1"))], 10), self.plan([(START, D("1"))], 9)).option_number, 9)


class ChooseTest(unittest.TestCase):
    def test_picks_best_safe_plan(self):
        forecast = build_forecast(D("1000"), D("100"), [CashItem(LATER, D("1000"), "pay", "salary", "series")], START)
        today = Plan(R.FULL_PAYMENT, ((START, D("950")),))
        wait = Plan(R.WAIT, ((LATER, D("950")),))
        self.assertIs(choose([today, wait], forecast, DEADLINE), wait)
        self.assertIsNone(choose([today], forecast, DEADLINE))


if __name__ == "__main__":
    unittest.main()
