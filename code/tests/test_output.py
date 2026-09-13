import unittest
from datetime import date
from decimal import Decimal as D

from engine.decide import Affordability as A, Decision
from engine.plans import NOT_RECOMMENDED, Plan, Recommendation as R, SpendingChange
from output.explain import explain, long_date, money
from output.format import changes_text, plain_amount, plan_amount, plan_text, to_row
from output.validate import COLUMNS


def decision(plan, *, currency="EUR", requested="620.4", minimum="800", safe="603.3", earliest=None,
             status=A.AFFORDABLE_WITH_PLAN, deadline=date(2026, 1, 14), partial=False):
    return Decision("request_x", currency, date(2026, 1, 3), deadline, D(requested), D(minimum), D(safe),
                    earliest, status, plan, partial, ())


class FormatTest(unittest.TestCase):
    def test_amount_styles_match_samples(self):
        self.assertEqual([plain_amount(D("620.40")), plain_amount(D("25256.00")), plain_amount(D("0"))],
                         ["620.4", "25256", "0"])
        self.assertEqual([plan_amount(D("620.4")), plan_amount(D("25256")), plan_amount(D("15952906.67"))],
                         ["620.40", "25256", "15952906.67"])

    def test_plan_and_changes_text(self):
        plan = Plan(R.PARTIAL_PAYMENT, ((date(2024, 9, 4), D("28820")), (date(2024, 9, 15), D("10840"))))
        self.assertEqual(plan_text(plan), "2024-09-04:28820|2024-09-15:10840")
        self.assertEqual(plan_text(NOT_RECOMMENDED), "none")
        changes = (SpendingChange("stop", "event_1815", None, "x", "x", D("1")),
                   SpendingChange("reduce_to", "event_1816", D("23.5"), "x", "x", D("1")))
        self.assertEqual(changes_text(changes), "stop:event_1815|reduce_to:event_1816:23.50")
        self.assertEqual(changes_text(()), "none")

    def test_row_has_exact_columns(self):
        row = to_row(decision(NOT_RECOMMENDED, status=A.NOT_AFFORDABLE), "text")
        self.assertEqual(tuple(row), COLUMNS)
        self.assertEqual(row["earliest_date_for_full_payment"], "")


class ExplainTest(unittest.TestCase):
    """Each expected string is the organisers' sample explanation."""

    def test_helpers(self):
        self.assertEqual(money(D("15952906.67"), "IDR"), "IDR 15,952,906.67")
        self.assertEqual(money(D("1300"), "EUR"), "EUR 1,300")
        self.assertEqual(long_date(date(2025, 8, 8)), "8 August 2025")

    def test_affordable_now(self):
        d = decision(Plan(R.FULL_PAYMENT, ((date(2024, 3, 3), D("25256")),)), currency="ZAR",
                     requested="25256", minimum="18000", status=A.AFFORDABLE_NOW)
        self.assertEqual(explain(d), "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days.")

    def test_installments(self):
        payments = tuple((day, D("15952906.67")) for day in (date(2025, 8, 8), date(2025, 9, 7), date(2025, 10, 7)))
        d = decision(Plan(R.INSTALLMENTS, payments, "payment_option_05", 5), currency="IDR", minimum="29158400")
        self.assertEqual(explain(d), "Use 3 installments of IDR 15,952,906.67, starting 8 August 2025. "
                                     "This leaves at least IDR 29,158,400 available.")

    def test_wait(self):
        d = decision(Plan(R.WAIT, ((date(2019, 11, 15), D("5491000")),)), currency="IDR", requested="5491000",
                     minimum="2668700", status=A.AFFORDABLE_LATER)
        self.assertEqual(explain(d), "Pay IDR 5,491,000 in full on 15 November 2019. "
                                     "Paying earlier would take the balance below the IDR 2,668,700 minimum.")

    def test_partial(self):
        plan = Plan(R.PARTIAL_PAYMENT, ((date(2024, 9, 4), D("28820")), (date(2024, 9, 15), D("10840"))))
        d = decision(plan, currency="INR", requested="39660", minimum="92800")
        self.assertEqual(explain(d), "Pay INR 28,820 today and the remaining INR 10,840 on 15 September 2024. "
                                     "This completes the full request and keeps the INR 92,800 minimum protected.")

    def test_full_payment_with_changes(self):
        changes = (SpendingChange("stop", "event_1815", None, "Online backup subscription", "cloud_storage", D("1")),
                   SpendingChange("reduce_to", "event_1816", D("23.5"), "Streaming subscription", "streaming", D("1")))
        d = decision(Plan(R.FULL_PAYMENT, ((date(2026, 4, 3), D("1574.4")),), changes=changes), currency="USD",
                     requested="1574.4", minimum="1800")
        self.assertEqual(explain(d), "Stop the online backup subscription and reduce the streaming subscription "
                                     "to USD 23.50, then pay USD 1,574.40 today. This leaves at least USD 1,800 available.")

    def test_not_recommended_variants(self):
        d = decision(NOT_RECOMMENDED, currency="ZAR", requested="15488", minimum="13100", safe="737",
                     status=A.NOT_AFFORDABLE, deadline=date(2026, 1, 12))
        self.assertEqual(explain(d), "Do not make this payment by 12 January 2026. "
                                     "None of the available options keeps the ZAR 13,100 minimum protected.")
        d = decision(NOT_RECOMMENDED, currency="EUR", requested="5414.2", safe="597.74", status=A.NOT_AFFORDABLE,
                     partial=True)
        self.assertEqual(explain(d), "Do not proceed with the EUR 5,414.20 request. Although EUR 597.74 is "
                                     "available today, the full amount cannot be completed safely within 90 days.")


if __name__ == "__main__":
    unittest.main()
