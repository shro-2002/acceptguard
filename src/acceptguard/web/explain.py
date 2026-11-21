"""Plain-English wording for reason codes, assumptions and decisions. Wording only: no logic lives here."""

REASONS: dict[str, tuple[str, str]] = {
    # verification
    "QUOTE_NOT_FOUND": ("Quote not in the source", "Gemini cited a sentence that could not be found word-for-word in the document (or in independent OCR of an image), so the date was not used."),
    "DATE_NOT_IN_QUOTE": ("Date not in its quote", "The cited date does not appear inside the sentence Gemini quoted for it."),
    "DATE_NOT_IN_OCR": ("Date unreadable in OCR", "Independent Tesseract OCR could not read this exact date on the image, so the model's reading cannot be confirmed."),
    "OCR_UNAVAILABLE": ("Image not independently readable", "OCR is unavailable, so a date read from an image cannot be confirmed."),
    "INCOMPLETE_CITATION": ("Incomplete citation", "A date was reported without its exact text, ISO value and quote, so it cannot be checked."),
    "DATE_MISMATCH": ("Model misread a date", "The date as written parses to a different day than Gemini reported."),
    "AMBIGUOUS_DATE": ("Day/month ambiguous", "A numeric date like 04/03/2026 could be 4 March or 3 April, and nothing else in the document settles it."),
    "NO_YEAR": ("Date has no year", "The document gives a day and month but no year."),
    "UNPARSEABLE_DATE": ("Date not recognised", "The date is not in a format the parser accepts."),
    "INVALID_DATE": ("Impossible date", "The written date does not exist on the calendar."),
    "NO_EMAIL_DATE": ("Email has no usable date", "The email's Date header is missing or unreadable."),
    "CREDIT_NOT_IN_QUOTE": ("Credit days not in quote", "The payment period was not written as digits in the quoted clause."),
    "MISFILED": ("Document belongs to another invoice", "A document cites a different invoice number than the one under review."),
    "NO_FACTS_EXTRACTED": ("A document yielded nothing", "An uploaded file produced no date or payment term. Verification can only check what the model reports, so a person must read it before anything is computed."),
    "EXTRACTION_FAILED": ("Gemini unavailable", "The extraction request failed (rate limit, outage, timeout or invalid output). Nothing was computed or guessed."),
    # evidence assembly and clock
    "NO_DELIVERY_DATE": ("No proof of delivery", "No document states when the goods were received, so acceptance cannot be dated."),
    "CONFLICT_DELIVERY": ("Documents disagree on delivery", "Two verified documents give different delivery dates."),
    "CONFLICT_REMOVAL": ("Documents disagree on resolution", "Two verified documents give different dates for fixing the objection."),
    "CONFLICT_CREDIT": ("Conflicting credit terms", "Two documents state different payment terms."),
    "OBJECTION_MEDIUM_UNKNOWN": ("Objection medium unclear", "A complaint record does not say whether it was written or oral."),
    "DATE_ORDER": ("Dates out of order", "An objection precedes delivery, or a fix precedes the objection."),
    "MULTIPLE_OBJECTIONS": ("Several objections", "More than one written objection falls inside the 15-day window."),
    "OBJECTION_UNRESOLVED": ("Objection never resolved", "A valid written objection has no evidence of being resolved, so the acceptance day is unknown."),
    "AGREED_BEFORE_ACCEPTANCE": ("Agreed date before acceptance", "The contract date falls before the acceptance day; the law is unclear here."),
    "CONTRACT_NOT_PROVIDED": ("Contract needed", "The ledger claims credit days but no contract was supplied, and the answer differs between the strict 15-day reading and the ledger's terms."),
    # scope
    "OUT_OF_SCOPE": ("Not a micro or small enterprise", "s.43B(h) covers micro and small enterprises only."),
    "OUT_OF_SCOPE_PARTIAL": ("Part-payment", "Part-payments are not handled by this tool."),
    "CATEGORY_UNCLEAR": ("Vendor category unclear", "Whether traders are covered is unsettled, so the CA decides."),
    "LEDGER_INCOMPLETE": ("Ledger incomplete", "Payment date and amount must be given together and not exceed the invoice."),
}

ASSUMPTIONS = {
    "ASSUMED_NO_WRITTEN_AGREEMENT": "No written payment agreement was supplied, so the MSMED s.15 default applies: pay within 15 days of acceptance.",
    "CONTRACT_NOT_PROVIDED_BOUNDS_AGREE": "No contract was supplied; the strict 15-day reading and the ledger's credit terms give the same answer.",
    "CREDIT_BASIS_ASSUMED_INVOICE": "The contract does not say what the credit days count from; counted from the invoice date [CA-4].",
}

DECISIONS = {
    "ALLOWED": "Deductible this year",
    "DISALLOWED": "s.43B(h) disallowance candidate",
    "PENDING": "Not yet due",
}

FAILURE_KINDS = (
    (("429", "RESOURCE_EXHAUSTED", "quota"), "Gemini rate limit reached. Wait a minute and retry."),
    (("503", "UNAVAILABLE", "overloaded"), "Gemini is temporarily overloaded. Retry shortly."),
    (("timed out", "timeout", "Timeout"), "Gemini did not answer in time. Retry shortly."),
    (("API key", "API_KEY", "PERMISSION_DENIED", "401", "403"), "The server's Gemini credentials were rejected."),
    (("schema validation", "no text"), "Gemini returned output that failed schema validation."),
)


def reason(code: str, detail: str) -> dict:
    title, why = REASONS.get(code, (code.replace("_", " ").title(), "Routed to the CA."))
    if code == "EXTRACTION_FAILED":
        detail = failure_summary(detail)
    return {"code": code, "title": title, "explanation": why, "detail": detail}


def failure_summary(error: str) -> str:
    """Never echo raw provider errors to the browser; classify them."""
    for needles, message in FAILURE_KINDS:
        if any(n in error for n in needles):
            return message
    return "Gemini request failed. Retry shortly."
