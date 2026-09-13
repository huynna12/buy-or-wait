"""CSV adapter: reads dataset/ into engine models.

Messages and images are loaded here but never passed to the engine; only the
validated amendments built from them (Phases 5 and 6) are.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from engine.currency import ExchangeRate, RateTable
from engine.models import (
    Event, Profile, Request, PaymentOption, RequestContext,
    Status, Direction, EventType, Flexibility, PaymentMethod, RequestType,
)

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "dataset"


# ---- evidence models (adapter-only, never seen by the engine) --------

class SourceType(StrEnum):
    EMPLOYER = "employer"
    SERVICE_PROVIDER = "service_provider"
    FINANCIAL_SERVICE = "financial_service"
    BANK = "bank"
    MERCHANT = "merchant"


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime
    source_type: SourceType
    message_text: str  # untrusted


@dataclass(frozen=True)
class ImageRef:
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    path: Path  # may not exist; never invent evidence for a missing file


# ---- parse helpers -------------------------------------------------

def _text(s):   return s.strip() or None
def _money(s):  return Decimal(s.strip()) if s.strip() else None
def _date(s):   return date.fromisoformat(s.strip()) if s.strip() else None
def _int(s):    return int(s.strip()) if s.strip() else None
def _set(s, sep="|"):
    return frozenset(p.strip() for p in s.split(sep) if p.strip())
def _tuple(s, sep="|"):
    return tuple(p.strip() for p in s.split(sep) if p.strip())


def _bool(s):
    # Strict: a typo must fail loudly, not silently become False.
    value = s.strip().lower()
    if value not in ("true", "false"):
        raise ValueError(f"expected true/false, got {s!r}")
    return value == "true"


def _required(parse, s):
    value = parse(s)
    if value is None:
        raise ValueError("required value is blank")
    return value


def _load(path, build):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        # Line 1 is the header, so the first data row is line 2.
        for line, row in enumerate(csv.DictReader(f), start=2):
            try:
                rows.append(build(row))
            except (KeyError, ValueError, ArithmeticError) as exc:
                raise ValueError(f"{path.name}:{line}: {exc!r}") from exc
    return rows


# ---- row builders --------------------------------------------------

def _event(row) -> Event:
    return Event(
        event_id=row["event_id"],
        user_id=row["user_id"],
        event_type=EventType(row["event_type"]),
        description=row["description"].strip(),
        category=row["category"].strip(),
        direction=Direction(row["direction"]),
        amount=_money(row["amount"]),                  # blank = unknown
        currency=row["currency"].strip(),
        event_date=_required(_date, row["event_date"]),
        settlement_date=_date(row["settlement_date"]), # blank only for unrealized
        status=Status(row["status"]),
        linked_event_id=_text(row["linked_event_id"]),
        flexibility=Flexibility(row["flexibility"]),
        minimum_allowed_amount=_money(row["minimum_allowed_amount"]),
    )


def _profile(row) -> Profile:
    return Profile(
        user_id=row["user_id"],
        home_currency=row["home_currency"].strip(),
        current_available_balance=_required(_money, row["current_available_balance"]),
        minimum_balance_to_keep=_required(_money, row["minimum_balance_to_keep"]),
        financial_priorities=_tuple(row["financial_priorities"]),
        protected_categories=_set(row["expense_categories_to_protect"]),
        reducible_categories=_set(row["expense_categories_user_is_willing_to_reduce"]),
        stoppable_categories=_set(row["expense_categories_user_is_willing_to_stop"]),
        payment_methods=frozenset(
            PaymentMethod(m) for m in _tuple(row["payment_methods_user_will_consider"])
        ),
        max_installment_months=_int(row["max_installment_months"]),  # blank = no installments
    )


def _request(row) -> Request:
    # sample_requests.csv has extra output columns; they are ignored here.
    return Request(
        request_id=row["request_id"],
        user_id=row["user_id"],
        request_date=_required(_date, row["request_date"]),
        request_type=RequestType(row["request_type"]),
        requested_amount=_required(_money, row["requested_amount"]),
        desired_completion_date=_required(_date, row["desired_completion_date"]),
        allows_partial_payment=_bool(row["allows_partial_payment"]),
    )


def _option(row) -> PaymentOption:
    return PaymentOption(
        payment_option_id=row["payment_option_id"],
        request_id=row["request_id"],
        method=PaymentMethod(row["payment_method"]),
        payment_amount=_required(_money, row["payment_amount"]),
        number_of_payments=_required(_int, row["number_of_payments"]),
        first_payment_date=_required(_date, row["first_payment_date"]),
        payment_frequency_days=_int(row["payment_frequency_days"]),
        financing_fee=_required(_money, row["financing_fee"]),
        total_payable_amount=_required(_money, row["total_payable_amount"]),
    )


def _rate(row) -> ExchangeRate:
    return ExchangeRate(
        rate_date=_required(_date, row["rate_date"]),
        from_currency=row["from_currency"].strip(),
        to_currency=row["to_currency"].strip(),
        rate=_required(_money, row["rate"]),
    )


def _message(row) -> Message:
    return Message(
        message_id=row["message_id"],
        user_id=row["user_id"],
        request_id=_text(row["request_id"]),
        related_event_id=_text(row["related_event_id"]),
        sent_at=datetime.fromisoformat(row["sent_at"].strip()),
        source_type=SourceType(row["source_type"]),
        message_text=row["message_text"],
    )


def _image(row, root: Path) -> ImageRef:
    return ImageRef(
        image_id=row["image_id"],
        user_id=row["user_id"],
        request_id=_text(row["request_id"]),
        related_event_id=_text(row["related_event_id"]),
        path=root / "media" / "images" / f"{row['image_id']}.png",
    )


class Dataset:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = root
        self.profiles = {p.user_id: p for p in _load(root / "financial_profiles.csv", _profile)}

        self.events_by_user = defaultdict(list)
        for e in _load(root / "financial_events.csv", _event):
            self.events_by_user[e.user_id].append(e)
        for lst in self.events_by_user.values():
            lst.sort(key=lambda e: e.event_date)

        self.requests = _load(root / "requests.csv", _request)
        self.sample_requests = _load(root / "sample_requests.csv", _request)

        self.options_by_request = defaultdict(list)
        for o in _load(root / "request_payment_options.csv", _option):
            self.options_by_request[o.request_id].append(o)

        self.rates = RateTable(_load(root / "exchange_rates.csv", _rate))

        self.messages_by_request = defaultdict(list)
        self.messages_by_user = defaultdict(list)  # user-level only: no request_id
        for m in _load(root / "messages.csv", _message):
            if m.request_id:
                self.messages_by_request[m.request_id].append(m)
            else:
                self.messages_by_user[m.user_id].append(m)

        self.images_by_event = {
            img.related_event_id: img
            for img in _load(root / "images.csv", lambda row: _image(row, root))
            if img.related_event_id
        }

    def messages_for(self, request: Request) -> list[Message]:
        """Request-level plus user-level messages, oldest first (newer wins later)."""
        found = self.messages_by_request.get(request.request_id, []) + \
            self.messages_by_user.get(request.user_id, [])
        return sorted(found, key=lambda m: m.sent_at)


def build_context(ds: Dataset, request: Request) -> RequestContext:
    profile = ds.profiles[request.user_id]          # KeyError is correct here
    events = tuple(ds.events_by_user[request.user_id])
    options = tuple(ds.options_by_request[request.request_id])
    if not options:
        raise ValueError(f"{request.request_id}: no payment options")
    return RequestContext(
        request=request, profile=profile, events=events, options=options, rates=ds.rates,
    )
