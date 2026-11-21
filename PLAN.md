# AcceptGuard plan v2

Status: plan approved in principle; no implementation code yet.
Date rules live in `.claude/rules/legal-logic.md` (authoritative until `interpretations.py` exists).
Extraction and verification rules live in `.claude/rules/extraction.md`; evaluation rules in `.claude/rules/evaluation.md`.

## Changes from v1

| # | v1 problem | v2 fix |
|---|---|---|
| 1 | No contract uploaded meant the strict A+15 rule, inflating "late" results | If the ledger says `credit_days` > 15 and no contract evidence exists, compute the decision at both bounds (A+15 and min(I+credit_days, A+45)). Same decision at both: report it with an assumption label. Different: abstain `CONTRACT_NOT_PROVIDED`. |
| 2 | Fuzzy OCR match (≥90) could pass a misread digit | The exact `date_text` token must appear in the OCR text. Fuzzy matching applies only to the surrounding words. Digits are never fuzzy-matched. |
| 3 | `dayfirst=True` hid DD/MM vs MM/DD errors | Numeric dates with day ≤ 12, month ≤ 12 and day ≠ month are ambiguous. Resolve from another unambiguous date in the same document and format, or abstain `AMBIGUOUS_DATE`. |
| 4 | Email sent dates came from the model | For the top message of an `.eml`, the date comes from the `Date` header via Python, converted to Asia/Kolkata. Model output for that date is ignored. |
| 5 | Held-out set correlated with dev set | Held-out phrasing is written by a different model than the system under test, with different renderer settings. The README states OCR numbers are optimistic and the photographed documents (about 4) are anecdotal. |
| 6 | Cache key missing model and schema | Cache key = sha256(file bytes) + model ID + prompt version + schema version. |
| 7 | Ledger could not show part-payments | Add a `paid_amount` column. `paid_amount` < `amount` gives `OUT_OF_SCOPE_PARTIAL`; a missing or excess value gives `LEDGER_INCOMPLETE`. |
| 8 | 14 hours was optimistic | Re-budgeted to 20 hours plus 2 buffer, with a cut decision at hour 8. |
| 9 | No deadline gate | Hour 0 confirms the Path 02 deadline and deliverables in the Hack2skill portal before any build work. |
| 10 | Pricing claim called unsourced | It was in the verification report (AI Studio pricing page: 3.8 and 3.6 Flash pricing doubles 1 Jan 2027). Re-confirm on the pricing page at hour 0 anyway. |

Decisions taken: Tesseract is in. [CA] defaults stay labelled as interpretations until a CA reviews them.

## Ledger CSV schema

`invoice_no, vendor, vendor_category, invoice_date, amount, credit_days, paid_amount, payment_date`

## Schema change

`DocExtraction` gains `objection_location: "top_message" | "quoted_text" | "attachment" | null`.
For `top_message` in an `.eml`, the objection date comes from the header. Otherwise it goes through the cited-date path.

## Build schedule (20 h + 2 h buffer)

| Hours | Work |
|---|---|
| 0–0.5 | Gate: confirm the Path 02 deadline and deliverables; stop and rescope if the window is too short. Confirm `gemini-3.8-flash` structured output and the pricing page. Scaffold with `uv`. |
| 0.5–3 | `clock.py` with about 18 tests written first (boundaries, bounds case, partial payment, category) |
| 3–4.5 | Date parser: ambiguity rule, no-year rule, `.eml` header with timezone, plus tests |
| 4.5–5.5 | Models, schema, prompt v1 |
| 5.5–7 | Ingest, extraction, cache |
| 7–8 | `verify.py`: exact token in OCR, quote context, conflicts, reason codes, plus tests |
| **8** | **Checkpoint: decide which cuts to take, using the cut list below.** |
| 8–11 | Dev set generator and labels |
| 11–12.5 | CLI and HTML report |
| 12.5–14.5 | Scorer, dev run, at most 2 prompt iterations, then freeze and record the prompt hash |
| 14.5–16.5 | Held-out set (other-model phrasing, about 4 photographed documents), held-out run, 3 uncached repeats |
| 16.5–18 | README with results and caveats |
| 18–20 | 90-second demo recorded from cache |

## Cut list (cut first to last)

1. HTML report, replaced by Markdown and CSV
2. 3 repeat runs, replaced by 1 run with a note
3. Photographed held-out documents
4. Tesseract: images labelled "model-read, not independently verified"
5. Credit-basis handling: contract treated as N days from acceptance only

Never cut: clock tests, exact quote and date-token checks on text sources, abstention, the honest evaluation table.

## Demo cases

1. Written objection on day 11, removed on day 30: disallowance falls to zero.
2. Phone objection on day 10, confirming email on day 18: nothing moves, and the tool explains why.
3. Blurred stamp: the date token is not found in the OCR text, so the tool abstains and routes to the CA.
