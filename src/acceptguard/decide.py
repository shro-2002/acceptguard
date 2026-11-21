"""Combine one ledger row with its verified documents into a single outcome for the CA."""
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from acceptguard import interpretations as rules
from acceptguard.clock import Agreement, ClockInput, ClockResult, Decision, Objection, Period, evaluate, ledger_baseline
from acceptguard.ingest import LedgerRow
from acceptguard.models import Abstention
from acceptguard.verify import Checked, VerifiedDate, VerifiedDoc

Status = Literal["COMPUTED", "ABSTAIN", "OUT_OF_SCOPE"]


@dataclass(frozen=True)
class InvoiceOutcome:
    invoice_no: str
    status: Status
    decision: Decision | None
    ledger_decision: Decision | None
    reasons: tuple[Abstention, ...] = ()
    result: ClockResult | None = None
    citations: tuple[tuple[str, str], ...] = ()  # (what, verbatim quote)
    notes: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return None not in (self.decision, self.ledger_decision) and self.decision != self.ledger_decision


def decide(row: LedgerRow, docs: Sequence[VerifiedDoc], period: Period) -> InvoiceOutcome:
    if gate := scope_gate(row):
        status: Status = "OUT_OF_SCOPE" if gate.code.startswith("OUT_OF_SCOPE") else "ABSTAIN"
        return InvoiceOutcome(row.invoice_no, status, None, None, (gate,))
    ledger = ledger_baseline(row.invoice_date, row.credit_days, row.payment_date, period).decision
    evidence = _gather(docs)
    if isinstance(evidence, Abstention):
        return InvoiceOutcome(row.invoice_no, "ABSTAIN", None, ledger, (evidence,))
    clock_input = ClockInput(
        invoice_date=row.invoice_date,
        delivery_date=evidence.delivery,
        objections=evidence.objections,
        agreement=evidence.agreement,
        ledger_credit_days=row.credit_days,
        payment_date=row.payment_date,
    )
    result = evaluate(clock_input, period)
    notes = _raised_notes(docs, evidence.objections) + _late_objection_notes(evidence)
    if isinstance(result, Abstention):
        return InvoiceOutcome(row.invoice_no, "ABSTAIN", None, ledger, (result,), None, evidence.citations, notes)
    return InvoiceOutcome(row.invoice_no, "COMPUTED", result.decision, ledger, (), result, evidence.citations, notes)


def scope_gate(row: LedgerRow) -> Abstention | None:
    category = row.vendor_category
    if category in rules.OUT_OF_SCOPE_CATEGORIES:
        return Abstention("OUT_OF_SCOPE", f"vendor category {category!r} is not micro or small")
    if category not in rules.COMPUTED_CATEGORIES:
        return Abstention("CATEGORY_UNCLEAR", f"vendor category {category!r} needs CA review")
    if (row.payment_date is None) != (row.paid_amount is None):
        return Abstention("LEDGER_INCOMPLETE", "payment_date and paid_amount must be given together")
    if row.paid_amount is not None and row.paid_amount > row.amount:
        return Abstention("LEDGER_INCOMPLETE", "paid_amount exceeds invoice amount")
    if row.paid_amount is not None and row.paid_amount < row.amount:
        return Abstention("OUT_OF_SCOPE_PARTIAL", "part-payments are not handled")
    return None


@dataclass(frozen=True)
class Evidence:
    delivery: date
    objections: tuple[Objection, ...]
    agreement: Agreement | None
    citations: tuple[tuple[str, str], ...]


def _gather(docs: Sequence[VerifiedDoc]) -> Evidence | Abstention:
    """Merge evidence across documents. Any unverifiable or conflicting fact routes to the CA."""
    problems = [problem for doc in docs for problem in doc.problems]
    if problems:
        return problems[0]
    delivery = _one_date((d.delivery for d in docs), missing="NO_DELIVERY_DATE", conflict="CONFLICT_DELIVERY")
    if isinstance(delivery, Abstention):
        return delivery
    removal = _one_date((d.objection_removed for d in docs), missing=None, conflict="CONFLICT_REMOVAL")
    if isinstance(removal, Abstention):
        return removal
    objections = _objections(docs, removal)
    if isinstance(objections, Abstention):
        return objections
    agreement = _agreement(docs)
    if isinstance(agreement, Abstention):
        return agreement
    citations = [("delivery", delivery.quote)]
    citations += [("objection", d.objection_recorded.quote) for d in docs if isinstance(d.objection_recorded, VerifiedDate)]
    citations += [("removal", removal.quote)] if removal else []
    citations += [("credit terms", d.credit.quote) for d in docs if d.credit is not None]
    return Evidence(delivery.value, objections, agreement, tuple(citations))


def _one_date(values: Iterable[Checked], *, missing: str | None, conflict: str) -> VerifiedDate | Abstention | None:
    found: list[VerifiedDate] = []
    for value in values:
        if isinstance(value, Abstention):
            return value
        if value is not None:
            found.append(value)
    distinct = sorted({v.value for v in found})
    if len(distinct) > 1:
        return Abstention(conflict, ", ".join(str(d) for d in distinct))
    if not found:
        return Abstention(missing, "no document states this date") if missing else None
    return found[0]


def _objections(docs: Sequence[VerifiedDoc], removal: VerifiedDate | None) -> tuple[Objection, ...] | Abstention:
    records = set()
    for doc in docs:
        recorded = doc.objection_recorded
        if isinstance(recorded, Abstention):
            return recorded
        if recorded is None:
            continue
        if doc.objection_medium is None:
            return Abstention("OBJECTION_MEDIUM_UNKNOWN", recorded.quote)
        records.add((recorded.value, doc.objection_medium in rules.WRITTEN_MEDIA))
    removed_on = removal.value if removal else None
    return tuple(Objection(day, written, removed_on if written else None) for day, written in sorted(records))


def _agreement(docs: Sequence[VerifiedDoc]) -> Agreement | Abstention | None:
    terms = set()
    for doc in docs:
        if isinstance(doc.credit, Abstention):
            return doc.credit
        if doc.credit is not None:
            terms.add((doc.credit.days, doc.credit.basis))
    if len(terms) > 1:
        return Abstention("CONFLICT_CREDIT", str(sorted(terms)))
    return Agreement(*terms.pop()) if terms else None


def _raised_notes(docs: Sequence[VerifiedDoc], objections: tuple[Objection, ...]) -> tuple[str, ...]:
    """Explain complaints that were raised (often orally) on a different day from any written record."""
    recorded_days = {o.recorded_on for o in objections}
    return tuple(
        f"Complaint first raised {doc.objection_raised.value}: {doc.objection_raised.quote!r}"
        for doc in docs
        if isinstance(doc.objection_raised, VerifiedDate) and doc.objection_raised.value not in recorded_days
    )


def _late_objection_notes(evidence: Evidence) -> tuple[str, ...]:
    """Say why a written objection did not move the clock."""
    window_end = evidence.delivery + timedelta(days=rules.OBJECTION_WINDOW_DAYS)
    return tuple(
        f"Written objection dated {o.recorded_on} is after the objection window closed on {window_end} "
        f"(delivery {evidence.delivery} + {rules.OBJECTION_WINDOW_DAYS} days), so it does not move acceptance."
        for o in evidence.objections
        if o.written and o.recorded_on > window_end
    )
