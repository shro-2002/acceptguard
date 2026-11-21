---
paths:
  - "src/acceptguard/clock.py"
  - "src/acceptguard/decide.py"
  - "src/acceptguard/interpretations.py"
  - "tests/test_clock.py"
---

# Date and disallowance rules (v2)

Notation: D delivery or service date, I invoice date, O_w date of the written objection record,
R removal date, A acceptance day, F financial-year end, T as-of date, P payment date.
Every rule marked [CA] is an interpretation that must live in `interpretations.py` with its citation.

## Acceptance day A (MSMED s.2(b) Explanation)

1. A written objection is valid if D ≤ O_w ≤ D+15. [CA-1: General Clauses Act s.9 counting] [CA-2: email/WhatsApp count as writing, IT Act s.4]
2. Valid objection and R ≥ O_w: A = R.
3. Valid objection, no R in evidence: abstain `OBJECTION_UNRESOLVED`.
4. No valid written objection (phone, in person, or written after D+15): A = D.
5. O_w < D or R < O_w: abstain `DATE_ORDER`.
6. More than one objection, or conflicting delivery dates: abstain `MULTIPLE_OBJECTIONS` / `CONFLICT_DELIVERY`.

## Due date (MSMED s.15)

1. Contract evidence, N days from basis B: Agreed = B+N; Due = min(Agreed, A+45).
2. Basis unspecified: B = I, labelled. [CA-4]
3. Agreed < A: abstain `AGREED_BEFORE_ACCEPTANCE`. [CA-5]
4. No contract evidence and ledger `credit_days` blank or ≤ 15: Due = A+15, labelled `ASSUMED_NO_WRITTEN_AGREEMENT`.
5. No contract evidence and ledger `credit_days` > 15: compute the decision with Due = A+15 and with Due = min(I+credit_days, A+45). Same decision: report it, labelled. Different: abstain `CONTRACT_NOT_PROVIDED`.
6. No weekend or holiday shift. [CA-6]

## Disallowance for the year ending F

| Case | Result |
|---|---|
| P ≤ F | Allowed (lateness affects interest only; out of scope) |
| P > F and P ≤ Due | Allowed [CA-3: majority practitioner view] |
| P > F and P > Due | Disallowed this year; allowable in year of payment |
| Unpaid and T > Due | Disallowed |
| Unpaid and T ≤ Due | PENDING |

## Scope gates (checked before any date logic)

- `vendor_category` in {micro, small}: compute. medium or unregistered: `OUT_OF_SCOPE`. trader or blank: `CATEGORY_UNCLEAR`. [CA-7: trader exclusion unsettled]
- `paid_amount` < `amount`: `OUT_OF_SCOPE_PARTIAL`. `payment_date` without `paid_amount`, or `paid_amount` > `amount`: `LEDGER_INCOMPLETE`.

## Ledger baseline (for comparison only)

A = I; Due = I + min(credit_days or 15, 45); same disallowance table.
