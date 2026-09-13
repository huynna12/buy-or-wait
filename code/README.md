# Buy or Wait? — financial decision agent

For every request in `dataset/requests.csv` the agent decides whether the user should pay in full,
pay partially, use installments, wait, or not proceed, and writes `output.csv`.

**Design in one sentence:** the decision is computed by a deterministic, fully tested engine; a
language model is used only to read untrusted evidence (messages and document images) into a closed,
validated schema.

## Setup

Python 3.11+.

```bash
pip install -r code/requirements.txt
```

Put the API key in the environment or in `code/.env` (git-ignored, never committed):

```
ANTHROPIC_API_KEY=...
```

## Run

From the repository root:

| Command | What it does |
|---|---|
| `python3 code/main.py` | Decide all 250 requests → `output.csv`, and write `code/evaluation/usage_report.md` |
| `python3 code/main.py --samples` | Decide the 25 labelled samples and print a per-field score (evaluation workflow) |
| `python3 code/main.py --refresh` | Re-extract every message and image instead of using the cache |
| `python3 code/main.py --offline` | Never call the model; use cached extractions only |
| `python3 code/main.py --user user_21` | Debug view: one user's events and detected recurring series |
| `cd code && python3 -m unittest discover -s tests -t .` | Run the test suite (no network) |

Every row is checked against the output contract before `output.csv` is written; the command exits
non-zero if any row is invalid.

Running from an extracted `code.zip` instead of the repository: from the extracted folder, pass the
dataset location, e.g. `python3 main.py --offline --dataset /path/to/dataset --out output.csv`.
`--offline` reproduces the submitted `output.csv` from the bundled extraction cache with no API key.

## Architecture

```
dataset/*.csv, media/images ──► data/loader.py ──► engine models ──────────────┐
                                     │                                          │
messages, images ──► extraction/ (LLM, cached) ──► validated Amendments ──────► engine/decide.py ──► Decision
                                                                                                        │
                                              output/format.py + explain.py + validate.py ◄─────────────┘
                                                                  │
                                                             output.csv
```

- `engine/` is pure: no CSV, no LLM, no file I/O. It owns the domain models. `data/`, `extraction/`
  and `output/` are adapters that import the engine; the engine imports none of them.
- The engine never sees message, image, or request text — only validated `Amendment` objects.

### Engine, per request

1. **Ledger** (`engine/ledger.py`) — dated cash items for the next 90 days.
   `current_available_balance` already contains every settled event, so history is never replayed;
   it is only evidence of what recurs.
   - pending debits are reserved; pending credits, failed, cancelled and unrealized rows are ignored
   - scheduled rows land on their settlement date
   - monthly series (`engine/recurrence.py`: same description, same day of month, ≥3 consecutive
     months, still active) are projected: bills at their mean, income at its lowest amount
   - a scheduled salary with no salary history repeats monthly
   - spending with a dominant interval (e.g. groceries every 10 days) is projected at its smallest
     past amount; a one-off extra purchase on the same day does not hide the habit, and spending with
     no dominant interval (most common gap under 75% of gaps) is not invented
   - amendments from evidence are applied last (new salary amount or payday, salary start or end,
     confirmed one-off credit, percentage bill change, a blank amount filled from an image)
2. **Forecast** (`engine/forecast.py`) — `headroom[d] = balance[d] − minimum_balance_to_keep`.
   - `amount_safe_to_pay = clamp(min(headroom), 0, requested)`: a payment today lowers every later day.
   - `earliest_date_for_full_payment` = first day `D` with `min(headroom[D:]) ≥ requested`: a payment on
     `D` only lowers days after it, and that suffix minimum never decreases, so the first day that
     clears is the earliest. Both are O(90).
3. **Plans** (`engine/plans.py`) — full payment, wait, partial payment, and every installment option,
   filtered by what the user accepts (`max_installment_months` blank ⇒ no installments; an option is
   allowed when its number of payments ≤ the maximum), by the deadline, and by the forecast (every
   payment keeps headroom ≥ 0). Ranking is exactly the spec's: finish by deadline → no spending
   changes → least paid → start earlier → fewer payments → lowest `payment_option_id` (numeric).
4. **Spending changes** (`engine/spending.py`) — searched only when no plan is safe as-is. Legal
   changes: category not protected, flexibility allows the action, and the user listed the category.
   Up to three changes, never stop and reduce the same event; the combination removing the least
   total spending wins.
5. **Output** — amounts formatted as in the samples, explanations from templates (they narrate the
   engine's decision, so they cannot contradict it, and cost nothing).

### Evidence (the only model calls)

- **Messages** (`extraction/messages.py`): the model classifies each message into one of 14 intents and
  copies out amount, currency, date, percentage and category, constrained by a JSON schema. Code then
  decides what it means and rejects: intents from the wrong sender type (a salary claim inside a
  wallet receipt), messages dated after the request, implausible dates, unknown currencies or
  categories. Pending bonuses, refunds, disputes, investment values and scam messages change nothing.
- **Images** (`extraction/images.py`): sent only for events whose amount is blank and whose file exists,
  with the event's description and payment date so the right figure is chosen (a rent receipt's
  *balance due*, a payslip's *net pay*, a bill's amount *after* its due date when paid late). The
  amount must be readable, positive, and in the event's currency.
- Prompt injection: message and image content is wrapped as data, the prompts say never to follow
  instructions in it, the output can only be one of a few schema values, and every value is
  re-validated in code before it can become an `Amendment`.
- Model: `claude-opus-5` at low effort with structured outputs and server-side refusal fallbacks.
  Results are cached in `extraction/cache/` keyed by prompt version and content hash.

## Evaluation

`python3 code/main.py --samples` scores against `dataset/sample_requests.csv` (25 labelled rows):

| Field | Correct |
|---|---:|
| affordability_status | 23 / 25 |
| recommended_payment_method | 25 / 25 |
| payment_plan | 24 / 25 |
| earliest_date_for_full_payment | 23 / 25 |
| spending_changes_needed | 23 / 25 |
| amount_safe_to_pay (within 1%) | 5 / 25 |

Where the spec is silent (how to estimate variable spending, whether a habit falling on the request
day is reserved), rules were chosen by comparing alternatives with this scorer; the labels are never
read at decision time. `amount_safe_to_pay` is the hardest field to match exactly because it depends on
the precise spending estimate; the categorical fields depend mostly on where the balance dips.

Token usage and cost of the full run: `code/evaluation/usage_report.md`.

## Layout

```
code/
  main.py              entry point
  data/loader.py       CSV → models, joins
  engine/              models, currency, recurrence, amendments, ledger, forecast, plans, spending, decide
  extraction/          llm.py (only provider code), messages.py, images.py, evidence.py, usage.py, cache/
  output/              format.py, explain.py, validate.py
  evaluation/          scorer.py, usage_report.md, sample_predictions.csv
  tests/               unit tests per component + end-to-end contract test
```
