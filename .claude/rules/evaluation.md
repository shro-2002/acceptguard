---
paths:
  - "eval/**"
---

# Evaluation integrity rules (v2)

- Labels come from the generator specification, never from model output.
- Dev set: `eval/data/dev/`. Held-out set: `eval/data/holdout/`, phrasing written by a different model than the system under test, with different renderer settings.
- Freeze the prompt before the first held-out run and record its hash in the results file. Never tune on held-out results.
- Never edit labels after seeing results, except documented label bugs logged in `eval/LABEL_CHANGES.md`.
- Report dev and held-out separately, as counts plus a per-case table. Headline metric: false-confident rate (computed but wrong).
- Also report: decision accuracy on computed invoices, abstention rate, abstention recall, unnecessary abstentions, field-level date exact match with coverage, evidence-changed-outcome count, cost and latency per document, variance over 3 uncached runs.
- Always state: synthetic data, small n, author-generated; OCR numbers are optimistic on clean renders; photographed documents are anecdotal.
