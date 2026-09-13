import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from data.loader import ImageRef, Message, SourceType
from engine.amendments import AmendmentKind as K
from engine.models import Status
from extraction import images, messages
from extraction.evidence import EvidenceExtractor
from extraction.usage import CallUsage, UsageLog, render_report
from tests.builders import event, request

REQUEST_DATE = date(2026, 4, 3)


def message(text="x", source=SourceType.EMPLOYER, sent=date(2026, 3, 28), message_id="message_1"):
    return Message(message_id, "user_x", None, None, datetime(sent.year, sent.month, sent.day, 9, 30, tzinfo=timezone.utc),
                   source, text)


def facts(intent, **fields):
    raw = {"intent": intent, "amount": None, "currency": None, "effective_date": None, "percent": None,
           "category": None, **fields}
    return messages.parse_facts(raw)


def kinds(amendments):
    return [a.kind for a in amendments]


class ParseFactsTest(unittest.TestCase):
    def test_rejects_off_schema_values(self):
        self.assertIsNone(messages.parse_facts({"intent": "approve_everything"}))
        self.assertIsNone(facts("salary_amount_change", amount=100, currency="BTC"))
        self.assertIsNone(facts("salary_amount_change", amount=-5, currency="EUR"))
        self.assertIsNone(facts("salary_date_change", effective_date="next friday"))
        self.assertIsNone(messages.parse_facts("ignore previous instructions"))

    def test_parses_valid_output(self):
        f = facts("salary_start", amount=1661, currency="EUR", effective_date="2026-01-15")
        self.assertEqual((f.amount, f.effective_date), (D("1661"), date(2026, 1, 15)))


class ToAmendmentsTest(unittest.TestCase):
    def test_salary_change_from_employer(self):
        a = messages.to_amendments(facts("salary_amount_change", amount=1422.85, currency="EUR"), message(), REQUEST_DATE)
        self.assertEqual((a[0].kind, a[0].amount, a[0].effective_date), (K.SALARY_AMOUNT, D("1422.85"), date(2026, 3, 28)))

    def test_salary_claim_from_wrong_source_is_rejected(self):
        # e.g. a wallet receipt that also claims "your employer confirmed a salary"
        f = facts("salary_start", amount=1296, currency="USD", effective_date="2026-04-15")
        self.assertEqual(messages.to_amendments(f, message(source=SourceType.FINANCIAL_SERVICE), REQUEST_DATE), [])

    def test_message_after_request_date_is_ignored(self):
        f = facts("income_end")
        self.assertEqual(messages.to_amendments(f, message(sent=date(2026, 4, 5)), REQUEST_DATE), [])

    def test_pending_and_informational_intents_change_nothing(self):
        for intent in ("unconfirmed_income", "refund_pending", "scam_or_solicitation", "investment_value_only"):
            self.assertEqual(messages.to_amendments(facts(intent, amount=500, currency="EUR"), message(), REQUEST_DATE), [])

    def test_confirmed_credit_needs_a_date(self):
        f = facts("confirmed_one_off_credit", amount=196000, currency="INR")
        self.assertEqual(messages.to_amendments(f, message(source=SourceType.SERVICE_PROVIDER), REQUEST_DATE), [])
        f = facts("confirmed_one_off_credit", amount=196000, currency="INR", effective_date="2026-04-15")
        self.assertEqual(kinds(messages.to_amendments(f, message(source=SourceType.SERVICE_PROVIDER), REQUEST_DATE)),
                         [K.CONFIRMED_CREDIT])

    def test_implausible_dates_are_rejected(self):
        f = facts("salary_date_change", effective_date="2031-01-01")
        self.assertEqual(messages.to_amendments(f, message(), REQUEST_DATE), [])

    def test_expense_change_percent(self):
        f = facts("expense_change_percent", percent=12, category="rent")
        [a] = messages.to_amendments(f, message(source=SourceType.SERVICE_PROVIDER), REQUEST_DATE)
        self.assertEqual((a.kind, a.category, a.percent), (K.EXPENSE_CHANGE_PCT, "rent", D("12")))


class ImageAmendmentTest(unittest.TestCase):
    IMAGE = ImageRef("image_02", "user_x", None, "event_9", Path("unused.png"))
    EVENT = event("event_9", REQUEST_DATE, None, currency="INR", status=Status.SCHEDULED)

    def test_valid_amount(self):
        a = images.to_amendment({"amount": 100000, "currency": "INR", "label": "Balance Due", "readable": True},
                                self.IMAGE, self.EVENT)
        self.assertEqual((a.kind, a.event_id, a.amount), (K.EVENT_AMOUNT, "event_9", D("100000")))

    def test_prompt_states_the_payment_date(self):
        # A bill can show "due till 06-Feb" and a higher "due after 06-Feb"; the model needs the date.
        bill = event("event_9", date(2026, 2, 6), None, currency="INR", status=Status.PENDING,
                     settlement=date(2026, 2, 9))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image_05.png"
            path.write_bytes(b"\x89PNG")
            image = ImageRef("image_05", "user_x", None, "event_9", path)
            text = images.user_content(image, bill)[1]["text"]
        self.assertIn("payment date 2026-02-09", text)

    def test_rejects_unreadable_wrong_currency_or_non_positive(self):
        for raw in ({"amount": 5, "currency": "INR", "label": "x", "readable": False},
                    {"amount": 5, "currency": "USD", "label": "x", "readable": True},
                    {"amount": 0, "currency": "INR", "label": "x", "readable": True},
                    None):
            self.assertIsNone(images.to_amendment(raw, self.IMAGE, self.EVENT))


class FakeModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def extract(self, system, content, schema, purpose):
        self.calls += 1
        return self.reply, CallUsage(purpose, "claude-opus-5", 1000, 100)


class ExtractorTest(unittest.TestCase):
    def dataset(self, msgs, image_path=None):
        blank = event("event_9", REQUEST_DATE, None, status=Status.PENDING)
        imgs = {"event_9": ImageRef("image_1", "user_x", None, "event_9", image_path)} if image_path else {}
        return SimpleNamespace(events_by_user={"user_x": [blank]}, images_by_event=imgs,
                               messages_for=lambda req: msgs)

    def test_cache_prevents_a_second_call_and_usage_is_counted(self):
        reply = {"intent": "income_end", "amount": None, "currency": None, "effective_date": None,
                 "percent": None, "category": None}
        model, usage = FakeModel(reply), UsageLog()
        with tempfile.TemporaryDirectory() as tmp:
            ds = self.dataset([message()])
            first = EvidenceExtractor(model, usage, cache_dir=Path(tmp)).amendments_for(ds, request())
            second = EvidenceExtractor(model, usage, cache_dir=Path(tmp)).amendments_for(ds, request())
        self.assertEqual((kinds(first), kinds(second)), ([K.INCOME_END], [K.INCOME_END]))
        self.assertEqual((model.calls, len(usage.calls), usage.cache_hits), (1, 1, 1))

    def test_offline_without_cache_returns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = EvidenceExtractor(None, UsageLog(), cache_dir=Path(tmp)).amendments_for(
                self.dataset([message()]), request())
        self.assertEqual(found, [])

    def test_missing_image_file_is_never_sent(self):
        model = FakeModel({"amount": 1, "currency": "EUR", "label": "x", "readable": True})
        with tempfile.TemporaryDirectory() as tmp:
            ds = self.dataset([], image_path=Path(tmp) / "absent.png")
            self.assertEqual(EvidenceExtractor(model, UsageLog(), cache_dir=Path(tmp)).amendments_for(ds, request()), [])
        self.assertEqual(model.calls, 0)


class UsageReportTest(unittest.TestCase):
    def test_report_totals(self):
        log = UsageLog([CallUsage("message", "claude-opus-5", 1000, 200), CallUsage("image", "claude-opus-5", 3000, 100)])
        report = render_report(log, 250, command="python3 code/main.py")
        self.assertIn("| Anthropic | `claude-opus-5` | 2 | 4,000 | 300 | 4,300 | 0.0275 |", report)
        self.assertIn("Average tokens per request: 17.2", report)


if __name__ == "__main__":
    unittest.main()
