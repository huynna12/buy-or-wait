import unittest
from datetime import date
from decimal import Decimal

from engine.currency import ExchangeRate, MissingRateError, RateTable

RATES = RateTable([ExchangeRate(date(2024, 3, 15), "USD", "IDR", Decimal("15833.33"))])


class RateTableTest(unittest.TestCase):
    def test_same_currency_is_identity(self):
        self.assertEqual(RATES.convert(Decimal("5"), "IDR", "IDR", date(2000, 1, 1)), Decimal("5"))

    def test_converts_in_stated_direction_on_date(self):
        self.assertEqual(
            RATES.convert(Decimal("1800"), "USD", "IDR", date(2024, 3, 15)),
            Decimal("28499994.00"),
        )

    def test_missing_date_raises(self):
        with self.assertRaises(MissingRateError):
            RATES.convert(Decimal("1"), "USD", "IDR", date(2024, 3, 14))

    def test_reverse_direction_is_not_inferred(self):
        with self.assertRaises(MissingRateError):
            RATES.convert(Decimal("1"), "IDR", "USD", date(2024, 3, 15))

    def test_conflicting_duplicate_rows_raise(self):
        with self.assertRaises(ValueError):
            RateTable([
                ExchangeRate(date(2024, 3, 15), "USD", "IDR", Decimal("1")),
                ExchangeRate(date(2024, 3, 15), "USD", "IDR", Decimal("2")),
            ])


if __name__ == "__main__":
    unittest.main()
