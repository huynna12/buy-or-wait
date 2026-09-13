# Buy or Wait — Plan

Deadline: 6:00 PM IST Sept 13 = **8:30 AM EDT Sept 13**. **Target submit: 7:30 AM EDT.**

Structure and design are documented in `code/README.md`.

---

## Status

### Phase 1 — Data layer ✅ (committed)
- [x] `engine/models.py`, `engine/currency.py`, `engine/recurrence.py`, `data/loader.py`, `main.py --user`

### Phase 2 — Scorer + validator ✅
- [x] `evaluation/scorer.py` — per-field score on the 25 samples, diff table
- [x] `output/validate.py` — contract checks; accepts all 25 organiser sample rows

### Phase 3 — Ledger + forecast ✅
- [x] `engine/amendments.py`, `engine/ledger.py`, `engine/forecast.py`
- [x] Calibrated on samples: cadence spending at min amount, bills at mean, income at min, scheduled salary repeats, no cadence item on request day

### Phase 4 — Plans, spending changes, output ✅ ★ SAFE SUBMIT
- [x] `engine/plans.py`, `engine/spending.py`, `engine/decide.py`, `output/format.py`, `output/explain.py`
- [x] `output.csv` for 250 requests passes the validator
- [ ] **You:** commit + tag `safe-submit`

### Phase 5 — Message interpretation ✅
- [x] `extraction/messages.py` (14 closed intents, sender-type rules, date rules), `extraction/llm.py`, `extraction/evidence.py` (cache)

### Phase 6 — Image extraction ✅
- [x] `extraction/images.py` (blank-amount events only, event description in prompt, currency check)

### Phase 7 — Full run, report, README
- [x] `code/README.md`
- [x] Final full run → `output.csv` + `code/evaluation/usage_report.md` (209 calls, 345,117 tokens, ~$1.93)
- [x] Tolerant cadence detection + payment date in image prompt; type-checker clean except SDK stub in `extraction/llm.py`
- [ ] **You:** review, commit

### Package + submit · by 7:30 AM EDT
- [ ] `code.zip` (no `.env`, no keys), `output.csv`, `log.txt`
- https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

---

## Sample score (25 labelled rows)

status 23 · method 25 · plan 24 · earliest date 23 · spending changes 23 · amount within 1% 5

## Open decisions
- [x] "Possible duplicate card charge": reserved as a pending debit (safer)
- [x] Variable essentials: cadence projection at smallest past amount (best on scorer)

## Known gaps
- request_11 (commission income + dining estimate) and request_21 (spending estimate) still miss
- `amount_safe_to_pay` rarely matches to 1%: depends on exact spending estimate
