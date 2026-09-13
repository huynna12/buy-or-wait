"""Score predictions against sample_requests.csv, the only labelled data.

Usage (from the repo root):
    python3 code/evaluation/scorer.py sample_predictions.csv

Categorical fields, dates, plans and spending changes must match exactly
(plans and amounts compare as numbers, so "620.4" equals "620.40").
amount_safe_to_pay matches within a small relative tolerance, because the
hidden grader's rounding is unknown. decision_explanation is not scored here.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = (
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
)
AMOUNT_TOLERANCE = Decimal("0.01")  # 1% relative
DEFAULT_EXPECTED = Path(__file__).resolve().parents[2] / "dataset" / "sample_requests.csv"


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        return None


def amount_matches(expected: str, got: str) -> bool:
    e, g = _decimal(expected), _decimal(got)
    if e is None or g is None:
        return False
    return abs(e - g) <= max(Decimal("0.01"), AMOUNT_TOLERANCE * abs(e))


def normalize_plan(text: str) -> tuple | str:
    text = text.strip()
    if text in ("", "none"):
        return "none"
    entries = []
    for part in text.split("|"):
        day, _, amount = part.partition(":")
        entries.append((day.strip(), _decimal(amount)))
    return tuple(entries)


def normalize_changes(text: str) -> frozenset | str:
    text = text.strip()
    if text in ("", "none"):
        return "none"
    normalized: set[tuple] = set()
    for part in text.split("|"):
        pieces = part.strip().split(":")
        if pieces[0] == "reduce_to" and len(pieces) == 3:
            normalized.add(("reduce_to", pieces[1], _decimal(pieces[2])))
        else:
            normalized.add(tuple(pieces))
    return frozenset(normalized)


def field_matches(name: str, expected: str, got: str) -> bool:
    if name == "amount_safe_to_pay":
        return amount_matches(expected, got)
    if name == "payment_plan":
        return normalize_plan(expected) == normalize_plan(got)
    if name == "spending_changes_needed":
        return normalize_changes(expected) == normalize_changes(got)
    return expected.strip() == got.strip()


@dataclass
class Report:
    total: int
    correct: dict[str, int] = field(default_factory=lambda: {f: 0 for f in FIELDS})
    fully_correct: int = 0
    mismatches: list[tuple[str, str, str, str]] = field(default_factory=list)


def score(expected: dict[str, dict[str, str]], predicted: dict[str, dict[str, str]]) -> Report:
    report = Report(total=len(expected))
    for request_id, exp_row in expected.items():
        pred_row = predicted.get(request_id)
        all_ok = True
        for name in FIELDS:
            got = pred_row.get(name, "") if pred_row else "<missing row>"
            if field_matches(name, exp_row[name], got):
                report.correct[name] += 1
            else:
                all_ok = False
                report.mismatches.append((request_id, name, exp_row[name], got))
        report.fully_correct += all_ok
    return report


def load_rows(path: Path) -> dict[str, dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["request_id"]: row for row in csv.DictReader(f)}


def format_report(report: Report) -> str:
    lines = [f"requests: {report.total}   fully correct: {report.fully_correct}"]
    for name in FIELDS:
        lines.append(f"  {name:<32} {report.correct[name]:>3}/{report.total}")
    if report.mismatches:
        lines.append("\nmismatches (request, field, expected, got):")
        for request_id, name, exp, got in report.mismatches:
            lines.append(f"  {request_id:<11} {name:<32} {exp!r:<50} {got!r}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    args = parser.parse_args()
    print(format_report(score(load_rows(args.expected), load_rows(args.predictions))))


if __name__ == "__main__":
    main()
