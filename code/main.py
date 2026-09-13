"""Entry point.

From the repo root:
    python3 code/main.py                  decide every request  -> output.csv + evaluation/usage_report.md
    python3 code/main.py --samples        decide the 25 samples, then score them
    python3 code/main.py --user user_21   print one user's events and series

Evidence flags:
    --offline   never call the model; use cached extractions only
    --refresh   ignore the cache and re-extract every message and image
"""
import argparse
import csv
import sys
from pathlib import Path

from data.loader import DEFAULT_ROOT, Dataset, build_context
from engine.decide import decide
from engine.recurrence import detect_series
from evaluation.scorer import format_report, load_rows, score
from extraction.evidence import EvidenceExtractor
from extraction.usage import UsageLog, render_report
from output.explain import explain
from output.format import to_row
from output.validate import COLUMNS, validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = Path(__file__).resolve().parent / "evaluation"
SAMPLE_PREDICTIONS = EVALUATION_DIR / "sample_predictions.csv"
USAGE_REPORT = EVALUATION_DIR / "usage_report.md"


def run(ds: Dataset, requests, amendments_for=lambda request: ()) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for request in requests:
        ctx = build_context(ds, request)
        decision = decide(ctx, amendments_for(request))
        row = to_row(decision, explain(decision))
        problems += [f"{request.request_id}: {e}" for e in validate_row(row, ctx)]
        rows.append(row)
    return rows, problems


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def make_extractor(offline: bool, refresh: bool, usage: UsageLog) -> EvidenceExtractor:
    model = None
    if not offline:
        from extraction.llm import AnthropicJsonModel, MissingApiKey  # SDK only needed when calling the model
        try:
            model = AnthropicJsonModel()
        except MissingApiKey as exc:
            raise SystemExit(str(exc)) from None
    return EvidenceExtractor(model, usage, refresh=refresh)


def print_user(ds: Dataset, user_id: str) -> None:
    request = next((r for r in ds.requests + ds.sample_requests if r.user_id == user_id), None)
    if request is None:
        raise SystemExit(f"no request found for {user_id}")

    ctx = build_context(ds, request)
    profile = ctx.profile
    # Series activity is judged on the request date, not the latest event:
    # the latest event can be a future scheduled salary.
    as_of = request.request_date

    print(f"\n=== {user_id} | {request.request_id} on {as_of} | {profile.home_currency} "
          f"| balance {profile.current_available_balance} "
          f"| min {profile.minimum_balance_to_keep} ===\n")

    print(f"{'date':<12} {'event_id':<12} {'description':<32} {'amount':>12} {'cur':<5} {'status':<10}")
    for e in ctx.events:
        amt = "" if e.amount is None else f"{e.amount:,.2f}"
        print(f"{e.event_date} {e.event_id:<12} {e.description[:32]:<32} {amt:>12} {e.currency:<5} {e.status:<10}")

    series = detect_series(ctx.events)
    print(f"\n=== {len(series)} series ===\n")
    for s in series:
        last_amount = s.amounts[-1] if s.amounts else None
        print(f"day {s.day_of_month:>2} | {s.description[:32]:<32} "
              f"| {last_amount} | n={len(s.events)} | last={s.last_event.event_id} | active={s.is_active(as_of)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Buy or Wait? decision agent")
    parser.add_argument("--user", help="print events and detected series for one user")
    parser.add_argument("--samples", action="store_true", help="decide and score sample_requests.csv")
    parser.add_argument("--offline", action="store_true", help="use cached extractions only; no model calls")
    parser.add_argument("--refresh", action="store_true", help="ignore cached extractions and call the model")
    parser.add_argument("--dataset", default=DEFAULT_ROOT, type=Path)
    parser.add_argument("--out", default=REPO_ROOT / "output.csv", type=Path)
    args = parser.parse_args()

    ds = Dataset(args.dataset)

    if args.user:
        print_user(ds, args.user)
        return

    usage = UsageLog()
    extractor = make_extractor(args.offline, args.refresh, usage)
    requests = ds.sample_requests if args.samples else ds.requests
    out = SAMPLE_PREDICTIONS if args.samples else args.out

    rows, problems = run(ds, requests, lambda request: extractor.amendments_for(ds, request))
    write_csv(out, rows)
    print(f"wrote {len(rows)} rows to {out}")
    print(f"model calls: {len(usage.calls)}  cached extractions reused: {usage.cache_hits}")
    for problem in problems:
        print(f"INVALID {problem}", file=sys.stderr)

    if args.samples:
        print(format_report(score(load_rows(args.dataset / "sample_requests.csv"), load_rows(out))))
    else:
        command = "python3 code/main.py" + (" --refresh" if args.refresh else "") + (" --offline" if args.offline else "")
        USAGE_REPORT.write_text(render_report(usage, len(requests), command=command), encoding="utf-8")
        print(f"wrote {USAGE_REPORT}")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
