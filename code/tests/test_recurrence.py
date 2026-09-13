import unittest
from datetime import date
from decimal import Decimal

from engine.models import Direction, Event, EventType, Flexibility, Status
from engine.recurrence import detect_series


def make_event(event_id: str, day: date, *, description: str = "Streaming subscription",
               status: Status = Status.SETTLED, amount: str | None = "47") -> Event:
    return Event(
        event_id=event_id,
        user_id="user_x",
        event_type=EventType.SUBSCRIPTION,
        description=description,
        category="streaming",
        direction=Direction.DEBIT,
        amount=Decimal(amount) if amount is not None else None,
        currency="USD",
        event_date=day,
        settlement_date=day,
        status=status,
        linked_event_id=None,
        flexibility=Flexibility.REDUCIBLE_OR_STOPPABLE,
        minimum_allowed_amount=Decimal("23.5"),
    )


def monthly(day: int, months: list[tuple[int, int]], **kwargs) -> list[Event]:
    return [make_event(f"event_{i}", date(y, m, day), **kwargs) for i, (y, m) in enumerate(months)]


class DetectSeriesTest(unittest.TestCase):
    def test_detects_consecutive_monthly_series(self):
        events = monthly(9, [(2025, 12), (2026, 1), (2026, 2), (2026, 3)])
        [series] = detect_series(reversed(events))  # input order must not matter
        self.assertEqual(series.day_of_month, 9)
        self.assertEqual(series.last_event.event_id, "event_3")
        self.assertTrue(series.has_constant_amount)

    def test_needs_three_occurrences(self):
        self.assertEqual(detect_series(monthly(9, [(2026, 1), (2026, 2)])), [])

    def test_skipped_month_is_not_a_series(self):
        self.assertEqual(detect_series(monthly(9, [(2026, 1), (2026, 2), (2026, 4)])), [])

    def test_different_days_are_not_a_series(self):
        events = [make_event("a", date(2026, 1, 5)), make_event("b", date(2026, 2, 5)),
                  make_event("c", date(2026, 3, 6))]
        self.assertEqual(detect_series(events), [])

    def test_only_settled_events_count(self):
        events = monthly(9, [(2026, 1), (2026, 2)]) + [
            make_event("p", date(2026, 3, 9), status=Status.PENDING)]
        self.assertEqual(detect_series(events), [])

    def test_month_end_series_survives_february(self):
        events = [make_event("a", date(2024, 1, 31)), make_event("b", date(2024, 2, 29)),
                  make_event("c", date(2024, 3, 31))]
        [series] = detect_series(events)
        self.assertEqual(series.day_of_month, 31)
        self.assertEqual(series.next_after(date(2024, 3, 31)), date(2024, 4, 30))

    def test_blank_amount_is_skipped_not_zeroed(self):
        events = monthly(15, [(2019, 6), (2019, 7)]) + [
            make_event("blank", date(2019, 8, 15), amount=None)]
        [series] = detect_series(events)
        self.assertEqual(series.amounts, (Decimal("47"), Decimal("47")))


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        [self.series] = detect_series(monthly(9, [(2025, 12), (2026, 1), (2026, 2), (2026, 3)]))

    def test_is_active_until_an_occurrence_is_missed(self):
        self.assertTrue(self.series.is_active(date(2026, 4, 3)))
        self.assertTrue(self.series.is_active(date(2026, 4, 9)))
        self.assertFalse(self.series.is_active(date(2026, 4, 10)))

    def test_occurrences_between_is_inclusive(self):
        self.assertEqual(
            self.series.occurrences_between(date(2026, 4, 9), date(2026, 6, 9)),
            [date(2026, 4, 9), date(2026, 5, 9), date(2026, 6, 9)],
        )


if __name__ == "__main__":
    unittest.main()
