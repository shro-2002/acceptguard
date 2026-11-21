"""Hour-0 smoke test: does the model return schema-valid JSON for an Optional + Literal model?

Run: GEMINI_API_KEY=... uv run python scripts/smoke_gemini.py
"""
import os
import sys
from datetime import date
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

MODEL_ID = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.5-flash-lite"
TIMEOUT_MS = 60_000

SAMPLE = (
    "DELIVERY CHALLAN No. DC-118  Dispatch date: 28/02/2026\n"
    "Received in good condition. Stamp: RECEIVED 02/03/2026, Stores, Sharma Components\n"
)


class Cited(BaseModel):
    date_text: str | None
    iso_date: date | None
    quote: str | None


class Probe(BaseModel):
    doc_type: Literal["challan", "email", "contract", "other"]
    delivery: Cited


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set; export it first.", file=sys.stderr)
        return 1
    client = genai.Client(http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    print(f"Calling {MODEL_ID} (timeout {TIMEOUT_MS // 1000}s)...", flush=True)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=SAMPLE,
        config=types.GenerateContentConfig(
            system_instruction=(
                "Extract the buyer's receipt (delivery) date, not the dispatch date. "
                "date_text and quote must be exact substrings of the input. Return null if absent."
            ),
            response_mime_type="application/json",
            response_schema=Probe,
        ),
    )
    probe = Probe.model_validate_json(response.text)
    print(probe.model_dump_json(indent=2))
    print("usage:", response.usage_metadata)
    ok = probe.delivery.iso_date == date(2026, 3, 2) and probe.delivery.date_text in SAMPLE
    print("PASS" if ok else "FAIL: wrong date or non-verbatim date_text")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
