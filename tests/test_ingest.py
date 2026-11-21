from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image

from acceptguard.ingest import LedgerError, evidence_files, load_ledger, source_text

HEADER = "invoice_no,vendor,vendor_category,invoice_date,amount,credit_days,paid_amount,payment_date\n"


def test_load_ledger_parses_blanks_as_none(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER + "INV-1,Sharma,Micro,2026-03-02,118000.00,,,\n")
    (row,) = load_ledger(path)
    assert row.vendor_category == "micro"
    assert row.invoice_date == date(2026, 3, 2)
    assert row.amount == Decimal("118000.00")
    assert row.credit_days is None and row.paid_amount is None and row.payment_date is None


def test_load_ledger_rejects_non_iso_dates_with_row_number(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER + "INV-1,Sharma,micro,02/03/2026,1,,,\n")
    with pytest.raises(LedgerError, match="row 2"):
        load_ledger(path)


def test_evidence_files_are_sorted_and_filtered(tmp_path):
    folder = tmp_path / "INV-1"
    folder.mkdir()
    for name in ("b.eml", "a.png", "notes.docx"):
        (folder / name).write_bytes(b"x")
    assert [p.name for p in evidence_files(tmp_path, "INV-1")] == ["a.png", "b.eml"]


def test_email_source_has_body_and_header_date(tmp_path):
    path = tmp_path / "objection.eml"
    path.write_bytes(b"Date: Sat, 21 Mar 2026 10:00:00 +0530\r\nSubject: x\r\n\r\nWe reject batch 7.\r\n")
    source = source_text(path)
    assert source.kind == "email"
    assert "We reject batch 7." in source.text
    assert source.email_date == date(2026, 3, 21)


def test_image_source_uses_injected_ocr(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    path = tmp_path / "challan.png"
    path.write_bytes(buffer.getvalue())
    source = source_text(path, ocr=lambda image: "RECEIVED 02/03/2026")
    assert source.kind == "image"
    assert source.text == "RECEIVED 02/03/2026"


def test_scanned_pdf_is_ocrd_from_embedded_page_image(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="PDF")
    path = tmp_path / "contract.pdf"
    path.write_bytes(buffer.getvalue())
    seen = []
    source = source_text(path, ocr=lambda image: seen.append(image) or "Payment within 30 days")
    assert source.kind == "image"
    assert source.text == "Payment within 30 days"
    assert len(seen) == 1


def test_image_source_without_ocr_has_no_text(tmp_path):
    path = tmp_path / "challan.png"
    path.write_bytes(b"not really a png")
    assert source_text(path, ocr=lambda image: None).text is None


def test_email_view_decodes_quoted_printable_soft_breaks(tmp_path):
    raw = (b"Date: Thu, 09 Apr 2026 10:30:00 +0530\r\nContent-Type: text/plain; charset=utf-8\r\n"
           b"Content-Transfer-Encoding: quoted-printable\r\n\r\naccepted on 9 April =\r\n2026.\r\n")
    path = tmp_path / "removal.eml"
    path.write_bytes(raw)
    text = source_text(path).text
    assert "accepted on 9 April 2026." in text
    assert "Date: Thu, 09 Apr 2026 10:30:00 +0530" in text
