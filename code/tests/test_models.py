import unittest
from datetime import date
from decimal import Decimal

from engine.models import Flexibility, PaymentMethod, PaymentOption, Profile, Status


def make_profile(methods: set[PaymentMethod], max_months: int | None) -> Profile:
    return Profile(
        user_id="user_x",
        home_currency="IDR",
        current_available_balance=Decimal("100"),
        minimum_balance_to_keep=Decimal("10"),
        financial_priorities=(),
        protected_categories=frozenset(),
        reducible_categories=frozenset(),
        stoppable_categories=frozenset(),
        payment_methods=frozenset(methods),
        max_installment_months=max_months,
    )


class EnumTest(unittest.TestCase):
    def test_unknown_status_raises(self):
        with self.assertRaises(ValueError):
            Status("estimated")

    def test_flexibility_capabilities(self):
        self.assertTrue(Flexibility.REDUCIBLE_OR_STOPPABLE.can_reduce)
        self.assertTrue(Flexibility.REDUCIBLE_OR_STOPPABLE.can_stop)
        self.assertFalse(Flexibility.STOPPABLE.can_reduce)
        self.assertFalse(Flexibility.FIXED.can_stop)


class ProfileTest(unittest.TestCase):
    def test_blank_max_months_rejects_installments(self):
        profile = make_profile({PaymentMethod.INSTALLMENTS}, None)
        self.assertFalse(profile.accepts(PaymentMethod.INSTALLMENTS))

    def test_accepts_listed_method_only(self):
        profile = make_profile({PaymentMethod.PARTIAL_PAYMENT, PaymentMethod.INSTALLMENTS}, 7)
        self.assertTrue(profile.accepts(PaymentMethod.INSTALLMENTS))
        self.assertFalse(profile.accepts(PaymentMethod.FULL_PAYMENT))


class PaymentOptionTest(unittest.TestCase):
    def test_schedule_matches_sample_request_02(self):
        option = PaymentOption(
            payment_option_id="payment_option_05",
            request_id="request_02",
            method=PaymentMethod.INSTALLMENTS,
            payment_amount=Decimal("15952906.67"),
            number_of_payments=3,
            first_payment_date=date(2025, 8, 8),
            payment_frequency_days=30,
            financing_fee=Decimal("1840720.01"),
            total_payable_amount=Decimal("47858720.01"),
        )
        self.assertEqual(
            [d for d, _ in option.schedule()],
            [date(2025, 8, 8), date(2025, 9, 7), date(2025, 10, 7)],
        )

    def test_id_number_is_numeric(self):
        def option(option_id: str) -> PaymentOption:
            return PaymentOption(option_id, "r", PaymentMethod.FULL_PAYMENT, Decimal("1"), 1,
                                 date(2025, 1, 1), None, Decimal("0"), Decimal("1"))

        self.assertLess(option("payment_option_99").id_number, option("payment_option_100").id_number)

    def test_recurring_option_without_frequency_raises(self):
        with self.assertRaises(ValueError):
            PaymentOption("payment_option_01", "r", PaymentMethod.INSTALLMENTS, Decimal("1"), 3,
                          date(2025, 1, 1), None, Decimal("0"), Decimal("3"))


if __name__ == "__main__":
    unittest.main()
