---
paths:
  - "src/acceptguard/models.py"
  - "src/acceptguard/extract.py"
  - "src/acceptguard/verify.py"
  - "src/acceptguard/ingest.py"
  - "src/acceptguard/prompts/**"
  - "tests/test_verify.py"
---

# Extraction and verification rules (v2)

## Extraction

- One `gemini-3.5-flash-lite` call per document with `response_schema`. No sampling parameters.
- The model returns `date_text` (exact substring), `iso_date` and `quote` (exact sentence) per field, or null. It never infers.
- Delivery date means the buyer's receipt stamp or signature date, never dispatch, invoice, PO or e-way bill dates.
- The model reports `objection_medium` and `objection_location`; Python decides what counts as written.
- Cache key: sha256(file bytes) + model ID + prompt version + schema version. Cache lives in `.cache/` (gitignored).

## Verification (a field is used only if all pass)

1. Text sources (`.txt`, `.eml`, PDF text layer): `quote` found in source after whitespace and case normalisation.
2. Image sources: the exact `date_text` token appears in independent Tesseract OCR text. Fuzzy matching (rapidfuzz partial_ratio ≥ 90) applies only to the rest of the quote. Digits are never fuzzy-matched.
3. `date_text` appears inside `quote`.
4. Date parsing uses an explicit parser, not dateutil defaults:
   - Month-name dates are unambiguous.
   - Numeric dates with day ≤ 12, month ≤ 12 and day ≠ month are ambiguous. Resolve the order from another unambiguous numeric date in the same document with the same separator, else abstain `AMBIGUOUS_DATE`.
   - Two-digit years mean 20YY. No year: abstain `NO_YEAR`.
5. The parsed date must equal the model's `iso_date`, else `DATE_MISMATCH`.
6. `.eml` with `objection_location == "top_message"`: date = `Date` header via `email.utils.parsedate_to_datetime`, converted to Asia/Kolkata. Missing or unparseable header: abstain `NO_EMAIL_DATE`.
7. The document's `invoice_ref`, when present, must match its folder, else `MISFILED`.
