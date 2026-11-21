from datetime import date

import pytest

from acceptguard.ingest import SourceText
from acceptguard.models import Abstention, Cited, DocExtraction
from acceptguard.verify import VerifiedCredit, VerifiedDate, verify_cited, verify_document

CHALLAN = "DELIVERY CHALLAN DC-118  Dispatch 28/02/2026\nInvoice INV-1\nRECEIVED 02/03/2026, Stores"
TEXT = SourceText("text", CHALLAN)
GOOD = Cited(date_text="02/03/2026", iso_date=date(2026, 3, 2), quote="RECEIVED 02/03/2026, Stores")


def code(result: object) -> str:
    assert isinstance(result, Abstention), result
    return result.code


def test_verified_text_citation():
    assert verify_cited(GOOD, TEXT) == VerifiedDate(date(2026, 3, 2), GOOD.quote, "02/03/2026")


def test_absent_citation_is_none():
    assert verify_cited(Cited(), TEXT) is None


def test_whitespace_and_case_differences_are_tolerated():
    cited = GOOD.model_copy(update={"quote": "received   02/03/2026,  STORES"})
    assert isinstance(verify_cited(cited, TEXT), VerifiedDate)


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        pytest.param({"quote": None}, "INCOMPLETE_CITATION", id="partial citation"),
        pytest.param({"quote": "RECEIVED 03/03/2026, Stores", "date_text": "03/03/2026"}, "QUOTE_NOT_FOUND", id="invented quote"),
        pytest.param({"date_text": "28/02/2026"}, "DATE_NOT_IN_QUOTE", id="date from another line"),
        pytest.param({"iso_date": date(2026, 2, 3)}, "DATE_MISMATCH", id="DD/MM flipped by model"),
    ],
)
def test_text_citation_abstains(update, expected):
    assert code(verify_cited(GOOD.model_copy(update=update), TEXT)) == expected


def test_ambiguous_date_without_context_abstains():
    source = SourceText("text", "RECEIVED 02/03/2026")
    cited = Cited(date_text="02/03/2026", iso_date=date(2026, 3, 2), quote="RECEIVED 02/03/2026")
    assert code(verify_cited(cited, source)) == "AMBIGUOUS_DATE"


def test_ocr_with_noisy_words_but_exact_date_passes():
    ocr = SourceText("image", "DELIVERY CHALLAN 28/02/2026\nRECIEVED 02/03/2026, Stores")
    assert isinstance(verify_cited(GOOD, ocr), VerifiedDate)


def test_ocr_misread_digit_abstains_even_when_words_match():
    ocr = SourceText("image", "DELIVERY CHALLAN 28/02/2026\nRECEIVED 02/08/2026, Stores")
    assert code(verify_cited(GOOD, ocr)) == "DATE_NOT_IN_OCR"


def test_missing_ocr_abstains():
    assert code(verify_cited(GOOD, SourceText("image", None))) == "OCR_UNAVAILABLE"


def extraction(**fields) -> DocExtraction:
    base = {"doc_type": "email", "delivery": {}, "objection_raised": {}, "objection_recorded": {}, "objection_removed": {}}
    return DocExtraction.model_validate(base | fields)


EMAIL_BODY = "Batch 7 of INV-1 has cracked housings. We reject it.\n\nOn 12 Mar 2026, Sharma wrote:\n> Dispatching today."


def test_top_message_objection_uses_email_header_date_not_model_date():
    doc = extraction(
        objection_recorded={"date_text": "12 Mar 2026", "iso_date": "2026-03-12", "quote": "We reject it."},
        objection_medium="email",
        objection_location="top_message",
    )
    source = SourceText("email", EMAIL_BODY, email_date=date(2026, 3, 21))
    result = verify_document(doc, source, "INV-1").objection_recorded
    assert isinstance(result, VerifiedDate)
    assert result.value == date(2026, 3, 21)


def test_top_message_objection_without_header_date_abstains():
    doc = extraction(objection_recorded={"quote": "We reject it."}, objection_location="top_message")
    source = SourceText("email", EMAIL_BODY, email_date=Abstention("NO_EMAIL_DATE", "missing"))
    assert code(verify_document(doc, source, "INV-1").objection_recorded) == "NO_EMAIL_DATE"


def test_misfiled_document_is_flagged():
    doc = extraction(invoice_ref="INV-9")
    assert [p.code for p in verify_document(doc, TEXT, "INV-1").problems] == ["MISFILED"]


def test_invoice_ref_formatting_differences_are_not_misfiled():
    doc = extraction(invoice_ref="inv 1")
    assert verify_document(doc, TEXT, "INV-1").problems == ()


def test_credit_terms_verified():
    source = SourceText("text", "Payment within 30 days of invoice date.")
    doc = extraction(doc_type="contract", credit_days=30, credit_basis="invoice", credit_quote="Payment within 30 days of invoice date.")
    assert verify_document(doc, source, "INV-1").credit == VerifiedCredit(30, "invoice", doc.credit_quote)


def test_credit_days_not_in_quote_abstains():
    source = SourceText("text", "Payment within thirty days of invoice date.")
    doc = extraction(doc_type="contract", credit_days=30, credit_quote="Payment within thirty days of invoice date.")
    assert code(verify_document(doc, source, "INV-1").credit) == "CREDIT_NOT_IN_QUOTE"
