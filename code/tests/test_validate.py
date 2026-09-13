import csv
import unittest

from data.loader import DEFAULT_ROOT, Dataset, build_context
from output.validate import COLUMNS, validate_row

DATASET = Dataset()
CONTEXTS = {r.request_id: build_context(DATASET, r) for r in DATASET.sample_requests}
with open(DEFAULT_ROOT / "sample_requests.csv", newline="", encoding="utf-8") as f:
    SAMPLES = {row["request_id"]: {c: row[c] for c in COLUMNS} for row in csv.DictReader(f)}


def edited(request_id: str, **changes: str) -> dict[str, str]:
    return {**SAMPLES[request_id], **changes}


class GroundTruthTest(unittest.TestCase):
    def test_every_published_sample_row_is_valid(self):
        # The validator must accept the organisers' own answers.
        for request_id, row in SAMPLES.items():
            with self.subTest(request_id):
                self.assertEqual(validate_row(row, CONTEXTS[request_id]), [])


class RejectionTest(unittest.TestCase):
    def assert_invalid(self, request_id: str, row: dict[str, str], fragment: str):
        errors = validate_row(row, CONTEXTS[request_id])
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_amount_above_requested(self):
        self.assert_invalid("request_01", edited("request_01", amount_safe_to_pay="99999999"), "outside")

    def test_status_method_mismatch(self):
        self.assert_invalid("request_05", edited("request_05", recommended_payment_method="wait"), "not valid with")

    def test_partial_must_sum_to_requested(self):
        row = edited("request_19", payment_plan="2024-09-04:28820|2024-09-15:10000")
        self.assert_invalid("request_19", row, "sums to")

    def test_installments_must_match_an_option(self):
        row = edited("request_02", payment_plan="2025-08-08:15952906.67|2025-09-08:15952906.67|2025-10-07:15952906.67")
        self.assert_invalid("request_02", row, "does not match")

    def test_affordable_now_needs_request_date(self):
        self.assert_invalid("request_01", edited("request_01", earliest_date_for_full_payment="2024-03-04"), "affordable_now")

    def test_protected_category_cannot_change(self):
        # event_1818 is user_21's rent, a protected category.
        self.assert_invalid("request_21", edited("request_21", spending_changes_needed="stop:event_1818"), "protected")

    def test_reduce_below_minimum(self):
        row = edited("request_21", spending_changes_needed="stop:event_1815|reduce_to:event_1816:10")
        self.assert_invalid("request_21", row, "below minimum")

    def test_user_must_accept_method(self):
        # user_12 does not accept full_payment.
        row = edited("request_12", affordability_status="affordable_now", recommended_payment_method="full_payment",
                     payment_plan="2026-04-05:65164")
        self.assert_invalid("request_12", row, "does not accept")

    def test_malformed_plan(self):
        self.assert_invalid("request_01", edited("request_01", payment_plan="2024-03-03-25256"), "without ':'")


if __name__ == "__main__":
    unittest.main()
