# Evaluation method and results

All numbers: synthetic, author-generated documents; real Gemini 3.5 Flash-Lite calls; real Tesseract 5.5.4 OCR; extraction prompt frozen at `extract_v2.md` sha256 `2d9043fdffc0` before any held-out run. Tables are generated from `eval/results/*.json` by `eval/report.py` into [`EVALUATION_TABLES.md`](EVALUATION_TABLES.md).

## Protocol

1. **Dev set** (`eval/data/dev`, 18 invoices, 16 scored): the prompt and code were developed against it. Not evidence of generalisation.
2. **Held-out set 1** (`eval/data/holdout`, 22 invoices, 38 evidence files): written by Claude (a different model from the system under test) after the prompt was frozen, with new suppliers, wording, fonts, tabular layouts, simulated phone photographs (perspective warp, blur, noise), a localised blur over a receipt date, an ink blot over one digit, a WhatsApp export, a forwarded email thread, a UTC email header that falls on the next day in IST, conflicts, a correction, replacement deliveries, a misfiled document, missing evidence, contradictory credit terms, a trader vendor, an unpaid-but-not-yet-due case, and three prompt-injection documents. Labels were derived by hand from the statute rules and committed (`651218d`) before the first model call. A pre-run oracle check (expected extractions plus real OCR, no model) found one check-order label, fixed and logged in [`eval/LABEL_CHANGES.md`](../eval/LABEL_CHANGES.md).
3. Three **uncached** runs per held-out set, each with an empty extraction cache.
4. **Release gate:** zero observed wrong computed conclusions.
5. On failure: preserve the result, find the root cause, apply the smallest justified fix with a regression test, then evaluate on a set the fix never saw.
6. **Held-out set 2** (`eval/data/holdout2`, 18 invoices, 31 evidence files; one out-of-scope row is not scored): written after fixes 1 and 2, committed (`8c52031`, `bd2b3e6`) before its first model run, then run three times uncached.

Scoring verdicts per invoice: `ok`, `FALSE_CONFIDENT` (computed and wrong, or computed when it should have abstained), `unnecessary_abstention` (abstained when the ideal answer is computable), `abstained_other_reason` (abstained, as required, but with a different reason code). Labels state the **ideal** answer, so the cost of any safety rule shows up as unnecessary abstentions rather than being hidden.

## What happened

| Step | Result |
|---|---|
| Held-out 1, run 1 | **Gate failed.** KSF-0093: Gemini returned no facts for an ERP inward-register export, so the delivery conflict disappeared and the plant email alone produced DISALLOWED. Verification checks what the model reports and cannot see what it drops. |
| Fix 1 (`NO_FACTS_EXTRACTED`) | Every uploaded file must contribute at least one cited date or payment term, else the invoice routes to the accountant. Content-independent. |
| Held-out 1, runs 2-3 (with fix 1) | **Gate failed.** DP-0419: a receipt note showed the original date and an initialled correction. Gemini cited the original. Both quotes exist in the source, so every check passed. |
| Fix 2 (`AMENDED_RECORD`) | A document with amendment wording and more than one distinct date routes to the accountant. A wording rule, so it was tested on new amendment phrasings, including one it deliberately does not match. |
| Held-out 2, runs 1-3 (fixes 1-2) | **Gate passed** in all three runs: 0 wrong computed, 8/8 computed correct, 2/2 required abstentions, 7/17 unnecessary abstentions, 0 request failures. AT-317 (amendment wording the rule misses) computed correctly in all three runs. |
| Fix 3 (security review) | The amendment rule failed open on dates it could not parse (no year, two-digit year, ambiguous). It now counts every date-like token. Strictly more conservative; post-hoc rescoring of both held-out sets shows 0 wrong computed in every run. |

Earlier, before the held-out freeze, a security review found that quote matching used plain substrings, so a truncated quote such as `1 March 2026 - Stores` would have verified against `21 March 2026 - Stores`. Matching now requires token boundaries (`e64384a`).

## Measures (see tables for every run)

| Measure | Held-out 1 (original code, 3 runs) | Held-out 2 (untouched, 3 runs) |
|---|---|---|
| Wrong computed conclusions | 1 · 1 · 1 | 0 · 0 · 0 |
| Correct computed | 8/9 · 7/8 · 7/8 | 8/8 · 8/8 · 8/8 |
| Required abstentions met | 8/9 · 9/9 · 9/9 | 2/2 · 2/2 · 2/2 |
| Unnecessary abstentions | 5 · 5 · 5 of 22 | 7 · 7 · 7 of 17 |
| Model request failures | 0 · 0 · 0 | 0 · 0 · 0 |
| Median latency per uncached document | 6.8 · 2.1 · 2.0 s | 2.2 · 1.8 · 1.7 s |
| Max latency per document | 44.8 · 35.7 · 13.6 s | 37.5 · 78.8 · 34.1 s |
| API cost per run (reported tokens) | about $0.04 for 36-37 documents | about $0.03 for 31 documents |

Run-to-run variability: held-out 2 outcomes were identical across the three runs; field-level counts varied slightly (for example, complaint-resolution dates found 2, 1 and 2 times). Held-out 1 differed between runs 1 and 2-3 because fix 1 was applied in between, plus one reason code that changed.

Field-level extraction (summed over three runs) is in the tables. The most common model error was reporting a replacement or repair delivery as the original delivery (`spurious` delivery dates), which the conflict check catches as an abstention.

## Why the unnecessary abstentions happen

- Replacement or repair deliveries reported as deliveries, which creates a delivery conflict (VPW-2210, VPW-2215, KSF-0112, DP-0425, AT-306, AT-307).
- A resolution date the model did not report (AT-305 service report), which trips `NO_FACTS_EXTRACTED`.
- Tesseract misreading a simulated photo (AT-302).
- The rules' own costs: an irrelevant invoice copy (AT-304), correctly worded amendments (AT-316, AT-318, DP-0419).

Fixing the first two needs prompt or schema work, which was out of bounds once the prompt was frozen for evaluation. Any such change needs a new untouched set.

## Limitations

- Small n: 24 computed answers on the untouched set across three runs of 8 invoices. Zero observed errors does not establish production safety.
- Synthetic, clean renders. Simulated photographs, not camera images. Labels by one author. Claude wrote the held-out phrasing, which is different from, but not independent of, human document styles.
- Legal interpretations marked `[CA]` in `interpretations.py` (e.g. day counting, email as writing, payment after year-end within the limit, the trader question) are unreviewed.
- The cost figure uses API-reported token counts at $0.30 / $2.50 per 1M input / output tokens (Gemini API pricing page) and is a lower bound if unreported thinking tokens were billed.
