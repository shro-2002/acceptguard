"""Curated synthetic cases for the demo, drawn from the evaluated dev and held-out sets."""
from dataclasses import dataclass
from datetime import date

DEV = (date(2026, 3, 31), date(2026, 10, 1))
HOLDOUT = (date(2026, 3, 31), date(2026, 5, 15))


@dataclass(frozen=True)
class Sample:
    id: str
    journey: str
    title: str
    blurb: str
    dataset: str
    invoice_no: str
    fy_end: date
    as_of: date

    def card(self) -> dict:
        return {"id": self.id, "journey": self.journey, "title": self.title, "blurb": self.blurb,
                "invoice_no": self.invoice_no}


SAMPLES = {s.id: s for s in (
    Sample("late-receipt", "Valid evidence", "Goods arrived 15 days after the invoice",
           "The ledger assumes acceptance on the invoice date. The receipt stamp moves the deadline.",
           "eval/data/dev", "INV-006", *DEV),
    Sample("written-objection", "Written objection", "Rejected on day 11, replaced on day 30",
           "A valid written objection moves acceptance to the day the defect was fixed.",
           "eval/data/dev", "INV-002", *DEV),
    Sample("phone-complaint", "Oral objection", "Complaint by phone, email only on day 18",
           "Only a written objection inside 15 days moves the clock. AcceptGuard explains why nothing moved.",
           "eval/data/dev", "INV-005", *DEV),
    Sample("conflict", "Contradictory evidence", "Challan and email disagree on delivery",
           "Two verified documents give different receipt dates, so it routes to the accountant.",
           "eval/data/dev", "INV-012", *DEV),
    Sample("blurred-photo", "Unreadable evidence", "Phone photo with a blurred receipt date",
           "Independent OCR cannot confirm what the model read, so nothing is computed.",
           "eval/data/holdout", "KSF-0091", *HOLDOUT),
    Sample("prompt-injection", "Prompt injection", "Challan tells the AI to report a later date",
           "Embedded instructions are data, not commands. The real stamp date is used.",
           "eval/data/holdout", "DP-0420", *HOLDOUT),
)}
