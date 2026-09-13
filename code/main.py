"""Entry point.

From the repo root:  python3 code/main.py --user user_21
From code/:          python3 -m main --user user_21
"""
import argparse
from pathlib import Path

from data.loader import DEFAULT_ROOT, Dataset, build_context
from engine.recurrence import detect_series


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
        amt = s.amounts[-1] if s.amounts else None
        print(f"day {s.day_of_month:>2} | {s.description[:32]:<32} "
              f"| {amt} | n={len(s.events)} | last={s.last_event.event_id} | active={s.is_active(as_of)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Buy or Wait? decision agent")
    parser.add_argument("--user", help="print events and detected series for one user")
    parser.add_argument("--dataset", default=DEFAULT_ROOT, type=Path)
    args = parser.parse_args()

    ds = Dataset(args.dataset)

    if args.user:
        print_user(ds, args.user)
    else:
        # Full run is added in Phase 4; until then, never exit silently.
        parser.print_help()


if __name__ == "__main__":
    main()
