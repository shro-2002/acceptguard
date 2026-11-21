"""Check every extracted value against its source before anything downstream may use it."""
import re
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz

from acceptguard.dates import parse_date_text
from acceptguard.ingest import SourceText
from acceptguard.models import Abstention, Cited, DocExtraction

# Fuzzy matching only covers the words around a date in OCR text; the date itself must match exactly.
OCR_CONTEXT_THRESHOLD = 90


@dataclass(frozen=True)
class VerifiedDate:
    value: date
    quote: str
    date_text: str


@dataclass(frozen=True)
class VerifiedCredit:
    days: int
    basis: str
    quote: str


Checked = VerifiedDate | Abstention | None  # None means the document does not state the field


@dataclass(frozen=True)
class VerifiedDoc:
    doc_type: str
    problems: tuple[Abstention, ...]
    delivery: Checked
    objection_raised: Checked
    objection_recorded: Checked
    objection_removed: Checked
    objection_medium: str | None
    credit: VerifiedCredit | Abstention | None


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def quote_problem(quote: str, source: SourceText) -> Abstention | None:
    if source.text is None:
        return Abstention("OCR_UNAVAILABLE", "image source could not be read independently")
    needle, haystack = normalize(quote), normalize(source.text)
    if source.kind == "image":
        found = fuzz.partial_ratio(needle, haystack) >= OCR_CONTEXT_THRESHOLD
    else:
        found = needle in haystack
    return None if found else Abstention("QUOTE_NOT_FOUND", quote)


def verify_cited(cited: Cited, source: SourceText) -> Checked:
    parts = (cited.date_text, cited.iso_date, cited.quote)
    if all(part is None for part in parts):
        return None
    if any(part is None for part in parts):
        return Abstention("INCOMPLETE_CITATION", f"date_text, iso_date and quote must all be present: {cited}")
    if normalize(cited.date_text) not in normalize(cited.quote):
        return Abstention("DATE_NOT_IN_QUOTE", f"{cited.date_text!r} not in {cited.quote!r}")
    if problem := quote_problem(cited.quote, source):
        return problem
    if source.kind == "image" and normalize(cited.date_text) not in normalize(source.text):
        return Abstention("DATE_NOT_IN_OCR", f"{cited.date_text!r} not found exactly in OCR text")
    parsed = parse_date_text(cited.date_text, source.text)
    if isinstance(parsed, Abstention):
        return parsed
    if parsed != cited.iso_date:
        return Abstention("DATE_MISMATCH", f"{cited.date_text!r} parses to {parsed}, model said {cited.iso_date}")
    return VerifiedDate(parsed, cited.quote, cited.date_text)


def verify_header_dated(cited: Cited, source: SourceText) -> Checked:
    """Objection in the newest email message: quote must verify, date comes from the Date header."""
    if cited.quote is None:
        return None if cited.date_text is None and cited.iso_date is None else Abstention("INCOMPLETE_CITATION", str(cited))
    if problem := quote_problem(cited.quote, source):
        return problem
    if isinstance(source.email_date, Abstention):
        return source.email_date
    if source.email_date is None:
        return Abstention("NO_EMAIL_DATE", "objection marked top_message but source is not an email")
    return VerifiedDate(source.email_date, cited.quote, "email Date header")


def verify_credit(doc: DocExtraction, source: SourceText) -> VerifiedCredit | Abstention | None:
    if doc.credit_days is None and doc.credit_quote is None:
        return None
    if doc.credit_days is None or doc.credit_quote is None:
        return Abstention("INCOMPLETE_CITATION", "credit_days and credit_quote must both be present")
    if problem := quote_problem(doc.credit_quote, source):
        return problem
    if not re.search(rf"\b{doc.credit_days}\b", doc.credit_quote):
        return Abstention("CREDIT_NOT_IN_QUOTE", f"{doc.credit_days} not written as digits in {doc.credit_quote!r}")
    return VerifiedCredit(doc.credit_days, doc.credit_basis or "unspecified", doc.credit_quote)


def _ref_key(ref: str) -> str:
    return re.sub(r"[\s\-_/]", "", ref).casefold()


def verify_document(doc: DocExtraction, source: SourceText, folder_invoice_no: str) -> VerifiedDoc:
    problems: tuple[Abstention, ...] = ()
    if doc.invoice_ref and _ref_key(doc.invoice_ref) != _ref_key(folder_invoice_no):
        problems = (Abstention("MISFILED", f"document cites {doc.invoice_ref}, filed under {folder_invoice_no}"),)
    header_dated = source.kind == "email" and doc.objection_location == "top_message"
    recorded = verify_header_dated if header_dated else verify_cited
    return VerifiedDoc(
        doc_type=doc.doc_type,
        problems=problems,
        delivery=verify_cited(doc.delivery, source),
        objection_raised=verify_cited(doc.objection_raised, source),
        objection_recorded=recorded(doc.objection_recorded, source),
        objection_removed=verify_cited(doc.objection_removed, source),
        objection_medium=doc.objection_medium,
        credit=verify_credit(doc, source),
    )
