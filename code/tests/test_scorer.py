import unittest

from evaluation.scorer import FIELDS, amount_matches, field_matches, normalize_changes, score

ROW = {
    "request_id": "request_19",
    "amount_safe_to_pay": "28820",
    "affordability_status": "affordable_with_plan",
    "recommended_payment_method": "partial_payment",
    "payment_plan": "2024-09-04:28820|2024-09-15:10840",
    "earliest_date_for_full_payment": "2024-09-15",
    "spending_changes_needed": "none",
}


class FieldMatchTest(unittest.TestCase):
    def test_amount_within_one_percent(self):
        self.assertTrue(amount_matches("28820", "28600"))
        self.assertFalse(amount_matches("28820", "28000"))
        self.assertFalse(amount_matches("28820", ""))

    def test_plan_compares_numbers_not_strings(self):
        self.assertTrue(field_matches("payment_plan", "2026-01-03:620.40", "2026-01-03:620.4"))
        self.assertFalse(field_matches("payment_plan", "2026-01-03:620.40", "2026-01-04:620.40"))

    def test_changes_are_order_independent(self):
        self.assertEqual(
            normalize_changes("stop:event_1815|reduce_to:event_1816:23.50"),
            normalize_changes("reduce_to:event_1816:23.5|stop:event_1815"),
        )

    def test_blank_earliest_matches_blank_only(self):
        self.assertTrue(field_matches("earliest_date_for_full_payment", "", ""))
        self.assertFalse(field_matches("earliest_date_for_full_payment", "", "2024-09-15"))


class ScoreTest(unittest.TestCase):
    def test_perfect_prediction(self):
        report = score({"request_19": ROW}, {"request_19": dict(ROW)})
        self.assertEqual(report.fully_correct, 1)
        self.assertEqual(report.mismatches, [])

    def test_missing_prediction_fails_every_field(self):
        report = score({"request_19": ROW}, {})
        self.assertEqual(report.fully_correct, 0)
        self.assertEqual(len(report.mismatches), len(FIELDS))

    def test_one_wrong_field_is_reported(self):
        wrong = dict(ROW, recommended_payment_method="wait")
        report = score({"request_19": ROW}, {"request_19": wrong})
        self.assertEqual(report.correct["recommended_payment_method"], 0)
        self.assertEqual(report.correct["affordability_status"], 1)


if __name__ == "__main__":
    unittest.main()
