# AcceptGuard

Evidence-backed MSMED Act s.2(b) acceptance date for s.43B(h) (s.37(2)(g) from tax year 2026-27) review.
Portfolio project. Synthetic data only. A CA reviews every output. Plan: `PLAN.md`.

## Rules

- The LLM only extracts dates and quotes. All legal and date logic is deterministic Python (`clock.py`, `decide.py`).
- Never add `is_written`, `acceptance_date` or `confidence` fields to the extraction schema.
- Every legal interpretation lives in `interpretations.py` with a `[CA]` tag and a one-line citation.
- Abstain rather than guess. Never use model self-reported confidence.
- Model ID is one constant: `gemini-3.5-flash-lite` (switched from 3.8 Flash on 2026-11-21: overloaded, and structured output unconfirmed). Send no `temperature`, `top_p` or `top_k`.
- `.eml` top-message dates come from the `Date` header in Python, never from the model.
- Never commit `.cache/` or any real client document. Output wording: "candidate for review", never advice.
- Write clock tests before `clock.py`. Never tune the prompt on the held-out set.
- Do not start implementation work that `PLAN.md` has not scheduled; scope is capped at about 20 hours.

## Commands

- API key: put `GEMINI_API_KEY=...` in `.env` (gitignored, never read or print it); pass `--env-file .env` to `uv run` for anything that calls Gemini.
- Smoke test: `uv run --env-file .env python scripts/smoke_gemini.py`
- Tests: `uv run pytest`
- Generate dev set: `PYTHONPATH=src uv run python -m acceptguard.synthetic eval/data/dev`
- Eval: `PYTHONPATH=src uv run --env-file .env python eval/score.py eval/data/dev --ocr simulated` (or `--ocr tesseract`); results in `eval/results/`
- Known issue: macOS sets the `hidden` flag on `.venv/.../site-packages/*.pth`, and Python 3.13 skips hidden `.pth` files, so `import acceptguard` fails outside pytest. Prefix commands with `PYTHONPATH=src`, or run `chflags nohidden .venv/lib/python3.13/site-packages/*.pth`.
- Run: `uv run acceptguard ledger.csv evidence/ --fy-end 2026-03-31 --as-of <date>`
