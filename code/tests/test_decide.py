import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from engine.decide import Affordability as A, decide
from engine.models import Direction, Flexibility, Status
from engine.plans import Recommendation as R
from tests.builders import LAST_THREE_MONTHS, START, context, event, monthly, option, profile, request

SALARY_DAY = date(2026, 4, 15)
# Headroom 900 today, 600 after a pending debit on 04-05, +1000 each month from 04-15.
EVENTS = [
    event("pending", date(2026, 4, 2), "300", status=Status.PENDING, settlement=date(2026, 4, 5)),
    event("salary", SALARY_DAY, "1000", status=Status.SCHEDULED, direction=Direction.CREDIT, category="salary"),
]


def run(amount, accepted, *, deadline=date(2026, 4, 30), partial=False, max_months=None, options=(), events=EVENTS):
    ctx = context(events, prof=profile("1000", "100", methods=accepted, max_months=max_months,
                                       stop=("streaming",)),
                  req=request(amount, deadline=deadline, partial=partial), options=options)
    return decide(ctx)


class DecideTest(unittest.TestCase):
    def test_affordable_now(self):
        d = run("500", ("full_payment",))
        self.assertEqual((d.status, d.plan.method, d.earliest_full_payment, d.amount_safe_to_pay),
                         (A.AFFORDABLE_NOW, R.FULL_PAYMENT, START, D("500.00")))

    def test_wait_for_salary(self):
        d = run("800", ("full_payment",))
        self.assertEqual((d.status, d.plan.payments, d.amount_safe_to_pay),
                         (A.AFFORDABLE_LATER, ((SALARY_DAY, D("800")),), D("600.00")))

    def test_partial_beats_wait_by_starting_earlier(self):
        d = run("800", ("full_payment", "partial_payment"), partial=True)
        self.assertEqual((d.status, d.plan.method), (A.AFFORDABLE_WITH_PLAN, R.PARTIAL_PAYMENT))
        self.assertEqual(d.plan.payments, ((START, D("600.00")), (SALARY_DAY, D("200.00"))))

    def test_installments_when_full_payment_not_accepted(self):
        opts = (option("payment_option_1", "full_payment", "500", 1, START),
                option("payment_option_2", "installments", "200", 3, START, 20))
        d = run("500", ("installments",), max_months=3, deadline=date(2026, 5, 30), options=opts)
        self.assertEqual((d.status, d.plan.option_id, d.earliest_full_payment),
                         (A.AFFORDABLE_WITH_PLAN, "payment_option_2", START))

    def test_spending_change_when_waiting_misses_deadline(self):
        streaming = monthly("event_5", 4, LAST_THREE_MONTHS, "50", category="streaming",
                            flexibility=Flexibility.STOPPABLE)
        d = run("900", ("full_payment",), deadline=START + timedelta(days=5), events=streaming)
        self.assertEqual((d.status, d.plan.method), (A.AFFORDABLE_WITH_PLAN, R.FULL_PAYMENT))
        self.assertEqual([(c.action, c.event_id) for c in d.plan.changes], [("stop", "event_5_2")])
        # Streaming repeats on 04-04, 05-04 and 06-04, so the lowest headroom is 900 - 150.
        self.assertEqual((d.amount_safe_to_pay, d.earliest_full_payment), (D("750.00"), None))

    def test_not_recommended_fallback(self):
        d = run("5000", ("full_payment",))
        self.assertEqual((d.status, d.plan.method, d.plan.payments), (A.NOT_AFFORDABLE, R.NOT_RECOMMENDED, ()))


if __name__ == "__main__":
    unittest.main()
