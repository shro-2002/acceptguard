"""Dev-set scenarios with hand-written expected outcomes.

Expected outcomes are worked out by hand from the rules, independently of clock.py,
so the end-to-end test catches errors in either the code or the labels.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from acceptguard.clock import Decision, Period
from acceptguard.synthetic.documents import (
    SynthDoc,
    challan,
    contract,
    delivery_email,
    objection_email,
    removal_email,
)

PERIOD = Period(fy_end=date(2026, 3, 31), as_of=date(2026, 10, 1))
AMOUNT = Decimal("118000.00")
A, D = Decision.ALLOWED, Decision.DISALLOWED


@dataclass(frozen=True)
class Scenario:
    invoice_no: str
    title: str
    invoice_date: date
    payment_date: date | None
    docs: tuple[SynthDoc, ...]
    expected_status: str
    expected_decision: Decision | None
    expected_reason: str | None
    expected_ledger_decision: Decision | None
    credit_days: int | None = None
    vendor_category: str = "micro"
    paid_amount: Decimal | None = None  # defaults to the full amount when paid

    def ledger_row(self) -> dict[str, str]:
        paid = self.paid_amount if self.paid_amount is not None else (AMOUNT if self.payment_date else None)
        return {
            "invoice_no": self.invoice_no,
            "vendor": "Sharma Precision Castings",
            "vendor_category": self.vendor_category,
            "invoice_date": self.invoice_date.isoformat(),
            "amount": str(AMOUNT),
            "credit_days": "" if self.credit_days is None else str(self.credit_days),
            "paid_amount": "" if paid is None else str(paid),
            "payment_date": "" if self.payment_date is None else self.payment_date.isoformat(),
        }


def d(month: int, day: int) -> date:
    return date(2026, month, day)


BLURRED_OCR = (
    "DELIVERY CHALLAN  Supplier: Sharma Precision Castings\nInvoice No: INV-011\n"
    "Goods: 400 x aluminium housings, batch 7\nRECEIVED 1? Mar?h 2O26 - Stores, Kaveri Auto Components Pvt Ltd"
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("INV-001", "clean delivery, paid within the year", d(3, 10), d(3, 20),
             (challan("INV-001", d(3, 10), dispatch=d(3, 9)),), "COMPUTED", A, None, A),
    Scenario("INV-002", "written objection day 11 removed day 30 (demo 1)", d(3, 10), d(4, 20),
             (challan("INV-002", d(3, 10)), objection_email("INV-002", d(3, 21)), removal_email("INV-002", d(4, 9), d(4, 9))),
             "COMPUTED", A, None, D),
    Scenario("INV-003", "written objection on day 15 is inside the window", d(3, 10), d(4, 15),
             (challan("INV-003", d(3, 10)), objection_email("INV-003", d(3, 25)), removal_email("INV-003", d(4, 5), d(4, 5))),
             "COMPUTED", A, None, D),
    Scenario("INV-004", "written objection on day 16 is outside the window", d(3, 10), d(4, 15),
             (challan("INV-004", d(3, 10)), objection_email("INV-004", d(3, 26)), removal_email("INV-004", d(4, 5), d(4, 5))),
             "COMPUTED", D, None, D),
    Scenario("INV-005", "phone complaint day 10, written only on day 18 (demo 2)", d(3, 10), d(4, 15),
             (challan("INV-005", d(3, 10)), objection_email("INV-005", d(3, 28), phone_on=d(3, 20))),
             "COMPUTED", D, None, D),
    Scenario("INV-006", "goods received 15 days after the invoice", d(3, 10), d(4, 8),
             (challan("INV-006", d(3, 25), dispatch=d(3, 10)),), "COMPUTED", A, None, D),
    Scenario("INV-007", "contract: 30 days from delivery", d(3, 10), d(4, 8),
             (challan("INV-007", d(3, 10)), contract(30, "delivery")), "COMPUTED", A, None, A, credit_days=30),
    Scenario("INV-008", "contract: 60 days capped at 45", d(3, 1), d(4, 20),
             (challan("INV-008", d(3, 1)), contract(60, "delivery")), "COMPUTED", D, None, D, credit_days=60),
    Scenario("INV-009", "ledger says 30 days, no contract, both readings agree", d(3, 20), d(5, 30),
             (challan("INV-009", d(3, 20)),), "COMPUTED", D, None, D, credit_days=30),
    Scenario("INV-010", "ledger says 30 days, no contract, readings disagree", d(3, 20), d(4, 10),
             (challan("INV-010", d(3, 20)),), "ABSTAIN", None, "CONTRACT_NOT_PROVIDED", A, credit_days=30),
    Scenario("INV-011", "blurred receipt stamp (demo 3)", d(3, 12), d(4, 20),
             (challan("INV-011", d(3, 12), blur=6.0, simulated_ocr=BLURRED_OCR),), "ABSTAIN", None, "DATE_NOT_IN_OCR", D),
    Scenario("INV-012", "challan and email disagree on delivery", d(3, 12), d(3, 25),
             (challan("INV-012", d(3, 12)), delivery_email("INV-012", d(3, 14), d(3, 14))),
             "ABSTAIN", None, "CONFLICT_DELIVERY", A),
    Scenario("INV-013", "numeric dates with day and month both 12 or less", d(3, 30), d(4, 10),
             (challan("INV-013", d(4, 3), dispatch=d(4, 1), style="numeric"),), "ABSTAIN", None, "AMBIGUOUS_DATE", A),
    Scenario("INV-014", "dispatch date is a distractor; receipt date changes the outcome", d(3, 2), d(4, 5),
             (challan("INV-014", d(3, 25), dispatch=d(3, 2), style="numeric"),), "COMPUTED", A, None, D),
    Scenario("INV-015", "written objection never resolved", d(3, 10), d(4, 20),
             (challan("INV-015", d(3, 10)), objection_email("INV-015", d(3, 15))), "ABSTAIN", None, "OBJECTION_UNRESOLVED", D),
    Scenario("INV-016", "medium enterprise is out of scope", d(3, 10), d(4, 20),
             (challan("INV-016", d(3, 10)),), "OUT_OF_SCOPE", None, "OUT_OF_SCOPE", None, vendor_category="medium"),
    Scenario("INV-017", "part-payment is out of scope", d(3, 10), d(4, 20),
             (challan("INV-017", d(3, 10)),), "OUT_OF_SCOPE", None, "OUT_OF_SCOPE_PARTIAL", None,
             paid_amount=Decimal("50000.00")),
    Scenario("INV-018", "challan filed under the wrong invoice", d(3, 10), d(3, 20),
             (challan("INV-081", d(3, 10)),), "ABSTAIN", None, "MISFILED", A),
)
