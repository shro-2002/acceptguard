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

SPOKEN_MEDIA = frozenset({"phone", "in_person"})

# A record that shows an amendment and more than one date needs a person to decide which entry stands.
AMENDMENT_RE = re.compile(r"\b(correction|corrected|amend(?:ed|ment)?|revis(?:ed|ion)|supersed\w*|struck|"
                          r"strike\s*(?:through|off|out)|read\s+as|erratum|in\s+place\s+of|instead\s+of|cancell?ed)\b", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# Year-ful forms come first so the longest reading wins at each position; year-less named dates still count.
DATE_TOKEN_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b"
    r"|\b\d{1,2}([./-])\d{1,2}\1(?:\d{4}|\d{2})\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?[\s.\-/,]*{_MONTH}[\s.\-/,']+\d{{2,4}}\b"
    rf"|\b{_MONTH}\s*\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s*{_MONTH}(?![a-z])"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.I)


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


def contains(needle: str, haystack: str) -> bool:
    """Normalized match that may not start or end mid-token: "1 march" is not inside "21 march"."""
    pattern = rf"(?<!\w){re.escape(normalize(needle))}(?!\w)"
    return re.search(pattern, normalize(haystack)) is not None


def quote_problem(quote: str, source: SourceText) -> Abstention | None:
    if source.text is None:
        return Abstention("OCR_UNAVAILABLE", "image source could not be read independently")
    needle, haystack = normalize(quote), normalize(source.text)
    if source.kind == "image":
        found = fuzz.partial_ratio(needle, haystack) >= OCR_CONTEXT_THRESHOLD
    else:
        found = contains(quote, source.text)
    return None if found else Abstention("QUOTE_NOT_FOUND", quote)


def verify_cited(cited: Cited, source: SourceText) -> Checked:
    parts = (cited.date_text, cited.iso_date, cited.quote)
    if all(part is None for part in parts):
        return None
    if any(part is None for part in parts):
        return Abstention("INCOMPLETE_CITATION", f"date_text, iso_date and quote must all be present: {cited}")
    if not contains(cited.date_text, cited.quote):
        return Abstention("DATE_NOT_IN_QUOTE", f"{cited.date_text!r} not in {cited.quote!r}")
    if problem := quote_problem(cited.quote, source):
        return problem
    if source.kind == "image" and not contains(cited.date_text, source.text):
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


def distinct_dates(text: str) -> set[object]:
    """Every date-like token counts; one that does not parse is keyed by its raw text (fail closed)."""
    found: set[object] = set()
    for match in DATE_TOKEN_RE.finditer(text):
        parsed = parse_date_text(match.group(0), text)
        found.add(parsed if isinstance(parsed, date) else normalize(match.group(0)))
    return found


def amendment_problem(source: SourceText) -> Abstention | None:
    if source.text and AMENDMENT_RE.search(source.text) and len(distinct_dates(source.text)) > 1:
        return Abstention("AMENDED_RECORD", "the document shows an amendment and more than one date; a person must decide which entry stands")
    return None


QUOTED_MARKER_RE = re.compile(r"^\s*(>|-{2,}\s*forwarded message|on .+ wrote:)", re.I | re.M)


def _in_quoted_region(quote: str, text: str) -> bool:
    """Python's own check that a quote sits after a reply/forward marker; the model's 'quoted_text' label is not trusted."""
    marker = QUOTED_MARKER_RE.search(text)
    if marker is None:
        return False
    return contains(quote, text[marker.start():]) and not contains(quote, text[:marker.start()])


def _ref_key(ref: str) -> str:
    return re.sub(r"[\s\-_/]", "", ref).casefold()


def verify_document(doc: DocExtraction, source: SourceText, folder_invoice_no: str) -> VerifiedDoc:
    problems: tuple[Abstention, ...] = ()
    if doc.invoice_ref and _ref_key(doc.invoice_ref) != _ref_key(folder_invoice_no):
        problems = (Abstention("MISFILED", f"document cites {doc.invoice_ref}, filed under {folder_invoice_no}"),)
    if amended := amendment_problem(source):
        problems += (amended,)
    header_dated = source.kind == "email" and doc.objection_location == "top_message"
    recorded = (verify_header_dated if header_dated else verify_cited)(doc.objection_recorded, source)
    # A complaint in the newest message of an email file is a written record [CA-2], whatever medium the model
    # reports: the medium is a model claim, and injected text can steer it. Quoted text keeps the model's medium.
    medium = "email" if header_dated and isinstance(recorded, VerifiedDate) else doc.objection_medium
    raised = verify_cited(doc.objection_raised, source)
    quoted = next((c for c in (recorded, raised) if isinstance(c, VerifiedDate)), None)
    in_quoted_region = source.kind == "email" and quoted is not None and _in_quoted_region(quoted.quote, source.text or "")
    if medium in SPOKEN_MEDIA and quoted is not None and not header_dated and not in_quoted_region:
        # The complaint is quoted from a written document (an export, letter or scan), yet the model calls it oral.
        # Injected text can steer the medium (held-out 3, QX-502), so a person resolves the contradiction.
        problems += (Abstention("MEDIUM_CONFLICT", f"model reports a {medium} complaint for text in a written document: {quoted.quote!r}"),)
    return VerifiedDoc(
        doc_type=doc.doc_type,
        problems=problems,
        delivery=verify_cited(doc.delivery, source),
        objection_raised=raised,
        objection_recorded=recorded,
        objection_removed=verify_cited(doc.objection_removed, source),
        objection_medium=medium,
        credit=verify_credit(doc, source),
    )
