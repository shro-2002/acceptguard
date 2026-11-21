# Label changes

| When | Case | Change | Why |
|---|---|---|---|
| 2026-11-21, before any held-out model run | holdout KSF-0091 | expected_reason DATE_NOT_IN_OCR -> QUOTE_NOT_FOUND | Pre-run oracle check (label extractions + real Tesseract, no model) showed the blurred line fails the quote check before the date check. Both are correct abstentions; label now matches check order. |
