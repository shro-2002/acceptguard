"""Turn one InvoiceRun into the JSON the browser renders: verdict, reasons, per-file evidence, timeline."""
from datetime import date, timedelta

from acceptguard import interpretations as rules
from acceptguard.clock import Period
from acceptguard.models import Abstention, Cited
from acceptguard.pipeline import DocRun, InvoiceRun
from acceptguard.verify import VerifiedCredit, VerifiedDate
from acceptguard.web.explain import ASSUMPTIONS, DECISIONS, reason

FACT_FIELDS = (
    ("delivery", "Delivery / receipt"),
    ("objection_raised", "Complaint first raised"),
    ("objection_recorded", "Complaint record"),
    ("objection_removed", "Complaint resolved"),
)
DISCLAIMER = ("Candidate for chartered-accountant review, not tax advice. Synthetic demo data. "
              "Legal interpretations marked [CA] are unconfirmed.")


def invoice_json(run: InvoiceRun, period: Period) -> dict:
    o, row, result = run.outcome, run.row, run.outcome.result
    return {
        "invoice": {"invoice_no": row.invoice_no, "vendor": row.vendor, "vendor_category": row.vendor_category,
                    "invoice_date": _iso(row.invoice_date), "amount": str(row.amount), "credit_days": row.credit_days,
                    "paid_amount": None if row.paid_amount is None else str(row.paid_amount),
                    "payment_date": _iso(row.payment_date)},
        "period": {"fy_end": _iso(period.fy_end), "as_of": _iso(period.as_of)},
        "status": o.status,
        "decision": o.decision,
        "decision_label": DECISIONS.get(o.decision or "", None),
        "ledger_decision": o.ledger_decision,
        "ledger_label": DECISIONS.get(o.ledger_decision or "", None),
        "changed": o.changed,
        "headline": _headline(run, period),
        "reasons": [reason(r.code, r.detail) for r in o.reasons],
        "result": None if result is None else {
            "acceptance_day": _iso(result.acceptance_day),
            "due_dates": [_iso(d) for d in result.due_dates],
            "assumptions": [{"code": a, "explanation": ASSUMPTIONS.get(a, a)} for a in result.assumptions],
        },
        "citations": [{"what": what, "quote": quote} for what, quote in o.citations],
        "notes": list(o.notes),
        "documents": [_document(doc) for doc in run.docs],
        "timeline": _timeline(run, period),
        "disclaimer": DISCLAIMER,
    }


def _headline(run: InvoiceRun, period: Period) -> str:
    o, r, row = run.outcome, run.outcome.result, run.row
    if o.status == "OUT_OF_SCOPE":
        return "Outside s.43B(h): no deadline computed."
    if o.status == "ABSTAIN" or r is None:
        return "Routed to accountant review: the evidence does not support a conclusion."
    due = " or ".join(f"{d:%d %b %Y}" for d in r.due_dates)
    if o.decision == "PENDING":
        return f"Unpaid, but the MSMED payment deadline ({due}) has not passed as of {period.as_of:%d %b %Y}."
    if row.payment_date is None:
        return f"Unpaid on {period.as_of:%d %b %Y}, after the MSMED deadline of {due}: disallowance candidate."
    if o.decision == "ALLOWED" and row.payment_date <= period.fy_end:
        return f"Paid {row.payment_date:%d %b %Y}, within the financial year: deductible this year."
    if o.decision == "ALLOWED":
        return f"Paid {row.payment_date:%d %b %Y}, on or before the MSMED deadline of {due}: deductible this year."
    return f"Paid {row.payment_date:%d %b %Y}, after year-end and after the MSMED deadline of {due}: disallowance candidate."


def _document(doc: DocRun) -> dict:
    out = {"name": doc.path.name, "error": None, "doc_type": None, "facts": [], "credit": None,
           "objection_medium": None, "invoice_ref": None, "illegible": [], "problems": []}
    if doc.error is not None:
        out["error"] = reason("EXTRACTION_FAILED", doc.error)
        return out
    e, v = doc.extraction, doc.verified
    out.update(doc_type=e.doc_type, objection_medium=e.objection_medium, invoice_ref=e.invoice_ref,
               illegible=list(e.illegible_regions))
    if v is not None:
        out["problems"] = [reason(p.code, p.detail) for p in v.problems]
    for name, label in FACT_FIELDS:
        cited: Cited = getattr(e, name)
        if not (cited.date_text or cited.iso_date or cited.quote):
            continue
        out["facts"].append(_fact(label, cited, None if v is None else getattr(v, name)))
    if e.credit_days is not None or e.credit_quote:
        checked = None if v is None else v.credit
        out["credit"] = {"days": e.credit_days, "basis": e.credit_basis, "quote": e.credit_quote,
                         **_check(checked)}
    return out


def _fact(label: str, cited: Cited, checked: object) -> dict:
    return {"label": label, "date_text": cited.date_text, "model_iso_date": _iso(cited.iso_date), "quote": cited.quote,
            **_check(checked)}


def _check(checked: object) -> dict:
    if isinstance(checked, VerifiedDate):
        return {"verified": True, "value": _iso(checked.value), "source": checked.date_text, "check": None}
    if isinstance(checked, VerifiedCredit):
        return {"verified": True, "value": checked.days, "source": None, "check": None}
    if isinstance(checked, Abstention):
        return {"verified": False, "value": None, "source": None, "check": reason(checked.code, checked.detail)}
    return {"verified": False, "value": None, "source": None, "check": None}


def _timeline(run: InvoiceRun, period: Period) -> list[dict]:
    """Every date the decision rests on, in order. Only verified facts appear; unverified ones never do."""
    row, result = run.row, run.outcome.result
    events: list[tuple[date, str, str]] = [(row.invoice_date, "Invoice date (ledger)", "ledger")]
    deliveries: set[date] = set()
    for doc in run.docs:
        v = doc.verified
        if v is None:
            continue
        for name, label, kind in (("delivery", "Goods received", "delivery"),
                                  ("objection_recorded", "Written complaint" if v.objection_medium in rules.WRITTEN_MEDIA
                                   else "Complaint (not in writing)", "objection"),
                                  ("objection_raised", "Complaint first raised", "note"),
                                  ("objection_removed", "Complaint resolved", "removal")):
            value = getattr(v, name)
            if isinstance(value, VerifiedDate):
                events.append((value.value, f"{label} ({doc.path.name})", kind))
                if name == "delivery":
                    deliveries.add(value.value)
    if len(deliveries) == 1:
        (delivery,) = deliveries
        window = delivery + timedelta(days=rules.OBJECTION_WINDOW_DAYS)
        events.append((window, "15-day written-objection window closes", "window"))
    if result is not None:
        events.append((result.acceptance_day, "Acceptance day (MSMED s.2(b))", "acceptance"))
        for due in result.due_dates:
            events.append((due, "MSMED s.15 payment deadline", "due"))
    events.append((period.fy_end, "Financial year ends", "fy"))
    if row.payment_date is not None:
        events.append((row.payment_date, "Paid (ledger)", "payment"))
    else:
        events.append((period.as_of, "Status date: still unpaid", "asof"))
    unique = sorted(set(events), key=lambda e: (e[0], _ORDER.get(e[2], 9)))
    return [{"date": _iso(day), "label": label, "kind": kind} for day, label, kind in unique]


_ORDER = {"ledger": 0, "delivery": 1, "note": 2, "objection": 3, "removal": 4, "window": 5, "acceptance": 6, "due": 7, "fy": 8, "payment": 9}


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()
