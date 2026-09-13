"""Token accounting for model calls, and the usage report rendered from it."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

# USD per million tokens (Anthropic first-party list prices).
PRICES = {
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
}
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class CallUsage:
    purpose: str  # "message" | "image"
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> Decimal:
        price_in, price_out = PRICES.get(self.model, (Decimal(0), Decimal(0)))
        return (price_in * self.input_tokens + price_out * self.output_tokens) / MILLION


@dataclass
class UsageLog:
    calls: list[CallUsage] = field(default_factory=list)
    cache_hits: int = 0

    def add(self, call: CallUsage) -> None:
        self.calls.append(call)


def render_report(log: UsageLog, requests: int, *, command: str, provider: str = "Anthropic") -> str:
    by_model: dict[str, list[CallUsage]] = defaultdict(list)
    by_purpose: dict[str, list[CallUsage]] = defaultdict(list)
    for call in log.calls:
        by_model[call.model].append(call)
        by_purpose[call.purpose].append(call)

    def totals(calls):
        inp = sum(c.input_tokens for c in calls)
        out = sum(c.output_tokens for c in calls)
        return len(calls), inp, out, inp + out, sum((c.cost for c in calls), Decimal(0))

    lines = [
        "# Usage Report",
        "",
        f"Run: `{command}` over {requests} requests in `dataset/requests.csv`.",
        "",
        "Only two steps call a model: interpreting messages and reading images for blank amounts. "
        "Every number in `output.csv` is computed deterministically, and explanations are templated, "
        "so model usage scales with the evidence, not with the number of requests.",
        "",
        "## Per model",
        "",
        "| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model, calls in sorted(by_model.items()):
        n, inp, out, tot, cost = totals(calls)
        lines.append(f"| {provider} | `{model}` | {n} | {inp:,} | {out:,} | {tot:,} | {cost:.4f} |")
    n, inp, out, tot, cost = totals(log.calls)
    lines.append(f"| **All** | | **{n}** | **{inp:,}** | **{out:,}** | **{tot:,}** | **{cost:.4f}** |")

    lines += ["", "## Per step", "", "| Step | Calls | Input tokens | Output tokens | Est. cost (USD) |",
              "|---|---:|---:|---:|---:|"]
    for purpose, calls in sorted(by_purpose.items()):
        n_p, inp_p, out_p, _, cost_p = totals(calls)
        lines.append(f"| {purpose} | {n_p} | {inp_p:,} | {out_p:,} | {cost_p:.4f} |")

    per_request_tokens = Decimal(tot) / requests if requests else Decimal(0)
    per_request_cost = cost / requests if requests else Decimal(0)
    lines += [
        "",
        "## Per request",
        "",
        f"- Average tokens per request: {per_request_tokens:,.1f}",
        f"- Average estimated cost per request: ${per_request_cost:.5f}",
        f"- Cached extractions reused (no call made): {log.cache_hits}",
        "",
        "Costs use list prices per million tokens: "
        + ", ".join(f"`{m}` ${p[0]} input / ${p[1]} output" for m, p in PRICES.items()) + ".",
        "",
    ]
    return "\n".join(lines)
